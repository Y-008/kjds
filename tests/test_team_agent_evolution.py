from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
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
)
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    TeamAgentEvidenceAuthorityAdapter,
)
from apps.control_plane.security import Principal
from apps.control_plane.team_agent_evolution import (
    EVIDENCE_CONTRACT_ID,
    SUPPORT_EVIDENCE_CONTRACTS,
    ZERO_SHA256,
    GovernedTeamAgentEvolutionWorkspace,
    TeamAgentEvolutionCandidateRow,
    TeamAgentEvolutionConflictError,
    TeamAgentEvolutionError,
    TeamAgentEvolutionEventRow,
    TeamAgentEvolutionEvidenceLinkRow,
    _digest,
)

# The complete repository Gate collects this module before a multi-minute suite.
# Keep one frozen valid-time horizon that cannot expire during that run.
NOW = datetime.now(UTC) + timedelta(days=1)
AUTHORITY_A = "a" * 64


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeScopeGrants:
    def __init__(self) -> None:
        self.authority = AUTHORITY_A
        self.status = "ready"
        self.entity_ref = "entity-a"
        self.calls = 0
        self.rotate_on_call: int | None = None

    def current(self, *, principal, store_ref, as_of):
        self.calls += 1
        if self.rotate_on_call == self.calls:
            self.authority = "b" * 64
        return {
            "status": self.status,
            "tenant_ref": principal.tenant_ref,
            "entity_ref": self.entity_ref,
            "store_ref": store_ref,
            "authority_sha256": self.authority,
        }


def principal(actor_id: str, *roles: str) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset(roles),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


@pytest.fixture
def workspace():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        EvidenceBlobRow.__table__,
        EvidenceRecordRow.__table__,
        AgentRuntimeRunEnvelopeRow.__table__,
        AgentRuntimeRunEventRow.__table__,
        TeamAgentEvolutionCandidateRow.__table__,
        TeamAgentEvolutionEventRow.__table__,
        TeamAgentEvolutionEvidenceLinkRow.__table__,
    ]
    for table in tables:
        table.create(engine, checkfirst=True)
    evidence = EvidenceService(engine)
    grants = FakeScopeGrants()
    service = GovernedTeamAgentEvolutionWorkspace(
        engine=engine,
        evidence=evidence,
        scope_grants=grants,
        clock=lambda: NOW,
    )
    return engine, evidence, grants, service


def candidate_contract(service: GovernedTeamAgentEvolutionWorkspace) -> dict[str, str]:
    return {
        "agent_role_version_sha256": sha("role-v1"),
        "skill_contract_sha256": sha("skill-v1"),
        "eval_set_sha256": service.eval_set.sha256,
        "model_profile_sha256": sha("model-v1"),
        "tool_contract_sha256": sha("tools-v1"),
        "policy_version_sha256": sha("policy-v1"),
        "rollback_artifact_sha256": sha("rollback-v1"),
    }


def runtime_sha(contract: dict[str, str]) -> str:
    return _digest(
        {
            key: contract[key]
            for key in (
                "agent_role_version_sha256",
                "skill_contract_sha256",
                "model_profile_sha256",
                "tool_contract_sha256",
                "policy_version_sha256",
            )
        }
    )


