#!/bin/bash
# Local CI mirror — runs the same checks as .github/workflows/ci.yml.
# Usage:
#   bash tools/check.sh          # full: lint + format + mypy + pytest + smoke
#   bash tools/check.sh --quick  # fast: lint + format only
# Windows: run from Git Bash (included with Git for Windows).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

QUICK=false
if [ "$1" = "--quick" ]; then
    QUICK=true
fi

FAILED=0
RESULTS=()

run_step() {
    local name="$1"
    shift
    echo -e "${DIM}--- $name ---${RESET}"
    if "$@" 2>&1; then
        RESULTS+=("${GREEN}pass${RESET}  $name")
    else
        RESULTS+=("${RED}FAIL${RESET}  $name")
        FAILED=1
    fi
    echo ""
}

if $QUICK; then
    echo -e "\n${BOLD}Quick check${RESET} (lint + format)\n"
else
    echo -e "\n${BOLD}Full check${RESET} (lint + format + mypy + pytest + smoke)\n"
fi

# --- Always run ---
run_step "ruff check"  uv run ruff check scatter/
run_step "ruff format" uv run ruff format --check scatter/

# --- Full only ---
if ! $QUICK; then
    run_step "mypy"  uv run mypy scatter --ignore-missing-imports
    run_step "pytest" uv run pytest --cov=scatter --cov-report=term-missing -q

    # --- Smoke tests (mirrors .github/workflows/ci.yml smoke job) ---
    run_step "smoke: target-project" uv run scatter \
        --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
        --search-scope . \
        --output-format json \
        --output-file /tmp/scatter-smoke-target.json

    run_step "smoke: graph" uv run scatter \
        --graph \
        --search-scope . \
        --output-format json \
        --output-file /tmp/scatter-smoke-graph.json

    run_step "smoke: validate output" python -c "
import json
d = json.load(open('/tmp/scatter-smoke-target.json'))
results = d.get('all_results', d) if isinstance(d, dict) else d
assert isinstance(results, list) and len(results) > 0, 'No consumer results'
assert any('ConsumerProjectName' in r or 'consumer' in str(r).lower() for r in results), 'No consumer data in results'
g = json.load(open('/tmp/scatter-smoke-graph.json'))
assert isinstance(g, dict), 'Graph output should be a dict'
assert g.get('node_count', 0) > 0 or g.get('projects', 0) > 0 or len(g) > 0, 'Empty graph'
print(f'  target: {len(results)} consumers, graph: {g.get(\"node_count\", len(g))} nodes')
"

    run_step "lint: validate workflow YAML" python -c "
import yaml; yaml.safe_load(open('tools/github-action/scatter-pr-risk.yml'))
"

    # --- PR risk smoke (mirrors CI: creates temp branch, runs --pr-risk) ---
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    SMOKE_BRANCH="smoke/local-check-$$"

    git checkout -b "$SMOKE_BRANCH" --quiet 2>/dev/null
    mkdir -p SmokeProject
    echo '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>' > SmokeProject/SmokeProject.csproj
    echo 'namespace SmokeProject; public class SmokeWidget { }' > SmokeProject/SmokeWidget.cs
    git add SmokeProject/ && git commit -m "smoke: add SmokeWidget" --quiet 2>/dev/null

    run_step "smoke: pr-risk markdown" uv run scatter \
        --pr-risk \
        --branch-name "$SMOKE_BRANCH" \
        --base-branch "$CURRENT_BRANCH" \
        --repo-path . --search-scope . \
        --output-format markdown \
        --output-file /tmp/scatter-smoke-pr-risk.md

    run_step "smoke: pr-risk validate" python -c "
content = open('/tmp/scatter-smoke-pr-risk.md').read()
assert '## Scatter Risk:' in content, 'Missing risk header'
assert 'GREEN' in content or 'YELLOW' in content or 'RED' in content, 'Missing risk level'
print(f'  pr-risk: {len(content)} chars')
"

    run_step "smoke: pr-risk collapsible" uv run scatter \
        --pr-risk --collapsible \
        --branch-name "$SMOKE_BRANCH" \
        --base-branch "$CURRENT_BRANCH" \
        --repo-path . --search-scope . \
        --output-format markdown \
        --output-file /tmp/scatter-smoke-pr-risk-collapsible.md

    run_step "smoke: branch backward-compat" uv run scatter \
        --branch-name "$SMOKE_BRANCH" \
        --base-branch "$CURRENT_BRANCH" \
        --search-scope . \
        --output-format json \
        --output-file /tmp/scatter-smoke-branch-compat.json

    run_step "smoke: branch-compat validate" python -c "
import json
d = json.load(open('/tmp/scatter-smoke-branch-compat.json'))
assert 'all_results' in d, 'Missing all_results key — consumer table format expected'
print('  branch-compat: all_results key present')
"

    # Clean up smoke branch
    git checkout "$CURRENT_BRANCH" --quiet 2>/dev/null
    git branch -D "$SMOKE_BRANCH" --quiet 2>/dev/null
    rm -rf SmokeProject

    # --- AI smoke test (requires GOOGLE_API_KEY, skipped in CI) ---
    if [ -n "$GOOGLE_API_KEY" ]; then
        run_step "smoke: ai summarization" uv run scatter \
            --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
            --search-scope . \
            --summarize-consumers \
            --max-ai-calls 3 \
            --output-format json \
            --output-file /tmp/scatter-smoke-ai.json

        run_step "smoke: ai validate" python -c "
import json
d = json.load(open('/tmp/scatter-smoke-ai.json'))
results = d.get('all_results', d) if isinstance(d, dict) else d
assert isinstance(results, list) and len(results) > 0, 'No consumer results'
has_summary = any(
    any('summary' in str(f).lower() for f in r.get('RelevantFiles', r.get('relevant_files', [])))
    for r in results if isinstance(r, dict)
)
print(f'  ai smoke: {len(results)} consumers, summaries present: {has_summary}')
"
    else
        echo -e "${DIM}--- smoke: ai (skipped — GOOGLE_API_KEY not set) ---${RESET}"
        RESULTS+=("${DIM}skip${RESET}  smoke: ai (no GOOGLE_API_KEY)")
    fi
fi

# --- Summary ---
echo -e "${BOLD}Results${RESET}"
for r in "${RESULTS[@]}"; do
    echo -e "  $r"
done
echo ""

if [ $FAILED -ne 0 ]; then
    echo -e "${RED}Some checks failed.${RESET}"
    exit 1
else
    echo -e "${GREEN}All checks passed.${RESET}"
fi
