from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .security import Principal
from .sql_repository import Base

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "media_agent_contracts.json"
)
CONTRACT_ID = "kjds-media-connector-descriptor-v1"
SCHEMA_VERSION = "kjds-media-agent-contracts-v1"
REGISTERABLE_CONNECTOR_PROVIDERS = frozenset(
    {"codex_oauth", "comfyui", "ffmpeg", "remotion", "windows_agent"}
)
INTERNAL_BLUEPRINT_PROVIDER = "kjds_internal_blueprint_compiler"
RUNTIME_FFMPEG_PROVIDER = "ffmpeg"
INTERNAL_TUTORIAL_PROVIDER = "kjds_internal_tutorial_compiler"
CONTRACT_PROVIDERS = REGISTERABLE_CONNECTOR_PROVIDERS | frozenset(
    {INTERNAL_BLUEPRINT_PROVIDER, INTERNAL_TUTORIAL_PROVIDER}
)
CONTRACT_PROVIDER_SEQUENCE = (
    "codex_oauth",
    "comfyui",
    "ffmpeg",
    INTERNAL_BLUEPRINT_PROVIDER,
    INTERNAL_TUTORIAL_PROVIDER,
    "remotion",
    "windows_agent",
)
PROVIDERS = REGISTERABLE_CONNECTOR_PROVIDERS
DEPLOYMENT_MODES = frozenset({"customer_local", "hosted_isolated"})
HEALTH_STATES = frozenset(
    {
        "ENROLLING",
        "READY",
        "BUSY",
        "LOGIN_REQUIRED",
        "LIMITED",
        "OFFLINE",
        "ERROR",
        "REVOKED",
    }
)
OBSERVABLE_HEALTH_STATES = HEALTH_STATES - {"ENROLLING", "REVOKED"}
RATE_LIMIT_STATUSES = frozenset({"ok", "limited", "unknown"})
DESCRIPTOR_FIELDS = frozenset(
    {
        "connector_ref",
        "derived_tenant_ref",
        "provider",
        "deployment_mode",
        "binding_sha256",
        "protocol_version",
        "capabilities",
        "health",
        "concurrency_limit",
        "rate_limit_summary",
        "last_heartbeat_at",
        "created_at",
        "revoked_at",
    }
)
RATE_LIMIT_FIELDS = frozenset({"status", "observed_at", "retry_after_at"})
ZERO_SHA256 = "0" * 64
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
PROTOCOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,79}$")
SECRET_VALUE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "sk-",
)


class MediaConnectorConflictError(RuntimeError):
    """A stable idempotency key or immutable connector binding drifted."""


@dataclass(frozen=True)
class RuntimeOwnedProviderDescriptor:
    provider: str
    connector_ref: str
    binding_sha256: str
    protocol_version: str
    capabilities: frozenset[str]
    deterministic: bool
    external_call: bool
    credential_required: bool
    cost_amount_minor: int
    cost_currency: str
    cost_basis: str
    enrollment_allowed: bool
    automatic_retry: bool
    automatic_failover: bool