def attestation(service, actor_id: str, purpose: str, claims: dict):
    payload_field = {
        "agent_run": "snapshot_sha256",
        "eval_set": "eval_set_sha256",
        "baseline": "baseline_snapshot_sha256",
        "shadow": "snapshot_sha256",
        "review": "snapshot_sha256",
        "risk_authority": "snapshot_sha256",
        "rollback": "rollback_artifact_sha256",
        "license": "license_sha256",
        "deidentification": "deidentification_sha256",
        "revocation": "revocation_contract_sha256",
        "graph_observation": "graph_snapshot_sha256",
    }[purpose]
    authority = SUPPORT_EVIDENCE_CONTRACTS[purpose]
    payload_sha256 = claims[payload_field]
    source_ref = f"{authority.source}://{sha(f'{purpose}:{actor_id}:{payload_sha256}')}"
    scope = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "scope_authority_sha256": AUTHORITY_A,
    }
    payload = {
        "contract_id": EVIDENCE_CONTRACT_ID,
        "source_contract_id": authority.contract_id,
        "scope": scope,
        "purpose": purpose,
        "claims": claims,
        "payload_sha256": payload_sha256,
        "source": authority.source,
        "source_ref": source_ref,
        "grade": authority.grade,
        "payload_status": "hash_and_code_only",
        "contains_customer_data": False,
        "external_write_allowed": False,
    }
    signer_role = {
        "eval_set": "compliance",
        "baseline": "reviewer",
        "shadow": "reviewer",
        "review": "reviewer",
        "risk_authority": "risk",
        "rollback": "risk",
        "license": "compliance",
        "deidentification": "compliance",
        "revocation": "compliance",
        "retirement": "compliance",
    }.get(purpose)
    if signer_role is not None:
        return TeamAgentEvidenceAuthorityAdapter(service.evidence).capture(
            principal=principal(actor_id, signer_role),
            purpose=purpose,
            claims=claims,
            **scope,
            candidate_author_actor_id="author-a",
            human_owner_actor_id="owner-a",
            effective_at=NOW.isoformat(),
            effective_until=(NOW + timedelta(days=30)).isoformat(),
        )
    return service.evidence.capture(
        content=json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        filename=f"{sha(source_ref)}.json",
        content_type="application/json",
        source=authority.source,
        source_ref=source_ref,
        grade=EvidenceGrade(authority.grade),
        effective_at=NOW.isoformat(),
        effective_until=(NOW + timedelta(days=30)).isoformat(),
        created_by=actor_id,
        metadata={
            "contract_id": EVIDENCE_CONTRACT_ID,
            "source_contract_id": authority.contract_id,
            **scope,
            "evolution_purpose": purpose,
            "payload_sha256": payload_sha256,
            "claims_sha256": _digest(claims),
            **claims,
            "retention_class": "security",
            "legal_hold": False,
        },
    )


def governed_run(service, tag: str) -> tuple[str, str]:
    run_id = f"run_{sha(tag)[:32]}"
    started_at = NOW - timedelta(minutes=1)
    scoped_input = service.evidence.capture(
        content=f'{{"contract":"hash-only","tag_sha256":"{sha(tag)}"}}'.encode(),
        filename=f"{sha(tag)}.json",
        content_type="application/json",
        source="test-team-agent-runtime-input",
        source_ref=f"team-agent-runtime://{sha(tag)}",
        grade=EvidenceGrade.A,
        effective_at=started_at.isoformat(),
        effective_until=None,
        created_by="runtime-input-reviewer",
    )
    evidence_refs = (
        AgentRunEvidenceRef(
            evidence_id=scoped_input.id,
            evidence_sha256=scoped_input.sha256,
        ),
    )
    context = AgentRunScopeContext(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_sha256=AUTHORITY_A,
        actor_id=f"runtime-{tag}",
        scope_as_of=started_at,
        evidence_refs=evidence_refs,
    )
    envelope = RuntimeAuditEnvelope(
        run_id=run_id,
        trace_id=sha(f"trace:{tag}")[:32],
        root_span_id=sha(f"span:{tag}")[:16],
        scope=context,
        task_type="team_agent_evaluation",
        registry_sha256=sha(f"registry:{tag}"),
        contract_version="1.0.0",
        prompt_version="hash-only-v1",
        schema_version="1.0.0",
        routing_policy_version="proposal-only-v1",
        prompt_sha256=sha(f"prompt:{tag}"),
        output_schema_sha256=sha(f"schema:{tag}"),
        tool_contract_sha256=sha(f"tool:{tag}"),
        idempotency_key=f"runtime-{tag}",
        request_sha256=sha(f"request:{tag}"),
        input_sha256=sha(f"input:{tag}"),
        input_field_names=(),
        input_bytes=0,
        evidence_snapshot_sha256=_digest(
            [(scoped_input.id, scoped_input.sha256)]
        ),
        required_capabilities=(),
        allowed_tools=(),
        max_cost_usd=Decimal("1"),
        max_latency_ms=10_000,
        max_attempts=1,
        started_at=started_at,
    )
    preparation = service.agent_runs.prepare(envelope)
    if preparation.disposition == "new":
        for event in (
            RuntimeAuditEvent(event_type="route_selected", occurred_at=started_at),
            RuntimeAuditEvent(event_type="attempt_started", occurred_at=started_at),
            RuntimeAuditEvent(
                event_type="attempt_completed",
                output_sha256=sha(f"output:{tag}"),
                occurred_at=started_at,
            ),
            RuntimeAuditEvent(
                event_type="eval_completed",
                eval_sha256=sha(f"eval:{tag}"),
                occurred_at=started_at,
            ),
            RuntimeAuditEvent(event_type="run_succeeded", occurred_at=started_at),
        ):
            service.agent_runs.append(run_id=run_id, event=event)
    detail = service.agent_runs.get_run(
        context=AgentRunScopeContext(
            tenant_ref="tenant-a",
            entity_ref="entity-a",
            store_ref="store-a",
            authority_sha256=AUTHORITY_A,
            actor_id="team-agent-test-verifier",
            scope_as_of=NOW,
            evidence_refs=(),
        ),
        run_id=run_id,
    )
    return run_id, _digest(detail)


