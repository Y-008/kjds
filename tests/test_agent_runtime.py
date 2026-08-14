from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.control_plane.agent_inference import FakeInferenceAdapter
from apps.control_plane.agent_runtime import (
    REDACTED,
    AdapterProfile,
    AgentRunEvidenceRef,
    AgentRunScopeContext,
    AgentRuntimeExhaustedError,
    AgentRuntimePolicyError,
    CallableRuntimeAdapter,
    DeterministicFakeRuntimeAdapter,
    ExistingInferenceRuntimeAdapter,
    GovernedAgentRuntime,
    GovernedRunReceipt,
    InMemoryGenAITraceSink,
    InMemoryRuntimeAuditLedger,
    RuntimeAdapterError,
    RuntimeAdapterResponse,
    RuntimeAuditEvent,
    RuntimeTask,
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string"},
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["recommendation", "confidence"],
}


class FakeTaskRegistry:
    registry_sha256 = "a" * 64

    def __init__(
        self,
        *,
        prompt: str = "Return a governed SKU proposal.",
        output_schema: dict | None = None,
        allowed_tools: tuple[str, ...] = ("evidence.read",),
    ) -> None:
        self.payload = {"authority": {"maximum_provider_attempts": 2}}
        self.contract = {
            "contract_version": "sku-profit-strategy-v1",
            "prompt_version": "prompt-v1",
            "schema_version": "schema-v1",
            "prompt": prompt,
            "output_schema": output_schema or OUTPUT_SCHEMA,
            "required_capabilities": ["json_schema", "strategy"],
            "allowed_input_fields": [
                "sku",
                "downside_cm3",
                "api_key",
                "nested",
            ],
            "allowed_tools": list(allowed_tools),
            "minimum_confidence": "0.80",
            "timeout_seconds": 2,
            "max_cost_usd": "2.00",
            "max_output_tokens": 2_000,
        }

    def require(self, task_type: str) -> dict:
        if task_type != "sku_profit_strategy":
            raise KeyError(task_type)
        return self.contract


def scope(**changes) -> AgentRunScopeContext:
    base = AgentRunScopeContext(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_sha256="b" * 64,
        actor_id="operator-a",
        scope_as_of=datetime(2026, 8, 3, 8, 0, tzinfo=UTC),
        evidence_refs=(
            AgentRunEvidenceRef(
                evidence_id="evidence-current",
                evidence_sha256="c" * 64,
            ),
        ),
    )
    return replace(base, **changes)


def task(**changes) -> RuntimeTask:
    base = RuntimeTask(
        task_type="sku_profit_strategy",
        model_input={"sku": "sku-1", "downside_cm3": "12.50"},
        idempotency_key="strategy-sku-1-v1",
        expected_profit_value_usd=Decimal("1000"),
        max_cost_to_profit_ratio=Decimal("0.10"),
        max_attempts=2,
        max_latency_ms=2_000,
        max_cost_usd=Decimal("2.00"),
    )
    return replace(base, **changes)


def governed(adapters, *, registry=None, **kwargs) -> GovernedAgentRuntime:
    return GovernedAgentRuntime(
        adapters,
        task_registry=registry or FakeTaskRegistry(),
        **kwargs,
    )


def profile(
    name: str,
    *,
    accuracy: str = "0.90",
    latency_ms: int = 100,
    cost_usd: str = "0.02",
    capabilities: frozenset[str] = frozenset({"json_schema", "strategy"}),
) -> AdapterProfile:
    return AdapterProfile(
        name=name,
        provider=f"{name}-provider",
        model=f"{name}-model",
        capabilities=capabilities,
        estimated_accuracy=Decimal(accuracy),
        p95_latency_ms=latency_ms,
        estimated_cost_usd=Decimal(cost_usd),
    )


def successful_response(
    *,
    recommendation: str = "pilot",
    cost_usd: str = "0.02",
    latency_ms: int = 100,
    note: str | None = None,
) -> RuntimeAdapterResponse:
    output: dict[str, object] = {
        "recommendation": recommendation,
        "confidence": 0.92,
    }
    if note is not None:
        output["note"] = note
    return RuntimeAdapterResponse(
        output=output,
        input_tokens=30,
        output_tokens=12,
        cost_usd=Decimal(cost_usd),
        latency_ms=latency_ms,
    )