class MediaConnectorRow(Base):
    __tablename__ = "media_connectors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "registration_idempotency_sha256",
            name="uq_media_connector_tenant_idempotency",
        ),
        UniqueConstraint(
            "connector_ref",
            "tenant_ref",
            "provider",
            name="uq_media_connector_exact_binding",
        ),
        CheckConstraint(
            "provider IN ('codex_oauth','comfyui','ffmpeg','remotion','windows_agent')",
            name="ck_media_connector_provider",
        ),
        CheckConstraint(
            "deployment_mode IN ('customer_local','hosted_isolated')",
            name="ck_media_connector_deployment_mode",
        ),
        CheckConstraint(
            "length(connector_ref) > 4 AND length(tenant_ref) > 0 "
            "AND length(binding_sha256) = 64 "
            "AND length(protocol_version) > 0 "
            "AND length(registration_request_sha256) = 64 "
            "AND length(registration_idempotency_sha256) = 64 "
            "AND length(created_by) > 0",
            name="ck_media_connector_required_fields",
        ),
        CheckConstraint(
            "concurrency_limit = 1",
            name="ck_media_connector_v1_concurrency",
        ),
        Index(
            "ix_media_connector_tenant_provider",
            "tenant_ref",
            "provider",
            "connector_ref",
        ),
    )

    connector_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    deployment_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(80), nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_request_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    registration_idempotency_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MediaConnectorEventRow(Base):
    __tablename__ = "media_connector_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connector_ref", "tenant_ref", "provider"],
            [
                "media_connectors.connector_ref",
                "media_connectors.tenant_ref",
                "media_connectors.provider",
            ],
            name="fk_media_connector_event_exact_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "connector_ref",
            "tenant_ref",
            "sequence",
            name="uq_media_connector_event_sequence",
        ),
        UniqueConstraint(
            "connector_ref",
            "tenant_ref",
            "idempotency_sha256",
            name="uq_media_connector_event_idempotency",
        ),
        CheckConstraint(
            "event_type IN ('registered','health_observed','revoked')",
            name="ck_media_connector_event_type",
        ),
        CheckConstraint(
            "health IN ('ENROLLING','READY','BUSY','LOGIN_REQUIRED','LIMITED',"
            "'OFFLINE','ERROR','REVOKED')",
            name="ck_media_connector_event_health",
        ),
        CheckConstraint(
            "(event_type = 'registered' AND health = 'ENROLLING') "
            "OR (event_type = 'revoked' AND health = 'REVOKED') "
            "OR (event_type = 'health_observed' "
            "AND health NOT IN ('ENROLLING','REVOKED'))",
            name="ck_media_connector_event_semantics",
        ),
        CheckConstraint(
            "sequence > 0 AND length(event_ref) > 4 "
            "AND length(connector_ref) > 4 AND length(tenant_ref) > 0 "
            "AND length(observation_request_sha256) = 64 "
            "AND length(idempotency_sha256) = 64 "
            "AND length(previous_event_sha256) = 64 "
            "AND length(event_sha256) = 64 "
            "AND length(created_by) > 0",
            name="ck_media_connector_event_required_fields",
        ),
        CheckConstraint(
            "(rate_limit_status IS NULL "
            "AND rate_limit_observed_at IS NULL AND retry_after_at IS NULL) "
            "OR (rate_limit_status IN ('ok','limited','unknown') "
            "AND rate_limit_observed_at IS NOT NULL "
            "AND (retry_after_at IS NULL "
            "OR retry_after_at >= rate_limit_observed_at))",
            name="ck_media_connector_rate_limit_summary",
        ),
        CheckConstraint(
            "(health = 'LIMITED' AND rate_limit_status = 'limited') "
            "OR (health <> 'LIMITED' AND "
            "(rate_limit_status IS NULL OR rate_limit_status <> 'limited'))",
            name="ck_media_connector_limited_state",
        ),
        CheckConstraint(
            "recorded_at >= observed_at",
            name="ck_media_connector_event_time_order",
        ),
        Index(
            "ix_media_connector_event_latest",
            "tenant_ref",
            "connector_ref",
            "sequence",
        ),
    )

    event_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    connector_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    health: Mapped[str] = mapped_column(String(32), nullable=False)
    rate_limit_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    rate_limit_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_after_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observation_request_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_event_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)


