from __future__ import annotations

import hashlib
import importlib
import json
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.agent_runtime import (
    AgentRunEvidenceRef,
    AgentRunScopeContext,
    RuntimeAuditEnvelope,
    RuntimeAuditEvent,
)
from apps.control_plane.agent_runtime_evidence import (
    AgentRuntimeRunEnvelopeRow,
    AgentRuntimeRunEventRow,
    SqlAgentRuntimeEvidenceLedger,
)
from apps.control_plane.closed_loop_evolution import (
    _AGENT_RUN_EVENT_CONTRACT,
    Bas177ClosedLoopObservationPort,
    ClosedLoopContractError,
    ClosedLoopEvolutionRegistry,
    ClosedLoopOutcomeBundleRow,
    ClosedLoopOutcomeEventRow,
    ClosedLoopOutcomeEvidenceLinkRow,
    GovernedClosedLoopEvolutionWorkspace,
    _agent_run_canonical,
    _agent_run_event_hash,
    _agent_run_event_id,
    _agent_run_event_row_payload,
    _handoff_seal,
    _hash_json,
    _validate_agent_run_event_contract,
)
from apps.control_plane.evidence import (
    CLOSED_LOOP_AUTHORITY_CONTRACTS,
    CLOSED_LOOP_AUTHORITY_SCHEMA_MANIFESTS,
    CLOSED_LOOP_RESERVED_SOURCES,
    ClosedLoopEvidenceAuthorityAdapter,
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    _closed_loop_claims,
    _closed_loop_claims_sha256,
)
from apps.control_plane.evidence_integrity import EvidenceIntegrityMonitorService
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base
from apps.control_plane.strategic_capital_dashboard import (
    ClosedLoopEvolutionReadPort,
    DashboardNoData,
    DashboardReadContext,
    ScopedDashboardCitationAuthority,
    StrategicCapitalDashboardRegistry,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures/closed_loop_evolution/bas204_closed_loop_v1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(FIXTURE["trusted_now"])
DATA_AS_OF = datetime.fromisoformat(FIXTURE["data_as_of"])
SEALING_KEY = b"bas204-unit-test-sealing-key-32-bytes-minimum"


class ScopeGrants:
    def __init__(self) -> None:
        self.authority_sha256 = FIXTURE["scope"]["scope_grant_authority_sha256"]
        self.calls = 0
        self.rotate_on_call: int | None = None

    def current(self, *, principal, store_ref, as_of):
        del as_of
        self.calls += 1
        if self.rotate_on_call == self.calls:
            self.authority_sha256 = "c" * 64
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": FIXTURE["scope"]["entity_ref"],
            "store_ref": store_ref,
            "authority_sha256": self.authority_sha256,
        }


class AgentRunReceipts:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.status = "succeeded"
        self.contract_id = "kjds-governed-agent-runtime-v1"
        self.proposal_only = True
        self.formal_fact = False
        self.external_write_allowed = False
        self.event_sha256: str | None = None

    def get_run(self, *, context, run_id):
        assert context.authority_sha256 == FIXTURE["scope"]["scope_grant_authority_sha256"]
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(AgentRuntimeRunEventRow)
                    .where(AgentRuntimeRunEventRow.run_id == run_id)
                    .order_by(AgentRuntimeRunEventRow.event_index)
                )
            )
        events = []
        for index, row in enumerate(rows):
            payload = SqlAgentRuntimeEvidenceLedger._event_payload(row)
            if index == len(rows) - 1 and self.event_sha256 is not None:
                payload["event_sha256"] = self.event_sha256
            payload["evidence"] = {
                "evidence_id": row.evidence_id,
                "evidence_sha256": row.evidence_sha256,
            }
            events.append(payload)
        return {
            "contract_id": "kjds-governed-agent-run-audit-v1",
            "run_id": run_id,
            "status": self.status,
            "proposal_only": self.proposal_only,
            "formal_fact": self.formal_fact,
            "external_write_allowed": self.external_write_allowed,
            "events": events,
        }

    def replay(self, *, context, run_id):
        del context
        with Session(self.engine) as session:
            event_count = len(
                list(session.scalars(select(AgentRuntimeRunEventRow).where(AgentRuntimeRunEventRow.run_id == run_id)))
            )
        return SimpleNamespace(
            contract_id=self.contract_id,
            run_id=run_id,
            status=self.status,
            event_count=event_count,
            proposal_only=self.proposal_only,
            formal_fact=self.formal_fact,
            external_write_allowed=self.external_write_allowed,
        )


