# Demonstrate scatter's impact analysis on the sample .NET projects.
# Works without an API key (shows blast radius tree).
# With a GOOGLE_API_KEY, shows full AI-enriched report.

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Run 'pwsh tools/setup.ps1' first." -ForegroundColor Red
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "Scatter Impact Analysis Demo"
Write-Host "============================"
Write-Host ""
Write-Host "SOW: Modify PortalDataService in GalaxyWorks.Data to add tenant isolation"
Write-Host ""

uv run scatter `
    --sow "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation parameter" `
    --search-scope $RepoRoot `
    --output-format markdown
