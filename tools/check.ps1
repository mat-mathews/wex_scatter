# Local CI mirror — runs the same checks as .github/workflows/ci.yml.
# Usage:
#   pwsh tools/check.ps1          # full: lint + format + mypy + pytest + smoke
#   pwsh tools/check.ps1 -Quick   # fast: lint + format only

param([switch]$Quick)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Run 'pwsh tools/setup.ps1' first." -ForegroundColor Red
    exit 1
}

Push-Location $RepoRoot

$Failed = 0
$Results = @()

function Run-Step {
    param([string]$Name, [scriptblock]$Command)
    Write-Host "--- $Name ---" -ForegroundColor DarkGray
    try {
        & $Command 2>&1 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        $script:Results += @{ Status = "pass"; Name = $Name }
    } catch {
        $script:Results += @{ Status = "FAIL"; Name = $Name }
        $script:Failed = 1
    }
    Write-Host ""
}

if ($Quick) {
    Write-Host "`nQuick check (lint + format)`n" -ForegroundColor White
} else {
    Write-Host "`nFull check (lint + format + mypy + pytest + smoke)`n" -ForegroundColor White
}

# --- Always run ---
Run-Step "ruff check"  { uv run ruff check scatter/ }
Run-Step "ruff format" { uv run ruff format --check scatter/ }

# --- Full only ---
if (-not $Quick) {
    Run-Step "mypy"  { uv run mypy scatter --ignore-missing-imports }
    Run-Step "pytest" { uv run pytest --cov=scatter --cov-report=term-missing -q }

    $tempDir = if ($env:TEMP) { $env:TEMP } else { "/tmp" }

    $smokeTarget = Join-Path $tempDir "scatter-smoke-target.json"
    $smokeGraph = Join-Path $tempDir "scatter-smoke-graph.json"

    Run-Step "smoke: target-project" {
        uv run scatter `
            --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj `
            --search-scope . `
            --output-format json `
            --output-file $smokeTarget
    }

    Run-Step "smoke: graph" {
        uv run scatter `
            --graph `
            --search-scope . `
            --output-format json `
            --output-file $smokeGraph
    }

    # NOTE: The closing "@ of a here-string MUST start at column 0 (no indentation).
    Run-Step "smoke: validate output" {
        python -c @"
import json
d = json.load(open(r'$smokeTarget'))
results = d.get('all_results', d) if isinstance(d, dict) else d
assert isinstance(results, list) and len(results) > 0, 'No consumer results'
assert any('ConsumerProjectName' in r or 'consumer' in str(r).lower() for r in results), 'No consumer data'
g = json.load(open(r'$smokeGraph'))
assert isinstance(g, dict), 'Graph output should be a dict'
assert g.get('node_count', 0) > 0 or g.get('projects', 0) > 0 or len(g) > 0, 'Empty graph'
print(f'  target: {len(results)} consumers, graph: {g.get("node_count", len(g))} nodes')
"@
    }

    # --- AI smoke test ---
    if ($env:GOOGLE_API_KEY) {
        $smokeAi = Join-Path $tempDir "scatter-smoke-ai.json"

        Run-Step "smoke: ai summarization" {
            uv run scatter `
                --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj `
                --search-scope . `
                --summarize-consumers `
                --max-ai-calls 3 `
                --output-format json `
                --output-file $smokeAi
        }

        Run-Step "smoke: ai validate" {
            python -c @"
import json
d = json.load(open(r'$smokeAi'))
results = d.get('all_results', d) if isinstance(d, dict) else d
assert isinstance(results, list) and len(results) > 0, 'No consumer results'
print(f'  ai smoke: {len(results)} consumers')
"@
        }
    } else {
        Write-Host "--- smoke: ai (skipped - GOOGLE_API_KEY not set) ---" -ForegroundColor DarkGray
        $Results += @{ Status = "skip"; Name = "smoke: ai (no GOOGLE_API_KEY)" }
    }
}

# --- Summary ---
Write-Host "Results" -ForegroundColor White
foreach ($r in $Results) {
    $color = switch ($r.Status) {
        "pass" { "Green" }
        "FAIL" { "Red" }
        default { "DarkGray" }
    }
    Write-Host "  $($r.Status)  $($r.Name)" -ForegroundColor $color
}
Write-Host ""

Pop-Location

if ($Failed -ne 0) {
    Write-Host "Some checks failed." -ForegroundColor Red
    exit 1
} else {
    Write-Host "All checks passed." -ForegroundColor Green
}
