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
from typing import Any, Protocol

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
class RuntimeTask:
    task_type: str
    tenant_ref: str
    entity_ref: str
    store_ref: str
    prompt: str
    model_input: dict[str, Any]
    output_schema: dict[str, Any]
    required_capabilities: tuple[str, ...]
    idempotency_key: str
    requested_by: str
    min_accuracy: Decimal = Decimal("0")
    max_latency_ms: int = 30_000
    max_cost_usd: Decimal = Decimal("1")
    expected_profit_value_usd: Decimal | None = None
    max_cost_to_profit_ratio: Decimal = Decimal("0.10")
    max_attempts: int = 2
    max_output_tokens: int = 2_000
    timeout_seconds: int = 30
    allowed_tools: tuple[str, ...] = ()
    requested_tools: tuple[str, ...] = ()
    agent_actor_id: str = "kjds-agent-runtime"
    approval_actor_id: str | None = None
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
        trace_sink: GenAITraceSink | None = None,
        result_store: RuntimeResultStore | None = None,
        allowed_read_tools: frozenset[str] = frozenset(
            {"catalog.read", "evidence.read", "inventory.read", "profit.read"}
        ),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not adapters:
            raise ValueError("Governed runtime requires at least one adapter")
        names = [adapter.profile.name for adapter in adapters]
        if len(names) != len(set(names)):
            raise ValueError("Governed runtime adapter names must be unique")
        self.adapters = tuple(adapters)
        self.trace_sink = trace_sink or NullGenAITraceSink()
        self.result_store = result_store or InMemoryRuntimeResultStore()
        self.allowed_read_tools = frozenset(_normalize_tool(item) for item in allowed_read_tools)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._scope_locks: dict[str, threading.RLock] = {}

    def run(self, task: RuntimeTask) -> GovernedRunResult:
        with self._scope_lock(_scope_key(task)):
            admitted = self._admit(task)
            fingerprint = _task_fingerprint(task)
            scope_key = _scope_key(task)
            existing = self.result_store.get(scope_key)
            if existing is not None:
                if existing[0] != fingerprint:
                    raise AgentRuntimePolicyError(
                        "idempotency_conflict",
                        "Idempotency key was already used for different governed input",
                    )
                return existing[1]

            run_id = _stable_id("agr", {"scope": scope_key, "fingerprint": fingerprint}, 24)
            trace_id = _stable_hex({"run_id": run_id, "kind": "trace"}, 32)
            root_span_id = _stable_hex({"run_id": run_id, "kind": "root"}, 16)
            started_at = self.clock()
            route = self._route(task, admitted["effective_cost_cap"])
            attempts: list[RuntimeAttempt] = []
            total_cost = Decimal("0")
            selected: tuple[RuntimeAdapter, RuntimeAdapterResponse, dict[str, Any]] | None = None

            for attempt_number, (adapter, candidate) in enumerate(route, start=1):
                if attempt_number > task.max_attempts:
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
                    output_schema=task.output_schema,
                    max_output_tokens=task.max_output_tokens,
                    timeout_seconds=min(task.timeout_seconds, max(1, task.max_latency_ms // 1000)),
                    idempotency_key=f"{task.idempotency_key}:{attempt_number}",
                    image_inputs=task.image_inputs,
                    tools=admitted["tools"],
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
                    if response.latency_ms > task.max_latency_ms:
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
                    _validate_schema(safe_output, task.output_schema, "$output")
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
                raise AgentRuntimeExhaustedError(
                    "all_adapters_failed",
                    "No eligible runtime adapter produced a governed proposal",
                    attempts=tuple(attempts),
                )

            adapter, response, output = selected
            input_sha256 = _sha256(admitted["safe_input"])
            output_sha256 = _sha256(output)
            eval_record = self._evaluate(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                span_id=root_span_id,
                adapter=adapter,
                response=response,
                input_sha256=input_sha256,
                output_sha256=output_sha256,
                total_cost=total_cost,
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
            self.result_store.put(scope_key, fingerprint, result)
            self._emit_root_success(task, result, started_at)
            return result

    @contextmanager
    def _scope_lock(self, scope_key: str) -> Iterator[None]:
        with self._lock:
            lock = self._scope_locks.setdefault(scope_key, threading.RLock())
        with lock:
            yield

    def _admit(self, task: RuntimeTask) -> dict[str, Any]:
        identity = (
            task.task_type,
            task.tenant_ref,
            task.entity_ref,
            task.store_ref,
            task.idempotency_key,
            task.requested_by,
            task.agent_actor_id,
        )
        if any(not value.strip() for value in identity):
            raise AgentRuntimePolicyError("scope_incomplete", "Runtime task scope and identity must be complete")
        min_accuracy = _decimal(task.min_accuracy, "min_accuracy")
        max_cost = _decimal(task.max_cost_usd, "max_cost_usd")
        ratio = _decimal(task.max_cost_to_profit_ratio, "max_cost_to_profit_ratio")
        if min_accuracy < 0 or min_accuracy > 1:
            raise AgentRuntimePolicyError("accuracy_budget_invalid", "Minimum accuracy must be between zero and one")
        if max_cost < 0 or ratio < 0:
            raise AgentRuntimePolicyError("cost_budget_invalid", "Runtime cost budgets cannot be negative")
        if task.max_latency_ms < 1 or task.timeout_seconds < 1:
            raise AgentRuntimePolicyError("latency_budget_invalid", "Runtime latency budget must be positive")
        if task.max_attempts < 1 or task.max_attempts > 8:
            raise AgentRuntimePolicyError("attempt_budget_invalid", "Runtime attempt budget is invalid")
        if task.max_output_tokens < 1:
            raise AgentRuntimePolicyError("output_budget_invalid", "Runtime output token budget must be positive")
        if task.approval_actor_id and task.approval_actor_id == task.agent_actor_id:
            raise AgentRuntimePolicyError(
                "self_approval_denied",
                "An agent cannot approve its own proposal",
            )
        _guard_schema(task.output_schema)
        tools = tuple(_normalize_tool(item) for item in task.requested_tools)
        allowed = frozenset(_normalize_tool(item) for item in task.allowed_tools)
        for tool in tools:
            if _tool_is_denied(tool) or tool not in allowed or tool not in self.allowed_read_tools:
                raise AgentRuntimePolicyError(
                    "tool_denied",
                    f"Tool is not admitted as a governed read operation: {_safe_code(tool)}",
                )
        safe_prompt = _redact_text(task.prompt)
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
        }

    def _route(
        self,
        task: RuntimeTask,
        effective_cost_cap: Decimal,
    ) -> tuple[tuple[RuntimeAdapter, RouteCandidate], ...]:
        required = frozenset(task.required_capabilities)
        candidates: list[tuple[RuntimeAdapter, RouteCandidate]] = []
        for adapter in self.adapters:
            profile = adapter.profile
            if not required.issubset(profile.capabilities):
                continue
            if profile.estimated_accuracy < _decimal(task.min_accuracy, "min_accuracy"):
                continue
            if profile.p95_latency_ms > task.max_latency_ms:
                continue
            if profile.estimated_cost_usd > effective_cost_cap:
                continue
            score = _route_score(profile, task, effective_cost_cap)
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
        return tuple(candidates[: task.max_attempts])

    def _evaluate(
        self,
        *,
        task: RuntimeTask,
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
                frozenset(task.required_capabilities).issubset(adapter.profile.capabilities),
                Decimal("1"),
                "capabilities_satisfied",
            ),
            EvalAssertion(
                "accuracy_threshold",
                adapter.profile.estimated_accuracy >= task.min_accuracy,
                adapter.profile.estimated_accuracy,
                "estimated_accuracy_satisfied",
            ),
            EvalAssertion(
                "latency_budget",
                response.latency_ms <= task.max_latency_ms,
                Decimal("1") if response.latency_ms <= task.max_latency_ms else Decimal("0"),
                "latency_budget_satisfied",
            ),
            EvalAssertion(
                "cost_budget",
                total_cost <= task.max_cost_usd,
                Decimal("1") if total_cost <= task.max_cost_usd else Decimal("0"),
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


def _route_score(profile: AdapterProfile, task: RuntimeTask, effective_cost_cap: Decimal) -> Decimal:
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
    latency_denominator = max(task.max_latency_ms, 1)
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


def _scope_key(task: RuntimeTask) -> str:
    return _sha256(
        {
            "tenant_ref": task.tenant_ref,
            "entity_ref": task.entity_ref,
            "store_ref": task.store_ref,
            "task_type": task.task_type,
            "idempotency_key": task.idempotency_key,
        }
    )


def _task_fingerprint(task: RuntimeTask) -> str:
    return _sha256(
        {
            "contract_id": RUNTIME_CONTRACT_ID,
            "routing_policy_version": ROUTING_POLICY_VERSION,
            "task_type": task.task_type,
            "scope": [task.tenant_ref, task.entity_ref, task.store_ref],
            "prompt": task.prompt,
            "model_input": task.model_input,
            "output_schema": task.output_schema,
            "required_capabilities": sorted(task.required_capabilities),
            "requested_by": task.requested_by,
            "min_accuracy": str(task.min_accuracy),
            "max_latency_ms": task.max_latency_ms,
            "max_cost_usd": str(task.max_cost_usd),
            "expected_profit_value_usd": (
                None if task.expected_profit_value_usd is None else str(task.expected_profit_value_usd)
            ),
            "max_cost_to_profit_ratio": str(task.max_cost_to_profit_ratio),
            "max_attempts": task.max_attempts,
            "max_output_tokens": task.max_output_tokens,
            "timeout_seconds": task.timeout_seconds,
            "allowed_tools": sorted(task.allowed_tools),
            "requested_tools": sorted(task.requested_tools),
            "agent_actor_id": task.agent_actor_id,
            "approval_actor_id": task.approval_actor_id,
            "image_inputs": list(task.image_inputs),
        }
    )


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