def base_attestations(service, contract):
    runtime = runtime_sha(contract)
    run_ref, run_receipt_sha256 = governed_run(service, "candidate-v1")
    run = attestation(
        service,
        "run-reviewer",
        "agent_run",
        {
            "agent_run_ref": run_ref,
            "runtime_sha256": runtime,
            "snapshot_sha256": run_receipt_sha256,
            "zero_external_writes": True,
        },
    )
    eval_set = attestation(
        service,
        "eval-reviewer",
        "eval_set",
        {
            "eval_set_sha256": contract["eval_set_sha256"],
            "snapshot_sha256": sha("eval-set-snapshot"),
        },
    )
    rollback = attestation(
        service,
        "rollback-reviewer",
        "rollback",
        {
            "rollback_target_ref": "rollback-base",
            "rollback_version": "v0",
            "rollback_target_content_sha256": ZERO_SHA256,
            "rollback_target_runtime_sha256": ZERO_SHA256,
            "rollback_artifact_sha256": contract["rollback_artifact_sha256"],
            "snapshot_sha256": sha("rollback-snapshot"),
        },
    )
    return run, eval_set, rollback


def create_candidate(service, *, idempotency_key: str = "candidate-1"):
    contract = candidate_contract(service)
    evidence = base_attestations(service, contract)
    result = service.create_candidate(
        principal=principal("author-a", "operator"),
        store_ref="store-a",
        as_of=NOW,
        human_owner_actor_id="owner-a",
        skill_id="listing-quality",
        skill_version="1.0.0",
        learning_input_type="verified_failure",
        evidence_ids=[item.id for item in evidence],
        idempotency_key=idempotency_key,
        **contract,
    )
    return result, contract, evidence


def create_cross_candidate(service, suffix: str):
    contract = candidate_contract(service)
    base = base_attestations(service, contract)
    subject_sha256 = sha(f"cross-subject:{suffix}")
    hashes = {
        "license": sha(f"license:{suffix}"),
        "deidentification": sha(f"deidentification:{suffix}"),
        "revocation": sha(f"revocation:{suffix}"),
    }
    license_evidence = attestation(
        service,
        f"license-signer-{suffix}",
        "license",
        {
            "license_sha256": hashes["license"],
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 1,
            "current": True,
            "snapshot_sha256": sha(f"license-snapshot:{suffix}:1"),
        },
    )
    deidentification_evidence = attestation(
        service,
        f"deidentification-signer-{suffix}",
        "deidentification",
        {
            "deidentification_sha256": hashes["deidentification"],
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 1,
            "current": True,
            "nonreversible": True,
            "snapshot_sha256": sha(f"deidentification-snapshot:{suffix}:1"),
        },
    )
    revocation_evidence = attestation(
        service,
        f"revocation-signer-{suffix}",
        "revocation",
        {
            "revocation_contract_sha256": hashes["revocation"],
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 1,
            "current": True,
            "revoked": False,
            "snapshot_sha256": sha(f"revocation-snapshot:{suffix}:1"),
        },
    )
    cross_evidence = (
        *base,
        license_evidence,
        deidentification_evidence,
        revocation_evidence,
    )
    request = {
        "principal": principal("author-a", "operator"),
        "store_ref": "store-a",
        "as_of": NOW,
        "human_owner_actor_id": "owner-a",
        "skill_id": f"cross-{suffix}",
        "skill_version": "1.0.0",
        "learning_input_type": "verified_failure",
        "evidence_ids": [item.id for item in cross_evidence],
        "idempotency_key": f"cross-{suffix}",
        "cross_tenant_mode": "licensed_deidentified_nonreversible",
        "license_sha256": hashes["license"],
        "deidentification_sha256": hashes["deidentification"],
        "revocation_contract_sha256": hashes["revocation"],
        **contract,
    }
    created = service.create_candidate(**request)
    return created, contract, base, cross_evidence, subject_sha256, hashes, request


