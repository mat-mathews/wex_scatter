#!/bin/bash
# Local CI mirror — runs the same checks as .github/workflows/ci.yml.
# Usage:
#   bash tools/check.sh          # full: lint + format + mypy + pytest
#   bash tools/check.sh --quick  # fast: lint + format only

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
    echo -e "\n${BOLD}Full check${RESET} (lint + format + mypy + pytest)\n"
fi

# --- Always run ---
run_step "ruff check"  uv run ruff check scatter/
run_step "ruff format" uv run ruff format --check scatter/

# --- Full only ---
if ! $QUICK; then
    run_step "mypy"  uv run mypy scatter --ignore-missing-imports
    run_step "pytest" uv run pytest --cov=scatter --cov-report=term-missing -q
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
