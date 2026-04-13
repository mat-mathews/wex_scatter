#!/bin/bash
# Smoke test: verify each scatter skill command runs successfully against
# the sample .NET projects in this repo.
#
# Usage: bash tools/smoke-test-claude-skills.sh
#
# This does NOT test Claude Code integration — it validates that the CLI
# commands embedded in each SKILL.md produce valid output.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
SKIP=0
OUTFILE=$(mktemp /tmp/scatter_smoke_XXXXXX.json)

cleanup() {
    rm -f "$OUTFILE"
}
trap cleanup EXIT

run_test() {
    local name="$1"
    shift
    echo -n "  $name ... "
    if "$@" 2>/dev/null; then
        if [ -s "$OUTFILE" ]; then
            echo "OK"
            PASS=$((PASS + 1))
        else
            echo "FAIL (empty output)"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "FAIL (exit code $?)"
        FAIL=$((FAIL + 1))
    fi
    : > "$OUTFILE"  # truncate for next test
}

echo "Scatter Claude Skills — Smoke Tests"
echo "====================================="
echo ""

# scatter-graph: dependency graph analysis
echo "scatter-graph:"
run_test "graph json output" \
    python -m scatter --graph --include-db --search-scope . --output-format json --output-file "$OUTFILE"

# scatter-consumers: target project consumers
echo "scatter-consumers:"
run_test "consumers json output" \
    python -m scatter --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . --output-format json --output-file "$OUTFILE"

# scatter-sproc: stored procedure consumers
echo "scatter-sproc:"
run_test "sproc json output" \
    python -m scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . --output-format json --output-file "$OUTFILE"

# scatter-branch: git branch analysis (uses current branch vs main)
echo "scatter-branch:"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    run_test "branch json output" \
        python -m scatter --branch-name "$CURRENT_BRANCH" --repo-path . --output-format json --output-file "$OUTFILE"
else
    echo "  branch json output ... SKIP (on main, need a feature branch)"
    SKIP=$((SKIP + 1))
fi

# scatter-impact: SOW impact analysis (requires Gemini API key)
echo "scatter-impact:"
if [ -n "$GOOGLE_API_KEY" ]; then
    SOW_TEMP=$(mktemp /tmp/scatter_sow_XXXXXX.txt)
    echo "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation" > "$SOW_TEMP"
    run_test "impact json output (with AI)" \
        python -m scatter --sow-file "$SOW_TEMP" --search-scope . --output-format json --output-file "$OUTFILE"
    rm -f "$SOW_TEMP"
else
    echo "  impact json output ... SKIP (GOOGLE_API_KEY not set)"
    SKIP=$((SKIP + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
