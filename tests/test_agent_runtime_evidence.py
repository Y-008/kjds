from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.agent_runtime import (
    AdapterProfile,
    AgentRunEvidenceRef,
    AgentRunScopeContext,
    AgentRuntimePolicyError,
    DeterministicFakeRuntimeAdapter,
    GovernedAgentRuntime,
    GovernedRunReceipt,
    RuntimeAdapterResponse,
    RuntimeAuditEvent,
    RuntimeTask,
    _audit_event_payload,
)
from apps.control_plane.agent_runtime_evidence import (
    AGENT_RUN_EVIDENCE_SOURCE,
    AgentRuntimeRunEnvelopeRow,
    AgentRuntimeRunEventRow,
    SqlAgentRuntimeEvidenceLedger,
)
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.sql_repository import Base


class FakeTaskRegistry:
    registry_sha256 = "1" * 64
    payload = {"authority": {"maximum_provider_attempts": 2}}

    def require(self, task_type: str) -> dict:
        if task_type != "listing_quality_qa":
            raise KeyError(task_type)
        return {
            "contract_version": "listing-quality-qa-v1",
            "prompt_version": "prompt-v1",
            "schema_version": "schema-v1",
            "prompt": "Return a proposal only.",
            "output_schema": {
                "type": "object",
                "properties": {
                    "recommendation": {"type": "string"},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                },
                "required": ["recommendation", "confidence"],
            },
            "required_capabilities": ["json_schema"],
            "allowed_input_fields": ["sku", "api_key"],
            "allowed_tools": [],
            "minimum_confidence": "0.80",
            "timeout_seconds": 3,
            "max_cost_usd": "1.00",
            "max_output_tokens": 500,
        }


def make_services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            EvidenceBlobRow.__table__,
            EvidenceRecordRow.__table__,
            AgentRuntimeRunEnvelopeRow.__table__,
            AgentRuntimeRunEventRow.__table__,
        ],
    )
    evidence = EvidenceService(engine)
    ledger = SqlAgentRuntimeEvidenceLedger(engine=engine, evidence=evidence)
    return engine, evidence, ledger


def scoped_input(evidence: EvidenceService):
    record = evidence.capture(
        content=b'{"approved_listing_rules":"hash-only-input"}',
        filename="listing-rules.json",
        content_type="application/json",
        source="test-governed-input",
        source_ref="rules://listing/v1",
        grade=EvidenceGrade.A,
        effective_at="2026-08-03T10:00:00Z",
        effective_until=None,
        created_by="independent-reviewer",
    )
    return record


def scope(evidence: EvidenceService, **changes) -> AgentRunScopeContext:
    record = scoped_input(evidence)
    base = AgentRunScopeContext(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_sha256="2" * 64,
        actor_id="operator-a",
        scope_as_of=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        evidence_refs=(
            AgentRunEvidenceRef(
                evidence_id=record.id,
                evidence_sha256=record.sha256,
            ),
        ),
    )
    return replace(base, **changes)


def query_scope(context: AgentRunScopeContext, **changes) -> AgentRunScopeContext:
    return replace(
        context,
        scope_as_of=context.scope_as_of + timedelta(minutes=5),
        **changes,
    )


def task(**changes) -> RuntimeTask:
    base = RuntimeTask(
        task_type="listing_quality_qa",
        model_input={"sku": "sku-1"},
        idempotency_key="listing-quality-sku-1-v1",
        max_attempts=1,
        max_cost_usd=Decimal("0.10"),
        max_latency_ms=2_000,
    )
    return replace(base, **changes)


