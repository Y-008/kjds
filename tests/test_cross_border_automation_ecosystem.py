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