def insert_new_revocation_epoch(
    engine,
    service,
    *,
    suffix: str,
    subject_sha256: str,
    revocation_sha256: str,
):
    newest = attestation(
        service,
        f"revocation-new-signer-{suffix}",
        "revocation",
        {
            "revocation_contract_sha256": revocation_sha256,
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 2,
            "current": True,
            "revoked": True,
            "snapshot_sha256": sha(f"revocation-snapshot:{suffix}:2"),
        },
    )
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, newest.id)
        row.recorded_at = NOW + timedelta(seconds=1)
    service.clock = lambda: NOW + timedelta(seconds=2)


def baseline_claims(service, contract):
    runtime = runtime_sha(contract)
    baseline_run_ref, baseline_run_sha256 = governed_run(service, "baseline-v1")
    candidate_run_ref, candidate_run_sha256 = governed_run(service, "candidate-v1")
    return {
        "baseline_agent_run_ref": baseline_run_ref,
        "baseline_agent_run_sha256": baseline_run_sha256,
        "baseline_runtime_ref": "runtime-baseline-v1",
        "baseline_runtime_sha256": sha("baseline-runtime"),
        "candidate_agent_run_ref": candidate_run_ref,
        "candidate_agent_run_sha256": candidate_run_sha256,
        "candidate_runtime_ref": "runtime-candidate-v1",
        "candidate_runtime_sha256": runtime,
        "baseline_snapshot_sha256": sha("baseline-snapshot"),
        "candidate_snapshot_sha256": sha("candidate-snapshot"),
        "eval_baseline_passed": True,
        "negative_tests_passed": True,
        "scope_tests_passed": True,
    }


def shadow_claims(service, contract):
    run_ref, run_receipt_sha256 = governed_run(service, "candidate-v1")
    return {
        "agent_run_ref": run_ref,
        "runtime_sha256": runtime_sha(contract),
        "snapshot_sha256": run_receipt_sha256,
        "shadow_passed": True,
        "zero_external_writes": True,
        "cost_usd": "0.25",
        "latency_ms": "12.5",
        "token_count": 32,
    }


def transition(service, candidate_ref, actor, roles, previous, target, evidence, key, **gates):
    return service.transition(
        principal=principal(actor, *roles),
        store_ref="store-a",
        candidate_ref=candidate_ref,
        as_of=NOW,
        expected_previous_state=previous,
        to_state=target,
        reason_code=f"to_{target}",
        evidence_ids=[item.id for item in evidence],
        idempotency_key=key,
        **gates,
    )


def test_candidate_is_append_only_idempotent_and_exact_scope(workspace):
    engine, _, grants, service = workspace
    created, _, _ = create_candidate(service)
    replay, _, _ = create_candidate(service)

    assert replay == created
    assert created["state"] == "skill_candidate"
    assert created["runtime_activation_performed"] is False
    assert created["formal_fact_created"] is False
    assert created["external_write_performed"] is False
    assert {item["purpose"] for item in created["events"][0]["source_evidence"]} == {
        "agent_run",
        "eval_set",
        "rollback",
    }
    with Session(engine) as session:
        assert len(session.scalars(select(TeamAgentEvolutionCandidateRow)).all()) == 1
        assert len(session.scalars(select(TeamAgentEvolutionEventRow)).all()) == 1
        assert len(session.scalars(select(TeamAgentEvolutionEvidenceLinkRow)).all()) == 4

    grants.authority = "b" * 64
    with pytest.raises(KeyError):
        service.get_candidate(
            principal=principal("author-a", "operator"),
            store_ref="store-a",
            candidate_ref=created["candidate_ref"],
            as_of=NOW,
        )
    assert service.list_candidates(
        principal=principal("author-a", "operator"),
        store_ref="store-a",
        as_of=NOW,
    )["status"] == "no_data"


def test_idempotency_drift_and_numeric_fail_closed(workspace):
    _, _, _, service = workspace
    created, contract, base = create_candidate(service)
    with pytest.raises(TeamAgentEvolutionConflictError):
        service.create_candidate(
            principal=principal("author-a", "operator"),
            store_ref="store-a",
            as_of=NOW,
            human_owner_actor_id="owner-a",
            skill_id="different-skill",
            skill_version="1.0.0",
            learning_input_type="verified_failure",
            evidence_ids=[item.id for item in base],
            idempotency_key="candidate-1",
            **contract,
        )
    with pytest.raises(TeamAgentEvolutionError, match="finite"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("reviewer",),
            "skill_candidate",
            "evaluation",
            base,
            "eval-nan",
            cost_usd=float("nan"),
        )


