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

BAS223_OWNER_THREAD_ID = "019ffd36-1417-7321-bacb-b3c9510ec970"
BAS223_TASK = {
    "task_id": "BAS-223",
    "state": "in_progress",
    "owner_thread_id": BAS223_OWNER_THREAD_ID,
    "write_scope": [
        "enterprise_positioning_contract",
        "control_plane_api",
        "team_control_web",
        "board_operating_documents",
    ],
    "blocked_on": [],
}
BAS223_SHARED_LEASES = {
    "alembic_migration": None,
    "api_aggregation_root": "BAS-223",
    "master_spec": "BAS-223",
    "openapi_snapshot": "BAS-223",
}
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


def test_bas186_release_frees_media_lane_and_migration_lease():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    media = lanes["J"]

    assert media["current_task"] is None
    assert media["next_task_id"] is None
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] == "BAS-223"
    assert registry["shared_write_leases"]["openapi_snapshot"] == "BAS-223"
    assert registry["shared_write_leases"]["master_spec"] == "BAS-223"
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
    assert "exact tenant/entity/store/current-authority/subject/scope-binding" in bas184_row
    assert "事务紧邻持久化前重验 current scope" in bas184_row
    assert "refs/hash/version/count/safe codes" in bas184_row
    assert "immutable tool descriptor" in bas184_row
    assert "UNKNOWN_OUTCOME" in bas184_row
    assert "不新增数据库/迁移/API/router/OpenAPI/Web/runtime/compose" in bas184_row
    assert "apps/control_plane/media_jobs.py" in bas184_row
    assert "tests/test_media_jobs.py" in bas184_row
    assert "tests/test_media_jobs_postgres.py" in bas184_row
    assert "scope-authority advisory lock" in bas184_row
    assert "真实 PostgreSQL 双连接" in bas184_row
    assert "ab2c66d6fb8c5ea7b03c97e81edd92c522f11b81" in bas184_row
    assert "FD8807B07BABA76F0664E14FD34BE1CAF137B44DE973163635F7E44571FD4FAF" in bas184_row
    assert "本切片未运行 G1" in bas184_row
    assert bas184_row.endswith("| DONE_ENGINEERING |")
    bas186_row = next(
        line for line in plan.splitlines() if line.startswith("| BAS-186 |")
    )
    assert "GovernedEditingBlueprintWorkspace.process" in bas186_row
    assert "GovernedMediaJobWorkspace" in bas186_row
    assert "唯一 Job 真源" in bas186_row
    assert "20260809_0098_media_job_result_readback.py" in bas186_row
    assert "same connector/provider" in bas186_row
    assert "Remotion 保持 watch/not_admitted" in bas186_row
    assert "tests/test_media_jobs_postgres.py" in bas186_row
    assert "apps/control_plane/scoped_product_content.py" in bas186_row
    assert "apps/control_plane/evidence.py" in bas186_row
    assert "apps/control_plane/media_worker.py" in bas186_row
    assert "apps/control_plane/runtime.py" in bas186_row
    assert "apps/control_plane/media_connectors.py" in bas186_row
    assert "tests/test_media_connectors.py" in bas186_row
    assert "tests/test_editing_blueprint_runtime_composition.py" in bas186_row
    assert "internal blueprint compiler" in bas186_row
    assert "reserved worker-input receipt" in bas186_row
    assert "dedicated reserved authority capture" in bas186_row
    assert "禁止复用 `MediaExecutionRow`" in bas186_row
    assert "不改 router/API/OpenAPI/Web/compose/auto-commerce" in bas186_row
    assert "不运行 G1" in bas186_row
    assert "53da4ea242ce4fbd5ffba37d3aa0db4510308ed7" in bas186_row
    assert "D0B255A7D80072A39DE7ADCA822EF05FC9C7498442ADF4D92C8B955A0A454C3A" in bas186_row
    assert "142 passed" in bas186_row
    assert "20 passed, 1 skipped" in bas186_row
    assert "56 passed" in bas186_row
    assert "74 passed" in bas186_row
    assert "本切片未运行 G1" in bas186_row
    assert bas186_row.endswith("| DONE_ENGINEERING |")


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

    assert engineering["current_task"] == BAS223_TASK
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] == "BAS-223"
    assert registry["shared_write_leases"]["master_spec"] == "BAS-223"
    assert registry["shared_write_leases"]["openapi_snapshot"] == "BAS-223"
    assert "BAS-204" not in registry["shared_write_leases"].values()

