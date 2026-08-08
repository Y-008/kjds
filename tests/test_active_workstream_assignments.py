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


def _bas184_current_task():
    return {
        "task_id": "BAS-184",
        "state": "in_progress",
        "owner_thread_id": "019fc514-1b68-7503-afe3-50f1511c52de",
        "write_scope": [
            "commander_tool_gateway_contract",
            "campaign_brief_compilation",
            "versioned_media_tool_dispatch",
            "media_job_safe_projection",
            "bas184_tests_and_evidence",
        ],
        "blocked_on": [],
    }


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


def test_bas184_claims_media_lane_after_bas183_release():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    media = lanes["J"]

    assert media["current_task"] == _bas184_current_task()
    assert media["next_task_id"] is None
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] is None
    assert registry["shared_write_leases"]["openapi_snapshot"] is None
    assert registry["shared_write_leases"]["master_spec"] == "BAS-217"
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas183_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-183 |")
    )
    assert "GovernedMediaJobWorkspace" in bas183_row
    assert "20260808_0097_governed_media_jobs.py" in bas183_row
    assert "不改 API/SSE/runtime/media_worker/compose" in bas183_row
    assert "Native API/SSE" in bas183_row
    assert "9066a3fc" in bas183_row
    assert "本切片未运行 G1" in bas183_row
    assert bas183_row.endswith("| DONE_ENGINEERING |")
    bas184_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-184 |")
    )
    assert "CommanderToolGateway" in bas184_row
    assert "UNKNOWN_OUTCOME" in bas184_row
    assert "不新增数据库/迁移/API/router/OpenAPI/Web/runtime/compose" in bas184_row
    assert bas184_row.endswith("| IN_PROGRESS |")


def test_bas196_release_frees_local_demo_lane():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    demo = lanes["K"]

    assert demo["current_task"] is None
    assert demo["next_task_id"] is None
    assert "BAS-196" not in registry["shared_write_leases"].values()


def test_bas201_and_bas216a_releases_allow_bas216b_without_shared_writes():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    strategic = lanes["L"]

    assert strategic["current_task"] is None
    assert strategic["next_task_id"] is None
    assert "BAS-201" not in registry["shared_write_leases"].values()
    assert "BAS-216A" not in registry["shared_write_leases"].values()


def test_data_cov_002_release_no_longer_owns_coverage_or_migration_leases():
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

    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] is None
    assert registry["shared_write_leases"]["master_spec"] == "BAS-217"
    assert registry["shared_write_leases"]["openapi_snapshot"] is None
    assert "BAS-204" not in registry["shared_write_leases"].values()

def test_bas210_release_frees_lane_c_and_shared_api_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] is None
    assert registry["shared_write_leases"]["openapi_snapshot"] is None
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["master_spec"] == "BAS-217"
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
    assert "ea60b198" in bas210_row
    assert "本切片未运行 G1" in bas210_row
    assert bas210_row.endswith("| DONE_ENGINEERING |")



def test_bas211_release_record_and_bas210_release_are_preserved():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert engineering["next_task_id"] is None
    assert "BAS-211" not in registry["shared_write_leases"].values()
    plan = PLAN_PATH.read_text(encoding="utf-8")
    assert "| BAS-211 |" in plan
    assert "`pg_shdepend`" in plan
    assert "禁止 `DROP OWNED`" in plan
    assert "| DONE_ENGINEERING |" in plan


def test_bas212_release_record_and_bas210_release_are_preserved():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert engineering["next_task_id"] is None
    assert "BAS-212" not in registry["shared_write_leases"].values()
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": None,
        "master_spec": "BAS-217",
        "openapi_snapshot": None,
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas212_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-212 |")
    )
    assert "outbox_coverage.json" in bas212_row
    assert "internal_only" in bas212_row
    assert "e3100b04 full G-1 PASS" in bas212_row
    assert bas212_row.endswith("| DONE_ENGINEERING |")


def test_bas213_release_frees_lane_e_and_preserves_bas210_release():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    risk = lanes["E"]
    engineering = lanes["C"]

    assert risk["current_task"] is None
    assert risk["next_task_id"] is None
    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": None,
        "master_spec": "BAS-217",
        "openapi_snapshot": None,
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas213_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-213 |")
    )
    assert "frontier technology registry" in bas213_row
    assert "20260807_PROJECT_ENTRY_AND_FRONTIER_REVIEW_GOVERNANCE.md" in bas213_row
    assert "不升级依赖" in bas213_row
    assert bas213_row.endswith("| DONE_ENGINEERING |")


