$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
  Write-Host "[shiftops]" $Message
}

function Command-Exists([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Info "Checking Node.js toolchain..."

if (-not (Command-Exists "node")) {
  throw "Node.js is not installed (node not found). Install Node.js 20+ and re-run."
}
if (-not (Command-Exists "npm")) {
  throw "npm is not available (npm not found). Reinstall Node.js."
}

$nodeV = (node -v).Trim()
$npmV = (npm -v).Trim()
Write-Info "node $nodeV"
Write-Info "npm  $npmV"

Write-Info "Ensuring pnpm is installed..."
if (-not (Command-Exists "pnpm")) {
  Write-Info "pnpm not found — installing globally via npm..."
  npm i -g pnpm
}

# Ensure npm global bin is on PATH (User scope).
$prefix = (npm config get prefix).Trim()
$npmBin = Join-Path $prefix ""
$roamingBin = Join-Path $env:APPDATA "npm"
$candidate = if (Test-Path $roamingBin) { $roamingBin } else { $npmBin }

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }

$parts = $userPath.Split(";", [System.StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() }
if ($parts -notcontains $candidate) {
  Write-Info "Adding to USER PATH: $candidate"
  $newPath = ($parts + $candidate) -join ";"
  [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
  Write-Info "PATH updated. Restart your terminal for changes to take effect."
} else {
  Write-Info "PATH already contains: $candidate"
}

if (-not (Command-Exists "pnpm")) {
  throw "pnpm still not found. Restart terminal and run: pnpm -v"
}

$pnpmV = (pnpm -v).Trim()
Write-Info "pnpm $pnpmV"
Write-Info "Done. Next: cd apps/web; pnpm install; pnpm run lint; pnpm run typecheck"