def test_bas210_release_frees_lane_c_and_shared_api_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    engineering = lanes["C"]

    assert engineering["current_task"] == BAS223_TASK
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"]["api_aggregation_root"] == "BAS-223"
    assert registry["shared_write_leases"]["openapi_snapshot"] == "BAS-223"
    assert registry["shared_write_leases"]["alembic_migration"] is None
    assert registry["shared_write_leases"]["master_spec"] == "BAS-223"
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

    assert engineering["current_task"] == BAS223_TASK
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

    assert engineering["current_task"] == BAS223_TASK
    assert engineering["next_task_id"] is None
    assert "BAS-212" not in registry["shared_write_leases"].values()
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
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
    assert engineering["current_task"] == BAS223_TASK
    assert engineering["next_task_id"] is None
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
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
    assert engineering["current_task"] == BAS223_TASK
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
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
    assert engineering["current_task"] == BAS223_TASK
    assert coverage["current_task"] is None
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
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


def test_shared_write_leases_are_owner_bounded_and_authority_stays_fail_closed():
    registry = _registry()
    assert set(registry["shared_write_leases"]) == {
        "alembic_migration",
        "api_aggregation_root",
        "master_spec",
        "openapi_snapshot",
    }
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
    assert registry["policy"]["legacy_in_progress_is_execution_lease"] is False
    assert registry["policy"]["current_task_is_execution_lease"] is True
    assert registry["policy"]["external_write_allowed"] is False
    assert all(value is False for value in registry["control_boundary"].values())


def test_bas217_and_bas218_releases_are_preserved_while_bas186_runs():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}
    assert lanes["C"]["current_task"] == BAS223_TASK
    assert lanes["C"]["next_task_id"] is None
    assert lanes["J"]["current_task"] is None
    assert lanes["J"]["next_task_id"] is None
    assert lanes["M"]["current_task"] is None
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
    released_claim = {
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
            "profit_row_identity_receipt",
            "runtime_owned_profit_receipt_authority",
        ],
        "blocked_on": [],
    }
    assert released_claim not in [lane["current_task"] for lane in registry["lanes"]]
    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-217 |"))
    assert "ScopedProfitLedgerAuthority" in row
    assert "canonical_order_sku_receipt_v1" in row
    assert "apps/control_plane/scoped_profit_ledger.py" in row
    assert "tests/test_scoped_profit_ledger.py" in row
    assert "apps/control_plane/runtime.py" in row
    assert "tests/test_profit_receipt_runtime_composition.py" in row
    assert "ScopedProfitOrderSkuReceiptAuthority" in row
    assert "source_profit_snapshot_sha256" in row
    assert "恶意 adapter" in row
    assert "排除观测 `as_of` 和顶层 Profit snapshot" in row
    assert "Ozon offer 映射" in row
    assert "BLOCKED_EVIDENCE" in row
    assert "不改 DB/migration/router/API/OpenAPI/Web/G1" in row
    assert "58d3fa0e8a546d0069ed6059e03bf69afa7e537c" in row
    assert "7ac5c8555cc929c287dbee1c1db17340b055d592" in row
    assert "29EF546B9B9738FF0F11D20139ACC65CB70B1DCEBCCBC893E51DB769DD2062AA" in row
    assert "581135E3E2E40F30EE1C68E35AA5F79D23E5050F112DDF368DF2456330C16550" in row
    assert "113 passed in 8.60s" in row
    assert "双路 `P0=0/P1=0/PASS`" in row
    assert "G-1 未运行" in row
    assert row.endswith("| DONE_ENGINEERING |")


def test_bas218_release_frees_traceability_scope_without_touching_bas186():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}

    assert lanes["C"]["current_task"] == BAS223_TASK
    assert lanes["C"]["next_task_id"] is None
    assert lanes["J"]["current_task"] is None
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES

    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-218 |"))
    assert "RequirementsTraceabilityProgram.project()" in row
    assert "ADOPTED_ENGINEERING" in row
    assert "ISOLATED_IMPLEMENTED" in row
    assert "BLOCKED_EVIDENCE" in row
    assert "隔离自动经营" in row
    assert "不接 runtime/router/API/OpenAPI/Web/DB/migration/G1/外写" in row
    assert "requirements_traceability.json" in row
    assert "ADR-0096-requirements-traceability-and-automation-control.md" in row
    assert "80c6bffbc4905bdd314bf56eed2b1ac791c324c9" in row
    assert "ef2ae4ecb55125d285e1f9e0e46375525ba9e20f" in row
    assert "58 passed in 0.19s" in row
    assert "G-1 未运行" in row
    assert "继续 `BLOCKED_EVIDENCE`" in row
    assert row.endswith("| DONE_ENGINEERING |")


