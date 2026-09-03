import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "verify-g1.ps1"
DATABASE_MANAGER = ROOT / "scripts" / "manage_g1_database.py"
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
        "Verifying isolated closed-loop PostgreSQL lifecycle contracts",
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


def test_g1_archive_failure_stops_cleanup_to_retain_runtime_evidence(tmp_path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 cleanup contract")
    source = HARNESS.read_text(encoding="utf-8")
    helper_start = source.index("function Invoke-CleanupStep")
    harness_start = source.index("$startedAt =")
    helpers = source[helper_start:harness_start]
    marker = tmp_path / "cleanup-must-not-run.txt"
    report = tmp_path / "G1_VERIFICATION.json"
    invocation = f"""
$ErrorActionPreference = "Stop"
{helpers}
$result = [ordered]@{{
    gate = "G-1"
    status = "PASS"
    started_at = "2026-09-03T00:00:00Z"
    finished_at = $null
    git_commit = "test-commit"
    cleanup_processes = $true
    cleanup_database = $true
    cleanup_files = $true
    cleanup_file_errors = @()
    cleanup_error = $null
    error = $null
    report_error = $null
}}
$steps = @(
    @{{ Name = "persistent G-1 runtime evidence archive"; Action = {{ throw "archive unavailable" }} }},
    @{{ Name = "destructive cleanup"; Action = {{ [IO.File]::WriteAllText({powershell_quote(str(marker))}, "must-not-run") }} }}
)
$completion = Complete-G1Verification -Result $result -CleanupSteps $steps -ReportPath {powershell_quote(str(report))}
if (-not $completion.failed) {{ exit 31 }}
if (Test-Path -LiteralPath {powershell_quote(str(marker))}) {{ exit 32 }}
exit 0
"""
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", invocation],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(report.read_text(encoding="utf-8-sig"))
    assert payload["cleanup_error"] == (
        "Persistent G-1 evidence archive failed; disposable resources were retained"
    )


def test_g1_source_guard_blocks_source_changes_but_ignores_disposable_paths(tmp_path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 source guard contract")
    source = HARNESS.read_text(encoding="utf-8")
    helper_start = source.index("function Invoke-CleanupStep")
    harness_start = source.index("$startedAt =")
    helpers = source[helper_start:harness_start]
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "G-1 test"],
        check=True,
    )
    tracked = repository / "source.py"
    tracked.write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "source.py"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "init"], check=True)
    tracked.write_text("v2", encoding="utf-8")
    invocation = f"""
$ErrorActionPreference = "Stop"
{helpers}
    try {{
        Assert-SourceWorktreeClean -RepositoryRoot {powershell_quote(str(repository))}
        exit 11
    }} catch {{
        if (-not $_.Exception.Message.Contains("unregistered changes")) {{ exit 12 }}
    }}
exit 0
"""
    blocked = subprocess.run(
        [PWSH, "-NoProfile", "-Command", invocation],
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 0, f"rc={blocked.returncode}; stdout={blocked.stdout!r}; stderr={blocked.stderr!r}"

    tracked.write_text("v1", encoding="utf-8")
    (repository / "wuliu").mkdir()
    (repository / "wuliu" / "temporary.txt").write_text("temp", encoding="utf-8")
    (repository / "web").mkdir()
    (repository / "web" / "tsconfig.tsbuildinfo").write_text("temp", encoding="utf-8")
    (repository / "深入理解AI Agent(1).pdf").write_bytes(b"temp")
    disposable_invocation = f"""
$ErrorActionPreference = "Stop"
{helpers}
Assert-SourceWorktreeClean -RepositoryRoot {powershell_quote(str(repository))}
"""
    disposable = subprocess.run(
        [PWSH, "-NoProfile", "-Command", disposable_invocation],
        check=False,
        capture_output=True,
        text=True,
    )
    assert disposable.returncode == 0, disposable.stderr


def test_g1_evidence_archive_copy_is_atomic_and_outside_repository(tmp_path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 evidence archive contract")
    source = HARNESS.read_text(encoding="utf-8")
    helper_start = source.index("function Invoke-CleanupStep")
    harness_start = source.index("$startedAt =")
    helpers = source[helper_start:harness_start]
    repository = tmp_path / "repo"
    repository.mkdir()
    report = repository / "G1_VERIFICATION.json"
    report.write_text('{"status":"PASS"}', encoding="utf-8")
    archive = tmp_path / "archive" / "G1_VERIFICATION.json"
    invocation = f"""
$ErrorActionPreference = "Stop"
{helpers}
$published = Publish-G1EvidenceCopy `
    -SourcePath {powershell_quote(str(report))} `
    -DestinationPath {powershell_quote(str(archive))} `
    -RepositoryRoot {powershell_quote(str(repository))}
if ($published -ne {powershell_quote(str(archive))}) {{ exit 21 }}
if ((Get-FileHash -LiteralPath {powershell_quote(str(report))} -Algorithm SHA256).Hash -ne
    (Get-FileHash -LiteralPath {powershell_quote(str(archive))} -Algorithm SHA256).Hash) {{ exit 22 }}
$runtime_root = {powershell_quote(str(repository / ".runtime"))}
$runtime_evidence = Join-Path $runtime_root "team-agent-gate"
New-Item -ItemType Directory -Path $runtime_evidence -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $runtime_evidence "receipt.json"), "evidence")
$directory_archive = {powershell_quote(str(archive.parent / "runtime"))}
Publish-G1EvidenceDirectory `
    -SourceDirectory $runtime_evidence `
    -DestinationDirectory $directory_archive `
    -RepositoryRoot {powershell_quote(str(repository))} `
    -RuntimeRoot $runtime_root
if (-not (Test-Path -LiteralPath (Join-Path $directory_archive "receipt.json"))) {{ exit 24 }}
$result = [ordered]@{{
    gate = "G-1"
    status = "PASS"
    started_at = "2026-09-03T00:00:00Z"
    finished_at = $null
    git_commit = "test-commit"
    cleanup_processes = $true
    cleanup_database = $true
    cleanup_files = $true
    cleanup_file_errors = @()
    cleanup_error = $null
    error = $null
    report_error = $null
}}
$steps = @(@{{ Name = "noop"; Action = {{}} }})
$completion = Complete-G1Verification `
    -Result $result `
    -CleanupSteps $steps `
    -ReportPath {powershell_quote(str(report))} `
    -EvidenceArchivePath {powershell_quote(str(archive))} `
    -RepositoryRoot {powershell_quote(str(repository))}
if ($completion.failed -or -not (Test-Path -LiteralPath {powershell_quote(str(archive))})) {{ exit 25 }}
try {{
    Publish-G1EvidenceCopy `
        -SourcePath {powershell_quote(str(report))} `
        -DestinationPath {powershell_quote(str(repository / "forbidden.json"))} `
        -RepositoryRoot {powershell_quote(str(repository))} | Out-Null
    exit 23
}} catch {{ exit 0 }}
exit 0
"""
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", invocation],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, f"rc={completed.returncode}; stdout={completed.stdout!r}; stderr={completed.stderr!r}"


def test_g1_checks_source_worktree_before_cleanup_and_persists_evidence():
    source = HARNESS.read_text(encoding="utf-8")

    assert "KJDS_G1_EVIDENCE_ARCHIVE" in source
    assert "Publish-G1EvidenceCopy" in source
    assert source.index("Checking source worktree before cleanup") < source.index(
        "$completion = Complete-G1Verification"
    )
    assert "evidence_archive_report = $ArchivedReportPath" in source
    assert "evidence_archive_mutex_release_receipt = $ArchivedMutexReleaseReceipt" in source


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


def test_g1_coverage_issuer_principals_are_ephemeral_and_secrets_are_scrubbed():
    harness = HARNESS.read_text(encoding="utf-8")
    manager = DATABASE_MANAGER.read_text(encoding="utf-8")

    assert "KJDS_G1_COVERAGE_ISSUER_PASSWORD" in harness
    assert "KJDS_G1_RUNTIME_PASSWORD" in harness
    assert "KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL" in harness
    assert "KJDS_RUNTIME_DATABASE_URL" in harness
    assert '"grant-runtime"' in harness
    assert "Remove-Item Env:KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL" in harness
    assert "Remove-Item Env:KJDS_RUNTIME_DATABASE_URL" in harness
    assert "Remove-Item Env:KJDS_G1_COVERAGE_ISSUER_PASSWORD" in harness
    assert "Remove-Item Env:KJDS_G1_RUNTIME_PASSWORD" in harness
    assert "Remove-Item Env:KJDS_G1_RUN_TOKEN" in harness
    assert harness.index('"scripts/manage_g1_database.py", "acquire"') < harness.index(
        '"scripts/manage_g1_database.py", "recreate"'
    )
    assert "if ($DatabaseLeaseAcquired)" in harness
    assert "ISSUANCE_SIGNING_KEY" not in harness

    assert "KJDS_G1_RUN_TOKEN" in manager
    assert "run_token_sha256" in manager
    assert "roles_owned" in manager
    assert "database_owned" in manager
    assert "fixed-resource lease is not owned by this run" in manager
    assert "shobj_description" in manager
    assert "kjds_gdc_issuance_owner NOLOGIN NOINHERIT" in manager
    assert "kjds_gdc_issuance_runtime LOGIN NOINHERIT" in manager
    assert "kjds_g1_runtime LOGIN NOINHERIT" in manager
    assert "DROP OWNED BY" not in manager
    assert "REVOKE ADMIN OPTION FOR" in manager
    assert "_preflight_role_cleanup" in manager
    assert "GDC_RECEIPT_TABLE" in manager
    assert "REVOKE EXECUTE ON FUNCTION kjds_gdc_issue_evidence" in manager
    assert "print({" in manager
    assert "issuer_password" not in manager.split("print({", 1)[1]

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert sum(
        line.strip().startswith("KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL:")
        for line in compose.splitlines()
    ) == 1


def test_g1_strategic_benchmark_sealing_key_is_ephemeral_and_scrubbed():
    harness = HARNESS.read_text(encoding="utf-8")

    key_assignment = "$env:KJDS_STRATEGIC_BENCHMARK_SEALING_KEY = $StrategicBenchmarkSealingKey"
    test_invocation = '"python", "-m", "pytest"'
    cleanup = "Remove-Item Env:KJDS_STRATEGIC_BENCHMARK_SEALING_KEY"

    assert "RandomNumberGenerator]::GetBytes(32)" in harness
    assert key_assignment in harness
    assert cleanup in harness
    assert harness.index(key_assignment) < harness.index(test_invocation)
    assert harness.index(test_invocation) < harness.index(cleanup)


def test_g1_isolates_cluster_global_coverage_postgres_contracts_before_lease():
    harness = HARNESS.read_text(encoding="utf-8")
    postgres_contract = (ROOT / "tests" / "test_global_data_coverage_ledger_postgres.py").read_text(
        encoding="utf-8"
    )

    contract = '"tests\\test_global_data_coverage_ledger_postgres.py"'
    recovery_gate = "Recovering receipt-owned interrupted PostgreSQL resources"
    dedicated_gate = "Verifying isolated global data coverage PostgreSQL contracts"
    recovery = '"scripts/manage_g1_database.py", "recover"'
    acquire = '"scripts/manage_g1_database.py", "acquire"'
    generic_exclusion = "$_ -notin @("

    assert contract in harness
    assert recovery_gate in harness
    assert dedicated_gate in harness
    assert generic_exclusion in harness
    assert "$DataCoveragePostgresContract," in harness
    assert "$ClosedLoopPostgresContract" in harness
    assert harness.index(recovery_gate) < harness.index(recovery) < harness.index(dedicated_gate)
    assert harness.index(dedicated_gate) < harness.index(acquire)
    assert "$env:KJDS_DATABASE_URL = $AdminDatabaseUrl" in harness
    assert "$result.g1_stale_resource_recovery = $true" in harness
    assert "$result.global_data_coverage_postgres_contract = $true" in harness
    assert "g1_stale_resource_recovery = $false" in harness
    fixture = postgres_contract[
        postgres_contract.index('@pytest.fixture(scope="module")') : postgres_contract.index(
            "@pytest.fixture\ndef service"
        )
    ]
    assert "acquire_gdc_contract_resources" in fixture
    assert "release_gdc_contract_resources" in fixture
    assert "DROP ROLE" not in fixture


def test_g1_generic_tests_keep_owned_runtime_target_and_isolate_lifecycle_modules():
    harness = HARNESS.read_text(encoding="utf-8")

    marker = "Running generic tests with isolated migration-lifecycle database"
    invocation = 'Invoke-External -Command uv -Arguments (@("run", "python", "-m", "pytest"'
    marker_offset = harness.index(marker)
    migration_offset = harness.index(
        "$env:KJDS_DATABASE_URL = $MigrationDatabaseUrl", marker_offset
    )
    runtime_offset = harness.index(
        "$env:KJDS_RUNTIME_DATABASE_URL = $RuntimeDatabaseUrl", marker_offset
    )
    seam_offset = harness.index(
        "$env:KJDS_G1_CONTRACT_DATABASE_URL = $ContractDatabaseUrl", marker_offset
    )
    invocation_offset = harness.index(invocation, marker_offset)
    seam_cleanup_offset = harness.index(
        "Remove-Item Env:KJDS_G1_CONTRACT_DATABASE_URL", invocation_offset
    )

    assert harness.count("$env:KJDS_DATABASE_URL = $AdminDatabaseUrl") == 1
    assert (
        "$env:KJDS_DATABASE_URL = $ContractDatabaseUrl"
        not in harness[marker_offset:invocation_offset]
    )
    assert (
        marker_offset
        < migration_offset
        < runtime_offset
        < seam_offset
        < invocation_offset
        < seam_cleanup_offset
    )


def test_g1_generic_contract_database_has_run_scoped_ownership_and_cleanup():
    harness = HARNESS.read_text(encoding="utf-8")
    media_postgres = (ROOT / "tests" / "test_media_connectors_postgres.py").read_text(
        encoding="utf-8"
    )
    primary_postgres = (
        ROOT / "tests" / "test_primary_source_intake_postgres.py"
    ).read_text(encoding="utf-8")
    team_agent_postgres = (
        ROOT / "tests" / "test_team_agent_evolution_postgres.py"
    ).read_text(encoding="utf-8")

    create_marker = "Creating run-scoped generic PostgreSQL contract database"
    generic_marker = "Running generic tests with isolated migration-lifecycle database"
    cleanup_name = 'Name = "run-scoped generic PostgreSQL contract database"'

    assert "kjds_g1_contract_" in harness
    assert "kjds-g1-contract:" in harness
    assert "shobj_description(oid,'pg_database')" in harness
    assert "G-1 contract database is not owned by this run" in harness
    assert '"upgrade", "20260803_0094"' in harness
    assert "$env:KJDS_G1_CONTRACT_DATABASE_URL = $ContractDatabaseUrl" in harness
    assert "Remove-Item Env:KJDS_G1_CONTRACT_DATABASE_URL" in harness
    assert harness.index(create_marker) < harness.index(generic_marker)
    assert harness.index(generic_marker) < harness.index(cleanup_name)
    assert "$result.cleanup_contract_database = -not $ContractDatabaseCreated" in harness
    assert "Remove-Item Env:KJDS_G1_RUN_TOKEN_SHA256" in harness
    seam_consumers = {
        path.name
        for path in (ROOT / "tests").glob("test_*.py")
        if path.name
        not in {
            Path(__file__).name,
            "test_closed_loop_evolution_postgres.py",
        }
        and "KJDS_G1_CONTRACT_DATABASE_URL" in path.read_text(encoding="utf-8")
    }
    assert seam_consumers == {
        "test_media_connectors_postgres.py",
        "test_primary_source_intake_postgres.py",
        "test_team_agent_evolution_postgres.py",
    }
    for module in (media_postgres, primary_postgres):
        assert 'os.getenv("KJDS_G1_CONTRACT_DATABASE_URL")' in module
        assert 'os.environ["KJDS_DATABASE_URL"] = DATABASE_URL' in module
        assert 'os.environ["KJDS_DATABASE_URL"] = original_database_url' in module
    assert 'os.getenv("KJDS_G1_CONTRACT_DATABASE_URL")' in team_agent_postgres
    assert 'os.environ["KJDS_DATABASE_URL"] = target.url.render_as_string(' in (
        team_agent_postgres
    )
    assert 'os.environ["KJDS_DATABASE_URL"] = original_database_url' in (
        team_agent_postgres
    )


def test_g1_runs_closed_loop_lifecycle_before_primary_lease_and_excludes_generic():
    harness = HARNESS.read_text(encoding="utf-8")
    closed_loop_postgres = (
        ROOT / "tests" / "test_closed_loop_evolution_postgres.py"
    ).read_text(encoding="utf-8")

    create_marker = "Creating run-scoped generic PostgreSQL contract database"
    dedicated_marker = "Verifying isolated closed-loop PostgreSQL lifecycle contracts"
    acquire = '"scripts/manage_g1_database.py", "acquire"'
    generic_marker = "Running generic tests with isolated migration-lifecycle database"
    exclusion = "$_ -notin @("
    dedicated_offset = harness.index(dedicated_marker)
    seam_clear_offset = harness.index(
        "Remove-Item Env:KJDS_G1_CONTRACT_DATABASE_URL", dedicated_offset
    )
    seam_set_offset = harness.index(
        "$env:KJDS_G1_CONTRACT_DATABASE_URL = $ContractDatabaseUrl"
    )

    assert '"tests\\test_closed_loop_evolution_postgres.py"' in harness
    assert harness.index(create_marker) < harness.index(dedicated_marker)
    assert harness.index(dedicated_marker) < harness.index(acquire)
    assert harness.index(dedicated_marker) < harness.index(generic_marker)
    assert dedicated_offset < seam_clear_offset < harness.index(acquire)
    assert harness.index(acquire) < seam_set_offset
    assert exclusion in harness
    exclusion_offset = harness.index(exclusion)
    assert "$ClosedLoopPostgresContract" in harness[exclusion_offset:]
    assert "$result.closed_loop_evolution_postgres_contract = $true" in harness
    assert "closed_loop_evolution_postgres_contract = $false" in harness
    assert 'G1_CONTRACT_DATABASE_URL = os.getenv("KJDS_G1_CONTRACT_DATABASE_URL")' in (
        closed_loop_postgres
    )
    assert "must run in the dedicated" in closed_loop_postgres


def test_g1_runs_teamagent_postgres_gate_in_empty_owned_database_phase():
    """The durable TeamAgent gate must have an explicit, non-skippable phase."""

    harness = HARNESS.read_text(encoding="utf-8")
    acquire = '"scripts/manage_g1_database.py", "acquire"'
    recreate = '"scripts/manage_g1_database.py", "recreate"'
    teamagent_marker = "Verifying TeamAgent PostgreSQL 17 contracts"
    replay_marker = "Replaying migrations in disposable database"
    teamagent_env = "$env:KJDS_TEAM_AGENT_DATABASE_URL = $MigrationDatabaseUrl"
    teamagent_runner = '"scripts/verify_team_agent_postgres_gate.py"'
    teamagent_junit = '"--junit-output", $TeamAgentGateJunit'
    teamagent_receipt = '"--receipt-output", $TeamAgentGateReceipt'

    teamagent_offset = harness.index(teamagent_marker)
    acquire_offset = harness.index(acquire, teamagent_offset - 4000)
    recreate_offset = harness.index(recreate, acquire_offset)
    replay_offset = harness.index(replay_marker, teamagent_offset)
    cleanup_offset = harness.index(
        "Remove-Item Env:KJDS_TEAM_AGENT_DATABASE_URL",
        teamagent_offset,
    )

    assert acquire_offset < recreate_offset < teamagent_offset
    assert teamagent_offset < cleanup_offset < replay_offset
    assert teamagent_env in harness[teamagent_offset:replay_offset]
    assert teamagent_runner in harness[teamagent_offset:replay_offset]
    assert teamagent_junit in harness[teamagent_offset:replay_offset]
    assert teamagent_receipt in harness[teamagent_offset:replay_offset]
    assert "TeamAgent PostgreSQL Gate receipt was incomplete" in harness
    assert "TeamAgent PostgreSQL Gate JUnit hash does not match its receipt" in harness
    assert "TeamAgent PostgreSQL Gate evidence" in harness
    assert "team_agent_postgres_gate = $false" in harness
    assert "$result.team_agent_postgres_gate = $true" in harness
    assert "skipped contracts cannot look like" in harness


def test_g1_global_mutex_precedes_fixed_database_and_role_contracts():
    harness = HARNESS.read_text(encoding="utf-8")

    mutex_wait = "$G1ControlMutex.WaitOne(0)"
    dedicated_gate = "Verifying isolated global data coverage PostgreSQL contracts"
    mutex_release = "$G1ControlMutex.ReleaseMutex()"

    assert '"Global\\KJDS-G1-Verification"' in harness
    assert harness.index(mutex_wait) < harness.index(dedicated_gate)
    assert "$result.g1_control_mutex_acquired = $true" in harness
    assert mutex_release in harness


def test_g1_global_mutex_covers_cleanup_and_authoritative_report_publication():
    harness = HARNESS.read_text(encoding="utf-8")

    completion = "$completion = Complete-G1Verification"
    report_hash = "Get-FileHash -LiteralPath $completionReportPath"
    mutex_release = "$G1ControlMutex.ReleaseMutex()"
    release_receipt = "G-1-control-mutex-release"

    report_hash_offset = harness.index(report_hash)
    receipt_publish_offset = harness.index(release_receipt, report_hash_offset)
    receipt_validation_offset = harness.index(
        "-not (Test-G1ControlMutexReleaseReceipt", receipt_publish_offset
    )
    mutex_release_offset = harness.index(mutex_release, receipt_validation_offset)

    assert harness.index(completion) < report_hash_offset
    assert report_hash_offset < receipt_publish_offset
    assert receipt_publish_offset < receipt_validation_offset < mutex_release_offset
    assert "$completionReportPath = if ($G1ControlMutexAcquired)" in harness
    assert "$AuthoritativeReportPath" in harness
    assert "$PerRunReportPath" in harness
    assert "g1_control_mutex_finalization_required = $true" in harness
    assert "$result.g1_control_mutex_release_receipt = $G1ControlMutexReleaseReceipt" in harness
    assert 'state = "release_prepared"' in harness
    assert "report_sha256 = $publishedReportSha256" in harness
    assert "run_token_sha256 = $RunTokenSha256" in harness
    assert "G-1 control mutex finalization receipt publication failed" in harness


def test_g1_global_mutex_blocks_a_second_report_publisher_until_release(tmp_path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 mutex contract")

    mutex_name = f"Global\\KJDS-G1-Verification-test-{uuid.uuid4().hex}"
    marker = tmp_path / "owner-one-held.txt"
    release = tmp_path / "owner-one-release.txt"
    report = tmp_path / "G1_VERIFICATION.json"
    report.write_text("baseline", encoding="utf-8")
    owner_script = f"""
$ErrorActionPreference = "Stop"
$mutex = [Threading.Mutex]::new($false, {powershell_quote(mutex_name)})
if (-not $mutex.WaitOne(0)) {{ $mutex.Dispose(); exit 10 }}
try {{
    [IO.File]::WriteAllText({powershell_quote(str(marker))}, "held")
    while (-not (Test-Path -LiteralPath {powershell_quote(str(release))})) {{
        Start-Sleep -Milliseconds 25
    }}
    $temporary = {powershell_quote(str(report) + ".owner-one.tmp")}
    [IO.File]::WriteAllText($temporary, "owner-one")
    Move-Item -LiteralPath $temporary -Destination {powershell_quote(str(report))} -Force
}} finally {{
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}}
"""
    contender_script = f"""
$ErrorActionPreference = "Stop"
$mutex = [Threading.Mutex]::new($false, {powershell_quote(mutex_name)})
if (-not $mutex.WaitOne(0)) {{ $mutex.Dispose(); exit 23 }}
try {{
    [IO.File]::WriteAllText({powershell_quote(str(report))}, "owner-two")
}} finally {{
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}}
"""
    owner = subprocess.Popen(
        [PWSH, "-NoProfile", "-Command", owner_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists():
            if owner.poll() is not None:
                stdout, stderr = owner.communicate()
                raise AssertionError(f"owner exited early: {stdout}\n{stderr}")
            if time.monotonic() >= deadline:
                raise AssertionError("owner did not acquire the mutex")
            time.sleep(0.025)

        blocked = subprocess.run(
            [PWSH, "-NoProfile", "-Command", contender_script],
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 23, blocked.stderr
        assert report.read_text(encoding="utf-8") == "baseline"

        release.write_text("release", encoding="utf-8")
        owner_stdout, owner_stderr = owner.communicate(timeout=10)
        assert owner.returncode == 0, f"{owner_stdout}\n{owner_stderr}"
        assert report.read_text(encoding="utf-8") == "owner-one"

        admitted = subprocess.run(
            [PWSH, "-NoProfile", "-Command", contender_script],
            check=False,
            capture_output=True,
            text=True,
        )
        assert admitted.returncode == 0, admitted.stderr
        assert report.read_text(encoding="utf-8") == "owner-two"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)


def test_g1_mutex_release_receipt_validator_binds_report_run_and_commit(tmp_path):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the G-1 mutex receipt contract")
    source = HARNESS.read_text(encoding="utf-8")
    function_start = source.index("function Test-G1ControlMutexReleaseReceipt")
    harness_start = source.index("$startedAt =")
    validator = source[function_start:harness_start]
    receipt = tmp_path / "G1_MUTEX_RELEASE.json"
    payload = {
        "gate": "G-1-control-mutex-release",
        "state": "release_prepared",
        "run_token_sha256": "a" * 64,
        "git_commit": "commit-a",
        "report": str(tmp_path / "G1_VERIFICATION.json"),
        "report_sha256": "b" * 64,
        "prepared_at": "2026-08-05T00:00:00Z",
    }
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    invocation = f"""
$ErrorActionPreference = "Stop"
{validator}
$valid = Test-G1ControlMutexReleaseReceipt `
    -Path {powershell_quote(str(receipt))} `
    -RunTokenSha256 {powershell_quote('a' * 64)} `
    -GitCommit "commit-a" `
    -ReportPath {powershell_quote(payload['report'])} `
    -ReportSha256 {powershell_quote('b' * 64)}
$wrongRun = Test-G1ControlMutexReleaseReceipt `
    -Path {powershell_quote(str(receipt))} `
    -RunTokenSha256 {powershell_quote('c' * 64)} `
    -GitCommit "commit-a" `
    -ReportPath {powershell_quote(payload['report'])} `
    -ReportSha256 {powershell_quote('b' * 64)}
$wrongHash = Test-G1ControlMutexReleaseReceipt `
    -Path {powershell_quote(str(receipt))} `
    -RunTokenSha256 {powershell_quote('a' * 64)} `
    -GitCommit "commit-a" `
    -ReportPath {powershell_quote(payload['report'])} `
    -ReportSha256 {powershell_quote('d' * 64)}
if (-not $valid -or $wrongRun -or $wrongHash) {{ exit 1 }}
"""
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", invocation],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