def test_authority_rotation_between_preflight_and_transaction_fails_closed(
    workspace,
):
    engine, _, grants, service = workspace
    contract = candidate_contract(service)
    evidence = base_attestations(service, contract)
    grants.rotate_on_call = grants.calls + 2
    with pytest.raises(PermissionError, match="changed before commit"):
        service.create_candidate(
            principal=principal("author-a", "operator"),
            store_ref="store-a",
            as_of=NOW,
            human_owner_actor_id="owner-a",
            skill_id="authority-race",
            skill_version="1.0.0",
            learning_input_type="verified_failure",
            evidence_ids=[item.id for item in evidence],
            idempotency_key="authority-race",
            **contract,
        )
    with Session(engine) as session:
        assert session.scalar(select(TeamAgentEvolutionCandidateRow)) is None


def test_idempotency_winner_replay_relocks_and_revalidates_authority(
    workspace, monkeypatch
):
    _, _, grants, service = workspace
    create_candidate(service)

    def lose_concurrent_race(**_kwargs):
        grants.authority = "b" * 64
        raise IntegrityError("concurrent winner", {}, RuntimeError("race"))

    monkeypatch.setattr(service, "_create", lose_concurrent_race)
    with pytest.raises(PermissionError, match="authority changed"):
        create_candidate(service)


def test_transition_winner_replay_relocks_and_revalidates_authority(
    workspace, monkeypatch
):
    _, _, grants, service = workspace
    created, contract, base = create_candidate(service)
    baseline = attestation(
        service,
        "baseline-reviewer",
        "baseline",
        baseline_claims(service, contract),
    )
    run, eval_set, _ = base

    def lose_concurrent_race(**_kwargs):
        grants.authority = "b" * 64
        raise IntegrityError("concurrent winner", {}, RuntimeError("race"))

    monkeypatch.setattr(service, "_transition", lose_concurrent_race)
    with pytest.raises(PermissionError, match="authority changed"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("monitor",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, baseline),
            "transition-authority-race",
        )


def test_candidate_winner_replay_uses_refreshed_time_for_revocation(
    workspace, monkeypatch
):
    engine, _, _, service = workspace
    suffix = "candidate-winner-revocation"
    _, _, _, _, subject, hashes, request = create_cross_candidate(service, suffix)

    def lose_concurrent_race(**_kwargs):
        insert_new_revocation_epoch(
            engine,
            service,
            suffix=suffix,
            subject_sha256=subject,
            revocation_sha256=hashes["revocation"],
        )
        raise IntegrityError("concurrent winner", {}, RuntimeError("race"))

    monkeypatch.setattr(service, "_create", lose_concurrent_race)
    with pytest.raises(TeamAgentEvolutionError, match="latest epoch"):
        service.create_candidate(**request)


def test_event_winner_replay_uses_refreshed_time_for_revocation(
    workspace, monkeypatch
):
    engine, _, _, service = workspace
    suffix = "event-winner-revocation"
    created, contract, base, cross, subject, hashes, _ = create_cross_candidate(
        service, suffix
    )
    baseline = attestation(
        service,
        "baseline-reviewer",
        "baseline",
        baseline_claims(service, contract),
    )
    run, eval_set, _ = base
    support = (run, eval_set, baseline, *cross[-3:])
    transition(
        service,
        created["candidate_ref"],
        "evaluator-a",
        ("monitor",),
        "skill_candidate",
        "evaluation",
        support,
        "cross-evaluation-winner",
    )

    def lose_concurrent_race(**_kwargs):
        insert_new_revocation_epoch(
            engine,
            service,
            suffix=suffix,
            subject_sha256=subject,
            revocation_sha256=hashes["revocation"],
        )
        raise IntegrityError("concurrent winner", {}, RuntimeError("race"))

    monkeypatch.setattr(service, "_transition", lose_concurrent_race)
    with pytest.raises(TeamAgentEvolutionError, match="latest epoch"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("monitor",),
            "skill_candidate",
            "evaluation",
            support,
            "cross-evaluation-winner",
        )


