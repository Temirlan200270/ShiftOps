# ShiftOps: первичный (или повторный) деплой API на Fly.io + сопутствующие шаги.
# Запуск (из корня репозитория, после `flyctl auth login`):
#   .\scripts\deploy_fly_production.ps1
#
# Требуется: apps/api/.env.production (не в git) со всеми прод-секретами.

[CmdletBinding()]
param(
    [string] $AppName = "shiftops-api",
    [string] $Org = "personal",
    [string] $VercelFrontendUrl = "https://shiftops-web.vercel.app",
    [string] $ApiPublicUrl = "https://shiftops-api.fly.dev",
    [switch] $SkipSeed,
    [switch] $SkipSmoke,
    [switch] $SkipVercelEnv,
    [switch] $WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-Flyctl {
    if (Get-Command flyctl -ErrorAction SilentlyContinue) { return (Get-Command flyctl).Source }
    $p = Join-Path $env:USERPROFILE ".fly\bin\flyctl.exe"
    if (Test-Path -LiteralPath $p) { return $p }
    throw "flyctl not found. Install: iwr https://fly.io/install.ps1 -useb | iex"
}

function Import-DotEnv {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing file: $Path" }
    Get-Content -LiteralPath $Path -Encoding utf8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $ix = $line.IndexOf("=")
        if ($ix -lt 1) { return }
        $k = $line.Substring(0, $ix).Trim()
        $v = $line.Substring($ix + 1).Trim()
        if ($v.Length -ge 2 -and $v.StartsWith('"') -and $v.EndsWith('"')) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        elseif ($v.Length -ge 2 -and $v.StartsWith("'") -and $v.EndsWith("'")) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

function Test-FlyAuth {
    param([string] $Fly)
    & $Fly auth whoami 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Fly.io: not logged in. Run: $Fly auth login   then: $Fly auth whoami"
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$EnvProd = Join-Path $RepoRoot "apps\api\.env.production"
$Fly = Get-Flyctl
Write-Host "Using flyctl: $Fly"

if (-not (Test-Path -LiteralPath $EnvProd)) {
    throw "Create $EnvProd with production secrets (see DEPLOY_NEXT_STEPS.md)."
}

if ($WhatIf) {
    Write-Host "WhatIf: would deploy $AppName to $ApiPublicUrl (env file: $EnvProd)"
    exit 0
}

Test-FlyAuth -Fly $Fly

# --- A1: приложение (идемпотентно) ---
$createOut = & $Fly apps create $AppName --org $Org 2>&1
$createText = if ($null -eq $createOut) { "" } else { $createOut | Out-String }
if ($LASTEXITCODE -ne 0) {
    if ($createText -match "Already exists|has already been taken|duplicate|taken name") {
        Write-Host "App '$AppName' already exists; continuing."
    } else {
        throw "fly apps create failed: $createText"
    }
} else {
    Write-Host "Created app $AppName"
}

# --- A2: секреты ---
Write-Host "Importing secrets from apps/api/.env.production …"
Get-Content -LiteralPath $EnvProd -Raw | & $Fly secrets import --app $AppName
if ($LASTEXITCODE -ne 0) { throw "fly secrets import failed" }

# --- A3: деплой ---
$apiDir = Join-Path $RepoRoot "apps\api"
Push-Location $apiDir
try {
    & $Fly deploy --remote-only --config fly.toml --dockerfile Dockerfile
    if ($LASTEXITCODE -ne 0) { throw "fly deploy failed" }
} finally {
    Pop-Location
}

# healthz
Write-Host "GET $ApiPublicUrl/healthz"
Start-Sleep -Seconds 3
$health = try { Invoke-RestMethod -Uri "$ApiPublicUrl/healthz" -TimeoutSec 30 } catch { $null }
if (-not $health) { throw "Health check failed. Wait for rollout and retry: $ApiPublicUrl/healthz" }
Write-Host "Health: $([pscustomobject]$health | ConvertTo-Json -Compress)"

# --- A4: миграции ---
& $Fly ssh console --app $AppName -C "alembic upgrade head"
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed" }

# --- A5: seed (опционально) ---
if (-not $SkipSeed) {
    & $Fly ssh console --app $AppName -C "python -m scripts.seed"
    if ($LASTEXITCODE -ne 0) { throw "python -m scripts.seed failed" }
}

# --- A6: CORS (явно под Vercel + локалку) ---
$cors = "$VercelFrontendUrl,http://localhost:3000"
& $Fly secrets set "API_CORS_ORIGINS=$cors" --app $AppName
if ($LASTEXITCODE -ne 0) { throw "API_CORS_ORIGINS set failed" }
Push-Location $apiDir
try {
    & $Fly deploy --remote-only --config fly.toml --dockerfile Dockerfile
    if ($LASTEXITCODE -ne 0) { throw "fly deploy (after CORS) failed" }
} finally {
    Pop-Location
}

# --- A7: Vercel (нужен vercel whoami) ---
if (-not $SkipVercelEnv) {
    if (Get-Command vercel -ErrorAction SilentlyContinue) {
        $webDir = Join-Path $RepoRoot "apps\web"
        $vercelProject = Join-Path $webDir ".vercel\project.json"
        if (-not (Test-Path -LiteralPath $vercelProject)) {
            Write-Warning "No apps/web/.vercel/project.json — link with: cd apps/web; vercel link. Skipping Vercel env."
        }
        elseif (Test-Path $webDir) {
            Push-Location $webDir
            try {
                vercel env rm NEXT_PUBLIC_API_URL production --yes 2>&1 | Out-Null
                $apiNoSlash = $ApiPublicUrl.TrimEnd("/")
                $apiNoSlash | vercel env add NEXT_PUBLIC_API_URL production
                if ($LASTEXITCODE -ne 0) { throw "vercel env add failed" }
                vercel deploy --prod
                if ($LASTEXITCODE -ne 0) { throw "vercel deploy --prod failed" }
            } finally {
                Pop-Location
            }
        }
    } else {
        Write-Warning "Vercel CLI not found. Set NEXT_PUBLIC_API_URL in Vercel Dashboard to: $ApiPublicUrl"
    }
}

# --- A8: Telegram webhook (из .env.production) ---
Import-DotEnv -Path $EnvProd
$tg = $env:TG_BOT_TOKEN
$wh = $env:TG_WEBHOOK_SECRET
if ($tg -and $wh) {
    $hook = "$($ApiPublicUrl.TrimEnd("/"))/api/v1/telegram/webhook"
    $setUrl = "https://api.telegram.org/bot${tg}/setWebhook"
    try {
        & curl.exe -fsS -X POST $setUrl `
            --data-urlencode "url=$hook" `
            -d "secret_token=$wh" `
            -d "drop_pending_updates=false" `
            -d "allowed_updates=[`"message`",`"callback_query`",`"my_chat_member`"]"
        if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
        Write-Host "Telegram setWebhook OK → $hook"
    } catch {
        Write-Warning "setWebhook failed (check token/URL): $_"
    }
} else {
    Write-Warning "TG_BOT_TOKEN or TG_WEBHOOK_SECRET missing in .env.production; skip setWebhook"
}

# --- A10: smoke (нужен DATABASE_URL/остальные ключи как у API — грузим .env.production) ---
if (-not $SkipSmoke) {
    Import-DotEnv -Path $EnvProd
    $env:SMOKE_API_URL = $ApiPublicUrl
    Push-Location $apiDir
    try {
        python -m scripts.smoke_pilot
        if ($LASTEXITCODE -ne 0) { throw "smoke_pilot failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Done. Remaining: GitHub Actions secrets (see DEPLOY_NEXT_STEPS.md, A9) — names match .github/workflows/deploy.yml:"
Write-Host "  FLY_API_TOKEN, VERCEL_TOKEN, VERCEL_ORG_ID, VERCEL_PROJECT_ID, TG_BOT_TOKEN_PROD, TG_WEBHOOK_SECRET_PROD, API_PUBLIC_URL_PROD, SENTRY_* (optional)"
