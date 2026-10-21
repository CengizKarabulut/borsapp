[CmdletBinding()]
param(
    [switch]$Dispatch,
    [string]$Now = '',
    [string]$CStatePath = '',
    [string]$GhPath = 'C:\Program Files\GitHub CLI\gh.exe',
    [string]$ExpectedGhSha256 = 'cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b'
)

# Project-specific dispatch backup. Default mode never calls GitHub.
# No Telegram token, E data, order channel or account session is accessed here.
$ErrorActionPreference = 'Stop'
$taskRepository = 'CengizKarabulut/borsapp'
$taskWorkflow = 'atc-scheduled-snapshots.yml'
$taskGhExpectedPath = 'C:\Program Files\GitHub CLI\gh.exe'
$taskState = [ordered]@{
    schema = 1
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    status = 'checking'
    explicit_dispatch = [bool]$Dispatch
    repository = $taskRepository
    workflow = $taskWorkflow
    ref = 'main'
    scope = 'due'
    delivery = 'publish'
    github_called = $false
    delivery_verified = $false
    task_created = $false
    E_writes = 0
    orders_sent = 0
}
$taskLock = $null
$taskExit = 0
if (-not $CStatePath) {
    $taskRelative = 'Documents\Codex\2026-09-10\https-github-com-cengizkarabulut-taramabot-https\work\borsapp\work\repo-integration-20261018\oct19-recovery\snapshot-dispatch-backup\dispatcher-state.json'
    $CStatePath = Join-Path $env:USERPROFILE $taskRelative
}
$CStatePath = [IO.Path]::GetFullPath($CStatePath)

function Write-AtcDispatchState {
    $taskDirectory = [IO.Path]::GetDirectoryName($CStatePath)
    $taskTemporary = $CStatePath + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($taskTemporary, (($taskState | ConvertTo-Json -Depth 5 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
        if ([IO.File]::Exists($CStatePath)) {
            [IO.File]::Replace($taskTemporary, $CStatePath, [System.Management.Automation.Language.NullString]::Value)
        } else {
            [IO.File]::Move($taskTemporary, $CStatePath)
        }
    } finally {
        if ([IO.File]::Exists($taskTemporary)) { [IO.File]::Delete($taskTemporary) }
    }
    $taskLogPath = Join-Path $taskDirectory 'dispatcher.log'
    if ([IO.File]::Exists($taskLogPath) -and (Get-Item -LiteralPath $taskLogPath).Length -gt 131072) {
        [IO.File]::Copy($taskLogPath, $taskLogPath + '.previous', $true)
        [IO.File]::WriteAllText($taskLogPath, '', [Text.UTF8Encoding]::new($false))
    }
    $taskLine = [ordered]@{observed_at_utc=$taskState.observed_at_utc;status=$taskState.status;github_called=$taskState.github_called}
    [IO.File]::AppendAllText($taskLogPath, (($taskLine | ConvertTo-Json -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
}

function Invoke-AtcSnapshotDispatch {
    if ($Dispatch -and $Now) { throw 'clock_fixture_is_dry_run_only' }
    if ([IO.Path]::GetPathRoot($CStatePath) -ine [IO.Path]::GetPathRoot($env:USERPROFILE)) {
        throw 'dispatch_state_must_remain_on_user_C_drive'
    }
    $taskZone = [TimeZoneInfo]::FindSystemTimeZoneById('Turkey Standard Time')
    if ($Now) {
        if ($Now -notmatch '(?:Z|[+-]\d{2}:\d{2})$') { throw 'aware_clock_fixture_required' }
        $taskLocal = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::Parse($Now), $taskZone)
    } else {
        $taskLocal = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $taskZone)
    }
    $taskState.istanbul_observation = $taskLocal.ToString('o')
    $taskIsWeekday = [int]$taskLocal.DayOfWeek -ge 1 -and [int]$taskLocal.DayOfWeek -le 5
    $taskMinute = $taskLocal.Hour * 60 + $taskLocal.Minute
    if (-not $taskIsWeekday -or $taskMinute -lt 607 -or $taskMinute -gt 1125) {
        $taskState.status = 'outside_weekday_dispatch_window'
        return
    }
    if ([IO.Path]::GetFullPath($GhPath) -ine $taskGhExpectedPath) { throw 'reviewed_exact_gh_path_required' }
    if ($ExpectedGhSha256 -notmatch '^[a-fA-F0-9]{64}$' -or
        (Get-FileHash -LiteralPath $GhPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedGhSha256.ToLowerInvariant()) {
        throw 'github_cli_changed_requires_review'
    }
    $taskState.github_cli_sha256 = $ExpectedGhSha256.ToLowerInvariant()
    if (-not $Dispatch) {
        $taskState.status = 'would_dispatch_latest_due_dry_run'
        return
    }
    $taskState.github_called = $true
    # Keep CLI output local and unreported: authentication errors are represented
    # by exit status, never by dumping credentials or arbitrary stderr to logs.
    $taskPreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $taskOutput = @(& $GhPath workflow run $taskWorkflow --repo $taskRepository --ref main -f scope=due -f delivery=publish 2>&1)
        $taskGhExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $taskPreviousPreference
    }
    $taskState.github_exit_code = $taskGhExit
    if ($taskGhExit -ne 0) { throw 'github_dispatch_failed_no_delivery_claim' }
    $taskState.status = 'dispatch_accepted_delivery_not_yet_verified'
}

try {
    if ($Dispatch) {
        if ([IO.Path]::GetPathRoot($CStatePath) -ine [IO.Path]::GetPathRoot($env:USERPROFILE)) { throw 'dispatch_state_must_remain_on_user_C_drive' }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($CStatePath)) | Out-Null
        try {
            $taskLock = [IO.File]::Open($CStatePath + '.lock', [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        } catch [IO.IOException] {
            $taskState.status = 'another_dispatch_check_owns_lock'
        }
        if ($taskLock) { Invoke-AtcSnapshotDispatch }
    } else {
        Invoke-AtcSnapshotDispatch
    }
} catch {
    $taskState.status = 'dispatch_blocked_or_failed'
    $taskState.error_type = $_.Exception.GetType().Name
    $taskState.error_code = if ($_.Exception.Message -match '^[a-z_]+$') { $_.Exception.Message } else { 'inspect_local_cli_or_task_configuration' }
    $taskExit = 1
} finally {
    try {
        if ($Dispatch -and $taskLock) { Write-AtcDispatchState }
    } catch {
        $taskState.status_write_error = $_.Exception.GetType().Name
        $taskExit = 1
    }
    if ($taskLock) { $taskLock.Dispose() }
}
$taskState | ConvertTo-Json -Depth 5 -Compress
exit $taskExit
