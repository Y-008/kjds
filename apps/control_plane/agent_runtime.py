from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from .agent_inference import InferenceAttemptError, ModelInferencePort

RUNTIME_CONTRACT_ID = "kjds-governed-agent-runtime-v1"
ROUTING_POLICY_VERSION = "profit-aware-routing-v1"
REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|cookie|credential|password|passwd|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization\s*:\s*bearer|cookie|password|passwd|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key)"
    r"\s*[:=]?\s*([^\s,;\"']+)"
)
_PRIVILEGED_OUTPUT_KEYS = frozenset(
    {
        "approval_id",
        "approved_by",
        "external_write",
        "external_write_allowed",
        "formal_fact_id",
        "marketplace_write",
        "permit",
        "permit_id",
        "self_approved",
        "write_authorized",
    }
)
_POSITIVE_APPROVAL_VALUES = frozenset(
    {"approve", "approved", "authorized", "granted", "issued", "passed"}
)
_DENIED_TOOL_TOKENS = frozenset(
    {
        "approve",
        "approval.approve",
        "fact.promote",
        "formal_fact.promote",
        "marketplace.write",
        "permit.issue",
        "write.marketplace",
    }
)
_DENIED_TOOL_PREFIXES = (
    "approval.write",
    "fact.write",
    "marketplace.create",
    "marketplace.delete",
    "marketplace.publish",
    "marketplace.update",
    "ozon.write",
    "permit.write",
    "telegram.send",
    "vk.publish",
)


class AgentRuntimePolicyError(ValueError):
    """The request or response crossed a non-retryable governance rule."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AgentRuntimeExhaustedError(RuntimeError):
    """Every eligible adapter failed without producing a governed result."""

    def __init__(self, code: str, message: str, *, attempts: tuple[RuntimeAttempt, ...]) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = attempts


class RuntimeAdapterError(RuntimeError):
    """One adapter attempt failed and may be eligible for fallback."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = True,
        cost_usd: Decimal = Decimal("0"),
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.cost_usd = _decimal(cost_usd, "adapter_error.cost_usd")
        self.input_tokens = max(0, int(input_tokens))
        self.output_tokens = max(0, int(output_tokens))
        self.latency_ms = max(0, int(latency_ms))


@dataclass(frozen=True, slots=True)
class AdapterProfile:
    name: str
    provider: str
    model: str
    capabilities: frozenset[str]
    estimated_accuracy: Decimal
    p95_latency_ms: int
    estimated_cost_usd: Decimal
    config_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.provider.strip() or not self.model.strip():
            raise ValueError("Adapter profile identity must be complete")
        accuracy = _decimal(self.estimated_accuracy, "estimated_accuracy")
        cost = _decimal(self.estimated_cost_usd, "estimated_cost_usd")
        if accuracy < 0 or accuracy > 1:
            raise ValueError("Adapter estimated_accuracy must be between zero and one")
        if self.p95_latency_ms < 0:
            raise ValueError("Adapter p95_latency_ms cannot be negative")
        if cost < 0:
            raise ValueError("Adapter estimated_cost_usd cannot be negative")
        object.__setattr__(self, "estimated_accuracy", accuracy)
        object.__setattr__(self, "estimated_cost_usd", cost)
        object.__setattr__(
            self,
            "capabilities",
            frozenset(item.strip() for item in self.capabilities if item.strip()),
        )
        if not self.config_sha256:
            object.__setattr__(
                self,
                "config_sha256",
                _sha256(
                    {
                        "name": self.name,
                        "provider": self.provider,
                        "model": self.model,
                        "capabilities": sorted(self.capabilities),
                        "estimated_accuracy": str(accuracy),
                        "p95_latency_ms": self.p95_latency_ms,
                        "estimated_cost_usd": str(cost),
                    }
                ),
            )


@dataclass(frozen=True, slots=True)
class AgentRunEvidenceRef:
    evidence_id: str
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class AgentRunScopeContext:
    """Server-derived exact scope. Callers cannot supply its individual fields."""

    tenant_ref: str
    entity_ref: str
    store_ref: str
    authority_sha256: str
    actor_id: str
    scope_as_of: datetime
    evidence_refs: tuple[AgentRunEvidenceRef, ...]

    def __post_init__(self) -> None:
        required = {
            "tenant_ref": self.tenant_ref,
            "entity_ref": self.entity_ref,
            "store_ref": self.store_ref,
            "actor_id": self.actor_id,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.authority_sha256):
            raise ValueError("authority_sha256 must be a lowercase SHA-256")
        if self.scope_as_of.tzinfo is None:
            raise ValueError("scope_as_of must include a timezone")
        ids = [item.evidence_id for item in self.evidence_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate scoped Evidence references are not allowed")
        for item in self.evidence_refs:
            if not item.evidence_id.strip() or not re.fullmatch(
                r"[0-9a-f]{64}", item.evidence_sha256
            ):
                raise ValueError("Scoped Evidence identity is invalid")


@dataclass(frozen=True, slots=True)
class RuntimeTaskContract:
    task_type: str
    registry_sha256: str
    contract_version: str
    prompt_version: str
    schema_version: str
    prompt: str
    output_schema: dict[str, Any]
    required_capabilities: tuple[str, ...]
    allowed_input_fields: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    min_accuracy: Decimal
    max_latency_ms: int
    max_cost_usd: Decimal
    max_attempts: int
    max_output_tokens: int
    timeout_seconds: int

    @classmethod
    def from_registry(
        cls,
        *,
        task_type: str,
        registry_sha256: str,
        registry_payload: Mapping[str, Any],
        registry_authority: Mapping[str, Any],
    ) -> RuntimeTaskContract:
        return cls(
            task_type=task_type,
            registry_sha256=registry_sha256,
            contract_version=str(registry_payload["contract_version"]),
            prompt_version=str(registry_payload["prompt_version"]),
            schema_version=str(registry_payload["schema_version"]),
            prompt=str(registry_payload["prompt"]),
            output_schema=dict(registry_payload["output_schema"]),
            required_capabilities=tuple(registry_payload["required_capabilities"]),
            allowed_input_fields=tuple(registry_payload["allowed_input_fields"]),
            allowed_tools=tuple(registry_payload.get("allowed_tools", ())),
            min_accuracy=_decimal(
                registry_payload.get("minimum_confidence", "0"),
                "minimum_confidence",
            ),
            max_latency_ms=int(registry_payload["timeout_seconds"]) * 1000,
            max_cost_usd=_decimal(
                registry_payload["max_cost_usd"], "max_cost_usd"
            ),
            max_attempts=int(
                registry_authority.get("maximum_provider_attempts", 1)
            ),
            max_output_tokens=int(registry_payload["max_output_tokens"]),
            timeout_seconds=int(registry_payload["timeout_seconds"]),
        )


@dataclass(frozen=True, slots=True)
class RuntimeTask:
    task_type: str
    model_input: dict[str, Any]
    idempotency_key: str
    expected_profit_value_usd: Decimal | None = None
    max_cost_to_profit_ratio: Decimal = Decimal("0.10")
    max_attempts: int | None = None
    max_cost_usd: Decimal | None = None
    max_latency_ms: int | None = None
    requested_tools: tuple[str, ...] = ()
    image_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    run_id: str
    attempt: int
    task_type: str
    prompt: str
    model_input: dict[str, Any]
    output_schema: dict[str, Any]
    max_output_tokens: int
    timeout_seconds: int
    idempotency_key: str
    image_inputs: tuple[str, ...]
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeAdapterResponse:
    output: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    provider_request_id: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        cost = _decimal(self.cost_usd, "response.cost_usd")
        if cost < 0:
            raise ValueError("Adapter response cost cannot be negative")
        if self.input_tokens < 0 or self.output_tokens < 0 or self.latency_ms < 0:
            raise ValueError("Adapter response usage cannot be negative")
        object.__setattr__(self, "cost_usd", cost)


class RuntimeAdapter(Protocol):
    profile: AdapterProfile

    def invoke(self, request: AdapterRequest) -> RuntimeAdapterResponse: ...


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    adapter_name: str
    provider: str
    model: str
    estimated_accuracy: Decimal
    estimated_latency_ms: int
    estimated_cost_usd: Decimal
    score: Decimal


@dataclass(frozen=True, slots=True)
class RuntimeAttempt:
    attempt: int
    adapter_name: str
    provider: str
    model: str
    status: str
    reason_code: str | None
    estimated_cost_usd: Decimal
    actual_cost_usd: Decimal
    latency_ms: int
    input_tokens: int
    output_tokens: int
    span_id: str


@dataclass(frozen=True, slots=True)
class EvalAssertion:
    name: str
    passed: bool
    score: Decimal
    detail_code: str


@dataclass(frozen=True, slots=True)
class EvalRecord:
    eval_id: str
    run_id: str
    trace_id: str
    span_id: str
    task_type: str
    routing_policy_version: str
    adapter_name: str
    model: str
    input_sha256: str
    output_sha256: str
    assertions: tuple[EvalAssertion, ...]
    score: Decimal
    passed: bool


@dataclass(frozen=True, slots=True)
class GovernanceEnvelope:
    proposal_only: bool = True
    formal_fact: bool = False
    self_approval_allowed: bool = False
    permit_issue_allowed: bool = False
    external_write_allowed: bool = False
    marketplace_write_allowed: bool = False
    tool_execution_allowed: bool = False


@dataclass(frozen=True, slots=True)
class GovernedRunResult:
    contract_id: str
    run_id: str
    trace_id: str
    root_span_id: str
    task_type: str
    provider: str
    model: str
    input_sha256: str
    output: dict[str, Any]
    output_sha256: str
    total_cost_usd: Decimal
    attempts: tuple[RuntimeAttempt, ...]
    route: tuple[RouteCandidate, ...]
    eval_record: EvalRecord
    governance: GovernanceEnvelope = field(default_factory=GovernanceEnvelope)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class GovernedRunReceipt:
    contract_id: str
    run_id: str
    trace_id: str
    task_type: str
    status: str
    input_sha256: str
    output_sha256: str | None
    eval_sha256: str | None
    event_count: int
    payload_status: str = "not_retained"
    network_invoked: bool = False
    proposal_only: bool = True
    formal_fact: bool = False
    external_write_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True, slots=True)
