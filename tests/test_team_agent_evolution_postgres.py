from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.control_plane.agent_runtime import (
    AgentRunEvidenceRef,
    AgentRunScopeContext,
    RuntimeAuditEnvelope,
    RuntimeAuditEvent,
)
from apps.control_plane.evidence import (
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
    TeamAgentEvolutionEventRow,
    TeamAgentEvolutionEvidenceLinkRow,
    _digest,
    _event_digest,
)

DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL contract tests require KJDS_DATABASE_URL",
)

CANDIDATES = "team_agent_evolution_candidates"
EVENTS = "team_agent_evolution_events"
EVIDENCE_LINKS = "team_agent_evolution_evidence_links"
TABLES = (CANDIDATES, EVENTS, EVIDENCE_LINKS)
NOW = datetime.now(UTC) + timedelta(days=1)
AUTHORITY_A = "a" * 64


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def stable_ref(prefix: str, value: str) -> str:
    return f"{prefix}_{sha(value)[:32]}"


def migration_config(engine: Engine) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def reflected(connection: Connection, table_name: str) -> Table:
    return Table(table_name, MetaData(), autoload_with=connection)


class FakeScopeGrants:
    def __init__(self) -> None:
        self.authority = AUTHORITY_A
        self.status = "ready"
        self.entity_ref = "entity-a"

    def current(self, *, principal, store_ref, as_of):
        del as_of
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


@pytest.fixture(scope="module")
def engine() -> Engine:
    schema = f"bas177_pg_{uuid4().hex}"
    admin = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    target = create_engine(
        url.set(query=query),
        pool_pre_ping=True,
        pool_size=32,
        max_overflow=32,
    )
    original_database_url = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = target.url.render_as_string(
        hide_password=False
    ).replace("%", "%%")
    config = migration_config(target)
    try:
        command.upgrade(config, "20260803_0093")
        command.upgrade(config, "20260803_0094")
        command.downgrade(config, "20260803_0093")
        assert not set(TABLES).intersection(inspect(target).get_table_names())
        command.upgrade(config, "20260803_0094")
        yield target
    finally:
        if original_database_url is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = original_database_url
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def workspace(engine: Engine):
    grants = FakeScopeGrants()
    service = GovernedTeamAgentEvolutionWorkspace(
        engine=engine,
        evidence=EvidenceService(engine),
        scope_grants=grants,
        clock=lambda: NOW,
    )
    return grants, service


def candidate_contract(
    service: GovernedTeamAgentEvolutionWorkspace, tag: str
) -> dict[str, str]:
    return {
        "agent_role_version_sha256": sha(f"role:{tag}"),
        "skill_contract_sha256": sha(f"skill:{tag}"),
        "eval_set_sha256": service.eval_set.sha256,
        "model_profile_sha256": sha(f"model:{tag}"),
        "tool_contract_sha256": sha(f"tools:{tag}"),
        "policy_version_sha256": sha(f"policy:{tag}"),
        "rollback_artifact_sha256": sha(f"rollback:{tag}"),
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


def attestation(
    service: GovernedTeamAgentEvolutionWorkspace,
    tag: str,
    actor_id: str,
    purpose: str,
    claims: dict,
):
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
        "retirement": "retirement_sha256",
    }[purpose]
    authority = SUPPORT_EVIDENCE_CONTRACTS[purpose]
    payload_sha256 = claims[payload_field]
    source_ref = f"{authority.source}://{sha(f'{purpose}:{tag}:{actor_id}:{payload_sha256}')}"
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
            candidate_author_actor_id=f"author-{tag}",
            human_owner_actor_id=f"owner-{tag}",
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


