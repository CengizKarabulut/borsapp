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

Push-Location $RepositoryRoot
try {
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime stop
}
finally {
    Pop-Location
}
