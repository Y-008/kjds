from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.control_plane.agent_harness import (
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    OperatingSubjectBindingEventRow,
)
from apps.control_plane.operating_gate_bootstrap import (
    PROJECT_ID,
    bootstrap_operating_gate,
    require_g1_database,
)
from apps.control_plane.security import Principal


@pytest.fixture
def engine(tmp_path):
    target = create_engine(f"sqlite+pysqlite:///{tmp_path / 'bootstrap.db'}")
    GraphProjectRow.metadata.create_all(
        target,
        tables=[
            GraphProjectRow.__table__,
            GoalTaskRow.__table__,
            GraphNodeRow.__table__,
            GraphEdgeRow.__table__,
            OperatingSubjectBindingEventRow.__table__,
        ],
    )
    return target


def _principals() -> tuple[Principal, Principal]:
    return (
        Principal(
            actor_id="g1-verifier",
            roles=frozenset({"admin"}),
            tenant_ref="default",
            store_refs=frozenset({"ozon-primary"}),
        ),
        Principal(
            actor_id="g1-operating-subject",
            roles=frozenset({"operator"}),
            tenant_ref="default",
            store_refs=frozenset({"ozon-primary"}),
        ),
    )


def test_bootstrap_creates_minimum_graph_and_is_idempotent(engine) -> None:
    admin, subject = _principals()
    now = datetime(2026, 8, 2, 8, tzinfo=UTC)

    first = bootstrap_operating_gate(
        engine=engine,
        admin=admin,
        operating_subject=subject,
        now=now,
    )
    replay = bootstrap_operating_gate(
        engine=engine,
        admin=admin,
        operating_subject=subject,
        now=now,
    )

    assert first == replay
    assert first["counts"] == {
        "projects": 1,
        "tasks": 7,
        "nodes": 7,
        "edges": 6,
        "subject_binding_events": 1,
    }
    assert first["external_write_allowed"] is False
    assert first["model_self_certification_allowed"] is False
    assert len(first["subject_binding_sha256"]) == 64


def test_bootstrap_rejects_structural_drift(engine) -> None:
    admin, subject = _principals()
    now = datetime(2026, 8, 2, 8, tzinfo=UTC)
    bootstrap_operating_gate(
        engine=engine,
        admin=admin,
        operating_subject=subject,
        now=now,
    )
    with Session(engine) as session, session.begin():
        project = session.get(GraphProjectRow, PROJECT_ID)
        assert project is not None
        project.store_ref = "other-store"

    with pytest.raises(RuntimeError, match="graph project drifted: store_ref"):
        bootstrap_operating_gate(
            engine=engine,
            admin=admin,
            operating_subject=subject,
            now=now,
        )


def test_bootstrap_rejects_monitor_as_operating_subject(engine) -> None:
    admin, subject = _principals()
    monitor = Principal(
        actor_id=subject.actor_id,
        roles=frozenset({"operator", "monitor"}),
        tenant_ref=subject.tenant_ref,
        store_refs=subject.store_refs,
    )

    with pytest.raises(
        PermissionError, match="separate non-admin operator"
    ):
        bootstrap_operating_gate(
            engine=engine,
            admin=admin,
            operating_subject=monitor,
            now=datetime(2026, 8, 2, 8, tzinfo=UTC),
        )
    with Session(engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(GraphProjectRow))
            == 0
        )


def test_g1_database_guard_rejects_non_disposable_database(engine) -> None:
    with pytest.raises(RuntimeError, match="restricted to the disposable"):
        require_g1_database(engine)