def governed_run(
    service: GovernedTeamAgentEvolutionWorkspace, tag: str
) -> tuple[str, str]:
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
    preparation = service.agent_runs.prepare(
        RuntimeAuditEnvelope(
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
    )
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


def base_attestations(
    service: GovernedTeamAgentEvolutionWorkspace,
    tag: str,
    contract: dict[str, str],
):
    runtime = runtime_sha(contract)
    run_ref, run_receipt_sha256 = governed_run(service, f"candidate-{tag}")
    run = attestation(
        service,
        tag,
        f"run-reviewer-{tag}",
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
        tag,
        f"eval-reviewer-{tag}",
        "eval_set",
        {
            "eval_set_sha256": contract["eval_set_sha256"],
            "snapshot_sha256": sha(f"eval-set-snapshot:{tag}"),
        },
    )
    rollback = attestation(
        service,
        tag,
        f"rollback-reviewer-{tag}",
        "rollback",
        {
            "rollback_target_ref": f"rollback-{tag}",
            "rollback_version": "v0",
            "rollback_target_content_sha256": ZERO_SHA256,
            "rollback_target_runtime_sha256": ZERO_SHA256,
            "rollback_artifact_sha256": contract["rollback_artifact_sha256"],
            "snapshot_sha256": sha(f"rollback-snapshot:{tag}"),
        },
    )
    return run, eval_set, rollback


def create_candidate(
    service: GovernedTeamAgentEvolutionWorkspace,
    tag: str,
    *,
    contract: dict[str, str] | None = None,
    evidence=(),
    idempotency_key: str | None = None,
    skill_id: str | None = None,
    skill_version: str = "1.0.0",
    cross_tenant_mode: str = "same_tenant",
    license_sha256: str = ZERO_SHA256,
    deidentification_sha256: str = ZERO_SHA256,
    revocation_contract_sha256: str = ZERO_SHA256,
    predecessor_candidate_ref: str | None = None,
    supersedes_sha256: str = ZERO_SHA256,
):
    selected_contract = contract or candidate_contract(service, tag)
    selected_evidence = tuple(evidence) or base_attestations(
        service, tag, selected_contract
    )
    result = service.create_candidate(
        principal=principal(f"author-{tag}", "operator"),
        store_ref="store-a",
        as_of=NOW,
        human_owner_actor_id=f"owner-{tag}",
        skill_id=skill_id or f"skill-{tag}",
        skill_version=skill_version,
        learning_input_type="verified_failure",
        cross_tenant_mode=cross_tenant_mode,
        license_sha256=license_sha256,
        deidentification_sha256=deidentification_sha256,
        revocation_contract_sha256=revocation_contract_sha256,
        predecessor_candidate_ref=predecessor_candidate_ref,
        supersedes_sha256=supersedes_sha256,
        evidence_ids=[item.id for item in selected_evidence],
        idempotency_key=idempotency_key or f"candidate-{tag}",
        **selected_contract,
    )
    return result, selected_contract, selected_evidence


def baseline_claims(
    service: GovernedTeamAgentEvolutionWorkspace,
    tag: str,
    contract: dict[str, str],
) -> dict:
    baseline_run_ref, baseline_run_sha256 = governed_run(
        service, f"baseline-{tag}"
    )
    candidate_run_ref, candidate_run_sha256 = governed_run(
        service, f"candidate-{tag}"
    )
    return {
        "baseline_agent_run_ref": baseline_run_ref,
        "baseline_agent_run_sha256": baseline_run_sha256,
        "baseline_runtime_ref": f"runtime-baseline-{tag}",
        "baseline_runtime_sha256": sha(f"baseline-runtime:{tag}"),
        "candidate_agent_run_ref": candidate_run_ref,
        "candidate_agent_run_sha256": candidate_run_sha256,
        "candidate_runtime_ref": f"runtime-candidate-{tag}",
        "candidate_runtime_sha256": runtime_sha(contract),
        "baseline_snapshot_sha256": sha(f"baseline-snapshot:{tag}"),
        "candidate_snapshot_sha256": sha(f"candidate-snapshot:{tag}"),
        "eval_baseline_passed": True,
        "negative_tests_passed": True,
        "scope_tests_passed": True,
    }


def transition(
    service: GovernedTeamAgentEvolutionWorkspace,
    candidate_ref: str,
    tag: str,
    actor: str,
    roles: tuple[str, ...],
    previous: str,
    target: str,
    evidence,
    **gates,
):
    return service.transition(
        principal=principal(actor, *roles),
        store_ref="store-a",
        candidate_ref=candidate_ref,
        as_of=NOW,
        expected_previous_state=previous,
        to_state=target,
        reason_code=f"to_{target}",
        evidence_ids=[item.id for item in evidence],
        idempotency_key=f"{target}-{tag}",
        **gates,
    )


def activate_candidate(
    service: GovernedTeamAgentEvolutionWorkspace,
    tag: str,
    *,
    skill_id: str | None = None,
    skill_version: str = "1.0.0",
) -> dict:
    created, contract, base = create_candidate(
        service,
        tag,
        skill_id=skill_id,
        skill_version=skill_version,
    )
    candidate_ref = created["candidate_ref"]
    baseline = attestation(
        service,
        tag,
        f"baseline-reviewer-{tag}",
        "baseline",
        baseline_claims(service, tag, contract),
    )
    candidate_run_ref, candidate_run_sha256 = governed_run(
        service, f"candidate-{tag}"
    )
    shadow = attestation(
        service,
        tag,
        f"shadow-reviewer-{tag}",
        "shadow",
        {
            "agent_run_ref": candidate_run_ref,
            "runtime_sha256": runtime_sha(contract),
            "snapshot_sha256": candidate_run_sha256,
            "shadow_passed": True,
            "zero_external_writes": True,
            "cost_usd": "0.25",
            "latency_ms": "12.5",
            "token_count": 32,
        },
    )
    review = attestation(
        service,
        tag,
        f"reviewer-{tag}",
        "review",
        {
            "review_verdict": "approved",
            "snapshot_sha256": sha(f"review-snapshot:{tag}"),
        },
    )
    risk = attestation(
        service,
        tag,
        f"risk-{tag}",
        "risk_authority",
        {
            "risk_authority_sha256": sha(f"risk-authority:{tag}"),
            "current": True,
            "snapshot_sha256": sha(f"risk-snapshot:{tag}"),
        },
    )
    run, eval_set, _ = base
    transition(
        service,
        candidate_ref,
        tag,
        f"evaluator-{tag}",
        ("monitor",),
        "skill_candidate",
        "evaluation",
        (run, eval_set, baseline),
    )
    transition(
        service,
        candidate_ref,
        tag,
        f"shadow-{tag}",
        ("reviewer",),
        "evaluation",
        "shadow",
        (run, baseline, shadow),
        eval_baseline_passed=True,
        negative_tests_passed=True,
        scope_tests_passed=True,
    )
    transition(
        service,
        candidate_ref,
        tag,
        f"reviewer-{tag}",
        ("reviewer",),
        "shadow",
        "independent_review",
        (review, shadow),
        shadow_passed=True,
    )
    transition(
        service,
        candidate_ref,
        tag,
        f"promoter-{tag}",
        ("approver",),
        "independent_review",
        "promoted",
        (baseline, shadow, review, risk),
    )
    return transition(
        service,
        candidate_ref,
        tag,
        f"owner-{tag}",
        ("approver",),
        "promoted",
        "active",
        (baseline, shadow, review, risk),
        risk_authority_sha256=sha(f"risk-authority:{tag}"),
    )


def advance_candidate_to_shadow(
    service: GovernedTeamAgentEvolutionWorkspace,
    tag: str,
) -> tuple[str, dict[str, str], object, object]:
    created, contract, base = create_candidate(service, tag)
    candidate_ref = created["candidate_ref"]
    baseline = attestation(
        service,
        tag,
        f"baseline-reviewer-{tag}",
        "baseline",
        baseline_claims(service, tag, contract),
    )
    candidate_run_ref, candidate_run_sha256 = governed_run(
        service, f"candidate-{tag}"
    )
    shadow = attestation(
        service,
        tag,
        f"shadow-reviewer-{tag}",
        "shadow",
        {
            "agent_run_ref": candidate_run_ref,
            "runtime_sha256": runtime_sha(contract),
            "snapshot_sha256": candidate_run_sha256,
            "shadow_passed": True,
            "zero_external_writes": True,
            "cost_usd": "0.25",
            "latency_ms": "12.5",
            "token_count": 32,
        },
    )
    run, eval_set, _ = base
    transition(
        service,
        candidate_ref,
        tag,
        f"evaluator-{tag}",
        ("monitor",),
        "skill_candidate",
        "evaluation",
        (run, eval_set, baseline),
    )
    transition(
        service,
        candidate_ref,
        tag,
        f"shadow-{tag}",
        ("reviewer",),
        "evaluation",
        "shadow",
        (run, baseline, shadow),
        eval_baseline_passed=True,
        negative_tests_passed=True,
        scope_tests_passed=True,
    )
    return candidate_ref, contract, baseline, shadow


def candidate_rows(engine: Engine, candidate_ref: str):
    with Session(engine) as session:
        candidate = session.get(TeamAgentEvolutionCandidateRow, candidate_ref)
        events = list(
            session.scalars(
                select(TeamAgentEvolutionEventRow)
                .where(TeamAgentEvolutionEventRow.candidate_ref == candidate_ref)
                .order_by(TeamAgentEvolutionEventRow.ordinal)
            )
        )
        links = list(
            session.scalars(
                select(TeamAgentEvolutionEvidenceLinkRow)
                .where(
                    TeamAgentEvolutionEvidenceLinkRow.candidate_ref == candidate_ref
                )
                .order_by(
                    TeamAgentEvolutionEvidenceLinkRow.event_ref,
                    TeamAgentEvolutionEvidenceLinkRow.ordinal,
                )
            )
        )
        return candidate, events, links


def direct_evaluation_event(
    connection: Connection,
    candidate_ref: str,
    tag: str,
    *,
    actor_id: str,
) -> tuple[dict, int]:
    events = reflected(connection, EVENTS)
    previous = dict(
        connection.execute(
            select(events)
            .where(events.c.candidate_ref == candidate_ref)
            .order_by(events.c.ordinal.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )
    values = dict(previous)
    values.pop("insert_xid", None)
    values.update(
        {
            "event_ref": stable_ref("gtae", f"direct-eval:{tag}"),
            "ordinal": previous["ordinal"] + 1,
            "from_state": previous["to_state"],
            "to_state": "evaluation",
            "actor_id": actor_id,
            "actor_role": "evaluator",
            "risk_actor_id": None,
            "reason_code": "direct_evaluation",
            "eval_baseline_passed": False,
            "negative_tests_passed": False,
            "scope_tests_passed": False,
            "shadow_passed": False,
            "risk_authority_sha256": ZERO_SHA256,
            "review_verdict": "not_reviewed",
            "prev_event_sha256": previous["event_sha256"],
            "event_sha256": ZERO_SHA256,
            "request_sha256": sha(f"direct-request:{tag}"),
            "idempotency_sha256": sha(f"direct-idempotency:{tag}"),
            "occurred_at": NOW,
        }
    )
    values["event_sha256"] = _event_digest(
        GovernedTeamAgentEvolutionWorkspace._event_hash_payload(
            SimpleNamespace(**values)
        )
    )
    insert_xid = connection.execute(
        events.insert().values(**values).returning(events.c.insert_xid)
    ).scalar_one()
    return values, insert_xid


def test_schema_matches_orm_and_empty_replay(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(TABLES).issubset(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns(CANDIDATES)} == set(
        TeamAgentEvolutionCandidateRow.__table__.columns.keys()
    )
    assert {column["name"] for column in inspector.get_columns(EVENTS)} == set(
        TeamAgentEvolutionEventRow.__table__.columns.keys()
    )
    assert {
        column["name"] for column in inspector.get_columns(EVIDENCE_LINKS)
    } == set(TeamAgentEvolutionEvidenceLinkRow.__table__.columns.keys())
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version"))
            .scalar_one()
            == "20260803_0094"
        )
        triggers = set(
            connection.execute(
                text(
                    "SELECT tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE NOT t.tgisinternal AND c.relname = ANY(:tables)"
                ),
                {"tables": [*TABLES, "scope_grant_events", "evidence_records"]},
            ).scalars()
        )
    assert {
        "trg_gta_candidate_immutable",
        "trg_gta_event_immutable",
        "trg_gta_link_immutable",
        "trg_gta_event_append",
        "trg_gta_link_exact_evidence",
        "trg_gta_candidate_conservation",
        "trg_gta_event_conservation",
        "trg_gta_link_conservation",
        "trg_gta_scope_authority_write_lock",
        "trg_gta_authority_subject_write_lock",
        "trg_gta_evidence_immutable",
    } <= triggers
    evidence_indexes = {
        index["name"] for index in inspector.get_indexes("evidence_records")
    }
    assert {
        "uq_team_agent_evolution_evidence_source_ref",
        "uq_team_agent_authority_evidence_source_ref",
    } <= evidence_indexes


def test_service_lifecycle_is_atomic_exact_scope_and_observation_only(
    engine: Engine, workspace
) -> None:
    _, service = workspace
    tag = f"lifecycle-{uuid4().hex[:8]}"
    active = activate_candidate(service, tag)
    candidate_ref = active["candidate_ref"]
    candidate, events, links = candidate_rows(engine, candidate_ref)
    assert candidate is not None
    assert [event.to_state for event in events] == [
        "skill_candidate",
        "evaluation",
        "shadow",
        "independent_review",
        "promoted",
        "active",
    ]
    assert all(
        current.prev_event_sha256 == previous.event_sha256
        for previous, current in pairwise(events)
    )
    assert all(not event.external_write_observed for event in events)
    assert all(event.zero_external_writes for event in events)
    assert all(event.graph_observation_only for event in events)
    assert all(not event.graph_gate_eligible for event in events)
    assert len([link for link in links if link.purpose == "event_audit"]) == len(
        events
    )
    assert all(
        link.event_insert_xid
        == next(event.insert_xid for event in events if event.event_ref == link.event_ref)
        for link in links
    )
    replay = service.replay(
        principal=principal(f"owner-{tag}", "approver"),
        store_ref="store-a",
        candidate_ref=candidate_ref,
        as_of=NOW,
    )
    assert replay["state"] == "active"
    assert replay["network_invoked"] is False
    assert replay["runtime_activation_performed"] is False
    assert replay["external_write_performed"] is False


def test_evaluation_binding_replay_drift_scope_and_rollback_snapshot_contract(
    engine: Engine, workspace
) -> None:
    grants, service = workspace
    tag = f"binding-contract-{uuid4().hex[:8]}"
    created, contract, base = create_candidate(service, tag)
    candidate_ref = created["candidate_ref"]
    run, eval_set, _ = base
    baseline = attestation(
        service,
        tag,
        f"baseline-reviewer-{tag}",
        "baseline",
        baseline_claims(service, tag, contract),
    )
    first = transition(
        service,
        candidate_ref,
        tag,
        f"evaluator-{tag}",
        ("monitor",),
        "skill_candidate",
        "evaluation",
        (run, eval_set, baseline),
    )
    replayed = transition(
        service,
        candidate_ref,
        tag,
        f"evaluator-{tag}",
        ("monitor",),
        "skill_candidate",
        "evaluation",
        (run, eval_set, baseline),
    )
    assert replayed == first
    _, evaluation_events, _ = candidate_rows(engine, candidate_ref)
    assert len(evaluation_events) == 2
    assert evaluation_events[-1].baseline_runtime_ref == f"runtime-baseline-{tag}"

    drift_claims = baseline_claims(service, tag, contract)
    drift_claims["baseline_runtime_sha256"] = sha(f"baseline-drift:{tag}")
    drift_claims["baseline_snapshot_sha256"] = sha(f"baseline-snapshot-drift:{tag}")
    drift = attestation(
        service,
        f"{tag}-drift",
        f"baseline-drift-reviewer-{tag}",
        "baseline",
        drift_claims,
    )
    with pytest.raises(TeamAgentEvolutionConflictError):
        transition(
            service,
            candidate_ref,
            tag,
            f"evaluator-{tag}",
            ("monitor",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, drift),
        )

    grants.authority = "b" * 64
    with pytest.raises(KeyError):
        service.get_candidate(
            principal=principal(f"evaluator-{tag}", "monitor"),
            store_ref="store-a",
            candidate_ref=candidate_ref,
            as_of=NOW,
        )
    grants.authority = AUTHORITY_A

    rollback_tag = f"rollback-contract-{uuid4().hex[:8]}"
    shared_skill_id = f"skill-{rollback_tag}"
    rollback_target_tag = f"{rollback_tag}-target"
    rollback_target = activate_candidate(
        service,
        rollback_target_tag,
        skill_id=shared_skill_id,
        skill_version="1.0.0",
    )
    active = activate_candidate(
        service,
        rollback_tag,
        skill_id=shared_skill_id,
        skill_version="2.0.0",
    )
    rollback_ref = active["candidate_ref"]
    rollback_target_ref = rollback_target["candidate_ref"]
    target_candidate, target_events, _ = candidate_rows(engine, rollback_target_ref)
    target_active_event = target_events[-1]
    rollback_contract = candidate_contract(service, rollback_tag)
    rollback = attestation(
        service,
        rollback_tag,
        f"rollback-final-reviewer-{rollback_tag}",
        "rollback",
        {
            "rollback_target_ref": rollback_target_ref,
            "rollback_version": "1.0.0",
            "rollback_target_content_sha256": target_candidate.content_sha256,
            "rollback_target_runtime_sha256": (
                target_active_event.candidate_runtime_sha256
            ),
            "rollback_artifact_sha256": rollback_contract[
                "rollback_artifact_sha256"
            ],
            "snapshot_sha256": sha(f"rollback-snapshot:{rollback_tag}"),
        },
    )
    transition(
        service,
        rollback_ref,
        rollback_tag,
        f"owner-{rollback_tag}",
        ("approver",),
        "active",
        "rolled_back",
        (rollback,),
    )
    _, rollback_events, _ = candidate_rows(engine, rollback_ref)
    active_event, rollback_event = rollback_events[-2:]
    assert rollback_event.to_state == "rolled_back"
    assert rollback_event.rollback_target_candidate_ref == rollback_target_ref
    assert rollback_event.rollback_target_content_sha256 == target_candidate.content_sha256
    assert (
        rollback_event.rollback_target_runtime_sha256
        == target_active_event.candidate_runtime_sha256
    )
    assert (
        rollback_event.baseline_runtime_ref,
        rollback_event.baseline_runtime_sha256,
        rollback_event.candidate_runtime_ref,
        rollback_event.candidate_runtime_sha256,
        rollback_event.eval_set_sha256,
    ) == (
        active_event.baseline_runtime_ref,
        active_event.baseline_runtime_sha256,
        active_event.candidate_runtime_ref,
        active_event.candidate_runtime_sha256,
        active_event.eval_set_sha256,
    )
    rolled_back_candidate, _, _ = candidate_rows(engine, rollback_ref)
    successor, _, _ = create_candidate(
        service,
        f"{rollback_tag}-successor",
        skill_id=shared_skill_id,
        skill_version="3.0.0",
        predecessor_candidate_ref=rollback_ref,
        supersedes_sha256=rolled_back_candidate.content_sha256,
    )
    assert successor["predecessor"] == {
        "predecessor_candidate_ref": rollback_ref,
        "predecessor_skill_version": "2.0.0",
        "supersedes_sha256": rolled_back_candidate.content_sha256,
    }
    with pytest.raises(ValueError, match="Predecessor skill/version/hash"):
        create_candidate(
            service,
            f"{rollback_tag}-downgrade-successor",
            skill_id=shared_skill_id,
            skill_version="1.5.0",
            predecessor_candidate_ref=rollback_ref,
            supersedes_sha256=rolled_back_candidate.content_sha256,
        )


def test_concurrent_idempotency_and_authority_rotation(
    engine: Engine, workspace
) -> None:
    grants, service = workspace
    tag = f"concurrent-{uuid4().hex[:8]}"
    contract = candidate_contract(service, tag)
    evidence = base_attestations(service, tag, contract)

    def invoke(_index: int):
        return create_candidate(
            service,
            tag,
            contract=contract,
            evidence=evidence,
            idempotency_key=f"same-{tag}",
        )[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(invoke, range(8)))
    refs = {item["candidate_ref"] for item in results}
    assert len(refs) == 1
    candidate_ref = refs.pop()
    candidate, events, links = candidate_rows(engine, candidate_ref)
    assert candidate is not None
    assert len(events) == 1
    assert len(links) == 4
    grants.authority = "b" * 64
    with pytest.raises(KeyError):
        service.get_candidate(
            principal=principal(f"author-{tag}", "operator"),
            store_ref="store-a",
            candidate_ref=candidate_ref,
            as_of=NOW,
        )
    assert (
        service.list_candidates(
            principal=principal(f"author-{tag}", "operator"),
            store_ref="store-a",
            as_of=NOW,
        )["status"]
        == "no_data"
    )


def test_cross_tenant_authority_latest_epoch_blocks_historical_replay(
    engine: Engine, workspace
) -> None:
    _, service = workspace
    tag = f"cross-authority-{uuid4().hex[:8]}"
    contract = candidate_contract(service, tag)
    base = base_attestations(service, tag, contract)
    subject_sha256 = sha(f"cross-subject:{tag}")
    license_sha256 = sha(f"license:{tag}")
    deidentification_sha256 = sha(f"deidentification:{tag}")
    revocation_sha256 = sha(f"revocation:{tag}")

    def cross_attestation(purpose: str, epoch: int, **claims):
        return attestation(
            service,
            f"{tag}-{purpose}-epoch-{epoch}",
            f"{purpose}-signer-{tag}",
            purpose,
            {
                **claims,
                "authority_subject_sha256": subject_sha256,
                "authority_epoch": epoch,
                "current": True,
                "snapshot_sha256": sha(f"{purpose}-snapshot:{tag}:{epoch}"),
            },
        )

    license_evidence = cross_attestation(
        "license",
        1,
        license_sha256=license_sha256,
    )
    deidentification_evidence = cross_attestation(
        "deidentification",
        1,
        deidentification_sha256=deidentification_sha256,
        nonreversible=True,
    )
    revocation_evidence = cross_attestation(
        "revocation",
        1,
        revocation_contract_sha256=revocation_sha256,
        revoked=False,
    )
    created, _, _ = create_candidate(
        service,
        tag,
        contract=contract,
        evidence=(*base, license_evidence, deidentification_evidence, revocation_evidence),
        cross_tenant_mode="licensed_deidentified_nonreversible",
        license_sha256=license_sha256,
        deidentification_sha256=deidentification_sha256,
        revocation_contract_sha256=revocation_sha256,
    )
    assert created["state"] == "skill_candidate"
    cross_attestation(
        "revocation",
        2,
        revocation_contract_sha256=revocation_sha256,
        revoked=True,
    )
    with pytest.raises(ValueError, match="latest epoch"):
        service.get_candidate(
            principal=principal(f"author-{tag}", "operator"),
            store_ref="store-a",
            candidate_ref=created["candidate_ref"],
            as_of=NOW,
        )
    candidate, events, links = candidate_rows(engine, created["candidate_ref"])
    assert candidate.cross_tenant_mode == "licensed_deidentified_nonreversible"
    assert len(events) == 1
    assert {
        link.purpose for link in links if link.purpose != "event_audit"
    } == {
        "agent_run",
        "eval_set",
        "rollback",
        "license",
        "deidentification",
        "revocation",
    }


@pytest.mark.parametrize("drift", ["subject", "epoch"])
def test_initial_cross_tenant_authority_conservation_is_fail_closed(
    workspace, monkeypatch, drift: str
) -> None:
    _, service = workspace
    tag = f"cross-initial-{drift}-{uuid4().hex[:6]}"
    contract = candidate_contract(service, tag)
    base = base_attestations(service, tag, contract)
    subject = sha(f"subject:{tag}")
    license_sha256 = sha(f"license:{tag}")
    deidentification_sha256 = sha(f"deidentification:{tag}")
    revocation_sha256 = sha(f"revocation:{tag}")

    def authority(purpose: str, **claims):
        purpose_subject = (
            sha(f"different-subject:{tag}")
            if drift == "subject" and purpose == "revocation"
            else subject
        )
        epoch = 2 if drift == "epoch" and purpose == "revocation" else 1
        return attestation(
            service,
            f"{tag}-{purpose}",
            f"{purpose}-signer-{tag}",
            purpose,
            {
                **claims,
                "authority_subject_sha256": purpose_subject,
                "authority_epoch": epoch,
                "current": True,
                "snapshot_sha256": sha(f"{purpose}-snapshot:{tag}"),
            },
        )

    evidence = (
        *base,
        authority("license", license_sha256=license_sha256),
        authority(
            "deidentification",
            deidentification_sha256=deidentification_sha256,
            nonreversible=True,
        ),
        authority(
            "revocation",
            revocation_contract_sha256=revocation_sha256,
            revoked=False,
        ),
    )
    monkeypatch.setattr(service, "_candidate_evidence_gates", lambda **_kwargs: None)
    monkeypatch.setattr(service, "_cross_tenant_gate", lambda *_args: None)
    with pytest.raises(DBAPIError, match="authority epoch/subject drift"):
        create_candidate(
            service,
            tag,
            contract=contract,
            evidence=evidence,
            cross_tenant_mode="licensed_deidentified_nonreversible",
            license_sha256=license_sha256,
            deidentification_sha256=deidentification_sha256,
            revocation_contract_sha256=revocation_sha256,
        )


def test_concurrent_revocation_serializes_before_cross_tenant_commit(
    workspace,
) -> None:
    _, service = workspace
    tag = f"cross-race-{uuid4().hex[:8]}"
    contract = candidate_contract(service, tag)
    base = base_attestations(service, tag, contract)
    subject = sha(f"subject:{tag}")
    license_sha256 = sha(f"license:{tag}")
    deidentification_sha256 = sha(f"deidentification:{tag}")
    revocation_sha256 = sha(f"revocation:{tag}")

    def authority(purpose: str, **claims):
        return attestation(
            service,
            f"{tag}-{purpose}-epoch-1",
            f"{purpose}-signer-{tag}",
            purpose,
            {
                **claims,
                "authority_subject_sha256": subject,
                "authority_epoch": 1,
                "current": True,
                "snapshot_sha256": sha(f"{purpose}-snapshot:{tag}:1"),
            },
        )

    old_evidence = (
        *base,
        authority("license", license_sha256=license_sha256),
        authority(
            "deidentification",
            deidentification_sha256=deidentification_sha256,
            nonreversible=True,
        ),
        authority(
            "revocation",
            revocation_contract_sha256=revocation_sha256,
            revoked=False,
        ),
    )

    def mutate():
        return create_candidate(
            service,
            tag,
            contract=contract,
            evidence=old_evidence,
            cross_tenant_mode="licensed_deidentified_nonreversible",
            license_sha256=license_sha256,
            deidentification_sha256=deidentification_sha256,
            revocation_contract_sha256=revocation_sha256,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with service.evidence.transaction() as session:
            TeamAgentEvidenceAuthorityAdapter(service.evidence).capture(
                principal=principal(f"revocation-signer-{tag}", "compliance"),
                purpose="revocation",
                claims={
                    "revocation_contract_sha256": revocation_sha256,
                    "revoked": True,
                    "authority_subject_sha256": subject,
                    "authority_epoch": 2,
                    "current": True,
                    "snapshot_sha256": sha(f"revocation-snapshot:{tag}:2"),
                },
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                store_ref="store-a",
                scope_authority_sha256=AUTHORITY_A,
                candidate_author_actor_id=f"author-{tag}",
                human_owner_actor_id=f"owner-{tag}",
                effective_at=NOW.isoformat(),
                effective_until=(NOW + timedelta(days=30)).isoformat(),
                session=session,
            )
            future = pool.submit(mutate)
            time.sleep(0.25)
            assert not future.done()
        with pytest.raises(ValueError, match="latest epoch"):
            future.result(timeout=10)


def test_append_only_and_late_link_append_fail_closed(
    engine: Engine, workspace
) -> None:
    _, service = workspace
    tag = f"immutable-{uuid4().hex[:8]}"
    created, _, _ = create_candidate(service, tag)
    candidate, events, links = candidate_rows(engine, created["candidate_ref"])
    audit = next(link for link in links if link.purpose == "event_audit")
    support = next(link for link in links if link.purpose != "event_audit")
    reserved_authority = next(link for link in links if link.purpose == "eval_set")
    statements = (
        (
            f"UPDATE {CANDIDATES} SET skill_version='2.0.0' "
            "WHERE candidate_ref=:target",
            candidate.candidate_ref,
        ),
        (
            f"DELETE FROM {EVENTS} WHERE event_ref=:target",
            events[0].event_ref,
        ),
        (
            f"UPDATE {EVIDENCE_LINKS} SET ordinal=99 WHERE link_ref=:target",
            support.link_ref,
        ),
        (
            "DELETE FROM evidence_records WHERE id=:target",
            audit.evidence_id,
        ),
        (
            "DELETE FROM evidence_records WHERE id=:target",
            reserved_authority.evidence_id,
        ),
    )
    for statement, target in statements:
        with pytest.raises(DBAPIError, match="append-only|immutable"), engine.begin() as connection:
            connection.execute(text(statement), {"target": target})

    with pytest.raises(DBAPIError, match="late team-agent Evidence link"), engine.begin() as connection:
        link_table = reflected(connection, EVIDENCE_LINKS)
        clone = dict(
            connection.execute(
                select(link_table).where(link_table.c.link_ref == support.link_ref)
            )
            .mappings()
            .one()
        )
        clone["link_ref"] = stable_ref("gtal", f"late:{tag}")
        clone["ordinal"] = max(link.ordinal for link in links) + 1
        connection.execute(link_table.insert().values(**clone))


def test_transition_sod_sequence_and_evidence_conservation_fail_closed(
    engine: Engine, workspace, monkeypatch
) -> None:
    _, service = workspace
    tag = f"negative-{uuid4().hex[:8]}"
    created, contract, base = create_candidate(service, tag)
    candidate_ref = created["candidate_ref"]
    with pytest.raises(DBAPIError, match="separation of duties"), engine.begin() as connection:
        direct_evaluation_event(
            connection,
            candidate_ref,
            f"sod:{tag}",
            actor_id=f"author-{tag}",
        )

    bad_baseline = TeamAgentEvidenceAuthorityAdapter(service.evidence).capture(
        principal=principal(f"author-{tag}", "reviewer"),
        purpose="baseline",
        claims=baseline_claims(service, tag, contract),
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        scope_authority_sha256=AUTHORITY_A,
        candidate_author_actor_id="decoy-author",
        human_owner_actor_id="decoy-owner",
        effective_at=NOW.isoformat(),
        effective_until=(NOW + timedelta(days=30)).isoformat(),
    )
    run, eval_set, _ = base
    monkeypatch.setattr(service, "_enforce_authority_signers", lambda **_kwargs: None)
    with pytest.raises(DBAPIError, match="authority signer separation"):
        transition(
            service,
            candidate_ref,
            tag,
            f"evaluator-{tag}",
            ("monitor",),
            "skill_candidate",
            "evaluation",
            (run, eval_set, bad_baseline),
        )

    with pytest.raises(DBAPIError, match="Evidence purpose conservation"), engine.begin() as connection:
        direct_evaluation_event(
            connection,
            candidate_ref,
            f"missing-evidence:{tag}",
            actor_id=f"evaluator-{tag}",
        )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with pytest.raises(DBAPIError, match="invalid team-agent lifecycle transition"), engine.begin() as connection:
        events = reflected(connection, EVENTS)
        previous = dict(
            connection.execute(
                select(events).where(events.c.candidate_ref == candidate_ref)
            )
            .mappings()
            .one()
        )
        previous.pop("insert_xid", None)
        previous.update(
            {
                "event_ref": stable_ref("gtae", f"skip:{tag}"),
                "ordinal": 2,
                "from_state": "skill_candidate",
                "to_state": "active",
                "actor_id": f"owner-{tag}",
                "actor_role": "human_owner",
                "risk_actor_id": f"risk-{tag}",
                "reason_code": "skip_to_active",
                "eval_baseline_passed": True,
                "negative_tests_passed": True,
                "scope_tests_passed": True,
                "shadow_passed": True,
                "risk_authority_sha256": sha(f"risk:{tag}"),
                "review_verdict": "approved",
                "prev_event_sha256": previous["event_sha256"],
                "event_sha256": ZERO_SHA256,
                "request_sha256": sha(f"skip-request:{tag}"),
                "idempotency_sha256": sha(f"skip-idempotency:{tag}"),
                "occurred_at": NOW,
            }
        )
        previous["event_sha256"] = _event_digest(
            GovernedTeamAgentEvolutionWorkspace._event_hash_payload(
                SimpleNamespace(**previous)
            )
        )
        connection.execute(events.insert().values(**previous))


def test_review_signer_must_equal_independent_review_actor_in_database(
    workspace, monkeypatch
) -> None:
    _, service = workspace
    tag = f"review-signer-{uuid4().hex[:8]}"
    candidate_ref, _, _, shadow = advance_candidate_to_shadow(service, tag)
    mismatched_review = attestation(
        service,
        tag,
        f"different-reviewer-{tag}",
        "review",
        {
            "review_verdict": "approved",
            "snapshot_sha256": sha(f"review-snapshot:{tag}"),
        },
    )
    monkeypatch.setattr(service, "_transition_gates", lambda **_kwargs: None)
    with pytest.raises(DBAPIError, match="review Evidence event binding"):
        transition(
            service,
            candidate_ref,
            tag,
            f"reviewer-{tag}",
            ("reviewer",),
            "shadow",
            "independent_review",
            (mismatched_review, shadow),
            shadow_passed=True,
        )


def test_risk_signer_must_differ_from_prior_gate_actors_in_database(
    workspace, monkeypatch
) -> None:
    _, service = workspace
    tag = f"risk-signer-{uuid4().hex[:8]}"
    candidate_ref, _, baseline, shadow = advance_candidate_to_shadow(service, tag)
    review = attestation(
        service,
        tag,
        f"reviewer-{tag}",
        "review",
        {
            "review_verdict": "approved",
            "snapshot_sha256": sha(f"review-snapshot:{tag}"),
        },
    )
    transition(
        service,
        candidate_ref,
        tag,
        f"reviewer-{tag}",
        ("reviewer",),
        "shadow",
        "independent_review",
        (review, shadow),
        shadow_passed=True,
    )
    risk = attestation(
        service,
        tag,
        f"evaluator-{tag}",
        "risk_authority",
        {
            "risk_authority_sha256": sha(f"risk-authority:{tag}"),
            "current": True,
            "snapshot_sha256": sha(f"risk-snapshot:{tag}"),
        },
    )
    monkeypatch.setattr(service, "_enforce_sod", lambda **_kwargs: None)
    with pytest.raises(DBAPIError, match="risk authority Evidence event binding"):
        transition(
            service,
            candidate_ref,
            tag,
            f"promoter-{tag}",
            ("approver",),
            "independent_review",
            "promoted",
            (baseline, shadow, review, risk),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cost_usd", Decimal("NaN")),
        ("cost_usd", Decimal("Infinity")),
        ("cost_usd", Decimal("-1")),
        ("latency_ms", Decimal("Infinity")),
        ("token_count", -1),
    ],
)
def test_nonfinite_or_negative_usage_is_rejected(
    engine: Engine, workspace, field: str, value
) -> None:
    _, service = workspace
    tag = f"metric-{field}-{uuid4().hex[:6]}"
    created, _, _ = create_candidate(service, tag)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        events = reflected(connection, EVENTS)
        previous = dict(
            connection.execute(
                select(events).where(
                    events.c.candidate_ref == created["candidate_ref"]
                )
            )
            .mappings()
            .one()
        )
        previous.pop("insert_xid", None)
        previous.update(
            {
                "event_ref": stable_ref("gtae", f"metric:{tag}"),
                "ordinal": 2,
                "from_state": "skill_candidate",
                "to_state": "evaluation",
                "actor_id": f"evaluator-{tag}",
                "actor_role": "evaluator",
                "reason_code": "metric_negative",
                "prev_event_sha256": previous["event_sha256"],
                "event_sha256": ZERO_SHA256,
                "request_sha256": sha(f"metric-request:{tag}"),
                "idempotency_sha256": sha(f"metric-idem:{tag}"),
                "occurred_at": NOW,
                field: value,
            }
        )
        previous["event_sha256"] = _event_digest(
            GovernedTeamAgentEvolutionWorkspace._event_hash_payload(
                SimpleNamespace(**previous)
            )
        )
        connection.execute(events.insert().values(**previous))


def test_event_content_hash_is_recomputed_before_insert(
    engine: Engine, workspace
) -> None:
    _, service = workspace
    tag = f"event-hash-{uuid4().hex[:8]}"
    created, _, _ = create_candidate(service, tag)
    with pytest.raises(DBAPIError, match="event content hash"), engine.begin() as connection:
        events = reflected(connection, EVENTS)
        previous = dict(
            connection.execute(
                select(events).where(
                    events.c.candidate_ref == created["candidate_ref"]
                )
            )
            .mappings()
            .one()
        )
        previous.pop("insert_xid", None)
        previous.update(
            {
                "event_ref": stable_ref("gtae", f"forged-hash:{tag}"),
                "ordinal": 2,
                "from_state": "skill_candidate",
                "to_state": "evaluation",
                "actor_id": f"evaluator-{tag}",
                "actor_role": "evaluator",
                "reason_code": "forged_event_hash",
                "prev_event_sha256": previous["event_sha256"],
                "event_sha256": sha(f"forged-event:{tag}"),
                "request_sha256": sha(f"forged-request:{tag}"),
                "idempotency_sha256": sha(f"forged-idem:{tag}"),
                "occurred_at": NOW,
            }
        )
        connection.execute(events.insert().values(**previous))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_ref", "gtac_" + "b" * 32),
        ("from_state", "forged"),
        ("to_state", "retired"),
        ("data_as_of", (NOW - timedelta(days=1)).isoformat()),
        (
            "predecessor",
            {
                "predecessor_candidate_ref": "gtac_" + "c" * 32,
                "predecessor_skill_version": "9.9.9",
                "supersedes_sha256": "d" * 64,
            },
        ),
        ("external_write_performed", True),
    ],
)
def test_event_audit_canonical_receipt_drift_is_rejected(
    workspace, monkeypatch, field: str, value
) -> None:
    _, service = workspace
    tag = f"audit-{field}-{uuid4().hex[:6]}"
    original = service._event_audit_payload

    def forged_receipt(**kwargs):
        payload = original(**kwargs)
        payload[field] = value
        return payload

    monkeypatch.setattr(service, "_event_audit_payload", forged_receipt)
    with pytest.raises(DBAPIError, match="event audit Evidence"):
        create_candidate(service, tag)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_sha256", sha("wrong-hash")),
        ("evidence_source", "wrong-source"),
        ("evidence_source_ref", "wrong://source-ref"),
        ("evidence_grade", "C"),
        ("evidence_effective_at", NOW - timedelta(days=1)),
    ],
)
def test_evidence_exact_composite_binding_is_rejected(
    engine: Engine, workspace, field: str, value
) -> None:
    _, service = workspace
    tag = f"binding-{field}-{uuid4().hex[:6]}"
    created, _, _ = create_candidate(service, tag)
    candidate_ref = created["candidate_ref"]
    with pytest.raises(DBAPIError, match="exact binding"), engine.begin() as connection:
        event, insert_xid = direct_evaluation_event(
            connection,
            candidate_ref,
            f"binding:{tag}",
            actor_id=f"evaluator-{tag}",
        )
        links = reflected(connection, EVIDENCE_LINKS)
        source = dict(
            connection.execute(
                select(links)
                .where(
                    links.c.candidate_ref == candidate_ref,
                    links.c.purpose == "agent_run",
                )
                .limit(1)
            )
            .mappings()
            .one()
        )
        source.update(
            {
                "link_ref": stable_ref("gtal", f"binding:{field}:{tag}"),
                "event_ref": event["event_ref"],
                "event_insert_xid": insert_xid,
                "ordinal": 1,
                field: value,
            }
        )
        connection.execute(links.insert().values(**source))


