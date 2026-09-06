from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.control_plane.project_graph_proposal_ledger import (
    ProjectGraphProposalConflict,
    ProjectGraphProposalRow,
    SqlProjectGraphProposalLedger,
)


def ledger() -> SqlProjectGraphProposalLedger:
    return SqlProjectGraphProposalLedger.for_url("sqlite:///:memory:")


def proposal(*, status: str = "proposed") -> dict[str, object]:
    return {
        "contract_id": "kjds-project-graph-dispatch-wave-v1",
        "status": status,
        "tasks": [],
        "budget_units": Decimal("12.5000"),
        "external_write_allowed": False,
    }


def record(store: SqlProjectGraphProposalLedger, *, key: str = "key-1", request: str = "a" * 64, expected_revision: int | None = None, kind: str = "dispatch-wave"):
    return store.record(
        project_id="project-1",
        tenant_id="tenant-1",
        entity_id="entity-1",
        store_ref="store-1",
        kind=kind,
        idempotency_key=key,
        request_sha256=request,
        proposal=proposal(),
        proposal_sha256="b" * 64,
        graph_snapshot_sha256="c" * 64,
        recorded_by="operator-1",
        observed_at=datetime(2026, 9, 6, tzinfo=UTC),
        expected_revision=expected_revision,
    )


def test_record_replay_preserves_exact_json_and_decimal_precision() -> None:
    store = ledger()
    first = record(store)
    replay = store.record(
        project_id="project-1",
        tenant_id="tenant-1",
        entity_id="entity-1",
        store_ref="store-1",
        kind="dispatch-wave",
        idempotency_key="key-1",
        request_sha256="a" * 64,
        proposal={"status": "changed", "budget_units": Decimal("99")},
        proposal_sha256="d" * 64,
        recorded_by="another-worker",
    )

    assert first["proposal_id"] == replay["proposal_id"]
    assert first["revision"] == replay["revision"] == 1
    assert first["payload"] == replay["payload"]
    assert first["payload"]["budget_units"] == "12.5000"
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert len(store.history(
        tenant_id="tenant-1",
        project_id="project-1",
        entity_id="entity-1",
        store_ref="store-1",
    )) == 1


def test_key_reuse_with_changed_request_is_a_structured_conflict() -> None:
    store = ledger()
    record(store)
    with pytest.raises(ProjectGraphProposalConflict) as caught:
        record(store, request="d" * 64)
    assert caught.value.http_status_code == 409
    assert caught.value.http_detail["code"] == "project_graph_proposal_conflict"


def test_expected_revision_is_compare_and_swap_per_kind() -> None:
    store = ledger()
    record(store, expected_revision=0)
    with pytest.raises(ProjectGraphProposalConflict, match="revision is stale"):
        record(store, key="key-2", expected_revision=0)
    second = record(store, key="key-2", expected_revision=1)
    assert second["revision"] == 2
    invalidation = record(
        store,
        key="invalid-1",
        kind="invalidation",
        expected_revision=0,
    )
    assert invalidation["revision"] == 1


def test_scope_isolation_prevents_cross_tenant_replay() -> None:
    store = ledger()
    record(store)
    with pytest.raises(KeyError):
        store.replay(
            tenant_id="tenant-2",
            project_id="project-1",
            entity_id="entity-1",
            store_ref="store-1",
            kind="dispatch-wave",
            idempotency_key="key-1",
        )
    assert store.history(
        tenant_id="tenant-2",
        project_id="project-1",
        entity_id="entity-1",
        store_ref="store-1",
    ) == ()


def test_history_is_bounded_and_ordered() -> None:
    store = ledger()
    first = record(store, key="key-1")
    second = store.record(
        project_id="project-1",
        tenant_id="tenant-1",
        entity_id="entity-1",
        store_ref="store-1",
        kind="dispatch-wave",
        idempotency_key="key-2",
        request_sha256="d" * 64,
        proposal=proposal(status="blocked"),
        proposal_sha256="e" * 64,
        recorded_by="operator-1",
        observed_at=datetime(2026, 9, 6, tzinfo=UTC) + timedelta(seconds=1),
    )
    rows = store.history(
        tenant_id="tenant-1",
        project_id="project-1",
        entity_id="entity-1",
        store_ref="store-1",
        limit=1,
    )
    assert [row["proposal_id"] for row in rows] == [first["proposal_id"]]
    assert second["revision"] == 2


def test_external_write_flag_is_rejected_before_insert() -> None:
    store = ledger()
    with pytest.raises(ValueError, match="cannot allow external writes"):
        store.record(
            project_id="project-1",
            tenant_id="tenant-1",
            entity_id="entity-1",
            store_ref="store-1",
            kind="dispatch-wave",
            idempotency_key="unsafe",
            request_sha256="a" * 64,
            proposal={"external_write_allowed": True},
            proposal_sha256="b" * 64,
        )
    assert store.history(
        tenant_id="tenant-1",
        project_id="project-1",
        entity_id="entity-1",
        store_ref="store-1",
    ) == ()


def test_model_exposes_append_only_scope_constraints() -> None:
    names = {item.name for item in ProjectGraphProposalRow.__table__.constraints}
    assert "uq_graph_proposal_scope_idempotency" in names
    assert "uq_graph_proposal_scope_revision" in names
    assert "ck_graph_proposal_external_write_forbidden" in names