class AttestationAuthority:
    def __init__(self, purpose: str, claims: dict[str, object]) -> None:
        self.purpose = purpose
        self.contract = CLOSED_LOOP_AUTHORITY_CONTRACTS[purpose]
        self.authority_id = self.contract["issuer_id"]
        self.claims = deepcopy(claims)
        self.issuer_actor_id_override: str | None = None

    def project(self, *, purpose, attestation_ref, exact_scope, data_as_of, checked_at):
        if purpose == "review_event":
            spec = {
                "issuer_actor_id": "review-authority-actor",
                "effective_at": checked_at.isoformat(),
                "recorded_at": checked_at.isoformat(),
                "review_due_at": (checked_at + timedelta(days=1)).isoformat(),
                "effective_until": (checked_at + timedelta(days=2)).isoformat(),
            }
        else:
            spec = deepcopy(FIXTURE["attestations"][purpose])
        if self.issuer_actor_id_override is not None:
            spec["issuer_actor_id"] = self.issuer_actor_id_override
        claims = _closed_loop_claims(purpose, deepcopy(self.claims))
        envelope = {
            "contract_id": self.contract["contract_id"],
            "purpose": purpose,
            "attestation_ref": attestation_ref,
            "authority_receipt_id": f"receipt-{purpose}-1",
            "issuer_id": self.contract["issuer_id"],
            "issuer_contract_id": self.contract["issuer_contract_id"],
            "issuer_contract_version": self.contract["issuer_contract_version"],
            "issuer_contract_sha256": self.contract["issuer_contract_sha256"],
            "schema_sha256": self.contract["schema_sha256"],
            "issuer_actor_id": spec["issuer_actor_id"],
            "exact_scope": exact_scope,
            "data_as_of": data_as_of.isoformat(),
            "effective_at": datetime.fromisoformat(spec["effective_at"]).isoformat(),
            "effective_until": datetime.fromisoformat(spec["effective_until"]).isoformat(),
            "recorded_at": datetime.fromisoformat(spec["recorded_at"]).isoformat(),
            "review_due_at": datetime.fromisoformat(spec["review_due_at"]).isoformat(),
            "claims": claims,
            "claims_sha256": _closed_loop_claims_sha256(claims),
        }
        attestation_sha256 = hashlib.sha256(
            json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        return {
            "status": "ready",
            **envelope,
            "attestation_sha256": attestation_sha256,
            "attestation_signature_sha256": hashlib.sha256(f"signature:{attestation_sha256}".encode()).hexdigest(),
        }

    def verify_receipt(self, *, attestation_sha256, attestation_signature_sha256, expected_envelope):
        expected_signature = hashlib.sha256(f"signature:{attestation_sha256}".encode()).hexdigest()
        if (
            attestation_signature_sha256 != expected_signature
            or hashlib.sha256(
                json.dumps(
                    expected_envelope,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            != attestation_sha256
        ):
            return {"status": "invalid"}
        return {
            "status": "verified",
            "authority_id": self.authority_id,
            "attestation_sha256": attestation_sha256,
        }


def principal(actor_id: str = "bundle-recorder") -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset({"operator", "reviewer"}),
        tenant_ref=FIXTURE["scope"]["tenant_ref"],
        store_refs=frozenset({FIXTURE["scope"]["store_ref"]}),
    )


def make_workspace(engine=None):
    engine = engine or create_engine(
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
            ClosedLoopOutcomeBundleRow.__table__,
            ClosedLoopOutcomeEvidenceLinkRow.__table__,
            ClosedLoopOutcomeEventRow.__table__,
        ],
    )
    evidence = EvidenceService(engine)
    scope_grants = ScopeGrants()
    service = GovernedClosedLoopEvolutionWorkspace(
        engine=engine,
        evidence=evidence,
        scope_grants=scope_grants,
        clock=lambda: NOW,
        handoff_sealing_key=SEALING_KEY,
        agent_run_receipts=AgentRunReceipts(engine),
    )
    authorities = {
        purpose: AttestationAuthority(purpose, spec["claims"]) for purpose, spec in FIXTURE["attestations"].items()
    }
    adapter = ClosedLoopEvidenceAuthorityAdapter(
        evidence,
        scope_grants=scope_grants,
        attestation_authorities={
            **authorities,
            "review_event": AttestationAuthority(
                "review_event",
                {
                    "bundle_id": "placeholder-bundle",
                    "event_type": "review_requested",
                    "reason_code": "review_due",
                    "replacement_bundle_id": None,
                    "requested_by_actor_id": "bundle-recorder",
                },
            ),
        },
        clock=lambda: NOW,
    )
    return engine, evidence, scope_grants, service, adapter


def seed_agent_run(engine, evidence: EvidenceService) -> None:
    del engine
    seed_governed_agent_run(evidence)


def seed_governed_agent_run(evidence: EvidenceService) -> SqlAgentRuntimeEvidenceLedger:
    ledger = SqlAgentRuntimeEvidenceLedger(engine=evidence.engine, evidence=evidence)
    scope = FIXTURE["scope"]
    scoped_input = evidence.capture(
        content=b'{"fixture":"closed-loop-agent-input"}',
        filename="closed-loop-agent-input.json",
        content_type="application/json",
        source="test-governed-input",
        source_ref="fixture://closed-loop-agent-input",
        grade=EvidenceGrade.A,
        effective_at="2026-08-05T08:00:00+00:00",
        effective_until="2026-08-06T00:00:00+00:00",
        created_by="agent-input-authority",
    )
    context = AgentRunScopeContext(
        tenant_ref=scope["tenant_ref"],
        entity_ref=scope["entity_ref"],
        store_ref=scope["store_ref"],
        authority_sha256=scope["scope_grant_authority_sha256"],
        actor_id="agent-actor",
        scope_as_of=DATA_AS_OF,
        evidence_refs=(
            AgentRunEvidenceRef(
                evidence_id=scoped_input.id,
                evidence_sha256=scoped_input.sha256,
            ),
        ),
    )
    envelope = RuntimeAuditEnvelope(
        run_id=FIXTURE["agent_run_ref"],
        trace_id="1" * 32,
        root_span_id="2" * 16,
        scope=context,
        task_type="closed-loop-fixture",
        registry_sha256="3" * 64,
        contract_version="1.0.0",
        prompt_version="p1",
        schema_version="s1",
        routing_policy_version="r1",
        prompt_sha256="4" * 64,
        output_schema_sha256="5" * 64,
        tool_contract_sha256="6" * 64,
        idempotency_key="agent-run-fixture",
        request_sha256="8" * 64,
        input_sha256="9" * 64,
        input_field_names=(),
        input_bytes=2,
        evidence_snapshot_sha256="a" * 64,
        required_capabilities=(),
        allowed_tools=(),
        max_cost_usd="1.0",
        max_latency_ms=1000,
        max_attempts=1,
        started_at=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    assert ledger.prepare(envelope).disposition == "new"
    adapter = {
        "adapter_name": "fixture-adapter",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "adapter_config_sha256": "d" * 64,
    }
    events = (
        RuntimeAuditEvent(
            event_type="route_selected",
            safe_payload={
                "adapter_count": 1,
                "adapter_config_sha256": ["d" * 64],
            },
        ),
        RuntimeAuditEvent(
            event_type="attempt_started",
            **adapter,
            safe_payload={"attempt": 1},
        ),
        RuntimeAuditEvent(
            event_type="attempt_completed",
            **adapter,
            output_sha256="e" * 64,
            input_tokens=10,
            output_tokens=10,
            cost_usd="0.01",
            latency_ms=100,
            safe_payload={"attempt": 1},
        ),
        RuntimeAuditEvent(
            event_type="eval_completed",
            **adapter,
            output_sha256="e" * 64,
            eval_sha256="f" * 64,
            safe_payload={"passed": True, "assertion_count": 6},
        ),
        RuntimeAuditEvent(
            event_type="run_succeeded",
            output_sha256="e" * 64,
            eval_sha256="f" * 64,
            input_tokens=10,
            output_tokens=10,
            cost_usd="0.01",
            latency_ms=100,
            safe_payload={"attempt_count": 1},
        ),
    )
    for second, event in enumerate(events, start=1):
        ledger.append(
            run_id=envelope.run_id,
            event=replace(
                event,
                occurred_at=datetime(2026, 8, 5, 9, 0, second, tzinfo=UTC),
            ),
        )
    with Session(evidence.engine) as session, session.begin():
        rows = list(
            session.scalars(
                select(AgentRuntimeRunEventRow)
                .where(AgentRuntimeRunEventRow.run_id == envelope.run_id)
                .order_by(AgentRuntimeRunEventRow.event_index)
            )
        )
        for row in rows:
            row.recorded_at = row.occurred_at
            evidence_row = session.get(EvidenceRecordRow, row.evidence_id)
            assert evidence_row is not None
            evidence_row.recorded_at = row.occurred_at
    return ledger


def expire_agent_run_evidence(engine, *, effective_until: datetime) -> None:
    with Session(engine) as session, session.begin():
        evidence_ids = list(
            session.scalars(
                select(AgentRuntimeRunEventRow.evidence_id).where(
                    AgentRuntimeRunEventRow.run_id == FIXTURE["agent_run_ref"]
                )
            )
        )
        rows = list(session.scalars(select(EvidenceRecordRow).where(EvidenceRecordRow.id.in_(evidence_ids))))
        assert len(rows) == len(evidence_ids)
        for row in rows:
            row.effective_until = effective_until


_EVENT_IDENTITY = {
    "adapter_sha256": "1" * 64,
    "provider_sha256": "2" * 64,
    "model_sha256": "3" * 64,
    "adapter_config_sha256": "4" * 64,
}


def _contract_event(
    prior: list[dict[str, object]],
    event_type: str,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_index": len(prior) + 1,
        "event_type": event_type,
        "reason_code": None,
        "adapter_sha256": None,
        "provider_sha256": None,
        "model_sha256": None,
        "adapter_config_sha256": None,
        "output_sha256": None,
        "eval_sha256": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": "0",
        "latency_ms": 0,
        "safe_payload": {},
        "previous_event_sha256": (prior[-1]["event_sha256"] if prior else "0" * 64),
        "occurred_at": datetime(2026, 8, 5, 9, 0, len(prior), tzinfo=UTC).isoformat(),
    }
    payload.update(overrides)
    payload["event_sha256"] = _agent_run_event_hash(payload)
    return payload


def _success_contract_events() -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    events.append(_contract_event(events, "run_started"))
    events.append(
        _contract_event(
            events,
            "route_selected",
            safe_payload={
                "adapter_count": 1,
                "adapter_config_sha256": ["4" * 64],
            },
        )
    )
    events.append(
        _contract_event(
            events,
            "attempt_started",
            **_EVENT_IDENTITY,
            safe_payload={"attempt": 1},
        )
    )
    events.append(
        _contract_event(
            events,
            "attempt_completed",
            **_EVENT_IDENTITY,
            output_sha256="5" * 64,
            input_tokens=3,
            output_tokens=4,
            cost_usd="0.5",
            latency_ms=6,
            safe_payload={"attempt": 1},
        )
    )
    events.append(
        _contract_event(
            events,
            "eval_completed",
            **_EVENT_IDENTITY,
            output_sha256="5" * 64,
            eval_sha256="6" * 64,
            safe_payload={"passed": True, "assertion_count": 6},
        )
    )
    events.append(
        _contract_event(
            events,
            "run_succeeded",
            output_sha256="5" * 64,
            eval_sha256="6" * 64,
            input_tokens=3,
            output_tokens=4,
            cost_usd="0.5",
            latency_ms=6,
            safe_payload={"attempt_count": 1},
        )
    )
    return events


def _validate_contract_sequence(events: list[dict[str, object]]) -> None:
    prior: list[dict[str, object]] = []
    for event in events:
        prior.append(
            _validate_agent_run_event_contract(
                event,
                previous=prior[-1] if prior else None,
                prior_events=prior,
                max_attempts=1,
            )
        )


def test_agent_run_event_contract_accepts_all_frozen_event_types():
    success = _success_contract_events()
    denied = [_contract_event([], "run_started")]
    denied.append(_contract_event(denied, "run_denied", reason_code="no_eligible_adapter"))
    attempt_denied = _success_contract_events()[:3]
    attempt_denied.append(
        _contract_event(
            attempt_denied,
            "attempt_denied",
            **_EVENT_IDENTITY,
            reason_code="actual_cost_budget_exceeded",
            safe_payload={"attempt": 1},
        )
    )
    attempt_denied.append(
        _contract_event(
            attempt_denied,
            "run_denied",
            reason_code="actual_cost_budget_exceeded",
        )
    )
    failed = _success_contract_events()[:3]
    failed.append(
        _contract_event(
            failed,
            "attempt_failed",
            **_EVENT_IDENTITY,
            reason_code="provider_timeout",
            input_tokens=1,
            cost_usd="0.25",
            latency_ms=4,
            safe_payload={"attempt": 1},
        )
    )
    failed.append(
        _contract_event(
            failed,
            "run_failed",
            reason_code="all_adapters_failed",
            cost_usd="0.25",
        )
    )
    unknown = _success_contract_events()[:2]
    unknown.append(
        _contract_event(
            unknown,
            "unknown_outcome",
            reason_code="provider_outcome_not_terminal",
        )
    )

    sequences = (success, denied, attempt_denied, failed, unknown)
    for sequence in sequences:
        _validate_contract_sequence(sequence)
    assert {
        str(event["event_type"]) for sequence in sequences for event in sequence
    } == _AGENT_RUN_EVENT_CONTRACT.event_types


def test_agent_run_event_contract_requires_run_started_as_the_first_event():
    events = _success_contract_events()
    resigned: list[dict[str, object]] = []
    for event in events[1:]:
        candidate = deepcopy(event)
        candidate["event_index"] = len(resigned) + 1
        candidate["previous_event_sha256"] = (
            resigned[-1]["event_sha256"] if resigned else "0" * 64
        )
        candidate["event_sha256"] = _agent_run_event_hash(
            {key: value for key, value in candidate.items() if key != "event_sha256"}
        )
        resigned.append(candidate)

    with pytest.raises(ClosedLoopContractError):
        _validate_contract_sequence(resigned)


def test_agent_run_event_contract_matches_0096_migration_constants():
    migration = importlib.import_module(
        "migrations.versions.20260805_0096_governed_closed_loop_evolution"
    )

    assert frozenset(migration.AGENT_RUN_EVENT_KEYS) == _AGENT_RUN_EVENT_CONTRACT.event_keys
    assert frozenset(migration.AGENT_RUN_EVENT_TYPES) == _AGENT_RUN_EVENT_CONTRACT.event_types
    assert (
        frozenset(migration.AGENT_RUN_TERMINAL_EVENT_TYPES)
        == _AGENT_RUN_EVENT_CONTRACT.terminal_event_types
    )
    assert (
        frozenset(migration.AGENT_RUN_UNKNOWN_REASON_CODES)
        == _AGENT_RUN_EVENT_CONTRACT.unknown_reason_codes
    )
    assert {
        source: frozenset(targets) for source, targets in migration.AGENT_RUN_TRANSITIONS.items()
    } == dict(_AGENT_RUN_EVENT_CONTRACT.transitions)
    assert {
        event_type: frozenset(keys)
        for event_type, keys in migration.AGENT_RUN_SAFE_PAYLOAD_KEYS.items()
    } == dict(_AGENT_RUN_EVENT_CONTRACT.safe_payload_keys)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_key",
        "extra_key",
        "wrong_type",
        "null_matrix",
        "safe_payload_extra",
        "attempt_count",
        "aggregate_tokens",
        "hash",
    ),
)
def test_agent_run_event_contract_rejects_shape_and_cross_field_drift(mutation):
    events = _success_contract_events()
    target = deepcopy(events[-1])
    if mutation == "missing_key":
        target.pop("safe_payload")
    elif mutation == "extra_key":
        target["raw_output"] = "forbidden"
    elif mutation == "wrong_type":
        target["input_tokens"] = True
    elif mutation == "null_matrix":
        target["adapter_sha256"] = "1" * 64
    elif mutation == "safe_payload_extra":
        target["safe_payload"] = {"attempt_count": 1, "prompt": "secret"}
    elif mutation == "attempt_count":
        target["safe_payload"] = {"attempt_count": 2}
    elif mutation == "aggregate_tokens":
        target["input_tokens"] = 4
    else:
        target["event_sha256"] = "f" * 64
    if mutation != "hash" and set(target) == _AGENT_RUN_EVENT_CONTRACT.event_keys:
        target["event_sha256"] = _agent_run_event_hash(
            {key: value for key, value in target.items() if key != "event_sha256"}
        )
    with pytest.raises(ClosedLoopContractError):
        _validate_agent_run_event_contract(
            target,
            previous=events[-2],
            prior_events=events[:-1],
            max_attempts=1,
        )