def test_unrelated_authority_evidence_cannot_satisfy_event_claims(
    engine: Engine, workspace
) -> None:
    _, service = workspace
    target_tag = f"semantic-target-{uuid4().hex[:8]}"
    other_tag = f"semantic-other-{uuid4().hex[:8]}"
    target, _, _ = create_candidate(service, target_tag)
    other, _, _ = create_candidate(service, other_tag)
    with pytest.raises(
        DBAPIError,
        match="payload hash drift|AgentRun Evidence event binding",
    ), engine.begin() as connection:
        event, insert_xid = direct_evaluation_event(
            connection,
            target["candidate_ref"],
            f"semantic:{target_tag}",
            actor_id=f"evaluator-{target_tag}",
        )
        links = reflected(connection, EVIDENCE_LINKS)
        unrelated = dict(
            connection.execute(
                select(links)
                .where(
                    links.c.candidate_ref == other["candidate_ref"],
                    links.c.purpose == "agent_run",
                )
                .limit(1)
            )
            .mappings()
            .one()
        )
        unrelated.update(
            {
                "link_ref": stable_ref("gtal", f"semantic:{target_tag}"),
                "event_ref": event["event_ref"],
                "candidate_ref": target["candidate_ref"],
                "event_insert_xid": insert_xid,
                "ordinal": 1,
            }
        )
        connection.execute(links.insert().values(**unrelated))


