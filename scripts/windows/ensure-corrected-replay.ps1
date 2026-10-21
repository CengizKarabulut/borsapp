[CmdletBinding()]
param(
    [switch]$Resume,
    [string]$ResumeHelperPath = '',
    [string]$CStatePath = '',
    [string]$InstallationRoot = 'E:\Borsapp-Manual',
    [string]$ExpectedHelperSha256 = '225f12632d2606f631f35bbc839fafa35e34bf232fc6d391fc8d461b6a94bef7',
    [string]$ExpectedPreflightSha256 = '76b9514fffd36fe35391088f9a19d12ecdb3c5a966c0f595a53b71c241bd0442',
    [ValidateRange(5, 180)][int]$ReceiptWaitSeconds = 75
)

# Without -Resume this is a read-only probe.  It neither creates a task nor
# changes the reviewed replay package, E installation, power policy or orders.
$ErrorActionPreference = 'Stop'
$taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (-not $ResumeHelperPath) {
    $taskRelative = 'Documents\Codex\2026-09-10\https-github-com-cengizkarabulut-taramabot-https\work\borsapp\work\repo-integration-20261018\oct19-recovery\replay-resume-20261020\Resume-CorrectedReplay.ps1'
    $ResumeHelperPath = Join-Path $env:USERPROFILE $taskRelative
}
$ResumeHelperPath = [IO.Path]::GetFullPath($ResumeHelperPath)
$taskHelperFolder = Split-Path $ResumeHelperPath -Parent
$taskProofFolder = Split-Path $taskHelperFolder -Parent
$taskReplayPath = Join-Path $taskProofFolder 'newreplay-v4\run_corrected_replay.py'
$taskPreflightPath = Join-Path $taskHelperFolder 'replay_resume_preflight.py'
$InstallationRoot = [IO.Path]::GetFullPath($InstallationRoot).TrimEnd([char]'\')
if (-not $CStatePath) {
    $CStatePath = Join-Path $taskProofFolder 'replay-recovery\supervisor-state.json'
}
$CStatePath = [IO.Path]::GetFullPath($CStatePath)
if ($InstallationRoot -ine 'E:\Borsapp-Manual') { throw 'reviewed_resume_helper_is_bound_to_E_installation' }
if ([IO.Path]::GetPathRoot($CStatePath) -ine [IO.Path]::GetPathRoot($env:USERPROFILE)) {
    throw 'supervisor_state_must_remain_on_user_C_drive'
}
$taskSummaryPath = Join-Path $InstallationRoot 'results\exit-research-adjusted-v2\replay-v4\corrected-v4-analysis-summary.json'
$taskStopPath = Join-Path $InstallationRoot 'results\exit-research-adjusted-v2\replay-v4\stop.request'
$taskLock = $null
$taskExit = 0
$taskState = [ordered]@{
    schema = 1
    observed_at = [DateTime]::UtcNow.ToString('o')
    status = 'checking'
    explicit_resume = [bool]$Resume
    same_user_sid = $taskSid
    summary_read = $false
    resume_helper_invoked = $false
    task_created = $false
    global_power_policy_changed = $false
    orders_sent = 0
    messages_sent = 0
    downloads_started = 0
}

function Test-AtcCommandToken([string]$Command, [string]$Token) {
    $taskEscaped = [Regex]::Escape($Token)
    return $Command -match ('(?i)(?:^|\s)(?:"' + $taskEscaped + '"|' + $taskEscaped + ')(?=\s|$)')
}

function Get-AtcSameUserMatches([string[]]$Names, [string]$ScriptPath, [switch]$RequireRoot, [switch]$RequireChild) {
    $taskFilter = ($Names | ForEach-Object { "Name='$_'" }) -join ' OR '
    $taskMatches = @()
    foreach ($taskCandidate in @(Get-CimInstance Win32_Process -Filter $taskFilter)) {
        $taskCommand = [string]$taskCandidate.CommandLine
        if (-not $taskCommand -or -not (Test-AtcCommandToken $taskCommand $ScriptPath)) { continue }
        if ($RequireChild -and -not (Test-AtcCommandToken $taskCommand '-Child')) { continue }
        if ($RequireRoot) {
            $taskRootPattern = '(?i)(?:^|\s)"?--root"?\s+(?:"' + [Regex]::Escape($InstallationRoot) + '"|' + [Regex]::Escape($InstallationRoot) + ')(?=\s|$)'
            if ($taskCommand -notmatch $taskRootPattern) { continue }
        }
        $taskOwner = Invoke-CimMethod -InputObject $taskCandidate -MethodName GetOwnerSid
        if ($taskOwner.ReturnValue -ne 0 -or -not $taskOwner.Sid) { throw 'replay_process_owner_unverified' }
        if ($taskOwner.Sid -ne $taskSid) { throw 'matching_replay_belongs_to_another_user' }
        $taskMatches += [pscustomobject]@{
            pid = [uint32]$taskCandidate.ProcessId
            parent_pid = [uint32]$taskCandidate.ParentProcessId
            created_filetime = $taskCandidate.CreationDate.ToUniversalTime().ToFileTimeUtc()
            created_utc = $taskCandidate.CreationDate.ToUniversalTime().ToString('o')
        }
    }
    return $taskMatches
}

function Get-AtcRunRoots($Processes) {
    $taskIds = @($Processes | ForEach-Object { [uint32]$_.pid })
    return @($Processes | Where-Object { $taskIds -notcontains [uint32]$_.parent_pid })
}

function Write-AtcRecoveryState($State) {
    $taskDirectory = [IO.Path]::GetDirectoryName($CStatePath)
    [IO.Directory]::CreateDirectory($taskDirectory) | Out-Null
    $taskTemporary = $CStatePath + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    $taskJson = ($State | ConvertTo-Json -Depth 10 -Compress)
    try {
        [IO.File]::WriteAllText($taskTemporary, $taskJson + "`n", [Text.UTF8Encoding]::new($false))
        for ($taskAttempt = 0; $taskAttempt -lt 3; $taskAttempt++) {
            try {
                if ([IO.File]::Exists($CStatePath)) {
                    # Windows PowerShell 5.1 otherwise binds $null as an empty
                    # backup path; use the explicit null string for .NET.
                    [IO.File]::Replace($taskTemporary, $CStatePath, [System.Management.Automation.Language.NullString]::Value)
                } else {
                    [IO.File]::Move($taskTemporary, $CStatePath)
                }
                break
            } catch [IO.IOException] {
                if ($taskAttempt -eq 2) { throw }
                Start-Sleep -Milliseconds 100
            }
        }
    } finally {
        if ([IO.File]::Exists($taskTemporary)) { [IO.File]::Delete($taskTemporary) }
    }
    # This is a small observation log, not a cached claim that a process lives.
    $taskLog = Join-Path $taskDirectory 'supervisor.log'
    if ([IO.File]::Exists($taskLog) -and (Get-Item -LiteralPath $taskLog).Length -gt 131072) {
        [IO.File]::Copy($taskLog, $taskLog + '.previous', $true)
        [IO.File]::WriteAllText($taskLog, '', [Text.UTF8Encoding]::new($false))
    }
    $taskLine = [ordered]@{observed_at=$State.observed_at;status=$State.status;helper_invoked=$State.resume_helper_invoked}
    [IO.File]::AppendAllText($taskLog, (($taskLine | ConvertTo-Json -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
}

function Invoke-AtcRecoveryCheck {
    # The supervisor's exclusive C lock also serializes manual and task starts.
    if ($Resume) {
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($CStatePath)) | Out-Null
        try {
            $script:taskLock = [IO.File]::Open($CStatePath + '.lock', [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        } catch [IO.IOException] {
            $taskState.status = 'another_recovery_check_owns_lock'
            return
        }
    }
    if (-not [IO.Directory]::Exists($InstallationRoot)) {
        $taskState.status = 'waiting_for_E_installation'
        return
    }
    if ([IO.File]::Exists($taskStopPath)) {
        $taskState.status = 'stop_requested_no_restart'
        return
    }
    $taskActive = @(Get-AtcSameUserMatches @('python.exe', 'pythonw.exe') $taskReplayPath -RequireRoot)
    if ($taskActive.Count -gt 0) {
        $taskRoots = @(Get-AtcRunRoots $taskActive)
        if ($taskRoots.Count -ne 1) { throw 'multiple_replay_process_trees_require_review' }
        $taskState.status = 'observed_existing_same_user_replay'
        $taskState.processes = $taskActive
        $taskState.logical_run_count = 1
        return
    }
    $taskPending = @(Get-AtcSameUserMatches @('powershell.exe', 'pwsh.exe') $ResumeHelperPath -RequireChild)
    if ($taskPending.Count -gt 0) {
        $taskState.status = 'observed_existing_resume_helper_pending'
        $taskState.processes = $taskPending
        return
    }
    try {
        if (-not [IO.File]::Exists($taskSummaryPath)) {
            $taskState.status = 'waiting_for_E_research_summary'
            return
        }
        # Reading the large summary is reserved for the NO active-process path.
        $taskSummary = Get-Content -LiteralPath $taskSummaryPath -Raw | ConvertFrom-Json
        $taskState.summary_read = $true
    } catch [IO.IOException] {
        $taskState.status = 'waiting_for_E_summary_access'
        return
    }
    $taskState.previous_summary = [ordered]@{
        status = $taskSummary.status
        updated_at = $taskSummary.updated_at
        completed_job_count = $taskSummary.completed_job_count
        remaining_job_count = $taskSummary.remaining_job_count
    }
    if ($taskSummary.status -in @('completed', 'completed_with_exclusions')) {
        $taskState.status = 'research_completed_no_restart'
        return
    }
    if (-not $Resume) {
        $taskState.status = 'no_active_replay_explicit_resume_required'
        return
    }
    foreach ($taskPinnedFile in @(
        @{path=$ResumeHelperPath;hash=$ExpectedHelperSha256},
        @{path=$taskPreflightPath;hash=$ExpectedPreflightSha256}
    )) {
        if ($taskPinnedFile.hash -notmatch '^[a-fA-F0-9]{64}$' -or
            (Get-FileHash -LiteralPath $taskPinnedFile.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPinnedFile.hash.ToLowerInvariant()) {
            throw 'reviewed_resume_helper_or_preflight_changed'
        }
    }
    # Only the already reviewed helper can invoke the real runtime preflight,
    # acquire its existing research lock and use its hidden same-user WMI plan.
    $taskLaunchBegan = [DateTime]::UtcNow
    $taskState.resume_helper_invoked = $true
    $taskLaunchText = (& $ResumeHelperPath | Out-String)
    $taskLaunch = $taskLaunchText | ConvertFrom-Json
    if ($taskLaunch.state -ne 'created_pending_verification' -or [int64]$taskLaunch.helper_pid -le 0) {
        throw 'reviewed_helper_did_not_report_a_created_child'
    }
    $taskChildReceipt = [IO.Path]::GetFullPath([string]$taskLaunch.child_receipt)
    if ([IO.Path]::GetDirectoryName($taskChildReceipt) -ne [IO.Path]::GetFullPath($taskHelperFolder) -or
        [IO.Path]::GetFileName($taskChildReceipt) -notmatch '^\d{8}-\d{6}-[a-f0-9]{8}-replay-child\.json$') {
        throw 'bound_fresh_child_receipt_required'
    }
    $taskState.launch_receipt = [string]$taskLaunch.receipt
    $taskState.child_receipt = $taskChildReceipt
    $taskState.status = 'reviewed_helper_created_pending_verification'
    Write-AtcRecoveryState $taskState
    $taskDeadline = [DateTime]::UtcNow.AddSeconds($ReceiptWaitSeconds)
    while ([DateTime]::UtcNow -lt $taskDeadline) {
        if ([IO.File]::Exists($taskChildReceipt)) {
            $taskReceiptInfo = Get-Item -LiteralPath $taskChildReceipt
            if ($taskReceiptInfo.LastWriteTimeUtc -lt $taskLaunchBegan.AddSeconds(-2)) { throw 'child_receipt_is_not_fresh' }
            $taskReceipt = Get-Content -LiteralPath $taskChildReceipt -Raw | ConvertFrom-Json
            if ($taskReceipt.state -like 'failed*') { throw 'reviewed_resume_helper_failed_or_unverified' }
            if ($taskReceipt.state -eq 'fresh_summary_and_reused_reports_verified_native_job_observations_recorded_close_survival_not_tested') {
                if ($taskReceipt.same_user_sid -ne $taskSid) { throw 'child_receipt_owner_differs' }
                if ($taskReceipt.launch_nonce + '-replay-child.json' -ne [IO.Path]::GetFileName($taskChildReceipt) -or
                    [uint32]$taskReceipt.helper_pid -ne [uint32]$taskLaunch.helper_pid -or
                    [DateTimeOffset]::Parse([string]$taskReceipt.started_at).UtcDateTime -lt $taskLaunchBegan.AddSeconds(-2) -or
                    $taskReceipt.preflight.ok -ne $true -or
                    $taskReceipt.preflight.runtime_identity -ne '8ad6dfa91f5c6017d59e58a80cb6a0a1e51c7816f18100d7d8bbbb12f7e8b8c9' -or
                    $taskReceipt.preflight.implementation_sha256 -ne 'eab2b32a04f0fece9a62116c346b8b4f017e1d2b60be261f11229a70e351fadf' -or
                    $taskReceipt.preflight.manifest_sha256 -ne '0bc6b1e152b875091e863391fc2c82de883ebee01d972b95aa4aebc5d013e0fc') {
                    throw 'fresh_child_receipt_identity_differs'
                }
                $taskFresh = @(Get-AtcSameUserMatches @('python.exe', 'pythonw.exe') $taskReplayPath -RequireRoot)
                $taskVerified = @($taskFresh | Where-Object {
                    $taskObserved = $_
                    @($taskReceipt.processes | Where-Object {
                        [uint32]$_.pid -eq [uint32]$taskObserved.pid -and
                        [int64]$_.created_filetime -eq [int64]$taskObserved.created_filetime -and
                        [DateTimeOffset]::Parse([string]$taskObserved.created_utc).UtcDateTime -ge $taskLaunchBegan.AddSeconds(-2)
                    }).Count -gt 0
                })
                if ($taskVerified.Count -lt 1 -or @(Get-AtcRunRoots $taskFresh).Count -ne 1) {
                    throw 'fresh_replay_process_creation_not_verified'
                }
                $taskState.status = 'resumed_with_fresh_receipt_and_live_process_verified'
                $taskState.processes = $taskVerified
                $taskState.summary = $taskReceipt.summary
                $taskState.close_survival_tested = $false
                return
            }
        }
        Start-Sleep -Milliseconds 800
    }
    throw 'fresh_child_receipt_verification_timed_out_no_fallback'
}

try {
    Invoke-AtcRecoveryCheck
} catch {
    $taskState.status = 'blocked_or_unverified_no_fallback'
    $taskState.error_type = $_.Exception.GetType().Name
    $taskState.error_code = if ($_.Exception.Message -match '^[a-z_]+$') { $_.Exception.Message } else { 'inspect_reviewed_helper_receipt' }
    $taskExit = 1
} finally {
    try {
        if ($Resume -and $taskLock) { Write-AtcRecoveryState $taskState }
    } catch {
        $taskState.status_write_error = $_.Exception.GetType().Name
        $taskExit = 1
    }
    if ($taskLock) { $taskLock.Dispose() }
}
$taskState | ConvertTo-Json -Depth 10 -Compress
exit $taskExit
