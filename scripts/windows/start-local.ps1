[CmdletBinding()]
param(
    [string]$RepositoryRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepositoryRoot) {
    $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$command = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($command) { $command.Source } else { Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe" }
if (-not (Test-Path -LiteralPath $docker)) {
    throw "Docker çalıştırılabilir dosyası bulunamadı."
}

function Test-DockerEngineReady {
    $previousErrorAction = $ErrorActionPreference
    try {
        # Windows PowerShell treats Docker's stderr as a terminating error under Stop.
        # A stopped engine is an expected probe result, so allow the startup branch.
        $ErrorActionPreference = "Continue"
        & $docker info 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

$dockerReady = Test-DockerEngineReady
if (-not $dockerReady) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    Start-Process -FilePath $desktop -WindowStyle Hidden
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 5
        $dockerReady = Test-DockerEngineReady
        if ($dockerReady) {
            break
        }
    }
}
if (-not $dockerReady) {
    throw "Docker motoru hazır değil."
}

Push-Location $RepositoryRoot
try {
    $composeReady = $false
    $startupDeadline = [DateTime]::UtcNow.AddMinutes(20)
    do {
        $previousErrorAction = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime --profile financials up -d
            $composeReady = ($LASTEXITCODE -eq 0)
        }
        finally {
            $ErrorActionPreference = $previousErrorAction
        }
        if ($composeReady) { break }
        Write-Warning "Borsapp is not ready yet; retrying while PostgreSQL or Docker starts."
        Start-Sleep -Seconds 15
    } while ([DateTime]::UtcNow -lt $startupDeadline)
    if (-not $composeReady) {
        throw "Borsapp services did not become ready within the startup window."
    }
}
finally {
    Pop-Location
}
