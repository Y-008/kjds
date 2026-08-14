import json
from pathlib import Path


def test_competitive_patterns_borrow_workflows_without_delegating_truth_or_writes():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "competitive_capability_patterns.json"
    )
    registry = json.loads(path.read_text(encoding="utf-8"))
    providers = registry["providers"]

    assert {item["id"] for item in providers} == {
        "dianxiaomi_erp",
        "linkfox",
        "lizhi_ozon_assistant",
        "mango_erp",
        "maozierp",
        "menglar_ozon_tools",
        "seerfar",
        "miaoshou_erp",
        "selling51_erp",
    }
    assert registry["baseline_policy"] == {
        "requirement": "must_have_native_parity",
        "safe_capability_omission_allowed": False,
        "mapping_is_not_implementation": True,
        "providers_are_runtime_dependencies": False,
        "prohibited_patterns_require_safe_jtbd_replacement": True,
        "coverage_dimensions": [
            "code",
            "migration",
            "api",
            "web",
            "permissions",
            "runtime_replay",
            "evidence",
        ],
        "ai_advantage_is_scored_separately": True,
        "external_write_allowed": False,
    }
    for provider in providers:
        assert provider["observed_capabilities"]
        assert provider["patterns_to_borrow"]
        assert provider["do_not_copy"]
        assert provider["evidence_tier"] in {"C", "D"}
        assert provider["requires_review"] is True
        assert provider["next_contract"]

    forbidden = {item for provider in providers for item in provider["do_not_copy"]}
    assert "automatic_pricing" in forbidden
    assert "automatic_purchase" in forbidden
    assert "unapproved_batch_write" in forbidden
    assert "erp_as_canonical_fact_owner" in forbidden

    portfolio = next(
        item
        for item in registry["shared_contracts"]
        if item["id"] == "three_candidate_portfolio_decision_view_v1"
    )
    assert portfolio["status"] == "implemented"
    assert "no automatic product selection" in portfolio["boundary"]
    assert "no automatic procurement" in portfolio["boundary"]

    exception_workspace = next(
        item
        for item in registry["shared_contracts"]
        if item["id"] == "evidence_backed_operations_exception_workspace_v1"
    )
    assert exception_workspace["status"] == "implemented"
    assert "without invented SLA" in exception_workspace["boundary"]
    assert "no automatic resolution" in exception_workspace["boundary"]

    cost_provenance = next(
        item
        for item in registry["shared_contracts"]
        if item["id"] == "field_level_cost_provenance_v1"
    )
    assert cost_provenance["status"] == "implemented"
    assert "Evidence reference" in cost_provenance["boundary"]

    evidenceops = next(
        item
        for item in registry["shared_contracts"]
        if item["id"] == "evidenceops_objective_to_evidence_plan_v1"
    )
    assert evidenceops["status"] == "implemented"
    assert "explicit unknowns" in evidenceops["boundary"]
    assert "stable hash" in evidenceops["boundary"]
    assert "platform write" in evidenceops["boundary"]

    atlas = next(
        item
        for item in registry["shared_contracts"]
        if item["id"] == "cross_border_capability_atlas_v1"
    )
    assert atlas["status"] == "implemented"
    assert "C-tier comparison evidence only" in atlas["boundary"]
    assert "no write authority" in atlas["boundary"]
    assert "unverified Ozon support" in atlas["boundary"]

    linkfox = next(item for item in providers if item["id"] == "linkfox")
    assert linkfox["evidence_tier"] == "C"
    assert linkfox["implemented_contract"] == evidenceops["id"]
    assert linkfox["implemented_companion_contract"] == atlas["id"]
    assert "ozon_support_not_verified" in linkfox["integration_status"]
    assert "third-party calculator values remain cross-checks" in cost_provenance["boundary"]

    selling51 = next(item for item in providers if item["id"] == "selling51_erp")
    assert "field_level_source_badge" in selling51["patterns_to_borrow"]
    assert "explicit_unmapped_finance_queue" in selling51["patterns_to_borrow"]

    dianxiaomi = next(
        item for item in providers if item["id"] == "dianxiaomi_erp"
    )
    assert dianxiaomi["source_documents"] == [
        "https://www.dianxiaomi.com/",
        "https://help.dianxiaomi.com/",
    ]
    assert "procurement_and_1688_purchase_tracking" in (
        dianxiaomi["observed_capabilities"]
    )
    assert "session_or_cookie_reuse" in dianxiaomi["do_not_copy"]

    seerfar = next(item for item in providers if item["id"] == "seerfar")
    assert "advertising_analysis_and_strategy" in (
        seerfar["observed_capabilities"]
    )
    assert "review_insight_packet" in seerfar["patterns_to_borrow"]

    maozi = next(item for item in providers if item["id"] == "maozierp")
    assert maozi["source_documents"] == [
        "https://mcn5ze6lo0iz.feishu.cn/wiki/"
        "Zd2xwn5m4ijIaQkiDc7c34qgnye"
    ]
    assert maozi["benchmark_registry"] == (
        "maozierp_feishu_capability_benchmark.json"
    )
    assert maozi["implemented_contract"] == (
        "browser_capture_inbox_v1_in_progress"
    )
    assert "cookie_binding" in maozi["do_not_copy"]
    assert "unlicensed_image_copy" in maozi["do_not_copy"]
    assert (
        "automatic_bulk_listing_without_profit_and_governance_gates"
        in maozi["do_not_copy"]
    )

    linkfox = next(item for item in providers if item["id"] == "linkfox")
    assert linkfox["evidence_tier"] == "C"
    assert "public_marketing_workflow_reference_only" in linkfox["integration_status"]
    assert "unsupported_ozon_integration_inference" in linkfox["do_not_copy"]

    unverified = {item["id"]: item for item in registry["unverified_candidates"]}
    assert set(unverified) == {"ozon_bigsell", "xiongmao_xcw", "yduanerp_client"}
    assert all(item["evidence_tier"] == "D" for item in unverified.values())
    assert all(item["admission"] == "defer" for item in unverified.values())