@pytest.mark.parametrize(
    ("event_type", "field"),
    (("attempt_completed", "attempt"), ("run_succeeded", "attempt_count")),
)
def test_agent_run_event_contract_rejects_boolean_integer_payloads(
    event_type,
    field,
):
    events = _success_contract_events()
    index = next(
        position
        for position, event in enumerate(events)
        if event["event_type"] == event_type
    )
    target = deepcopy(events[index])
    target["safe_payload"][field] = True
    target["event_sha256"] = _agent_run_event_hash(
        {key: value for key, value in target.items() if key != "event_sha256"}
    )

    with pytest.raises(ClosedLoopContractError):
        _validate_agent_run_event_contract(
            target,
            previous=events[index - 1],
            prior_events=events[:index],
            max_attempts=1,
        )


def capture_supporting(adapter, signer: Principal) -> dict[str, str]:
    refs = {}
    for purpose, spec in FIXTURE["attestations"].items():
        record = getattr(adapter, f"capture_{purpose}")(
            principal=signer,
            store_ref=FIXTURE["scope"]["store_ref"],
            data_as_of=DATA_AS_OF,
            attestation_ref=spec["attestation_ref"],
        )
        refs[purpose] = record.id
    return refs


def record_bundle(service, refs):
    return service.record(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        as_of=DATA_AS_OF,
        agent_run_ref=FIXTURE["agent_run_ref"],
        experiment_evidence_ref=refs["experiment"],
        cost_evidence_ref=refs["cost"],
        outcome_evidence_ref=refs["business_outcome"],
        idempotency_key=FIXTURE["idempotency_key"],
    )


