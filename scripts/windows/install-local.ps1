[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-DockerExecutable {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidate = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }
    throw "Docker bulunamadı. Önce Docker Desktop kurulumunu tamamlayın."
}

function Wait-DockerEngine {
    param([string]$DockerExecutable)

    & $DockerExecutable info *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $desktop)) {
        throw "Docker Desktop uygulaması bulunamadı."
    }
    Start-Process -FilePath $desktop -WindowStyle Hidden
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 5
        & $DockerExecutable info *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
    }
    throw "Docker motoru 5 dakika içinde hazır olmadı. Docker Desktop penceresini kontrol edin."
}

function New-LocalEnvironment {
    param([string]$TargetPath)

    $templatePath = Join-Path $RepositoryRoot ".env.local.example"
    $alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    $password = -join (1..36 | ForEach-Object {
        $alphabet[[Security.Cryptography.RandomNumberGenerator]::GetInt32($alphabet.Length)]
    })

    do {
        $secureToken = Read-Host "Telegram bot tokenını girin" -AsSecureString
        $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        try {
            $telegramToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
        }
    } until ($telegramToken -match "^\d+:[A-Za-z0-9_-]{30,}$")

    do {
        $telegramChatId = Read-Host "Telegram grup kimliğini girin (genellikle -100 ile başlar)"
    } until ($telegramChatId -match "^-?\d+$")

    $content = [IO.File]::ReadAllText($templatePath)
    $content = $content.Replace("POSTGRES_PASSWORD=CHANGE_ME", "POSTGRES_PASSWORD=$password")
    $content = $content.Replace(
        "DATABASE_URL=postgresql://borsapp:CHANGE_ME@localhost:5432/borsapp",
        "DATABASE_URL=postgresql://borsapp:$password@localhost:5432/borsapp"
    )
    $content = $content.Replace(
        "COMPOSE_DATABASE_URL=postgresql://borsapp:CHANGE_ME@postgres:5432/borsapp",
        "COMPOSE_DATABASE_URL=postgresql://borsapp:$password@postgres:5432/borsapp"
    )
    $content = $content.Replace("TELEGRAM_BOT_TOKEN=CHANGE_ME", "TELEGRAM_BOT_TOKEN=$telegramToken")
    $content = $content.Replace("TELEGRAM_CHAT_ID=CHANGE_ME", "TELEGRAM_CHAT_ID=$telegramChatId")
    [IO.File]::WriteAllText($TargetPath, $content, [Text.UTF8Encoding]::new($false))

    & icacls.exe $TargetPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning ".env dosya izinleri daraltılamadı; dosyayı başka kullanıcılarla paylaşmayın."
    }
}

$environmentPath = Join-Path $RepositoryRoot ".env"
if (-not (Test-Path -LiteralPath $environmentPath)) {
    New-LocalEnvironment -TargetPath $environmentPath
}
elseif ((Get-Content -LiteralPath $environmentPath -Raw) -match "CHANGE_ME") {
    throw ".env içinde CHANGE_ME kaldı. Dosyayı düzeltin veya silip kurulumu yeniden çalıştırın."
}

$docker = Resolve-DockerExecutable
Wait-DockerEngine -DockerExecutable $docker

Push-Location $RepositoryRoot
try {
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose yapılandırması geçersiz."
    }
    & $docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "Borsapp servisleri başlatılamadı."
    }
}
finally {
    Pop-Location
}

$startScript = Join-Path $RepositoryRoot "scripts\windows\start-local.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File ""$startScript"""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Borsapp Local" -Action $action -Trigger $trigger -Settings $settings -Description "Windows oturumu açılınca Borsapp Docker servislerini başlatır." -Force | Out-Null

Write-Host "Borsapp yerel kurulumu tamamlandı."
Write-Host "Durum: powershell -File scripts\windows\status-local.ps1"
