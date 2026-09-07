from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.control_plane.ozon_acceptance_snapshot import (
    OzonAcceptanceSnapshotError,
    build_snapshot,
    freeze_snapshot,
    read_artifact_binding,
    validate_snapshot,
)

CAPTURED = datetime(2026, 9, 7, 1, 0, tzinfo=UTC)
HEAD = "a" * 40
SCHEMA = "b" * 64
RAW = "c" * 64
GRAPH = "d" * 64
OBSERVE = "e" * 64
LEASE_ID = "f" * 64


def _lease(status: str = "ready") -> dict[str, object]:
    return {
        "contract_id": "kjds-channel-account-managed-credential-lease-v2",
        "issuer": "control-plane",
        "key_id": "acceptance-key",
        "status": status,
        "lease_fresh": True,
        "managed_store_bound": True,
        "credential_material_returned": "false",
        "lease_id_sha256": LEASE_ID,
    }


def _build(path: Path, **changes):
    values = {
        "canonical_head": HEAD,
        "api_version": "v1",
        "schema_sha256": SCHEMA,
        "migration_head": "20260907_0120",
        "browser_artifact_path": path,
        "browser_raw_sha256": RAW,
        "browser_observed_at": CAPTURED - timedelta(minutes=1),
        "graph_snapshot_sha256": GRAPH,
        "observe_receipt_sha256": OBSERVE,
        "lease_projection": _lease(),
        "captured_at": CAPTURED,
        "as_of": CAPTURED,
    }
    values.update(changes)
    return build_snapshot(**values)


def _current(path: Path, **changes):
    values = {
        "current_canonical_head": HEAD,
        "current_api_version": "v1",
        "current_schema_sha256": SCHEMA,
        "current_migration_head": "20260907_0120",
        "current_browser_artifact_path": path,
        "current_browser_raw_sha256": RAW,
        "current_graph_snapshot_sha256": GRAPH,
        "current_observe_receipt_sha256": OBSERVE,
        "current_lease_projection": _lease(),
    }
    values.update(changes)
    return values


def test_snapshot_is_deterministic_and_recursively_immutable(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b'{"items": []}')
    first = _build(artifact)
    second = _build(artifact)

    assert first == second
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert len(first.snapshot_sha256) == 64
    assert first["external_write_allowed"] is False
    with pytest.raises(TypeError):
        first["canonical_head"] = "0" * 40  # type: ignore[index]
    with pytest.raises(TypeError):
        first["browser_artifact"]["file_sha256"] = "0" * 64  # type: ignore[index]
    detached = first.to_dict()
    detached["browser_artifact"]["path"] = "changed"
    assert first["browser_artifact"]["path"] != "changed"
    assert freeze_snapshot(first) is first


def test_file_and_raw_hashes_are_bound_and_drift_is_reported(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"before")
    snapshot = _build(artifact)
    assert validate_snapshot(snapshot, **_current(artifact), now=CAPTURED) ["valid"] is True

    artifact.write_bytes(b"after")
    report = validate_snapshot(snapshot, **_current(artifact), now=CAPTURED)
    assert report["status"] == "drifted"
    assert "browser_artifact_file_hash_drift" in report["blockers"]

    report = validate_snapshot(snapshot, **_current(artifact, current_browser_raw_sha256="0" * 64), now=CAPTURED)
    assert "browser_artifact_file_hash_drift" in report["blockers"]
    assert "browser_artifact_raw_hash_drift" in report["blockers"]


@pytest.mark.parametrize(
    ("field", "kwargs", "code"),
    [
        ("head", {"current_canonical_head": "0" * 40}, "canonical_head_drift"),
        ("api", {"current_api_version": "v2"}, "api_version_drift"),
        ("schema", {"current_schema_sha256": "0" * 64}, "schema_sha256_drift"),
        ("migration", {"current_migration_head": "20260908_0001"}, "migration_head_drift"),
        ("graph", {"current_graph_snapshot_sha256": "0" * 64}, "graph_snapshot_hash_drift"),
        ("observe", {"current_observe_receipt_sha256": "0" * 64}, "observe_receipt_hash_drift"),
        ("lease", {"current_lease_projection": _lease("revoked")}, "lease_projection_drift"),
    ],
)
def test_each_bound_identity_has_an_independent_drift_code(tmp_path: Path, field, kwargs, code) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"artifact")
    snapshot = _build(artifact)
    report = validate_snapshot(snapshot, **_current(artifact, **kwargs), now=CAPTURED)
    assert report["status"] == "drifted", field
    assert code in report["blockers"], field


def test_time_checks_cover_future_and_stale_snapshots(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"artifact")
    snapshot = _build(artifact)
    future = validate_snapshot(snapshot, **_current(artifact), now=CAPTURED - timedelta(seconds=1))
    assert future["status"] == "drifted"
    assert "snapshot_from_future" in future["blockers"]

    stale = validate_snapshot(
        snapshot,
        **_current(artifact),
        now=CAPTURED + timedelta(hours=2),
        max_age_seconds=60,
    )
    assert stale["status"] == "stale"
    assert stale["valid"] is False
    assert "snapshot_stale" in stale["blockers"]

    with pytest.raises(OzonAcceptanceSnapshotError, match="browser_observed_at"):
        _build(artifact, browser_observed_at=CAPTURED + timedelta(seconds=1))


def test_tampering_the_payload_cannot_reuse_the_old_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"artifact")
    snapshot = _build(artifact)
    tampered = snapshot.to_dict()
    tampered["canonical_head"] = "0" * 40
    report = validate_snapshot(tampered, **_current(artifact), now=CAPTURED)
    assert report["status"] == "drifted"
    assert "snapshot_hash_drift" in report["blockers"]
    with pytest.raises(OzonAcceptanceSnapshotError, match="snapshot_sha256"):
        freeze_snapshot(tampered)


def test_lease_projection_is_allow_listed_and_secret_free(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"artifact")
    snapshot = _build(artifact, lease_projection={**_lease(), "internal_note": "ignored"})
    assert "internal_note" not in snapshot["lease_projection"]
    assert "lease_id" not in snapshot["lease_projection"]
    with pytest.raises(OzonAcceptanceSnapshotError):
        _build(artifact, lease_projection={**_lease(), "api_key": "secret-value"})
    with pytest.raises(OzonAcceptanceSnapshotError):
        _build(artifact, lease_projection={**_lease(), "credential_material_returned": True})


def test_invalid_digest_or_missing_artifact_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"artifact")
    with pytest.raises(OzonAcceptanceSnapshotError):
        read_artifact_binding(artifact, raw_sha256="not-a-hash")
    with pytest.raises(OzonAcceptanceSnapshotError):
        _build(tmp_path / "missing.json")


def test_report_never_returns_current_raw_values(tmp_path: Path) -> None:
    artifact = tmp_path / "browser.json"
    artifact.write_bytes(b"visible browser text that must stay local")
    snapshot = _build(artifact)
    report = validate_snapshot(snapshot, **_current(artifact, current_api_version="v2"), now=CAPTURED)
    rendered = repr(report)
    assert "visible browser text" not in rendered
    assert report["credential_values_returned"] is False
    assert report["external_write_allowed"] is False
