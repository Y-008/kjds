import json
from pathlib import Path


def test_accio_is_a_market_benchmark_not_a_runtime_or_truth_authority():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "accio_sourcing_capability_benchmark.json"
    )
    registry = json.loads(path.read_text(encoding="utf-8"))

    assert registry["contract_id"] == "kjds-sourcing-market-benchmark-v1"
    assert registry["provider_id"] == "accio"
    assert registry["evidence_tier"] == "C"
    assert registry["benchmark_only"] is True
    assert registry["provider_is_runtime_dependency"] is False
    assert registry["authorized_adapter_configured"] is False
    assert registry["external_write_allowed"] is False
    assert registry["mapping_is_implementation"] is False
    assert len(registry["source_documents"]) == 3
    assert all(
        item["native_status"] in registry["status_vocabulary"]
        and item["native_module"]
        and item["authority_boundary"]
        for item in registry["capabilities"]
    )
    capability_ids = {
        item["id"] for item in registry["capabilities"]
    }
    assert {
        "product_and_opportunity_discovery",
        "supplier_discovery_and_comparison",
        "ai_assisted_inquiry_and_rfq",
        "three_quote_and_landed_cost_decision",
        "agent_mode_end_to_end_sourcing",
    } <= capability_ids
    assert {
        "private_endpoint_reverse_engineering",
        "cookie_or_session_reuse",
        "captcha_bypass",
        "automatic_purchase_or_payment",
    } <= set(registry["prohibited_patterns"])