def adapter(*, note: str | None = None, provider: str = "provider-sensitive-name"):
    output = {"recommendation": "hold", "confidence": 0.95}
    if note is not None:
        output["note"] = note
    profile = AdapterProfile(
        name="adapter-sensitive-name",
        provider=provider,
        model="model-sensitive-name",
        capabilities=frozenset({"json_schema"}),
        estimated_accuracy=Decimal("0.90"),
        p95_latency_ms=100,
        estimated_cost_usd=Decimal("0.01"),
    )
    return DeterministicFakeRuntimeAdapter(
        profile,
        [
            RuntimeAdapterResponse(
                output=output,
                input_tokens=20,
                output_tokens=8,
                cost_usd=Decimal("0.01"),
                latency_ms=80,
            )
        ],
    )


def runtime(runtime_adapter, ledger) -> GovernedAgentRuntime:
    return GovernedAgentRuntime(
        [runtime_adapter],
        task_registry=FakeTaskRegistry(),
        audit_ledger=ledger,
        clock=lambda: datetime(2026, 8, 3, 12, 0, 1, tzinfo=UTC),
    )


def test_sql_ledger_persists_evidence_and_replays_without_plaintext_or_network():
    engine, evidence, ledger = make_services()
    context = scope(evidence)
    secret = "sk-live-never-persist"
    first_adapter = adapter(note=f"api_key={secret}")

    result = runtime(first_adapter, ledger).run(
        context,
        task(model_input={"sku": "sku-1", "api_key": secret}),
    )
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "agent_runtime"
            / "listing_quality_qa_v1_eval_v1.json"
        ).read_text(encoding="utf-8")
    )

    with Session(engine) as session:
        envelope = session.scalar(select(AgentRuntimeRunEnvelopeRow))
        events = list(
            session.scalars(
                select(AgentRuntimeRunEventRow).order_by(
                    AgentRuntimeRunEventRow.event_index
                )
            )
        )
        evidence_rows = list(
            session.scalars(
                select(EvidenceRecordRow).where(
                    EvidenceRecordRow.source == AGENT_RUN_EVIDENCE_SOURCE
                )
            )
        )
        blobs = [session.get(EvidenceBlobRow, item.blob_sha256) for item in evidence_rows]

    assert envelope is not None
    assert result.task_type == fixture["task_type"]
    assert result.eval_record.passed is fixture["expected_passed"]
    assert [item.name for item in result.eval_record.assertions] == fixture[
        "expected_assertion_names"
    ]
    assert result.governance.proposal_only is fixture["expected_governance"][
        "proposal_only"
    ]
    assert envelope.idempotency_sha256 != task().idempotency_key
    assert [item.event_type for item in events] == [
        "run_started",
        "route_selected",
        "attempt_started",
        "attempt_completed",
        "eval_completed",
        "run_succeeded",
    ]
    assert len(evidence_rows) == len(events) == 6
    persisted = json.dumps(
        {
            "envelope": envelope.__dict__,
            "events": [item.__dict__ for item in events],
            "evidence": [item.__dict__ for item in evidence_rows],
            "blobs": [item.content_bytes.decode() for item in blobs if item],
        },
        default=str,
        sort_keys=True,
    )
    for forbidden in (
        secret,
        "provider-sensitive-name",
        "model-sensitive-name",
        "adapter-sensitive-name",
        "api_key=",
        '"recommendation":"hold"',
    ):
        assert forbidden not in persisted

    visible = query_scope(context)
    listing = ledger.list_runs(
        context=visible,
        status="succeeded",
        task_type="listing_quality_qa",
        limit=50,
        offset=0,
    )
    detail = ledger.get_run(context=visible, run_id=result.run_id)
    second_adapter = adapter(provider="must-not-run")
    replay = runtime(second_adapter, ledger).run(
        context,
        task(model_input={"sku": "sku-1", "api_key": secret}),
    )

    assert listing["status"] == "ready"
    assert listing["runs"][0]["run_id"] == result.run_id
    assert detail["payload_status"] == "not_retained"
    assert all("provider" not in event for event in detail["events"])
    assert any(event["provider_sha256"] for event in detail["events"])
    assert isinstance(replay, GovernedRunReceipt)
    assert replay.status == "succeeded"
    assert replay.network_invoked is False
    assert second_adapter.calls == []


