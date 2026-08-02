from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GoalContractRow,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    _sha,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base


def principal(
    *,
    actor: str = "monitor-a",
    roles: frozenset[str] = frozenset({"monitor"}),
    tenant: str = "tenant-a",
    stores: frozenset[str] = frozenset({"store-a"}),
) -> Principal:
    return Principal(
        actor_id=actor,
        roles=roles,
        tenant_ref=tenant,
        store_refs=stores,
    )


def harness():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            GraphProjectRow(
                id="kjds-059",
                tenant_ref="tenant-a",
                entity_ref=None,
                store_ref="store-a",
                title="KJDS 0.59",
                lifecycle="active",
                baseline_sha256="a" * 64,
                goal_contract_sha256="b" * 64,
                created_at=now,
            )
        )
        session.add(
            GoalContractRow(
                id="goal-kjds",
                project_id="kjds-059",
                objective="Ship verified control-plane slices.",
                constraints_json=["no external write"],
                content_sha256="b" * 64,
                created_at=now,
            )
        )
        session.add(
            GoalTaskRow(
                id="task-pytest",
                project_id="kjds-059",
                title="Full backend",
                owner="engineering",
                verifier_id="pytest",
                verifier_version="1",
                dependency_ids_json=[],
                verification_condition="exit zero and parsed pass count",
                next_safe_action="inspect failure",
                workspace="/engineering-graph",
                sla_seconds=3600,
                fingerprint=_sha(["task", "pytest"]),
                created_at=now,
            )
        )
        for kind in ("project", "requirements", "engineering", "runtime", "evidence", "commerce", "authority"):
            session.add(
                GraphNodeRow(
                    id=f"node-{kind}",
                    project_id="kjds-059",
                    graph_kind=kind,
                    stable_key=f"{kind}:root",
                    node_type="root",
                    label=kind,
                    authority="declared",
                    source="ADR-0048",
                    scope_json={"tenant_ref": "tenant-a", "store_ref": "store-a"},
                    version="1",
                    content_sha256=_sha([kind, "root"]),
                    artifact_ref="docs/adr/ADR-0048-agent-harness-and-canonical-graph.md",
                    created_at=now,
                )
            )
        session.add(
            GraphEdgeRow(
                id="edge-inferred",
                project_id="kjds-059",
                graph_kind="engineering",
                source_node_id="node-engineering",
                target_node_id="node-runtime",
                edge_type="may_affect",
                derivation_method="inferred",
                confidence=50,
                evidence_ref=None,
                effective_from=now,
                effective_until=None,
                content_sha256=_sha(["inferred"]),
            )
        )
    service = AgentHarnessService(engine)
    service.register_verifier(
        {
            "id": "pytest",
            "version": "1",
            "source_type": "process_log",
            "authority": "external_verifier",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    return service


def test_only_bound_verifier_can_pass_and_replay_is_idempotent():
    service = harness()
    binding = service.bind_node_status(
        project_id="kjds-059",
        node_id="node-project",
        task_id="task-pytest",
    )
    assert (
        service.bind_node_status(
            project_id="kjds-059",
            node_id="node-project",
            task_id="task-pytest",
        )
        == binding
    )
    observed_at = datetime.now(UTC)
    payload = {
        "project_id": "kjds-059",
        "task_id": "task-pytest",
        "verifier_id": "pytest",
        "verifier_version": "1",
        "source": "pytest process log",
        "scope": {"tenant_ref": "tenant-a", "store_ref": "store-a"},
        "state": "passed",
        "summary": "743 passed",
        "input_sha256": "1" * 64,
        "artifact_ref": "output/pytest/full.log",
        "evidence_ref": "docs/project/evidence/BAS-123.md",
        "observed_at": observed_at.isoformat(),
        "store_ref": "store-a",
    }
    first = service.record_observation(payload, principal=principal())
    replay = service.record_observation(payload, principal=principal())
    assert replay == first
    view = service.workspace(
        "kjds-059",
        principal=principal(roles=frozenset({"operator"})),
        store_ref="store-a",
        as_of=observed_at + timedelta(minutes=1),
    )
    assert view["counts"]["passed"] == 1
    assert view["status"] == "ready"
    assert view["tasks"][0]["observation_id"] == first["id"]
    project_node = next(
        item for item in view["nodes"] if item["id"] == "node-project"
    )
    assert project_node["verification"] == {
        "state": "passed",
        "freshness": "fresh",
        "why": "743 passed",
        "blockers": [],
        "owner": "engineering",
        "sla_seconds": 3600,
        "dependencies": [],
        "verifier": {"id": "pytest", "version": "1"},
        "observation_id": first["id"],
        "artifact_ref": "output/pytest/full.log",
        "evidence_ref": "docs/project/evidence/BAS-123.md",
        "next_safe_action": "inspect failure",
        "workspace": "/engineering-graph",
        "binding_sha256": binding["content_sha256"],
    }
    assert view["counts"]["verified_nodes"] == 1
    assert view["external_write_allowed"] is False


def test_stale_observation_cannot_keep_task_passed():
    service = harness()
    observed_at = datetime.now(UTC) - timedelta(hours=2)
    service.record_observation(
        {
            "project_id": "kjds-059",
            "task_id": "task-pytest",
            "verifier_id": "pytest",
            "verifier_version": "1",
            "source": "pytest process log",
            "scope": {"tenant_ref": "tenant-a", "store_ref": "store-a"},
            "state": "passed",
            "summary": "743 passed",
            "input_sha256": "1" * 64,
            "artifact_ref": "output/pytest/full.log",
            "evidence_ref": None,
            "observed_at": observed_at.isoformat(),
            "store_ref": "store-a",
        },
        principal=principal(),
    )
    view = service.workspace(
        "kjds-059",
        principal=principal(roles=frozenset({"operator"})),
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )
    assert view["tasks"][0]["state"] == "stale"
    assert view["tasks"][0]["blockers"] == [
        "verifier_observation_stale"
    ]
    assert view["counts"]["passed"] == 0
    assert view["status"] == "stale"


def test_own_blocked_observation_exposes_structured_verifier_blocker():
    service = harness()
    observed_at = datetime.now(UTC)
    service.record_observation(
        {
            "project_id": "kjds-059",
            "task_id": "task-pytest",
            "verifier_id": "pytest",
            "verifier_version": "1",
            "source": "external deployment verifier",
            "scope": {
                "tenant_ref": "tenant-a",
                "store_ref": "store-a",
            },
            "state": "blocked",
            "summary": "scheduled task is not installed",
            "input_sha256": "9" * 64,
            "artifact_ref": "output/runtime/task-audit.json",
            "evidence_ref": None,
            "observed_at": observed_at.isoformat(),
            "store_ref": "store-a",
        },
        principal=principal(),
    )
    view = service.workspace(
        "kjds-059",
        principal=principal(roles=frozenset({"operator"})),
        store_ref="store-a",
        as_of=observed_at + timedelta(seconds=1),
    )
    task = view["tasks"][0]
    assert task["state"] == "blocked"
    assert task["freshness"] == "fresh"
    assert task["blockers"] == ["verifier_state:blocked"]
    assert view["status"] == "blocked"


def test_changed_upstream_observation_invalidates_dependent_pass():
    service = harness()
    service.register_verifier(
        {
            "id": "browser",
            "version": "1",
            "source_type": "browser_observation",
            "authority": "external_verifier",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    now = datetime.now(UTC)
    with Session(service.engine) as session, session.begin():
        session.add(
            GoalTaskRow(
                id="task-browser",
                project_id="kjds-059",
                title="Browser acceptance",
                owner="engineering",
                verifier_id="browser",
                verifier_version="1",
                dependency_ids_json=["task-pytest"],
                verification_condition="fresh browser observation",
                next_safe_action="rerun after upstream verification",
                workspace="/runtime-graph",
                sla_seconds=3600,
                fingerprint=_sha(["task", "browser"]),
                created_at=now,
            )
        )
    common = {
        "project_id": "kjds-059",
        "scope": {"tenant_ref": "tenant-a", "store_ref": "store-a"},
        "state": "passed",
        "store_ref": "store-a",
    }
    upstream_at = now - timedelta(minutes=20)
    service.record_observation(
        {
            **common,
            "task_id": "task-pytest",
            "verifier_id": "pytest",
            "verifier_version": "1",
            "source": "pytest process log",
            "summary": "first source state passed",
            "input_sha256": "1" * 64,
            "artifact_ref": "output/pytest/first.log",
            "observed_at": upstream_at.isoformat(),
        },
        principal=principal(),
    )
    dependent_at = now - timedelta(minutes=10)
    service.record_observation(
        {
            **common,
            "task_id": "task-browser",
            "verifier_id": "browser",
            "verifier_version": "1",
            "source": "browser observation",
            "summary": "browser accepted first source state",
            "input_sha256": "2" * 64,
            "artifact_ref": "evidence/browser-first.md",
            "observed_at": dependent_at.isoformat(),
        },
        principal=principal(),
    )
    before = service.workspace(
        "kjds-059",
        principal=principal(roles=frozenset({"operator"})),
        store_ref="store-a",
        as_of=now - timedelta(minutes=5),
    )
    assert before["counts"]["passed"] == 2

    changed_at = now
    service.record_observation(
        {
            **common,
            "task_id": "task-pytest",
            "verifier_id": "pytest",
            "verifier_version": "1",
            "source": "pytest process log",
            "summary": "changed source state independently passed",
            "input_sha256": "3" * 64,
            "artifact_ref": "output/pytest/changed.log",
            "observed_at": changed_at.isoformat(),
        },
        principal=principal(),
    )
    after = service.workspace(
        "kjds-059",
        principal=principal(roles=frozenset({"operator"})),
        store_ref="store-a",
        as_of=changed_at + timedelta(seconds=1),
    )
    tasks = {item["id"]: item for item in after["tasks"]}
    assert tasks["task-pytest"]["state"] == "passed"
    assert tasks["task-browser"]["state"] == "stale"
    assert "upstream_changed:task-pytest" in tasks["task-browser"]["blockers"]
    assert after["counts"]["passed"] == 1
    assert after["counts"]["stale"] == 1


def test_inferred_edge_is_exploratory_and_scope_fails_closed():
    service = harness()
    view = service.workspace(
        "kjds-059",
        principal=principal(roles=frozenset({"operator"})),
        store_ref="store-a",
        graph_kind="engineering",
        as_of=datetime.now(UTC),
    )
    assert view["edges"][0]["can_satisfy_gate"] is False
    with pytest.raises(PermissionError):
        service.workspace(
            "kjds-059",
            principal=principal(
                roles=frozenset({"operator"}),
                stores=frozenset({"store-b"}),
            ),
            store_ref="store-b",
            as_of=datetime.now(UTC),
        )


def test_unregistered_or_wrong_verifier_cannot_self_certify():
    service = harness()
    with pytest.raises(ValueError, match="registered verifier"):
        service.record_observation(
            {
                "project_id": "kjds-059",
                "task_id": "task-pytest",
                "verifier_id": "model",
                "verifier_version": "self-report",
                "source": "model narration",
                "scope": {"tenant_ref": "tenant-a"},
                "state": "passed",
                "summary": "I say it passed",
                "input_sha256": "2" * 64,
                "artifact_ref": "none",
                "observed_at": datetime.now(UTC).isoformat(),
                "store_ref": "store-a",
            },
            principal=principal(),
        )


def test_node_status_binding_is_immutable_and_project_scoped():
    service = harness()
    service.bind_node_status(
        project_id="kjds-059",
        node_id="node-project",
        task_id="task-pytest",
    )
    with Session(service.engine) as session, session.begin():
        session.add(
            GoalTaskRow(
                id="task-other",
                project_id="kjds-059",
                title="Other verifier task",
                owner="engineering",
                verifier_id="pytest",
                verifier_version="1",
                dependency_ids_json=[],
                verification_condition="independent verification",
                next_safe_action="observe",
                workspace="/project-graph",
                sla_seconds=None,
                fingerprint=_sha(["task", "other"]),
                created_at=datetime.now(UTC),
            )
        )
    with pytest.raises(ValueError, match="create a new node version"):
        service.bind_node_status(
            project_id="kjds-059",
            node_id="node-project",
            task_id="task-other",
        )
    with pytest.raises(KeyError, match="outside project"):
        service.bind_node_status(
            project_id="kjds-059",
            node_id="missing-node",
            task_id="task-pytest",
        )


def test_operating_subject_binding_is_append_only_scoped_and_as_of_stable():
    service = harness()
    admin = principal(
        actor="admin-a",
        roles=frozenset({"admin"}),
    )
    operator = principal(
        actor="operator-a",
        roles=frozenset({"operator"}),
    )
    monitor = principal()
    effective_at = datetime.now(UTC) - timedelta(minutes=1)

    first = service.record_operating_subject_event(
        project_id="kjds-059",
        principal=admin,
        subject=operator,
        event_type="bind",
        effective_at=effective_at,
        reason="bind the registered operating operator",
        idempotency_key="bind-operator-a",
    )
    replay = service.record_operating_subject_event(
        project_id="kjds-059",
        principal=admin,
        subject=operator,
        event_type="bind",
        effective_at=effective_at,
        reason="bind the registered operating operator",
        idempotency_key="bind-operator-a",
    )
    assert replay == {**first, "idempotent": True}

    before = service.operating_subject(
        project_id="kjds-059",
        principal=monitor,
        as_of=effective_at - timedelta(seconds=1),
    )
    current = service.operating_subject(
        project_id="kjds-059",
        principal=monitor,
        as_of=effective_at + timedelta(seconds=1),
    )
    assert before["status"] == "no_data"
    assert current["status"] == "ready"
    assert current["subject_actor_id"] == "operator-a"
    assert len(current["authority_sha256"]) == 64
    assert current["external_write_allowed"] is False

    with pytest.raises(ValueError, match="revoke the current"):
        service.record_operating_subject_event(
            project_id="kjds-059",
            principal=admin,
            subject=operator,
            event_type="bind",
            effective_at=effective_at + timedelta(seconds=2),
            reason="attempt a second active bind",
            idempotency_key="bind-operator-a-again",
        )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        service.record_operating_subject_event(
            project_id="kjds-059",
            principal=admin,
            subject=operator,
            event_type="revoke",
            effective_at=effective_at,
            reason="drift the immutable request",
            idempotency_key="bind-operator-a",
        )

    revoked_at = effective_at + timedelta(seconds=3)
    service.record_operating_subject_event(
        project_id="kjds-059",
        principal=admin,
        subject=operator,
        event_type="revoke",
        effective_at=revoked_at,
        reason="retire the project operating subject",
        idempotency_key="revoke-operator-a",
    )
    revoked = service.operating_subject(
        project_id="kjds-059",
        principal=monitor,
        as_of=revoked_at + timedelta(seconds=1),
    )
    assert revoked["status"] == "no_data"
    assert revoked["reason"] == "operating_subject_binding_missing"


def test_operating_subject_binding_rejects_recorder_and_scope_escalation():
    service = harness()
    operator = principal(
        actor="operator-a",
        roles=frozenset({"operator"}),
    )
    now = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(PermissionError, match="admin role"):
        service.record_operating_subject_event(
            project_id="kjds-059",
            principal=operator,
            subject=operator,
            event_type="bind",
            effective_at=now,
            reason="self bind",
            idempotency_key="self-bind",
        )
    with pytest.raises(PermissionError, match="outside authorized scope"):
        service.record_operating_subject_event(
            project_id="kjds-059",
            principal=principal(
                actor="admin-b",
                roles=frozenset({"admin"}),
                tenant="tenant-b",
            ),
            subject=operator,
            event_type="bind",
            effective_at=now,
            reason="cross tenant",
            idempotency_key="cross-tenant",
        )
    with pytest.raises(ValueError, match="non-admin, non-monitor operator"):
        service.record_operating_subject_event(
            project_id="kjds-059",
            principal=principal(
                actor="admin-a",
                roles=frozenset({"admin"}),
            ),
            subject=principal(
                actor="monitor-b",
                roles=frozenset({"operator", "monitor"}),
            ),
            event_type="bind",
            effective_at=now,
            reason="privileged subject",
            idempotency_key="privileged-subject",
        )
