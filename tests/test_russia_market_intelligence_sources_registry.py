import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "russia_market_intelligence_sources.json"
)
EVIDENCE_PATH = (
    ROOT
    / "docs"
    / "project"
    / "evidence"
    / "20260803_RUSSIA_MARKET_DEMAND_AND_EVENT_SOURCE_RESEARCH.md"
)


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_russia_registry_has_full_collection_and_conservation_contract():
    registry = _registry()
    policy = registry["collection_policy"]

    assert registry["schema_version"] == (
        "kjds-russia-market-intelligence-sources-v1"
    )
    assert registry["market"] == "RU"
    assert policy["all_available_pages_fields_and_time_windows"] is True
    assert policy["arbitrary_kjds_sample_cap_allowed"] is False
    assert policy["source_native_cap_must_be_recorded"] is True
    assert policy["checkpoint_and_incremental_resume_required"] is True
    assert policy["accepted_plus_quarantined_equals_source_total"] is True
    assert policy["partial_collection_may_be_labeled_complete"] is False
    assert policy["market_demand_signal_is_sales_fact"] is False


def test_russia_registry_covers_market_search_social_platform_and_macro():
    registry = _registry()
    source_classes = {source["source_class"] for source in registry["sources"]}

    assert {
        "official_authorized_marketplace",
        "official_authorized_search_demand",
        "official_authorized_public_social",
        "official_public_economic",
        "official_public_platform_change",
    }.issubset(source_classes)
    ids = [source["id"] for source in registry["sources"]]
    assert len(ids) == len(set(ids))
    assert {"ozon_seller_analytics", "wildberries_seller_analytics"}.issubset(
        ids
    )
    assert {"yandex_wordstat", "telegram_public_market_conversation"}.issubset(
        ids
    )


def test_all_russia_sources_are_evidence_linked_and_have_explicit_gates():
    evidence = EVIDENCE_PATH.read_text(encoding="utf-8")

    for source in _registry()["sources"]:
        assert source["authority"]
        assert source["collection"]
        assert source["native_limits"]
        assert source["current_status"]
        assert source["next_gate"]
        for url in source["urls"]:
            parsed = urlparse(url)
            assert parsed.scheme == "https"
            assert parsed.hostname
            assert url in evidence


def test_hot_event_score_is_explainable_and_cannot_create_facts():
    scoring = _registry()["hot_event_scoring"]

    assert "cross_source_count" in scoring["inputs"]
    assert "observed_market_response" in scoring["inputs"]
    assert {"score", "components", "source_ids", "unknowns"}.issubset(
        scoring["required_outputs"]
    )
    assert scoring["llm_may_create_event_fact"] is False
    assert scoring["single_social_post_may_trigger_external_action"] is False


def test_current_public_observations_are_context_not_business_truth():
    registry = _registry()
    observations = registry["current_observations"]

    assert len(observations) == 2
    assert all("context_only" in item["decision_use"] for item in observations)
    assert all(item["facts"] for item in observations)
    assert all(item["url"].startswith("https://") for item in observations)
    assert all(value is False for value in registry["control_boundary"].values())