def test_exact_scope_queries_hide_tenant_entity_store_and_authority_drift():
    _, evidence, ledger = make_services()
    context = scope(evidence)
    result = runtime(adapter(), ledger).run(context, task())

    for hidden in (
        query_scope(context, tenant_ref="tenant-b"),
        query_scope(context, entity_ref="entity-b"),
        query_scope(context, store_ref="store-b"),
        query_scope(context, authority_sha256="3" * 64),
    ):
        assert ledger.list_runs(
            context=hidden,
            status=None,
            task_type=None,
            limit=50,
            offset=0,
        )["status"] == "no_data"
        with pytest.raises(KeyError, match="not found"):
            ledger.get_run(context=hidden, run_id=result.run_id)
        with pytest.raises(KeyError, match="not found"):
            ledger.replay(context=hidden, run_id=result.run_id)


def test_durable_idempotency_drift_and_invalid_evidence_stop_before_provider():
    engine, evidence, ledger = make_services()
    context = scope(evidence)
    first_adapter = adapter()
    first_runtime = runtime(first_adapter, ledger)
    first_runtime.run(context, task())

    drift_adapter = adapter()
    with pytest.raises(AgentRuntimePolicyError) as conflict:
        runtime(drift_adapter, ledger).run(
            context,
            task(model_input={"sku": "sku-drift"}),
        )
    assert conflict.value.code == "idempotency_conflict"
    assert drift_adapter.calls == []

    record = evidence.get(context.evidence_refs[0].evidence_id)
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceBlobRow)
            .where(EvidenceBlobRow.sha256 == record.sha256)
            .values(content_bytes=b"tampered input")
        )
    with pytest.raises(AgentRuntimePolicyError) as cached_invalid:
        first_runtime.run(context, task())
    assert cached_invalid.value.code == "scoped_evidence_invalid"
    assert len(first_adapter.calls) == 1

    invalid_adapter = adapter()
    with pytest.raises(AgentRuntimePolicyError) as invalid:
        runtime(invalid_adapter, ledger).run(
            context,
            task(idempotency_key="invalid-evidence-v1"),
        )
    assert invalid.value.code == "scoped_evidence_invalid"
    assert invalid_adapter.calls == []


def test_event_hash_tamper_and_terminal_followup_are_rejected():
    engine, evidence, ledger = make_services()
    context = scope(evidence)
    result = runtime(adapter(), ledger).run(context, task())

    with pytest.raises(AgentRuntimePolicyError) as terminal:
        ledger.append(
            run_id=result.run_id,
            event=RuntimeAuditEvent(event_type="attempt_started"),
        )
    assert terminal.value.code == "terminal_event_conflict"

    with Session(engine) as session, session.begin():
        session.execute(
            update(AgentRuntimeRunEventRow)
            .where(AgentRuntimeRunEventRow.run_id == result.run_id)
            .where(AgentRuntimeRunEventRow.event_index == 3)
            .values(latency_ms=999)
        )
    with pytest.raises(AgentRuntimePolicyError) as tamper:
        ledger.get_run(context=query_scope(context), run_id=result.run_id)
    assert tamper.value.code == "audit_chain_invalid"


@pytest.mark.parametrize(
    "event",
    [
        RuntimeAuditEvent(event_type="run_started", cost_usd=Decimal("NaN")),
        RuntimeAuditEvent(event_type="run_started", cost_usd=Decimal("-0.01")),
        RuntimeAuditEvent(event_type="run_started", latency_ms=-1),
        RuntimeAuditEvent(event_type="run_started", input_tokens=-1),
    ],
)
def test_invalid_audit_metrics_are_rejected(event: RuntimeAuditEvent):
    with pytest.raises(ValueError):
        _audit_event_payload(
            event=event,
            event_index=1,
            previous_event_sha256="0" * 64,
            occurred_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        )
