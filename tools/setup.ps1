# One-time developer environment bootstrap.
# Run from anywhere: pwsh tools/setup.ps1
# Safe to re-run — all steps are idempotent.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

function Pass($msg) { Write-Host "  ok  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  FAIL  $msg" -ForegroundColor Red }

Write-Host "`nscatter dev setup`n"

# --- 1. Python version ---
Write-Host "Python" -ForegroundColor White

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Fail "python not found on PATH"
    exit 1
}
$pyCmd = $python.Source

$pyVersion = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pyMajor = & $pyCmd -c "import sys; print(sys.version_info.major)"
$pyMinor = & $pyCmd -c "import sys; print(sys.version_info.minor)"

if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 10)) {
    Fail "Python >= 3.10 required (found $pyVersion)"
    Write-Host "       Install 3.10+ and try again."
    exit 1
}
Pass "Python $pyVersion"

# --- 2. uv ---
Write-Host "`nuv" -ForegroundColor White

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Warn "uv not found"
    Write-Host "       Install it with:"
    Write-Host ""
    Write-Host "         powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
    Write-Host ""
    Write-Host "       Then re-run this script."
    exit 1
}
$uvVersion = (uv --version 2>&1) | Select-Object -First 1
Pass "uv $uvVersion"

# --- 3. Dependencies ---
Write-Host "`nDependencies" -ForegroundColor White

Push-Location $RepoRoot
try {
    uv sync --quiet
    Pass "uv sync (all deps installed)"
} finally {
    Pop-Location
}

# --- 4. Git config ---
Write-Host "`nGit" -ForegroundColor White

if (Test-Path "$RepoRoot/.git-blame-ignore-revs") {
    git -C $RepoRoot config blame.ignoreRevsFile .git-blame-ignore-revs
    Pass "blame.ignoreRevsFile configured"
} else {
    Warn ".git-blame-ignore-revs not found - skipping"
}

# --- 5. Claude skills ---
Write-Host "`nClaude skills" -ForegroundColor White

$skillsSetup = Join-Path $ScriptDir "setup-claude-skills.ps1"
if (Test-Path $skillsSetup) {
    & $skillsSetup
} else {
    Warn "setup-claude-skills.ps1 not found - skipping"
}

# --- Summary ---
Write-Host "`nReady!`n" -ForegroundColor White
Write-Host "  Run tests:          uv run pytest"
Write-Host "  Run full check:     pwsh tools/check.ps1"
Write-Host "  Run quick check:    pwsh tools/check.ps1 -Quick"
Write-Host ""