class MediaConnectorContract:
    def __init__(
        self,
        *,
        path: Path | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        raw = payload or json.loads(
            (path or CONTRACT_PATH).read_text(encoding="utf-8")
        )
        connector = raw.get("connector_contract")
        if (
            raw.get("schema_version") != SCHEMA_VERSION
            or not isinstance(connector, dict)
            or connector.get("contract_id") != CONTRACT_ID
        ):
            raise RuntimeError("Unknown media connector contract")
        if connector.get("providers") != list(CONTRACT_PROVIDER_SEQUENCE):
            raise RuntimeError("Media connector Provider contract drifted")
        if set(connector.get("deployment_modes", [])) != DEPLOYMENT_MODES:
            raise RuntimeError("Media connector deployment contract drifted")
        if set(connector.get("health_states", [])) != HEALTH_STATES:
            raise RuntimeError("Media connector health contract drifted")
        if set(connector.get("allowed_record_fields", [])) != DESCRIPTOR_FIELDS:
            raise RuntimeError("Media connector descriptor contract drifted")
        if set(connector.get("rate_limit_summary_fields", [])) != RATE_LIMIT_FIELDS:
            raise RuntimeError("Media connector rate-limit contract drifted")
        for flag in (
            "shared_pool",
            "cross_tenant_reuse",
            "automatic_rotation",
            "raw_credential_readback",
        ):
            if connector.get(flag) is not False:
                raise RuntimeError(f"Media connector {flag} contract drifted")
        self.payload = raw
        self.connector = connector
        self.contract_sha256 = self._hash(raw)
        self.provider_capabilities = self._provider_capabilities(raw)
        self.runtime_owned_providers = self._runtime_owned_providers(raw)
        self._validate_provider_parity(raw)

    @staticmethod
    def _provider_capabilities(raw: dict[str, Any]) -> dict[str, frozenset[str]]:
        result = {provider: set() for provider in CONTRACT_PROVIDERS}
        gateway = raw.get("tool_gateway", {})
        for tool in gateway.get("tools", []):
            capabilities = set(tool.get("required_capabilities", []))
            for provider in tool.get("accepted_providers", []):
                if provider in result:
                    result[provider].update(capabilities)
        return {key: frozenset(value) for key, value in result.items()}

    @classmethod
    def _runtime_owned_providers(
        cls, raw: dict[str, Any]
    ) -> dict[str, RuntimeOwnedProviderDescriptor]:
        connector = raw["connector_contract"]
        descriptors = connector.get("runtime_owned_provider_descriptors")
        if not isinstance(descriptors, Mapping) or set(descriptors) != {
            INTERNAL_BLUEPRINT_PROVIDER,
            INTERNAL_TUTORIAL_PROVIDER,
            RUNTIME_FFMPEG_PROVIDER,
        }:
            raise RuntimeError("Runtime-owned media provider inventory drifted")
        fields = {
            "provider",
            "connector_ref",
            "binding_sha256",
            "protocol_version",
            "capabilities",
            "deterministic",
            "external_call",
            "credential_required",
            "cost_upper_bound",
            "enrollment_allowed",
            "automatic_retry",
            "automatic_failover",
        }
        expected = {
            INTERNAL_BLUEPRINT_PROVIDER: {
                "connector_ref": "internal://editing-blueprint-compiler-v1",
                "binding_sha256": hashlib.sha256(
                    b"kjds-internal-editing-blueprint-compiler-v1"
                ).hexdigest(),
                "protocol_version": "kjds-internal-blueprint-compiler/1",
                "capabilities": ["vision", "structured_output"],
                "cost_basis": "internal_deterministic_compiler_no_provider_charge",
            },
            INTERNAL_TUTORIAL_PROVIDER: {
                "connector_ref": "internal://tutorial-graph-compiler-v1",
                "binding_sha256": hashlib.sha256(
                    b"kjds-internal-tutorial-graph-compiler-v1"
                ).hexdigest(),
                "protocol_version": "kjds-internal-tutorial-compiler/1",
                "capabilities": ["tutorial_graph", "structured_output"],
                "cost_basis": "internal_deterministic_compiler_no_provider_charge",
            },
            RUNTIME_FFMPEG_PROVIDER: {
                "connector_ref": "internal://local-ffmpeg-renderer-v1",
                "binding_sha256": hashlib.sha256(
                    b"kjds-runtime-owned-local-ffmpeg-v1"
                ).hexdigest(),
                "protocol_version": "kjds-local-ffmpeg/1",
                "capabilities": ["video_render"],
                "cost_basis": "internal_deterministic_ffmpeg_no_provider_charge",
            },
        }
        result: dict[str, RuntimeOwnedProviderDescriptor] = {}
        for provider, exact in expected.items():
            item = descriptors[provider]
            if not isinstance(item, Mapping) or set(item) != fields:
                raise RuntimeError("Runtime-owned media provider descriptor drifted")
            cost = item["cost_upper_bound"]
            capabilities = item["capabilities"]
            if (
                item["provider"] != provider
                or item["connector_ref"] != exact["connector_ref"]
                or item["binding_sha256"] != exact["binding_sha256"]
                or item["protocol_version"] != exact["protocol_version"]
                or not isinstance(capabilities, list)
                or capabilities != exact["capabilities"]
                or item["deterministic"] is not True
                or item["external_call"] is not False
                or item["credential_required"] is not False
                or item["enrollment_allowed"] is not False
                or item["automatic_retry"] is not False
                or item["automatic_failover"] is not False
                or not isinstance(cost, Mapping)
                or type(cost.get("amount_minor")) is not int
                or dict(cost)
                != {
                    "amount_minor": 0,
                    "currency": "USD",
                    "basis": exact["cost_basis"],
                }
            ):
                raise RuntimeError("Runtime-owned media provider contract drifted")
            result[provider] = RuntimeOwnedProviderDescriptor(
                provider=item["provider"],
                connector_ref=item["connector_ref"],
                binding_sha256=item["binding_sha256"],
                protocol_version=item["protocol_version"],
                capabilities=frozenset(capabilities),
                deterministic=item["deterministic"],
                external_call=item["external_call"],
                credential_required=item["credential_required"],
                cost_amount_minor=cost["amount_minor"],
                cost_currency=cost["currency"],
                cost_basis=cost["basis"],
                enrollment_allowed=item["enrollment_allowed"],
                automatic_retry=item["automatic_retry"],
                automatic_failover=item["automatic_failover"],
            )
        return result

    def _validate_provider_parity(self, raw: dict[str, Any]) -> None:
        gateway = raw.get("tool_gateway")
        tools = gateway.get("tools") if isinstance(gateway, Mapping) else None
        if not isinstance(tools, list):
            raise RuntimeError("Media provider tool inventory drifted")
        accepted: set[str] = set()
        runtime_tools: dict[str, Mapping[str, Any]] = {}
        for tool in tools:
            if not isinstance(tool, Mapping):
                raise RuntimeError("Media provider tool contract drifted")
            providers = tool.get("accepted_providers")
            capabilities = tool.get("required_capabilities")
            if (
                not isinstance(providers, list)
                or len(providers) != len(set(providers))
                or not all(isinstance(provider, str) for provider in providers)
                or not isinstance(capabilities, list)
                or len(capabilities) != len(set(capabilities))
                or not all(isinstance(value, str) for value in capabilities)
            ):
                raise RuntimeError("Media provider tool contract drifted")
            accepted.update(providers)
            if tool.get("name") in {"media.video_blueprint", "media.video_render", "tutorial.build"}:
                runtime_tools[tool["name"]] = tool
        if not accepted.issubset(CONTRACT_PROVIDERS):
            raise RuntimeError("Media provider coverage drifted")
        expected_tools = {
            "media.video_blueprint": (
                INTERNAL_BLUEPRINT_PROVIDER,
                ["vision", "structured_output"],
                "internal_deterministic_compile_only",
            ),
            "tutorial.build": (
                INTERNAL_TUTORIAL_PROVIDER,
                ["tutorial_graph", "structured_output"],
                "internal_deterministic_compile_only",
            ),
            "media.video_render": (
                RUNTIME_FFMPEG_PROVIDER,
                ["video_render"],
                "local_media_render_only",
            ),
        }
        for name, (provider, capabilities, side_effect) in expected_tools.items():
            tool = runtime_tools.get(name)
            descriptor = self.runtime_owned_providers[provider]
            if (
                not isinstance(tool, Mapping)
                or tool.get("accepted_providers") != [provider]
                or tool.get("required_capabilities") != capabilities
                or tool.get("external_side_effect") != side_effect
                or tool.get("cost_upper_bound")
                != {
                    "amount_minor": descriptor.cost_amount_minor,
                    "currency": descriptor.cost_currency,
                    "basis": descriptor.cost_basis,
                }
            ):
                raise RuntimeError("Runtime-owned media provider parity drifted")

    def internal_runtime_provider(
        self, provider: str
    ) -> RuntimeOwnedProviderDescriptor:
        try:
            return self.runtime_owned_providers[provider]
        except KeyError as exc:
            raise KeyError("Runtime-owned media provider not found") from exc

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class MediaConnectorRegistry:
    """Tenant-bound, descriptor-only registry for media execution nodes."""

    def __init__(
        self,
        *,
        engine,
        contract: MediaConnectorContract | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.engine = engine
        self.contract = contract or MediaConnectorContract()
        self.clock = clock or (lambda: datetime.now(UTC))

    def register(
        self,
        *,
        principal: Principal,
        provider: str,
        deployment_mode: str,
        protocol_version: str,
        capabilities: list[str],
        concurrency_limit: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_role(principal, "admin")
        tenant_ref = self._required(principal.tenant_ref, "tenant_ref", 160)
        provider = self._provider(provider)
        deployment_mode = self._deployment_mode(deployment_mode)
        protocol_version = self._protocol_version(protocol_version)
        capabilities = self._capabilities(provider, capabilities)
        if concurrency_limit != 1 or isinstance(concurrency_limit, bool):
            raise ValueError("Media Connector v1 concurrency_limit must be 1")
        idempotency_key = self._idempotency_key(idempotency_key)
        idempotency_sha256 = self._hash(
            {
                "tenant_ref": tenant_ref,
                "purpose": "media_connector_register",
                "idempotency_key": idempotency_key,
            }
        )
        connector_ref = f"mcn_{idempotency_sha256[:32]}"
        binding = {
            "derived_tenant_ref": tenant_ref,
            "connector_ref": connector_ref,
            "provider": provider,
            "deployment_mode": deployment_mode,
            "protocol_version": protocol_version,
            "capabilities": capabilities,
            "concurrency_limit": concurrency_limit,
        }
        binding_sha256 = self._hash(binding)
        request_sha256 = self._hash(
            {
                **binding,
                "binding_sha256": binding_sha256,
                "idempotency_sha256": idempotency_sha256,
            }
        )
        now = self._now()
        try:
            with Session(self.engine) as db, db.begin():
                existing = db.scalar(
                    select(MediaConnectorRow).where(
                        MediaConnectorRow.tenant_ref == tenant_ref,
                        MediaConnectorRow.registration_idempotency_sha256
                        == idempotency_sha256,
                    )
                )
                if existing is not None:
                    self._require_same_registration(existing, request_sha256)
                    return self._result(db, existing)
                row = MediaConnectorRow(
                    connector_ref=connector_ref,
                    tenant_ref=tenant_ref,
                    provider=provider,
                    deployment_mode=deployment_mode,
                    binding_sha256=binding_sha256,
                    protocol_version=protocol_version,
                    capabilities_json=capabilities,
                    concurrency_limit=concurrency_limit,
                    registration_request_sha256=request_sha256,
                    registration_idempotency_sha256=idempotency_sha256,
                    created_by=self._required(
                        principal.actor_id, "actor_id", 160
                    ),
                    created_at=now,
                )
                db.add(row)
                db.flush()
                self._append_event(
                    db,
                    row=row,
                    event_type="registered",
                    health="ENROLLING",
                    observed_at=now,
                    rate_limit_status=None,
                    rate_limit_observed_at=None,
                    retry_after_at=None,
                    idempotency_sha256=idempotency_sha256,
                    request_sha256=request_sha256,
                    created_by=row.created_by,
                )
                return self._result(db, row)
        except IntegrityError as exc:
            return self._registration_race_winner(
                tenant_ref=tenant_ref,
                idempotency_sha256=idempotency_sha256,
                request_sha256=request_sha256,
                cause=exc,
            )

    def observe(
        self,
        *,
        principal: Principal,
        connector_ref: str,
        health: str,
        observed_at: datetime,
        rate_limit_status: str | None,
        rate_limit_observed_at: datetime | None,
        retry_after_at: datetime | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_role(principal, "operator", "monitor", "admin")
        health = str(health or "").strip().upper()
        if health not in OBSERVABLE_HEALTH_STATES:
            raise ValueError("Unsupported observable Media Connector health")
        return self._record_event(
            principal=principal,
            connector_ref=connector_ref,
            event_type="health_observed",
            health=health,
            observed_at=observed_at,
            rate_limit_status=rate_limit_status,
            rate_limit_observed_at=rate_limit_observed_at,
            retry_after_at=retry_after_at,
            idempotency_key=idempotency_key,
        )

    def revoke(
        self,
        *,
        principal: Principal,
        connector_ref: str,
        observed_at: datetime,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_role(principal, "admin")
        return self._record_event(
            principal=principal,
            connector_ref=connector_ref,
            event_type="revoked",
            health="REVOKED",
            observed_at=observed_at,
            rate_limit_status=None,
            rate_limit_observed_at=None,
            retry_after_at=None,
            idempotency_key=idempotency_key,
        )

    def get(
        self,
        *,
        principal: Principal,
        connector_ref: str,
    ) -> dict[str, Any]:
        self._require_role(
            principal,
            "operator",
            "reviewer",
            "compliance",
            "monitor",
            "admin",
        )
        tenant_ref = self._required(principal.tenant_ref, "tenant_ref", 160)
        connector_ref = self._connector_ref(connector_ref)
        with Session(self.engine) as session:
            row = self._connector(
                session,
                tenant_ref=tenant_ref,
                connector_ref=connector_ref,
            )
            return self._result(session, row)

    def list(
        self,
        *,
        principal: Principal,
        provider: str | None = None,
        health: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require_role(
            principal,
            "operator",
            "reviewer",
            "compliance",
            "monitor",
            "admin",
        )
        tenant_ref = self._required(principal.tenant_ref, "tenant_ref", 160)
        if isinstance(limit, bool) or not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        provider = self._provider(provider) if provider else None
        health = str(health or "").strip().upper() or None
        if health is not None and health not in HEALTH_STATES:
            raise ValueError("Unsupported Media Connector health filter")
        cursor = self._connector_ref(cursor) if cursor else None
        with Session(self.engine) as session:
            latest_health = (
                select(MediaConnectorEventRow.health)
                .where(
                    MediaConnectorEventRow.connector_ref
                    == MediaConnectorRow.connector_ref,
                    MediaConnectorEventRow.tenant_ref
                    == MediaConnectorRow.tenant_ref,
                )
                .order_by(desc(MediaConnectorEventRow.sequence))
                .limit(1)
                .correlate(MediaConnectorRow)
                .scalar_subquery()
            )
            query = select(MediaConnectorRow).where(
                MediaConnectorRow.tenant_ref == tenant_ref
            )
            if provider:
                query = query.where(MediaConnectorRow.provider == provider)
            if health:
                query = query.where(latest_health == health)
            if cursor:
                query = query.where(MediaConnectorRow.connector_ref > cursor)
            rows = list(
                session.scalars(
                    query.order_by(MediaConnectorRow.connector_ref).limit(
                        int(limit) + 1
                    )
                )
            )
            has_more = len(rows) > int(limit)
            rows = rows[: int(limit)]
            return {
                "contract_id": CONTRACT_ID,
                "items": [
                    self._descriptor(session, row) for row in rows
                ],
                "next_cursor": (
                    rows[-1].connector_ref if has_more and rows else None
                ),
            }

    def require_eligible(
        self,
        *,
        tenant_ref: str,
        connector_ref: str,
        provider: str,
        required_capabilities: set[str],
        as_of: datetime,
    ) -> dict[str, Any]:
        tenant_ref = self._required(tenant_ref, "tenant_ref", 160)
        connector_ref = self._connector_ref(connector_ref)
        provider = self._provider(provider)
        required = self._capabilities(provider, list(required_capabilities))
        cutoff = self._aware(as_of, "as_of")
        with Session(self.engine) as session:
            row = self._connector(
                session,
                tenant_ref=tenant_ref,
                connector_ref=connector_ref,
            )
            if row.provider != provider:
                raise PermissionError("Media Connector Provider binding mismatch")
            if not set(required).issubset(set(row.capabilities_json)):
                raise PermissionError("Media Connector capability is missing")
            descriptor = self._descriptor(session, row, as_of=cutoff)
            if descriptor["health"] != "READY":
                raise PermissionError("Media Connector is not ready")
            return {"contract_id": CONTRACT_ID, "connector": descriptor}

    def _record_event(
        self,
        *,
        principal: Principal,
        connector_ref: str,
        event_type: str,
        health: str,
        observed_at: datetime,
        rate_limit_status: str | None,
        rate_limit_observed_at: datetime | None,
        retry_after_at: datetime | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        tenant_ref = self._required(principal.tenant_ref, "tenant_ref", 160)
        connector_ref = self._connector_ref(connector_ref)
        observed_at = self._observation_time(observed_at, "observed_at")
        (
            rate_limit_status,
            rate_limit_observed_at,
            retry_after_at,
        ) = self._rate_limit_summary(
            health=health,
            status=rate_limit_status,
            observed_at=rate_limit_observed_at,
            retry_after_at=retry_after_at,
        )
        idempotency_key = self._idempotency_key(idempotency_key)
        idempotency_sha256 = self._hash(
            {
                "tenant_ref": tenant_ref,
                "connector_ref": connector_ref,
                "event_type": event_type,
                "idempotency_key": idempotency_key,
            }
        )
        request_sha256 = self._hash(
            {
                "tenant_ref": tenant_ref,
                "connector_ref": connector_ref,
                "event_type": event_type,
                "health": health,
                "observed_at": observed_at.isoformat(),
                "rate_limit_status": rate_limit_status,
                "rate_limit_observed_at": self._iso(rate_limit_observed_at),
                "retry_after_at": self._iso(retry_after_at),
                "idempotency_sha256": idempotency_sha256,
            }
        )
        try:
            with Session(self.engine) as db, db.begin():
                row = self._connector(
                    db,
                    tenant_ref=tenant_ref,
                    connector_ref=connector_ref,
                    for_update=True,
                )
                existing = db.scalar(
                    select(MediaConnectorEventRow).where(
                        MediaConnectorEventRow.connector_ref == connector_ref,
                        MediaConnectorEventRow.tenant_ref == tenant_ref,
                        MediaConnectorEventRow.idempotency_sha256
                        == idempotency_sha256,
                    )
                )
                if existing is not None:
                    self._require_same_event(existing, request_sha256)
                    return self._result(db, row)
                last = self._latest_event(db, row)
                if last is None:
                    raise MediaConnectorConflictError(
                        "Media Connector registration event is missing"
                    )
                if last.health == "REVOKED":
                    raise MediaConnectorConflictError(
                        "Media Connector is already revoked"
                    )
                self._append_event(
                    db,
                    row=row,
                    event_type=event_type,
                    health=health,
                    observed_at=observed_at,
                    rate_limit_status=rate_limit_status,
                    rate_limit_observed_at=rate_limit_observed_at,
                    retry_after_at=retry_after_at,
                    idempotency_sha256=idempotency_sha256,
                    request_sha256=request_sha256,
                    created_by=self._required(
                        principal.actor_id, "actor_id", 160
                    ),
                )
                return self._result(db, row)
        except IntegrityError as exc:
            return self._event_race_winner(
                tenant_ref=tenant_ref,
                connector_ref=connector_ref,
                idempotency_sha256=idempotency_sha256,
                request_sha256=request_sha256,
                cause=exc,
            )

    def _append_event(
        self,
        session: Session,
        *,
        row: MediaConnectorRow,
        event_type: str,
        health: str,
        observed_at: datetime,
        rate_limit_status: str | None,
        rate_limit_observed_at: datetime | None,
        retry_after_at: datetime | None,
        idempotency_sha256: str,
        request_sha256: str,
        created_by: str,
    ) -> MediaConnectorEventRow:
        last = self._latest_event(session, row)
        sequence = 1 if last is None else last.sequence + 1
        previous_sha256 = ZERO_SHA256 if last is None else last.event_sha256
        if last is not None and observed_at < self._stored_aware(
            last.observed_at, "last observed_at"
        ):
            raise ValueError("Media Connector observation time moved backwards")
        recorded_at = self._now()
        if observed_at > recorded_at:
            recorded_at = observed_at
        event_payload = {
            "connector_ref": row.connector_ref,
            "derived_tenant_ref": row.tenant_ref,
            "provider": row.provider,
            "sequence": sequence,
            "event_type": event_type,
            "health": health,
            "rate_limit_status": rate_limit_status,
            "rate_limit_observed_at": self._iso(rate_limit_observed_at),
            "retry_after_at": self._iso(retry_after_at),
            "observation_request_sha256": request_sha256,
            "idempotency_sha256": idempotency_sha256,
            "previous_event_sha256": previous_sha256,
            "observed_at": observed_at.isoformat(),
            "recorded_at": recorded_at.isoformat(),
            "created_by": created_by,
        }
        event_sha256 = self._hash(event_payload)
        event = MediaConnectorEventRow(
            event_ref=f"mce_{event_sha256[:32]}",
            connector_ref=row.connector_ref,
            tenant_ref=row.tenant_ref,
            provider=row.provider,
            sequence=sequence,
            event_type=event_type,
            health=health,
            rate_limit_status=rate_limit_status,
            rate_limit_observed_at=rate_limit_observed_at,
            retry_after_at=retry_after_at,
            observation_request_sha256=request_sha256,
            idempotency_sha256=idempotency_sha256,
            previous_event_sha256=previous_sha256,
            event_sha256=event_sha256,
            observed_at=observed_at,
            recorded_at=recorded_at,
            created_by=created_by,
        )
        session.add(event)
        session.flush()
        return event

    def _registration_race_winner(
        self,
        *,
        tenant_ref: str,
        idempotency_sha256: str,
        request_sha256: str,
        cause: Exception,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            winner = session.scalar(
                select(MediaConnectorRow).where(
                    MediaConnectorRow.tenant_ref == tenant_ref,
                    MediaConnectorRow.registration_idempotency_sha256
                    == idempotency_sha256,
                )
            )
            if winner is None:
                raise MediaConnectorConflictError(
                    "Media Connector registration conflicted"
                ) from cause
            self._require_same_registration(winner, request_sha256)
            return self._result(session, winner)

    def _event_race_winner(
        self,
        *,
        tenant_ref: str,
        connector_ref: str,
        idempotency_sha256: str,
        request_sha256: str,
        cause: Exception,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = self._connector(
                session,
                tenant_ref=tenant_ref,
                connector_ref=connector_ref,
            )
            winner = session.scalar(
                select(MediaConnectorEventRow).where(
                    MediaConnectorEventRow.connector_ref == connector_ref,
                    MediaConnectorEventRow.tenant_ref == tenant_ref,
                    MediaConnectorEventRow.idempotency_sha256
                    == idempotency_sha256,
                )
            )
            if winner is None:
                raise MediaConnectorConflictError(
                    "Media Connector event conflicted"
                ) from cause
            self._require_same_event(winner, request_sha256)
            return self._result(session, row)

    @staticmethod
    def _require_same_registration(
        row: MediaConnectorRow, request_sha256: str
    ) -> None:
        if row.registration_request_sha256 != request_sha256:
            raise MediaConnectorConflictError(
                "Media Connector registration idempotency payload drifted"
            )

    @staticmethod
    def _require_same_event(
        row: MediaConnectorEventRow, request_sha256: str
    ) -> None:
        if row.observation_request_sha256 != request_sha256:
            raise MediaConnectorConflictError(
                "Media Connector event idempotency payload drifted"
            )

    def _result(
        self, session: Session, row: MediaConnectorRow
    ) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID,
            "connector": self._descriptor(session, row),
        }

    def _descriptor(
        self,
        session: Session,
        row: MediaConnectorRow,
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of") if as_of is not None else None
        event_query = select(MediaConnectorEventRow).where(
            MediaConnectorEventRow.connector_ref == row.connector_ref,
            MediaConnectorEventRow.tenant_ref == row.tenant_ref,
        )
        if cutoff is not None:
            event_query = event_query.where(
                MediaConnectorEventRow.recorded_at <= cutoff
            )
        latest = session.scalar(
            event_query.order_by(desc(MediaConnectorEventRow.sequence)).limit(1)
        )
        if latest is None:
            raise MediaConnectorConflictError(
                "Media Connector registration event is missing"
            )
        heartbeat = session.scalar(
            event_query.where(
                MediaConnectorEventRow.event_type == "health_observed"
            )
            .order_by(desc(MediaConnectorEventRow.sequence))
            .limit(1)
        )
        rate_event = session.scalar(
            event_query.where(
                MediaConnectorEventRow.rate_limit_status.is_not(None)
            )
            .order_by(desc(MediaConnectorEventRow.sequence))
            .limit(1)
        )
        rate_limit_summary = (
            {
                "status": rate_event.rate_limit_status,
                "observed_at": self._iso(rate_event.rate_limit_observed_at),
                "retry_after_at": self._iso(rate_event.retry_after_at),
            }
            if rate_event is not None
            else None
        )
        return {
            "connector_ref": row.connector_ref,
            "derived_tenant_ref": row.tenant_ref,
            "provider": row.provider,
            "deployment_mode": row.deployment_mode,
            "binding_sha256": row.binding_sha256,
            "protocol_version": row.protocol_version,
            "capabilities": list(row.capabilities_json),
            "health": latest.health,
            "concurrency_limit": row.concurrency_limit,
            "rate_limit_summary": rate_limit_summary,
            "last_heartbeat_at": (
                self._iso(heartbeat.observed_at) if heartbeat else None
            ),
            "created_at": self._iso(row.created_at),
            "revoked_at": (
                self._iso(latest.observed_at)
                if latest.health == "REVOKED"
                else None
            ),
        }

    @staticmethod
    def _latest_event(
        session: Session, row: MediaConnectorRow
    ) -> MediaConnectorEventRow | None:
        return session.scalar(
            select(MediaConnectorEventRow)
            .where(
                MediaConnectorEventRow.connector_ref == row.connector_ref,
                MediaConnectorEventRow.tenant_ref == row.tenant_ref,
            )
            .order_by(desc(MediaConnectorEventRow.sequence))
            .limit(1)
        )

    @staticmethod
    def _connector(
        session: Session,
        *,
        tenant_ref: str,
        connector_ref: str,
        for_update: bool = False,
    ) -> MediaConnectorRow:
        query = select(MediaConnectorRow).where(
            MediaConnectorRow.tenant_ref == tenant_ref,
            MediaConnectorRow.connector_ref == connector_ref,
        )
        if for_update:
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise KeyError("Media Connector not found")
        return row

    def _rate_limit_summary(
        self,
        *,
        health: str,
        status: str | None,
        observed_at: datetime | None,
        retry_after_at: datetime | None,
    ) -> tuple[str | None, datetime | None, datetime | None]:
        status = str(status or "").strip().lower() or None
        if status is not None and status not in RATE_LIMIT_STATUSES:
            raise ValueError("Unsupported rate limit status")
        if health == "LIMITED" and status != "limited":
            raise ValueError("LIMITED health requires limited rate status")
        if status == "limited" and health != "LIMITED":
            raise ValueError("limited rate status requires LIMITED health")
        if status is None:
            if observed_at is not None or retry_after_at is not None:
                raise ValueError("Rate limit times require a status")
            return None, None, None
        observed = self._observation_time(
            observed_at, "rate_limit observed_at"
        )
        retry = (
            self._aware(retry_after_at, "retry_after_at")
            if retry_after_at is not None
            else None
        )
        if retry is not None and retry < observed:
            raise ValueError("retry_after_at precedes rate limit observation")
        return status, observed, retry

    def _observation_time(
        self, value: datetime | None, name: str
    ) -> datetime:
        if value is None:
            raise ValueError(f"{name} is required")
        parsed = self._aware(value, name)
        if parsed > self._now() + timedelta(minutes=5):
            raise ValueError(f"{name} is too far in the future")
        return parsed

    def _capabilities(
        self, provider: str, values: list[str]
    ) -> list[str]:
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(item, str) for item in values)
        ):
            raise ValueError("Media Connector capabilities are required")
        normalized = sorted({item.strip() for item in values if item.strip()})
        if len(normalized) != len(values):
            raise ValueError("Media Connector capabilities contain duplicates")
        allowed = self.contract.provider_capabilities[provider]
        if not set(normalized).issubset(allowed):
            raise ValueError("Media Connector capability is not allowed")
        return normalized

    @staticmethod
    def _require_role(principal: Principal, *roles: str) -> None:
        if not principal.has_any_role(*roles):
            raise PermissionError("Media Connector role is not authorized")

    @staticmethod
    def _provider(value: Any) -> str:
        result = str(value or "").strip().lower()
        if result not in REGISTERABLE_CONNECTOR_PROVIDERS:
            raise ValueError("Unsupported Media Connector Provider")
        return result

    @staticmethod
    def _deployment_mode(value: Any) -> str:
        result = str(value or "").strip().lower()
        if result not in DEPLOYMENT_MODES:
            raise ValueError("Unsupported Media Connector deployment mode")
        return result

    @classmethod
    def _protocol_version(cls, value: Any) -> str:
        result = str(value or "").strip()
        if not PROTOCOL_PATTERN.fullmatch(result):
            raise ValueError("Invalid Media Connector protocol version")
        cls._reject_secret_shape(result)
        return result

    @classmethod
    def _idempotency_key(cls, value: Any) -> str:
        result = str(value or "").strip()
        if not IDEMPOTENCY_PATTERN.fullmatch(result):
            raise ValueError("Invalid Media Connector idempotency key")
        cls._reject_secret_shape(result)
        return result

    @staticmethod
    def _connector_ref(value: Any) -> str:
        result = str(value or "").strip()
        if not re.fullmatch(r"mcn_[0-9a-f]{32}", result):
            raise KeyError("Media Connector not found")
        return result

    @staticmethod
    def _required(value: Any, name: str, limit: int) -> str:
        result = str(value or "").strip()
        if not result or len(result) > limit:
            raise ValueError(f"{name} is required")
        return result

    @staticmethod
    def _reject_secret_shape(value: str) -> None:
        lowered = value.lower()
        if any(marker in lowered for marker in SECRET_VALUE_MARKERS):
            raise ValueError("Credential-shaped values are excluded")

    def _now(self) -> datetime:
        return self._aware(self.clock(), "clock")

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must include timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _stored_aware(value: datetime, name: str) -> datetime:
        """Normalize DB timestamps; SQLite may omit an otherwise stored UTC zone."""
        if not isinstance(value, datetime):
            raise ValueError(f"{name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
