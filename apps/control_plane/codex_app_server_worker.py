from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import stat
import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from .security import Principal

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "codex_app_server_image_worker_contracts.json"
)
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "media_agent"
    / "bas182_codex_app_server_image_worker_v1.json"
)
CONTRACT_ID = "kjds-codex-app-server-image-worker-v1"
PROVIDER = "codex_oauth"
PROTOCOL_VERSION = "codex-app-server/0.142.5"
EXPECTED_PROTOCOL_PINS = MappingProxyType(
    {
        "aggregate_v2_canonical_sha256": "064f4e66f3f9efa34601039e80e1c57a5593fdd77bad7a6562ec014cf7452dc2",
        "item_completed_canonical_sha256": "0ebc5cf18b3e4e37b3e5813c7f20faea64682c5b322bdc358d391d3900891b89",
        "turn_completed_canonical_sha256": "ece1a0743df0ea913f259bdb747557d812a3e6e45aed222fa70ebeb996a57a44",
        "canonical_bundle_observation_sha256": "004e2846436659b58b9ce4d71ab7e5a862e4756dc52dc4651d6bef368131f377",
    }
)
EXPECTED_CONTRACT_CONTENT_SHA256 = (
    "4a06aecd5e2e0c1ab4b24fd69ffe2c8253d5b91797518855f0274f33c0cb80c3"
)
EXPECTED_FIXTURE_CONTENT_SHA256 = (
    "14b4db5bef03232f756c071fb2b10735442ad8acfbb3eafd6c26d5d4d7a5a4ef"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REF_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{2,159}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_BASE64_CHARS = 4 * ((MAX_ARTIFACT_BYTES + 2) // 3)
MAX_PROTOCOL_MESSAGES = 32
MAX_PROTOCOL_FIELD_CHARS = 16_384
MAX_PROTOCOL_METADATA_CHARS = 262_144
MAX_PROTOCOL_CONTAINER_ITEMS = 1_024
MAX_PROTOCOL_DEPTH = 12
MAX_RUNTIME_RECEIPT_FRESHNESS = timedelta(minutes=5)
ALLOWED_TRANSPORTS = frozenset({"stdio", "unix"})
WORKER_ROLES = frozenset({"operator", "admin"})
TOOL_CAPABILITIES = MappingProxyType(
    {
        "media.image_generate": "image_generation",
        "media.image_edit": "image_editing",
    }
)
TERMINAL_STATES = frozenset(
    {
        "ARTIFACT_READY",
        "FAILED",
        "LOGIN_REQUIRED",
        "LIMITED",
        "UNKNOWN_OUTCOME",
        "BLOCKED",
    }
)
SAFE_REASON_CODES = frozenset(
    {
        "artifact_verified",
        "image_generation_failed",
        "connector_not_currently_eligible",
        "connector_binding_invalid",
        "transport_not_admitted",
        "protocol_pin_mismatch",
        "protocol_handshake_invalid",
        "protocol_event_unknown",
        "protocol_event_malformed",
        "protocol_event_out_of_order",
        "protocol_identity_mismatch",
        "protocol_completion_time_invalid",
        "image_item_missing",
        "image_item_terminal_semantics_unknown",
        "artifact_path_missing",
        "artifact_path_not_admitted",
        "artifact_symlink_or_reparse",
        "artifact_format_invalid",
        "artifact_result_mismatch",
        "turn_failed_after_artifact",
        "login_required",
        "usage_limited",
        "transport_disconnected_after_dispatch",
        "transport_adapter_failure",
        "readback_only_unknown_outcome",
        "fresh_readback_requires_explicit_resume",
        "durable_claim_invalid",
        "durable_record_failed",
        "principal_role_not_authorized",
        "request_invalid",
    }
)
CODEX_ERROR_STRING_VALUES = frozenset(
    {
        "contextWindowExceeded",
        "usageLimitExceeded",
        "serverOverloaded",
        "cyberPolicy",
        "internalServerError",
        "unauthorized",
        "badRequest",
        "threadRollbackFailed",
        "sandboxError",
        "other",
    }
)
CODEX_HTTP_ERROR_VARIANTS = frozenset(
    {
        "httpConnectionFailed",
        "responseStreamConnectionFailed",
        "responseStreamDisconnected",
        "responseTooManyFailedAttempts",
    }
)


class CodexImageWorkerError(RuntimeError):
    """Base typed error for the bounded BAS-182 protocol adapter."""


class ProtocolContractError(CodexImageWorkerError):
    def __init__(self, reason_code: str) -> None:
        if reason_code not in SAFE_REASON_CODES:
            raise ValueError("Unknown safe reason code")
        super().__init__(reason_code)
        self.reason_code = reason_code


class ProtocolTransportDisconnected(CodexImageWorkerError):
    def __init__(self, *, after_dispatch: bool) -> None:
        super().__init__("transport disconnected")
        self.after_dispatch = bool(after_dispatch)


@dataclass(frozen=True, slots=True)
class ImageWorkerRequest:
    job_ref: str
    tool_name: str
    idempotency_key: str
    request_sha256: str
    data_as_of: datetime
    transport: str = "stdio"
    protocol_version: str = PROTOCOL_VERSION
    explicit_resume: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ImageWorkerRequest:
        allowed = {
            "job_ref",
            "tool_name",
            "idempotency_key",
            "request_sha256",
            "data_as_of",
            "transport",
            "protocol_version",
            "explicit_resume",
        }
        if set(value) - allowed:
            raise ValueError("Image Worker request contains unknown fields")
        data_as_of = value.get("data_as_of")
        if isinstance(data_as_of, str):
            data_as_of = datetime.fromisoformat(data_as_of.replace("Z", "+00:00"))
        if not isinstance(data_as_of, datetime):
            raise ValueError("data_as_of must be a datetime")
        return cls(
            job_ref=str(value.get("job_ref", "")),
            tool_name=str(value.get("tool_name", "")),
            idempotency_key=str(value.get("idempotency_key", "")),
            request_sha256=str(value.get("request_sha256", "")),
            data_as_of=data_as_of,
            transport=str(value.get("transport", "stdio")),
            protocol_version=str(
                value.get("protocol_version", PROTOCOL_VERSION)
            ),
            explicit_resume=value.get("explicit_resume", False),
        )


@dataclass(frozen=True, slots=True)
class WorkerScope:
    tenant_ref: str
    connector_ref: str
    provider: str
    connector_binding_sha256: str
    runtime_protocol_authority_sha256: str
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class DurableDispatchPeek:
    exists: bool
    current_state: str | None
    tenant_ref: str
    connector_ref: str
    provider: str
    connector_binding_sha256: str | None
    runtime_protocol_authority_sha256: str | None
    request_fingerprint_sha256: str
    peek_token_sha256: str
    resume_readback_satisfied: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeProtocolReceipt:
    connector_ref: str
    connector_binding_sha256: str
    protocol_version: str
    codex_cli_version: str
    aggregate_schema_canonical_sha256: str
    item_completed_schema_canonical_sha256: str
    turn_completed_schema_canonical_sha256: str
    canonical_bundle_sha256: str
    actual_transport_kind: str
    transport_adapter_version: str
    transport_adapter_sha256: str
    authority_sha256: str
    checked_at: datetime
    recorded_at: datetime
    effective_at: datetime
    fresh_until: datetime
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class DurableDispatchClaim:
    dispatch_ref: str
    action: Literal["dispatch", "readback", "terminal"]
    current_state: str
    tenant_ref: str
    connector_ref: str
    provider: str
    connector_binding_sha256: str
    runtime_protocol_authority_sha256: str
    request_fingerprint_sha256: str
    thread_id: str
    turn_id: str
    item_id: str
    dispatched_at_ms: int
    readback_deadline_ms: int
    resume_readback_satisfied: bool = False
    sealed_transition: WorkerTransition | None = None
    sealed_transition_sha256: str | None = None
    sealed_evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ProtocolTranscript:
    messages: tuple[Mapping[str, Any], ...]
    runtime_protocol_receipt_sha256: str
    disconnected: bool = False

    @classmethod
    def from_value(cls, value: Any) -> ProtocolTranscript:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ProtocolContractError("protocol_event_malformed")
        if set(value) != {
            "messages",
            "runtime_protocol_receipt_sha256",
            "disconnected",
        }:
            raise ProtocolContractError("protocol_event_unknown")
        messages = value.get("messages")
        if not isinstance(messages, Sequence) or isinstance(
            messages, (str, bytes, bytearray)
        ):
            raise ProtocolContractError("protocol_event_malformed")
        if any(not isinstance(item, Mapping) for item in messages):
            raise ProtocolContractError("protocol_event_malformed")
        _validate_protocol_budget(messages)
        disconnected = value.get("disconnected", False)
        if not isinstance(disconnected, bool):
            raise ProtocolContractError("protocol_event_malformed")
        receipt = value.get("runtime_protocol_receipt_sha256")
        if not isinstance(receipt, str) or not SHA256_PATTERN.fullmatch(receipt):
            raise ProtocolContractError("protocol_pin_mismatch")
        return cls(tuple(messages), receipt, disconnected)


@dataclass(frozen=True, slots=True)
class WorkerTransition:
    state: str
    safe_reason_code: str
    event_chain_sha256: str
    artifact: Mapping[str, Any] | None
    resume_readback_satisfied: bool
    protocol_dispatch_attempt_count: int
    protocol_readback_attempt_count: int


class DurableImageDispatchPort(Protocol):
    def peek(
        self,
        *,
        tenant_ref: str,
        connector_ref: str,
        request: ImageWorkerRequest,
        request_fingerprint_sha256: str,
    ) -> DurableDispatchPeek: ...

    def claim(
        self,
        *,
        scope: WorkerScope,
        request: ImageWorkerRequest,
        request_fingerprint_sha256: str,
        expected_peek_token_sha256: str,
    ) -> DurableDispatchClaim: ...

    def record(
        self,
        *,
        scope: WorkerScope,
        claim: DurableDispatchClaim,
        transition: WorkerTransition,
    ) -> str | None: ...


class TerminalTransitionAuthority(Protocol):
    def verify(
        self,
        *,
        scope: WorkerScope,
        claim: DurableDispatchClaim,
        transition: WorkerTransition,
        evidence_ref: str | None,
        sealed_transition_sha256: str,
    ) -> None: ...


class RuntimeProtocolAuthority(Protocol):
    def verify(
        self,
        *,
        descriptor: Mapping[str, Any],
        connector_ref: str,
        checked_at: datetime,
        contract: CodexImageWorkerContract,
        transport_descriptor: TransportDescriptor,
    ) -> RuntimeProtocolReceipt: ...


@dataclass(frozen=True, slots=True)
class TransportDescriptor:
    actual_transport_kind: str
    adapter_version: str
    adapter_sha256: str


class CodexAppServerTransport(Protocol):
    def descriptor(self) -> TransportDescriptor: ...

    def dispatch(
        self,
        *,
        claim: DurableDispatchClaim,
        request: ImageWorkerRequest,
    ) -> ProtocolTranscript | Mapping[str, Any]: ...

    def readback(
        self,
        *,
        claim: DurableDispatchClaim,
    ) -> ProtocolTranscript | Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ImageWorkerObservation:
    contract_id: str
    state: str
    safe_reason_code: str
    job_ref: str
    dispatch_ref: str | None
    connector_ref: str
    provider: str
    connector_binding_sha256: str | None
    checked_at: str
    data_as_of: str
    request_fingerprint_sha256: str
    protocol_version: str
    aggregate_schema_canonical_sha256: str
    item_completed_schema_canonical_sha256: str
    turn_completed_schema_canonical_sha256: str
    contract_sha256: str
    fixture_sha256: str
    event_chain_sha256: str | None
    projection_sha256: str
    artifact: Mapping[str, Any] | None
    protocol_dispatch_attempt_count: int
    protocol_readback_attempt_count: int
    automatic_provider_retry: bool = False
    identity_rotation_count: int = 0
    cross_scope_leakage_count: int = 0
    fact_promoted: bool = False
    finance_entry_persisted: bool = False
    approval_granted: bool = False
    permit_granted: bool = False
    pilot_started: bool = False
    outbox_emitted: bool = False
    platform_write: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "state": self.state,
            "safe_reason_code": self.safe_reason_code,
            "job_ref": self.job_ref,
            "dispatch_ref": self.dispatch_ref,
            "connector_ref": self.connector_ref,
            "provider": self.provider,
            "connector_binding_sha256": self.connector_binding_sha256,
            "checked_at": self.checked_at,
            "data_as_of": self.data_as_of,
            "request_fingerprint_sha256": self.request_fingerprint_sha256,
            "protocol_version": self.protocol_version,
            "aggregate_schema_canonical_sha256": (
                self.aggregate_schema_canonical_sha256
            ),
            "item_completed_schema_canonical_sha256": (
                self.item_completed_schema_canonical_sha256
            ),
            "turn_completed_schema_canonical_sha256": (
                self.turn_completed_schema_canonical_sha256
            ),
            "contract_sha256": self.contract_sha256,
            "fixture_sha256": self.fixture_sha256,
            "event_chain_sha256": self.event_chain_sha256,
            "projection_sha256": self.projection_sha256,
            "artifact": dict(self.artifact) if self.artifact else None,
            "protocol_dispatch_attempt_count": self.protocol_dispatch_attempt_count,
            "protocol_readback_attempt_count": self.protocol_readback_attempt_count,
            "automatic_provider_retry": self.automatic_provider_retry,
            "identity_rotation_count": self.identity_rotation_count,
            "cross_scope_leakage_count": self.cross_scope_leakage_count,
            "fact_promoted": self.fact_promoted,
            "finance_entry_persisted": self.finance_entry_persisted,
            "approval_granted": self.approval_granted,
            "permit_granted": self.permit_granted,
            "pilot_started": self.pilot_started,
            "outbox_emitted": self.outbox_emitted,
            "platform_write": self.platform_write,
        }


class CodexImageWorkerContract:
    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        repository_payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        if payload is not None and json.loads(json.dumps(payload)) != repository_payload:
            raise RuntimeError("Caller contract does not match repository authority")
        contract_body = dict(repository_payload)
        contract_seal = contract_body.pop("content_sha256", None)
        if (
            contract_seal != EXPECTED_CONTRACT_CONTENT_SHA256
            or not hmac.compare_digest(contract_seal, _hash_json(contract_body))
        ):
            raise RuntimeError("Codex Image Worker contract seal drifted")
        self.payload = repository_payload
        if self.payload.get("contract_id") != CONTRACT_ID:
            raise RuntimeError("Codex Image Worker contract id drifted")
        pin = self.payload.get("protocol_pin")
        if not isinstance(pin, dict):
            raise RuntimeError("Codex Image Worker protocol pin is missing")
        if pin.get("codex_cli_version") != "codex-cli 0.142.5":
            raise RuntimeError("Codex Image Worker CLI pin drifted")
        if pin.get("raw_aggregate_sha256_is_authoritative") is not False:
            raise RuntimeError("Raw aggregate schema hash cannot be authoritative")
        if any(pin.get(field) != expected for field, expected in EXPECTED_PROTOCOL_PINS.items()):
            raise RuntimeError("Codex Image Worker canonical pin drifted")
        image = self.payload.get("image_item_contract")
        if not isinstance(image, dict) or image.get("item_type") != "imageGeneration":
            raise RuntimeError("Codex Image Worker item contract drifted")
        if image.get("mcp_image_tool") != "not_admitted_future_contract":
            raise RuntimeError("MCP image result is outside BAS-182")
        observation = self.payload.get("observation_contract")
        if not isinstance(observation, dict) or any(
            observation.get(flag) is not False
            for flag in (
                "fact_promoted",
                "finance_entry_persisted",
                "approval_granted",
                "permit_granted",
                "pilot_started",
                "outbox_emitted",
                "platform_write",
            )
        ):
            raise RuntimeError("Codex Image Worker authority boundary drifted")
        scope_contract = self.payload.get("scope_contract")
        if not isinstance(scope_contract, dict) or (
            set(scope_contract.get("dispatch_roles", ())) != WORKER_ROLES
            or set(scope_contract.get("readback_roles", ())) != WORKER_ROLES
            or scope_contract.get("role_check_before_durable_peek") is not True
        ):
            raise RuntimeError("Codex Image Worker role policy drifted")
        durability = self.payload.get("durability_contract")
        if not isinstance(durability, dict) or any(
            durability.get(field) is not True
            for field in (
                "read_only_peek_before_claim",
                "atomic_claim_requires_expected_peek_token",
                "atomic_claim_must_match_peek_state_and_resume_flag",
                "prospective_dispatch_requires_current_eligible_before_claim",
            )
        ):
            raise RuntimeError("Codex Image Worker durability policy drifted")
        stable_authority_fields = {
            "connector_ref",
            "connector_binding_sha256",
            "protocol_version",
            "codex_cli_version",
            "aggregate_schema_canonical_sha256",
            "item_completed_schema_canonical_sha256",
            "turn_completed_schema_canonical_sha256",
            "canonical_bundle_sha256",
            "actual_transport_kind",
            "transport_adapter_version",
            "transport_adapter_sha256",
        }
        if set(durability.get("stable_runtime_protocol_authority_fields", ())) != (
            stable_authority_fields
        ):
            raise RuntimeError("Runtime protocol authority fields drifted")
        transport_policy = self.payload.get("transports")
        if not isinstance(transport_policy, dict) or any(
            transport_policy.get(field) is not True
            for field in (
                "runtime_receipt_binding_required",
                "descriptor_revalidated_before_durable_peek",
            )
        ) or transport_policy.get("selection_authority") != (
            "server_owned_transport_descriptor"
        ):
            raise RuntimeError("Transport authority policy drifted")
        budget = self.payload.get("protocol_budget")
        expected_budget = {
            "maximum_message_count": MAX_PROTOCOL_MESSAGES,
            "maximum_non_artifact_field_characters": MAX_PROTOCOL_FIELD_CHARS,
            "maximum_non_artifact_aggregate_characters": (
                MAX_PROTOCOL_METADATA_CHARS
            ),
            "maximum_container_items": MAX_PROTOCOL_CONTAINER_ITEMS,
            "maximum_depth": MAX_PROTOCOL_DEPTH,
            "maximum_base64_characters": MAX_BASE64_CHARS,
            "integer_range": "signed_int64",
            "nonfinite_float_allowed": False,
            "budget_enforced_before_canonical_hash_and_artifact_io": True,
            "event_chain_projection": "bounded_redacted_protocol_projection_v1",
        }
        if budget != expected_budget:
            raise RuntimeError("Protocol resource budget drifted")
        self.sha256 = contract_seal
        self.aggregate_schema_sha256 = pin["aggregate_v2_canonical_sha256"]
        self.item_schema_sha256 = pin["item_completed_canonical_sha256"]
        self.turn_schema_sha256 = pin["turn_completed_canonical_sha256"]
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        fixture_seal = fixture.pop("content_sha256", None)
        if (
            fixture_seal != EXPECTED_FIXTURE_CONTENT_SHA256
            or not hmac.compare_digest(fixture_seal, _hash_json(fixture))
        ):
            raise RuntimeError("Codex Image Worker fixture seal drifted")
        if fixture.get("protocol_pin") != {
            key: pin[key]
            for key in (
                "canonicalization",
                "aggregate_v2_canonical_sha256",
                "item_completed_canonical_sha256",
                "turn_completed_canonical_sha256",
                "canonical_bundle_observation_sha256",
            )
        }:
            raise RuntimeError("Codex Image Worker fixture protocol pin drifted")
        self.fixture_content_sha256 = fixture_seal
        # Semantic fixture identity is canonical; whitespace and key order are not.
        self.fixture_sha256 = fixture_seal


class CodexAppServerImageWorker:
    def __init__(
        self,
        *,
        connector_registry: Any,
        dispatch_port: DurableImageDispatchPort,
        terminal_authority: TerminalTransitionAuthority,
        runtime_protocol_authority: RuntimeProtocolAuthority,
        transport: CodexAppServerTransport,
        artifact_roots: Mapping[str, Path],
        clock: Callable[[], datetime],
        contract: CodexImageWorkerContract | None = None,
    ) -> None:
        self.connector_registry = connector_registry
        self.dispatch_port = dispatch_port
        self.terminal_authority = terminal_authority
        self.runtime_protocol_authority = runtime_protocol_authority
        self.transport = transport
        self.transport_descriptor = self._validate_transport_descriptor(
            transport.descriptor()
        )
        self.clock = clock
        self.contract = contract or CodexImageWorkerContract()
        self.fixture_sha256 = self.contract.fixture_sha256
        self.artifact_roots = {
            _required_ref(ref, "connector_ref"): Path(root)
            for ref, root in artifact_roots.items()
        }

    def run(
        self,
        *,
        principal: Principal,
        connector_ref: str,
        request: ImageWorkerRequest | Mapping[str, Any],
    ) -> ImageWorkerObservation:
        checked_at = _aware(self.clock(), "trusted worker clock")
        try:
            current_transport_descriptor = self._validate_transport_descriptor(
                self.transport.descriptor()
            )
            if current_transport_descriptor != self.transport_descriptor:
                raise ProtocolContractError("transport_not_admitted")
        except Exception:
            return self._blocked(
                connector_ref=connector_ref,
                request=request,
                checked_at=checked_at,
                reason="transport_not_admitted",
            )
        try:
            parsed = (
                request
                if isinstance(request, ImageWorkerRequest)
                else ImageWorkerRequest.from_mapping(request)
            )
            parsed = self._validate_request(parsed, checked_at)
            if (
                current_transport_descriptor.actual_transport_kind
                not in ALLOWED_TRANSPORTS
                or parsed.transport
                != current_transport_descriptor.actual_transport_kind
            ):
                raise ProtocolContractError("transport_not_admitted")
        except ProtocolContractError as exc:
            return self._blocked(
                connector_ref=connector_ref,
                request=request,
                checked_at=checked_at,
                reason=exc.reason_code,
            )
        except (TypeError, ValueError):
            return self._blocked(
                connector_ref=connector_ref,
                request=request,
                checked_at=checked_at,
                reason="request_invalid",
            )
        try:
            connector_ref = _required_ref(connector_ref, "connector_ref")
            tenant_ref = _required_text(principal.tenant_ref, "tenant_ref", 160)
        except (AttributeError, TypeError, ValueError):
            return self._blocked(
                connector_ref=connector_ref,
                request=parsed,
                checked_at=checked_at,
                reason="request_invalid",
            )
        if not principal.has_any_role(*WORKER_ROLES):
            return self._blocked(
                connector_ref=connector_ref,
                request=parsed,
                checked_at=checked_at,
                reason="principal_role_not_authorized",
            )
        fingerprint = self._request_fingerprint(principal, connector_ref, parsed)
        try:
            peek = self.dispatch_port.peek(
                tenant_ref=tenant_ref,
                connector_ref=connector_ref,
                request=parsed,
                request_fingerprint_sha256=fingerprint,
            )
            self._validate_peek(
                peek,
                tenant_ref=tenant_ref,
                connector_ref=connector_ref,
                fingerprint=fingerprint,
            )
        except Exception:
            return self._observation(
                parsed,
                connector_ref=connector_ref,
                binding_sha256=None,
                checked_at=checked_at,
                fingerprint=fingerprint,
                state="BLOCKED",
                reason="durable_claim_invalid",
            )
        prospective_dispatch = (
            not peek.exists
            or peek.current_state == "READY_TO_DISPATCH"
            or (
                peek.current_state in {"LOGIN_REQUIRED", "LIMITED"}
                and parsed.explicit_resume
                and peek.resume_readback_satisfied
            )
        )
        descriptor: Mapping[str, Any]
        try:
            current = (
                self.connector_registry.require_eligible(
                    tenant_ref=tenant_ref,
                    connector_ref=connector_ref,
                    provider=PROVIDER,
                    required_capabilities={TOOL_CAPABILITIES[parsed.tool_name]},
                    as_of=checked_at,
                )
                if prospective_dispatch
                else self.connector_registry.get(
                    principal=principal,
                    connector_ref=connector_ref,
                )
            )
            descriptor = current["connector"]
            self._validate_descriptor(
                descriptor,
                principal=principal,
                connector_ref=connector_ref,
                required_capability=TOOL_CAPABILITIES[parsed.tool_name],
            )
            runtime_receipt = self.runtime_protocol_authority.verify(
                descriptor=descriptor,
                connector_ref=connector_ref,
                checked_at=checked_at,
                contract=self.contract,
                transport_descriptor=current_transport_descriptor,
            )
            self._validate_runtime_receipt(
                runtime_receipt,
                descriptor=descriptor,
                checked_at=checked_at,
                transport_descriptor=current_transport_descriptor,
            )
            if peek.exists and (
                peek.connector_binding_sha256 != descriptor.get("binding_sha256")
                or (
                    peek.runtime_protocol_authority_sha256 is not None
                    and peek.runtime_protocol_authority_sha256
                    != runtime_receipt.authority_sha256
                )
            ):
                raise PermissionError("durable binding is no longer current")
        except Exception:
            return self._observation(
                parsed,
                connector_ref=connector_ref,
                binding_sha256=None,
                checked_at=checked_at,
                fingerprint=fingerprint,
                state="BLOCKED",
                reason=(
                    "connector_not_currently_eligible"
                    if prospective_dispatch
                    else "connector_binding_invalid"
                ),
            )
        binding_sha256 = str(descriptor["binding_sha256"])
        scope = WorkerScope(
            tenant_ref=tenant_ref,
            connector_ref=connector_ref,
            provider=PROVIDER,
            connector_binding_sha256=binding_sha256,
            runtime_protocol_authority_sha256=runtime_receipt.authority_sha256,
            checked_at=checked_at,
        )
        try:
            claim = self.dispatch_port.claim(
                scope=scope,
                request=parsed,
                request_fingerprint_sha256=fingerprint,
                expected_peek_token_sha256=peek.peek_token_sha256,
            )
            self._validate_claim(
                claim,
                scope=scope,
                fingerprint=fingerprint,
                peek=peek,
            )
            expected_actions = (
                {"dispatch"}
                if prospective_dispatch
                else {
                    "LOGIN_REQUIRED": {"readback"},
                    "LIMITED": {"readback"},
                    "UNKNOWN_OUTCOME": {"readback"},
                    "ARTIFACT_READY": {"terminal"},
                    "FAILED": {"terminal"},
                }.get(str(peek.current_state), set())
            )
            if claim.action not in expected_actions:
                raise ValueError("claim changed after durable peek")
        except Exception:
            return self._observation(
                parsed,
                connector_ref=connector_ref,
                binding_sha256=binding_sha256,
                checked_at=checked_at,
                fingerprint=fingerprint,
                state="BLOCKED",
                reason="durable_claim_invalid",
            )
        if claim.action == "terminal":
            transition = claim.sealed_transition
            if transition is None:
                return self._observation(
                    parsed,
                    connector_ref=connector_ref,
                    binding_sha256=binding_sha256,
                    checked_at=checked_at,
                    fingerprint=fingerprint,
                    dispatch_ref=claim.dispatch_ref,
                    state="BLOCKED",
                    reason="durable_claim_invalid",
                )
            try:
                self.terminal_authority.verify(
                    scope=scope,
                    claim=claim,
                    transition=transition,
                    evidence_ref=claim.sealed_evidence_ref,
                    sealed_transition_sha256=str(
                        claim.sealed_transition_sha256 or ""
                    ),
                )
            except Exception:
                return self._observation(
                    parsed,
                    connector_ref=connector_ref,
                    binding_sha256=binding_sha256,
                    checked_at=checked_at,
                    fingerprint=fingerprint,
                    dispatch_ref=claim.dispatch_ref,
                    state="BLOCKED",
                    reason="durable_claim_invalid",
                )
            artifact = dict(transition.artifact) if transition.artifact else None
            if artifact is not None:
                artifact["evidence_ref"] = claim.sealed_evidence_ref
            return self._observation(
                parsed,
                connector_ref=connector_ref,
                binding_sha256=binding_sha256,
                checked_at=checked_at,
                fingerprint=fingerprint,
                dispatch_ref=claim.dispatch_ref,
                state=transition.state,
                reason=transition.safe_reason_code,
                event_chain_sha256=transition.event_chain_sha256,
                artifact=artifact,
                protocol_dispatch_attempt_count=0,
                protocol_readback_attempt_count=0,
            )
        if claim.action == "dispatch":
            if claim.current_state in {"LOGIN_REQUIRED", "LIMITED"} and not (
                parsed.explicit_resume and claim.resume_readback_satisfied
            ):
                return self._observation(
                    parsed,
                    connector_ref=connector_ref,
                    binding_sha256=binding_sha256,
                    checked_at=checked_at,
                    fingerprint=fingerprint,
                    dispatch_ref=claim.dispatch_ref,
                    state=claim.current_state,
                    reason="fresh_readback_requires_explicit_resume",
                )
        elif claim.current_state == "UNKNOWN_OUTCOME":
            # A durable dispatch claim forces readback even when resume was requested.
            pass
        dispatch_attempts = int(claim.action == "dispatch")
        readback_attempts = int(claim.action == "readback")
        try:
            raw = (
                self.transport.dispatch(claim=claim, request=parsed)
                if claim.action == "dispatch"
                else self.transport.readback(claim=claim)
            )
            transcript = ProtocolTranscript.from_value(raw)
            if not hmac.compare_digest(
                transcript.runtime_protocol_receipt_sha256,
                runtime_receipt.receipt_sha256,
            ):
                raise ProtocolContractError("protocol_pin_mismatch")
            transition = self._project_transcript(
                transcript,
                claim=claim,
                connector_ref=connector_ref,
            )
        except ProtocolTransportDisconnected as exc:
            reason = (
                "transport_disconnected_after_dispatch"
                if exc.after_dispatch or claim.current_state == "UNKNOWN_OUTCOME"
                else "protocol_handshake_invalid"
            )
            transition = WorkerTransition(
                state="UNKNOWN_OUTCOME",
                safe_reason_code=reason,
                event_chain_sha256=_hash_json(
                    {"dispatch_ref": claim.dispatch_ref, "reason": reason}
                ),
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        except ProtocolContractError as exc:
            transition = WorkerTransition(
                state="UNKNOWN_OUTCOME",
                safe_reason_code=exc.reason_code,
                event_chain_sha256=_hash_json(
                    {
                        "dispatch_ref": claim.dispatch_ref,
                        "reason": exc.reason_code,
                    }
                ),
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        except Exception:
            transition = WorkerTransition(
                state="UNKNOWN_OUTCOME",
                safe_reason_code="transport_adapter_failure",
                event_chain_sha256=_hash_json(
                    {
                        "dispatch_ref": claim.dispatch_ref,
                        "reason": "transport_adapter_failure",
                    }
                ),
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        evidence_ref: str | None = None
        try:
            evidence_ref = self.dispatch_port.record(
                scope=scope,
                claim=claim,
                transition=transition,
            )
            if evidence_ref is not None and not re.fullmatch(
                r"evd_[0-9a-f]{32}", evidence_ref
            ):
                raise ValueError("invalid evidence ref")
            if transition.state == "ARTIFACT_READY" and evidence_ref is None:
                raise ValueError("artifact terminal Evidence is missing")
            if transition.state in {"ARTIFACT_READY", "FAILED"}:
                terminal_peek = self.dispatch_port.peek(
                    tenant_ref=tenant_ref,
                    connector_ref=connector_ref,
                    request=parsed,
                    request_fingerprint_sha256=fingerprint,
                )
                self._validate_peek(
                    terminal_peek,
                    tenant_ref=tenant_ref,
                    connector_ref=connector_ref,
                    fingerprint=fingerprint,
                )
                if (
                    terminal_peek.current_state != transition.state
                    or terminal_peek.connector_binding_sha256
                    != scope.connector_binding_sha256
                    or terminal_peek.runtime_protocol_authority_sha256
                    != scope.runtime_protocol_authority_sha256
                ):
                    raise ValueError("recorded terminal peek drifted")
                terminal_claim = self.dispatch_port.claim(
                    scope=scope,
                    request=parsed,
                    request_fingerprint_sha256=fingerprint,
                    expected_peek_token_sha256=terminal_peek.peek_token_sha256,
                )
                self._validate_claim(
                    terminal_claim,
                    scope=scope,
                    fingerprint=fingerprint,
                    peek=terminal_peek,
                )
                if (
                    terminal_claim.action != "terminal"
                    or terminal_claim.sealed_transition != transition
                    or terminal_claim.sealed_evidence_ref != evidence_ref
                    or not terminal_claim.sealed_transition_sha256
                ):
                    raise ValueError("recorded terminal projection drifted")
                self.terminal_authority.verify(
                    scope=scope,
                    claim=terminal_claim,
                    transition=transition,
                    evidence_ref=evidence_ref,
                    sealed_transition_sha256=terminal_claim.sealed_transition_sha256,
                )
        except Exception:
            transition = WorkerTransition(
                state="UNKNOWN_OUTCOME",
                safe_reason_code="durable_record_failed",
                event_chain_sha256=transition.event_chain_sha256,
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=transition.protocol_dispatch_attempt_count,
                protocol_readback_attempt_count=transition.protocol_readback_attempt_count,
            )
            evidence_ref = None
        artifact = dict(transition.artifact) if transition.artifact else None
        if artifact is not None:
            artifact["evidence_ref"] = evidence_ref
        return self._observation(
            parsed,
            connector_ref=connector_ref,
            binding_sha256=binding_sha256,
            checked_at=checked_at,
            fingerprint=fingerprint,
            dispatch_ref=claim.dispatch_ref,
            state=transition.state,
            reason=transition.safe_reason_code,
            event_chain_sha256=transition.event_chain_sha256,
            artifact=artifact,
            protocol_dispatch_attempt_count=transition.protocol_dispatch_attempt_count,
            protocol_readback_attempt_count=transition.protocol_readback_attempt_count,
        )

    def _project_transcript(
        self,
        transcript: ProtocolTranscript,
        *,
        claim: DurableDispatchClaim,
        connector_ref: str,
    ) -> WorkerTransition:
        dispatch_attempts = int(claim.action == "dispatch")
        readback_attempts = int(claim.action == "readback")
        if transcript.disconnected:
            raise ProtocolTransportDisconnected(after_dispatch=True)
        _validate_protocol_budget(transcript.messages)
        messages = list(transcript.messages)
        self._validate_handshake(messages)
        events = messages[3:]
        if not events:
            raise ProtocolContractError("protocol_event_malformed")
        image_started: Mapping[str, Any] | None = None
        image_completed: Mapping[str, Any] | None = None
        turn_started: Mapping[str, Any] | None = None
        turn_completed: Mapping[str, Any] | None = None
        resume_ready = False
        paused_readback_observed = False
        for message in events:
            if turn_completed is not None:
                raise ProtocolContractError("protocol_event_out_of_order")
            if set(message) != {"direction", "method", "params"}:
                raise ProtocolContractError("protocol_event_unknown")
            if message.get("direction") != "server_notification":
                raise ProtocolContractError("protocol_event_unknown")
            method = message.get("method")
            params = message.get("params")
            if not isinstance(params, Mapping):
                raise ProtocolContractError("protocol_event_malformed")
            if method == "turn/started":
                if (
                    paused_readback_observed
                    or turn_started is not None
                    or image_started is not None
                    or image_completed is not None
                ):
                    raise ProtocolContractError("protocol_event_out_of_order")
                self._validate_turn_started(params, claim)
                turn_started = params
            elif method == "item/started":
                if (
                    paused_readback_observed
                    or turn_started is None
                    or image_started is not None
                    or image_completed is not None
                ):
                    raise ProtocolContractError("protocol_event_out_of_order")
                self._validate_item_started(params, claim)
                image_started = params
            elif method == "item/completed":
                if (
                    turn_started is None
                    or image_started is None
                    or image_completed is not None
                    or turn_completed is not None
                ):
                    raise ProtocolContractError("protocol_event_out_of_order")
                self._validate_item_identity(params, claim, completed=True)
                image_completed = params
            elif method == "turn/completed":
                if turn_started is None or turn_completed is not None:
                    raise ProtocolContractError("protocol_event_out_of_order")
                self._validate_turn_completed_identity(
                    params,
                    claim,
                    image_started=image_started,
                    image_completed=image_completed,
                    turn_started=turn_started,
                )
                turn_completed = params
            elif method == "account/updated":
                if (
                    claim.current_state != "LOGIN_REQUIRED"
                    or paused_readback_observed
                    or turn_started is not None
                    or image_started is not None
                    or image_completed is not None
                    or turn_completed is not None
                ):
                    raise ProtocolContractError("protocol_event_out_of_order")
                resume_ready = self._account_ready(params)
                paused_readback_observed = True
            elif method == "account/rateLimits/updated":
                if (
                    claim.current_state != "LIMITED"
                    or paused_readback_observed
                    or turn_started is not None
                    or image_started is not None
                    or image_completed is not None
                    or turn_completed is not None
                ):
                    raise ProtocolContractError("protocol_event_out_of_order")
                resume_ready = self._rate_limit_ready(params, claim)
                paused_readback_observed = True
            else:
                raise ProtocolContractError("protocol_event_unknown")
        event_hash = _bounded_event_chain_sha256(messages)
        no_media_events = (
            turn_started is None
            and image_started is None
            and image_completed is None
            and turn_completed is None
        )
        if resume_ready and no_media_events:
            return WorkerTransition(
                state=claim.current_state,
                safe_reason_code="fresh_readback_requires_explicit_resume",
                event_chain_sha256=event_hash,
                artifact=None,
                resume_readback_satisfied=True,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        if (
            paused_readback_observed
            and no_media_events
        ):
            return WorkerTransition(
                state=claim.current_state,
                safe_reason_code=(
                    "login_required"
                    if claim.current_state == "LOGIN_REQUIRED"
                    else "usage_limited"
                ),
                event_chain_sha256=event_hash,
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        if turn_completed is None:
            raise ProtocolContractError("protocol_event_out_of_order")
        turn_state, turn_reason = self._turn_state(turn_completed)
        if turn_state in {"LOGIN_REQUIRED", "LIMITED"}:
            return WorkerTransition(
                state=turn_state,
                safe_reason_code=turn_reason,
                event_chain_sha256=event_hash,
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        if image_completed is None:
            raise ProtocolContractError("image_item_missing")
        item = image_completed["item"]
        item_status = item["status"]
        if item_status == "failed" and item["result"] == "" and item.get(
            "savedPath"
        ) is None:
            if (
                set(item) != {"id", "result", "status", "type", "revisedPrompt"}
                or not isinstance(item.get("revisedPrompt"), (str, type(None)))
                or turn_completed["turn"].get("status") != "failed"
            ):
                raise ProtocolContractError(
                    "image_item_terminal_semantics_unknown"
                )
            return WorkerTransition(
                state="FAILED",
                safe_reason_code="image_generation_failed",
                event_chain_sha256=event_hash,
                artifact=None,
                resume_readback_satisfied=False,
                protocol_dispatch_attempt_count=dispatch_attempts,
                protocol_readback_attempt_count=readback_attempts,
            )
        if item_status != "completed":
            raise ProtocolContractError("image_item_terminal_semantics_unknown")
        if set(item) != {
            "id",
            "result",
            "status",
            "type",
            "revisedPrompt",
            "savedPath",
        } or not isinstance(item.get("revisedPrompt"), (str, type(None))):
            raise ProtocolContractError("image_item_terminal_semantics_unknown")
        if turn_state != "ARTIFACT_READY":
            raise ProtocolContractError("turn_failed_after_artifact")
        artifact = self._artifact_receipt(
            connector_ref=connector_ref,
            saved_path=item.get("savedPath"),
            encoded_result=item.get("result"),
        )
        return WorkerTransition(
            state="ARTIFACT_READY",
            safe_reason_code="artifact_verified",
            event_chain_sha256=event_hash,
            artifact=MappingProxyType(artifact),
            resume_readback_satisfied=False,
            protocol_dispatch_attempt_count=dispatch_attempts,
            protocol_readback_attempt_count=readback_attempts,
        )

    def _validate_handshake(self, messages: list[Mapping[str, Any]]) -> None:
        if len(messages) < 4:
            raise ProtocolContractError("protocol_handshake_invalid")
        request, response, initialized = messages[:3]
        if set(request) != {"direction", "id", "method", "params"} or (
            request.get("direction"), request.get("method")
        ) != ("client_request", "initialize"):
            raise ProtocolContractError("protocol_handshake_invalid")
        params = request.get("params")
        if not isinstance(params, Mapping) or set(params) != {
            "clientInfo",
            "capabilities",
        }:
            raise ProtocolContractError("protocol_handshake_invalid")
        client = params.get("clientInfo")
        capabilities = params.get("capabilities")
        if not isinstance(client, Mapping) or not isinstance(capabilities, Mapping):
            raise ProtocolContractError("protocol_handshake_invalid")
        if set(client) != {"name", "title", "version"} or not all(
            isinstance(client.get(field), str) and client.get(field)
            for field in ("name", "title", "version")
        ):
            raise ProtocolContractError("protocol_handshake_invalid")
        if capabilities != {"experimentalApi": False}:
            raise ProtocolContractError("protocol_handshake_invalid")
        if set(response) != {"direction", "id", "result"} or (
            response.get("direction") != "server_response"
            or response.get("id") != request.get("id")
        ):
            raise ProtocolContractError("protocol_handshake_invalid")
        result = response.get("result")
        if not isinstance(result, Mapping) or set(result) != {"serverInfo"}:
            raise ProtocolContractError("protocol_handshake_invalid")
        server = result.get("serverInfo")
        if (
            not isinstance(server, Mapping)
            or set(server) != {"name", "version"}
            or server.get("name") != "codex-app-server"
            or server.get("version") != "0.142.5"
        ):
            raise ProtocolContractError("protocol_pin_mismatch")
        if set(initialized) != {"direction", "method"} or initialized != {
            "direction": "client_notification",
            "method": "initialized",
        }:
            raise ProtocolContractError("protocol_handshake_invalid")
        initialize_count = sum(
            item.get("method") == "initialize" for item in messages
        )
        initialized_count = sum(
            item.get("method") == "initialized" for item in messages
        )
        if initialize_count != 1 or initialized_count != 1:
            raise ProtocolContractError("protocol_handshake_invalid")

    @staticmethod
    def _validate_turn_started(
        params: Mapping[str, Any], claim: DurableDispatchClaim
    ) -> None:
        if set(params) != {"turn"} or not isinstance(params.get("turn"), Mapping):
            raise ProtocolContractError("protocol_event_unknown")
        turn = params["turn"]
        if set(turn) != {
            "id",
            "items",
            "status",
            "itemsView",
            "error",
            "startedAt",
            "completedAt",
            "durationMs",
        }:
            raise ProtocolContractError("protocol_event_unknown")
        if (
            turn.get("id") != claim.turn_id
            or turn.get("status") != "inProgress"
            or turn.get("items") != []
            or turn.get("itemsView") != "full"
            or turn.get("error") is not None
            or isinstance(turn.get("startedAt"), bool)
            or not isinstance(turn.get("startedAt"), int)
            or not 0 <= turn["startedAt"] <= 253_402_300_799
            or not claim.dispatched_at_ms
            <= turn["startedAt"] * 1000
            <= claim.readback_deadline_ms
            or turn.get("completedAt") is not None
            or turn.get("durationMs") is not None
        ):
            raise ProtocolContractError("protocol_identity_mismatch")

    def _validate_item_started(
        self, params: Mapping[str, Any], claim: DurableDispatchClaim
    ) -> None:
        self._validate_item_identity(params, claim, completed=False)
        item = params["item"]
        if (
            set(item) != {"id", "result", "status", "type", "revisedPrompt"}
            or item.get("status") != "in_progress"
            or item.get("result") != ""
            or item.get("revisedPrompt") is not None
        ):
            raise ProtocolContractError("protocol_event_malformed")

    @staticmethod
    def _validate_item_identity(
        params: Mapping[str, Any],
        claim: DurableDispatchClaim,
        *,
        completed: bool,
    ) -> None:
        expected = {"threadId", "turnId", "item"}
        if completed:
            expected.add("completedAtMs")
        else:
            expected.add("startedAtMs")
        if set(params) != expected or not isinstance(params.get("item"), Mapping):
            raise ProtocolContractError("protocol_event_unknown")
        if (
            params.get("threadId") != claim.thread_id
            or params.get("turnId") != claim.turn_id
        ):
            raise ProtocolContractError("protocol_identity_mismatch")
        item = params["item"]
        allowed = {"id", "result", "status", "type", "revisedPrompt", "savedPath"}
        required = {"id", "result", "status", "type"}
        if set(item) - allowed or not required.issubset(item):
            raise ProtocolContractError("protocol_event_unknown")
        if item.get("type") != "imageGeneration" or item.get("id") != claim.item_id:
            raise ProtocolContractError("protocol_identity_mismatch")
        if not isinstance(item.get("result"), str) or not isinstance(
            item.get("status"), str
        ):
            raise ProtocolContractError("protocol_event_malformed")
        if completed:
            completed_at = params.get("completedAtMs")
            if (
                isinstance(completed_at, bool)
                or not isinstance(completed_at, int)
                or not claim.dispatched_at_ms
                <= completed_at
                <= claim.readback_deadline_ms
            ):
                raise ProtocolContractError("protocol_completion_time_invalid")
        else:
            started_at = params.get("startedAtMs")
            if (
                isinstance(started_at, bool)
                or not isinstance(started_at, int)
                or not claim.dispatched_at_ms <= started_at <= claim.readback_deadline_ms
            ):
                raise ProtocolContractError("protocol_completion_time_invalid")

    @staticmethod
    def _validate_turn_completed_identity(
        params: Mapping[str, Any],
        claim: DurableDispatchClaim,
        *,
        image_started: Mapping[str, Any] | None,
        image_completed: Mapping[str, Any] | None,
        turn_started: Mapping[str, Any],
    ) -> None:
        if set(params) != {"threadId", "turn"} or not isinstance(
            params.get("turn"), Mapping
        ):
            raise ProtocolContractError("protocol_event_unknown")
        turn = params["turn"]
        required = {
            "id",
            "items",
            "status",
            "error",
            "completedAt",
            "durationMs",
            "itemsView",
            "startedAt",
        }
        if set(turn) != required:
            raise ProtocolContractError("protocol_event_unknown")
        if params.get("threadId") != claim.thread_id or turn.get("id") != claim.turn_id:
            raise ProtocolContractError("protocol_identity_mismatch")
        if not isinstance(turn.get("items"), list):
            raise ProtocolContractError("protocol_event_malformed")
        if turn.get("itemsView") != "full":
            raise ProtocolContractError("protocol_event_malformed")
        status = turn.get("status")
        error = turn.get("error")
        if status == "completed":
            if error is not None:
                raise ProtocolContractError("protocol_event_malformed")
        elif status == "failed" and error is not None:
            CodexAppServerImageWorker._validate_turn_error(error)
        else:
            raise ProtocolContractError("protocol_event_malformed")
        expected_items = [image_completed["item"]] if image_completed else []
        if turn.get("items") != expected_items:
            raise ProtocolContractError("protocol_identity_mismatch")
        if (
            isinstance(turn.get("startedAt"), bool)
            or isinstance(turn.get("completedAt"), bool)
            or not isinstance(turn.get("startedAt"), int)
            or not isinstance(turn.get("completedAt"), int)
        ):
            raise ProtocolContractError("protocol_event_malformed")
        if (
            not 0 <= turn["startedAt"] <= turn["completedAt"] <= 253_402_300_799
            or turn["startedAt"] != turn_started["turn"]["startedAt"]
            or not claim.dispatched_at_ms
            <= turn["startedAt"] * 1000
            <= turn["completedAt"] * 1000
            <= claim.readback_deadline_ms
        ):
            raise ProtocolContractError("protocol_completion_time_invalid")
        if turn.get("durationMs") is not None and (
            isinstance(turn["durationMs"], bool)
            or not isinstance(turn["durationMs"], int)
            or turn["durationMs"] < 0
            or not max(
                0, (turn["completedAt"] - turn["startedAt"] - 1) * 1000
            )
            <= turn["durationMs"]
            <= (turn["completedAt"] - turn["startedAt"] + 1) * 1000
            or turn["durationMs"]
            > claim.readback_deadline_ms - claim.dispatched_at_ms
        ):
            raise ProtocolContractError("protocol_event_malformed")
        if image_completed is not None:
            if image_started is None:
                raise ProtocolContractError("protocol_event_out_of_order")
            item_started_ms = image_started.get("startedAtMs")
            item_completed_ms = image_completed.get("completedAtMs")
            turn_started_ms = turn["startedAt"] * 1000
            turn_completed_exclusive_ms = (turn["completedAt"] + 1) * 1000
            if not (
                isinstance(item_started_ms, int)
                and not isinstance(item_started_ms, bool)
                and isinstance(item_completed_ms, int)
                and not isinstance(item_completed_ms, bool)
                and turn_started_ms
                <= item_started_ms
                <= item_completed_ms
                < turn_completed_exclusive_ms
            ):
                raise ProtocolContractError("protocol_completion_time_invalid")

    @staticmethod
    def _turn_state(params: Mapping[str, Any]) -> tuple[str, str]:
        turn = params["turn"]
        status = turn.get("status")
        if status == "completed" and turn.get("error") is None:
            return "ARTIFACT_READY", "artifact_verified"
        error = turn.get("error")
        info = error.get("codexErrorInfo") if isinstance(error, Mapping) else None
        if info == "unauthorized":
            return "LOGIN_REQUIRED", "login_required"
        if info == "usageLimitExceeded" or _contains_http_429(info):
            return "LIMITED", "usage_limited"
        return "UNKNOWN_OUTCOME", "protocol_event_malformed"

    @staticmethod
    def _validate_turn_error(value: Any) -> None:
        if not isinstance(value, Mapping) or "message" not in value or set(value) - {
            "message",
            "additionalDetails",
            "codexErrorInfo",
        }:
            raise ProtocolContractError("protocol_event_malformed")
        if not isinstance(value.get("message"), str):
            raise ProtocolContractError("protocol_event_malformed")
        details = value.get("additionalDetails")
        if details is not None and not isinstance(details, str):
            raise ProtocolContractError("protocol_event_malformed")
        info = value.get("codexErrorInfo")
        if info is None:
            return
        if isinstance(info, str):
            if info not in CODEX_ERROR_STRING_VALUES:
                raise ProtocolContractError("protocol_event_malformed")
            return
        if not isinstance(info, Mapping) or len(info) != 1:
            raise ProtocolContractError("protocol_event_malformed")
        variant, payload = next(iter(info.items()))
        if variant in CODEX_HTTP_ERROR_VARIANTS:
            if not isinstance(payload, Mapping) or set(payload) - {"httpStatusCode"}:
                raise ProtocolContractError("protocol_event_malformed")
            status_code = payload.get("httpStatusCode")
            if status_code is not None and (
                isinstance(status_code, bool)
                or not isinstance(status_code, int)
                or not 0 <= status_code <= 65_535
            ):
                raise ProtocolContractError("protocol_event_malformed")
            return
        if (
            variant == "activeTurnNotSteerable"
            and isinstance(payload, Mapping)
            and set(payload) == {"turnKind"}
            and payload.get("turnKind")
            in {
                "review",
                "compact",
            }
        ):
            return
        raise ProtocolContractError("protocol_event_malformed")

    @staticmethod
    def _account_ready(params: Mapping[str, Any]) -> bool:
        allowed = {"authMode", "planType"}
        if set(params) - allowed or "authMode" not in params:
            raise ProtocolContractError("protocol_event_unknown")
        mode = params.get("authMode")
        plan_type = params.get("planType")
        admitted_modes = {
            "none",
            "apikey",
            "chatgpt",
            "personalAccessToken",
            "bedrockApiKey",
        }
        if not isinstance(mode, str) or mode not in admitted_modes or not isinstance(
            plan_type, (str, type(None))
        ):
            raise ProtocolContractError("protocol_event_malformed")
        return mode != "none"

    @staticmethod
    def _rate_limit_ready(
        params: Mapping[str, Any], claim: DurableDispatchClaim
    ) -> bool:
        if set(params) != {"limited", "observedAtMs"}:
            raise ProtocolContractError("protocol_event_unknown")
        if not isinstance(params.get("limited"), bool):
            raise ProtocolContractError("protocol_event_malformed")
        observed_at = params.get("observedAtMs")
        if (
            isinstance(observed_at, bool)
            or not isinstance(observed_at, int)
            or observed_at < 0
            or not claim.dispatched_at_ms
            <= observed_at
            <= claim.readback_deadline_ms
        ):
            return False
        return params.get("limited") is False

    def _artifact_receipt(
        self,
        *,
        connector_ref: str,
        saved_path: Any,
        encoded_result: Any,
    ) -> dict[str, Any]:
        if not isinstance(saved_path, str) or not saved_path:
            raise ProtocolContractError("artifact_path_missing")
        if not isinstance(encoded_result, str) or not encoded_result:
            raise ProtocolContractError("image_item_terminal_semantics_unknown")
        if len(encoded_result) > MAX_BASE64_CHARS:
            raise ProtocolContractError("image_item_terminal_semantics_unknown")
        root = self.artifact_roots.get(connector_ref)
        if root is None:
            raise ProtocolContractError("artifact_path_not_admitted")
        raw_path = Path(saved_path)
        if not raw_path.is_absolute() or ".." in raw_path.parts:
            raise ProtocolContractError("artifact_path_not_admitted")
        try:
            root_metadata = root.lstat()
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or root.is_symlink()
                or _is_reparse(root)
            ):
                raise ProtocolContractError("artifact_symlink_or_reparse")
            root_resolved = root.resolve(strict=True)
            target_lexical = Path(os.path.abspath(os.path.normpath(str(raw_path))))
        except OSError as exc:
            raise ProtocolContractError("artifact_path_missing") from exc
        if not target_lexical.is_relative_to(root_resolved):
            raise ProtocolContractError("artifact_path_not_admitted")
        root_descriptor = _open_directory_descriptor(root_resolved)
        try:
            root_opened = os.fstat(root_descriptor)
            root_handle_path = _opened_file_final_path(root_descriptor)
            if (
                not stat.S_ISDIR(root_opened.st_mode)
                or root_handle_path != root_resolved
            ):
                raise ProtocolContractError("artifact_path_not_admitted")
            self._reject_reparse_chain(root_resolved, target_lexical)
            data = self._read_bounded_regular_file(
                target_lexical,
                root_descriptor=root_descriptor,
                expected_root_handle_path=root_handle_path,
            )
        finally:
            os.close(root_descriptor)
        size = len(data)
        width, height = self._png_structure(data)
        try:
            decoded = base64.b64decode(encoded_result, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProtocolContractError(
                "image_item_terminal_semantics_unknown"
            ) from exc
        if not _constant_time_equal(decoded, data):
            raise ProtocolContractError("artifact_result_mismatch")
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": size,
            "mime_type": "image/png",
            "width": width,
            "height": height,
            "evidence_ref": None,
        }

    @staticmethod
    def _read_bounded_regular_file(
        path: Path,
        *,
        root_descriptor: int,
        expected_root_handle_path: Path,
    ) -> bytes:
        try:
            before = path.lstat()
        except OSError as exc:
            raise ProtocolContractError("artifact_path_missing") from exc
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size < 33
            or before.st_size > MAX_ARTIFACT_BYTES
        ):
            raise ProtocolContractError("artifact_format_invalid")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            root_opened = os.fstat(root_descriptor)
            root_handle_path = _opened_file_final_path(root_descriptor)
            if (
                not stat.S_ISDIR(root_opened.st_mode)
                or root_handle_path != expected_root_handle_path
            ):
                raise ProtocolContractError("artifact_path_not_admitted")
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            opened_path = _opened_file_final_path(descriptor)
            current_root_handle_path = _opened_file_final_path(root_descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size != before.st_size
                or opened.st_ino != before.st_ino
                or opened.st_dev != before.st_dev
                or current_root_handle_path != root_handle_path
                or not opened_path.is_relative_to(current_root_handle_path)
            ):
                raise ProtocolContractError("artifact_path_not_admitted")
            remaining = opened.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise ProtocolContractError("artifact_path_not_admitted")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise ProtocolContractError("artifact_path_not_admitted")
            after = os.fstat(descriptor)
            if (
                after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ino != opened.st_ino
                or after.st_dev != opened.st_dev
            ):
                raise ProtocolContractError("artifact_path_not_admitted")
            data = b"".join(chunks)
            if len(data) != opened.st_size:
                raise ProtocolContractError("artifact_path_not_admitted")
            return data
        except ProtocolContractError:
            raise
        except OSError as exc:
            raise ProtocolContractError("artifact_path_not_admitted") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _reject_reparse_chain(root: Path, raw_path: Path) -> None:
        try:
            if root.is_symlink() or _is_reparse(root):
                raise ProtocolContractError("artifact_symlink_or_reparse")
            current = raw_path
            chain: list[Path] = []
            while current != current.parent:
                chain.append(current)
                if current == root:
                    break
                current = current.parent
            for part in chain:
                if part.exists() and (part.is_symlink() or _is_reparse(part)):
                    raise ProtocolContractError("artifact_symlink_or_reparse")
        except OSError as exc:
            raise ProtocolContractError("artifact_path_not_admitted") from exc

    @staticmethod
    def _png_structure(data: bytes) -> tuple[int, int]:
        """Validate PNG structure and a bounded, exact non-interlaced scanline stream."""
        if data[:8] != PNG_MAGIC:
            raise ProtocolContractError("artifact_format_invalid")
        offset = len(PNG_MAGIC)
        chunk_index = 0
        width = height = 0
        seen_ihdr = False
        seen_idat = False
        seen_iend = False
        seen_plte = False
        idat_ended = False
        idat_parts: list[bytes] = []
        row_bytes = 0
        color_type = -1
        bit_depth = -1
        while offset < len(data):
            if len(data) - offset < 12:
                raise ProtocolContractError("artifact_format_invalid")
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_end = offset + 12 + length
            if chunk_end > len(data):
                raise ProtocolContractError("artifact_format_invalid")
            chunk_type = data[offset + 4 : offset + 8]
            if (
                not re.fullmatch(rb"[A-Za-z]{4}", chunk_type)
                or not 65 <= chunk_type[2] <= 90
                or (
                    65 <= chunk_type[0] <= 90
                    and chunk_type not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
                )
            ):
                raise ProtocolContractError("artifact_format_invalid")
            chunk_data = data[offset + 8 : offset + 8 + length]
            stored_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
            calculated_crc = zlib.crc32(chunk_type)
            calculated_crc = zlib.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
            if stored_crc != calculated_crc:
                raise ProtocolContractError("artifact_format_invalid")
            if chunk_index == 0 and chunk_type != b"IHDR":
                raise ProtocolContractError("artifact_format_invalid")
            if chunk_type == b"IHDR":
                if seen_ihdr or chunk_index != 0 or length != 13:
                    raise ProtocolContractError("artifact_format_invalid")
                seen_ihdr = True
                width, height, bit_depth, color_type, compression, filtering, interlace = (
                    struct.unpack(">IIBBBBB", chunk_data)
                )
                allowed_depths = {
                    0: {1, 2, 4, 8, 16},
                    2: {8, 16},
                    3: {1, 2, 4, 8},
                    4: {8, 16},
                    6: {8, 16},
                }
                if (
                    color_type not in allowed_depths
                    or bit_depth not in allowed_depths[color_type]
                    or compression != 0
                    or filtering != 0
                    or interlace != 0
                    or not 1 <= width <= 16_384
                    or not 1 <= height <= 16_384
                    or width * height > 67_108_864
                    or width * height * 4 > 268_435_456
                ):
                    raise ProtocolContractError("artifact_format_invalid")
                channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
                row_bytes = (width * channels * bit_depth + 7) // 8
            elif chunk_type == b"IDAT":
                if not seen_ihdr or seen_iend or idat_ended or length == 0:
                    raise ProtocolContractError("artifact_format_invalid")
                seen_idat = True
                idat_parts.append(chunk_data)
            elif chunk_type == b"PLTE":
                if (
                    not seen_ihdr
                    or seen_idat
                    or seen_iend
                    or seen_plte
                    or color_type in {0, 4}
                    or not 3 <= length <= 768
                    or length % 3
                    or (color_type == 3 and length // 3 > 2**bit_depth)
                ):
                    raise ProtocolContractError("artifact_format_invalid")
                seen_plte = True
            elif chunk_type == b"IEND":
                if not seen_ihdr or not seen_idat or seen_iend or length != 0:
                    raise ProtocolContractError("artifact_format_invalid")
                seen_iend = True
                if chunk_end != len(data):
                    raise ProtocolContractError("artifact_format_invalid")
            elif seen_iend:
                raise ProtocolContractError("artifact_format_invalid")
            elif seen_idat:
                idat_ended = True
            offset = chunk_end
            chunk_index += 1
        if (
            not (seen_ihdr and seen_idat and seen_iend)
            or (color_type == 3 and not seen_plte)
            or offset != len(data)
        ):
            raise ProtocolContractError("artifact_format_invalid")
        expected_decoded = height * (1 + row_bytes)
        if expected_decoded <= 0 or expected_decoded > 268_435_456:
            raise ProtocolContractError("artifact_format_invalid")
        compressed = b"".join(idat_parts)
        try:
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(compressed, expected_decoded + 1)
            if len(decoded) > expected_decoded or decoder.unconsumed_tail:
                raise ProtocolContractError("artifact_format_invalid")
            remaining = expected_decoded + 1 - len(decoded)
            decoded += decoder.flush(remaining)
        except (ValueError, zlib.error) as exc:
            raise ProtocolContractError("artifact_format_invalid") from exc
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(decoded) != expected_decoded
        ):
            raise ProtocolContractError("artifact_format_invalid")
        stride = row_bytes + 1
        if any(decoded[offset] not in {0, 1, 2, 3, 4} for offset in range(0, len(decoded), stride)):
            raise ProtocolContractError("artifact_format_invalid")
        return width, height

    @staticmethod
    def _validate_peek(
        peek: DurableDispatchPeek,
        *,
        tenant_ref: str,
        connector_ref: str,
        fingerprint: str,
    ) -> None:
        if not isinstance(peek, DurableDispatchPeek):
            raise TypeError("invalid durable peek")
        if (
            peek.tenant_ref != tenant_ref
            or peek.connector_ref != connector_ref
            or peek.provider != PROVIDER
            or peek.request_fingerprint_sha256 != fingerprint
            or not SHA256_PATTERN.fullmatch(peek.peek_token_sha256)
            or not isinstance(peek.resume_readback_satisfied, bool)
        ):
            raise ValueError("durable peek binding drifted")
        if not peek.exists:
            if any(
                value is not None
                for value in (
                    peek.current_state,
                    peek.connector_binding_sha256,
                    peek.runtime_protocol_authority_sha256,
                )
            ) or peek.resume_readback_satisfied:
                raise ValueError("missing durable peek contains state")
            return
        if peek.current_state not in {
            "READY_TO_DISPATCH",
            "LOGIN_REQUIRED",
            "LIMITED",
            "UNKNOWN_OUTCOME",
            "ARTIFACT_READY",
            "FAILED",
        } or not all(
            SHA256_PATTERN.fullmatch(str(value or ""))
            for value in (
                peek.connector_binding_sha256,
                peek.runtime_protocol_authority_sha256,
            )
        ):
            raise ValueError("existing durable peek is invalid")
        if peek.resume_readback_satisfied and peek.current_state not in {
            "LOGIN_REQUIRED",
            "LIMITED",
        }:
            raise ValueError("durable resume state drifted")

    @staticmethod
    def _validate_claim(
        claim: DurableDispatchClaim,
        *,
        scope: WorkerScope,
        fingerprint: str,
        peek: DurableDispatchPeek,
    ) -> None:
        if not isinstance(claim, DurableDispatchClaim):
            raise TypeError("invalid durable claim")
        if claim.action not in {"dispatch", "readback", "terminal"}:
            raise ValueError("invalid durable action")
        if (
            claim.tenant_ref != scope.tenant_ref
            or claim.connector_ref != scope.connector_ref
            or claim.provider != scope.provider
            or claim.connector_binding_sha256 != scope.connector_binding_sha256
            or claim.runtime_protocol_authority_sha256
            != scope.runtime_protocol_authority_sha256
            or claim.request_fingerprint_sha256 != fingerprint
        ):
            raise ValueError("durable claim binding drifted")
        if not peek.exists:
            if (
                claim.current_state != "READY_TO_DISPATCH"
                or claim.resume_readback_satisfied
            ):
                raise ValueError("new durable claim drifted from missing peek")
        elif (
            claim.current_state != peek.current_state
            or claim.resume_readback_satisfied != peek.resume_readback_satisfied
        ):
            raise ValueError("durable claim drifted from peek snapshot")
        for value in (
            claim.dispatch_ref,
            claim.thread_id,
            claim.turn_id,
            claim.item_id,
        ):
            _required_ref(value, "durable claim identity")
        if (
            isinstance(claim.dispatched_at_ms, bool)
            or isinstance(claim.readback_deadline_ms, bool)
            or not isinstance(claim.dispatched_at_ms, int)
            or not isinstance(claim.readback_deadline_ms, int)
            or claim.dispatched_at_ms <= 0
            or claim.readback_deadline_ms < claim.dispatched_at_ms
        ):
            raise ValueError("durable claim time window is invalid")
        allowed_state_actions = {
            "READY_TO_DISPATCH": {"dispatch"},
            "LOGIN_REQUIRED": {"readback", "dispatch"},
            "LIMITED": {"readback", "dispatch"},
            "UNKNOWN_OUTCOME": {"readback"},
            "ARTIFACT_READY": {"terminal"},
            "FAILED": {"terminal"},
        }
        if claim.action not in allowed_state_actions.get(claim.current_state, set()):
            raise ValueError("durable claim state/action matrix drifted")
        if claim.current_state in {"LOGIN_REQUIRED", "LIMITED"} and (
            claim.action == "dispatch" and not claim.resume_readback_satisfied
        ):
            raise ValueError("paused claim lacks fresh readback")
        if claim.action == "terminal":
            transition = claim.sealed_transition
            if transition is None or transition.state not in {
                "ARTIFACT_READY",
                "FAILED",
            }:
                raise ValueError("terminal claim lacks a sealed transition")
            if transition.state != claim.current_state:
                raise ValueError("terminal claim state drifted")
            terminal_matrix = {
                "ARTIFACT_READY": ("artifact_verified", True),
                "FAILED": ("image_generation_failed", False),
            }
            expected_reason, artifact_required = terminal_matrix[transition.state]
            if transition.safe_reason_code != expected_reason or (
                (transition.artifact is not None) is not artifact_required
            ):
                raise ValueError("terminal transition semantics drifted")
            if transition.safe_reason_code not in SAFE_REASON_CODES or not (
                SHA256_PATTERN.fullmatch(transition.event_chain_sha256)
            ):
                raise ValueError("terminal transition is invalid")
            if transition.artifact is not None:
                artifact = dict(transition.artifact)
                if set(artifact) != {
                    "sha256",
                    "bytes",
                    "mime_type",
                    "width",
                    "height",
                    "evidence_ref",
                }:
                    raise ValueError("terminal artifact shape drifted")
                if artifact.get("evidence_ref") is not None:
                    raise ValueError("transition cannot self-issue Evidence")
                if not SHA256_PATTERN.fullmatch(str(artifact.get("sha256", ""))):
                    raise ValueError("terminal artifact hash is invalid")
                if artifact.get("mime_type") != "image/png":
                    raise ValueError("terminal artifact MIME drifted")
                for field in ("bytes", "width", "height"):
                    if (
                        isinstance(artifact.get(field), bool)
                        or not isinstance(artifact.get(field), int)
                        or artifact[field] <= 0
                    ):
                        raise ValueError("terminal artifact metric is invalid")
            if claim.sealed_evidence_ref is not None and not re.fullmatch(
                r"evd_[0-9a-f]{32}", claim.sealed_evidence_ref
            ):
                raise ValueError("terminal Evidence ref is invalid")
            expected = _sealed_transition_sha256(
                claim=claim,
                transition=transition,
                evidence_ref=claim.sealed_evidence_ref,
            )
            if not hmac.compare_digest(
                str(claim.sealed_transition_sha256 or ""), expected
            ):
                raise ValueError("terminal transition hash drifted")
        elif any(
            value is not None
            for value in (
                claim.sealed_transition,
                claim.sealed_transition_sha256,
                claim.sealed_evidence_ref,
            )
        ):
            raise ValueError("nonterminal claim contains a sealed transition")

    @staticmethod
    def _validate_descriptor(
        descriptor: Mapping[str, Any],
        *,
        principal: Principal,
        connector_ref: str,
        required_capability: str,
    ) -> None:
        if (
            descriptor.get("connector_ref") != connector_ref
            or descriptor.get("derived_tenant_ref") != principal.tenant_ref
            or descriptor.get("provider") != PROVIDER
            or descriptor.get("protocol_version") != PROTOCOL_VERSION
            or required_capability not in descriptor.get("capabilities", [])
            or not SHA256_PATTERN.fullmatch(
                str(descriptor.get("binding_sha256", ""))
            )
        ):
            raise PermissionError("connector binding invalid")
        if descriptor.get("health") == "REVOKED":
            raise PermissionError("connector revoked")

    def _validate_runtime_receipt(
        self,
        receipt: RuntimeProtocolReceipt,
        *,
        descriptor: Mapping[str, Any],
        checked_at: datetime,
        transport_descriptor: TransportDescriptor,
    ) -> None:
        if not isinstance(receipt, RuntimeProtocolReceipt):
            raise TypeError("runtime protocol receipt is invalid")
        expected_authority_payload = {
            "connector_ref": descriptor["connector_ref"],
            "connector_binding_sha256": descriptor["binding_sha256"],
            "protocol_version": PROTOCOL_VERSION,
            "codex_cli_version": "codex-cli 0.142.5",
            "aggregate_schema_canonical_sha256": self.contract.aggregate_schema_sha256,
            "item_completed_schema_canonical_sha256": self.contract.item_schema_sha256,
            "turn_completed_schema_canonical_sha256": self.contract.turn_schema_sha256,
            "canonical_bundle_sha256": EXPECTED_PROTOCOL_PINS[
                "canonical_bundle_observation_sha256"
            ],
            "actual_transport_kind": transport_descriptor.actual_transport_kind,
            "transport_adapter_version": transport_descriptor.adapter_version,
            "transport_adapter_sha256": transport_descriptor.adapter_sha256,
        }
        actual_authority_payload = {
            "connector_ref": receipt.connector_ref,
            "connector_binding_sha256": receipt.connector_binding_sha256,
            "protocol_version": receipt.protocol_version,
            "codex_cli_version": receipt.codex_cli_version,
            "aggregate_schema_canonical_sha256": (
                receipt.aggregate_schema_canonical_sha256
            ),
            "item_completed_schema_canonical_sha256": (
                receipt.item_completed_schema_canonical_sha256
            ),
            "turn_completed_schema_canonical_sha256": (
                receipt.turn_completed_schema_canonical_sha256
            ),
            "canonical_bundle_sha256": receipt.canonical_bundle_sha256,
            "actual_transport_kind": receipt.actual_transport_kind,
            "transport_adapter_version": receipt.transport_adapter_version,
            "transport_adapter_sha256": receipt.transport_adapter_sha256,
        }
        expected_authority_sha = _hash_json(expected_authority_payload)
        receipt_checked_at = _aware(receipt.checked_at, "runtime receipt checked_at")
        recorded_at = _aware(receipt.recorded_at, "runtime receipt recorded_at")
        effective_at = _aware(receipt.effective_at, "runtime receipt effective_at")
        fresh_until = _aware(receipt.fresh_until, "runtime receipt fresh_until")
        receipt_payload = {
            **actual_authority_payload,
            "authority_sha256": receipt.authority_sha256,
            "checked_at": receipt_checked_at.isoformat(),
            "recorded_at": recorded_at.isoformat(),
            "effective_at": effective_at.isoformat(),
            "fresh_until": fresh_until.isoformat(),
        }
        if (
            actual_authority_payload != expected_authority_payload
            or not hmac.compare_digest(
                receipt.authority_sha256, expected_authority_sha
            )
            or receipt_checked_at != checked_at
            or not effective_at <= recorded_at <= checked_at < fresh_until
            or checked_at - recorded_at > MAX_RUNTIME_RECEIPT_FRESHNESS
            or fresh_until - checked_at > MAX_RUNTIME_RECEIPT_FRESHNESS
            or not hmac.compare_digest(
                receipt.receipt_sha256, _hash_json(receipt_payload)
            )
        ):
            raise ValueError("runtime protocol receipt drifted")

    @staticmethod
    def _validate_transport_descriptor(
        descriptor: TransportDescriptor,
    ) -> TransportDescriptor:
        if not isinstance(descriptor, TransportDescriptor):
            raise TypeError("transport descriptor is invalid")
        _required_ref(descriptor.actual_transport_kind, "transport kind")
        _required_ref(descriptor.adapter_version, "transport adapter version")
        if not SHA256_PATTERN.fullmatch(descriptor.adapter_sha256):
            raise ValueError("transport adapter hash is invalid")
        return descriptor

    @staticmethod
    def _validate_request(
        request: ImageWorkerRequest, checked_at: datetime
    ) -> ImageWorkerRequest:
        _required_ref(request.job_ref, "job_ref")
        _required_ref(request.idempotency_key, "idempotency_key")
        if request.tool_name not in TOOL_CAPABILITIES:
            raise ValueError("unsupported image tool")
        if not SHA256_PATTERN.fullmatch(request.request_sha256):
            raise ValueError("request_sha256 must be lowercase SHA-256")
        data_as_of = _aware(request.data_as_of, "data_as_of")
        if data_as_of > checked_at:
            raise ValueError("data_as_of cannot be in the future")
        if request.transport not in ALLOWED_TRANSPORTS:
            raise ProtocolContractError("transport_not_admitted")
        if request.protocol_version != PROTOCOL_VERSION:
            raise ProtocolContractError("protocol_pin_mismatch")
        if not isinstance(request.explicit_resume, bool):
            raise ValueError("explicit_resume must be boolean")
        return ImageWorkerRequest(
            job_ref=request.job_ref,
            tool_name=request.tool_name,
            idempotency_key=request.idempotency_key,
            request_sha256=request.request_sha256,
            data_as_of=data_as_of,
            transport=request.transport,
            protocol_version=request.protocol_version,
            explicit_resume=request.explicit_resume,
        )

    def _request_fingerprint(
        self,
        principal: Principal,
        connector_ref: str,
        request: ImageWorkerRequest,
    ) -> str:
        return _hash_json(
            {
                "contract_sha256": self.contract.sha256,
                "fixture_sha256": self.fixture_sha256,
                "tenant_ref": principal.tenant_ref,
                "connector_ref": connector_ref,
                "job_ref": request.job_ref,
                "tool_name": request.tool_name,
                "idempotency_key": request.idempotency_key,
                "request_sha256": request.request_sha256,
                "data_as_of": request.data_as_of.isoformat(),
                "transport": request.transport,
                "protocol_version": request.protocol_version,
            }
        )

    def _blocked(
        self,
        *,
        connector_ref: Any,
        request: Any,
        checked_at: datetime,
        reason: str,
    ) -> ImageWorkerObservation:
        job_ref = "invalid_request"
        data_as_of = checked_at
        if isinstance(request, Mapping):
            candidate = str(request.get("job_ref", ""))
            if REF_PATTERN.fullmatch(candidate):
                job_ref = candidate
            value = request.get("data_as_of")
            try:
                if isinstance(value, str):
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, datetime):
                    data_as_of = _aware(value, "data_as_of")
            except ValueError:
                pass
        fallback = ImageWorkerRequest(
            job_ref=job_ref,
            tool_name="media.image_generate",
            idempotency_key="invalid_request",
            request_sha256="0" * 64,
            data_as_of=data_as_of,
        )
        safe_connector_ref = str(connector_ref or "")
        return self._observation(
            fallback,
            connector_ref=(
                safe_connector_ref
                if REF_PATTERN.fullmatch(safe_connector_ref)
                else "invalid_connector"
            ),
            binding_sha256=None,
            checked_at=checked_at,
            fingerprint=_hash_json({"reason": reason, "contract": self.contract.sha256}),
            state="BLOCKED",
            reason=reason,
        )

    def _observation(
        self,
        request: ImageWorkerRequest,
        *,
        connector_ref: str,
        binding_sha256: str | None,
        checked_at: datetime,
        fingerprint: str,
        state: str,
        reason: str,
        dispatch_ref: str | None = None,
        event_chain_sha256: str | None = None,
        artifact: Mapping[str, Any] | None = None,
        protocol_dispatch_attempt_count: int = 0,
        protocol_readback_attempt_count: int = 0,
    ) -> ImageWorkerObservation:
        if state not in TERMINAL_STATES or reason not in SAFE_REASON_CODES:
            raise RuntimeError("unsafe Image Worker projection")
        projection_sha256 = _hash_json(
            {
                "contract_id": CONTRACT_ID,
                "state": state,
                "safe_reason_code": reason,
                "job_ref": request.job_ref,
                "dispatch_ref": dispatch_ref,
                "connector_ref": connector_ref,
                "provider": PROVIDER,
                "connector_binding_sha256": binding_sha256,
                "data_as_of": request.data_as_of.isoformat(),
                "request_fingerprint_sha256": fingerprint,
                "protocol_version": PROTOCOL_VERSION,
                "contract_sha256": self.contract.sha256,
                "fixture_sha256": self.fixture_sha256,
                "event_chain_sha256": event_chain_sha256,
                "artifact": dict(artifact) if artifact else None,
            }
        )
        return ImageWorkerObservation(
            contract_id=CONTRACT_ID,
            state=state,
            safe_reason_code=reason,
            job_ref=request.job_ref,
            dispatch_ref=dispatch_ref,
            connector_ref=connector_ref,
            provider=PROVIDER,
            connector_binding_sha256=binding_sha256,
            checked_at=checked_at.isoformat(),
            data_as_of=request.data_as_of.isoformat(),
            request_fingerprint_sha256=fingerprint,
            protocol_version=PROTOCOL_VERSION,
            aggregate_schema_canonical_sha256=(
                self.contract.aggregate_schema_sha256
            ),
            item_completed_schema_canonical_sha256=(
                self.contract.item_schema_sha256
            ),
            turn_completed_schema_canonical_sha256=(
                self.contract.turn_schema_sha256
            ),
            contract_sha256=self.contract.sha256,
            fixture_sha256=self.fixture_sha256,
            event_chain_sha256=event_chain_sha256,
            projection_sha256=projection_sha256,
            artifact=MappingProxyType(dict(artifact)) if artifact else None,
            protocol_dispatch_attempt_count=protocol_dispatch_attempt_count,
            protocol_readback_attempt_count=protocol_readback_attempt_count,
        )


def canonical_json_sha256(value: Any) -> str:
    """Hash parsed JSON semantics; raw aggregate key order is non-authoritative."""
    if isinstance(value, (str, bytes, bytearray)):
        value = json.loads(value)
    return _hash_json(value)


def sealed_transition_sha256(
    transition: WorkerTransition,
    *,
    claim: DurableDispatchClaim,
    evidence_ref: str | None,
) -> str:
    """Seal the safe terminal projection supplied by the future BAS-183 ledger."""
    return _sealed_transition_sha256(
        claim=claim, transition=transition, evidence_ref=evidence_ref
    )


def _sealed_transition_sha256(
    *,
    claim: DurableDispatchClaim,
    transition: WorkerTransition,
    evidence_ref: str | None,
) -> str:
    return _hash_json(
        {
            "dispatch_ref": claim.dispatch_ref,
            "tenant_ref": claim.tenant_ref,
            "connector_ref": claim.connector_ref,
            "provider": claim.provider,
            "connector_binding_sha256": claim.connector_binding_sha256,
            "runtime_protocol_authority_sha256": (
                claim.runtime_protocol_authority_sha256
            ),
            "request_fingerprint_sha256": claim.request_fingerprint_sha256,
            "thread_id": claim.thread_id,
            "turn_id": claim.turn_id,
            "item_id": claim.item_id,
            "dispatched_at_ms": claim.dispatched_at_ms,
            "readback_deadline_ms": claim.readback_deadline_ms,
            "current_state": claim.current_state,
            "state": transition.state,
            "safe_reason_code": transition.safe_reason_code,
            "event_chain_sha256": transition.event_chain_sha256,
            "artifact": (
                {**dict(transition.artifact), "evidence_ref": evidence_ref}
                if transition.artifact
                else None
            ),
            "resume_readback_satisfied": transition.resume_readback_satisfied,
        }
    )


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_protocol_budget(messages: Sequence[Any]) -> None:
    """Reject oversized/unbounded protocol values before canonical serialization."""
    if isinstance(messages, (str, bytes, bytearray)) or not isinstance(
        messages, Sequence
    ):
        raise ProtocolContractError("protocol_event_malformed")
    if not 1 <= len(messages) <= MAX_PROTOCOL_MESSAGES:
        raise ProtocolContractError("protocol_event_malformed")
    counters = {"metadata_chars": 0, "artifact_chars": 0, "items": 0}

    def visit(value: Any, *, key: str | None, depth: int) -> None:
        if depth > MAX_PROTOCOL_DEPTH:
            raise ProtocolContractError("protocol_event_malformed")
        counters["items"] += 1
        if counters["items"] > MAX_PROTOCOL_CONTAINER_ITEMS:
            raise ProtocolContractError("protocol_event_malformed")
        if isinstance(value, Mapping):
            if len(value) > MAX_PROTOCOL_CONTAINER_ITEMS:
                raise ProtocolContractError("protocol_event_malformed")
            for child_key, child_value in value.items():
                if not isinstance(child_key, str) or len(child_key) > 128:
                    raise ProtocolContractError("protocol_event_malformed")
                visit(child_value, key=child_key, depth=depth + 1)
            return
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            if len(value) > MAX_PROTOCOL_CONTAINER_ITEMS:
                raise ProtocolContractError("protocol_event_malformed")
            for child in value:
                visit(child, key=key, depth=depth + 1)
            return
        if isinstance(value, str):
            if key == "result":
                counters["artifact_chars"] += len(value)
                if counters["artifact_chars"] > MAX_BASE64_CHARS:
                    raise ProtocolContractError(
                        "image_item_terminal_semantics_unknown"
                    )
            else:
                if len(value) > MAX_PROTOCOL_FIELD_CHARS:
                    raise ProtocolContractError("protocol_event_malformed")
                counters["metadata_chars"] += len(value)
                if counters["metadata_chars"] > MAX_PROTOCOL_METADATA_CHARS:
                    raise ProtocolContractError("protocol_event_malformed")
            return
        if isinstance(value, int) and not isinstance(value, bool):
            if not -(2**63) <= value <= 2**63 - 1:
                raise ProtocolContractError("protocol_event_malformed")
            return
        if isinstance(value, float):
            if not math.isfinite(value) or abs(value) > 1e308:
                raise ProtocolContractError("protocol_event_malformed")
            return
        if value is not None and not isinstance(value, bool):
            raise ProtocolContractError("protocol_event_malformed")

    visit(messages, key=None, depth=0)


def _bounded_event_chain_sha256(messages: Sequence[Any]) -> str:
    """Hash a bounded projection without copying provider text or image bytes."""
    sensitive = {
        "result",
        "savedPath",
        "revisedPrompt",
        "message",
        "additionalDetails",
    }

    def project(value: Any, *, key: str | None = None) -> Any:
        if isinstance(value, Mapping):
            return {str(child_key): project(child, key=str(child_key)) for child_key, child in value.items()}
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return [project(child, key=key) for child in value]
        if isinstance(value, str) and key in sensitive:
            return {"redacted": True, "characters": len(value)}
        if isinstance(value, str) and key in {"name", "title"}:
            return {"redacted": True, "characters": len(value)}
        return value

    return _hash_json(project(messages))


def _opened_file_final_path(descriptor: int) -> Path:
    """Resolve the path of the already-open handle; never re-trust the input path."""
    if os.name == "nt":
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(descriptor)
        buffer = ctypes.create_unicode_buffer(32_768)
        length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(  # type: ignore[attr-defined]
            handle,
            buffer,
            len(buffer),
            0,
        )
        if length == 0 or length >= len(buffer):
            raise ProtocolContractError("artifact_path_not_admitted")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        try:
            return Path(value).resolve(strict=True)
        except OSError as exc:
            raise ProtocolContractError("artifact_path_not_admitted") from exc
    proc_path = Path(f"/proc/self/fd/{descriptor}")
    if not proc_path.exists():
        raise ProtocolContractError("artifact_path_not_admitted")
    try:
        return proc_path.resolve(strict=True)
    except OSError as exc:
        raise ProtocolContractError("artifact_path_not_admitted") from exc


def _open_directory_descriptor(path: Path) -> int:
    """Hold the connector root open so rename/swap races change no authority."""
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        try:
            return os.open(path, flags)
        except OSError as exc:
            raise ProtocolContractError("artifact_path_not_admitted") from exc

    import ctypes
    import msvcrt
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW  # type: ignore[attr-defined]
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x0080,  # FILE_READ_ATTRIBUTES
        0x0001 | 0x0002 | 0x0004,  # FILE_SHARE_READ|WRITE|DELETE
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS|OPEN_REPARSE_POINT
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ProtocolContractError("artifact_path_not_admitted")
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError as exc:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        raise ProtocolContractError("artifact_path_not_admitted") from exc


def _required_ref(value: Any, name: str) -> str:
    result = str(value or "").strip()
    if not REF_PATTERN.fullmatch(result):
        raise ValueError(f"{name} is invalid")
    return result


def _required_text(value: Any, name: str, limit: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > limit:
        raise ValueError(f"{name} is invalid")
    return result


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone")
    return value.astimezone(UTC)


def _contains_http_429(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "httpStatusCode" and child == 429:
                return True
            if _contains_http_429(child):
                return True
    elif isinstance(value, list):
        return any(_contains_http_429(item) for item in value)
    return False


def _constant_time_equal(left: bytes, right: bytes) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(left).digest(), hashlib.sha256(right).digest()
    )


def _is_reparse(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)