def test_bas219a_release_preserves_selective_core_integration_evidence():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}

    assert lanes["C"]["current_task"] == BAS223_TASK
    assert lanes["C"]["next_task_id"] is None
    assert lanes["J"]["current_task"] is None
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES

    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-219A |"))
    assert "5078b9fdaf781863f6f0700bd90abb3bdfad24c2" in row
    assert "AutomatedCommerceLoop" in row
    assert "requested_mode/effective_mode/grant_ready/runtime_execution_enabled" in row
    assert "完整分页" in row
    assert "不改 runtime/router/API/OpenAPI/Web/DB/migration/G1/外写" in row
    assert "BAS-219B" in row
    assert "40d0bebc06d2183951e2ba897bffb14c9e91d17b" in row
    assert "129 passed" in row
    assert "DB/G-1 未运行" in row
    assert "继续 `BLOCKED_EVIDENCE`" in row
    assert row.endswith("| DONE_ENGINEERING |")


def test_bas220_release_records_exact_currentness_scope_and_gates():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}

    assert lanes["J"]["current_task"] is None
    assert lanes["J"]["next_task_id"] is None
    assert lanes["C"]["current_task"] == BAS223_TASK
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES

    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-220 |"))
    assert "tests/test_closed_loop_evolution_postgres.py" in row
    assert "20260805_0096" in row
    assert "20260809_0098" in row
    assert "不修改 0096/0097/0098 migration" in row
    assert "不抢 shared lease" in row
    assert "80d33b93b65475934f7f76cc320e6f8c760c0842" in row
    assert "E298B06AA8A11FA6C9A6F8EE21407AEAEB609BCA332FFBEA863694DA99985CEF" in row
    assert "101 passed" in row
    assert "G-1 未通过" in row
    assert row.endswith("| DONE_ENGINEERING |")


def test_bas223_owner_correct_claim_survives_bas220_release():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}

    assert lanes["C"]["current_task"] == BAS223_TASK
    assert lanes["J"]["current_task"] is None
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES
    assert registry["as_of"] == "2026-08-03"
    assert all(value is False for value in registry["control_boundary"].values())

    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-223 |"))
    assert BAS223_OWNER_THREAD_ID in row
    for scope in BAS223_TASK["write_scope"]:
        assert f"`{scope}`" in row
    for lease in ("api_aggregation_root", "master_spec", "openapi_snapshot"):
        assert f"`{lease}`" in row
    assert "不占 migration" in row
    assert "不改变 BAS-220 当前任务" in row
    assert "不新增或宣称 BAS-221/BAS-222 状态" in row
    assert row.endswith("| IN_PROGRESS |")


def test_bas221_release_is_exact_and_preserves_bas223_leases():
    registry = _registry()
    lanes = {lane["id"]: lane for lane in registry["lanes"]}

    assert lanes["J"]["current_task"] is None
    assert lanes["J"]["next_task_id"] is None
    assert lanes["C"]["current_task"] == BAS223_TASK
    assert registry["shared_write_leases"] == BAS223_SHARED_LEASES

    plan = PLAN_PATH.read_text(encoding="utf-8")
    row = next(line for line in plan.splitlines() if line.startswith("| BAS-221 |"))
    for path in (
        "apps/control_plane/evidence.py",
        "apps/control_plane/research_inbox.py",
        "docs/project/registries/outbox_coverage.json",
        "docs/project/registries/write_path_registry.json",
        "tests/test_commercial_lifecycle.py",
        "tests/test_research_inbox.py",
        "tests/test_write_path_registry.py",
        "docs/project/evidence/20260814_BAS_221_G1_INTEGRATION_DRIFT.md",
    ):
        assert f"`{path}`" in row
    assert "不得改 DB/migration/API/OpenAPI/Web/依赖" in row
    assert "不占 shared lease" in row
    assert "4c12b5c99b8b0471717857b283fbe9aeda9ae9a5" in row
    assert "e218c39401be187c13dbc565606e91b39e65260e" in row
    assert "5E7A395A378C2385F532C730D9B2F611DDD006288C74F77E3050C70E809140F4" in row
    assert "82 passed, 1 skipped" in row
    assert "release-head G-1 尚未重跑" in row
    assert row.endswith("| DONE_ENGINEERING |")
