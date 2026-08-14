from __future__ import annotations

from copy import deepcopy

from apps.control_plane.operating_gate_verifier import OperatingStageVerifier

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


def _workspace(*, ready: bool = False) -> dict:
    status = "completed" if ready else "blocked"
    stages = [
        {
            "id": stage_id,
            "status": status,
            "qualified_record_count": 1 if ready else 0,
            "why": "verified" if ready else "not yet verified",
            "owner": f"{stage_id}-owner",
            "next_action": f"complete {stage_id}",
            "workspace_href": "/commerce-os",
            "client_recalculation_allowed": False,
            "external_write_allowed": False,
        }
        for stage_id in STAGE_IDS
    ]
    if not ready:
        stages[0]["status"] = "no_data"
    return {
        "contract_version": "commerce-operating-system/1.0.0",
        "status": "ready" if ready else "no_data",
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a" if ready else None,
            "store_ref": "store-a",
        },
        "stages": stages,
        "source_snapshots": {
            "truth_governance": "a" * 64 if ready else "b" * 64,
        },
        "formal_facts": {
            "status": "ready" if ready else "no_data",
            "formal_fact_count": 1 if ready else 0,
            "snapshot_sha256": "c" * 64 if ready else "d" * 64,
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
        "completion_claim": {
            "real_profit_loop_complete": ready,
        },
        "snapshot_sha256": "e" * 64,
    }


def _counts(value: int = 0) -> dict[str, int]:
    return {
        key: value
        for key in OperatingStageVerifier.SUPPORT_KEYS
    }


def _evaluate(workspace: dict, counts: dict[str, int], bucket: str = "2026-07-28T08:00:00+00:00"):
    return OperatingStageVerifier().evaluate(
        workspace=workspace,
        support_counts=counts,
        observation_bucket=bucket,
    )


def test_empty_scoped_workspace_is_no_data_then_blocked() -> None:
    result = _evaluate(_workspace(), _counts())

    assert result["status"] == "blocked"
    assert result["gates"]["m0"]["state"] == "no_data"
    assert [result["gates"][f"m{index}"]["state"] for index in range(1, 5)] == [
        "blocked",
        "blocked",
        "blocked",
        "blocked",
    ]
    assert result["external_write_allowed"] is False
    assert result["model_self_certification_allowed"] is False


def test_partial_data_cannot_skip_or_pass_a_gate() -> None:
    workspace = _workspace()
    workspace["scope"]["entity_ref"] = "entity-a"
    counts = _counts()
    counts["scope_grants"] = 1
    counts["native_products"] = 1
    counts["native_imports"] = 1
    for stage in workspace["stages"]:
        if stage["id"] in {"observe", "identity", "qualify", "item_draft"}:
            stage["status"] = "completed"
            stage["qualified_record_count"] = 1

    result = _evaluate(workspace, counts)

    assert result["gates"]["m0"]["state"] == "passed"
    assert result["gates"]["m1"]["state"] == "blocked"
    assert "support_count_zero:native_facts" in result["gates"]["m1"]["blockers"]
    assert result["gates"]["m2"]["state"] == "blocked"
    assert "upstream_gate_not_passed" in result["gates"]["m2"]["blockers"]


def test_all_real_authorities_are_required_for_full_pass() -> None:
    result = _evaluate(_workspace(ready=True), _counts(1))

    assert result["status"] == "passed"
    assert {item["state"] for item in result["gates"].values()} == {"passed"}
    assert len(result["result_sha256"]) == 64


def test_completed_downstream_stages_do_not_bypass_upstream() -> None:
    workspace = _workspace(ready=True)
    workspace["stages"][1]["status"] = "blocked"
    workspace["stages"][1]["qualified_record_count"] = 0

    result = _evaluate(workspace, _counts(1))

    assert result["gates"]["m0"]["state"] == "blocked"
    for gate_id in ("m1", "m2", "m3", "m4"):
        assert result["gates"][gate_id]["state"] == "blocked"
        assert "upstream_gate_not_passed" in result["gates"][gate_id]["blockers"]


def test_contract_drift_and_open_external_write_fail_closed() -> None:
    for mutate in (
        lambda workspace: workspace["stages"].pop(),
        lambda workspace: workspace["stages"].append(
            deepcopy(workspace["stages"][0])
        ),
        lambda workspace: workspace["control_envelope"].update(
            {"external_writes": True}
        ),
    ):
        workspace = _workspace(ready=True)
        mutate(workspace)

        result = _evaluate(workspace, _counts(1))

        assert result["status"] == "failed"
        assert {item["state"] for item in result["gates"].values()} == {"failed"}
        assert result["external_write_allowed"] is False


def test_hash_is_deterministic_and_changes_with_real_inputs() -> None:
    workspace = _workspace(ready=True)
    counts = _counts(1)
    first = _evaluate(workspace, counts)
    replay = _evaluate(deepcopy(workspace), dict(counts))

    assert replay["result_sha256"] == first["result_sha256"]
    assert (
        replay["gates"]["m2"]["input_sha256"]
        == first["gates"]["m2"]["input_sha256"]
    )

    changed_counts = dict(counts)
    changed_counts["listing_drafts"] = 2
    count_change = _evaluate(workspace, changed_counts)
    next_bucket = _evaluate(
        workspace,
        counts,
        bucket="2026-07-28T09:00:00+00:00",
    )

    assert count_change["result_sha256"] != first["result_sha256"]
    assert (
        count_change["gates"]["m2"]["input_sha256"]
        != first["gates"]["m2"]["input_sha256"]
    )
    assert next_bucket["result_sha256"] != first["result_sha256"]