def test_full_eval_shadow_review_promotion_active_and_replay(workspace):
    _, _, _, service = workspace
    created, contract, base = create_candidate(service)
    candidate_ref = created["candidate_ref"]
    baseline = attestation(
        service, "baseline-reviewer", "baseline", baseline_claims(service, contract)
    )
    shadow = attestation(
        service, "shadow-reviewer", "shadow", shadow_claims(service, contract)
    )
    review = attestation(
        service,
        "reviewer-a",
        "review",
        {"review_verdict": "approved", "snapshot_sha256": sha("review-snapshot")},
    )
    mismatched_review = attestation(
        service,
        "independent-reviewer",
        "review",
        {"review_verdict": "approved", "snapshot_sha256": sha("wrong-reviewer")},
    )
    risk = attestation(
        service,
        "risk-actor",
        "risk_authority",
        {
            "risk_authority_sha256": sha("risk-authority"),
            "current": True,
            "snapshot_sha256": sha("risk-snapshot"),
        },
    )
    prior_actor_risk = attestation(
        service,
        "evaluator-a",
        "risk_authority",
        {
            "risk_authority_sha256": sha("risk-authority"),
            "current": True,
            "snapshot_sha256": sha("risk-prior-actor-snapshot"),
        },
    )
    run, eval_set, _ = base
    transition(
        service,
        candidate_ref,
        "evaluator-a",
        ("monitor",),
        "skill_candidate",
        "evaluation",
        (run, eval_set, baseline),
        "evaluation-1",
    )
    transition(
        service,
        candidate_ref,
        "shadow-a",
        ("reviewer",),
        "evaluation",
        "shadow",
        (run, baseline, shadow),
        "shadow-1",
        eval_baseline_passed=True,
        negative_tests_passed=True,
        scope_tests_passed=True,
    )
    with pytest.raises(TeamAgentEvolutionError, match="shadow/review"):
        transition(
            service,
            candidate_ref,
            "reviewer-a",
            ("reviewer",),
            "shadow",
            "independent_review",
            (mismatched_review, shadow),
            "review-wrong-signer",
            shadow_passed=True,
        )
    transition(
        service,
        candidate_ref,
        "reviewer-a",
        ("reviewer",),
        "shadow",
        "independent_review",
        (review, shadow),
        "review-1",
        shadow_passed=True,
    )
    with pytest.raises(PermissionError, match="Risk signer"):
        transition(
            service,
            candidate_ref,
            "promoter-a",
            ("approver",),
            "independent_review",
            "promoted",
            (baseline, shadow, review, prior_actor_risk),
            "promote-prior-risk-actor",
        )
    transition(
        service,
        candidate_ref,
        "promoter-a",
        ("approver",),
        "independent_review",
        "promoted",
        (baseline, shadow, review, risk),
        "promote-1",
    )
    active = transition(
        service,
        candidate_ref,
        "owner-a",
        ("approver",),
        "promoted",
        "active",
        (baseline, shadow, review, risk),
        "active-1",
        risk_authority_sha256=sha("risk-authority"),
    )

    assert active["state"] == "active"
    assert [event["to_state"] for event in active["events"]] == [
        "skill_candidate",
        "evaluation",
        "shadow",
        "independent_review",
        "promoted",
        "active",
    ]
    assert active["events"][-1]["risk_actor_id"] == "risk-actor"
    replay = service.replay(
        principal=principal("owner-a", "approver"),
        store_ref="store-a",
        candidate_ref=candidate_ref,
        as_of=NOW,
    )
    assert replay["network_invoked"] is False
    assert replay["runtime_activation_performed"] is False


def test_sod_and_evidence_tamper_fail_before_transition(workspace):
    engine, _, _, service = workspace
    created, contract, base = create_candidate(service)
    baseline = attestation(
        service, "baseline-reviewer", "baseline", baseline_claims(service, contract)
    )
    run, eval_set, _ = base
    author_signed_baseline = TeamAgentEvidenceAuthorityAdapter(
        service.evidence
    ).capture(
        principal=principal("author-a", "reviewer"),
        purpose="baseline",
        claims=baseline_claims(service, contract),
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        scope_authority_sha256=AUTHORITY_A,
        candidate_author_actor_id="decoy-author",
        human_owner_actor_id="decoy-owner",
        effective_at=NOW.isoformat(),
        effective_until=(NOW + timedelta(days=30)).isoformat(),
    )
    with pytest.raises(PermissionError, match="authority signer"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("reviewer",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, author_signed_baseline),
            "author-signed-baseline",
        )
    with pytest.raises(PermissionError):
        transition(
            service,
            created["candidate_ref"],
            "author-a",
            ("reviewer",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, baseline),
            "self-eval",
        )
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, baseline.id)
        blob = session.get(EvidenceBlobRow, row.blob_sha256)
        blob.content_bytes = b"tampered"
    with pytest.raises(TeamAgentEvolutionError, match="integrity"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("reviewer",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, baseline),
            "tampered-eval",
        )


