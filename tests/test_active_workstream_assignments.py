import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "active_workstream_assignments.json"
)
PLAN_PATH = ROOT / "docs" / "project" / "03_REMAINING_WORK_AND_PARALLEL_PLAN.md"


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_workstream_registry_has_five_single_wip_lanes():
    registry = _registry()
    lanes = registry["lanes"]

    assert registry["schema_version"] == "kjds-active-workstream-assignments-v1"
    assert registry["policy"]["max_current_tasks_per_lane"] == 1
    assert {lane["id"] for lane in lanes} == {"A", "B", "C", "D", "E"}
    assert len(lanes) == 5
    assert len({lane["name"] for lane in lanes}) == 5

    current_tasks = [lane["current_task"] for lane in lanes if lane["current_task"]]
    task_ids = [task["task_id"] for task in current_tasks]
    assert len(task_ids) == len(set(task_ids))
    assert all(task["state"] in {"active_blocked", "in_progress_preparation_only"} for task in current_tasks)


def test_current_and_next_tasks_exist_in_the_dynamic_plan():
    registry = _registry()
    plan = PLAN_PATH.read_text(encoding="utf-8")

    for lane in registry["lanes"]:
        current = lane["current_task"]
        if current:
            assert f"| {current['task_id']} |" in plan
        next_task_id = lane.get("next_task_id")
        if next_task_id:
            assert f"| {next_task_id} |" in plan

    assert "| DAY0-TRUTH-20260802 |" in plan
    assert "| PARTIAL_BLOCKED |" in plan
    assert "| COM-001 |" in plan
    assert "| IN_PROGRESS_PREP_ONLY |" in plan


def test_commercial_lane_cannot_sell_before_c0():
    lanes = {lane["id"]: lane for lane in _registry()["lanes"]}
    commercial = lanes["B"]["current_task"]

    assert commercial["task_id"] == "COM-001"
    assert commercial["state"] == "in_progress_preparation_only"
    assert commercial["blocked_on"] == ["c0_commercial_pilot_gate"]
    assert "payment" not in commercial["write_scope"]
    assert "invoice" not in commercial["write_scope"]


def test_shared_write_leases_and_authority_stay_fail_closed():
    registry = _registry()
    assert set(registry["shared_write_leases"]) == {
        "alembic_migration",
        "api_aggregation_root",
        "master_spec",
        "openapi_snapshot",
    }
    assert all(owner is None for owner in registry["shared_write_leases"].values())
    assert registry["policy"]["legacy_in_progress_is_execution_lease"] is False
    assert registry["policy"]["current_task_is_execution_lease"] is True
    assert registry["policy"]["external_write_allowed"] is False
    assert all(value is False for value in registry["control_boundary"].values())
