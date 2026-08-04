import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "verify-g1.ps1"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
PWSH = shutil.which("pwsh")


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def test_g1_harness_keeps_infrastructure_seams_without_domain_scenarios():
    source = HARNESS.read_text(encoding="utf-8")

    required_seams = (
        "Replaying migrations in disposable database",
        "Seeding the disposable operating Gate observation graph",
        "Verifying transactional outbox on PostgreSQL",
        "Running Python quality gates",
        "Verifying production API image",
        "Verifying Ozon Worker cannot bypass explicit execution intent",
        "Starting disposable API",
        "Verifying bounded Evidence integrity monitoring",
        "Verifying backup and isolated restore",
        "Starting disposable web UI",
    )
    for seam in required_seams:
        assert seam in source

    migrated_domain_routes = (
        "/v1/market/research-signals",
        "/v1/experiments",
        "/v1/policies",
        "/v1/procurement",
        "/v1/finance/cash-plan",
        "/v1/finance/reconciliation",
        "/v1/sourcing/supplier-comparisons",
    )
    for route in migrated_domain_routes:
        assert route not in source

    assert "alembic heads" in source
    assert "scripts/seed_g1_operating_gate.py" in source
    assert 'actor = "g1-operating-subject"' in source
    assert 'result.migration = "20' not in source
    assert "-WorkingDirectory $WebSmoke -WindowStyle Hidden -PassThru" in source
    assert "-WorkingDirectory $Web -WindowStyle Hidden -PassThru" not in source


def run_cleanup_contract(tmp_path: Path, report_path: Path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 cleanup contract")
    source = HARNESS.read_text(encoding="utf-8")
    helper_start = source.index("function Invoke-CleanupStep")
    harness_start = source.index("$startedAt =")
    helpers = source[helper_start:harness_start]
    script = f"""
$ErrorActionPreference = "Stop"
{helpers}
$result = [ordered]@{{
    gate = "G-1"
    status = "PASS"
    started_at = "2026-07-23T00:00:00.0000000Z"
    finished_at = $null
    git_commit = "test-commit"
    cleanup_processes = $true
    cleanup_database = $true
    cleanup_files = $true
    cleanup_error = $null
    cleanup_file_errors = @()
    error = $null
    report_error = $null
}}
$marker = [IO.Path]::Combine(
    {powershell_quote(str(tmp_path))},
    "later-step-ran.txt"
)
$steps = @(
    @{{ Name = "native failure"; Action = {{
        & {powershell_quote(PWSH)} `
            -NoProfile `
            -Command "exit 7"
        if ($LASTEXITCODE -ne 0) {{
            throw "native command failed with exit code $LASTEXITCODE"
        }}
    }} }},
    @{{ Name = "later step"; Action = {{
        [IO.File]::WriteAllText($marker, "ran")
    }} }}
)
$completion = Complete-G1Verification `
    -Result $result `
    -CleanupSteps $steps `
    -ReportPath {powershell_quote(str(report_path))}
if ($completion.failed) {{ exit 1 }}
"""
    return subprocess.run(
        [PWSH, "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )


def test_g1_cleanup_removes_read_only_git_objects(tmp_path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 cleanup contract")
    source = HARNESS.read_text(encoding="utf-8")
    helper_start = source.index("function Invoke-CleanupStep")
    harness_start = source.index("$startedAt =")
    helpers = source[helper_start:harness_start]
    disposable = tmp_path / "pytest-g1-test" / ".git" / "objects" / "ab"
    disposable.mkdir(parents=True)
    git_object = disposable / "cdef"
    git_object.write_bytes(b"test")
    git_object.chmod(0o444)

    script = f"""
$ErrorActionPreference = "Stop"
{helpers}
$errorMessage = Remove-OwnedPath `
    -Path {powershell_quote(str(tmp_path / "pytest-g1-test"))} `
    -RuntimeRoot {powershell_quote(str(tmp_path))} `
    -Recurse
if ($errorMessage) {{ throw $errorMessage }}
"""
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "pytest-g1-test").exists()


def test_g1_cleanup_failures_cannot_skip_report_serialization(tmp_path):
    report = tmp_path / "G1_VERIFICATION.json"
    completed = run_cleanup_contract(tmp_path, report)

    assert completed.returncode == 1, completed.stderr
    assert (tmp_path / "later-step-ran.txt").read_text() == "ran"
    payload = json.loads(report.read_text(encoding="utf-8-sig"))
    assert payload["status"] == "FAIL"
    assert payload["git_commit"] == "test-commit"
    assert payload["cleanup_processes"] is True
    assert payload["cleanup_database"] is True
    assert payload["cleanup_files"] is True
    assert payload["cleanup_file_errors"] == [
        "Cleanup step 'native failure' failed: "
        "native command failed with exit code 7"
    ]


def test_g1_report_write_failure_exits_nonzero_and_preserves_prior_report(tmp_path):
    report_directory = tmp_path / "G1_VERIFICATION.json"
    report_directory.mkdir()
    sentinel = report_directory / "sentinel.txt"
    sentinel.write_text("prior report is not overwritten")
    report = report_directory / "missing" / "report.json"

    completed = run_cleanup_contract(tmp_path, report)

    assert completed.returncode == 1
    assert "Unable to write G-1 report" in completed.stdout
    assert sentinel.read_text() == "prior report is not overwritten"


def test_production_image_packages_machine_readable_registries():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")

    assert "COPY docs/project/registries ./docs/project/registries" in dockerfile
    assert "!docs/project/registries/*.json" in dockerignore