def _resign_supporting_causal_claim(engine, *, evidence_id: str, causal_claim_allowed: object) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, evidence_id)
        assert row is not None
        blob = session.get(EvidenceBlobRow, row.blob_sha256)
        assert blob is not None
        payload = json.loads(bytes(blob.content_bytes).decode("utf-8"))
        payload["claims"]["causal_claim_allowed"] = causal_claim_allowed
        claims_sha = _closed_loop_claims_sha256(payload["claims"])
        payload["claims_sha256"] = claims_sha
        attestation_envelope = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "attestation_sha256",
                "attestation_signature_sha256",
                "payload_status",
                "contains_customer_data",
                "external_write_allowed",
            }
        }
        attestation_sha = hashlib.sha256(
            json.dumps(
                attestation_envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        payload["attestation_sha256"] = attestation_sha
        payload["attestation_signature_sha256"] = hashlib.sha256(f"signature:{attestation_sha}".encode()).hexdigest()
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        content_sha = hashlib.sha256(content).hexdigest()
        metadata = dict(row.metadata_json)
        metadata["closed_loop_claims"] = payload["claims"]
        metadata["closed_loop_claims_sha256"] = claims_sha
        metadata["closed_loop_attestation_sha256"] = attestation_sha
        metadata["closed_loop_attestation_signature_sha256"] = payload["attestation_signature_sha256"]
        scope_binding = metadata["closed_loop_scope_binding_sha256"]
        row.filename = f"{payload['purpose']}-{content_sha}.json"
        row.source_ref = f"{row.source}://{scope_binding}/{claims_sha}/{content_sha}"
        row.metadata_json = metadata
        row.blob_sha256 = content_sha
        blob.sha256 = content_sha
        blob.byte_size = len(content)
        blob.content_bytes = content


def _resign_supporting_projection(
    engine,
    *,
    evidence_id: str,
    mutation: str,
) -> None:
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, evidence_id)
        assert row is not None
        blob = session.get(EvidenceBlobRow, row.blob_sha256)
        assert blob is not None
        payload = json.loads(bytes(blob.content_bytes).decode("utf-8"))
        metadata = dict(row.metadata_json)

        if mutation == "payload_extra":
            payload["unexpected"] = "jointly-resigned"
        elif mutation == "payload_status":
            payload["payload_status"] = "retained"
        elif mutation == "external_write_allowed":
            payload["external_write_allowed"] = True
        elif mutation == "contains_customer_data":
            payload["contains_customer_data"] = True
        elif mutation == "noncanonical_time":
            payload["recorded_at"] = payload["recorded_at"].replace("+00:00", "Z")
        elif mutation == "scope":
            payload["exact_scope"] = dict(payload["exact_scope"])
            payload["exact_scope"]["store_ref"] = "store-drift"
        elif mutation == "exact_scope_null":
            payload["exact_scope"] = dict(payload["exact_scope"])
            payload["exact_scope"]["entity_ref"] = None
        elif mutation == "contract":
            payload["contract_id"] = "wrong-contract"
        elif mutation == "issuer":
            payload["issuer_id"] = "wrong-issuer"
        elif mutation == "schema":
            payload["schema_sha256"] = "f" * 64
        elif mutation == "purpose":
            payload["purpose"] = "cost"
        elif mutation == "noncanonical_claims":
            purpose = payload["purpose"]
            if purpose == "experiment":
                payload["claims"]["window_start"] = payload["claims"][
                    "window_start"
                ].replace("+00:00", "Z")
            elif purpose == "cost":
                payload["claims"]["amount_minor_units"] = str(
                    payload["claims"]["amount_minor_units"]
                )
            elif purpose == "business_outcome":
                payload["claims"]["value_decimal"] = "01.00"
            else:
                payload["claims"]["replacement_bundle_id"] = ""
        elif mutation == "claims_sample_string":
            payload["claims"]["sample_size"] = str(
                payload["claims"]["sample_size"]
            )

        claims_sha = _closed_loop_claims_sha256(payload["claims"])
        payload["claims_sha256"] = claims_sha
        attestation_envelope = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "attestation_sha256",
                "attestation_signature_sha256",
                "payload_status",
                "contains_customer_data",
                "external_write_allowed",
            }
        }
        attestation_sha = _hash_json(attestation_envelope)
        payload["attestation_sha256"] = attestation_sha
        payload["attestation_signature_sha256"] = hashlib.sha256(
            f"signature:{attestation_sha}".encode()
        ).hexdigest()

        if mutation == "attestation_ref":
            payload["attestation_ref"] = "attestation-drift"
        elif mutation == "authority_receipt_id":
            payload["authority_receipt_id"] = "receipt-drift"

        metadata.update(
            {
                "contract_id": payload["contract_id"],
                "closed_loop_purpose": payload["purpose"],
                "closed_loop_claims": payload["claims"],
                "closed_loop_claims_sha256": claims_sha,
                "closed_loop_attestation_sha256": payload["attestation_sha256"],
                "closed_loop_attestation_signature_sha256": payload[
                    "attestation_signature_sha256"
                ],
                "closed_loop_attestation_ref": payload["attestation_ref"],
                "closed_loop_authority_receipt_id": payload["authority_receipt_id"],
                "closed_loop_issuer_id": payload["issuer_id"],
                "closed_loop_issuer_contract_id": payload["issuer_contract_id"],
                "closed_loop_issuer_contract_version": payload[
                    "issuer_contract_version"
                ],
                "closed_loop_issuer_contract_sha256": payload[
                    "issuer_contract_sha256"
                ],
                "closed_loop_schema_sha256": payload["schema_sha256"],
                "closed_loop_issuer_actor_id": payload["issuer_actor_id"],
                "closed_loop_data_as_of": payload["data_as_of"],
                "closed_loop_recorded_at": payload["recorded_at"],
                "closed_loop_review_due_at": payload["review_due_at"],
                "closed_loop_scope_binding_sha256": _hash_json(
                    payload["exact_scope"]
                ),
                **payload["exact_scope"],
            }
        )
        if mutation == "metadata_extra":
            metadata["unexpected"] = "jointly-resigned"
        elif mutation == "metadata_missing_extra":
            metadata.pop("legal_hold")
            metadata["unexpected"] = False

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        content_sha = hashlib.sha256(content).hexdigest()
        row.filename = f"{payload['purpose']}-{content_sha}.json"
        row.source_ref = (
            f"{row.source}://{metadata['closed_loop_scope_binding_sha256']}/"
            f"{claims_sha}/{content_sha}"
        )
        row.metadata_json = metadata
        row.blob_sha256 = content_sha
        row.effective_at = datetime.fromisoformat(payload["effective_at"])
        row.effective_until = datetime.fromisoformat(payload["effective_until"])
        row.recorded_at = datetime.fromisoformat(payload["recorded_at"])
        row.created_by = payload["issuer_actor_id"]
        if mutation == "source_ref":
            row.source_ref += "-drift"
        elif mutation == "row_recorded_at":
            row.recorded_at += timedelta(microseconds=1)
        elif mutation == "filename":
            row.filename = "wrong.json"
        elif mutation == "content_type":
            row.content_type = "text/plain"
        elif mutation == "created_by":
            row.created_by = "wrong-issuer-actor"
        blob.sha256 = content_sha
        blob.byte_size = len(content)
        blob.content_bytes = content


@pytest.mark.parametrize("causal_value", (True, "false", 0, 1))
def test_closed_loop_claim_normalizer_rejects_causal_true_before_evidence(
    causal_value,
):
    engine, _, _, _, adapter = make_workspace()
    adapter.attestation_authorities["experiment"].claims["causal_claim_allowed"] = causal_value

    with pytest.raises(PermissionError, match="causal claims are not admitted"):
        adapter.capture_experiment(
            principal=principal(),
            store_ref=FIXTURE["scope"]["store_ref"],
            data_as_of=DATA_AS_OF,
            attestation_ref="causal-claim-rejected",
        )

    with Session(engine) as session:
        for model in (
            EvidenceBlobRow,
            EvidenceRecordRow,
            ClosedLoopOutcomeBundleRow,
            ClosedLoopOutcomeEvidenceLinkRow,
            ClosedLoopOutcomeEventRow,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    ("purpose", "field", "value"),
    (
        ("experiment", "confidence_level_decimal", "0.9500001"),
        ("business_outcome", "confidence_level_decimal", "0.9500001"),
        ("business_outcome", "value_decimal", "42.5000000000001"),
        ("business_outcome", "value_decimal", "1000000000000000000"),
    ),
)
def test_authority_decimal_must_be_exactly_representable_before_evidence(
    purpose,
    field,
    value,
):
    engine, _, _, _, adapter = make_workspace()
    adapter.attestation_authorities[purpose].claims[field] = value

    with pytest.raises(PermissionError, match="exactly storable"):
        getattr(adapter, f"capture_{purpose}")(
            principal=principal(),
            store_ref=FIXTURE["scope"]["store_ref"],
            data_as_of=DATA_AS_OF,
            attestation_ref=f"decimal-rejected-{purpose}-{field}",
        )

    with Session(engine) as session:
        for model in (
            EvidenceBlobRow,
            EvidenceRecordRow,
            ClosedLoopOutcomeBundleRow,
            ClosedLoopOutcomeEvidenceLinkRow,
            ClosedLoopOutcomeEventRow,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_exact_numeric_boundaries_accept_trailing_zero_overrepresentation():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    adapter.attestation_authorities["experiment"].claims[
        "confidence_level_decimal"
    ] = "1.0000000"
    outcome_claims = adapter.attestation_authorities["business_outcome"].claims
    outcome_claims["confidence_level_decimal"] = "1.0000000"
    outcome_claims["value_decimal"] = "42.1234567890120"

    refs = capture_supporting(adapter, principal())
    first = record_bundle(service, refs)
    replay = record_bundle(service, refs)

    assert first["experiment"]["confidence_level_decimal"] == "1"
    assert replay["business_outcome"]["confidence_level_decimal"] == "1"
    assert replay["business_outcome"]["value_decimal"] == "42.123456789012"
    assert {**first, "idempotent": True} == replay


def test_supporting_causal_true_rehashed_still_blocks_bundle_without_residue():
    engine, _, _, service, adapter = make_workspace()
    seed_agent_run(engine, service.evidence)
    refs = capture_supporting(adapter, principal())
    _resign_supporting_causal_claim(
        engine,
        evidence_id=refs["experiment"],
        causal_claim_allowed=True,
    )

    with pytest.raises(ClosedLoopContractError, match="causal claim"):
        record_bundle(service, refs)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEvidenceLinkRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "payload_extra",
        "metadata_extra",
        "metadata_missing_extra",
        "payload_status",
        "external_write_allowed",
        "contains_customer_data",
        "noncanonical_time",
        "scope",
        "exact_scope_null",
        "claims_sample_string",
        "contract",
        "issuer",
        "schema",
        "purpose",
        "attestation_ref",
        "authority_receipt_id",
        "source_ref",
        "row_recorded_at",
        "filename",
        "content_type",
        "created_by",
    ),
)
def test_supporting_jointly_resigned_projection_drift_leaves_no_bundle_residue(
    mutation,
):
    engine, _, _, service, adapter = make_workspace()
    seed_agent_run(engine, service.evidence)
    refs = capture_supporting(adapter, principal())
    _resign_supporting_projection(
        engine,
        evidence_id=refs["experiment"],
        mutation=mutation,
    )

    with pytest.raises(ClosedLoopContractError):
        record_bundle(service, refs)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEvidenceLinkRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 0


