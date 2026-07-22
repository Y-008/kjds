import json
from pathlib import Path


def test_cross_border_ecosystem_reuses_tools_without_creating_a_second_control_plane():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "cross_border_automation_ecosystem.json"
    )
    registry = json.loads(path.read_text(encoding="utf-8"))

    assert registry["automatic_install"] is False
    assert registry["automatic_write_enablement"] is False
    assert len(registry["channels_checked"]) >= 5
    assert {item["id"] for item in registry["active_now"]} >= {
        "1688_cli",
        "opencli_isolated_trial",
        "openclaw_hermes",
        "n8n_internal",
        "firecrawl",
        "erpnext_dry_run",
    }

    cli = next(item for item in registry["active_now"] if item["id"] == "1688_cli")
    assert cli["package"] == "1688-cli@0.1.47"
    assert "No cart, checkout, order, payment" in cli["write_boundary"]

    for target in registry["official_api_targets"]:
        assert target["automatic_write_enabled"] is False
        assert target["next_gate"]

    rejected = {item["id"] for item in registry["not_adopted"]}
    assert "captcha_bypass_tools" in rejected
    assert "community_shopify_mcp" in rejected
    assert "pim_and_commerce_backends" in rejected

    opencli = next(
        item for item in registry["active_now"] if item["id"] == "opencli_isolated_trial"
    )
    assert opencli["package"] == "@jackwener/opencli@1.8.6"
    assert "browser_bridge_missing_exit_69" in opencli["current_state"]
    assert "main Edge profile" in opencli["write_boundary"]


def test_browser_candidates_compound_assets_without_a_second_write_path():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "cross_border_automation_ecosystem.json"
    )
    registry = json.loads(path.read_text(encoding="utf-8"))
    harnesses = registry["browser_harness_candidates_2026_07_22"]

    assert harnesses["production_owner"].startswith("KJDS deterministic browser lane")
    assert harnesses["automatic_write_enabled"] is False
    assert "10/10" in harnesses["promotion_criteria"]
    candidates = {item["id"]: item for item in harnesses["candidates"]}
    assert set(candidates) == {
        "playwright",
        "opencli",
        "stagehand",
        "browser_use",
        "skyvern",
    }
    assert candidates["opencli"]["decision"] == "installed_isolated_not_promoted"
    assert candidates["skyvern"]["decision"].endswith("no_second_platform")


def test_workflow_ecosystem_keeps_one_business_owner_and_no_second_platform():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "cross_border_automation_ecosystem.json"
    )
    workflow = json.loads(path.read_text(encoding="utf-8"))["workflow_ecosystem"]

    assert workflow["production_workflow_owner"] == "KJDS service and persisted state machine"
    assert {item["id"] for item in workflow["active_or_existing"]} == {
        "n8n_internal",
        "kjds_service_state_machine",
    }

    candidates = workflow["preferred_if_measured_gap_appears"]
    assert {item["id"] for item in candidates} >= {
        "pgqueuer",
        "procrastinate",
        "dbos_python",
        "openai_agents_sdk",
        "dlt",
    }
    assert all(item["trigger"] and item["boundary"] for item in candidates)

    deferred_ids = {
        item_id
        for group in workflow["deferred_platforms"]
        for item_id in group["ids"]
    }
    assert {"activepieces", "temporal", "airflow", "langgraph"} <= deferred_ids
    assert {item["id"] for item in workflow["not_adopted"]} == {
        "autogen",
        "bullmq",
    }


def test_frontier_snapshot_is_date_bounded_and_distinguishes_maturity():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "cross_border_automation_ecosystem.json"
    )
    frontier = json.loads(path.read_text(encoding="utf-8"))["frontier_2026_07_22"]

    assert frontier["as_of"].startswith("2026-07-22T")
    assert frontier["future_drafts_excluded"] is True
    protocols = {item["id"]: item for item in frontier["protocols"]}
    assert protocols["ucp"]["maturity"] == "released_open_spec"
    assert protocols["acp"]["maturity"].startswith("beta_")
    assert protocols["ap2"]["maturity"].startswith("v0_2_")
    assert protocols["a2a"]["latest_release"] == "v1.0.1"
    assert protocols["mcp_apps"]["stable_spec"] == "2026-01-26"
    assert protocols["a2ui"]["latest_release"] is None

    implementations = {item["id"]: item for item in frontier["implementations"]}
    assert implementations["openai_agents_sdk"]["latest_release"] == "v0.18.3"
    assert implementations["microsoft_agent_framework"]["latest_release"] == "python-1.12.0"
    assert implementations["github_agentic_workflows"]["latest_release"] == "v0.82.14"
    assert implementations["dbos_python"]["latest_release"] == "2.28.0"
    assert implementations["trigger_dev"]["latest_release"] == "v4.5.6"


def test_collection_chain_is_end_to_end_fail_closed_and_compounding():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "cross_border_automation_ecosystem.json"
    )
    chain = json.loads(path.read_text(encoding="utf-8"))["collection_chain"]

    assert chain["production_owner"] == "KJDS Evidence pipeline and persisted state machine"
    assert "cannot create formal facts" in chain["global_boundary"]

    stages = {item["id"]: item for item in chain["stages"]}
    assert set(stages) == {
        "source_authority",
        "account_session_scope",
        "official_api_export",
        "deterministic_authenticated_browser",
        "ai_browser_fallback",
        "raw_capture",
        "file_safety_privacy",
        "parse_schema_version",
        "canonical_identity",
        "window_pagination_control_totals",
        "hash_dedupe_history",
        "field_provenance_confidence",
        "independent_review",
        "evidence_lineage",
        "promotion_gate",
        "drift_quarantine_replay",
        "resilience_human_takeover",
        "readback_reconciliation",
        "retention_revocation",
        "monitoring_slo_incident",
        "manual_minutes_economics",
        "compound_asset_registry",
    }
    required = {
        "purpose",
        "primary",
        "fallback",
        "owner",
        "boundary",
        "status",
        "verification",
        "provenance",
    }
    assert all(required <= set(stage) for stage in stages.values())
    assert stages["official_api_export"]["status"].startswith("blocked_ozon")
    assert stages["promotion_gate"]["status"] == "active_formal_fact_promoted_false"
    assert "No CAPTCHA" in stages["resilience_human_takeover"]["boundary"]

    targets = chain["compounding_contract"]["targets"]
    assert targets == {
        "second_sku_workflow_adapter_reuse_pct_min": 70,
        "third_sku_workflow_adapter_reuse_pct_min": 85,
        "third_sku_manual_minutes_vs_first_pct_max": 50,
        "known_failure_recurrence_pct_max": 5,
        "duplicate_external_actions_max": 0,
        "unreviewed_fact_promotions_max": 0,
        "rollback_success_pct": 100,
    }