def test_bas215c_release_frees_lane_m_and_document_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    coverage = lanes["M"]
    engineering = lanes["C"]

    assert coverage["current_task"] is None
    assert coverage["next_task_id"] is None
    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": None,
        "master_spec": "BAS-217",
        "openapi_snapshot": None,
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas215a_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-215A |")
    )
    assert "EnterpriseAiErpProgram" in bas215a_row
    assert "enterprise_ai_erp_program.py" in bas215a_row
    assert "enterprise_ai_erp_program.json" in bas215a_row
    assert "test_enterprise_ai_erp_program.py" in bas215a_row
    assert "20260807_BAS_215A_ENTERPRISE_AI_ERP_PROGRAM.md" in bas215a_row
    assert "不接 OperatingTask/runtime/router/API/OpenAPI/DB/Web" in bas215a_row
    assert bas215a_row.endswith("| DONE_ENGINEERING |")
    bas215b_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-215B |")
    )
    assert "TeamControlTower.brief" in bas215b_row
    assert "decision_basis_sha256" in bas215b_row
    assert "apps/control_plane/runtime.py" in bas215b_row
    assert "docs/project/MASTER_SPEC.md" in bas215b_row
    assert "不改 router/API/OpenAPI/Web/DB/migration/G1/外写" in bas215b_row
    assert bas215b_row.endswith("| DONE_ENGINEERING |")
    bas215c_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-215C |")
    )
    assert "apps/control_plane/api_contracts.py" in bas215c_row
    assert "docs/project/contracts/openapi-v1.json" in bas215c_row
    assert "web/features/team-control-tower/contracts.ts" in bas215c_row
    assert "WCAG 2.2 AA" in bas215c_row
    assert "不改 TeamControlTower/Program/runtime/advance、DB/migration/G1" in bas215c_row
    assert bas215c_row.endswith("| DONE_ENGINEERING |")


def test_bas216b_release_frees_lane_l_without_shared_write_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    intelligence = lanes["L"]
    engineering = lanes["C"]
    coverage = lanes["M"]

    assert intelligence["current_task"] is None
    assert intelligence["next_task_id"] is None
    assert engineering["current_task"]["task_id"] == "BAS-217"
    assert coverage["current_task"] is None
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": None,
        "master_spec": "BAS-217",
        "openapi_snapshot": None,
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    bas216a_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-216A |")
    )
    assert "MarketplaceResearchWorkflow.project()" in bas216a_row
    assert "marketplace_research_source_contracts.json" in bas216a_row
    assert "bas216a_sellersprite_mcp_v1.json" in bas216a_row
    assert "fixture/manual export" in bas216a_row
    assert "不改依赖、DB/migration/runtime/router/API/OpenAPI/Web/G1" in bas216a_row
    assert bas216a_row.endswith("| DONE_ENGINEERING |")
    bas216b_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-216B |")
    )
    assert "marketplace_research_mcp.py" in bas216b_row
    assert "marketplace_research_mcp_admission.json" in bas216b_row
    assert "inspect_sellersprite_mcp.py" in bas216b_row
    assert "不实现或暴露 `call_tool`" in bas216b_row
    assert "live_admission=not_admitted" in bas216b_row
    assert "不改依赖、DB/migration/runtime/router/API/OpenAPI/Web/G1" in bas216b_row
    assert bas216b_row.endswith("| DONE_ENGINEERING |")


def test_shared_write_leases_and_authority_stay_fail_closed():
    registry = _registry()
    assert set(registry["shared_write_leases"]) == {
        "alembic_migration",
        "api_aggregation_root",
        "master_spec",
        "openapi_snapshot",
    }
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["openapi_snapshot"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] is None
    assert registry["shared_write_leases"]["master_spec"] == "BAS-217"
    assert registry["policy"]["legacy_in_progress_is_execution_lease"] is False
    assert registry["policy"]["current_task_is_execution_lease"] is True
    assert registry["policy"]["external_write_allowed"] is False
    assert all(value is False for value in registry["control_boundary"].values())


def test_bas217_claim_is_exact_and_does_not_take_runtime_or_schema_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    claim = lanes["C"]["current_task"]

    assert claim == {
        "task_id": "BAS-217",
        "state": "in_progress",
        "owner_thread_id": "019fd4c1-60c9-79a0-9338-8c204ba0f312",
        "write_scope": [
            "single_sku_cash_attribution_contract",
            "settlement_cash_projection",
            "team_control_cash_truth_projection",
            "team_control_registry_policy",
            "master_spec_and_control_docs",
            "focused_finance_control_tests",
            "engineering_evidence",
        ],
        "blocked_on": [],
    }
    assert lanes["M"]["current_task"] is None
    assert registry["shared_write_leases"] == {
        "alembic_migration": None,
        "api_aggregation_root": None,
        "master_spec": "BAS-217",
        "openapi_snapshot": None,
    }
    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-217 |"))
    assert "ScopedProfitLedgerAuthority" in row
    assert "Ozon offer 映射" in row
    assert "BLOCKED_EVIDENCE" in row
    assert "不改 DB/migration/runtime/router/API/OpenAPI/Web/G1" in row
    assert row.endswith("| IN_PROGRESS |")
