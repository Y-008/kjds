import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "manage-evidence-health-task.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="The evidence-health scheduler contract requires Windows Task Scheduler",
)


def run_manager(
    *arguments: str,
    env: dict[str, str] | None = None,
    script: Path = SCRIPT,
    cwd: Path = ROOT,
):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the Windows task contract")
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(script), *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed, payload


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_mocked_audit(*, drift: bool = False):
    if not PWSH:
        pytest.skip("PowerShell 7 is required for the Windows task contract")
    task_name = f"KJDS-Test-{uuid.uuid4()}"
    health_script = ROOT / "scripts" / "run-24x7-health.ps1"
    arguments = f'-NoProfile -NonInteractive -File "{health_script}" -ControlPlaneOnly'
    if drift:
        arguments += " -KJDS_API_KEY=secret-do-not-print"
    wrapper = f"""
function Get-ScheduledTask {{
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    [pscustomobject]@{{
        State = 'Ready'
        Actions = @([pscustomobject]@{{
            Execute = {powershell_quote(PWSH)}
            Arguments = {powershell_quote(arguments)}
            WorkingDirectory = {powershell_quote(str(ROOT))}
        }})
        Triggers = @([pscustomobject]@{{
            Repetition = [pscustomobject]@{{ Interval = [timespan]::FromMinutes(15) }}
        }})
        Settings = [pscustomobject]@{{
            ExecutionTimeLimit = [timespan]::FromMinutes(5)
            MultipleInstances = 'IgnoreNew'
        }}
    }}
}}
function Get-ScheduledTaskInfo {{
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    [pscustomobject]@{{ LastTaskResult = 0; LastRunTime = (Get-Date).AddMinutes(-1) }}
}}
function Get-WinEvent {{
    param($FilterHashtable, [int]$MaxEvents, $ErrorAction)
    if ($FilterHashtable.Id -ne 201) {{
        throw 'Expected native action-completed event 201'
    }}
    1..3 | ForEach-Object {{
        $event = [pscustomobject]@{{
            TimeCreated = (Get-Date).AddMinutes(-$_)
            XmlText = '<Event><EventData><Data Name="TaskName">\\{task_name}</Data><Data Name="TaskInstanceId">{{00000000-0000-0000-0000-00000000000' + $_ + '}}</Data><Data Name="ResultCode">0</Data></EventData></Event>'
        }}
        $event | Add-Member -MemberType ScriptMethod -Name ToXml -Value {{ $this.XmlText }}
        $event
    }}
}}
& {powershell_quote(str(SCRIPT))} -Mode Audit -TaskName {powershell_quote(task_name)}
exit $LASTEXITCODE
"""
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-Command", wrapper],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def test_plan_is_default_secret_free_and_has_no_mutation():
    task_name = f"KJDS-Test-{uuid.uuid4()}"

    completed, payload = run_manager("-TaskName", task_name)

    assert completed.returncode == 0
    assert payload == {
        "schema_version": "kjds-evidence-health-task-v1",
        "generated_at": payload["generated_at"],
        "mode": "plan",
        "task_name": task_name,
        "task_path": "\\",
        "health_script": str(ROOT / "scripts" / "run-24x7-health.ps1"),
        "working_directory": str(ROOT),
        "interval_minutes": 15,
        "execution_limit_minutes": 5,
        "configuration_source": "project_env_file",
        "control_plane_only": True,
        "command_contains_secrets": False,
        "required_consecutive_successes": 3,
        "mutation_performed": False,
        "status": "planned_no_mutation",
    }
    assert "API_KEY" not in completed.stdout
    assert "TOKEN=" not in completed.stdout

    audit, audit_payload = run_manager("-Mode", "Audit", "-TaskName", task_name)
    assert audit.returncode == 2
    assert audit_payload["audit"]["task_found"] is False
    assert (
        audit_payload["audit"]["error"]
        == "Scheduled task was not found or could not be read"
    )
    assert audit_payload["status"] == "not_accepted"


def test_install_fails_closed_before_registration_when_health_preflight_fails(tmp_path):
    task_name = f"KJDS-Test-{uuid.uuid4()}"
    isolated_scripts = tmp_path / "scripts"
    isolated_scripts.mkdir()
    isolated_manager = isolated_scripts / SCRIPT.name
    shutil.copy2(SCRIPT, isolated_manager)
    shutil.copy2(ROOT / "scripts" / "run-24x7-health.ps1", isolated_scripts)
    secret_values = [
        "operator-do-not-print-4921",
        "monitor-do-not-print-4921",
        "executor-do-not-print-4921",
        "pilot-do-not-print-4921",
        "ozon-do-not-print-4921",
    ]
    env = os.environ.copy()
    env.update(
        {
            "KJDS_CONTROL_PLANE_URL": "http://127.0.0.1:1",
            "KJDS_API_KEY": secret_values[0],
            "KJDS_MONITOR_API_KEY": secret_values[1],
            "KJDS_API_KEYS_JSON": json.dumps(
                {
                    secret_values[0]: {"actor": "operator", "roles": ["operator"]},
                    secret_values[1]: {"actor": "monitor", "roles": ["monitor"]},
                }
            ),
            "KJDS_EXECUTOR_API_KEY": secret_values[2],
            "KJDS_PILOT_READER_API_KEY": secret_values[3],
            "OZON_API_KEY": secret_values[4],
            "KJDS_HEALTH_REQUIRED": "true",
        }
    )

    completed, payload = run_manager(
        "-Mode",
        "Install",
        "-TaskName",
        task_name,
        env=env,
        script=isolated_manager,
        cwd=tmp_path,
    )

    assert completed.returncode == 2
    assert payload["mutation_performed"] is False
    assert payload["status"] == "preflight_failed"
    assert payload["preflight"]["ok"] is False
    assert payload["preflight"]["configuration_source_ready"] is False
    for secret in secret_values:
        assert secret not in completed.stdout
        assert secret not in completed.stderr

    audit, audit_payload = run_manager("-Mode", "Audit", "-TaskName", task_name)
    assert audit.returncode == 2
    assert audit_payload["audit"]["task_found"] is False


def test_invalid_interval_is_rejected_by_parameter_contract():
    completed, payload = run_manager("-IntervalMinutes", "4")

    assert completed.returncode != 0
    assert payload is None
    assert "IntervalMinutes" in completed.stderr
    assert "greater than or equal to 5" in completed.stderr


def test_audit_accepts_exact_definition_with_three_native_success_events():
    completed, payload = run_mocked_audit()

    assert completed.returncode == 0
    assert payload["status"] == "accepted"
    assert payload["audit"]["definition_valid"] is True
    assert payload["audit"]["history"]["available"] is True
    assert payload["audit"]["history"]["consecutive_successes"] == 3
    assert payload["audit"]["accepted"] is True


def test_audit_rejects_secret_bearing_definition_even_with_success_history():
    completed, payload = run_mocked_audit(drift=True)

    assert completed.returncode == 2
    assert payload["status"] == "not_accepted"
    assert payload["audit"]["action_valid"] is False
    assert payload["audit"]["arguments_secret_free"] is False
    assert payload["audit"]["history"]["consecutive_successes"] == 3
    assert payload["audit"]["accepted"] is False
    assert "secret-do-not-print" not in completed.stdout
    assert "secret-do-not-print" not in completed.stderr