@pytest.mark.parametrize(
    "purpose",
    ("experiment", "cost", "business_outcome", "review_event"),
)
def test_supporting_jointly_resigned_noncanonical_claims_fail_closed(purpose):
    engine, _, _, service, adapter = make_workspace()
    seed_agent_run(engine, service.evidence)
    refs = capture_supporting(adapter, principal())
    if purpose != "review_event":
        _resign_supporting_projection(
            engine,
            evidence_id=refs[purpose],
            mutation="noncanonical_claims",
        )
        with pytest.raises(ClosedLoopContractError, match="claims"):
            record_bundle(service, refs)
        expected_events = 0
    else:
        projection = record_bundle(service, refs)
        review_time = NOW + timedelta(hours=1)
        service.clock = lambda: review_time
        adapter.clock = lambda: review_time
        adapter.attestation_authorities["review_event"].claims = {
            "bundle_id": projection["bundle_id"],
            "event_type": "review_requested",
            "reason_code": "scheduled_review",
            "replacement_bundle_id": None,
            "requested_by_actor_id": "review-requester",
        }
        review = adapter.capture_review_event(
            principal=principal("capture-relay"),
            store_ref=FIXTURE["scope"]["store_ref"],
            data_as_of=review_time,
            attestation_ref="review-noncanonical-claims",
        )
        _resign_supporting_projection(
            engine,
            evidence_id=review.id,
            mutation="noncanonical_claims",
        )
        with pytest.raises(ClosedLoopContractError, match="claims"):
            service.append_review_event(
                principal=principal("review-requester"),
                store_ref=FIXTURE["scope"]["store_ref"],
                bundle_id=projection["bundle_id"],
                event_type="review_requested",
                reason_code="scheduled_review",
                review_evidence_ref=review.id,
                idempotency_key="review-noncanonical-claims",
            )
        expected_events = 1

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == expected_events
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEvidenceLinkRow)) == (
            3 if purpose == "review_event" else 0
        )


def test_record_replay_and_sealed_bas177_handoff_are_observation_only():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    refs = capture_supporting(adapter, principal())

    first = record_bundle(service, refs)
    replay = record_bundle(service, refs)
    handoff_port = Bas177ClosedLoopObservationPort(workspace=service)
    handoff = handoff_port.read(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=first["bundle_id"],
    )
    handoff_port.verify(handoff)

    assert first["status"] == "current"
    assert replay["idempotent"] is True
    assert handoff.status == "ready"
    assert handoff.learning_input_type == "association_only_outcome"
    assert handoff.causal_claim_allowed is False
    assert handoff.learning_eligibility == "observation_only"
    assert handoff.candidate_created is False
    assert handoff.transition_allowed is False
    assert handoff.promotion_allowed is False
    assert handoff.writes == 0
    assert handoff.opaque_scope_binding.startswith("clhs_")
    assert handoff.opaque_citation.startswith("clhc_")
    dumped = json.dumps(handoff.to_dict(), sort_keys=True)
    for raw in (
        FIXTURE["scope"]["tenant_ref"],
        FIXTURE["scope"]["entity_ref"],
        FIXTURE["scope"]["store_ref"],
        FIXTURE["scope"]["scope_grant_authority_sha256"],
        FIXTURE["agent_run_ref"],
    ):
        assert raw not in dumped
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 1
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEvidenceLinkRow)) == 3
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 1


def test_real_closed_loop_dashboard_ports_project_outcomes_and_review_state():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    registry = StrategicCapitalDashboardRegistry.load().payload["source_contracts"]
    citations = ScopedDashboardCitationAuthority(sealing_key=SEALING_KEY)
    context = DashboardReadContext(
        tenant_ref=FIXTURE["scope"]["tenant_ref"],
        entity_ref=FIXTURE["scope"]["entity_ref"],
        store_ref=FIXTURE["scope"]["store_ref"],
        scope_grant_authority_sha256=FIXTURE["scope"][
            "scope_grant_authority_sha256"
        ],
        data_as_of=NOW,
        authority_checked_at=NOW,
    )
    outcomes = ClosedLoopEvolutionReadPort(
        service=service,
        section_id="verified_outcomes",
        source_contract=registry["verified_outcomes"],
        citation_authority=citations,
    ).read(principal=principal(), context=context)
    assert outcomes.status == "ready"
    assert outcomes.display_items
    assert outcomes.citations[0].token.startswith("outc_")
    assert "USD" in outcomes.display_items[0].display_text

    reviews = ClosedLoopEvolutionReadPort(
        service=service,
        section_id="invalidation_review",
        source_contract=registry["invalidation_review"],
        citation_authority=citations,
    )
    with pytest.raises(DashboardNoData, match="no closed-loop review is due"):
        reviews.read(principal=principal(), context=context)

    review_time = NOW + timedelta(hours=1)
    service.clock = lambda: review_time
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": projection["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    review = adapter.capture_review_event(
        principal=principal("capture-relay"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="dashboard-review-state",
    )
    service.append_review_event(
        principal=principal("review-requester"),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
        event_type="review_requested",
        reason_code="scheduled_review",
        review_evidence_ref=review.id,
        idempotency_key="dashboard-review-state",
    )
    reviewed = reviews.read(
        principal=principal(),
        context=replace(
            context,
            data_as_of=review_time,
            authority_checked_at=review_time,
        ),
    )
    assert reviewed.status == "partial"
    assert reviewed.display_items
    assert reviewed.citations[0].token.startswith("invc_")


def test_all_closed_loop_reserved_evidence_is_hidden_from_generic_governance(
):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    review_time = NOW + timedelta(hours=1)
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": projection["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    adapter.capture_review_event(
        principal=principal("capture-relay"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="governance-reserved-matrix",
    )

    with Session(engine) as session, session.begin():
        reserved_rows = list(
            session.scalars(
                select(EvidenceRecordRow).where(
                    EvidenceRecordRow.source.in_(
                        tuple(sorted(CLOSED_LOOP_RESERVED_SOURCES))
                    )
                )
            )
        )
        assert {row.source for row in reserved_rows} == set(
            CLOSED_LOOP_RESERVED_SOURCES
        )
        reserved_ids = {row.id for row in reserved_rows}
        for row in reserved_rows:
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            assert blob is not None
            blob.content_bytes = b"reserved-integrity-drift"

    runtime_name = "apps.control_plane.runtime"
    router_name = "apps.control_plane.routers.evidence_governance"
    prior_runtime = sys.modules.pop(runtime_name, None)
    prior_router = sys.modules.pop(router_name, None)
    fake_runtime = ModuleType(runtime_name)
    fake_runtime.runtime = SimpleNamespace(evidence=evidence)
    sys.modules[runtime_name] = fake_runtime
    try:
        evidence_router = importlib.import_module(router_name)
        visible = evidence_router.list_evidence(principal=principal(), limit=500)
        assert reserved_ids.isdisjoint({item["id"] for item in visible})

        for evidence_id in reserved_ids:
            for operation in (
                evidence_router.get_evidence,
                evidence_router.verify_evidence,
                evidence_router.evidence_retention,
                evidence_router.evidence_content,
                evidence_router.evidence_lineage,
            ):
                with pytest.raises(HTTPException) as blocked:
                    operation(evidence_id=evidence_id, principal=principal())
                assert blocked.value.status_code == 404
            with pytest.raises(ValueError, match="dedicated ledger"):
                evidence.link(
                    evidence_id=evidence_id,
                    target_type="case",
                    target_id="case-reserved",
                    relationship="supports",
                    created_by="operator",
                )
    finally:
        sys.modules.pop(router_name, None)
        sys.modules.pop(runtime_name, None)
        if prior_router is not None:
            sys.modules[router_name] = prior_router
        if prior_runtime is not None:
            sys.modules[runtime_name] = prior_runtime

    class NoIncidents:
        @staticmethod
        def list():
            return []

        @staticmethod
        def open(**_):
            raise AssertionError("reserved Evidence must not create an incident")

    integrity = EvidenceIntegrityMonitorService(
        evidence=evidence,
        incidents=NoIncidents(),
    ).scan(
        actor_id="monitor",
        limit=500,
        as_of=review_time.isoformat(),
    )
    assert integrity["findings"] == []
    assert integrity["finding_evidence_ids"] == {}
    assert integrity["incident_ids"] == {}


def test_authority_rotation_and_terminal_expiry_invalidate_old_bundle():
    engine, evidence, scope_grants, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    refs = capture_supporting(adapter, principal())
    first = record_bundle(service, refs)

    expire_agent_run_evidence(engine, effective_until=datetime(2026, 8, 6, tzinfo=UTC))
    service.clock = lambda: datetime(2026, 8, 6, 1, 0, tzinfo=UTC)
    expired = service.get(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=first["bundle_id"],
    )
    assert expired["status"] == "invalidated"
    assert expired["reason_code"] == "agent_run_terminal_not_current"

    scope_grants.authority_sha256 = "c" * 64
    with pytest.raises(KeyError):
        service.get(
            principal=principal(),
            store_ref=FIXTURE["scope"]["store_ref"],
            bundle_id=first["bundle_id"],
        )


def test_unknown_causal_method_never_becomes_causal():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    adapter.attestation_authorities["experiment"].claims["method"] = "unknown_method"
    adapter.attestation_authorities["business_outcome"].claims["method"] = "unknown_method"
    adapter.attestation_authorities["experiment"].claims["sample_size"] = 1_000_000_000
    adapter.attestation_authorities["business_outcome"].claims["sample_size"] = 1_000_000_000
    refs = capture_supporting(adapter, principal())

    projection = record_bundle(service, refs)

    assert projection["business_outcome"]["causal_claim_allowed"] is False
    assert projection["reason_code"] == "observational_association_only"


def test_handoff_tamper_is_rejected():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    handoff = service.bas177_handoff(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
    )
    object.__setattr__(handoff, "reason_code", "tampered")
    object.__setattr__(handoff, "content_sha256", _hash_json(handoff.payload()))
    with pytest.raises(ClosedLoopContractError):
        service.verify_bas177_handoff(handoff)


def test_real_agent_run_receipt_authority_verifies_the_full_event_chain(tmp_path):
    database_engine = create_engine(f"sqlite:///{tmp_path / 'closed-loop.db'}")
    engine, evidence, _, service, adapter = make_workspace(database_engine)
    service.agent_run_receipts = seed_governed_agent_run(evidence)

    projection = record_bundle(service, capture_supporting(adapter, principal()))

    assert projection["status"] == "current"
    with Session(engine) as session, session.begin():
        first_event = session.scalar(
            select(AgentRuntimeRunEventRow)
            .where(AgentRuntimeRunEventRow.run_id == FIXTURE["agent_run_ref"])
            .order_by(AgentRuntimeRunEventRow.event_index)
            .limit(1)
        )
        assert first_event is not None
        first_event.previous_event_sha256 = "f" * 64
    invalidated = service.get(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
    )
    assert invalidated["status"] == "invalidated"
    assert invalidated["reason_code"] == "agent_run_terminal_not_current"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "unknown_outcome"),
        ("contract_id", "drifted-contract"),
        ("proposal_only", False),
        ("formal_fact", True),
        ("external_write_allowed", True),
        ("event_sha256", "c" * 64),
    ],
)
def test_agent_run_receipt_contract_drift_blocks_before_bundle_write(field, value):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    setattr(service.agent_run_receipts, field, value)
    refs = capture_supporting(adapter, principal())

    with pytest.raises(ClosedLoopContractError):
        record_bundle(service, refs)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0