def test_profit_aware_route_falls_back_to_next_eligible_adapter():
    high_accuracy = DeterministicFakeRuntimeAdapter(
        profile("high-accuracy", accuracy="0.98", latency_ms=800, cost_usd="0.50"),
        [
            RuntimeAdapterError(
                "provider_unavailable",
                "temporary outage",
                cost_usd=Decimal("0.01"),
            )
        ],
    )
    efficient = DeterministicFakeRuntimeAdapter(
        profile("efficient", accuracy="0.85", latency_ms=100, cost_usd="0.05"),
        [successful_response(cost_usd="0.05")],
    )

    result = governed([efficient, high_accuracy]).run(scope(), task())

    assert [candidate.adapter_name for candidate in result.route] == [
        "high-accuracy",
        "efficient",
    ]
    assert [attempt.status for attempt in result.attempts] == ["failed", "succeeded"]
    assert result.attempts[0].reason_code == "provider_unavailable"
    assert result.model == "efficient-model"
    assert result.total_cost_usd == Decimal("0.06")
    assert len(high_accuracy.calls) == len(efficient.calls) == 1


def test_input_output_and_trace_redaction_happen_before_each_seam():
    secret = "sk-live-super-secret"
    trace_sink = InMemoryGenAITraceSink()
    adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"),
        [successful_response(note=f"provider accidentally echoed api_key={secret}")],
    )
    runtime_task = task(
        model_input={
            "sku": "sku-1",
            "api_key": secret,
            "nested": {"note": f"password={secret}"},
        },
        max_attempts=1,
    )
    registry = FakeTaskRegistry(
        prompt=f"Authorization: Bearer {secret} Return JSON"
    )

    result = governed([adapter], registry=registry, trace_sink=trace_sink).run(
        scope(), runtime_task
    )

    request = adapter.calls[0]
    assert secret not in request.prompt
    assert request.model_input["api_key"] == REDACTED
    assert secret not in json.dumps(request.model_input)
    assert secret not in json.dumps(result.to_dict())
    assert REDACTED in result.output["note"]
    assert secret not in json.dumps([span.to_dict() for span in trace_sink.spans])


def test_client_cannot_supply_scope_prompt_schema_capabilities_or_actor():
    with pytest.raises(TypeError):
        RuntimeTask(
            task_type="sku_profit_strategy",
            model_input={},
            idempotency_key="forbidden-authority",
            requested_by="caller-controlled",
        )


@pytest.mark.parametrize(
    "tool_name",
    ["marketplace.write", "permit.issue", "fact.promote", "telegram.send"],
)
def test_privileged_tools_are_denied_before_adapter_invocation(tool_name: str):
    adapter = DeterministicFakeRuntimeAdapter(profile("safe"), [successful_response()])

    with pytest.raises(AgentRuntimePolicyError) as captured:
        governed([adapter]).run(
            scope(),
            task(max_attempts=1, requested_tools=(tool_name,)),
        )

    assert captured.value.code == "tool_denied"
    assert adapter.calls == []


def test_read_tool_can_be_proposed_but_is_never_executed_by_runtime():
    adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"),
        [
            RuntimeAdapterResponse(
                output={
                    "recommendation": "hold",
                    "confidence": 0.90,
                    "action": "hold",
                    "tool_calls": [
                        {"name": "evidence.read", "arguments": {"id": "ev-1"}}
                    ],
                },
                cost_usd=Decimal("0.01"),
                latency_ms=50,
            )
        ],
    )

    result = governed([adapter]).run(
        scope(),
        task(requested_tools=("evidence.read",)),
    )

    assert adapter.calls[0].tools == ("evidence.read",)
    assert result.governance.tool_execution_allowed is False
    assert result.governance.external_write_allowed is False