def test_downgrade_with_rows_evidence_and_lineage_is_fail_closed(
    engine: Engine, workspace
) -> None:
    _, service = workspace
    tag = f"downgrade-{uuid4().hex[:8]}"
    created, _, _ = create_candidate(service, tag)
    candidate_ref = created["candidate_ref"]
    _, _, links = candidate_rows(engine, candidate_ref)
    audit = next(link for link in links if link.purpose == "event_audit")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO lineage_edges "
                "(id,from_type,from_id,to_type,to_id,relationship,created_by,recorded_at) "
                "VALUES (:id,'evidence',:evidence,'team_agent_candidate',:candidate,"
                "'governs_evolution_candidate','postgres-contract-test',:recorded_at)"
            ),
            {
                "id": stable_ref("lin", tag),
                "evidence": audit.evidence_id,
                "candidate": candidate_ref,
                "recorded_at": NOW,
            },
        )
    with pytest.raises(DBAPIError, match="0094 downgrade blocked"):
        command.downgrade(migration_config(engine), "20260803_0093")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version"))
            .scalar_one()
            == "20260803_0094"
        )
        assert connection.execute(
            text(f"SELECT count(*) FROM {CANDIDATES} WHERE candidate_ref=:ref"),
            {"ref": candidate_ref},
        ).scalar_one() == 1
        assert connection.execute(
            select(EvidenceRecordRow.id).where(EvidenceRecordRow.id == audit.evidence_id)
        ).scalar_one() == audit.evidence_id