@pytest.mark.parametrize(
    ("purpose", "value"),
    [
        ("experiment", None),
        ("business_outcome", None),
        ("experiment", "EUR"),
        ("business_outcome", "EUR"),
    ],
)
def test_money_outcome_requires_one_currency_bound_to_cost(purpose, value):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    adapter.attestation_authorities[purpose].claims["metric_currency"] = value

    with pytest.raises((ClosedLoopContractError, PermissionError)):
        refs = capture_supporting(adapter, principal())
        record_bundle(service, refs)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0


def test_historical_cutoff_hides_future_bundles_and_future_review_events():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))

    before_record = service.list_current(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        as_of=NOW - timedelta(microseconds=1),
    )
    assert before_record["items"] == []

    review_time = NOW + timedelta(hours=1)
    service.clock = lambda: review_time
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": projection["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": principal().actor_id,
    }
    review = adapter.capture_review_event(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="review-attestation-1",
    )
    service.append_review_event(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
        event_type="review_requested",
        reason_code="scheduled_review",
        review_evidence_ref=review.id,
        idempotency_key="review-request-1",
    )

    historical = service.list_current(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        as_of=NOW,
    )
    assert historical["items"][0]["status"] == "current"
    assert historical["items"][0]["event_count"] == 1
    current = service.list_current(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        as_of=review_time,
    )
    assert current["items"][0]["status"] == "review_due"
    assert current["items"][0]["event_count"] == 2

    with Session(engine) as session, session.begin():
        future = session.scalar(
            select(ClosedLoopOutcomeEventRow).where(
                ClosedLoopOutcomeEventRow.bundle_id == projection["bundle_id"],
                ClosedLoopOutcomeEventRow.event_index == 2,
            )
        )
        assert future is not None
        future.previous_event_sha256 = "f" * 64
    historical_after_future_corruption = service.list_current(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        as_of=NOW,
    )
    assert historical_after_future_corruption["items"][0]["status"] == "current"


def test_scope_rotation_during_write_rolls_back_and_during_read_returns_nothing():
    engine, evidence, scope_grants, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    refs = capture_supporting(adapter, principal())
    scope_grants.calls = 0
    scope_grants.rotate_on_call = 2
    with pytest.raises(ClosedLoopContractError, match="authority changed"):
        record_bundle(service, refs)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0

    scope_grants.authority_sha256 = FIXTURE["scope"]["scope_grant_authority_sha256"]
    scope_grants.calls = 0
    scope_grants.rotate_on_call = None
    projection = record_bundle(service, refs)
    scope_grants.calls = 0
    scope_grants.rotate_on_call = 2
    with pytest.raises(ClosedLoopContractError, match="authority changed"):
        service.get(
            principal=principal(),
            store_ref=FIXTURE["scope"]["store_ref"],
            bundle_id=projection["bundle_id"],
        )


def test_final_trusted_timestamp_reprojects_expired_state_instead_of_replaying_fresh():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    expire_agent_run_evidence(engine, effective_until=datetime(2026, 8, 6, tzinfo=UTC))
    times = iter((NOW, datetime(2026, 8, 6, 1, 0, tzinfo=UTC)))
    service.clock = lambda: next(times)

    final = service.get(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
    )

    assert final["status"] == "invalidated"
    assert final["reason_code"] == "agent_run_terminal_not_current"


def test_bas177_full_payload_hmac_rejects_plain_hash_resealing():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    expire_agent_run_evidence(engine, effective_until=datetime(2026, 8, 6, tzinfo=UTC))
    service.clock = lambda: datetime(2026, 8, 6, 1, 0, tzinfo=UTC)
    original = service.bas177_handoff(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
    )
    assert original.status == "invalidated"

    mutations = (
        {"status": "ready"},
        {"reason_code": "observational_association_only"},
        {"data_as_of": "2026-08-05T11:00:00Z"},
        {"latest_event_recorded_at": "2026-08-05T11:59:59Z"},
        {"invalidation_conditions": ("none",)},
    )
    for values in mutations:
        tampered = replace(original, **values, content_sha256="")
        tampered = replace(
            tampered,
            content_sha256=_hash_json(tampered.payload()),
        )
        with pytest.raises(ClosedLoopContractError):
            service.verify_bas177_handoff(tampered)


@pytest.mark.parametrize(
    "changes",
    (
        {"reason_code": "bad\nreason"},
        {"data_as_of": "2026-08-05T10:00:00"},
        {"latest_event_type": "unknown_event"},
        {"latest_event_recorded_at": "2026-08-05T08:00:00Z"},
        {"invalidation_conditions": ["review_due"]},
        {"status": "ready", "latest_event_type": "review_requested"},
        {"status": "ready", "reason_code": "revoked"},
        {"status": "invalidated", "reason_code": "observational_association_only"},
        {
            "status": "invalidated",
            "reason_code": "revoked",
            "latest_event_type": "invalidated",
        },
    ),
)
def test_bas177_typed_contract_rejects_even_server_resigned_drift(changes):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    observation = service.bas177_handoff(
        principal=principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
    )
    tampered = replace(observation, **changes, content_sha256="", seal_sha256="")
    payload = tampered.payload()
    tampered = replace(
        tampered,
        content_sha256=_hash_json(payload),
        seal_sha256=_handoff_seal(SEALING_KEY, payload),
    )
    with pytest.raises(ClosedLoopContractError, match="handoff contract drifted"):
        service.verify_bas177_handoff(tampered)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("contract_id", "wrong-contract"),
        ("tenant_ref", "tenant-b"),
        ("entity_ref", "entity-b"),
        ("store_ref", "store-b"),
        ("authority_sha256", "c" * 64),
        ("run_id", "run-other"),
        ("event_id", "event-other"),
        ("event_type", "run_failed"),
        ("event_sha256", "c" * 64),
    ),
)
def test_agent_run_evidence_metadata_exact_binding_blocks_prewrite(field, value):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    with Session(engine) as session, session.begin():
        event = session.scalar(select(AgentRuntimeRunEventRow))
        assert event is not None
        row = session.get(EvidenceRecordRow, event.evidence_id)
        assert row is not None
        metadata = dict(row.metadata_json)
        metadata[field] = value
        row.metadata_json = metadata
    with pytest.raises(ClosedLoopContractError, match="AgentRun"):
        record_bundle(service, capture_supporting(adapter, principal()))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0