def test_estimated_absolute_and_profit_ratio_cost_limits_block_invocation():
    adapter = DeterministicFakeRuntimeAdapter(
        profile("expensive", cost_usd="0.06"),
        [successful_response(cost_usd="0.06")],
    )
    runtime = governed([adapter])

    with pytest.raises(AgentRuntimePolicyError) as absolute_error:
        runtime.run(scope(), task(max_attempts=1, max_cost_usd=Decimal("0.05")))
    assert absolute_error.value.code == "no_eligible_adapter"

    with pytest.raises(AgentRuntimePolicyError) as profit_error:
        runtime.run(
            scope(),
            task(
                idempotency_key="profit-capped",
                max_attempts=1,
                max_cost_usd=Decimal("1"),
                expected_profit_value_usd=Decimal("1"),
                max_cost_to_profit_ratio=Decimal("0.05"),
            ),
        )
    assert profit_error.value.code == "no_eligible_adapter"
    assert adapter.calls == []


def test_actual_cost_overrun_is_denied_without_fallback_spend():
    adapter = DeterministicFakeRuntimeAdapter(
        profile("underestimated", cost_usd="0.01"),
        [successful_response(cost_usd="0.20")],
    )

    with pytest.raises(AgentRuntimePolicyError) as captured:
        governed([adapter]).run(
            scope(),
            task(
                max_attempts=1,
                max_cost_usd=Decimal("0.10"),
                expected_profit_value_usd=None,
            ),
        )

    assert captured.value.code == "actual_cost_budget_exceeded"
    assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    ("privileged_output", "expected_code"),
    [
        ({"formal_fact": True}, "formal_fact_promotion_denied"),
        ({"approved": True}, "self_approval_denied"),
        ({"permit_id": "permit-model-created"}, "permit_issue_denied"),
        ({"external_write_allowed": True}, "marketplace_write_denied"),
        (
            {"tool_calls": [{"name": "marketplace.update.price", "arguments": {}}]},
            "tool_denied",
        ),
    ],
)
def test_model_output_cannot_escalate_authority(
    privileged_output: dict[str, object], expected_code: str
):
    output = {"recommendation": "pilot", "confidence": 0.99, **privileged_output}
    adapter = DeterministicFakeRuntimeAdapter(profile("unsafe-output"), [output])
    registry = FakeTaskRegistry(output_schema={"type": "object"})

    with pytest.raises(AgentRuntimeExhaustedError) as captured:
        governed([adapter], registry=registry).run(scope(), task(max_attempts=1))

    assert captured.value.attempts[0].reason_code == expected_code
    assert captured.value.attempts[0].actual_cost_usd == Decimal("0.02")


def test_trace_and_eval_are_linked_and_eval_identity_is_deterministic():
    def fixed_clock() -> datetime:
        return datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

    sink = InMemoryGenAITraceSink()
    adapter = DeterministicFakeRuntimeAdapter(profile("safe"), [successful_response()])
    result = governed([adapter], trace_sink=sink, clock=fixed_clock).run(
        scope(), task(max_attempts=1)
    )

    root = next(span for span in sink.spans if span.parent_span_id is None)
    attempt = next(span for span in sink.spans if span.parent_span_id is not None)
    assert root.trace_id == attempt.trace_id == result.eval_record.trace_id
    assert root.span_id == attempt.parent_span_id == result.eval_record.span_id
    assert root.attributes["kjds.agent.eval_id"] == result.eval_record.eval_id
    assert root.attributes["kjds.agent.formal_fact"] is False
    assert result.eval_record.run_id == result.run_id
    assert result.eval_record.passed is True

    second_adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"), [successful_response()]
    )
    second = governed([second_adapter], clock=fixed_clock).run(
        scope(), task(max_attempts=1)
    )
    assert second.run_id == result.run_id
    assert second.eval_record == result.eval_record


def test_idempotent_run_returns_cached_result_and_input_drift_conflicts():
    adapter = DeterministicFakeRuntimeAdapter(profile("safe"), [successful_response()])
    sink = InMemoryGenAITraceSink()
    runtime = governed([adapter], trace_sink=sink)
    runtime_task = task(max_attempts=1)

    first = runtime.run(scope(), runtime_task)
    replay = runtime.run(scope(), runtime_task)

    assert replay is first
    assert replay.run_id == first.run_id
    assert len(adapter.calls) == 1
    assert len(sink.spans) == 2

    with pytest.raises(AgentRuntimePolicyError) as captured:
        runtime.run(scope(), replace(runtime_task, model_input={"sku": "sku-2"}))
    assert captured.value.code == "idempotency_conflict"