def test_agent_run_receipt_missing_or_hash_chain_drift_blocks_transition(workspace):
    engine, _, _, service = workspace
    created, contract, base = create_candidate(service)
    baseline = attestation(
        service, "baseline-reviewer", "baseline", baseline_claims(service, contract)
    )
    _, eval_set, _ = base
    missing_run = attestation(
        service,
        "missing-run-reviewer",
        "agent_run",
        {
            "agent_run_ref": "missing-agent-run",
            "runtime_sha256": runtime_sha(contract),
            "snapshot_sha256": sha("missing-agent-run-receipt"),
            "zero_external_writes": True,
        },
    )
    with pytest.raises(TeamAgentEvolutionError, match="AgentRun receipt"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("reviewer",),
            "skill_candidate",
            "evaluation",
            (missing_run, eval_set, baseline),
            "missing-run-eval",
        )

    run, _, _ = base
    with Session(engine) as session, session.begin():
        event = session.scalar(
            select(AgentRuntimeRunEventRow).where(
                AgentRuntimeRunEventRow.run_id == run.metadata["agent_run_ref"]
            )
        )
        event.event_sha256 = "f" * 64
    with pytest.raises(TeamAgentEvolutionError, match="AgentRun receipt"):
        transition(
            service,
            created["candidate_ref"],
            "evaluator-a",
            ("reviewer",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, baseline),
            "drifted-run-eval",
        )


def test_graph_projection_is_observation_only_and_never_a_gate(workspace):
    _, _, _, service = workspace
    created, _, _ = create_candidate(service)
    graph = attestation(
        service,
        "graph-reviewer",
        "graph_observation",
        {
            "graph_snapshot_sha256": sha("graph-snapshot"),
            "graph_type": "FailurePattern",
            "graph_version": "1.0.0",
            "effective_from": (NOW - timedelta(days=1)).isoformat(),
            "effective_until": (NOW + timedelta(days=1)).isoformat(),
            "observation_only": True,
            "gate_eligible": False,
        },
    )
    projection = service.graph_observation(
        principal=principal("operator-a", "operator"),
        store_ref="store-a",
        candidate_ref=created["candidate_ref"],
        as_of=NOW,
    )
    assert {item["status"] for item in projection["nodes"]} == {"observation"}
    assert {item["status"] for item in projection["edges"]} == {"observation"}
    assert projection["graph_write_performed"] is False
    assert graph.id not in {
        item["evidence_id"]
        for event in created["events"]
        for item in event.get("source_evidence", [])
        if "evidence_id" in item
    }


def test_cross_tenant_requires_license_deidentification_and_revocation(workspace):
    _, _, _, service = workspace
    contract = candidate_contract(service)
    base = base_attestations(service, contract)
    with pytest.raises(TeamAgentEvolutionError, match="deidentification"):
        service.create_candidate(
            principal=principal("author-a", "operator"),
            store_ref="store-a",
            as_of=NOW,
            human_owner_actor_id="owner-a",
            skill_id="cross-pattern",
            skill_version="1.0.0",
            learning_input_type="verified_failure",
            evidence_ids=[item.id for item in base],
            idempotency_key="cross-missing",
            cross_tenant_mode="licensed_deidentified_nonreversible",
            license_sha256=sha("license"),
            deidentification_sha256=sha("deidentification"),
            revocation_contract_sha256=sha("revocation"),
            **contract,
        )
    assert ZERO_SHA256 not in {
        sha("license"), sha("deidentification"), sha("revocation")
    }