@pytest.mark.parametrize(
    "mutation",
    ("extra", "missing_extra", "retention_class", "legal_hold"),
)
def test_agent_run_evidence_metadata_shape_blocks_prewrite(mutation):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    with Session(engine) as session, session.begin():
        event = session.scalar(select(AgentRuntimeRunEventRow))
        assert event is not None
        row = session.get(EvidenceRecordRow, event.evidence_id)
        assert row is not None
        metadata = dict(row.metadata_json)
        if mutation == "extra":
            metadata["raw_prompt"] = "forbidden"
        elif mutation == "missing_extra":
            metadata.pop("legal_hold")
            metadata["customer_email"] = "forbidden"
        elif mutation == "retention_class":
            metadata["retention_class"] = "compliance"
        else:
            metadata["legal_hold"] = True
        row.metadata_json = metadata
    with pytest.raises(ClosedLoopContractError, match="AgentRun"):
        record_bundle(service, capture_supporting(adapter, principal()))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEvidenceLinkRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 0


@pytest.mark.parametrize("drift", ("grade", "blob"))
def test_agent_run_evidence_grade_and_blob_contract_block_prewrite(drift):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    with Session(engine) as session, session.begin():
        event = session.scalar(select(AgentRuntimeRunEventRow))
        assert event is not None
        row = session.get(EvidenceRecordRow, event.evidence_id)
        assert row is not None
        if drift == "grade":
            row.grade = EvidenceGrade.A.value
        else:
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            assert blob is not None
            blob.content_bytes = b'{"contract_id":"wrong"}'
    with pytest.raises(ClosedLoopContractError, match="AgentRun"):
        record_bundle(service, capture_supporting(adapter, principal()))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0


def test_jointly_resigned_sensitive_agent_run_payload_blocks_without_residue():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(AgentRuntimeRunEventRow)
            .where(AgentRuntimeRunEventRow.run_id == FIXTURE["agent_run_ref"])
            .order_by(AgentRuntimeRunEventRow.event_index.desc())
            .limit(1)
        )
        assert event is not None
        evidence_row = session.get(EvidenceRecordRow, event.evidence_id)
        assert evidence_row is not None
        old_blob = session.get(EvidenceBlobRow, evidence_row.blob_sha256)
        assert old_blob is not None
        event_payload = _agent_run_event_row_payload(event)
        event_payload["safe_payload"] = {
            "attempt_count": 1,
            "nested": {"prompt": "secret"},
        }
        event_sha = _agent_run_event_hash({key: value for key, value in event_payload.items() if key != "event_sha256"})
        event_id = _agent_run_event_id(event.run_id, event_sha)
        event_payload["event_sha256"] = event_sha
        evidence_payload = {
            "contract_id": "kjds-governed-agent-run-evidence-v1",
            "run_id": event.run_id,
            "event_id": event_id,
            **event_payload,
            "payload_status": "not_retained",
            "proposal_only": True,
            "formal_fact": False,
            "external_write_allowed": False,
        }
        content = _agent_run_canonical(evidence_payload)
        content_sha = hashlib.sha256(content).hexdigest()
        session.add(
            EvidenceBlobRow(
                sha256=content_sha,
                byte_size=len(content),
                content_bytes=content,
                created_at=old_blob.created_at,
            )
        )
        metadata = dict(evidence_row.metadata_json)
        metadata.update({"event_id": event_id, "event_sha256": event_sha})
        event.event_id = event_id
        event.event_sha256 = event_sha
        event.safe_payload_json = dict(event_payload["safe_payload"])
        event.evidence_sha256 = content_sha
        evidence_row.blob_sha256 = content_sha
        evidence_row.filename = f"{event_id}.json"
        evidence_row.source_ref = f"agent-run://{event.run_id}/{event_id}"
        evidence_row.metadata_json = metadata

    with pytest.raises(ClosedLoopContractError, match="AgentRun"):
        record_bundle(service, capture_supporting(adapter, principal()))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEvidenceLinkRow)) == 0
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 0


@pytest.mark.parametrize(
    "drift",
    (
        "request_scope",
        "request_actor_bool",
        "request_scope_number",
        "bundle_supporting",
        "bundle_supporting_issuer_number",
        "outcome_value",
        "link_claims",
        "link_recorded_at",
    ),
)
def test_read_projection_recomputes_root_and_link_canonical_bindings(drift):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    with Session(engine) as session, session.begin():
        row = session.get(ClosedLoopOutcomeBundleRow, projection["bundle_id"])
        assert row is not None
        if drift == "request_scope":
            request = deepcopy(row.request_json)
            request["scope"]["entity_ref"] = "entity-drift"
            row.request_json = request
        elif drift in {"request_actor_bool", "request_scope_number"}:
            request = deepcopy(row.request_json)
            bundle = deepcopy(row.bundle_json)
            if drift == "request_actor_bool":
                request["actor_id"] = True
                bundle["actor_id"] = True
                row.actor_id = "true"
            else:
                request["scope"]["entity_ref"] = 7
                bundle["scope"]["entity_ref"] = 7
            row.request_json = request
            row.bundle_json = bundle
            row.request_sha256 = _hash_json(request)
            row.bundle_sha256 = _hash_json(bundle)
        elif drift == "bundle_supporting":
            bundle = deepcopy(row.bundle_json)
            bundle["supporting"]["cost"]["claims_sha256"] = "f" * 64
            row.bundle_json = bundle
        elif drift == "bundle_supporting_issuer_number":
            bundle = deepcopy(row.bundle_json)
            bundle["supporting"]["experiment"]["issuer_actor_id"] = 7
            row.bundle_json = bundle
            row.bundle_sha256 = _hash_json(bundle)
        elif drift == "outcome_value":
            row.outcome_value_decimal = row.outcome_value_decimal + 1
        else:
            link = session.scalar(
                select(ClosedLoopOutcomeEvidenceLinkRow).where(
                    ClosedLoopOutcomeEvidenceLinkRow.bundle_id == projection["bundle_id"],
                    ClosedLoopOutcomeEvidenceLinkRow.purpose == "experiment",
                )
            )
            assert link is not None
            if drift == "link_claims":
                link.claims_sha256 = "f" * 64
            else:
                link.evidence_recorded_at = link.evidence_recorded_at + timedelta(seconds=1)

    with pytest.raises(ClosedLoopContractError):
        service.get(
            principal=principal(),
            store_ref=FIXTURE["scope"]["store_ref"],
            bundle_id=projection["bundle_id"],
        )


@pytest.mark.parametrize(
    "drift",
    ("nonterminal_expired", "event_recorded_late", "evidence_recorded_late"),
)
def test_agent_run_full_prefix_currentness_and_transaction_cutoff(drift, tmp_path):
    database_engine = create_engine(f"sqlite:///{tmp_path / f'{drift}.db'}")
    engine, evidence, _, service, adapter = make_workspace(database_engine)
    service.agent_run_receipts = seed_governed_agent_run(evidence)
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(AgentRuntimeRunEventRow)
            .where(AgentRuntimeRunEventRow.run_id == FIXTURE["agent_run_ref"])
            .order_by(AgentRuntimeRunEventRow.event_index)
            .limit(1)
        )
        assert event is not None
        evidence_row = session.get(EvidenceRecordRow, event.evidence_id)
        assert evidence_row is not None
        if drift == "nonterminal_expired":
            evidence_row.effective_until = NOW - timedelta(seconds=1)
        elif drift == "event_recorded_late":
            event.recorded_at = DATA_AS_OF + timedelta(seconds=1)
        else:
            evidence_row.recorded_at = DATA_AS_OF + timedelta(seconds=1)
    refs = capture_supporting(adapter, principal())
    with pytest.raises(ClosedLoopContractError):
        record_bundle(service, refs)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0


