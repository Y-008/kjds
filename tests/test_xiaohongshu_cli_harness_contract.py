from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts" / "manage-xiaohongshu-cli.ps1"


def _script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_xiaohongshu_cli_harness_pins_source_and_uses_ignored_runtime():
    script = _script()

    assert "xiaohongshu-cli-0.6.4" in script
    assert "4d63f3c0c85ccd9054fa8e96d7f761aaf2507449" in script
    assert "https://github.com/jackwener/xiaohongshu-cli.git" in script
    assert '.runtime\\social-intelligence' in script
    assert "Assert-PinnedCheckout" in script
    assert "checkout --detach" in script


def test_xiaohongshu_cli_harness_exposes_reads_writes_and_two_login_modes():
    script = _script()

    for mode in ("LoginQr", "LoginBrowser", "Run", "Test", "Doctor"):
        assert f'"{mode}"' in script
    assert '"--qrcode"' in script
    assert "[Parameter(ValueFromRemainingArguments = $true)]" in script
    assert "Invoke-Xhs" in script
    assert "Run requires xhs command arguments via -CliArgs" in script
    assert "-m xhs_cli" in script
    assert "Install-CamoufoxRuntime" in script
    assert "--continue-at" in script
    assert "386fc2f41139685f9a1a9cef0d024bc041d899c315ea538d561171b5b282e57d" in script


def test_xiaohongshu_cli_harness_isolates_profile_and_avoids_implicit_browser_scan():
    script = _script()

    assert '$env:HOME = $profileRoot' in script
    assert '$env:USERPROFILE = $profileRoot' in script
    assert '"kjds-qr-only"' in script
    assert "LoginBrowser requires an explicit -CookieSource" in script
    assert 'if ($CookieSource -eq "auto")' not in script


def test_upstream_packaging_workaround_is_explicit_and_pinned():
    script = _script()

    assert "omits editables" in script
    assert '"hatchling==1.31.0"' in script
    assert '"editables==0.6"' in script
    assert '"pathspec==1.1.1"' in script
    assert "uv export" in script
    assert "--frozen" in script
    assert "--no-emit-project" in script
    assert "--deselect" in script
    assert "Push-Location $toolRoot" in script
    assert "Pop-Location" in script
