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


def test_bas181_release_advances_media_lane():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    media = lanes["J"]

    assert media["current_task"] is None
    assert media["next_task_id"] == "BAS-182"


def test_bas195_holds_local_demo_portable_package_lease():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    demo = lanes["K"]

    assert demo["current_task"] == {
        "task_id": "BAS-195",
        "state": "in_progress",
        "owner_thread_id": "019fc81a-11cc-7653-b0c0-827f87ce0ada",
        "write_scope": [
            "portable_pwa_zip",
            "loopback_launcher",
            "offline_cold_start",
            "explicit_reset_and_cleanup",
            "deterministic_package_manifest",
            "secret_and_real_data_exclusion",
            "repeatable_build_hash",
        ],
        "blocked_on": [],
    }
    assert demo["next_task_id"] is None
    assert "BAS-195" not in registry["shared_write_leases"].values()


def test_bas199_release_advances_strategic_lane_without_preleasing_bas200():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    strategic = lanes["L"]

    assert strategic["current_task"] is None
    assert strategic["next_task_id"] == "BAS-200"
    assert "BAS-200" not in registry["shared_write_leases"].values()


def test_data_cov_002_holds_append_only_coverage_ledger_migration_lease():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    coverage = lanes["M"]

    assert coverage["current_task"] == {
        "task_id": "DATA-COV-002",
        "state": "in_progress",
        "owner_thread_id": "019fc7d6-d3ec-7e42-bc82-ebdc6c5710e9",
        "write_scope": [
            "coverage_ledger_migration_0095",
            "exact_scope_coverage_ledger",
            "immutable_coverage_observation_events",
            "manifest_native_caps_hash_binding",
            "idempotency_and_payload_drift",
            "valid_time_currentness",
            "conservation_failure_page_checkpoint_lineage",
            "coverage_ledger_postgres_tests",
            "reserved_coverage_intake_evidence_authority",
            "coverage_intake_evidence_authority_contract_tests",
        ],
        "blocked_on": [],
    }
    assert coverage["next_task_id"] is None
    assert registry["shared_write_leases"] == {
        "alembic_migration": "DATA-COV-002",
        "api_aggregation_root": None,
        "master_spec": None,
        "openapi_snapshot": None,
    }


def test_bas202_holds_constraint_breaker_red_team_lease_without_shared_writes():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"] == {
        "task_id": "BAS-202",
        "state": "in_progress",
        "owner_thread_id": "019fc104-db84-7fc2-b1de-08a51fc4e462",
        "write_scope": [
            "constraint_breaker_attack_registry",
            "prompt_and_indirect_injection_fixtures",
            "cross_scope_and_idempotency_red_team",
            "tool_poisoning_and_unknown_outcome_replay",
            "best_solution_license_data_cost_rollback_gate",
            "agent_run_retrieval_evolution_read_only_links",
            "constraint_breaker_contract_tests",
        ],
        "blocked_on": [],
    }
    assert engineering["next_task_id"] is None
    assert "BAS-202" not in registry["shared_write_leases"].values()
    assert registry["shared_write_leases"]["alembic_migration"] == "DATA-COV-002"
    assert registry["shared_write_leases"]["api_aggregation_root"] is None
    assert registry["shared_write_leases"]["master_spec"] is None
    assert registry["shared_write_leases"]["openapi_snapshot"] is None
    assert all(
        lane["current_task"] is None
        or lane["current_task"]["task_id"] != "BAS-200"
        for lane in registry["lanes"]
    )


def test_bas176_holds_only_the_disposable_postgres_rehearsal_lane():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    risk = lanes["E"]

    assert risk["current_task"] is None
    assert risk["next_task_id"] is None


def test_shared_write_leases_and_authority_stay_fail_closed():
    registry = _registry()
    assert set(registry["shared_write_leases"]) == {
        "alembic_migration",
        "api_aggregation_root",
        "master_spec",
        "openapi_snapshot",
    }
    assert registry["shared_write_leases"]["alembic_migration"] == "DATA-COV-002"
    assert registry["shared_write_leases"]["openapi_snapshot"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] is None
    assert registry["shared_write_leases"]["master_spec"] is None
    assert registry["policy"]["legacy_in_progress_is_execution_lease"] is False
    assert registry["policy"]["current_task_is_execution_lease"] is True
    assert registry["policy"]["external_write_allowed"] is False
    assert all(value is False for value in registry["control_boundary"].values())