@pytest.mark.parametrize("event_index", (1, 6))
def test_record_final_timestamp_revalidates_every_agent_run_event(event_index, tmp_path):
    database_engine = create_engine(f"sqlite:///{tmp_path / f'final-{event_index}.db'}")
    engine, evidence, _, service, adapter = make_workspace(database_engine)
    service.agent_run_receipts = seed_governed_agent_run(evidence)
    refs = capture_supporting(adapter, principal())
    original_reverify = service._reverify_agent_run_current

    def mutate_during_final_reverification(session, **kwargs):
        event = session.scalar(
            select(AgentRuntimeRunEventRow).where(
                AgentRuntimeRunEventRow.run_id == FIXTURE["agent_run_ref"],
                AgentRuntimeRunEventRow.event_index == event_index,
            )
        )
        assert event is not None
        evidence_row = session.get(EvidenceRecordRow, event.evidence_id)
        assert evidence_row is not None
        evidence_row.effective_until = NOW
        session.flush()
        return original_reverify(session, **kwargs)

    service._reverify_agent_run_current = mutate_during_final_reverification
    with pytest.raises(ClosedLoopContractError, match="AgentRun"):
        record_bundle(service, refs)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeBundleRow)) == 0


@pytest.mark.parametrize("mutation", ("remove", "add", "change"))
def test_authority_schema_manifest_drift_is_rejected_before_admission(mutation):
    payload = deepcopy(
        json.loads(Path("docs/project/registries/closed_loop_evolution_contracts.json").read_text(encoding="utf-8"))
    )
    manifest = payload["authority_claim_schemas"]["experiment"]
    if mutation == "remove":
        manifest["required_fields"].remove("metric_currency")
    elif mutation == "add":
        manifest["required_fields"].append("unregistered_field")
    else:
        manifest["field_types"]["metric_currency"] = "free_text"
    with pytest.raises(ClosedLoopContractError, match="claim schemas"):
        ClosedLoopEvolutionRegistry(payload)
    assert (
        CLOSED_LOOP_AUTHORITY_SCHEMA_MANIFESTS["experiment"]["field_types"]["metric_currency"]
        == "currency_or_null_by_metric_unit"
    )


@pytest.mark.parametrize("contract_kind", ("evidence", "review"))
@pytest.mark.parametrize(
    "mutation",
    ("empty", "missing", "extra", "missing_extra", "wrong_value"),
)
def test_registry_authority_contracts_require_exact_public_shape(
    contract_kind,
    mutation,
):
    payload = deepcopy(
        json.loads(
            Path(
                "docs/project/registries/closed_loop_evolution_contracts.json"
            ).read_text(encoding="utf-8")
        )
    )
    contract = (
        payload["evidence_contracts"]["experiment"]
        if contract_kind == "evidence"
        else payload["review_authority_contract"]
    )
    if mutation == "empty":
        contract.clear()
    elif mutation == "missing":
        contract.pop("source")
    elif mutation == "extra":
        contract["unexpected"] = "forbidden"
    elif mutation == "missing_extra":
        contract.pop("source")
        contract["unexpected"] = "forbidden"
    else:
        contract["source"] = "wrong-source"

    with pytest.raises(ClosedLoopContractError):
        ClosedLoopEvolutionRegistry(payload)


def test_registry_rejects_rehashed_authority_contract_injection():
    payload = deepcopy(
        json.loads(
            Path(
                "docs/project/registries/closed_loop_evolution_contracts.json"
            ).read_text(encoding="utf-8")
        )
    )
    payload["evidence_contracts"]["cost"]["raw_customer_data"] = "forbidden"
    attacker_rehash = _hash_json(payload)

    with pytest.raises(ClosedLoopContractError):
        ClosedLoopEvolutionRegistry(payload)
    assert len(attacker_rehash) == 64


def test_registry_load_requires_the_compiled_content_seal(tmp_path):
    loaded = ClosedLoopEvolutionRegistry.load()
    payload = deepcopy(loaded.payload)
    payload["migration_revision"] = "attacker-rehashed-revision"
    drifted = tmp_path / "closed-loop-registry.json"
    drifted.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="content seal drifted"):
        ClosedLoopEvolutionRegistry.load(drifted)


def test_review_requester_and_issuer_are_independent_across_principal_relay():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": projection["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    review_authority.issuer_actor_id_override = "review-requester"
    with pytest.raises(PermissionError, match="requester and issuer"):
        adapter.capture_review_event(
            principal=principal("capture-relay"),
            store_ref=FIXTURE["scope"]["store_ref"],
            data_as_of=NOW,
            attestation_ref="review-relay-attack",
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 1


def test_review_event_rejects_direct_same_actor_issuer(monkeypatch):
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    review_time = NOW + timedelta(hours=1)
    service.clock = lambda: review_time
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": projection["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    review = adapter.capture_review_event(
        principal=principal("capture-relay"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="review-direct-same-actor",
    )
    original_supporting = service._supporting

    def same_actor_supporting(*args, **kwargs):
        result = original_supporting(*args, **kwargs)
        if kwargs.get("purpose") == "review_event":
            result = dict(result)
            result["issuer_actor_id"] = "review-requester"
        return result

    monkeypatch.setattr(service, "_supporting", same_actor_supporting)
    with pytest.raises(ClosedLoopContractError, match="must be independent"):
        service.append_review_event(
            principal=principal("review-requester"),
            store_ref=FIXTURE["scope"]["store_ref"],
            bundle_id=projection["bundle_id"],
            event_type="review_requested",
            reason_code="scheduled_review",
            review_evidence_ref=review.id,
            idempotency_key="review-direct-same-actor",
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 1


def test_review_four_party_separation_positive_path():
    engine, evidence, _, service, adapter = make_workspace()
    seed_agent_run(engine, evidence)
    projection = record_bundle(service, capture_supporting(adapter, principal()))
    review_time = NOW + timedelta(hours=1)
    service.clock = lambda: review_time
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": projection["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    review = adapter.capture_review_event(
        principal=principal("capture-relay"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="review-four-party-positive",
    )
    result = service.append_review_event(
        principal=principal("review-requester"),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=projection["bundle_id"],
        event_type="review_requested",
        reason_code="scheduled_review",
        review_evidence_ref=review.id,
        idempotency_key="review-four-party-positive",
    )
    assert result["status"] == "review_due"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ClosedLoopOutcomeEventRow)) == 2


@pytest.mark.parametrize("failure", (2, 4, "registrar", "adapter"))
def test_runtime_factory_disposes_every_engine_on_partial_failure(monkeypatch, failure):
    class SellerOperatingSystemStub:
        def __init__(self, *args, **kwargs):
            del args, kwargs

    monkeypatch.setitem(
        sys.modules,
        "apps.control_plane.seller_operating_system",
        SimpleNamespace(SellerOperatingSystem=SellerOperatingSystemStub),
    )
    monkeypatch.setenv("KJDS_REPOSITORY", "memory")
    monkeypatch.setenv("KJDS_STRATEGIC_BENCHMARK_SEALING_KEY", "bas204-runtime-test-key-32-bytes-minimum")
    runtime_module = importlib.import_module("apps.control_plane.runtime")
    created = []

    class Engine:
        def __init__(self, purpose):
            self.purpose = purpose
            self.dispose_calls = 0

        def dispose(self):
            self.dispose_calls += 1

    def create_engine_for(purpose, *, generic_url):
        assert generic_url == "postgresql://runtime"
        if isinstance(failure, int) and len(created) + 1 == failure:
            raise RuntimeError("engine construction failed")
        engine = Engine(purpose)
        created.append(engine)
        return engine

    registrar_calls = 0

    def registrar(engine, *, purpose):
        nonlocal registrar_calls
        registrar_calls += 1
        if failure == "registrar" and registrar_calls == 2:
            raise RuntimeError("registrar construction failed")
        return (engine, purpose)

    def adapter(*args, **kwargs):
        if failure == "adapter":
            raise RuntimeError("adapter construction failed")
        return (args, kwargs)

    monkeypatch.setattr(runtime_module, "runtime_database_url", lambda: "postgresql://runtime")
    monkeypatch.setattr(runtime_module, "create_closed_loop_database_engine", create_engine_for)
    monkeypatch.setattr(runtime_module, "ClosedLoopEvidenceIssuerPort", lambda engine: engine)
    monkeypatch.setattr(runtime_module, "ClosedLoopAuthorityReceiptRegistrarPort", registrar)
    monkeypatch.setattr(runtime_module, "ClosedLoopEvidenceAuthorityAdapter", adapter)
    with pytest.raises(RuntimeError, match="construction failed"):
        runtime_module._build_closed_loop_evidence_authority(
            evidence=object(),
            scope_grants=object(),
            attestation_authorities={},
        )
    expected_created = failure - 1 if isinstance(failure, int) else 5
    assert len(created) == expected_created
    assert [engine.dispose_calls for engine in created] == [1] * expected_created