def test_durable_replay_returns_receipt_without_provider_invocation():
    ledger = InMemoryRuntimeAuditLedger()
    first_adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"), [successful_response()]
    )
    first = governed([first_adapter], audit_ledger=ledger).run(
        scope(), task(max_attempts=1)
    )
    second_adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"), [successful_response(recommendation="must-not-run")]
    )

    replay = governed([second_adapter], audit_ledger=ledger).run(
        scope(), task(max_attempts=1)
    )

    assert isinstance(replay, GovernedRunReceipt)
    assert replay.run_id == first.run_id
    assert replay.status == "succeeded"
    assert replay.payload_status == "not_retained"
    assert replay.network_invoked is False
    assert second_adapter.calls == []


def test_concurrent_same_idempotency_key_invokes_only_one_provider():
    barrier = threading.Barrier(2)

    class BarrierAuditLedger(InMemoryRuntimeAuditLedger):
        def prepare(self, envelope):
            prepared = super().prepare(envelope)
            barrier.wait(timeout=2)
            return prepared

    ledger = BarrierAuditLedger()
    shared_adapter = DeterministicFakeRuntimeAdapter(
        profile("single-provider"),
        [successful_response()],
    )
    runtimes = (
        governed([shared_adapter], audit_ledger=ledger),
        governed([shared_adapter], audit_ledger=ledger),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(item.run, scope(), task(max_attempts=1))
            for item in runtimes
        ]
        outcomes = []
        errors = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except AgentRuntimePolicyError as exc:
                errors.append(exc)

    assert len(outcomes) == 1
    assert len(errors) == 1
    assert errors[0].code in {
        "event_transition_invalid",
        "terminal_event_conflict",
    }
    assert len(shared_adapter.calls) == 1


def test_unknown_provider_outcome_is_not_retried_after_restart():
    class FailingOutcomeLedger(InMemoryRuntimeAuditLedger):
        def append(self, *, run_id: str, event: RuntimeAuditEvent) -> None:
            if event.event_type == "attempt_completed":
                raise RuntimeError("simulated durable write failure")
            super().append(run_id=run_id, event=event)

    ledger = FailingOutcomeLedger()
    first_adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"), [successful_response()]
    )
    with pytest.raises(AgentRuntimePolicyError) as captured:
        governed([first_adapter], audit_ledger=ledger).run(
            scope(), task(max_attempts=1)
        )
    assert captured.value.code == "unknown_outcome"
    assert len(first_adapter.calls) == 1

    second_adapter = DeterministicFakeRuntimeAdapter(
        profile("safe"), [successful_response()]
    )
    replay = governed([second_adapter], audit_ledger=ledger).run(
        scope(), task(max_attempts=1)
    )
    assert isinstance(replay, GovernedRunReceipt)
    assert replay.status == "unknown_outcome"
    assert replay.network_invoked is False
    assert second_adapter.calls == []


def test_independent_idempotency_scopes_can_run_in_parallel():
    arrived = threading.Barrier(2)

    def invoke(_request):
        arrived.wait(timeout=2)
        return successful_response()

    adapter = CallableRuntimeAdapter(profile("parallel"), invoke)
    runtime = governed([adapter])
    tasks = (
        task(max_attempts=1, idempotency_key="parallel-a"),
        task(max_attempts=1, idempotency_key="parallel-b"),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda item: runtime.run(scope(), item), tasks))

    assert results[0].run_id != results[1].run_id


def test_existing_openai_compatible_port_seam_requires_no_new_dependency():
    existing = FakeInferenceAdapter(
        responder=lambda request: {
            "recommendation": "reprice",
            "confidence": 0.95,
        }
    )
    adapter = ExistingInferenceRuntimeAdapter(existing, profile=profile("existing-port"))

    result = governed([adapter]).run(scope(), task(max_attempts=1))

    assert result.output["recommendation"] == "reprice"
    assert result.provider == "existing-port-provider"
    assert existing.calls[0]["idempotency_key"].endswith(":1")
    assert result.governance.proposal_only is True
    assert result.governance.formal_fact is False
    assert result.governance.permit_issue_allowed is False
    assert result.governance.marketplace_write_allowed is False
