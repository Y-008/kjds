import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "social_intelligence_read_allowlist.json"
)
HARNESS_PATH = ROOT / "scripts" / "manage-opencli-social-readonly.ps1"
ROLLBACK_PATH = ROOT / "scripts" / "rollback-opencli-social-readonly.ps1"


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_allowlist_is_exactly_the_owned_creator_read_surface():
    registry = _registry()
    assert registry["schema_version"] == (
        "kjds-opencli-social-read-allowlist-v1"
    )
    assert registry["deny_by_default"] is True
    allowed = {
        platform: {command["name"] for command in contract["commands"]}
        for platform, contract in registry["platforms"].items()
    }
    assert allowed == {
        "douyin": {"whoami", "profile", "videos", "stats"},
        "xiaohongshu": {
            "whoami",
            "creator-profile",
            "creator-notes",
            "creator-notes-summary",
            "creator-note-detail",
            "creator-stats",
        },
    }


def test_writes_downloads_and_discovery_are_not_allowlisted():
    registry = _registry()
    allowed = {
        f"{platform}.{command['name']}"
        for platform, contract in registry["platforms"].items()
        for command in contract["commands"]
    }
    prohibited_fragments = {
        "publish",
        "delete",
        "update",
        "follow",
        "login",
        "download",
        "comments",
        "search",
        "feed",
        "ask",
        "draft",
    }
    assert not any(
        fragment in command
        for command in allowed
        for fragment in prohibited_fragments
    )
    blocked = {
        f"{platform}.{command}"
        for platform, commands in registry["blocked_command_names"].items()
        for command in commands
    }
    assert "xiaohongshu.download" in blocked
    assert "douyin.publish" in blocked
    assert "xiaohongshu.publish" in blocked


def test_runtime_and_capture_are_pinned_and_isolated():
    registry = _registry()
    assert registry["runtime"] == {
        "package": "@jackwener/opencli",
        "cli_version": "1.8.6",
        "release_url": (
            "https://github.com/jackwener/OpenCLI/releases/tag/v1.8.6"
        ),
        "extension_version": "1.0.22",
        "extension_asset": "opencli-extension-v1.0.22.zip",
        "extension_sha256": (
            "9d2e3d053948beab5d97124aa79b1532d2122e33e461eca56cac113afd33207a"
        ),
    }
    isolation = registry["browser_isolation"]
    assert isolation["dedicated_profile_required"] is True
    assert isolation["cookie_import_allowed"] is False
    assert isolation["personal_browser_profile_reuse_allowed"] is False
    capture = registry["capture_contract"]
    assert capture["external_write"] is False
    assert capture["business_fact_promotion"] is False
    assert capture["literal_stdout_and_stderr_required"] is True
    assert capture["sha256_required"] is True


def test_harness_has_no_arbitrary_command_passthrough_and_rechecks_access():
    script = HARNESS_PATH.read_text(encoding="utf-8")
    assert "ValueFromRemainingArguments" not in script
    assert "CliArgs" not in script
    assert "Assert-CommandContract" in script
    assert 'access:\\s*read' in script
    assert '"--keep-tab", "false"' in script
    assert '"-f", "json"' in script
    assert "stdout_sha256" in script
    assert "stderr_sha256" in script
    assert "external_write = $false" in script
    assert "cookie" not in script.lower()


def test_rollback_is_scoped_to_the_delivery_and_uses_git_revert():
    script = ROLLBACK_PATH.read_text(encoding="utf-8")
    assert 'ValidateSet("Verify", "Apply")' in script
    assert "git revert --no-edit" in script
    assert "target_count" in script
    assert ".runtime" not in script
    assert "wuliu" not in script
