[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$LogLines = 30
)

$ErrorActionPreference = "Stop"
$command = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($command) { $command.Source } else { Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe" }

Push-Location $RepositoryRoot
try {
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime ps
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime logs --tail $LogLines listener publisher command-worker scanner news-worker
}
finally {
    Pop-Location
}
