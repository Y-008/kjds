from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.native_parity_acceptance import (
    ACCEPTANCE_DIMENSIONS,
    NativeParityAcceptanceError,
    NativeParityAcceptanceWorkspace,
)
from apps.control_plane.security import Principal

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
BASE = {"tenant_ref": "tenant-1", "entity_ref": "entity-1", "store_ref": "store-1"}
IDENTITY = {"provider_id": "ozon", "capability_id": "listing.publish", "capability_version": "v1"}
PRINCIPAL = Principal("operator-1", frozenset({"operator"}), "tenant-1", frozenset({"store-1"}))
ENTITY_SCOPE = {
    "status": "ready",
    **BASE,
    "authority_sha256": "f" * 64,
}


class MemoryRecords:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def read_records(self, **query):
        self.calls.append(query)
        return deepcopy(self.rows)


def signed(row: dict) -> dict:
    result = deepcopy(row)
    result["record_sha256"] = NativeParityAcceptanceWorkspace._hash(result)
    return result


def mapping(identity: dict = IDENTITY, *, gated: bool = False) -> dict:
    return signed(
        {
            **BASE,
            **identity,
            "record_kind": "mapping",
            "record_id": f"mapping-{identity['capability_id']}",
            "sequence": 1,
            "recorded_at": NOW - timedelta(hours=2),
            "status": "mapped",
            "gate_status": "gated" if gated else None,
        }
    )


def observation(
    dimension: str,
    identity: dict = IDENTITY,
    *,
    sequence: int = 1,
    status: str = "passed",
    expires_at: datetime | None = None,
    verifier_id: str = "external-verifier",
    producer_id: str = "build-system",
    binding: str = "a" * 64,
) -> dict:
    return signed(
        {
            **BASE,
            **identity,
            "record_kind": "observation",
            "record_id": f"{identity['capability_id']}-{dimension}-{sequence}",
            "dimension": dimension,
            "sequence": sequence,
            "recorded_at": NOW - timedelta(hours=1) + timedelta(minutes=sequence),
            "expires_at": expires_at or NOW + timedelta(days=1),
            "status": status,
            "producer_id": producer_id,
            "verifier_id": verifier_id,
            "verifier_kind": "external_graph" if dimension == "external_graph_verifier" else "external_harness",
            "acceptance_input_sha256": binding,
            "subject_sha256": "b" * 64,
            "evidence_sha256": "c" * 64,
        }
    )


def complete(identity: dict = IDENTITY) -> list[dict]:
    return [mapping(identity), *(observation(item, identity) for item in ACCEPTANCE_DIMENSIONS)]


def authority(rows: list[dict]):
    adapter = MemoryRecords(rows)
    return NativeParityAcceptanceWorkspace(records=adapter, external_verifier_ids={"external-verifier"}), adapter


def project(workspace: NativeParityAcceptanceWorkspace, **changes):
    request = {
        "principal": PRINCIPAL,
        "entity_scope": ENTITY_SCOPE,
        "store_ref": "store-1",
        "as_of": NOW,
    }
    request.update(changes)
    return workspace.project(**request)


def test_complete_bundle_is_verified_stable_and_read_only() -> None:
    workspace, adapter = authority(complete())
    first = project(workspace)
    assert first == project(workspace)
    item = first["items"][0]
    assert item["state"] == "verified_native"
    assert item["counts"]["passed_dimensions"] == 8
    assert first["counts"]["states"]["verified_native"] == 1
    assert first["provider_counts"] == {"ozon": 1}
    assert first["control_envelope"]["external_write_allowed"] is False
    assert adapter.calls[0] == {**BASE, "as_of": NOW}


def test_mapping_gated_and_partial_never_promote() -> None:
    mapped, _ = authority([mapping()])
    gated, _ = authority([mapping(gated=True)])
    partial, _ = authority([mapping(), observation("code")])
    assert project(mapped)["items"][0]["state"] == "mapped"
    assert project(gated)["items"][0]["state"] == "gated"
    item = project(partial)["items"][0]
    assert item["state"] == "implemented_unverified"
    assert item["verified_native"] is False
    assert len(item["missing_dimensions"]) == 7


@pytest.mark.parametrize(
    ("latest", "expected"),
    [
        (observation("code", sequence=2, status="failed"), "blocked"),
        (observation("code", sequence=2, expires_at=NOW - timedelta(seconds=1)), "stale"),
        (observation("code", sequence=2, binding="d" * 64), "blocked"),
        (
            observation("code", sequence=2, producer_id="external-verifier", verifier_id="external-verifier"),
            "blocked",
        ),
    ],
)
def test_latest_failed_stale_drift_and_self_certification_fail_closed(latest, expected) -> None:
    workspace, _ = authority([*complete(), latest])
    item = project(workspace)["items"][0]
    assert item["state"] == expected
    assert item["verified_native"] is False


def test_bad_latest_hash_blocks_without_falling_back() -> None:
    latest = observation("runtime_replay", sequence=2)
    latest["record_sha256"] = "0" * 64
    workspace, _ = authority([*complete(), latest])
    item = project(workspace)["items"][0]
    assert item["state"] == "blocked"
    assert item["counts"]["invalid_records"] == 1


def test_scope_is_principal_owned_and_missing_entity_is_zero_read() -> None:
    workspace, adapter = authority([])
    empty = project(workspace, entity_scope={"status": "no_data"})
    assert empty["status"] == "no_data"
    assert empty["items"] == []
    assert adapter.calls == []
    other = Principal("other", frozenset({"operator"}), "tenant-2", frozenset({"store-1"}))
    with pytest.raises(PermissionError, match="not authoritative"):
        project(workspace, principal=other)
    assert adapter.calls == []


def test_adapter_cross_scope_record_fails_closed() -> None:
    row = mapping()
    row["tenant_ref"] = "tenant-2"
    row.pop("record_sha256")
    workspace, _ = authority([signed(row)])
    with pytest.raises(NativeParityAcceptanceError, match="cross_scope"):
        project(workspace)


def test_multiple_capabilities_server_filter_counts_cursor_and_artifacts() -> None:
    second = {**IDENTITY, "capability_id": "inventory.read"}
    workspace, _ = authority([*complete(), *complete(second)])
    first = project(workspace, page_size=1)
    second_page = project(workspace, page_size=1, cursor=first["next_cursor"])
    assert first["counts"]["items"] == 2
    assert first["provider_counts"] == {"ozon": 2}
    assert first["capability_counts"] == {"inventory.read": 1, "listing.publish": 1}
    assert first["items"][0]["scope"]["capability_id"] != second_page["items"][0]["scope"]["capability_id"]
    filtered = project(workspace, capability_id="inventory.read", status="verified_native")
    assert [item["scope"]["capability_id"] for item in filtered["items"]] == ["inventory.read"]
    with pytest.raises(NativeParityAcceptanceError, match="Cursor does not match"):
        project(workspace, provider_id="ozon", cursor=first["next_cursor"])


def test_bad_request_rejected_before_read() -> None:
    workspace, adapter = authority([])
    with pytest.raises(NativeParityAcceptanceError):
        project(workspace, as_of="bad")
    with pytest.raises(NativeParityAcceptanceError):
        project(workspace, page_size=0)
    with pytest.raises(PermissionError):
        project(workspace, store_ref="other-store")
    assert adapter.calls == []
