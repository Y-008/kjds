from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    HarnessObservationRow,
    OperatingSubjectBindingEventRow,
    VerifierRegistryRow,
)
from apps.control_plane.operating_gate_observer import (
    AUTHORITY_TASK_ID,
    PROJECT_ID,
    SUBJECT_TASK_ID,
    TASK_IDS,
    OperatingGateObserverService,
)
from apps.control_plane.operating_gate_verifier import OperatingStageVerifier
from apps.control_plane.security import Principal

STAGE_IDS = (
    "observe",
    "identity",
    "qualify",
    "item_draft",
    "content",
    "listing_approval",
    "publish",
    "order",
    "procurement_review",
    "fulfill",
    "settle",
    "reconcile",
    "learn",
)


class _CommerceOs:
    def __init__(self):
        self.actor_ids = []

    def workspace(self, **_kwargs):
        self.actor_ids.append(_kwargs["principal"].actor_id)
        return {
            "contract_version": "commerce-operating-system/1.0.0",
            "status": "no_data",
            "scope": {
                "tenant_ref": "default",
                "entity_ref": None,
                "store_ref": "ozon-primary",
            },
            "stages": [
                {
                    "id": stage_id,
                    "status": "no_data" if stage_id == "observe" else "blocked",
                    "qualified_record_count": 0,
                    "why": "no verified record",
                    "owner": f"{stage_id}-owner",
                    "next_action": f"complete {stage_id}",
                    "workspace_href": "/commerce-os",
                    "client_recalculation_allowed": False,
                    "external_write_allowed": False,
                }
                for stage_id in STAGE_IDS
            ],
            "source_snapshots": {"truth_governance": "a" * 64},
            "formal_facts": {
                "status": "no_data",
                "formal_fact_count": 0,
                "snapshot_sha256": "b" * 64,
            },
            "control_envelope": {
                "read_only_projection": True,
                "external_writes": False,
                "ozon_write": False,
                "supplier_message": False,
                "supplier_order": False,
                "purchase": False,
                "payment": False,
                "inventory_write": False,
                "price_write": False,
                "advertising_write": False,
                "agent_self_approval": False,
                "agent_permit_issuance": False,
            },
            "completion_claim": {"real_profit_loop_complete": False},
            "snapshot_sha256": "c" * 64,
        }


class _ScopeGrants:
    def __init__(self):
        self.actor_ids = []

    def current(self, **_kwargs):
        self.actor_ids.append(_kwargs["principal"].actor_id)
        return {
            "status": "no_data",
            "entity_ref": None,
            "authority": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
            "active_grant_count": 0,
        }


def _support():
    return "20260728_0070", {
        key: 0 for key in OperatingStageVerifier.SUPPORT_KEYS
    }


@pytest.mark.parametrize(
    ("revision", "supported"),
    [
        ("20260728_0069", False),
        ("20260728_0070", True),
        ("20260802_0087", True),
        ("0087", False),
        ("20260802_head", False),
    ],
)
def test_observer_accepts_compatible_forward_migrations_only(
    revision: str,
    supported: bool,
) -> None:
    assert (
        OperatingGateObserverService._supports_database_revision(revision)
        is supported
    )


