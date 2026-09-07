from datetime import UTC, datetime

import pytest

from apps.control_plane.operating_snapshot import (
    OperatingSnapshotError,
    build_operating_snapshot,
)


def _payload(**overrides):
    value = {
        "project_id": "project-a",
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "observed_at": datetime(2026, 9, 7, 12, tzinfo=UTC),
        "exact_head": "a" * 40,
        "migration_head": "migration-20260907",
        "graph_snapshot_sha256": "b" * 64,
        "proof_state": "PROVED",
        "evidence_state": "VALID",
        "operational_state": "LIVE",
        "economic_state": "ALLOWED",
        "rollback_available": True,
        "external_readback_passed": True,
        "task_frontier": ["task-a"],
        "critical_path": ["task-a"],
        "test_receipts": ["test://receipt"],
        "proof_receipts": ["proof://receipt"],
        "evidence_refs": ["evidence://receipt"],
    }
    value.update(overrides)
    return value


def test_snapshot_is_deterministic_and_admission_is_explicit():
    first = build_operating_snapshot(_payload())
    second = build_operating_snapshot(first.as_dict())
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.admission_state == "LIVE"
    assert first.as_dict()["external_write_allowed"] is False


def test_any_missing_gate_holds_without_collapsing_states():
    snapshot = build_operating_snapshot(_payload(evidence_state="STALE"))
    assert snapshot.admission_state == "HOLD"
    assert snapshot.proof_state == "PROVED"
    assert snapshot.evidence_state == "STALE"


def test_snapshot_rejects_hash_tampering_and_authority_fields():
    with pytest.raises(OperatingSnapshotError, match="does not match"):
        build_operating_snapshot(_payload(snapshot_sha256="c" * 64))
    with pytest.raises(OperatingSnapshotError, match="authority"):
        build_operating_snapshot(_payload(blockers=[{"permit": "x"}]))
