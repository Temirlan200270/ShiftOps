# ShiftOps: first-time or repeat API deploy to Fly.io + follow-up steps.
# From repo root, after: flyctl auth login
#   .\scripts\deploy_fly_production.ps1
# If the script "does nothing" or Notepad opens, run explicitly:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_fly_production.ps1
#
# Requires: apps/api/.env.production (not in git) with production secrets.
# Do not pass -DryRun if you expect a real deploy (it only prints a plan and exits).

[CmdletBinding()]
param(
    [string] $AppName = "shiftops-api",
    [string] $Org = "personal",
    [string] $VercelFrontendUrl = "https://shiftops-web.vercel.app",
    [string] $ApiPublicUrl = "https://shiftops-api.fly.dev",
    [switch] $SkipSeed,
    [switch] $SkipSmoke,
    [switch] $SkipVercelEnv,
    [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-Flyctl {
    if (Get-Command flyctl -ErrorAction SilentlyContinue) { return (Get-Command flyctl).Source }
    $p = Join-Path $env:USERPROFILE ".fly\bin\flyctl.exe"
    if (Test-Path -LiteralPath $p) { return $p }
    throw "flyctl not found. Install: iwr https://fly.io/install.ps1 -useb | iex"
}

function Read-TextFileUtf8NoBom {
    param([string] $Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $offset = 0
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $offset = 3 }
    [System.Text.Encoding]::UTF8.GetString($bytes, $offset, $bytes.Length - $offset)
}

function Import-DotEnv {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing file: $Path" }
    Get-Content -LiteralPath $Path -Encoding utf8 | ForEach-Object {
        $line = $_.Trim().TrimStart([char]0xFEFF)
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $ix = $line.IndexOf("=")
        if ($ix -lt 1) { return }
        $k = $line.Substring(0, $ix).Trim().TrimStart([char]0xFEFF)
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
    $null = & $Fly @("auth", "whoami")
    if ($LASTEXITCODE -ne 0) {
        throw "Fly.io: not logged in. Run: $Fly auth login   then: $Fly auth whoami"
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$EnvProd = Join-Path $RepoRoot "apps\api\.env.production"
$Fly = Get-Flyctl
Write-Host ""
Write-Host "=== ShiftOps Fly deploy  $(Get-Date -Format o) ===" -ForegroundColor Cyan
Write-Host "Using flyctl: $Fly"
Write-Host "Repo:       $RepoRoot"
Write-Host "Env file:   $EnvProd"
Write-Host ""

if (-not (Test-Path -LiteralPath $EnvProd)) {
    throw "Create $EnvProd with production secrets (see DEPLOY_NEXT_STEPS.md)."
}

if ($DryRun) {
    Write-Host "DryRun: no Fly calls. Would deploy, secrets, CORS, webhook, smoke." -ForegroundColor Yellow
    exit 0
}

Test-FlyAuth -Fly $Fly
Write-Host "[auth] flyctl whoami: OK" -ForegroundColor Green

# --- A1: create app (idempotent) ---
# Native stderr from flyctl can trigger a terminating error with $ErrorActionPreference Stop; suppress for this call.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$createOut = & $Fly apps create $AppName --org $Org 2>&1
$ErrorActionPreference = $prevEap
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

# --- A2: secrets (strip UTF-8 BOM so the first key is not "\ufeffAPP_ENV") ---
Write-Host "[A2] fly secrets import (takes a moment) ..." -ForegroundColor Cyan
$envFileBody = Read-TextFileUtf8NoBom -Path $EnvProd
$envFileBody | & $Fly secrets import --app $AppName
if ($LASTEXITCODE -ne 0) { throw "fly secrets import failed" }
Write-Host "[A2] secrets import: OK" -ForegroundColor Green

# --- A3: deploy ---
$apiDir = Join-Path $RepoRoot "apps\api"
Write-Host "[A3] fly deploy --remote-only (often 3-10+ min, remote build on Fly) ..." -ForegroundColor Cyan
Push-Location $apiDir
try {
    & $Fly deploy --remote-only --config fly.toml --dockerfile Dockerfile
    if ($LASTEXITCODE -ne 0) { throw "fly deploy failed" }
} finally {
    Pop-Location
}
Write-Host "[A3] deploy: OK" -ForegroundColor Green

# healthz
Write-Host "GET $ApiPublicUrl/healthz"
Start-Sleep -Seconds 3
$health = try { Invoke-RestMethod -Uri "$ApiPublicUrl/healthz" -TimeoutSec 30 } catch { $null }
if (-not $health) { throw "Health check failed. Wait for rollout and retry: $ApiPublicUrl/healthz" }
Write-Host "Health: $([pscustomobject]$health | ConvertTo-Json -Compress)"

# --- A4: migrations ---
& $Fly ssh console --app $AppName -C "alembic upgrade head"
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed" }

# --- A5: seed (optional) ---
if (-not $SkipSeed) {
    & $Fly ssh console --app $AppName -C "python -m scripts.seed"
    if ($LASTEXITCODE -ne 0) { throw "python -m scripts.seed failed" }
}

# --- A6: CORS ---
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

# --- A7: Vercel ---
if (-not $SkipVercelEnv) {
    if (Get-Command vercel -ErrorAction SilentlyContinue) {
        $webDir = Join-Path $RepoRoot "apps\web"
        $vercelProject = Join-Path $webDir ".vercel\project.json"
        if (-not (Test-Path -LiteralPath $vercelProject)) {
            Write-Warning "No apps/web/.vercel/project.json. Run: cd apps/web; vercel link. Skipping Vercel env."
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

# --- A8: Telegram webhook ---
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
        Write-Host "Telegram setWebhook OK: $hook"
    } catch {
        Write-Warning "setWebhook failed (check token/URL): $_"
    }
} else {
    Write-Warning "TG_BOT_TOKEN or TG_WEBHOOK_SECRET missing in .env.production; skip setWebhook"
}

# --- A10: smoke ---
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
Write-Host "Done. Add GitHub Actions secrets (DEPLOY_NEXT_STEPS.md, A9). Names in .github/workflows/deploy.yml:"
Write-Host "  FLY_API_TOKEN, VERCEL_TOKEN, VERCEL_ORG_ID, VERCEL_PROJECT_ID, TG_BOT_TOKEN_PROD, TG_WEBHOOK_SECRET_PROD, API_PUBLIC_URL_PROD, (optional) Sentry secrets"