@pytest.fixture
def observer(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'observer.db'}")
    GraphProjectRow.metadata.create_all(
        engine,
        tables=[
            GraphProjectRow.__table__,
            OperatingSubjectBindingEventRow.__table__,
            VerifierRegistryRow.__table__,
            GoalTaskRow.__table__,
            HarnessObservationRow.__table__,
            GraphNodeRow.__table__,
            GraphEdgeRow.__table__,
        ],
    )
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            GraphProjectRow(
                id=PROJECT_ID,
                tenant_ref="default",
                entity_ref=None,
                store_ref="ozon-primary",
                title="test project",
                lifecycle="active",
                baseline_sha256="d" * 64,
                goal_contract_sha256="e" * 64,
                created_at=now,
            )
        )
        for index, task_id in enumerate(TASK_IDS):
            session.add(
                GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=f"M{index}",
                    owner="test-owner",
                    verifier_id="m0m4-real-postgres",
                    verifier_version="1",
                    dependency_ids_json=[],
                    verification_condition="old",
                    next_safe_action="old",
                    workspace="/goal-todo",
                    sla_seconds=None,
                    fingerprint=f"{index:064d}",
                    created_at=now,
                )
            )
            session.add(
                GraphNodeRow(
                    id=f"gate-node-{index}",
                    project_id=PROJECT_ID,
                    graph_kind="commerce",
                    stable_key=f"gate-state:M{index}",
                    node_type="gate_state",
                    label="old",
                    authority="observed",
                    source="old",
                    scope_json={
                        "tenant_ref": "default",
                        "store_ref": "ozon-primary",
                    },
                    version="old",
                    content_sha256="f" * 64,
                    artifact_ref="old",
                    created_at=now,
                )
            )
        session.add(
            GoalTaskRow(
                id=SUBJECT_TASK_ID,
                project_id=PROJECT_ID,
                title="M0 project operating subject binding",
                owner="project-admin+monitor",
                verifier_id="operating-subject-binding",
                verifier_version="1",
                dependency_ids_json=[],
                verification_condition="current binding",
                next_safe_action="bind operator",
                workspace="/authority-graph",
                sla_seconds=86400,
                fingerprint="9" * 64,
                created_at=now,
            )
        )
        session.add(
            GraphNodeRow(
                id="operating-subject-node",
                project_id=PROJECT_ID,
                graph_kind="authority",
                stable_key="authority:operating-subject-binding",
                node_type="authority",
                label="Append-only project operating subject binding",
                authority="canonical",
                source=(
                    f"/v1/agent-control/projects/{PROJECT_ID}/"
                    "operating-subject"
                ),
                scope_json={
                    "tenant_ref": "default",
                    "store_ref": "ozon-primary",
                },
                version="old",
                content_sha256="8" * 64,
                artifact_ref=(
                    f"/v1/agent-control/projects/{PROJECT_ID}/"
                    "operating-subject"
                ),
                created_at=now,
            )
        )
        session.add(
            GoalTaskRow(
                id=AUTHORITY_TASK_ID,
                project_id=PROJECT_ID,
                title="M0 current scope authority admission",
                owner="account-owner+compliance",
                verifier_id="scope-grant-current",
                verifier_version="1",
                dependency_ids_json=[SUBJECT_TASK_ID],
                verification_condition="current grant",
                next_safe_action="run preflight",
                workspace="/authority-graph",
                sla_seconds=86400,
                fingerprint="a" * 64,
                created_at=now,
            )
        )
        session.add(
            GraphNodeRow(
                id="authority-current-node",
                project_id=PROJECT_ID,
                graph_kind="authority",
                stable_key="authority:current-scope-grant",
                node_type="authority",
                label="Current tenant/entity/store scope authority",
                authority="canonical",
                source="/v1/scope-grants/current",
                scope_json={
                    "tenant_ref": "default",
                    "store_ref": "ozon-primary",
                },
                version="old",
                content_sha256="b" * 64,
                artifact_ref="/v1/scope-grants/current",
                created_at=now,
            )
        )
    harness = AgentHarnessService(engine)
    harness.record_operating_subject_event(
        project_id=PROJECT_ID,
        principal=Principal(
            actor_id="admin-a",
            roles=frozenset({"admin"}),
            tenant_ref="default",
            store_refs=frozenset({"ozon-primary"}),
        ),
        subject=Principal(
            actor_id="operator-a",
            roles=frozenset({"operator"}),
            tenant_ref="default",
            store_refs=frozenset({"ozon-primary"}),
        ),
        event_type="bind",
        effective_at=now - timedelta(hours=1),
        reason="test operating subject",
        idempotency_key="test-operating-subject",
    )
    return OperatingGateObserverService(
        engine=engine,
        commerce_os=_CommerceOs(),
        scope_grants=_ScopeGrants(),
        agent_harness=harness,
        identity_resolver=lambda actor_id: (
            Principal(
                actor_id="operator-a",
                roles=frozenset({"operator"}),
                tenant_ref="default",
                store_refs=frozenset({"ozon-primary"}),
            )
            if actor_id == "operator-a"
            else (_ for _ in ()).throw(KeyError("actor not found"))
        ),
        support_reader=_support,
    )


