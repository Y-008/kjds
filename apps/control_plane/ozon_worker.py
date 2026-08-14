from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack, nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx

from .channel_account_runtime_identity import (
    ManagedCredentialLeaseHandle,
    ResolvedChannelCredentialMaterial,
    SignedManagedCredentialLeaseResolver,
    SignedWorkerCredentialGrant,
    _is_server_bound_worker_resolver,
    require_managed_channel_credential_resolution,
)
from .channel_worker_runtime import build_channel_worker_runtime
from .correlation import correlation_id
from .pilot_readiness import (
    OZON_CATEGORY_READ_CONTRACT_VERSION,
    OZON_FINANCE_READ_CONTRACT_VERSION,
    OZON_PRODUCT_READ_CONTRACT_VERSION,
)

OFFICIAL_OZON_ORIGIN = "https://api-seller.ozon.ru"
PRODUCT_ATTRIBUTES_PATH = "/v4/product/info/attributes"
PLACEHOLDER_VALUES = {"missing", "replace-me", "replace-with-a-key", "changeme"}


def offline_execution_preflight(
    *,
    command_id: str,
    offer_id: str,
    evidence_ids: list[str],
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate one live command locally without constructing a network client."""
    env = os.environ if environment is None else environment
    command = _bounded_required(command_id, "Command id", 300)
    offer = _bounded_required(offer_id, "Offer id", 200)
    evidence = sorted({_bounded_required(value, "Evidence id", 300) for value in evidence_ids})
    if not evidence:
        raise ValueError("At least one Evidence id is required")
    environment_checks = validate_execution_environment(env)
    return {
        "status": "ready_for_explicit_execution",
        "mode": "offline_preflight",
        "network_calls_performed": False,
        "operation": "ozon.product.import.v3",
        "target_count": 1,
        "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
        "offer_sha256": hashlib.sha256(offer.encode()).hexdigest(),
        "evidence_count": len(evidence),
        "evidence_set_sha256": hashlib.sha256("\n".join(evidence).encode()).hexdigest(),
        **environment_checks,
        "explicit_execution_required": True,
    }


def validate_execution_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environment is None else environment
    ozon_url = _safe_url(
        env.get("OZON_API_URL", OFFICIAL_OZON_ORIGIN),
        name="Ozon API URL",
        allowed_hosts={"api-seller.ozon.ru"},
        require_https=True,
    )
    if ozon_url != OFFICIAL_OZON_ORIGIN:
        raise ValueError("Ozon execution must use the official Seller API origin")
    attributes_path = str(env.get("OZON_PRODUCT_ATTRIBUTES_PATH", PRODUCT_ATTRIBUTES_PATH)).strip()
    if attributes_path != PRODUCT_ATTRIBUTES_PATH:
        raise ValueError("Ozon execution must use the fixed v4 product attributes path")
    _safe_url(
        env.get("KJDS_CONTROL_PLANE_URL", "http://127.0.0.1:8000"),
        name="Control plane URL",
        allowed_hosts=None,
        require_https=False,
        allow_http_hosts={"127.0.0.1", "localhost", "::1", "api"},
    )
    expected_identity = _bounded_required(
        str(env.get("KJDS_OZON_EXECUTION_IDENTITY_REF", "")),
        "Ozon execution identity reference",
        120,
    )
    return {
        "ozon_origin_verified": True,
        "attributes_path_verified": True,
        "required_credentials_present": 0,
        "credential_values_read": False,
        "provider_credentials_from_environment": False,
        "execution_identity_sha256": hashlib.sha256(expected_identity.encode()).hexdigest(),
    }


def _bounded_required(value: str, name: str, maximum: int) -> str:
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER_VALUES:
        raise ValueError(f"{name} is required")
    if len(cleaned) > maximum or any(char in cleaned for char in ("\r", "\n", "\0")):
        raise ValueError(f"{name} is invalid")
    return cleaned


def _configured_value(environment: Mapping[str, str], name: str) -> str:
    value = str(environment.get(name, "")).strip()
    if not value or value.lower() in PLACEHOLDER_VALUES:
        raise ValueError(f"{name} must be configured for Ozon execution")
    return value


def _safe_url(
    value: str,
    *,
    name: str,
    allowed_hosts: set[str] | None,
    require_https: bool,
    allow_http_hosts: set[str] | None = None,
) -> str:
    raw = str(value).strip().rstrip("/")
    parsed = urlsplit(raw)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError(f"{name} must be a safe origin without credentials, path, query, or fragment")
    if allowed_hosts is not None and parsed.hostname.lower() not in allowed_hosts:
        raise ValueError(f"{name} host is not allowed")
    if parsed.scheme == "http" and allow_http_hosts is not None and parsed.hostname.lower() not in allow_http_hosts:
        raise ValueError(f"{name} requires HTTPS outside local or Compose networking")
    return raw


class ExecutionCheckpointError(RuntimeError):
    pass


class OzonApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "OZON_API_ERROR",
        status_code: int | None = None,
        retryable: bool = False,
        response_evidence_bytes: bytes | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.response_evidence_bytes = response_evidence_bytes


class OzonCircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= failure_threshold <= 100:
            raise ValueError("Ozon circuit failure threshold must be between 1 and 100")
        if not 0 < cooldown_seconds <= 3600:
            raise ValueError("Ozon circuit cooldown must be between 0 and 3600 seconds")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.failures = 0
        self.state = "closed"
        self.opened_at: float | None = None

    def before_call(self) -> None:
        if self.state == "closed":
            return
        now = self.clock()
        if self.state == "open" and self.opened_at is not None and now - self.opened_at >= self.cooldown_seconds:
            self.state = "half_open"
            return
        raise OzonApiError(
            "Ozon connector circuit is open",
            code="OZON_CIRCUIT_OPEN",
            retryable=True,
        )

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = self.clock()

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "consecutive_failures": self.failures,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }


class ChannelCredentialAuthorizationError(PermissionError):
    """A controlled fail-closed error at the worker credential boundary."""


class OzonCredentials:
    """Opaque value; production credentials only come from the resolver."""

    __slots__ = (
        "_client_id",
        "_api_key",
        "_resolver",
        "_resolved_material",
        "_readback_probe",
        "_sealed",
    )

    def __init__(self, *_args, **_kwargs) -> None:
        raise ChannelCredentialAuthorizationError(
            "OzonCredentials cannot be constructed directly; use an exact-scope managed lease"
        )

    def __setattr__(self, name, value) -> None:
        if getattr(self, "_sealed", False):
            raise ChannelCredentialAuthorizationError("Ozon credential objects are immutable")
        object.__setattr__(self, name, value)

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def api_key(self) -> str:
        return self._api_key

    @classmethod
    def for_test_fixture(
        cls,
        *,
        client_id: str,
        api_key: str,
    ) -> OzonCredentials:
        """Untrusted fixture accepted only with an injected transport."""
        instance = object.__new__(cls)
        instance._client_id = client_id
        instance._api_key = api_key
        instance._resolver = None
        instance._resolved_material = None
        instance._readback_probe = False
        instance._sealed = True
        return instance

    @classmethod
    def for_readback_probe(
        cls,
        *,
        client_id: str,
        api_key: str,
    ) -> OzonCredentials:
        """Explicit one-shot provisioning credential for a bounded official
        readback probe.  It is deliberately NOT runtime-attested, so it can
        never open a provider client through the managed worker factory; the
        only admission is ``OzonSellerClient(readback_probe_allowed=True)``
        for a single read-only identity verification."""
        instance = object.__new__(cls)
        instance._client_id = str(client_id or "").strip()
        instance._api_key = str(api_key or "").strip()
        instance._resolver = None
        instance._resolved_material = None
        instance._readback_probe = True
        instance._sealed = True
        if not instance._client_id or not instance._api_key:
            raise ChannelCredentialAuthorizationError(
                "Readback probe credentials are required"
            )
        return instance

    @classmethod
    def from_environment(cls) -> OzonCredentials:
        raise RuntimeError(
            "Environment-only Ozon credentials cannot authorize a "
            "multi-store worker; an exact-scope managed lease is required"
        )

    @classmethod
    def from_resolved_lease(
        cls,
        *,
        resolver: SignedManagedCredentialLeaseResolver,
        handle: ManagedCredentialLeaseHandle,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        required_capability: str,
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        as_of: datetime,
    ) -> OzonCredentials:
        if not _is_server_bound_worker_resolver(resolver):
            raise ChannelCredentialAuthorizationError(
                "Ozon production admission requires a composition-root "
                "server-bound managed credential resolver"
            )
        material = resolver.resolve(
            handle=handle,
            scope={
                "tenant_ref": tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store_ref,
            },
            platform="ozon",
            account_ref=account_ref,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            required_capability=required_capability,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=(credential_fingerprint_sha256),
            as_of=as_of,
        )
        if not resolver.accepts(material):
            raise ChannelCredentialAuthorizationError("Ozon credential material lacks resolver attestation")
        instance = object.__new__(cls)
        instance._client_id = material.client_id
        instance._api_key = material.api_key
        instance._resolver = resolver
        instance._resolved_material = material
        instance._readback_probe = False
        instance._sealed = True
        return instance

    @classmethod
    def from_resolved_material(
        cls,
        *,
        resolver: SignedManagedCredentialLeaseResolver,
        material: ResolvedChannelCredentialMaterial,
    ) -> OzonCredentials:
        """Build runtime-attested credentials from one already-resolved lease."""
        if not _is_server_bound_worker_resolver(resolver):
            raise ChannelCredentialAuthorizationError(
                "Ozon production admission requires a composition-root "
                "server-bound managed credential resolver"
            )
        if not resolver.accepts(material):
            raise ChannelCredentialAuthorizationError(
                "Ozon credential material lacks resolver attestation"
            )
        instance = object.__new__(cls)
        instance._client_id = material.client_id
        instance._api_key = material.api_key
        instance._resolver = resolver
        instance._resolved_material = material
        instance._readback_probe = False
        instance._sealed = True
        return instance

    def is_runtime_attested(self) -> bool:
        return (
            _is_server_bound_worker_resolver(self._resolver)
            and self._resolved_material is not None
            and self._resolver.accepts(self._resolved_material)
            and self._client_id == self._resolved_material.client_id
            and self._api_key == self._resolved_material.api_key
        )

    def is_test_fixture(self) -> bool:
        return (
            self._resolver is None
            and self._resolved_material is None
            and self._readback_probe is False
        )

    def is_readback_probe(self) -> bool:
        return (
            self._readback_probe is True
            and self._resolver is None
            and self._resolved_material is None
        )


def resolve_ozon_worker_credentials(
    *,
    required_capability: str,
    environment: Mapping[str, str] | None = None,
    as_of: datetime | None = None,
) -> OzonCredentials:
    """Admit lease before reading caller-controlled identity expectations."""

    env = os.environ if environment is None else environment
    resolver, handle = require_managed_channel_credential_resolution()
    if not _is_server_bound_worker_resolver(resolver):
        raise ChannelCredentialAuthorizationError(
            "Ozon production admission requires a composition-root "
            "server-bound managed credential resolver"
        )
    cutoff = as_of or datetime.now(UTC)
    resolver.require_current_handle(handle=handle, as_of=cutoff)
    return OzonCredentials.from_resolved_lease(
        resolver=resolver,
        handle=handle,
        tenant_ref=str(env.get("KJDS_CHANNEL_TENANT_REF", "")),
        entity_ref=str(env.get("KJDS_CHANNEL_ENTITY_REF", "")),
        store_ref=str(env.get("KJDS_CHANNEL_STORE_REF", "")),
        account_ref=str(env.get("KJDS_CHANNEL_ACCOUNT_REF", "")),
        adapter_id=str(env.get("KJDS_CHANNEL_ADAPTER_ID", "")),
        adapter_version=str(env.get("KJDS_CHANNEL_ADAPTER_VERSION", "")),
        required_capability=required_capability,
        secret_reference_sha256=str(
            env.get("KJDS_CHANNEL_SECRET_REFERENCE_SHA256", "")
        ),
        credential_fingerprint_sha256=str(
            env.get("KJDS_CHANNEL_CREDENTIAL_FINGERPRINT_SHA256", "")
        ),
        as_of=cutoff,
    )


class OzonSellerClient:
    PRODUCT_READ_CONTRACT_VERSION = OZON_PRODUCT_READ_CONTRACT_VERSION
    FINANCE_READ_CONTRACT_VERSION = OZON_FINANCE_READ_CONTRACT_VERSION
    CATEGORY_READ_CONTRACT_VERSION = OZON_CATEGORY_READ_CONTRACT_VERSION
    RESPONSE_BUNDLE_SCHEMA_VERSION = "ozon-response-bundle-v2"

    def __init__(
        self,
        credentials: OzonCredentials,
        *,
        base_url: str = "https://api-seller.ozon.ru",
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
        allow_insecure_http: bool = False,
        attributes_path: str = "/v4/product/info/attributes",
        circuit_failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 30,
        readback_probe_allowed: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        normalized = base_url.rstrip("/")
        test_transport = credentials.is_test_fixture() and isinstance(transport, httpx.MockTransport)
        probe_admitted = credentials.is_readback_probe() and readback_probe_allowed
        if not credentials.is_runtime_attested() and not test_transport and not probe_admitted:
            raise ChannelCredentialAuthorizationError(
                "Ozon production client requires a resolver-attested exact-scope credential lease"
            )
        if not allow_insecure_http and not normalized.startswith("https://"):
            raise ValueError("Ozon worker requires HTTPS for Seller API credentials")
        self._client = httpx.Client(
            base_url=normalized,
            headers={
                "Client-Id": credentials.client_id,
                "Api-Key": credentials.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "KJDS-Ozon-Worker/1.0",
            },
            timeout=timeout_seconds,
            transport=transport,
        )
        self._credentials = credentials
        self._test_transport = test_transport
        self._readback_probe_allowed = probe_admitted
        self._attributes_path = attributes_path
        self._breaker = OzonCircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            cooldown_seconds=circuit_cooldown_seconds,
            clock=clock,
        )

    def close(self) -> None:
        self._client.close()

    def offer_state(self, offer_id: str) -> dict[str, Any]:
        offer_id = self._required(offer_id, "offer_id")
        info, info_capture = self._read_with_capture(
            "/v3/product/info/list",
            {"offer_id": [offer_id]},
        )
        self._require_single_offer(
            info,
            keys=("items",),
            path="/v3/product/info/list",
            offer_id=offer_id,
        )
        attributes_body = {
            "filter": {"offer_id": [offer_id], "visibility": "ALL"},
            "limit": 100,
            "sort_dir": "ASC",
        }
        try:
            attributes, attributes_capture = self._read_with_capture(self._attributes_path, attributes_body)
        except OzonApiError as exc:
            if exc.status_code != 404 or self._attributes_path == "/v3/products/info/attributes":
                raise
            attributes, attributes_capture = self._read_with_capture("/v3/products/info/attributes", attributes_body)
        self._require_single_offer(
            attributes,
            keys=("result", "items"),
            path=attributes_capture["path"],
            offer_id=offer_id,
        )
        state = {
            "contract_version": self.PRODUCT_READ_CONTRACT_VERSION,
            "offer_id": offer_id,
            "info": info,
            "attributes": attributes,
        }
        return {
            "contract_version": self.PRODUCT_READ_CONTRACT_VERSION,
            "state": state,
            "state_hash": self.state_hash(state),
            "response_evidence_bytes": self._response_bundle(
                [info_capture, attributes_capture],
                contract_version=self.PRODUCT_READ_CONTRACT_VERSION,
            ),
        }

    def finance_transactions(
        self,
        *,
        date_from: str,
        date_to: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict[str, Any]:
        body = self.finance_request_body(
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
        response, capture = self._read_with_capture(
            "/v3/finance/transaction/list",
            body,
        )
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("operations"), list):
            raise self._schema_error("Ozon finance response is missing result.operations")
        page_count = result.get("page_count")
        if page_count is not None and (
            isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 0
        ):
            raise self._schema_error("Ozon finance response contains an invalid page_count")
        query_window_sha256 = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "contract_version": self.FINANCE_READ_CONTRACT_VERSION,
            "query_window_sha256": query_window_sha256,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "operation_count": len(result["operations"]),
            "response_evidence_bytes": self._response_bundle(
                [capture],
                contract_version=self.FINANCE_READ_CONTRACT_VERSION,
            ),
        }

    def category_tree(self, *, language: str = "RU") -> dict[str, Any]:
        """Read the official Ozon description-category tree (read-only)."""
        language = self._required(language, "language")
        response, capture = self._read_with_capture(
            "/v1/description-category/tree",
            {"language": language},
        )
        result = response.get("result")
        if not isinstance(result, list):
            raise self._schema_error(
                "Ozon category tree response is missing the result list"
            )
        state = {
            "language": language,
            "result": result,
        }
        return {
            "contract_version": self.CATEGORY_READ_CONTRACT_VERSION,
            "state": state,
            "state_hash": self.state_hash(state),
            "response_evidence_bytes": self._response_bundle(
                [capture],
                contract_version=self.CATEGORY_READ_CONTRACT_VERSION,
                request_context={"language": language},
            ),
        }

    def category_attributes(
        self,
        *,
        type_id: int,
        description_category_id: int,
        language: str = "RU",
    ) -> dict[str, Any]:
        """Read the official Ozon attribute contract for one category type (read-only)."""
        language = self._required(language, "language")
        if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id <= 0:
            raise ValueError("type_id must be a positive integer")
        if (
            isinstance(description_category_id, bool)
            or not isinstance(description_category_id, int)
            or description_category_id <= 0
        ):
            raise ValueError("description_category_id must be a positive integer")
        body = {
            "description_category_id": description_category_id,
            "language": language,
            "type_id": type_id,
        }
        response, capture = self._read_with_capture(
            "/v1/description-category/attribute",
            body,
        )
        result = response.get("result")
        if not isinstance(result, list):
            raise self._schema_error(
                "Ozon category attribute response is missing the result list"
            )
        state = {
            "description_category_id": description_category_id,
            "type_id": type_id,
            "language": language,
            "result": result,
        }
        return {
            "contract_version": self.CATEGORY_READ_CONTRACT_VERSION,
            "state": state,
            "state_hash": self.state_hash(state),
            "response_evidence_bytes": self._response_bundle(
                [capture],
                contract_version=self.CATEGORY_READ_CONTRACT_VERSION,
                request_context={
                    "description_category_id": description_category_id,
                    "type_id": type_id,
                    "language": language,
                },
            ),
        }

    def category_attribute_values(
        self,
        *,
        type_id: int,
        description_category_id: int,
        attribute_id: int,
        language: str = "RU",
        limit: int = 500,
        last_value_id: int = 0,
    ) -> dict[str, Any]:
        """Read the official Ozon dictionary values for one attribute (read-only)."""
        language = self._required(language, "language")
        if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id <= 0:
            raise ValueError("type_id must be a positive integer")
        if (
            isinstance(description_category_id, bool)
            or not isinstance(description_category_id, int)
            or description_category_id <= 0
        ):
            raise ValueError("description_category_id must be a positive integer")
        if (
            isinstance(attribute_id, bool)
            or not isinstance(attribute_id, int)
            or attribute_id <= 0
        ):
            raise ValueError("attribute_id must be a positive integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 5000:
            raise ValueError("limit must be an integer between 1 and 5000")
        if isinstance(last_value_id, bool) or not isinstance(last_value_id, int) or last_value_id < 0:
            raise ValueError("last_value_id must be a nonnegative integer")
        body = {
            "description_category_id": description_category_id,
            "type_id": type_id,
            "attribute_id": attribute_id,
            "language": language,
            "limit": limit,
            "last_value_id": last_value_id,
        }
        response, capture = self._read_with_capture(
            "/v1/description-category/attribute/values",
            body,
        )
        result = response.get("result")
        if not isinstance(result, list):
            raise self._schema_error(
                "Ozon attribute values response is missing the result list"
            )
        state = {
            "description_category_id": description_category_id,
            "type_id": type_id,
            "attribute_id": attribute_id,
            "language": language,
            "has_next": bool(response.get("has_next", False)),
            "result": result,
        }
        return {
            "contract_version": self.CATEGORY_READ_CONTRACT_VERSION,
            "state": state,
            "state_hash": self.state_hash(state),
            "response_evidence_bytes": self._response_bundle(
                [capture],
                contract_version=self.CATEGORY_READ_CONTRACT_VERSION,
                request_context={
                    "description_category_id": description_category_id,
                    "type_id": type_id,
                    "attribute_id": attribute_id,
                    "language": language,
                },
            ),
        }

    @classmethod
    def finance_request_body(
        cls,
        *,
        date_from: str,
        date_to: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict[str, Any]:
        start = cls._finance_datetime(date_from, "date_from")
        end = cls._finance_datetime(date_to, "date_to")
        if start >= end:
            raise ValueError("Ozon finance date_from must be before date_to")
        if end - start > timedelta(days=31):
            raise ValueError("Ozon finance query window cannot exceed 31 days")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("Ozon finance page must be a positive integer")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 1000:
            raise ValueError("Ozon finance page_size must be between 1 and 1000")
        return {
            "filter": {
                "date": {
                    "from": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    "to": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                },
                "operation_type": [],
                "posting_number": "",
                "transaction_type": "all",
            },
            "page": page,
            "page_size": page_size,
        }

    def import_product(self, item: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(item, dict) or not item.get("offer_id"):
            raise ValueError("Ozon product import requires a complete item with offer_id")
        response, capture = self._write_with_capture(
            "/v3/product/import",
            {"items": [item]},
        )
        result = response.get("result")
        task_id = result.get("task_id") if isinstance(result, dict) else None
        if task_id is None:
            error = self._schema_error("Ozon product import response did not contain task_id")
            error.response_evidence_bytes = self._response_bundle(
                [capture],
                contract_version="ozon-execution-v1",
            )
            raise error
        return {
            "task_id": str(task_id),
            "response_evidence_bytes": self._response_bundle(
                [capture],
                contract_version="ozon-execution-v1",
            ),
        }

    def import_status(self, task_id: str) -> dict[str, Any]:
        response, capture = self._read_with_capture(
            "/v1/product/import/info",
            {"task_id": task_id},
            error_contract_version="ozon-execution-v1",
            error_request_context={"task_id": task_id},
        )
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise self._schema_error("Ozon import status response is missing result.items")
        return {
            "response": response,
            "response_evidence_bytes": self._response_bundle(
                [capture],
                contract_version="ozon-execution-v1",
                request_context={"task_id": task_id},
            ),
        }

    def wait_for_import(
        self,
        task_id: str,
        *,
        attempts: int = 10,
        interval_seconds: float = 1,
        on_response: Callable[[bytes, int], None] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= attempts <= 60:
            raise ValueError("Ozon import polling attempts must be between 1 and 60")
        last: dict[str, Any] = {}
        for index in range(attempts):
            try:
                status_result = self.import_status(task_id)
            except OzonApiError as exc:
                if exc.response_evidence_bytes is not None and on_response is not None:
                    on_response(exc.response_evidence_bytes, index)
                raise
            last = status_result["response"]
            if on_response is not None:
                on_response(status_result["response_evidence_bytes"], index)
            statuses = self._import_statuses(last)
            if statuses and all(status == "imported" for status in statuses):
                return {"status": "succeeded", "response": last}
            if any(status in {"failed", "error", "declined"} for status in statuses):
                return {"status": "failed", "response": last}
            if index + 1 < attempts:
                time.sleep(interval_seconds)
        return {"status": "uncertain", "response": last}

    def _read(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        value, _ = self._read_with_capture(path, payload)
        return value

    def _read_with_capture(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        error_contract_version: str | None = None,
        error_request_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._require_current_runtime_admission()
        self._breaker.before_call()
        delay = 0.25
        for attempt in range(3):
            self._require_current_runtime_admission()
            try:
                response = self._client.post(path, json=payload)
            except httpx.TransportError as exc:
                if attempt == 2:
                    self._breaker.record_failure()
                    raise OzonApiError(
                        "Ozon read transport failure",
                        code="OZON_READ_TRANSPORT",
                        retryable=True,
                    ) from exc
                time.sleep(delay)
                delay *= 2
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    self._breaker.record_failure()
                    error = self._response_error(response, retryable=True)
                    if error_contract_version:
                        error.response_evidence_bytes = self._response_bundle(
                            [self._capture_response(path, response)],
                            contract_version=error_contract_version,
                            request_context=error_request_context,
                        )
                    raise error
                retry_after = self._retry_after(response, delay)
                time.sleep(retry_after)
                delay = min(delay * 2, 2)
                continue
            self._breaker.record_success()
            capture = self._capture_response(path, response)
            try:
                value = self._json_or_error(response)
            except OzonApiError as exc:
                if error_contract_version:
                    exc.response_evidence_bytes = self._response_bundle(
                        [capture],
                        contract_version=error_contract_version,
                        request_context=error_request_context,
                    )
                raise
            return value, capture
        self._breaker.record_failure()
        raise OzonApiError(
            "Ozon read retry loop exhausted",
            code="OZON_READ_RETRY_EXHAUSTED",
            retryable=True,
        )

    def _write_with_capture(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._require_current_runtime_admission()
        self._breaker.before_call()
        try:
            response = self._client.post(path, json=payload)
        except httpx.TransportError as exc:
            self._breaker.record_failure()
            raise OzonApiError(
                "Ozon write outcome is uncertain after transport failure",
                code="OZON_WRITE_UNCERTAIN",
                retryable=False,
            ) from exc
        capture = self._capture_response(path, response)
        if response.status_code == 429 or response.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        try:
            value = self._json_or_error(response)
        except OzonApiError as exc:
            raise OzonApiError(
                str(exc),
                code=exc.code,
                status_code=exc.status_code,
                retryable=exc.retryable,
                response_evidence_bytes=self._response_bundle(
                    [capture],
                    contract_version="ozon-execution-v1",
                ),
            ) from exc
        return value, capture

    def _require_current_runtime_admission(self) -> None:
        if self._test_transport:
            return
        if self._credentials.is_readback_probe() and self._readback_probe_allowed:
            return
        if not self._credentials.is_runtime_attested():
            raise ChannelCredentialAuthorizationError(
                "Ozon managed credential lease is no longer current"
            )

    def _json_or_error(self, response: httpx.Response) -> dict[str, Any]:
        if not response.is_success:
            raise self._response_error(
                response,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            value = response.json()
        except ValueError as exc:
            self._breaker.record_failure()
            raise OzonApiError(
                "Ozon API returned non-JSON response",
                code="OZON_NON_JSON_RESPONSE",
            ) from exc
        if not isinstance(value, dict):
            raise self._schema_error("Ozon API returned an unexpected response shape")
        return value

    @staticmethod
    def _response_error(response: httpx.Response, *, retryable: bool) -> OzonApiError:
        request_id = response.headers.get("x-o3-trace-id") or response.headers.get("x-request-id")
        suffix = f" request_id={request_id}" if request_id else ""
        return OzonApiError(
            f"Ozon API returned HTTP {response.status_code}.{suffix}",
            code=f"OZON_HTTP_{response.status_code}",
            status_code=response.status_code,
            retryable=retryable,
        )

    @staticmethod
    def _retry_after(response: httpx.Response, fallback: float) -> float:
        try:
            return min(max(float(response.headers.get("Retry-After", fallback)), 0), 2)
        except ValueError:
            return fallback

    @staticmethod
    def _import_statuses(response: dict[str, Any]) -> list[str]:
        result = response.get("result")
        items = result.get("items", []) if isinstance(result, dict) else []
        return [str(item.get("status", "")).casefold() for item in items if isinstance(item, dict)]

    @staticmethod
    def state_hash(state: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    def circuit_status(self) -> dict[str, Any]:
        return self._breaker.snapshot()

    def _schema_error(self, message: str) -> OzonApiError:
        self._breaker.record_failure()
        return OzonApiError(message, code="OZON_SCHEMA_DRIFT", retryable=False)

    def _require_single_offer(
        self,
        value: dict[str, Any],
        *,
        keys: tuple[str, ...],
        path: str,
        offer_id: str,
    ) -> None:
        items = next(
            (value.get(key) for key in keys if isinstance(value.get(key), list)),
            None,
        )
        if items is None:
            joined = " or ".join(keys)
            raise self._schema_error(f"Ozon response schema drift at {path}: missing {joined} list")
        if not items:
            raise OzonApiError(
                "Ozon product read did not return the requested target",
                code="OZON_TARGET_NOT_FOUND",
            )
        if len(items) != 1:
            raise OzonApiError(
                "Ozon product read returned an ambiguous target set",
                code="OZON_TARGET_AMBIGUOUS",
            )
        item = items[0]
        if not isinstance(item, dict) or not str(item.get("offer_id", "")).strip():
            raise self._schema_error(f"Ozon response schema drift at {path}: item is missing offer_id")
        if str(item["offer_id"]).strip() != offer_id:
            raise OzonApiError(
                "Ozon product read returned a different target",
                code="OZON_TARGET_MISMATCH",
            )

    @staticmethod
    def _capture_response(path: str, response: httpx.Response) -> dict[str, Any]:
        safe_headers = {}
        for name in ("content-type", "x-o3-trace-id", "x-request-id"):
            if value := response.headers.get(name):
                safe_headers[name] = value[:500]
        body = response.content
        return {
            "path": path,
            "status_code": response.status_code,
            "headers": safe_headers,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_base64": base64.b64encode(body).decode("ascii"),
        }

    @classmethod
    def _response_bundle(
        cls,
        responses: list[dict[str, Any]],
        *,
        contract_version: str,
        request_context: dict[str, Any] | None = None,
    ) -> bytes:
        return json.dumps(
            {
                "schema_version": cls.RESPONSE_BUNDLE_SCHEMA_VERSION,
                "contract_version": contract_version,
                "responses": responses,
                **({"request_context": request_context} if request_context else {}),
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def _finance_datetime(value: str, name: str) -> datetime:
        cleaned = str(value).strip()
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Ozon finance {name} must be an ISO-8601 datetime") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"Ozon finance {name} must include a timezone")
        return parsed

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned


class ControlPlaneExecutorClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Executor API key is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-KJDS-API-Key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get_command(self, command_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        value = self._request(
            "GET",
            f"/v1/limited-execution-commands/{command_id}",
            trace_id=trace_id,
        )
        if not isinstance(value, dict):
            raise RuntimeError("Control plane returned an invalid command")
        return value

    def claim(self, command_id: str, state_hash: str, *, trace_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/limited-execution-commands/{command_id}/claim",
            {"current_state_hash": state_hash, "lease_seconds": 300},
            trace_id=trace_id,
        )

    def begin_write_attempt(self, command_id: str, *, trace_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/limited-execution-commands/{command_id}/write-attempt",
            trace_id=trace_id,
        )

    def checkpoint_response(
        self,
        command_id: str,
        *,
        artifact_kind: str,
        content: bytes,
        sequence_number: int | None,
        trace_id: str,
    ) -> dict[str, Any]:
        response_sha256 = hashlib.sha256(content).hexdigest()
        data = {
            "artifact_kind": artifact_kind,
            "response_sha256": response_sha256,
        }
        if sequence_number is not None:
            data["sequence_number"] = str(sequence_number)

        def request() -> httpx.Response:
            return self._client.post(
                f"/v1/limited-execution-commands/{command_id}/response-checkpoint",
                data=data,
                files={
                    "file": (
                        f"{command_id}-{artifact_kind}.json",
                        content,
                        "application/json",
                    )
                },
                headers={
                    "X-Request-ID": correlation_id(None, "req"),
                    "X-Trace-ID": correlation_id(trace_id, "trace"),
                },
            )

        try:
            response = self._idempotent_write(request, "response checkpoint")
            value = response.json()
        except (RuntimeError, ValueError) as exc:
            raise ExecutionCheckpointError("Control plane could not durably checkpoint the response") from exc
        if not isinstance(value, dict) or not str(value.get("evidence_id", "")).strip():
            raise ExecutionCheckpointError("Control plane returned an invalid response checkpoint")
        return value

    def receipt(self, command_id: str, body: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
        headers = {
            "X-Request-ID": correlation_id(None, "req"),
            "X-Trace-ID": correlation_id(trace_id, "trace"),
        }

        def request() -> httpx.Response:
            return self._client.post(
                f"/v1/limited-execution-commands/{command_id}/receipt",
                json=body,
                headers=headers,
            )

        response = self._idempotent_write(request, "execution receipt")
        value = response.json()
        if not isinstance(value, dict) or not str(value.get("outcome", "")).strip():
            raise RuntimeError("Control plane returned an invalid execution receipt")
        return value

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        trace_id: str | None = None,
    ):
        response = self._client.request(
            method,
            path,
            json=body,
            headers={
                "X-Request-ID": correlation_id(None, "req"),
                "X-Trace-ID": correlation_id(trace_id, "trace"),
            },
        )
        if not response.is_success:
            raise RuntimeError(f"Control plane returned HTTP {response.status_code}")
        return response.json()

    @staticmethod
    def _idempotent_write(
        request: Callable[[], httpx.Response],
        description: str,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = request()
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < 2:
                    continue
                break
            if response.is_success:
                return response
            if response.status_code < 500 or attempt == 2:
                raise RuntimeError(f"Control plane {description} returned HTTP {response.status_code}")
        raise RuntimeError(f"Control plane {description} failed after bounded retries") from last_error


class OzonExecutionWorker:
    ADAPTER_ID = "ozon.product.import.v3"
    ACTION_ID = "listing_publish"

    def __init__(
        self,
        *,
        control_plane: ControlPlaneExecutorClient,
        ozon: OzonSellerClient | None = None,
        ozon_client_factory: Any = None,
    ) -> None:
        if (ozon is None) == (ozon_client_factory is None):
            raise ValueError("Exactly one Ozon client or exact-scope client factory is required")
        self.control_plane = control_plane
        self.ozon = ozon
        self.ozon_client_factory = ozon_client_factory

    def process(
        self,
        command: dict[str, Any],
        *,
        evidence_ids: list[str],
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        trace_id = correlation_id(trace_id, "trace")
        if command.get("adapter_id") != self.ADAPTER_ID:
            raise ValueError("Worker received a command for a different adapter")
        if command.get("status") != "queued":
            raise ValueError("Worker only processes queued commands")
        target = command.get("target", {})
        offer_id = str(target.get("offer_id", "")).strip()
        item = command.get("patch", {}).get("item")
        if not offer_id or not isinstance(item, dict) or item.get("offer_id") != offer_id:
            raise ValueError("Command target and full Ozon import item do not match")
        read_grant = command.get("credential_grant")
        if self.ozon_client_factory is not None:
            self._require_credential_grant(read_grant, "catalog.read")
        read_lease = (
            self.ozon_client_factory.open(grant=read_grant, as_of=datetime.now(UTC))
            if self.ozon_client_factory is not None
            else nullcontext(self.ozon)
        )
        with read_lease as read_client:
            before = read_client.offer_state(offer_id)
        claimed = self.control_plane.claim(command["id"], before["state_hash"], trace_id=trace_id)
        self._validate_claimed_command(claimed)
        execution_evidence_ids = list(evidence_ids)
        before_checkpoint = self.control_plane.checkpoint_response(
            command["id"],
            artifact_kind="before_read",
            content=before["response_evidence_bytes"],
            sequence_number=None,
            trace_id=trace_id,
        )
        execution_evidence_ids.append(before_checkpoint["evidence_id"])
        if claimed.get("target") != command.get("target"):
            raise ValueError("Claimed command target changed after precondition read")
        item = claimed.get("patch", {}).get("item")
        if not isinstance(item, dict) or item.get("offer_id") != offer_id:
            raise ValueError("Claimed command patch changed after authorization")
        write_attempt = self.control_plane.begin_write_attempt(
            command["id"],
            trace_id=trace_id,
        )
        self._validate_write_started_command(write_attempt)
        write_grant = write_attempt.get("credential_grant")
        if self.ozon_client_factory is not None:
            self._require_credential_grant(write_grant, "catalog.write")
        if (
            write_attempt.get("id") != claimed.get("id")
            or write_attempt.get("target") != claimed.get("target")
            or write_attempt.get("patch") != claimed.get("patch")
            or write_attempt.get("authorization_hash") != claimed.get("authorization_hash")
        ):
            raise ValueError("Write attempt does not match the claimed command")
        task_id = None
        write_stack = ExitStack()
        try:
            write_lease = (
                self.ozon_client_factory.open(grant=write_grant, as_of=datetime.now(UTC))
                if self.ozon_client_factory is not None
                else nullcontext(self.ozon)
            )
            try:
                ozon = write_stack.enter_context(write_lease)
                import_response = ozon.import_product(item)
                task_id = import_response["task_id"]
                import_checkpoint = self.control_plane.checkpoint_response(
                    command["id"],
                    artifact_kind="product_import_response",
                    content=import_response["response_evidence_bytes"],
                    sequence_number=None,
                    trace_id=trace_id,
                )
                execution_evidence_ids.append(import_checkpoint["evidence_id"])

                def checkpoint_status(content: bytes, sequence_number: int) -> None:
                    checkpoint = self.control_plane.checkpoint_response(
                        command["id"],
                        artifact_kind="import_status_response",
                        content=content,
                        sequence_number=sequence_number,
                        trace_id=trace_id,
                    )
                    execution_evidence_ids.append(checkpoint["evidence_id"])

                import_result = ozon.wait_for_import(
                    task_id,
                    on_response=checkpoint_status,
                )
            except OzonApiError as exc:
                if task_id is None and exc.response_evidence_bytes is not None:
                    import_checkpoint = self.control_plane.checkpoint_response(
                        command["id"],
                        artifact_kind="product_import_response",
                        content=exc.response_evidence_bytes,
                        sequence_number=None,
                        trace_id=trace_id,
                    )
                    execution_evidence_ids.append(import_checkpoint["evidence_id"])
                return self.control_plane.receipt(
                    command["id"],
                    {
                        "outcome": "uncertain",
                        "remote_operation_id": task_id,
                        "resulting_state_hash": None,
                        "mutation_applied": False,
                        "error_code": exc.code,
                        "error_detail": str(exc),
                        "evidence_ids": execution_evidence_ids,
                    },
                    trace_id=trace_id,
                )
            if import_result["status"] == "succeeded":
                try:
                    after = ozon.offer_state(offer_id)
                except OzonApiError as exc:
                    return self.control_plane.receipt(
                        command["id"],
                        {
                            "outcome": "uncertain",
                            "remote_operation_id": task_id,
                            "resulting_state_hash": None,
                            "mutation_applied": False,
                            "error_code": "OZON_AFTER_READ_UNCERTAIN",
                            "error_detail": str(exc),
                            "evidence_ids": execution_evidence_ids,
                        },
                        trace_id=trace_id,
                    )
                after_checkpoint = self.control_plane.checkpoint_response(
                    command["id"],
                    artifact_kind="after_read",
                    content=after["response_evidence_bytes"],
                    sequence_number=None,
                    trace_id=trace_id,
                )
                execution_evidence_ids.append(after_checkpoint["evidence_id"])
                readback_matches = self._readback_matches(item, after["state"])
                return self.control_plane.receipt(
                    command["id"],
                    {
                        "outcome": "succeeded" if readback_matches else "uncertain",
                        "remote_operation_id": task_id,
                        "resulting_state_hash": after["state_hash"],
                        "mutation_applied": True,
                        "error_code": None if readback_matches else "OZON_READBACK_DIVERGENT",
                        "error_detail": (
                            None if readback_matches else "Authoritative Ozon readback differs from the approved item"
                        ),
                        "evidence_ids": execution_evidence_ids,
                    },
                    trace_id=trace_id,
                )
            return self.control_plane.receipt(
                command["id"],
                {
                    "outcome": import_result["status"],
                    "remote_operation_id": task_id,
                    "resulting_state_hash": None,
                    "mutation_applied": False,
                    "error_code": "OZON_IMPORT_NOT_CONFIRMED",
                    "error_detail": "Ozon import task did not confirm a completed mutation",
                    "evidence_ids": execution_evidence_ids,
                },
                trace_id=trace_id,
            )
        except ExecutionCheckpointError as exc:
            return self.control_plane.receipt(
                command["id"],
                {
                    "outcome": "uncertain",
                    "remote_operation_id": task_id,
                    "resulting_state_hash": None,
                    "mutation_applied": False,
                    "error_code": "CONTROL_PLANE_CHECKPOINT_FAILED",
                    "error_detail": str(exc),
                    "evidence_ids": execution_evidence_ids,
                },
                trace_id=trace_id,
            )
        finally:
            write_stack.close()

    def run_once(
        self,
        *,
        command_id: str,
        offer_id: str,
        evidence_ids: list[str],
    ) -> dict[str, Any]:
        trace_id = correlation_id(None, "trace")
        command = self.control_plane.get_command(command_id, trace_id=trace_id)
        if command.get("id") != command_id:
            raise ValueError("Control plane returned a different execution command")
        if command.get("target") != {"offer_id": offer_id}:
            raise ValueError("Selected command does not match the explicit Ozon offer")
        return self.process(command, evidence_ids=evidence_ids, trace_id=trace_id)

    @classmethod
    def _readback_matches(
        cls,
        intended_item: dict[str, Any],
        state: dict[str, Any],
    ) -> bool:
        attributes = state.get("attributes")
        result = attributes.get("result") if isinstance(attributes, dict) else None
        items = result.get("items") if isinstance(result, dict) else result
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            return False
        observed = items[0]
        for key, expected in intended_item.items():
            if key not in observed or cls._canonical_value(observed[key]) != cls._canonical_value(expected):
                return False
        return True

    @staticmethod
    def _require_credential_grant(grant: Any, capability: str) -> None:
        observed = (
            grant.required_capability
            if type(grant) is SignedWorkerCredentialGrant
            else grant.get("required_capability")
            if isinstance(grant, dict)
            else None
        )
        if observed != capability:
            raise PermissionError(f"Server-owned {capability} credential grant is required")

    @staticmethod
    def _canonical_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): OzonExecutionWorker._canonical_value(nested)
                for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, list):
            return [OzonExecutionWorker._canonical_value(nested) for nested in value]
        return value

    @classmethod
    def _validate_write_started_command(cls, command: dict[str, Any]) -> None:
        if command.get("status") != "write_started" or command.get("write_attempt_consumed") is not True:
            raise ValueError("Control plane did not consume the single-use write attempt")
        cls._validate_authorized_command(command)

    @classmethod
    def _validate_claimed_command(cls, command: dict[str, Any]) -> None:
        if command.get("status") != "claimed":
            raise ValueError("Control plane did not return a claimed execution permit")
        cls._validate_authorized_command(command)

    @classmethod
    def _validate_authorized_command(cls, command: dict[str, Any]) -> None:
        if command.get("adapter_id") != cls.ADAPTER_ID or command.get("action_id") != cls.ACTION_ID:
            raise ValueError("Execution permit is not authorized for Ozon listing publication")
        for name in ("decision_hash", "authorization_hash"):
            value = str(command.get(name, "")).strip().lower()
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"Execution permit has an invalid {name}")
        expires_at = cls._aware_datetime(command.get("permit_expires_at"))
        if expires_at <= datetime.now(UTC):
            raise ValueError("Execution permit expired before the Ozon write")
        if command["authorization_hash"] != cls._authorization_hash(command):
            raise ValueError("Execution permit authorization hash does not match")
        portfolio_risk = command.get("portfolio_risk")
        if not isinstance(portfolio_risk, dict) or portfolio_risk.get("allowed") is not True:
            raise ValueError("Execution permit lacks an allowed portfolio risk snapshot")
        snapshot_hash = str(portfolio_risk.get("snapshot_hash", "")).strip().lower()
        snapshot_payload = {key: value for key, value in portfolio_risk.items() if key != "snapshot_hash"}
        if snapshot_hash != cls._hash(snapshot_payload):
            raise ValueError("Execution permit portfolio risk snapshot does not match")
        limits = command.get("risk_limits") or {}
        values = command.get("risk_values") or {}
        try:
            quantity = Decimal(str(values["quantity"]))
            max_quantity = Decimal(str(limits["max_quantity"]))
            expected_loss = Decimal(str(values["expected_loss"]))
            max_expected_loss = Decimal(str(limits["max_expected_loss"]))
        except (KeyError, InvalidOperation) as exc:
            raise ValueError("Execution permit is missing bounded listing risk values") from exc
        if quantity != 1 or quantity > max_quantity or expected_loss > max_expected_loss:
            raise ValueError("Execution permit listing risk values exceed their limits")

    @classmethod
    def _authorization_hash(cls, command: dict[str, Any]) -> str:
        common = {
            "action_id": command["action_id"],
            "action_policy_version": command["action_policy_version"],
            "decision_hash": command["decision_hash"],
            "risk_limits": command["risk_limits"],
            "risk_values": command["risk_values"],
            "risk_currency": command.get("risk_currency"),
            "portfolio_risk_snapshot": command["portfolio_risk"],
            "permit_expires_at": command["permit_expires_at"],
            "command_kind": command["command_kind"],
        }
        if command["command_kind"] == "rollback":
            common["parent_command_id"] = command["parent_command_id"]
        else:
            common["plan_id"] = command["plan_id"]
        return hashlib.sha256(
            json.dumps(
                common,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _aware_datetime(value: Any) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Execution permit expiry must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Execution permit expiry must include a timezone")
        return parsed.astimezone(UTC)


class _OzonClientLease:
    """Context-managed Ozon client bound to one resolved credential lease."""

    def __init__(self, client: OzonSellerClient) -> None:
        self._client = client
        self._closed = False

    def __enter__(self) -> OzonSellerClient:
        return self._client

    def __exit__(self, *_exc: object) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True


def ozon_client_builder(
    material: ResolvedChannelCredentialMaterial,
    resolver: SignedManagedCredentialLeaseResolver,
) -> _OzonClientLease:
    """Composition hook: build the Ozon client from one resolved lease."""
    credentials = OzonCredentials.from_resolved_material(
        resolver=resolver,
        material=material,
    )
    return _OzonClientLease(OzonSellerClient(credentials=credentials))


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated KJDS Ozon limited-execution worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="validate one command locally without constructing network clients",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="explicitly authorize one command in this process",
    )
    parser.add_argument(
        "--command-id",
        default=os.getenv("KJDS_EXECUTION_COMMAND_ID", ""),
    )
    parser.add_argument(
        "--offer-id",
        default=os.getenv("KJDS_EXECUTION_OFFER_ID", ""),
    )
    parser.add_argument("--evidence-id", action="append")
    args = parser.parse_args()
    evidence_ids = args.evidence_id or [
        item.strip() for item in os.getenv("KJDS_EXECUTION_EVIDENCE_IDS", "").split(",") if item.strip()
    ]
    if args.preflight:
        report = offline_execution_preflight(
            command_id=args.command_id,
            offer_id=args.offer_id,
            evidence_ids=evidence_ids,
        )
        print(json.dumps(report, ensure_ascii=False))
        return

    runtime = build_channel_worker_runtime(
        os.environ,
        client_builder=ozon_client_builder,
    )
    runtime.require_execution_ready()
    report = offline_execution_preflight(
        command_id=args.command_id,
        offer_id=args.offer_id,
        evidence_ids=evidence_ids,
    )
    control = ControlPlaneExecutorClient(
        base_url=os.getenv("KJDS_CONTROL_PLANE_URL", "http://127.0.0.1:8000"),
        api_key=_configured_value(os.environ, "KJDS_EXECUTOR_API_KEY"),
    )
    worker = OzonExecutionWorker(
        control_plane=control,
        ozon_client_factory=runtime.credential_client_factory,
    )
    try:
        worker.run_once(
            command_id=args.command_id,
            offer_id=args.offer_id,
            evidence_ids=evidence_ids,
        )
    finally:
        control.close()


if __name__ == "__main__":
    main()