def test_cross_tenant_authority_requires_latest_unrevoked_equal_epoch(workspace):
    _, _, _, service = workspace
    contract = candidate_contract(service)
    base = base_attestations(service, contract)
    subject_sha256 = sha("licensed-pattern-subject")
    license_hash = sha("license-v1")
    deidentification_hash = sha("deidentification-v1")
    revocation_hash = sha("revocation-v1")
    license_evidence = attestation(
        service,
        "license-signer",
        "license",
        {
            "license_sha256": license_hash,
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 1,
            "current": True,
            "snapshot_sha256": sha("license-snapshot-v1"),
        },
    )
    deidentification_evidence = attestation(
        service,
        "deidentification-signer",
        "deidentification",
        {
            "deidentification_sha256": deidentification_hash,
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 1,
            "current": True,
            "nonreversible": True,
            "snapshot_sha256": sha("deidentification-snapshot-v1"),
        },
    )
    revocation_evidence = attestation(
        service,
        "revocation-signer",
        "revocation",
        {
            "revocation_contract_sha256": revocation_hash,
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 1,
            "current": True,
            "revoked": False,
            "snapshot_sha256": sha("revocation-snapshot-v1"),
        },
    )
    cross_evidence = (
        *base,
        license_evidence,
        deidentification_evidence,
        revocation_evidence,
    )
    created = service.create_candidate(
        principal=principal("author-a", "operator"),
        store_ref="store-a",
        as_of=NOW,
        human_owner_actor_id="owner-a",
        skill_id="cross-pattern-v1",
        skill_version="1.0.0",
        learning_input_type="verified_failure",
        evidence_ids=[item.id for item in cross_evidence],
        idempotency_key="cross-current-v1",
        cross_tenant_mode="licensed_deidentified_nonreversible",
        license_sha256=license_hash,
        deidentification_sha256=deidentification_hash,
        revocation_contract_sha256=revocation_hash,
        **contract,
    )
    assert created["state"] == "skill_candidate"

    attestation(
        service,
        "revocation-signer",
        "revocation",
        {
            "revocation_contract_sha256": revocation_hash,
            "authority_subject_sha256": subject_sha256,
            "authority_epoch": 2,
            "current": True,
            "revoked": True,
            "snapshot_sha256": sha("revocation-snapshot-v2"),
        },
    )
    with pytest.raises(TeamAgentEvolutionError, match="latest epoch"):
        service.get_candidate(
            principal=principal("author-a", "operator"),
            store_ref="store-a",
            candidate_ref=created["candidate_ref"],
            as_of=NOW,
        )
    with pytest.raises(TeamAgentEvolutionError, match="latest epoch"):
        service.create_candidate(
            principal=principal("author-a", "operator"),
            store_ref="store-a",
            as_of=NOW,
            human_owner_actor_id="owner-a",
            skill_id="cross-pattern-v2",
            skill_version="1.0.0",
            learning_input_type="verified_failure",
            evidence_ids=[item.id for item in cross_evidence],
            idempotency_key="cross-replayed-v1",
            cross_tenant_mode="licensed_deidentified_nonreversible",
            license_sha256=license_hash,
            deidentification_sha256=deidentification_hash,
            revocation_contract_sha256=revocation_hash,
            **contract,
        )


def test_generic_evidence_capture_cannot_mint_reserved_team_agent_authority(
    workspace,
):
    _, evidence, _, _ = workspace
    with pytest.raises(ValueError, match="dedicated authority adapter"):
        evidence.capture(
            content=b'{"review_verdict":"approved"}',
            filename="forged-review.json",
            content_type="application/json",
            source="team-agent-review-authority",
            source_ref="team-agent-review-authority://forged-review",
            grade=EvidenceGrade.A,
            effective_at=NOW.isoformat(),
            effective_until=None,
            created_by="candidate-author",
            metadata={
                "source_contract_id": "kjds-team-agent-review-authority-v1",
                "retention_class": "security",
                "legal_hold": False,
            },
        )

    with pytest.raises(PermissionError, match="differ from author and owner"):
        TeamAgentEvidenceAuthorityAdapter(evidence).capture(
            principal=principal("author-a", "risk"),
            purpose="risk_authority",
            claims={
                "risk_authority_sha256": sha("forged-risk"),
                "current": True,
                "snapshot_sha256": sha("forged-risk-snapshot"),
            },
            tenant_ref="tenant-a",
            entity_ref="entity-a",
            store_ref="store-a",
            scope_authority_sha256=AUTHORITY_A,
            candidate_author_actor_id="author-a",
            human_owner_actor_id="owner-a",
            effective_at=NOW.isoformat(),
            effective_until=None,
        )


def test_team_agent_module_import_keeps_sqlalchemy_metadata_closed() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = """
import sys
from sqlalchemy import create_engine
from apps.control_plane.sql_repository import Base
from apps.control_plane import evidence  # noqa: F401
before = set(Base.metadata.tables)
assert 'apps.control_plane.agent_runtime' not in sys.modules
assert 'apps.control_plane.agent_runtime_evidence' not in sys.modules
from apps.control_plane import team_agent_evolution  # noqa: F401
after = set(Base.metadata.tables)
assert after - before == {
    'kill_switch_events',
    'team_agent_evolution_candidates',
    'team_agent_evolution_events',
    'team_agent_evolution_evidence_links',
}
assert 'apps.control_plane.agent_runtime' not in sys.modules
assert 'apps.control_plane.agent_runtime_evidence' not in sys.modules
engine = create_engine('sqlite://')
Base.metadata.create_all(engine)
assert 'agent_runtime_run_envelopes' not in Base.metadata.tables
assert 'agent_runtime_run_events' not in Base.metadata.tables
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
