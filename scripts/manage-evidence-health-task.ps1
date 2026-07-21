param(
    [ValidateSet("Plan", "Audit", "Install")]
    [string]$Mode = "Plan",
    [ValidateNotNullOrEmpty()]
    [string]$TaskName = "KJDS-Evidence-Integrity-Health",
    [ValidateRange(5, 1440)]
    [int]$IntervalMinutes = 15,
    [ValidateRange(1, 60)]
    [int]$ExecutionLimitMinutes = 5
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$HealthScript = Join-Path $PSScriptRoot "run-24x7-health.ps1"
$EnvironmentFile = Join-Path $Root ".env"
$PowerShell = (Get-Command pwsh.exe -ErrorAction Stop).Source
$TaskPath = "\"
$ExpectedArguments = "-NoProfile -NonInteractive -File `"$HealthScript`" -ControlPlaneOnly"
$ExpectedInterval = New-TimeSpan -Minutes $IntervalMinutes
$ExpectedExecutionLimit = New-TimeSpan -Minutes $ExecutionLimitMinutes
$RequiredConsecutiveSuccesses = 3

function Write-ResultAndExit {
    param(
        [Parameter(Mandatory = $true)]$Result,
        [Parameter(Mandatory = $true)][int]$ExitCode
    )
    $Result | ConvertTo-Json -Depth 8
    exit $ExitCode
}

function Test-SecretFreeArguments {
    param([string]$Arguments)

    if (-not $Arguments) { return $false }
    $forbidden = @(
        "KJDS_API_KEY",
        "KJDS_MONITOR_API_KEY",
        "KJDS_API_KEYS_JSON",
        "KJDS_EXECUTOR_API_KEY",
        "KJDS_PILOT_READER_API_KEY",
        "OZON_API_KEY",
        "TOKEN=",
        "SECRET=",
        "PASSWORD="
    )
    return -not ($forbidden | Where-Object { $Arguments.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
}

function Convert-TaskDuration {
    param($Value)

    if ($null -eq $Value) { return $null }
    if ($Value -is [TimeSpan]) { return $Value }
    try {
        return [Xml.XmlConvert]::ToTimeSpan([string]$Value)
    }
    catch {
        return $null
    }
}

function Get-TaskCompletionHistory {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$MaximumEvents = 200
    )

    $result = [ordered]@{
        available = $false
        matching_events = 0
        consecutive_successes = 0
        latest_results = @()
        error = $null
    }
    try {
        $events = Get-WinEvent -FilterHashtable @{
            LogName = "Microsoft-Windows-TaskScheduler/Operational"
            Id = 102
            StartTime = (Get-Date).AddDays(-7)
        } -MaxEvents $MaximumEvents -ErrorAction Stop
        $result.available = $true
        $target = "\$Name"
        $matching = foreach ($event in $events) {
            $xml = [xml]$event.ToXml()
            $data = @{}
            foreach ($entry in $xml.Event.EventData.Data) {
                $data[[string]$entry.Name] = [string]$entry.'#text'
            }
            $eventTaskName = @($data.TaskName, $data.TaskPath) |
                Where-Object { $_ } |
                Select-Object -First 1
            if ($eventTaskName -ne $target -and $eventTaskName -ne $Name) { continue }
            $rawResult = @($data.ResultCode, $data.Result) |
                Where-Object { $null -ne $_ -and $_ -ne "" } |
                Select-Object -First 1
            $parsedResult = $null
            if ($null -ne $rawResult) {
                try {
                    $textResult = [string]$rawResult
                    $parsedResult = if ($textResult.StartsWith("0x", [StringComparison]::OrdinalIgnoreCase)) {
                        [Convert]::ToInt64($textResult.Substring(2), 16)
                    } else {
                        [long]$textResult
                    }
                }
                catch {
                    $parsedResult = $null
                }
            }
            [pscustomobject]@{
                completed_at = $event.TimeCreated.ToUniversalTime().ToString("o")
                result_code = $parsedResult
            }
        }
        $latest = @($matching | Sort-Object completed_at -Descending | Select-Object -First $RequiredConsecutiveSuccesses)
        $result.matching_events = @($matching).Count
        $result.latest_results = $latest
        foreach ($entry in $latest) {
            if ($entry.result_code -ne 0) { break }
            $result.consecutive_successes += 1
        }
    }
    catch {
        $result.error = "Task Scheduler completion history is unavailable"
    }
    return $result
}

function Get-TaskAudit {
    param([Parameter(Mandatory = $true)][string]$Name)

    $audit = [ordered]@{
        task_found = $false
        enabled = $false
        action_valid = $false
        arguments_secret_free = $false
        working_directory_valid = $false
        trigger_valid = $false
        execution_limit_valid = $false
        overlap_policy_valid = $false
        last_result = $null
        last_run_time = $null
        history = [ordered]@{
            available = $false
            matching_events = 0
            consecutive_successes = 0
            latest_results = @()
            error = $null
        }
        definition_valid = $false
        accepted = $false
        error = $null
    }
    try {
        $task = Get-ScheduledTask -TaskName $Name -TaskPath $TaskPath -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $Name -TaskPath $TaskPath -ErrorAction Stop
        $audit.task_found = $true
        $audit.enabled = [string]$task.State -ne "Disabled"

        $actions = @($task.Actions)
        if ($actions.Count -eq 1) {
            $action = $actions[0]
            $audit.arguments_secret_free = Test-SecretFreeArguments -Arguments ([string]$action.Arguments)
            $audit.working_directory_valid = [string]$action.WorkingDirectory -eq $Root
            $audit.action_valid =
                [IO.Path]::GetFullPath([string]$action.Execute) -ieq [IO.Path]::GetFullPath($PowerShell) -and
                [string]$action.Arguments -eq $ExpectedArguments
        }

        $triggers = @($task.Triggers)
        if ($triggers.Count -eq 1) {
            $actualInterval = Convert-TaskDuration $triggers[0].Repetition.Interval
            $audit.trigger_valid = $null -ne $actualInterval -and $actualInterval -eq $ExpectedInterval
        }
        $actualExecutionLimit = Convert-TaskDuration $task.Settings.ExecutionTimeLimit
        $audit.execution_limit_valid =
            $null -ne $actualExecutionLimit -and
            $actualExecutionLimit -eq $ExpectedExecutionLimit
        $audit.overlap_policy_valid = [string]$task.Settings.MultipleInstances -eq "IgnoreNew"
        $audit.last_result = [long]$info.LastTaskResult
        if ($info.LastRunTime -and $info.LastRunTime.Year -gt 1900) {
            $audit.last_run_time = $info.LastRunTime.ToUniversalTime().ToString("o")
        }
        $audit.history = Get-TaskCompletionHistory -Name $Name
        $audit.definition_valid =
            $audit.enabled -and
            $audit.action_valid -and
            $audit.arguments_secret_free -and
            $audit.working_directory_valid -and
            $audit.trigger_valid -and
            $audit.execution_limit_valid -and
            $audit.overlap_policy_valid
        $audit.accepted =
            $audit.definition_valid -and
            $audit.last_result -eq 0 -and
            $audit.history.available -and
            $audit.history.consecutive_successes -ge $RequiredConsecutiveSuccesses
    }
    catch [Microsoft.Management.Infrastructure.CimException] {
        $audit.error = "Scheduled task was not found or could not be read"
    }
    catch {
        $audit.error = "Scheduled task audit failed"
    }
    return $audit
}

$baseResult = [ordered]@{
    schema_version = "kjds-evidence-health-task-v1"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = $Mode.ToLowerInvariant()
    task_name = $TaskName
    task_path = $TaskPath
    health_script = $HealthScript
    working_directory = $Root
    interval_minutes = $IntervalMinutes
    execution_limit_minutes = $ExecutionLimitMinutes
    configuration_source = "project_env_file"
    control_plane_only = $true
    command_contains_secrets = $false
    required_consecutive_successes = $RequiredConsecutiveSuccesses
    mutation_performed = $false
    status = $null
}

if ($Mode -eq "Plan") {
    $baseResult.status = "planned_no_mutation"
    Write-ResultAndExit -Result $baseResult -ExitCode 0
}

if ($Mode -eq "Audit") {
    $audit = Get-TaskAudit -Name $TaskName
    $baseResult.audit = $audit
    $baseResult.status = if ($audit.accepted) { "accepted" } else { "not_accepted" }
    Write-ResultAndExit -Result $baseResult -ExitCode $(if ($audit.accepted) { 0 } else { 2 })
}

if (
    -not (Test-Path -LiteralPath $HealthScript -PathType Leaf) -or
    -not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)
) {
    $baseResult.status = "preflight_failed"
    $baseResult.preflight = [ordered]@{
        ok = $false
        exit_code = $null
        configuration_source_ready = Test-Path -LiteralPath $EnvironmentFile -PathType Leaf
        error = "Scheduler-visible project configuration or health script is unavailable"
    }
    Write-ResultAndExit -Result $baseResult -ExitCode 2
}

$healthSettingNames = @(
    "KJDS_CONTROL_PLANE_URL",
    "KJDS_API_KEY",
    "KJDS_MONITOR_API_KEY",
    "KJDS_API_KEYS_JSON",
    "KJDS_EXECUTOR_API_KEY",
    "KJDS_PILOT_READER_API_KEY",
    "OZON_API_KEY",
    "KJDS_EVIDENCE_SCAN_PAGE_SIZE",
    "KJDS_EVIDENCE_SCAN_MAX_PAGES",
    "KJDS_HEALTH_REQUIRED"
)
$savedProcessSettings = @{}
try {
    foreach ($name in $healthSettingNames) {
        $savedProcessSettings[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    $preflightOutput = & $HealthScript -ControlPlaneOnly | Out-String
    $preflightExitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
}
finally {
    foreach ($name in $healthSettingNames) {
        [Environment]::SetEnvironmentVariable($name, $savedProcessSettings[$name], "Process")
    }
}
$preflightPayload = $null
try { $preflightPayload = $preflightOutput | ConvertFrom-Json }
catch { $preflightPayload = $null }
$preflightOk =
    $preflightExitCode -eq 0 -and
    $null -ne $preflightPayload -and
    $preflightPayload.control_plane.ok -eq $true -and
    $preflightPayload.operations_readiness.ok -eq $true -and
    $preflightPayload.evidence_integrity.ok -eq $true
$baseResult.preflight = [ordered]@{
    ok = $preflightOk
    exit_code = $preflightExitCode
    configuration_source_ready = $true
    control_plane_ok = $null -ne $preflightPayload -and $preflightPayload.control_plane.ok -eq $true
    operations_readiness_ok = $null -ne $preflightPayload -and $preflightPayload.operations_readiness.ok -eq $true
    evidence_integrity_ok = $null -ne $preflightPayload -and $preflightPayload.evidence_integrity.ok -eq $true
    error = $(if ($preflightOk) { $null } else { "Control-plane-only health preflight did not pass" })
}
if (-not $preflightOk) {
    $baseResult.status = "preflight_failed"
    Write-ResultAndExit -Result $baseResult -ExitCode 2
}

try {
    $action = New-ScheduledTaskAction `
        -Execute $PowerShell `
        -Argument $ExpectedArguments `
        -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval $ExpectedInterval
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit $ExpectedExecutionLimit
    Register-ScheduledTask `
        -TaskName $TaskName `
        -TaskPath $TaskPath `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "KJDS evidence-integrity control-plane health loop" `
        -Force | Out-Null
    $baseResult.mutation_performed = $true
    $baseResult.audit = Get-TaskAudit -Name $TaskName
    if (-not $baseResult.audit.definition_valid) {
        $baseResult.status = "installed_definition_invalid"
        Write-ResultAndExit -Result $baseResult -ExitCode 2
    }
    $baseResult.status = "installed_pending_history"
    Write-ResultAndExit -Result $baseResult -ExitCode 0
}
catch {
    $baseResult.status = "install_failed"
    $baseResult.error = "Scheduled task registration failed"
    Write-ResultAndExit -Result $baseResult -ExitCode 2
}
