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
        "lizhi_ozon_assistant",
        "maozierp",
        "menglar_ozon_tools",
        "seerfar",
        "miaoshou_erp",
        "selling51_erp",
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
    assert "third-party calculator values remain cross-checks" in cost_provenance["boundary"]

    selling51 = next(item for item in providers if item["id"] == "selling51_erp")
    assert "field_level_source_badge" in selling51["patterns_to_borrow"]
    assert "explicit_unmapped_finance_queue" in selling51["patterns_to_borrow"]

    unverified = {item["id"]: item for item in registry["unverified_candidates"]}
    assert set(unverified) == {"ozon_bigsell", "xiongmao_xcw", "yduanerp_client"}
    assert all(item["evidence_tier"] == "D" for item in unverified.values())
    assert all(item["admission"] == "defer" for item in unverified.values())
