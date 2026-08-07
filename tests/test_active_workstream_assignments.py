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


def test_workstream_registry_has_thirteen_single_wip_lanes():
    registry = _registry()
    lanes = registry["lanes"]

    assert registry["schema_version"] == "kjds-active-workstream-assignments-v1"
    assert registry["policy"]["max_current_tasks_per_lane"] == 1
    assert {lane["id"] for lane in lanes} == {
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
    }
    assert len(lanes) == 13
    assert len({lane["name"] for lane in lanes}) == 13

    current_tasks = [lane["current_task"] for lane in lanes if lane["current_task"]]
    task_ids = [task["task_id"] for task in current_tasks]
    assert len(task_ids) == len(set(task_ids))
    assert all(
        task["state"]
        in {"active_blocked", "in_progress_preparation_only", "in_progress"}
        for task in current_tasks
    )


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


def test_com002_release_restores_prep_only_c0_contract_without_shared_writes():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    commercial_platform = lanes["D"]

    assert commercial_platform["current_task"] == {
        "task_id": "COM-002",
        "state": "in_progress_preparation_only",
        "write_scope": [
            "commercial_pilot_deployment",
            "commercial_lifecycle",
            "customer_exit_export",
            "c0_engineering_evidence",
        ],
        "blocked_on": [
            "hosted_target_and_rpo_rto_decision",
            "payment_invoice_tax_contract_inputs",
            "contract_dpa_sla_review_authority",
        ],
    }
    assert commercial_platform["blocked_on"] == ["c0_commercial_pilot_gate"]
    assert "COM-002" not in registry["shared_write_leases"].values()


def test_social_platform_and_channel_operations_have_separate_lanes():
    lanes = {lane["id"]: lane for lane in _registry()["lanes"]}

    assert lanes["F"]["current_task"]["task_id"] == "BAS-178"
    assert lanes["G"]["current_task"]["task_id"] == "OPS-XHS-001"
    assert lanes["H"]["current_task"]["task_id"] == "OPS-DY-001"
    assert lanes["F"]["name"] == "social_intelligence_platform"
    assert lanes["G"]["name"] == "xiaohongshu_operations"
    assert lanes["H"]["name"] == "douyin_operations"
    assert lanes["I"]["current_task"]["task_id"] == "BAS-179"
    assert lanes["I"]["name"] == "russia_market_intelligence"


def test_bas185_release_frees_media_lane_without_shared_writes():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    media = lanes["J"]

    assert media["current_task"] is None
    assert media["next_task_id"] == "BAS-183"
    assert "BAS-185" not in registry["shared_write_leases"].values()


def test_bas196_release_frees_local_demo_lane():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    demo = lanes["K"]

    assert demo["current_task"] is None
    assert demo["next_task_id"] is None
    assert "BAS-196" not in registry["shared_write_leases"].values()


def test_bas201_release_frees_capital_allocation_lane_without_shared_writes():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    strategic = lanes["L"]

    assert strategic["current_task"] is None
    assert strategic["next_task_id"] is None
    assert "BAS-201" not in registry["shared_write_leases"].values()


def test_data_cov_002_release_frees_coverage_and_migration_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    coverage = lanes["M"]

    assert coverage["current_task"] is None
    assert coverage["next_task_id"] is None
    assert "DATA-COV-002" not in registry["shared_write_leases"].values()


def test_bas204_release_frees_closed_loop_and_migration_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"]["task_id"] == "BAS-210"
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] == "BAS-210"
    assert registry["shared_write_leases"]["master_spec"] is None
    assert registry["shared_write_leases"]["openapi_snapshot"] == "BAS-210"
    assert "BAS-204" not in registry["shared_write_leases"].values()

def test_bas210_claims_lane_c_with_exact_research_inbox_scope():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"] == {
        "task_id": "BAS-210",
        "state": "in_progress",
        "owner_thread_id": "019fc23a-1ea8-76b0-9688-c11d40eae3e4",
        "write_scope": [
            "evidence_research_role_query",
            "research_inbox_server_pagination",
            "research_inbox_reserved_evidence_fairness",
            "research_inbox_scope_no_data_tests",
            "bas210_remediation_evidence",
            "research_inbox_capture_scope_binding",
            "research_inbox_current_authority_route",
            "research_inbox_keyset_api_contract",
            "research_inbox_openapi_snapshot",
        ],
        "blocked_on": [],
    }
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] == "BAS-210"
    assert registry["shared_write_leases"]["openapi_snapshot"] == "BAS-210"
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["master_spec"] is None
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas210_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-210 |")
    )
    assert "apps/control_plane/evidence.py" in bas210_row
    assert "apps/control_plane/research_inbox.py" in bas210_row
    assert "20260807_BAS_210_RESEARCH_INBOX_PAGINATION.md" in bas210_row
    assert "apps/control_plane/routers/product_content.py" in bas210_row
    assert "docs/project/contracts/openapi-v1.json" in bas210_row
    assert "不改 migration/runtime/事实/外写" in bas210_row
    assert bas210_row.endswith("| IN_PROGRESS |")



def test_bas211_release_record_and_bas210_execution_are_preserved():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"]["task_id"] == "BAS-210"
    assert engineering["next_task_id"] is None
    assert "BAS-211" not in registry["shared_write_leases"].values()
    plan = PLAN_PATH.read_text(encoding="utf-8")
    assert "| BAS-211 |" in plan
    assert "`pg_shdepend`" in plan
    assert "禁止 `DROP OWNED`" in plan
    assert "| DONE_ENGINEERING |" in plan


def test_bas212_release_record_and_bas210_execution_are_preserved():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"]["task_id"] == "BAS-210"
    assert engineering["next_task_id"] is None
    assert "BAS-212" not in registry["shared_write_leases"].values()
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": "BAS-210",
        "master_spec": None,
        "openapi_snapshot": "BAS-210",
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas212_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-212 |")
    )
    assert "outbox_coverage.json" in bas212_row
    assert "internal_only" in bas212_row
    assert "e3100b04 full G-1 PASS" in bas212_row
    assert bas212_row.endswith("| DONE_ENGINEERING |")


def test_bas213_release_frees_lane_e_and_preserves_bas210_and_shared_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    risk = lanes["E"]
    engineering = lanes["C"]

    assert risk["current_task"] is None
    assert risk["next_task_id"] is None
    assert engineering["current_task"]["task_id"] == "BAS-210"
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": "BAS-210",
        "master_spec": None,
        "openapi_snapshot": "BAS-210",
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas213_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-213 |")
    )
    assert "frontier technology registry" in bas213_row
    assert "20260807_PROJECT_ENTRY_AND_FRONTIER_REVIEW_GOVERNANCE.md" in bas213_row
    assert "不升级依赖" in bas213_row
    assert bas213_row.endswith("| DONE_ENGINEERING |")


def test_shared_write_leases_and_authority_stay_fail_closed():
    registry = _registry()
    assert set(registry["shared_write_leases"]) == {
        "alembic_migration",
        "api_aggregation_root",
        "master_spec",
        "openapi_snapshot",
    }
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["openapi_snapshot"] == "BAS-210"
    assert registry["shared_write_leases"]["api_aggregation_root"] == "BAS-210"
    assert registry["shared_write_leases"]["master_spec"] is None
    assert registry["policy"]["legacy_in_progress_is_execution_lease"] is False
    assert registry["policy"]["current_task_is_execution_lease"] is True
    assert registry["policy"]["external_write_allowed"] is False
    assert all(value is False for value in registry["control_boundary"].values())
