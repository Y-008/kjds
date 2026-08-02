import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "social_commerce_source_adoption.json"
)
EVIDENCE_PATH = (
    ROOT
    / "docs"
    / "project"
    / "evidence"
    / "20260803_SOCIAL_COMMERCE_OPEN_SOURCE_RESEARCH.md"
)
DECISIONS = {
    "preferred_path",
    "adopt_pattern",
    "pilot_isolated",
    "watch",
    "reject_runtime",
}


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_has_ordered_source_ladder_and_unique_candidates():
    registry = _registry()

    assert registry["schema_version"] == (
        "kjds-social-commerce-source-adoption-v1"
    )
    assert registry["as_of"] == "2026-08-03"
    assert set(registry["decision_vocabulary"]) == DECISIONS
    assert [item["rank"] for item in registry["source_ladder"]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert registry["source_ladder"][0]["id"] == "official_authorized_api"

    candidates = registry["candidates"]
    ids = [item["id"] for item in candidates]
    assert len(ids) == len(set(ids))
    assert {item["decision"] for item in candidates} == DECISIONS


def test_every_candidate_is_evidence_linked_and_has_two_gates():
    research = EVIDENCE_PATH.read_text(encoding="utf-8")
    for item in _registry()["candidates"]:
        assert item["upstream"]
        assert item["version"]
        assert item["license"]
        assert item["borrowed_patterns"]
        assert item["allowed_kjds_use"]
        assert item["prohibited_kjds_use"]
        assert item["entry_gate"]
        assert item["exit_gate"]
        assert item["evidence_urls"]
        for url in item["evidence_urls"]:
            parsed = urlparse(url)
            assert parsed.scheme == "https"
            assert parsed.hostname in {
                "developer.open-douyin.com",
                "github.com",
                "school.xiaohongshu.com",
            }
            assert url in research


def test_restricted_or_high_risk_projects_are_not_runtime_candidates():
    by_id = {item["id"]: item for item in _registry()["candidates"]}

    assert by_id["mediacrawler"]["decision"] == "reject_runtime"
    assert by_id["mediacrawler"]["license"] == (
        "NON-COMMERCIAL-LEARNING-1.1"
    )
    assert by_id["xiaohongshu_cli"]["decision"] == "pilot_isolated"
    assert by_id["xhs_cli_alternative"]["decision"] == "watch"
    assert by_id["archived_douyin_downloader_mcp"]["decision"] == (
        "reject_runtime"
    )
    assert by_id["behavior_simulation_comment_clis"]["decision"] == (
        "reject_runtime"
    )


def test_isolated_pilots_have_explicit_write_and_secret_prohibitions():
    pilots = [
        item
        for item in _registry()["candidates"]
        if item["decision"] == "pilot_isolated"
    ]
    assert {item["id"] for item in pilots} == {
        "opencli",
        "xiaohongshu_mcp",
        "douyin_creator_mcp",
        "xiaohongshu_cli",
    }

    allowed = {
        value
        for item in pilots
        for value in item["allowed_kjds_use"]
    }
    assert any("campaign_scoped" in value for value in allowed)
    assert all(
        "credential_echo" in item["prohibited_kjds_use"]
        for item in pilots
    )


def test_registry_is_fail_closed_and_current_selection_is_not_ready():
    registry = _registry()
    policy = registry["policy"]
    assert policy["operator_selected_install_allowed"] is True
    assert policy["full_multidimensional_collection_allowed"] is True
    assert policy["full_pagination_and_incremental_sync_allowed"] is True
    assert policy["campaign_scoped_platform_writes_allowed"] is True
    assert policy["personal_browser_cookie_extraction_allowed"] is True
    assert policy["personal_browser_cookie_extraction_mode"] == (
        "operator_explicit_source_into_isolated_project_profile_only"
    )
    assert policy["captcha_or_rate_limit_bypass_allowed"] is False
    assert policy["platform_write_tools_exposed_after_campaign_grant"] is True
    assert policy["external_write_mode"] == (
        "campaign_grant_with_budget_readback_and_kill_switch"
    )
    assert policy["formal_fact_promotion_allowed"] is False
    assert registry["current_selection"]["runtime_installation_status"] == (
        "installed_isolated_not_authenticated"
    )
    assert registry["current_selection"]["real_account_connection_status"] == (
        "no_data"
    )
    assert all(value is False for value in registry["control_boundary"].values())


def test_registry_review_date_is_current():
    reviewed = date.fromisoformat(_registry()["as_of"])
    assert reviewed <= date.today()
