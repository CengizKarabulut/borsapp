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

& $docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    Start-Process -FilePath $desktop -WindowStyle Hidden
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 5
        & $docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            break
        }
    }
}
if ($LASTEXITCODE -ne 0) {
    throw "Docker motoru hazır değil."
}

Push-Location $RepositoryRoot
try {
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime --profile financials up -d
    if ($LASTEXITCODE -ne 0) {
        throw "Borsapp servisleri başlatılamadı."
    }
}
finally {
    Pop-Location
}
