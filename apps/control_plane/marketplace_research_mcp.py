from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import LATEST_PROTOCOL_VERSION

CONTRACT_ID = "kjds-sellersprite-mcp-admission-v1"
CANONICALIZATION_CONTRACT_ID = "kjds-mcp-tool-inventory-c14n-v1"
SECRET_ENV = "KJDS_SELLERSPRITE_MCP_SECRET_KEY"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "marketplace_research_mcp_admission.json"
)
_EXPECTED_ENDPOINT = "https://mcp.sellersprite.com/mcp"
_EXPECTED_HEADER = "secret-key"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SAFE_PROTOCOL_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_CONTROL_ENVELOPE = MappingProxyType(
    {
        "product_write": False,
        "fact_write": False,
        "finance_write": False,
        "approval_write": False,
        "permit_write": False,
        "procurement_write": False,
        "listing_write": False,
        "outreach_write": False,
        "external_write": False,
    }
)


class SellerSpriteMcpContractError(ValueError):
    """Fail-closed MCP contract error carrying only a stable reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class SecretValue:
    value: str = field(repr=False)

    def reveal(self) -> str:
        return self.value

    def __str__(self) -> str:
        return "<redacted>"


class SellerSpriteSecretProvider(Protocol):
    def read(self) -> SecretValue | None: ...


class SellerSpriteMcpSession(Protocol):
    async def initialize(self) -> Any: ...

    async def list_tools(self, cursor: str | None = None) -> Any: ...


class SellerSpriteMcpSessionFactory(Protocol):
    def open(
        self,
        *,
        endpoint: str,
        secret: SecretValue,
        timeout_seconds: float,
    ) -> Any: ...


class EnvironmentSellerSpriteSecretProvider:
    def read(self) -> SecretValue | None:
        raw = os.getenv(SECRET_ENV)
        if raw is None or not raw.strip():
            return None
        if raw != raw.strip():
            raise SellerSpriteMcpContractError("credential_invalid")
        value = raw
        if not 16 <= len(value) <= 512 or any(ord(char) < 32 for char in value):
            raise SellerSpriteMcpContractError("credential_invalid")
        return SecretValue(value)


class _StreamableHttpInventorySessionFactory:
    @asynccontextmanager
    async def open(
        self,
        *,
        endpoint: str,
        secret: SecretValue,
        timeout_seconds: float,
    ) -> AsyncIterator[SellerSpriteMcpSession]:
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(
            headers={_EXPECTED_HEADER: secret.reveal()},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client, streamable_http_client(
            endpoint,
            http_client=client,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _session_id), ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=timeout_seconds),
        ) as session:
            yield session


@dataclass(frozen=True, slots=True)
class McpInventoryProjection:
    status: str
    reason_codes: tuple[str, ...]
    registry_sha256: str
    endpoint_sha256: str
    protocol_version: str | None
    server_identity_sha256: str | None
    inventory_sha256: str | None
    tool_count: int
    tools: tuple[Mapping[str, Any], ...]
    network_invoked: bool
    initialized: bool
    list_pages: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "registry_sha256": self.registry_sha256,
            "endpoint_sha256": self.endpoint_sha256,
            "protocol_version": self.protocol_version,
            "server_identity_sha256": self.server_identity_sha256,
            "inventory_sha256": self.inventory_sha256,
            "tool_count": self.tool_count,
            "tools": [dict(item) for item in self.tools],
            "control_envelope": {
                **_CONTROL_ENVELOPE,
                "network_invoked": self.network_invoked,
                "initialized": self.initialized,
                "list_pages": self.list_pages,
                "tool_calls": 0,
                "model_invoked": False,
                "evidence_created": False,
            },
        }


@dataclass(frozen=True, slots=True)
class _Policy:
    registry_sha256: str
    endpoint: str
    endpoint_sha256: str
    allowed_protocol_versions: tuple[str, ...]
    timeout_seconds: float
    max_inventory_pages: int
    max_inventory_tools: int
    max_inventory_bytes: int
    max_descriptor_bytes: int
    max_json_depth: int


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SellerSpriteMcpContractError("inventory_json_invalid") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact_keys(value: Any, expected: set[str], reason: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise SellerSpriteMcpContractError(reason)
    return value


def _integer(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SellerSpriteMcpContractError(f"registry_{field_name}_invalid")
    return value


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, mode="json", exclude_unset=True)
    if isinstance(value, Mapping):
        return dict(value)
    raise SellerSpriteMcpContractError("provider_projection_invalid")


def _validate_json(value: Any, *, depth: int, maximum_depth: int) -> None:
    if depth > maximum_depth:
        raise SellerSpriteMcpContractError("inventory_depth_exceeded")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SellerSpriteMcpContractError("inventory_json_invalid")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SellerSpriteMcpContractError("inventory_json_invalid")
            _validate_json(item, depth=depth + 1, maximum_depth=maximum_depth)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _validate_json(item, depth=depth + 1, maximum_depth=maximum_depth)
        return
    raise SellerSpriteMcpContractError("inventory_json_invalid")


def _validate_endpoint(value: Any) -> str:
    endpoint = str(value or "").strip()
    parsed = urlparse(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SellerSpriteMcpContractError("registry_endpoint_invalid") from exc
    if (
        endpoint != _EXPECTED_ENDPOINT
        or parsed.scheme != "https"
        or parsed.hostname != "mcp.sellersprite.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/mcp"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise SellerSpriteMcpContractError("registry_endpoint_invalid")
    return endpoint


def _walk_json(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.append((key, item))
            found.extend(_walk_json(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found.extend(_walk_json(item))
    return found


def _load_policy(path: Path) -> _Policy:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SellerSpriteMcpContractError("registry_unavailable") from exc
    root = _exact_keys(
        raw,
        {
            "contract_id",
            "version",
            "as_of",
            "official_sources",
            "official_observations",
            "canonicalization",
            "source",
            "budgets",
            "admission",
            "public_projection",
            "schema_policy",
            "control_envelope",
        },
        "registry_shape_invalid",
    )
    if root["contract_id"] != CONTRACT_ID or type(root["version"]) is not int or root["version"] != 1:
        raise SellerSpriteMcpContractError("registry_contract_invalid")
    if root["as_of"] != "2026-08-08":
        raise SellerSpriteMcpContractError("registry_as_of_invalid")
    canonicalization = _exact_keys(
        root["canonicalization"],
        {"contract_id", "encoding", "object_keys", "tool_order", "hash_algorithm"},
        "registry_canonicalization_invalid",
    )
    if _canonical(canonicalization) != _canonical({
        "contract_id": CANONICALIZATION_CONTRACT_ID,
        "encoding": "utf-8-json-no-nan",
        "object_keys": "lexicographic",
        "tool_order": "name_ascending",
        "hash_algorithm": "sha256",
    }):
        raise SellerSpriteMcpContractError("registry_canonicalization_invalid")
    source = _exact_keys(
        root["source"],
        {
            "source_id",
            "transport",
            "endpoint",
            "credential_env",
            "credential_header",
            "tls_verify",
            "follow_redirects",
            "trust_env",
            "terminate_on_close",
            "allowed_operations",
            "allowed_protocol_versions",
        },
        "registry_source_invalid",
    )
    endpoint = _validate_endpoint(source["endpoint"])
    if _canonical(source) != _canonical({
        "source_id": "sellersprite",
        "transport": "streamable_http",
        "endpoint": endpoint,
        "credential_env": SECRET_ENV,
        "credential_header": _EXPECTED_HEADER,
        "tls_verify": True,
        "follow_redirects": False,
        "trust_env": False,
        "terminate_on_close": False,
        "allowed_operations": [
            "initialize",
            "notifications/initialized",
            "tools/list",
        ],
        "allowed_protocol_versions": ["2025-11-25"],
    }):
        raise SellerSpriteMcpContractError("registry_source_invalid")
    if LATEST_PROTOCOL_VERSION not in source["allowed_protocol_versions"]:
        raise SellerSpriteMcpContractError("registry_protocol_sdk_mismatch")
    budgets = _exact_keys(
        root["budgets"],
        {
            "timeout_seconds",
            "max_inventory_pages",
            "max_inventory_tools",
            "max_inventory_bytes",
            "max_descriptor_bytes",
            "max_json_depth",
        },
        "registry_budgets_invalid",
    )
    timeout = budgets["timeout_seconds"]
    if type(timeout) not in (int, float) or not 1 <= timeout <= 60:
        raise SellerSpriteMcpContractError("registry_timeout_seconds_invalid")
    admission = _exact_keys(
        root["admission"],
        {
            "live_admission",
            "approved_inventory_sha256",
            "approved_server_identity_sha256",
            "license_state",
            "cost_state",
            "rate_limit_state",
            "revocation_state",
            "allowed_tools",
        },
        "registry_admission_invalid",
    )
    if _canonical(admission) != _canonical({
        "live_admission": "not_admitted",
        "approved_inventory_sha256": None,
        "approved_server_identity_sha256": None,
        "license_state": "pending_independent_verification",
        "cost_state": "pending_independent_verification",
        "rate_limit_state": "pending_independent_verification",
        "revocation_state": "pending_independent_verification",
        "allowed_tools": [],
    }):
        raise SellerSpriteMcpContractError("registry_admission_invalid")
    public_projection = root["public_projection"]
    if _canonical(public_projection) != _canonical({
        "tool_fields": [
            "name",
            "descriptor_sha256",
            "input_schema_sha256",
            "output_schema_sha256",
            "annotations_sha256",
        ],
        "raw_description": False,
        "raw_schema": False,
        "raw_server_instructions": False,
        "raw_server_info": False,
    }):
        raise SellerSpriteMcpContractError("registry_public_projection_invalid")
    if _canonical(root["schema_policy"]) != _canonical({
        "draft": "2020-12",
        "schema_uri": "https://json-schema.org/draft/2020-12/schema",
        "input_root_type": "object",
        "output_root_type": "object",
        "local_refs_allowed": False,
        "remote_refs_allowed": False,
    }):
        raise SellerSpriteMcpContractError("registry_schema_policy_invalid")
    if _canonical(root["control_envelope"]) != _canonical(dict(_CONTROL_ENVELOPE)):
        raise SellerSpriteMcpContractError("registry_control_envelope_invalid")
    official_sources = root["official_sources"]
    if official_sources != [
        "https://open.sellersprite.com/mcp",
        "https://open.sellersprite.com/mcp/16",
        "https://open.sellersprite.com/pricing/mcp",
        "https://modelcontextprotocol.io/specification/2025-11-25/basic/transports",
    ]:
        raise SellerSpriteMcpContractError("registry_official_sources_invalid")
    if _canonical(root["official_observations"]) != _canonical({
        "documented_tool_count": 44,
        "documented_site_count": 10,
        "pricing_state": "observed_not_admission_authority",
    }):
        raise SellerSpriteMcpContractError("registry_official_observations_invalid")
    registry_sha256 = _sha256(raw)
    return _Policy(
        registry_sha256=registry_sha256,
        endpoint=endpoint,
        endpoint_sha256=_sha256(endpoint),
        allowed_protocol_versions=tuple(source["allowed_protocol_versions"]),
        timeout_seconds=float(timeout),
        max_inventory_pages=_integer(
            budgets["max_inventory_pages"],
            "max_inventory_pages",
            minimum=1,
            maximum=64,
        ),
        max_inventory_tools=_integer(
            budgets["max_inventory_tools"],
            "max_inventory_tools",
            minimum=1,
            maximum=512,
        ),
        max_inventory_bytes=_integer(
            budgets["max_inventory_bytes"],
            "max_inventory_bytes",
            minimum=1024,
            maximum=8 * 1024 * 1024,
        ),
        max_descriptor_bytes=_integer(
            budgets["max_descriptor_bytes"],
            "max_descriptor_bytes",
            minimum=512,
            maximum=1024 * 1024,
        ),
        max_json_depth=_integer(
            budgets["max_json_depth"],
            "max_json_depth",
            minimum=4,
            maximum=64,
        ),
    )


class SellerSpriteMcpAdmission:
    def __init__(
        self,
        *,
        registry_path: Path | None = None,
        secret_provider: SellerSpriteSecretProvider | None = None,
        session_factory: SellerSpriteMcpSessionFactory | None = None,
    ) -> None:
        self._policy = _load_policy(registry_path or DEFAULT_REGISTRY_PATH)
        self._secret_provider = secret_provider or EnvironmentSellerSpriteSecretProvider()
        self._session_factory = session_factory or _StreamableHttpInventorySessionFactory()

    async def inspect(self) -> McpInventoryProjection:
        try:
            secret = self._secret_provider.read()
        except SellerSpriteMcpContractError as exc:
            return self._closed(exc.reason_code)
        except Exception:
            return self._closed("credential_unavailable")
        if secret is None:
            return self._closed("credential_missing")
        initialized = False
        pages = 0
        try:
            async with self._session_factory.open(
                endpoint=self._policy.endpoint,
                secret=secret,
                timeout_seconds=self._policy.timeout_seconds,
            ) as session:
                initialize_result = _model_dump(await session.initialize())
                protocol_version, server_identity_sha256 = self._server_identity(
                    initialize_result
                )
                initialized = True
                tools, pages = await self._inventory(session)
            return self._review_required(
                protocol_version=protocol_version,
                server_identity_sha256=server_identity_sha256,
                tools=tools,
                pages=pages,
            )
        except SellerSpriteMcpContractError as exc:
            return self._closed(
                exc.reason_code,
                network_invoked=True,
                initialized=initialized,
                list_pages=pages,
            )
        except Exception:
            return self._closed(
                "provider_unavailable",
                network_invoked=True,
                initialized=initialized,
                list_pages=pages,
            )

    def _server_identity(self, value: Mapping[str, Any]) -> tuple[str, str]:
        _validate_json(value, depth=0, maximum_depth=self._policy.max_json_depth)
        if len(_canonical(value)) > self._policy.max_descriptor_bytes:
            raise SellerSpriteMcpContractError("server_identity_too_large")
        if not {"protocolVersion", "capabilities", "serverInfo"}.issubset(value):
            raise SellerSpriteMcpContractError("initialize_result_invalid")
        protocol_version = str(value["protocolVersion"] or "").strip()
        if (
            not _SAFE_PROTOCOL_VERSION.fullmatch(protocol_version)
            or protocol_version not in self._policy.allowed_protocol_versions
        ):
            raise SellerSpriteMcpContractError("protocol_version_invalid")
        if not isinstance(value["capabilities"], Mapping) or not isinstance(
            value["serverInfo"], Mapping
        ):
            raise SellerSpriteMcpContractError("initialize_result_invalid")
        return protocol_version, _sha256(
            {
                "endpoint_sha256": self._policy.endpoint_sha256,
                "initialize_result": value,
                "mcp_sdk_version": importlib.metadata.version("mcp"),
            }
        )

    async def _inventory(
        self,
        session: SellerSpriteMcpSession,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        tools_by_name: dict[str, Mapping[str, Any]] = {}
        total_bytes = 0
        pages = 0
        while True:
            if pages >= self._policy.max_inventory_pages:
                raise SellerSpriteMcpContractError("inventory_page_limit_exceeded")
            result = _model_dump(await session.list_tools(cursor=cursor))
            pages += 1
            _validate_json(
                result,
                depth=0,
                maximum_depth=self._policy.max_json_depth,
            )
            if not set(result).issubset({"tools", "nextCursor", "_meta"}) or "tools" not in result:
                raise SellerSpriteMcpContractError("inventory_page_invalid")
            total_bytes += len(_canonical(result))
            if total_bytes > self._policy.max_inventory_bytes:
                raise SellerSpriteMcpContractError("inventory_too_large")
            page_tools = result["tools"]
            if not isinstance(page_tools, Sequence) or isinstance(
                page_tools, (str, bytes, bytearray)
            ):
                raise SellerSpriteMcpContractError("inventory_page_invalid")
            for raw_tool in page_tools:
                descriptor = _model_dump(raw_tool)
                _validate_json(
                    descriptor,
                    depth=0,
                    maximum_depth=self._policy.max_json_depth,
                )
                encoded = _canonical(descriptor)
                if len(encoded) > self._policy.max_descriptor_bytes:
                    raise SellerSpriteMcpContractError("tool_descriptor_too_large")
                name = descriptor.get("name")
                if not isinstance(name, str) or not _SAFE_TOOL_NAME.fullmatch(name):
                    raise SellerSpriteMcpContractError("tool_name_invalid")
                if name in tools_by_name:
                    raise SellerSpriteMcpContractError("duplicate_tool_name")
                input_schema = descriptor.get("inputSchema")
                output_schema = descriptor.get("outputSchema")
                annotations = descriptor.get("annotations")
                if not isinstance(input_schema, Mapping):
                    raise SellerSpriteMcpContractError("tool_input_schema_invalid")
                if output_schema is not None and not isinstance(output_schema, Mapping):
                    raise SellerSpriteMcpContractError("tool_output_schema_invalid")
                self._validate_schema(input_schema, field_name="input")
                if output_schema is not None:
                    self._validate_schema(output_schema, field_name="output")
                if annotations is not None and not isinstance(annotations, Mapping):
                    raise SellerSpriteMcpContractError("tool_annotations_invalid")
                tools_by_name[name] = MappingProxyType(
                    {
                        "name": name,
                        "descriptor_sha256": hashlib.sha256(encoded).hexdigest(),
                        "input_schema_sha256": _sha256(input_schema),
                        "output_schema_sha256": _sha256(output_schema),
                        "annotations_sha256": _sha256(annotations),
                    }
                )
                if len(tools_by_name) > self._policy.max_inventory_tools:
                    raise SellerSpriteMcpContractError("inventory_tool_limit_exceeded")
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                break
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or len(next_cursor) > 512
                or any(ord(char) < 33 for char in next_cursor)
                or next_cursor in seen_cursors
            ):
                raise SellerSpriteMcpContractError("inventory_cursor_invalid")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        ordered = tuple(tools_by_name[name] for name in sorted(tools_by_name))
        if not ordered:
            raise SellerSpriteMcpContractError("inventory_empty")
        return ordered, pages

    def _validate_schema(self, schema: Mapping[str, Any], *, field_name: str) -> None:
        if schema.get("type") != "object":
            raise SellerSpriteMcpContractError(f"tool_{field_name}_schema_invalid")
        declared_draft = schema.get("$schema")
        if declared_draft not in (
            None,
            "https://json-schema.org/draft/2020-12/schema",
        ):
            raise SellerSpriteMcpContractError(f"tool_{field_name}_schema_invalid")
        for key, _value in _walk_json(schema):
            if key in {"$ref", "$dynamicRef", "$recursiveRef"}:
                raise SellerSpriteMcpContractError("schema_ref_forbidden")
        try:
            Draft202012Validator.check_schema(dict(schema))
        except SchemaError as exc:
            raise SellerSpriteMcpContractError(
                f"tool_{field_name}_schema_invalid"
            ) from exc

    def _review_required(
        self,
        *,
        protocol_version: str,
        server_identity_sha256: str,
        tools: tuple[Mapping[str, Any], ...],
        pages: int,
    ) -> McpInventoryProjection:
        inventory_sha256 = _sha256(
            {
                "canonicalization_contract_id": CANONICALIZATION_CONTRACT_ID,
                "endpoint_sha256": self._policy.endpoint_sha256,
                "protocol_version": protocol_version,
                "registry_sha256": self._policy.registry_sha256,
                "server_identity_sha256": server_identity_sha256,
                "tools": [dict(tool) for tool in tools],
            }
        )
        return McpInventoryProjection(
            status="review_required",
            reason_codes=(
                "inventory_unapproved",
                "server_identity_unapproved",
                "license_unverified",
                "cost_unverified",
                "rate_limit_unverified",
                "revocation_unverified",
            ),
            registry_sha256=self._policy.registry_sha256,
            endpoint_sha256=self._policy.endpoint_sha256,
            protocol_version=protocol_version,
            server_identity_sha256=server_identity_sha256,
            inventory_sha256=inventory_sha256,
            tool_count=len(tools),
            tools=tools,
            network_invoked=True,
            initialized=True,
            list_pages=pages,
        )

    def _closed(
        self,
        reason_code: str,
        *,
        network_invoked: bool = False,
        initialized: bool = False,
        list_pages: int = 0,
    ) -> McpInventoryProjection:
        return McpInventoryProjection(
            status="blocked",
            reason_codes=(reason_code,),
            registry_sha256=self._policy.registry_sha256,
            endpoint_sha256=self._policy.endpoint_sha256,
            protocol_version=None,
            server_identity_sha256=None,
            inventory_sha256=None,
            tool_count=0,
            tools=(),
            network_invoked=network_invoked,
            initialized=initialized,
            list_pages=list_pages,
        )


__all__ = [
    "CONTRACT_ID",
    "DEFAULT_REGISTRY_PATH",
    "SECRET_ENV",
    "EnvironmentSellerSpriteSecretProvider",
    "McpInventoryProjection",
    "SellerSpriteMcpAdmission",
    "SellerSpriteMcpContractError",
    "SecretValue",
]