class RuntimeAuditEnvelope:
    run_id: str
    trace_id: str
    root_span_id: str
    scope: AgentRunScopeContext
    task_type: str
    registry_sha256: str
    contract_version: str
    prompt_version: str
    schema_version: str
    routing_policy_version: str
    prompt_sha256: str
    output_schema_sha256: str
    tool_contract_sha256: str
    idempotency_key: str
    request_sha256: str
    input_sha256: str
    input_field_names: tuple[str, ...]
    input_bytes: int
    evidence_snapshot_sha256: str
    required_capabilities: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    max_cost_usd: Decimal
    max_latency_ms: int
    max_attempts: int
    started_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeAuditEvent:
    event_type: str
    reason_code: str | None = None
    adapter_name: str | None = None
    provider: str | None = None
    model: str | None = None
    adapter_config_sha256: str | None = None
    output_sha256: str | None = None
    eval_sha256: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    safe_payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeAuditPreparation:
    disposition: Literal["new", "resume", "replay", "unknown_outcome"]
    receipt: GovernedRunReceipt | None = None


class RuntimeAuditLedger(Protocol):
    def prepare(self, envelope: RuntimeAuditEnvelope) -> RuntimeAuditPreparation: ...

    def append(self, *, run_id: str, event: RuntimeAuditEvent) -> None: ...

    def list_runs(
        self,
        *,
        context: AgentRunScopeContext,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]: ...

    def get_run(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> dict[str, Any]: ...

    def replay(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> GovernedRunReceipt: ...


class RuntimeTaskRegistry(Protocol):
    registry_sha256: str
    payload: dict[str, Any]

    def require(self, task_type: str) -> dict[str, Any]: ...


class InMemoryRuntimeAuditLedger:
    """Authoritative contract double; production uses the SQL Evidence ledger."""

    def __init__(self) -> None:
        self.envelopes: dict[str, RuntimeAuditEnvelope] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self._scope_keys: dict[tuple[str, ...], str] = {}
        self._lock = threading.RLock()

    def prepare(self, envelope: RuntimeAuditEnvelope) -> RuntimeAuditPreparation:
        key = (
            envelope.scope.tenant_ref,
            envelope.scope.entity_ref,
            envelope.scope.store_ref,
            envelope.scope.authority_sha256,
            envelope.idempotency_key,
        )
        with self._lock:
            existing_run_id = self._scope_keys.get(key)
            if existing_run_id is None:
                self._scope_keys[key] = envelope.run_id
                self.envelopes[envelope.run_id] = envelope
                self.events[envelope.run_id] = []
                self.append(
                    run_id=envelope.run_id,
                    event=RuntimeAuditEvent(
                        event_type="run_started",
                        occurred_at=envelope.started_at,
                    ),
                )
                return RuntimeAuditPreparation("new")
            existing = self.envelopes[existing_run_id]
            if existing.request_sha256 != envelope.request_sha256:
                raise AgentRuntimePolicyError(
                    "idempotency_conflict",
                    "Idempotency key was already used for different governed input",
                )
            events = self.events[existing_run_id]
            last_type = events[-1]["event_type"] if events else ""
            if last_type == "run_started":
                return RuntimeAuditPreparation("resume")
            if last_type == "attempt_started":
                self.append(
                    run_id=existing_run_id,
                    event=RuntimeAuditEvent(
                        event_type="unknown_outcome",
                        reason_code="provider_outcome_not_persisted",
                        occurred_at=envelope.started_at,
                    ),
                )
                return RuntimeAuditPreparation(
                    "unknown_outcome", self._receipt(existing_run_id)
                )
            return RuntimeAuditPreparation("replay", self._receipt(existing_run_id))

    def append(self, *, run_id: str, event: RuntimeAuditEvent) -> None:
        with self._lock:
            if run_id not in self.envelopes:
                raise KeyError("Unknown governed Agent run")
            events = self.events[run_id]
            _assert_event_transition(events, event.event_type)
            occurred_at = event.occurred_at or datetime.now(UTC)
            previous_sha256 = events[-1]["event_sha256"] if events else "0" * 64
            payload = _audit_event_payload(
                event=event,
                event_index=len(events) + 1,
                previous_event_sha256=previous_sha256,
                occurred_at=occurred_at,
            )
            events.append(payload)

    def list_runs(
        self,
        *,
        context: AgentRunScopeContext,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        _validate_page(limit=limit, offset=offset)
        with self._lock:
            run_ids = [
                run_id
                for run_id, envelope in self.envelopes.items()
                if _envelope_visible(envelope, context)
                and (task_type is None or envelope.task_type == task_type)
                and (
                    status is None
                    or _event_status(self.events[run_id][-1]["event_type"]) == status
                )
            ]
            run_ids.sort(
                key=lambda item: (
                    self.envelopes[item].started_at,
                    item,
                ),
                reverse=True,
            )
            selected = run_ids[offset : offset + limit]
            rows = [self._projection(run_id, include_events=False) for run_id in selected]
        return _run_listing(rows=rows, total=len(run_ids), limit=limit, offset=offset)

    def get_run(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            envelope = self.envelopes.get(run_id)
            if envelope is None or not _envelope_visible(envelope, context):
                raise KeyError("Governed Agent run not found")
            return self._projection(run_id, include_events=True)

    def replay(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> GovernedRunReceipt:
        with self._lock:
            envelope = self.envelopes.get(run_id)
            if envelope is None or not _envelope_visible(envelope, context):
                raise KeyError("Governed Agent run not found")
            return self._receipt(run_id)

    def _receipt(self, run_id: str) -> GovernedRunReceipt:
        envelope = self.envelopes[run_id]
        events = self.events[run_id]
        latest = events[-1]
        return GovernedRunReceipt(
            contract_id=RUNTIME_CONTRACT_ID,
            run_id=run_id,
            trace_id=envelope.trace_id,
            task_type=envelope.task_type,
            status=str(latest["event_type"]).removeprefix("run_"),
            input_sha256=envelope.input_sha256,
            output_sha256=next(
                (
                    str(item["output_sha256"])
                    for item in reversed(events)
                    if item.get("output_sha256")
                ),
                None,
            ),
            eval_sha256=next(
                (
                    str(item["eval_sha256"])
                    for item in reversed(events)
                    if item.get("eval_sha256")
                ),
                None,
            ),
            event_count=len(events),
        )

    def _projection(
        self,
        run_id: str,
        *,
        include_events: bool,
    ) -> dict[str, Any]:
        envelope = self.envelopes[run_id]
        events = self.events[run_id]
        payload = _run_projection(
            envelope=envelope,
            events=events,
            evidence_refs=None,
        )
        if not include_events:
            payload.pop("events")
        return payload


@dataclass(frozen=True, slots=True)
class GenAISpanEvent:
    name: str
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GenAISpan:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    started_at: str
    ended_at: str
    status: str
    attributes: dict[str, Any]
    events: tuple[GenAISpanEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class GenAITraceSink(Protocol):
    def emit(self, span: GenAISpan) -> None: ...


class NullGenAITraceSink:
    def emit(self, span: GenAISpan) -> None:
        del span


class InMemoryGenAITraceSink:
    def __init__(self) -> None:
        self.spans: list[GenAISpan] = []

    def emit(self, span: GenAISpan) -> None:
        self.spans.append(span)


class RuntimeResultStore(Protocol):
    def get(self, scope_key: str) -> tuple[str, GovernedRunResult] | None: ...

    def put(self, scope_key: str, fingerprint: str, result: GovernedRunResult) -> None: ...


class InMemoryRuntimeResultStore:
    """Process-local adapter; a database implementation can replace it at the seam."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, GovernedRunResult]] = {}
        self._lock = threading.RLock()

    def get(self, scope_key: str) -> tuple[str, GovernedRunResult] | None:
        with self._lock:
            return self._items.get(scope_key)

    def put(self, scope_key: str, fingerprint: str, result: GovernedRunResult) -> None:
        with self._lock:
            existing = self._items.get(scope_key)
            if existing is not None and existing[0] != fingerprint:
                raise AgentRuntimePolicyError(
                    "idempotency_conflict",
                    "Idempotency key was already used for different governed input",
                )
            self._items[scope_key] = (fingerprint, result)


class ExistingInferenceRuntimeAdapter:
    """Adapts the existing ModelInferencePort, including OpenAI-compatible inference."""

    def __init__(self, port: ModelInferencePort, *, profile: AdapterProfile) -> None:
        self.port = port
        self.profile = profile

    def invoke(self, request: AdapterRequest) -> RuntimeAdapterResponse:
        started = time.monotonic()
        try:
            response = self.port.infer(
                prompt=request.prompt,
                model_input=request.model_input,
                output_schema=request.output_schema,
                max_output_tokens=request.max_output_tokens,
                timeout_seconds=request.timeout_seconds,
                idempotency_key=request.idempotency_key,
                image_inputs=request.image_inputs,
            )
        except InferenceAttemptError as exc:
            raise RuntimeAdapterError(exc.code, str(exc), retryable=True) from exc
        try:
            output = json.loads(response.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeAdapterError(
                "provider_output_not_json",
                "Existing inference adapter returned invalid JSON",
            ) from exc
        if not isinstance(output, dict):
            raise RuntimeAdapterError(
                "provider_output_not_object",
                "Existing inference adapter returned a non-object output",
            )
        return RuntimeAdapterResponse(
            output=output,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            provider_request_id=response.provider_request_id,
            model=self.port.model_for(request.image_inputs),
        )


class CallableRuntimeAdapter:
    """Dependency-free adapter for optional SDKs or internal model gateways."""

    def __init__(
        self,
        profile: AdapterProfile,
        invoke: Callable[[AdapterRequest], RuntimeAdapterResponse],
    ) -> None:
        self.profile = profile
        self._invoke = invoke

    def invoke(self, request: AdapterRequest) -> RuntimeAdapterResponse:
        return self._invoke(request)


class DeterministicFakeRuntimeAdapter:
    """Scripted adapter for contract tests; it never performs network I/O."""

    def __init__(
        self,
        profile: AdapterProfile,
        responses: Sequence[RuntimeAdapterResponse | RuntimeAdapterError | dict[str, Any]],
    ) -> None:
        if not responses:
            raise ValueError("Fake adapter requires at least one scripted response")
        self.profile = profile
        self._responses = tuple(responses)
        self.calls: list[AdapterRequest] = []

    def invoke(self, request: AdapterRequest) -> RuntimeAdapterResponse:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        scripted = self._responses[index]
        if isinstance(scripted, RuntimeAdapterError):
            raise scripted
        if isinstance(scripted, RuntimeAdapterResponse):
            return scripted
        return RuntimeAdapterResponse(
            output=scripted,
            cost_usd=self.profile.estimated_cost_usd,
            latency_ms=self.profile.p95_latency_ms,
        )


class GovernedAgentRuntime:
    """Profit-aware model routing with one immutable governance envelope."""

    def __init__(
        self,
        adapters: Sequence[RuntimeAdapter],
        *,
        task_registry: RuntimeTaskRegistry | None = None,
        audit_ledger: RuntimeAuditLedger | None = None,
        trace_sink: GenAITraceSink | None = None,
        result_store: RuntimeResultStore | None = None,
        allowed_read_tools: frozenset[str] = frozenset(
            {"catalog.read", "evidence.read", "inventory.read", "profit.read"}
        ),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        names = [adapter.profile.name for adapter in adapters]
        if len(names) != len(set(names)):
            raise ValueError("Governed runtime adapter names must be unique")
        self.adapters = tuple(adapters)
        self.task_registry = task_registry
        self.audit_ledger = audit_ledger or InMemoryRuntimeAuditLedger()
        self.trace_sink = trace_sink or NullGenAITraceSink()
        self.result_store = result_store or InMemoryRuntimeResultStore()
        self.allowed_read_tools = frozenset(_normalize_tool(item) for item in allowed_read_tools)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._scope_locks: dict[str, threading.RLock] = {}

    def run(
        self,
        context: AgentRunScopeContext,
        task: RuntimeTask,
    ) -> GovernedRunResult | GovernedRunReceipt:
        contract = self._contract(task.task_type)
        with self._scope_lock(_scope_key(context, task)):
            admitted = self._admit(context, task, contract)
            fingerprint = _task_fingerprint(context, task, contract, admitted)
            scope_key = _scope_key(context, task)
            existing = self.result_store.get(scope_key)
            if existing is not None and existing[0] != fingerprint:
                raise AgentRuntimePolicyError(
                    "idempotency_conflict",
                    "Idempotency key was already used for different governed input",
                )

            run_id = _stable_id("agr", {"scope": scope_key, "fingerprint": fingerprint}, 24)
            trace_id = _stable_hex({"run_id": run_id, "kind": "trace"}, 32)
            root_span_id = _stable_hex({"run_id": run_id, "kind": "root"}, 16)
            started_at = self.clock()
            input_sha256 = _sha256(admitted["safe_input"])
            envelope = RuntimeAuditEnvelope(
                run_id=run_id,
                trace_id=trace_id,
                root_span_id=root_span_id,
                scope=context,
                task_type=task.task_type,
                registry_sha256=contract.registry_sha256,
                contract_version=contract.contract_version,
                prompt_version=contract.prompt_version,
                schema_version=contract.schema_version,
                routing_policy_version=ROUTING_POLICY_VERSION,
                prompt_sha256=_sha256(contract.prompt),
                output_schema_sha256=_sha256(contract.output_schema),
                tool_contract_sha256=_sha256(
                    {
                        "allowed": sorted(contract.allowed_tools),
                        "requested": sorted(admitted["tools"]),
                    }
                ),
                idempotency_key=task.idempotency_key,
                request_sha256=fingerprint,
                input_sha256=input_sha256,
                input_field_names=tuple(sorted(admitted["safe_input"])),
                input_bytes=len(_canonical(admitted["safe_input"])),
                evidence_snapshot_sha256=_sha256(
                    [
                        {
                            "evidence_id": item.evidence_id,
                            "evidence_sha256": item.evidence_sha256,
                        }
                        for item in sorted(
                            context.evidence_refs,
                            key=lambda value: value.evidence_id,
                        )
                    ]
                ),
                required_capabilities=contract.required_capabilities,
                allowed_tools=admitted["tools"],
                max_cost_usd=admitted["effective_cost_cap"],
                max_latency_ms=admitted["max_latency_ms"],
                max_attempts=admitted["max_attempts"],
                started_at=started_at,
            )
            preparation = self.audit_ledger.prepare(envelope)
            if preparation.disposition in {"replay", "unknown_outcome"}:
                if preparation.receipt is None:
                    raise RuntimeError("Durable replay disposition requires a receipt")
                if (
                    preparation.disposition == "replay"
                    and preparation.receipt.status == "succeeded"
                    and existing is not None
                ):
                    return existing[1]
                return preparation.receipt
            if existing is not None:
                raise AgentRuntimePolicyError(
                    "audit_state_conflict",
                    "In-memory result exists without a terminal durable audit state",
                )

            try:
                route = self._route(
                    task,
                    contract,
                    effective_cost_cap=admitted["effective_cost_cap"],
                    max_latency_ms=admitted["max_latency_ms"],
                    max_attempts=admitted["max_attempts"],
                )
            except AgentRuntimePolicyError as exc:
                self.audit_ledger.append(
                    run_id=run_id,
                    event=RuntimeAuditEvent(
                        event_type="run_denied",
                        reason_code=exc.code,
                        occurred_at=self.clock(),
                    ),
                )
                raise
            self.audit_ledger.append(
                run_id=run_id,
                event=RuntimeAuditEvent(
                    event_type="route_selected",
                    safe_payload={
                        "adapter_count": len(route),
                        "adapter_config_sha256": [
                            item[0].profile.config_sha256 for item in route
                        ],
                    },
                    occurred_at=self.clock(),
                ),
            )
            attempts: list[RuntimeAttempt] = []
            total_cost = Decimal("0")
            selected: tuple[RuntimeAdapter, RuntimeAdapterResponse, dict[str, Any]] | None = None

            for attempt_number, (adapter, candidate) in enumerate(route, start=1):
                if attempt_number > admitted["max_attempts"]:
                    break
                if total_cost + candidate.estimated_cost_usd > admitted["effective_cost_cap"]:
                    continue
                attempt_started = self.clock()
                attempt_span_id = _stable_hex(
                    {"run_id": run_id, "kind": "attempt", "attempt": attempt_number},
                    16,
                )
                request = AdapterRequest(
                    run_id=run_id,
                    attempt=attempt_number,
                    task_type=task.task_type,
                    prompt=admitted["safe_prompt"],
                    model_input=admitted["safe_input"],
                    output_schema=contract.output_schema,
                    max_output_tokens=contract.max_output_tokens,
                    timeout_seconds=min(
                        contract.timeout_seconds,
                        max(1, admitted["max_latency_ms"] // 1000),
                    ),
                    idempotency_key=f"{task.idempotency_key}:{attempt_number}",
                    image_inputs=task.image_inputs,
                    tools=admitted["tools"],
                )
                self.audit_ledger.append(
                    run_id=run_id,
                    event=RuntimeAuditEvent(
                        event_type="attempt_started",
                        adapter_name=adapter.profile.name,
                        provider=adapter.profile.provider,
                        model=adapter.profile.model,
                        adapter_config_sha256=adapter.profile.config_sha256,
                        safe_payload={"attempt": attempt_number},
                        occurred_at=attempt_started,
                    ),
                )
                response: RuntimeAdapterResponse | None = None
                try:
                    response = adapter.invoke(request)
                    total_cost += response.cost_usd
                    if total_cost > admitted["effective_cost_cap"]:
                        raise AgentRuntimePolicyError(
                            "actual_cost_budget_exceeded",
                            "Adapter usage exceeded the governed cost budget",
                        )
                    if response.latency_ms > admitted["max_latency_ms"]:
                        raise RuntimeAdapterError(
                            "actual_latency_budget_exceeded",
                            "Adapter exceeded the governed latency budget",
                            retryable=True,
                            latency_ms=response.latency_ms,
                        )
                    safe_output = _sanitize(response.output)
                    if not isinstance(safe_output, dict):
                        raise RuntimeAdapterError(
                            "provider_output_not_object",
                            "Adapter output must be an object",
                        )
                    _validate_schema(safe_output, contract.output_schema, "$output")
                    _guard_output(safe_output, admitted["tools"])
                    attempt = RuntimeAttempt(
                        attempt=attempt_number,
                        adapter_name=adapter.profile.name,
                        provider=adapter.profile.provider,
                        model=response.model or adapter.profile.model,
                        status="succeeded",
                        reason_code=None,
                        estimated_cost_usd=candidate.estimated_cost_usd,
                        actual_cost_usd=response.cost_usd,
                        latency_ms=response.latency_ms,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        span_id=attempt_span_id,
                    )
                    attempts.append(attempt)
                    self._append_after_provider(
                        run_id=run_id,
                        event=RuntimeAuditEvent(
                            event_type="attempt_completed",
                            adapter_name=adapter.profile.name,
                            provider=adapter.profile.provider,
                            model=attempt.model,
                            adapter_config_sha256=adapter.profile.config_sha256,
                            output_sha256=_sha256(safe_output),
                            input_tokens=attempt.input_tokens,
                            output_tokens=attempt.output_tokens,
                            cost_usd=attempt.actual_cost_usd,
                            latency_ms=attempt.latency_ms,
                            safe_payload={"attempt": attempt_number},
                            occurred_at=self.clock(),
                        ),
                    )
                    self._emit_attempt_span(
                        task=task,
                        run_id=run_id,
                        trace_id=trace_id,
                        root_span_id=root_span_id,
                        span_id=attempt_span_id,
                        started_at=attempt_started,
                        adapter=adapter,
                        candidate=candidate,
                        attempt=attempt,
                        status="OK",
                    )
                    selected = (adapter, response, safe_output)
                    break
                except AgentRuntimePolicyError as exc:
                    if exc.code == "unknown_outcome":
                        raise
                    actual_cost = response.cost_usd if response is not None else Decimal("0")
                    attempt = RuntimeAttempt(
                        attempt=attempt_number,
                        adapter_name=adapter.profile.name,
                        provider=adapter.profile.provider,
                        model=(response.model or adapter.profile.model) if response is not None else adapter.profile.model,
                        status="denied",
                        reason_code=exc.code,
                        estimated_cost_usd=candidate.estimated_cost_usd,
                        actual_cost_usd=actual_cost,
                        latency_ms=response.latency_ms if response is not None else 0,
                        input_tokens=response.input_tokens if response is not None else 0,
                        output_tokens=response.output_tokens if response is not None else 0,
                        span_id=attempt_span_id,
                    )
                    attempts.append(attempt)
                    self._append_after_provider(
                        run_id=run_id,
                        event=RuntimeAuditEvent(
                            event_type="attempt_denied",
                            reason_code=exc.code,
                            adapter_name=adapter.profile.name,
                            provider=adapter.profile.provider,
                            model=attempt.model,
                            adapter_config_sha256=adapter.profile.config_sha256,
                            input_tokens=attempt.input_tokens,
                            output_tokens=attempt.output_tokens,
                            cost_usd=attempt.actual_cost_usd,
                            latency_ms=attempt.latency_ms,
                            safe_payload={"attempt": attempt_number},
                            occurred_at=self.clock(),
                        ),
                    )
                    self._emit_attempt_span(
                        task=task,
                        run_id=run_id,
                        trace_id=trace_id,
                        root_span_id=root_span_id,
                        span_id=attempt_span_id,
                        started_at=attempt_started,
                        adapter=adapter,
                        candidate=candidate,
                        attempt=attempt,
                        status="ERROR",
                    )
                    self._emit_root_failure(
                        task,
                        run_id,
                        trace_id,
                        root_span_id,
                        started_at,
                        attempts,
                        exc.code,
                    )
                    self._append_after_provider(
                        run_id=run_id,
                        event=RuntimeAuditEvent(
                            event_type="run_denied",
                            reason_code=exc.code,
                            occurred_at=self.clock(),
                        ),
                    )
                    raise
                except RuntimeAdapterError as exc:
                    if response is None:
                        total_cost += exc.cost_usd
                        actual_cost = exc.cost_usd
                        latency_ms = exc.latency_ms
                        input_tokens = exc.input_tokens
                        output_tokens = exc.output_tokens
                        model = adapter.profile.model
                    else:
                        actual_cost = response.cost_usd
                        latency_ms = response.latency_ms
                        input_tokens = response.input_tokens
                        output_tokens = response.output_tokens
                        model = response.model or adapter.profile.model
                    attempt = RuntimeAttempt(
                        attempt=attempt_number,
                        adapter_name=adapter.profile.name,
                        provider=adapter.profile.provider,
                        model=model,
                        status="failed",
                        reason_code=exc.code,
                        estimated_cost_usd=candidate.estimated_cost_usd,
                        actual_cost_usd=actual_cost,
                        latency_ms=latency_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        span_id=attempt_span_id,
                    )
                    attempts.append(attempt)
                    self._append_after_provider(
                        run_id=run_id,
                        event=RuntimeAuditEvent(
                            event_type="attempt_failed",
                            reason_code=exc.code,
                            adapter_name=adapter.profile.name,
                            provider=adapter.profile.provider,
                            model=attempt.model,
                            adapter_config_sha256=adapter.profile.config_sha256,
                            input_tokens=attempt.input_tokens,
                            output_tokens=attempt.output_tokens,
                            cost_usd=attempt.actual_cost_usd,
                            latency_ms=attempt.latency_ms,
                            safe_payload={"attempt": attempt_number},
                            occurred_at=self.clock(),
                        ),
                    )
                    self._emit_attempt_span(
                        task=task,
                        run_id=run_id,
                        trace_id=trace_id,
                        root_span_id=root_span_id,
                        span_id=attempt_span_id,
                        started_at=attempt_started,
                        adapter=adapter,
                        candidate=candidate,
                        attempt=attempt,
                        status="ERROR",
                    )
                    if not exc.retryable or total_cost > admitted["effective_cost_cap"]:
                        break

            if selected is None:
                self._emit_root_failure(
                    task,
                    run_id,
                    trace_id,
                    root_span_id,
                    started_at,
                    attempts,
                    "all_adapters_failed",
                )
                self._append_after_provider(
                    run_id=run_id,
                    event=RuntimeAuditEvent(
                        event_type="run_failed",
                        reason_code="all_adapters_failed",
                        cost_usd=total_cost,
                        occurred_at=self.clock(),
                    ),
                )
                raise AgentRuntimeExhaustedError(
                    "all_adapters_failed",
                    "No eligible runtime adapter produced a governed proposal",
                    attempts=tuple(attempts),
                )

            adapter, response, output = selected
            output_sha256 = _sha256(output)
            eval_record = self._evaluate(
                task=task,
                contract=contract,
                max_latency_ms=admitted["max_latency_ms"],
                max_cost_usd=admitted["effective_cost_cap"],
                run_id=run_id,
                trace_id=trace_id,
                span_id=root_span_id,
                adapter=adapter,
                response=response,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                total_cost=total_cost,
            )
            eval_sha256 = _sha256(_json_safe(asdict(eval_record)))
            self._append_after_provider(
                run_id=run_id,
                event=RuntimeAuditEvent(
                    event_type="eval_completed",
                    adapter_name=adapter.profile.name,
                    provider=adapter.profile.provider,
                    model=response.model or adapter.profile.model,
                    adapter_config_sha256=adapter.profile.config_sha256,
                    output_sha256=output_sha256,
                    eval_sha256=eval_sha256,
                    safe_payload={
                        "passed": eval_record.passed,
                        "assertion_count": len(eval_record.assertions),
                    },
                    occurred_at=self.clock(),
                ),
            )
            result = GovernedRunResult(
                contract_id=RUNTIME_CONTRACT_ID,
                run_id=run_id,
                trace_id=trace_id,
                root_span_id=root_span_id,
                task_type=task.task_type,
                provider=adapter.profile.provider,
                model=response.model or adapter.profile.model,
                input_sha256=input_sha256,
                output=output,
                output_sha256=output_sha256,
                total_cost_usd=total_cost,
                attempts=tuple(attempts),
                route=tuple(item[1] for item in route),
                eval_record=eval_record,
            )
            self._append_after_provider(
                run_id=run_id,
                event=RuntimeAuditEvent(
                    event_type="run_succeeded",
                    output_sha256=output_sha256,
                    eval_sha256=eval_sha256,
                    input_tokens=sum(item.input_tokens for item in attempts),
                    output_tokens=sum(item.output_tokens for item in attempts),
                    cost_usd=total_cost,
                    latency_ms=sum(item.latency_ms for item in attempts),
                    safe_payload={"attempt_count": len(attempts)},
                    occurred_at=self.clock(),
                ),
            )
            self.result_store.put(scope_key, fingerprint, result)
            self._emit_root_success(task, result, started_at)
            return result

    def list_runs(
        self,
        *,
        context: AgentRunScopeContext,
        status: str | None = None,
        task_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.audit_ledger.list_runs(
            context=context,
            status=status,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )

    def get_run(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> dict[str, Any]:
        return self.audit_ledger.get_run(context=context, run_id=run_id)

    def replay(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> GovernedRunReceipt:
        return self.audit_ledger.replay(context=context, run_id=run_id)

    def _append_after_provider(
        self,
        *,
        run_id: str,
        event: RuntimeAuditEvent,
    ) -> None:
        try:
            self.audit_ledger.append(run_id=run_id, event=event)
        except Exception as exc:
            raise AgentRuntimePolicyError(
                "unknown_outcome",
                "Provider returned but the durable outcome could not be persisted",
            ) from exc

    @contextmanager
    def _scope_lock(self, scope_key: str) -> Iterator[None]:
        with self._lock:
            lock = self._scope_locks.setdefault(scope_key, threading.RLock())
        with lock:
            yield

    def _contract(self, task_type: str) -> RuntimeTaskContract:
        if self.task_registry is None:
            raise AgentRuntimePolicyError(
                "task_registry_missing",
                "Governed runtime requires the canonical Agent task registry",
            )
        payload = self.task_registry.require(task_type)
        return RuntimeTaskContract.from_registry(
            task_type=task_type,
            registry_sha256=self.task_registry.registry_sha256,
            registry_payload=payload,
            registry_authority=self.task_registry.payload.get("authority", {}),
        )

    def _admit(
        self,
        context: AgentRunScopeContext,
        task: RuntimeTask,
        contract: RuntimeTaskContract,
    ) -> dict[str, Any]:
        if not task.task_type.strip() or not task.idempotency_key.strip():
            raise AgentRuntimePolicyError(
                "task_identity_incomplete",
                "Runtime task type and idempotency key are required",
            )
        if task.task_type != contract.task_type:
            raise AgentRuntimePolicyError(
                "task_contract_drift", "Runtime task contract does not match task type"
            )
        if not context.evidence_refs:
            raise AgentRuntimePolicyError(
                "scoped_evidence_missing",
                "Governed runtime requires current exact-scope Evidence",
            )
        unknown_fields = sorted(
            set(task.model_input) - set(contract.allowed_input_fields)
        )
        if unknown_fields:
            raise AgentRuntimePolicyError(
                "input_field_not_allowed",
                f"Model input contains fields outside the task contract: {', '.join(unknown_fields)}",
            )
        max_cost = contract.max_cost_usd
        if task.max_cost_usd is not None:
            requested_cost = _decimal(task.max_cost_usd, "max_cost_usd")
            if requested_cost > contract.max_cost_usd:
                raise AgentRuntimePolicyError(
                    "cost_budget_exceeds_contract",
                    "Requested cost budget exceeds the task contract",
                )
            max_cost = requested_cost
        max_latency_ms = contract.max_latency_ms
        if task.max_latency_ms is not None:
            if task.max_latency_ms > contract.max_latency_ms:
                raise AgentRuntimePolicyError(
                    "latency_budget_exceeds_contract",
                    "Requested latency budget exceeds the task contract",
                )
            max_latency_ms = task.max_latency_ms
        max_attempts = contract.max_attempts
        if task.max_attempts is not None:
            if task.max_attempts > contract.max_attempts:
                raise AgentRuntimePolicyError(
                    "attempt_budget_exceeds_contract",
                    "Requested attempt budget exceeds the task contract",
                )
            max_attempts = task.max_attempts
        ratio = _decimal(task.max_cost_to_profit_ratio, "max_cost_to_profit_ratio")
        if max_cost < 0 or ratio < 0:
            raise AgentRuntimePolicyError("cost_budget_invalid", "Runtime cost budgets cannot be negative")
        if max_latency_ms < 1 or contract.timeout_seconds < 1:
            raise AgentRuntimePolicyError("latency_budget_invalid", "Runtime latency budget must be positive")
        if max_attempts < 1 or max_attempts > 8:
            raise AgentRuntimePolicyError("attempt_budget_invalid", "Runtime attempt budget is invalid")
        if contract.max_output_tokens < 1:
            raise AgentRuntimePolicyError("output_budget_invalid", "Runtime output token budget must be positive")
        _guard_schema(contract.output_schema)
        tools = tuple(_normalize_tool(item) for item in task.requested_tools)
        allowed = frozenset(_normalize_tool(item) for item in contract.allowed_tools)
        for tool in tools:
            if _tool_is_denied(tool) or tool not in allowed or tool not in self.allowed_read_tools:
                raise AgentRuntimePolicyError(
                    "tool_denied",
                    f"Tool is not admitted as a governed read operation: {_safe_code(tool)}",
                )
        safe_prompt = _redact_text(contract.prompt)
        safe_input = _sanitize(task.model_input)
        profit = (
            None
            if task.expected_profit_value_usd is None
            else _decimal(task.expected_profit_value_usd, "expected_profit_value_usd")
        )
        if profit is not None and profit < 0:
            raise AgentRuntimePolicyError("profit_value_invalid", "Expected profit value cannot be negative")
        effective_cost_cap = max_cost
        if profit is not None:
            effective_cost_cap = min(max_cost, profit * ratio)
        return {
            "safe_prompt": safe_prompt,
            "safe_input": safe_input,
            "tools": tools,
            "effective_cost_cap": effective_cost_cap,
            "max_latency_ms": max_latency_ms,
            "max_attempts": max_attempts,
        }

    def _route(
        self,
        task: RuntimeTask,
        contract: RuntimeTaskContract,
        *,
        effective_cost_cap: Decimal,
        max_latency_ms: int,
        max_attempts: int,
    ) -> tuple[tuple[RuntimeAdapter, RouteCandidate], ...]:
        required = frozenset(contract.required_capabilities)
        candidates: list[tuple[RuntimeAdapter, RouteCandidate]] = []
        for adapter in self.adapters:
            profile = adapter.profile
            if not required.issubset(profile.capabilities):
                continue
            if profile.estimated_accuracy < contract.min_accuracy:
                continue
            if profile.p95_latency_ms > max_latency_ms:
                continue
            if profile.estimated_cost_usd > effective_cost_cap:
                continue
            score = _route_score(
                profile,
                task,
                effective_cost_cap,
                max_latency_ms=max_latency_ms,
            )
            candidates.append(
                (
                    adapter,
                    RouteCandidate(
                        adapter_name=profile.name,
                        provider=profile.provider,
                        model=profile.model,
                        estimated_accuracy=profile.estimated_accuracy,
                        estimated_latency_ms=profile.p95_latency_ms,
                        estimated_cost_usd=profile.estimated_cost_usd,
                        score=score,
                    ),
                )
            )
        candidates.sort(
            key=lambda item: (
                -item[1].score,
                -item[1].estimated_accuracy,
                item[1].estimated_cost_usd,
                item[1].estimated_latency_ms,
                item[1].adapter_name,
            )
        )
        if not candidates:
            raise AgentRuntimePolicyError(
                "no_eligible_adapter",
                "No adapter satisfies capability, accuracy, latency, and profit-aware cost budgets",
            )
        return tuple(candidates[:max_attempts])

    def _evaluate(
        self,
        *,
        task: RuntimeTask,
        contract: RuntimeTaskContract,
        max_latency_ms: int,
        max_cost_usd: Decimal,
        run_id: str,
        trace_id: str,
        span_id: str,
        adapter: RuntimeAdapter,
        response: RuntimeAdapterResponse,
        input_sha256: str,
        output_sha256: str,
        total_cost: Decimal,
    ) -> EvalRecord:
        assertions = (
            EvalAssertion(
                "capability_match",
                frozenset(contract.required_capabilities).issubset(
                    adapter.profile.capabilities
                ),
                Decimal("1"),
                "capabilities_satisfied",
            ),
            EvalAssertion(
                "accuracy_threshold",
                adapter.profile.estimated_accuracy >= contract.min_accuracy,
                adapter.profile.estimated_accuracy,
                "estimated_accuracy_satisfied",
            ),
            EvalAssertion(
                "latency_budget",
                response.latency_ms <= max_latency_ms,
                Decimal("1") if response.latency_ms <= max_latency_ms else Decimal("0"),
                "latency_budget_satisfied",
            ),
            EvalAssertion(
                "cost_budget",
                total_cost <= max_cost_usd,
                Decimal("1") if total_cost <= max_cost_usd else Decimal("0"),
                "cost_budget_satisfied",
            ),
            EvalAssertion("proposal_only", True, Decimal("1"), "governance_envelope_enforced"),
            EvalAssertion("no_privileged_action", True, Decimal("1"), "output_guardrail_passed"),
        )
        score = sum((item.score for item in assertions), Decimal("0")) / Decimal(len(assertions))
        stable = {
            "run_id": run_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "task_type": task.task_type,
            "routing_policy_version": ROUTING_POLICY_VERSION,
            "adapter_name": adapter.profile.name,
            "model": response.model or adapter.profile.model,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "assertions": [
                {
                    "name": item.name,
                    "passed": item.passed,
                    "score": str(item.score),
                    "detail_code": item.detail_code,
                }
                for item in assertions
            ],
            "score": str(score),
            "passed": all(item.passed for item in assertions),
        }
        return EvalRecord(
            eval_id=_stable_id("aev", stable, 24),
            run_id=run_id,
            trace_id=trace_id,
            span_id=span_id,
            task_type=task.task_type,
            routing_policy_version=ROUTING_POLICY_VERSION,
            adapter_name=adapter.profile.name,
            model=response.model or adapter.profile.model,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            assertions=assertions,
            score=score,
            passed=all(item.passed for item in assertions),
        )

    def _emit_attempt_span(
        self,
        *,
        task: RuntimeTask,
        run_id: str,
        trace_id: str,
        root_span_id: str,
        span_id: str,
        started_at: datetime,
        adapter: RuntimeAdapter,
        candidate: RouteCandidate,
        attempt: RuntimeAttempt,
        status: str,
    ) -> None:
        attributes = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.provider.name": adapter.profile.provider,
            "gen_ai.request.model": attempt.model,
            "gen_ai.usage.input_tokens": attempt.input_tokens,
            "gen_ai.usage.output_tokens": attempt.output_tokens,
            "error.type": attempt.reason_code or "",
            "kjds.agent.run_id": run_id,
            "kjds.agent.task_type": task.task_type,
            "kjds.agent.adapter": adapter.profile.name,
            "kjds.agent.routing_score": str(candidate.score),
            "kjds.agent.estimated_accuracy": str(candidate.estimated_accuracy),
            "kjds.agent.cost_usd": str(attempt.actual_cost_usd),
            "kjds.agent.proposal_only": True,
            "kjds.agent.external_write_allowed": False,
        }
        self._emit(
            GenAISpan(
                name="kjds.agent.adapter.invoke",
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=root_span_id,
                started_at=_iso(started_at),
                ended_at=_iso(self.clock()),
                status=status,
                attributes=_sanitize(attributes),
                events=(
                    GenAISpanEvent(
                        name="kjds.agent.route.selected",
                        attributes={
                            "adapter": adapter.profile.name,
                            "attempt": attempt.attempt,
                            "reason_code": attempt.reason_code or "selected",
                        },
                    ),
                ),
            )
        )

    def _emit_root_success(
        self,
        task: RuntimeTask,
        result: GovernedRunResult,
        started_at: datetime,
    ) -> None:
        self._emit(
            GenAISpan(
                name="kjds.agent.run",
                trace_id=result.trace_id,
                span_id=result.root_span_id,
                parent_span_id=None,
                started_at=_iso(started_at),
                ended_at=_iso(self.clock()),
                status="OK",
                attributes=_sanitize(
                    {
                        "gen_ai.operation.name": "invoke_agent",
                        "gen_ai.provider.name": result.provider,
                        "gen_ai.response.model": result.model,
                        "kjds.agent.run_id": result.run_id,
                        "kjds.agent.task_type": task.task_type,
                        "kjds.agent.input_sha256": result.input_sha256,
                        "kjds.agent.output_sha256": result.output_sha256,
                        "kjds.agent.eval_id": result.eval_record.eval_id,
                        "kjds.agent.total_cost_usd": str(result.total_cost_usd),
                        "kjds.business.expected_profit_value_usd": (
                            "unknown"
                            if task.expected_profit_value_usd is None
                            else str(task.expected_profit_value_usd)
                        ),
                        "kjds.agent.proposal_only": True,
                        "kjds.agent.formal_fact": False,
                        "kjds.agent.self_approval_allowed": False,
                        "kjds.agent.permit_issue_allowed": False,
                        "kjds.agent.external_write_allowed": False,
                    }
                ),
            )
        )

    def _emit_root_failure(
        self,
        task: RuntimeTask,
        run_id: str,
        trace_id: str,
        root_span_id: str,
        started_at: datetime,
        attempts: Sequence[RuntimeAttempt],
        reason_code: str,
    ) -> None:
        self._emit(
            GenAISpan(
                name="kjds.agent.run",
                trace_id=trace_id,
                span_id=root_span_id,
                parent_span_id=None,
                started_at=_iso(started_at),
                ended_at=_iso(self.clock()),
                status="ERROR",
                attributes=_sanitize(
                    {
                        "gen_ai.operation.name": "invoke_agent",
                        "error.type": reason_code,
                        "kjds.agent.run_id": run_id,
                        "kjds.agent.task_type": task.task_type,
                        "kjds.agent.attempt_count": len(attempts),
                        "kjds.agent.proposal_only": True,
                        "kjds.agent.external_write_allowed": False,
                    }
                ),
            )
        )

    def _emit(self, span: GenAISpan) -> None:
        try:
            self.trace_sink.emit(span)
        except Exception:
            # Telemetry is deliberately non-authoritative and cannot block governance.
            return


def _route_score(
    profile: AdapterProfile,
    task: RuntimeTask,
    effective_cost_cap: Decimal,
    *,
    max_latency_ms: int,
) -> Decimal:
    profit = (
        Decimal("0")
        if task.expected_profit_value_usd is None
        else _decimal(task.expected_profit_value_usd, "expected_profit_value_usd")
    )
    profit_weight = profit / (profit + Decimal("100")) if profit > 0 else Decimal("0")
    accuracy_weight = Decimal("0.45") + Decimal("0.35") * profit_weight
    cost_weight = Decimal("0.40") - Decimal("0.25") * profit_weight
    latency_weight = Decimal("1") - accuracy_weight - cost_weight
    cost_denominator = max(effective_cost_cap, Decimal("0.000001"))
    latency_denominator = max(max_latency_ms, 1)
    cost_score = max(Decimal("0"), Decimal("1") - profile.estimated_cost_usd / cost_denominator)
    latency_score = max(
        Decimal("0"),
        Decimal("1") - Decimal(profile.p95_latency_ms) / Decimal(latency_denominator),
    )
    score = (
        profile.estimated_accuracy * accuracy_weight
        + cost_score * cost_weight
        + latency_score * latency_weight
    )
    return score.quantize(Decimal("0.000001"))


def _guard_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return
    for key, nested in properties.items():
        lowered = str(key).strip().lower()
        if lowered in _PRIVILEGED_OUTPUT_KEYS or lowered in {
            "approved",
            "approval_status",
            "formal_fact",
        }:
            raise AgentRuntimePolicyError(
                "output_schema_privilege_escalation",
                "Model output schema cannot grant facts, approvals, permits, or writes",
            )
        if isinstance(nested, dict):
            _guard_schema(nested)
            items = nested.get("items")
            if isinstance(items, dict):
                _guard_schema(items)


def _guard_output(output: dict[str, Any], admitted_tools: tuple[str, ...]) -> None:
    admitted = frozenset(admitted_tools)

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            lowered = {str(key).strip().lower(): item for key, item in value.items()}
            for key, item in lowered.items():
                if key == "formal_fact" and _truthy(item):
                    _deny_output(path, "formal_fact_promotion_denied")
                if key in {"approved", "self_approved"} and _truthy(item):
                    _deny_output(path, "self_approval_denied")
                if key == "approval_status" and str(item).strip().lower() in _POSITIVE_APPROVAL_VALUES:
                    _deny_output(path, "self_approval_denied")
                if key in _PRIVILEGED_OUTPUT_KEYS and _truthy(item):
                    if "permit" in key:
                        _deny_output(path, "permit_issue_denied")
                    if "approval" in key or "approved" in key:
                        _deny_output(path, "self_approval_denied")
                    _deny_output(path, "marketplace_write_denied")
            tool = _tool_from_mapping(lowered)
            if tool:
                if _tool_is_denied(tool):
                    _deny_output(path, "tool_denied")
                if tool not in admitted:
                    _deny_output(path, "unrequested_tool_denied")
            action = lowered.get("action") or lowered.get("operation")
            if isinstance(action, str) and _tool_is_denied(action):
                _deny_output(path, "tool_denied")
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(output, "$output")


def _deny_output(path: str, code: str) -> None:
    raise RuntimeAdapterError(code, f"Model output attempted a privileged action at {_safe_code(path)}")


def _tool_from_mapping(value: Mapping[str, Any]) -> str | None:
    for key in ("tool_name", "tool"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return _normalize_tool(candidate)
    if "arguments" in value and isinstance(value.get("name"), str):
        return _normalize_tool(str(value["name"]))
    return None


def _tool_is_denied(tool: str) -> bool:
    normalized = _normalize_tool(tool)
    if normalized in _DENIED_TOOL_TOKENS:
        return True
    return any(normalized.startswith(prefix) for prefix in _DENIED_TOOL_PREFIXES)


def _normalize_tool(value: str) -> str:
    return re.sub(r"[^a-z0-9_.:-]+", ".", str(value).strip().lower()).strip(".")


def _truthy(value: Any) -> bool:
    if value is None or value is False or value == 0:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "none", "no", "not_allowed", "proposal_only"}
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return bool(value)
    return bool(value)


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected and not _matches_type(value, str(expected)):
        raise RuntimeAdapterError("output_schema_invalid", f"Schema type mismatch at {_safe_code(path)}")
    if "enum" in schema and value not in schema["enum"]:
        raise RuntimeAdapterError("output_schema_invalid", f"Schema enum mismatch at {_safe_code(path)}")
    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise RuntimeAdapterError("output_schema_invalid", f"Required output missing at {_safe_code(path)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise RuntimeAdapterError("output_schema_invalid", f"Unexpected output field at {_safe_code(path)}")
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _validate_schema(item, child, f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "array": isinstance(value, list),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
        "number": isinstance(value, (int, float, Decimal)) and not isinstance(value, bool),
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }.get(expected, True)


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            sanitized[text_key] = REDACTED if _SENSITIVE_KEY.search(text_key) else _sanitize(item)
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


def _redact_text(value: str) -> str:
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}={REDACTED}", value)


def _scope_key(context: AgentRunScopeContext, task: RuntimeTask) -> str:
    return _sha256(
        {
            "tenant_ref": context.tenant_ref,
            "entity_ref": context.entity_ref,
            "store_ref": context.store_ref,
            "authority_sha256": context.authority_sha256,
            "task_type": task.task_type,
            "idempotency_key": task.idempotency_key,
        }
    )


def _task_fingerprint(
    context: AgentRunScopeContext,
    task: RuntimeTask,
    contract: RuntimeTaskContract,
    admitted: Mapping[str, Any],
) -> str:
    return _sha256(
        {
            "contract_id": RUNTIME_CONTRACT_ID,
            "routing_policy_version": ROUTING_POLICY_VERSION,
            "task_type": task.task_type,
            "scope": [
                context.tenant_ref,
                context.entity_ref,
                context.store_ref,
                context.authority_sha256,
                context.actor_id,
            ],
            "evidence": [
                [item.evidence_id, item.evidence_sha256]
                for item in sorted(
                    context.evidence_refs,
                    key=lambda value: value.evidence_id,
                )
            ],
            "registry_sha256": contract.registry_sha256,
            "contract_version": contract.contract_version,
            "prompt_version": contract.prompt_version,
            "schema_version": contract.schema_version,
            "prompt_sha256": _sha256(contract.prompt),
            "model_input": admitted["safe_input"],
            "output_schema_sha256": _sha256(contract.output_schema),
            "required_capabilities": sorted(contract.required_capabilities),
            "max_latency_ms": admitted["max_latency_ms"],
            "max_cost_usd": str(admitted["effective_cost_cap"]),
            "expected_profit_value_usd": (
                None if task.expected_profit_value_usd is None else str(task.expected_profit_value_usd)
            ),
            "max_cost_to_profit_ratio": str(task.max_cost_to_profit_ratio),
            "max_attempts": admitted["max_attempts"],
            "max_output_tokens": contract.max_output_tokens,
            "timeout_seconds": contract.timeout_seconds,
            "allowed_tools": sorted(contract.allowed_tools),
            "requested_tools": sorted(task.requested_tools),
            "image_input_sha256": [_sha256(item) for item in task.image_inputs],
        }
    )


_TERMINAL_AUDIT_EVENTS = frozenset(
    {"run_succeeded", "run_failed", "run_denied", "unknown_outcome"}
)
_AUDIT_TRANSITIONS = {
    None: frozenset({"run_started"}),
    "run_started": frozenset({"route_selected", "run_denied"}),
    "route_selected": frozenset({"attempt_started", "run_failed", "unknown_outcome"}),
    "attempt_started": frozenset(
        {"attempt_completed", "attempt_denied", "attempt_failed", "unknown_outcome"}
    ),
    "attempt_completed": frozenset({"eval_completed", "unknown_outcome"}),
    "attempt_denied": frozenset({"run_denied", "unknown_outcome"}),
    "attempt_failed": frozenset({"attempt_started", "run_failed", "unknown_outcome"}),
    "eval_completed": frozenset({"run_succeeded", "unknown_outcome"}),
}


def _assert_event_transition(
    events: Sequence[Mapping[str, Any]],
    event_type: str,
) -> None:
    previous = str(events[-1]["event_type"]) if events else None
    if previous in _TERMINAL_AUDIT_EVENTS:
        raise AgentRuntimePolicyError(
            "terminal_event_conflict",
            "A terminal governed Agent run cannot accept more events",
        )
    if event_type not in _AUDIT_TRANSITIONS.get(previous, frozenset()):
        raise AgentRuntimePolicyError(
            "event_transition_invalid",
            "Governed Agent run event transition is invalid",
        )


def _audit_event_payload(
    *,
    event: RuntimeAuditEvent,
    event_index: int,
    previous_event_sha256: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    if occurred_at.tzinfo is None:
        raise ValueError("Runtime audit event time must include a timezone")
    if event_index < 1:
        raise ValueError("Runtime audit event index must be positive")
    if not re.fullmatch(r"[0-9a-f]{64}", previous_event_sha256):
        raise ValueError("Runtime audit previous event hash is invalid")
    for field_name, value in {
        "adapter_config_sha256": event.adapter_config_sha256,
        "output_sha256": event.output_sha256,
        "eval_sha256": event.eval_sha256,
    }.items():
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{field_name} must be a lowercase SHA-256")
    payload = {
        "event_index": event_index,
        "event_type": event.event_type,
        "reason_code": _safe_code(event.reason_code) if event.reason_code else None,
        "adapter_sha256": _sha256(event.adapter_name) if event.adapter_name else None,
        "provider_sha256": _sha256(event.provider) if event.provider else None,
        "model_sha256": _sha256(event.model) if event.model else None,
        "adapter_config_sha256": event.adapter_config_sha256,
        "output_sha256": event.output_sha256,
        "eval_sha256": event.eval_sha256,
        "input_tokens": _non_negative_int(event.input_tokens, "input_tokens"),
        "output_tokens": _non_negative_int(event.output_tokens, "output_tokens"),
        "cost_usd": _decimal_string(
            _non_negative_decimal(event.cost_usd, "cost_usd")
        ),
        "latency_ms": _non_negative_int(event.latency_ms, "latency_ms"),
        "safe_payload": _json_safe(event.safe_payload),
        "previous_event_sha256": previous_event_sha256,
        "occurred_at": _iso(occurred_at),
    }
    _guard_audit_payload(payload)
    payload["event_sha256"] = _sha256(payload)
    return payload


def _event_status(event_type: str) -> str:
    return event_type.removeprefix("run_")


def _envelope_visible(
    envelope: RuntimeAuditEnvelope,
    context: AgentRunScopeContext,
) -> bool:
    return (
        envelope.scope.tenant_ref == context.tenant_ref
        and envelope.scope.entity_ref == context.entity_ref
        and envelope.scope.store_ref == context.store_ref
        and envelope.scope.authority_sha256 == context.authority_sha256
        and envelope.started_at <= context.scope_as_of
    )


def _run_projection(
    *,
    envelope: RuntimeAuditEnvelope,
    events: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Mapping[str, str]] | None,
) -> dict[str, Any]:
    latest = events[-1]
    projected_events = []
    for index, event in enumerate(events):
        projected = dict(event)
        if evidence_refs is not None:
            projected["evidence"] = dict(evidence_refs[index])
        projected_events.append(projected)
    return {
        "contract_id": "kjds-governed-agent-run-audit-v1",
        "run_id": envelope.run_id,
        "trace_id": envelope.trace_id,
        "task_type": envelope.task_type,
        "status": _event_status(str(latest["event_type"])),
        "started_at": _iso(envelope.started_at),
        "last_event_at": str(latest["occurred_at"]),
        "event_count": len(events),
        "registry_sha256": envelope.registry_sha256,
        "contract_version": envelope.contract_version,
        "prompt_version": envelope.prompt_version,
        "schema_version": envelope.schema_version,
        "routing_policy_version": envelope.routing_policy_version,
        "prompt_sha256": envelope.prompt_sha256,
        "output_schema_sha256": envelope.output_schema_sha256,
        "tool_contract_sha256": envelope.tool_contract_sha256,
        "request_sha256": envelope.request_sha256,
        "input_sha256": envelope.input_sha256,
        "input_field_names": list(envelope.input_field_names),
        "input_bytes": envelope.input_bytes,
        "evidence_snapshot_sha256": envelope.evidence_snapshot_sha256,
        "required_capabilities": list(envelope.required_capabilities),
        "allowed_tools": list(envelope.allowed_tools),
        "limits": {
            "max_cost_usd": str(envelope.max_cost_usd),
            "max_latency_ms": envelope.max_latency_ms,
            "max_attempts": envelope.max_attempts,
        },
        "payload_status": "not_retained",
        "proposal_only": True,
        "formal_fact": False,
        "external_write_allowed": False,
        "events": projected_events,
    }


def _run_listing(
    *,
    rows: list[dict[str, Any]],
    total: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "contract_id": "kjds-governed-agent-run-list-v1",
        "status": "ready" if rows else "no_data",
        "runs": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
        "snapshot_sha256": _sha256(rows),
    }


def _validate_page(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset cannot be negative")


def _non_negative_decimal(value: Any, field_name: str) -> Decimal:
    result = _decimal(value, field_name)
    if result < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return result


def _decimal_string(value: Decimal) -> str:
    if -value.as_tuple().exponent > 18:
        raise ValueError("Runtime audit decimal precision exceeds 18 places")
    rendered = format(value, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if result < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return result


def _guard_audit_payload(payload: Mapping[str, Any]) -> None:
    forbidden = {
        "prompt",
        "model_input",
        "output",
        "tool_arguments",
        "image_inputs",
        "provider_request_id",
        "error_detail",
        "raw_response",
    }

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).strip().lower()
                if normalized in forbidden or _SENSITIVE_KEY.search(normalized):
                    raise ValueError("Runtime audit payload contains forbidden plaintext")
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif (
            isinstance(value, (float, Decimal))
            and not Decimal(str(value)).is_finite()
        ):
            raise ValueError("Runtime audit payload contains a non-finite number")
        elif isinstance(value, str) and _SECRET_ASSIGNMENT.search(value):
            raise ValueError("Runtime audit payload contains secret-like plaintext")

    walk(payload)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_hex(value: Any, length: int) -> str:
    return _sha256(value)[:length]


def _stable_id(prefix: str, value: Any, length: int) -> str:
    return f"{prefix}_{_stable_hex(value, length)}"


def _safe_code(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:\-\[\]]+", "_", str(value))[:160]


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
