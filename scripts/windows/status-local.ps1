[CmdletBinding()]
param(
    [string]$RepositoryRoot = "",
    [int]$LogLines = 30
)

$ErrorActionPreference = "Stop"
if (-not $RepositoryRoot) {
    $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$command = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($command) { $command.Source } else { Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe" }

Push-Location $RepositoryRoot
try {
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime --profile financials ps
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime --profile financials logs --tail $LogLines listener publisher command-worker scanner news-worker
}
finally {
    Pop-Location
}