def test_observer_records_real_verifier_states_and_replays_idempotently(
    observer,
) -> None:
    principal = Principal(
        actor_id="monitor-a",
        roles=frozenset({"monitor"}),
        tenant_ref="default",
        store_refs=frozenset({"ozon-primary"}),
    )
    observed_at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    first = observer.observe(
        project_id=PROJECT_ID,
        principal=principal,
        store_ref="ozon-primary",
        observed_at=observed_at,
    )
    replay = observer.observe(
        project_id=PROJECT_ID,
        principal=principal,
        store_ref="ozon-primary",
        observed_at=observed_at,
    )

    assert first["states"] == {
        "operating_subject": "passed",
        "scope_authority": "no_data",
        "m0": "no_data",
        "m1": "blocked",
        "m2": "blocked",
        "m3": "blocked",
        "m4": "blocked",
    }
    assert replay["result_sha256"] == first["result_sha256"]
    assert first["operating_subject_actor_id"] == "operator-a"
    assert len(first["subject_binding_sha256"]) == 64
    assert replay["counts"]["observations"] == 7
    assert first["external_write_allowed"] is False
    assert observer.commerce_os.actor_ids == ["operator-a", "operator-a"]
    assert observer.scope_grants.actor_ids == ["operator-a", "operator-a"]
    with Session(observer.engine) as session:
        assert session.scalar(
            select(func.count()).select_from(HarnessObservationRow)
        ) == 7
        assert {
            row.verifier_id
            for row in session.scalars(select(GoalTaskRow)).all()
        } == {
            "m0m4-commerce-os",
            "operating-subject-binding",
            "scope-grant-current",
        }
        assert all(
            row.label.startswith(f"M{index}")
            for index, row in enumerate(
                session.scalars(
                    select(GraphNodeRow)
                    .where(GraphNodeRow.graph_kind == "commerce")
                    .order_by(GraphNodeRow.stable_key)
                ).all()
            )
        )
        authority_node = session.scalar(
            select(GraphNodeRow).where(
                GraphNodeRow.stable_key
                == "authority:current-scope-grant"
            )
        )
        assert authority_node is not None
        assert (
            authority_node.label
            == "Current tenant/entity/store scope authority"
        )


def test_observer_rejects_non_monitor_identity(observer) -> None:
    principal = Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="default",
        store_refs=frozenset({"ozon-primary"}),
    )

    with pytest.raises(PermissionError, match="monitor or admin"):
        observer.observe(
            project_id=PROJECT_ID,
            principal=principal,
            store_ref="ozon-primary",
        )


def test_observer_fails_closed_without_operating_subject_binding(
    observer,
) -> None:
    with Session(observer.engine) as session, session.begin():
        session.execute(delete(OperatingSubjectBindingEventRow))
    principal = Principal(
        actor_id="monitor-a",
        roles=frozenset({"monitor"}),
        tenant_ref="default",
        store_refs=frozenset({"ozon-primary"}),
    )

    with pytest.raises(
        ValueError,
        match="operating-subject binding is required",
    ):
        observer.observe(
            project_id=PROJECT_ID,
            principal=principal,
            store_ref="ozon-primary",
        )
    with Session(observer.engine) as session:
        assert session.scalar(
            select(func.count()).select_from(HarnessObservationRow)
        ) == 0
