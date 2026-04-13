#!/bin/bash
# Run scatter's test suite.
#
# Usage:
#   bash tools/test.sh              # all tests (unit + integration)
#   bash tools/test.sh unit         # unit tests only (~6s)
#   bash tools/test.sh integration  # integration tests only (~15s)
#   bash tools/test.sh smoke        # smoke tests against sample projects
#   bash tools/test.sh full         # lint + format + mypy + all tests + smoke
#   bash tools/test.sh coverage     # all tests with coverage report
#
# Windows: run from Git Bash (included with Git for Windows).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- colors ---
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

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

print_summary() {
    echo -e "\n${BOLD}Results${RESET}"
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
}

MODE="${1:-all}"

case "$MODE" in
    unit)
        echo -e "\n${BOLD}Unit tests${RESET}\n"
        run_step "unit tests" uv run pytest tests/unit -q
        ;;

    integration)
        echo -e "\n${BOLD}Integration tests${RESET}\n"
        run_step "integration tests" uv run pytest tests/integration -q
        ;;

    smoke)
        echo -e "\n${BOLD}Smoke tests${RESET}\n"
        run_step "target-project analysis" uv run scatter \
            --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
            --search-scope . \
            --output-format json \
            --output-file /tmp/scatter-smoke-target.json

        run_step "graph analysis" uv run scatter \
            --graph \
            --search-scope . \
            --output-format json \
            --output-file /tmp/scatter-smoke-graph.json

        run_step "sproc analysis" uv run scatter \
            --stored-procedure "dbo.sp_InsertPortalConfiguration" \
            --search-scope . \
            --output-format json \
            --output-file /tmp/scatter-smoke-sproc.json

        run_step "validate target output" python -c "
import json
d = json.load(open('/tmp/scatter-smoke-target.json'))
results = d.get('all_results', d) if isinstance(d, dict) else d
count = len(results) if isinstance(results, list) else len(d)
assert count > 0, 'No consumer results'
print(f'  {count} consumers found')
"
        run_step "validate graph output" python -c "
import json
d = json.load(open('/tmp/scatter-smoke-graph.json'))
assert isinstance(d, dict) and len(d) > 0, 'Empty graph'
print(f'  {d.get(\"node_count\", len(d))} nodes')
"
        ;;

    coverage)
        echo -e "\n${BOLD}Tests with coverage${RESET}\n"
        run_step "pytest + coverage" uv run pytest tests/ \
            --cov=scatter --cov-report=term-missing --cov-report=html -q
        echo -e "${DIM}HTML report: htmlcov/index.html${RESET}"
        ;;

    full)
        echo -e "\n${BOLD}Full check${RESET} (lint + format + mypy + tests + smoke)\n"
        run_step "ruff check"  uv run ruff check scatter/
        run_step "ruff format" uv run ruff format --check scatter/
        run_step "mypy"        uv run mypy scatter --ignore-missing-imports
        run_step "unit tests"  uv run pytest tests/unit -q
        run_step "integration tests" uv run pytest tests/integration -q

        run_step "smoke: target-project" uv run scatter \
            --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
            --search-scope . --output-format json --output-file /tmp/scatter-smoke-target.json

        run_step "smoke: graph" uv run scatter \
            --graph --search-scope . --output-format json --output-file /tmp/scatter-smoke-graph.json

        run_step "validate smoke output" python -c "
import json
t = json.load(open('/tmp/scatter-smoke-target.json'))
results = t.get('all_results', t) if isinstance(t, dict) else t
assert len(results) > 0, 'No consumer results'
g = json.load(open('/tmp/scatter-smoke-graph.json'))
assert isinstance(g, dict) and len(g) > 0, 'Empty graph'
print(f'  target: {len(results)} consumers, graph: {g.get(\"node_count\", len(g))} nodes')
"
        ;;

    all|"")
        echo -e "\n${BOLD}All tests${RESET} (unit + integration)\n"
        run_step "all tests" uv run pytest tests/ -q
        ;;

    *)
        echo "Usage: bash tools/test.sh [unit|integration|smoke|coverage|full|all]"
        exit 1
        ;;
esac

print_summary
