#!/bin/bash
# One-time developer environment bootstrap.
# Run from anywhere: bash tools/setup.sh
# Safe to re-run — all steps are idempotent.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- colors ---
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

pass()  { echo -e "  ${GREEN}ok${RESET}  $1"; }
warn()  { echo -e "  ${YELLOW}!!${RESET}  $1"; }
fail()  { echo -e "  ${RED}FAIL${RESET}  $1"; }

echo -e "\n${BOLD}wex-scatter dev setup${RESET}\n"

# --- 1. Python version ---
echo -e "${BOLD}Python${RESET}"

if ! command -v python3 &>/dev/null; then
    fail "python3 not found on PATH"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    fail "Python >= 3.10 required (found $PY_VERSION)"
    echo "       Install 3.10+ and try again."
    exit 1
fi
pass "Python $PY_VERSION"

# --- 2. uv ---
echo -e "\n${BOLD}uv${RESET}"

if ! command -v uv &>/dev/null; then
    warn "uv not found"
    echo "       Install it with:"
    echo ""
    echo "         curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    echo "       Then re-run this script."
    exit 1
fi
pass "uv $(uv --version 2>/dev/null | head -1)"

# --- 3. Dependencies ---
echo -e "\n${BOLD}Dependencies${RESET}"

cd "$REPO_ROOT"
uv sync --quiet
pass "uv sync (all deps installed)"

# --- 4. Git config ---
echo -e "\n${BOLD}Git${RESET}"

if [ -f "$REPO_ROOT/.git-blame-ignore-revs" ]; then
    git -C "$REPO_ROOT" config blame.ignoreRevsFile .git-blame-ignore-revs
    pass "blame.ignoreRevsFile configured"
else
    warn ".git-blame-ignore-revs not found — skipping"
fi

# --- 5. Claude skills ---
echo -e "\n${BOLD}Claude skills${RESET}"

if [ -x "$SCRIPT_DIR/setup-claude-skills.sh" ]; then
    bash "$SCRIPT_DIR/setup-claude-skills.sh"
else
    warn "setup-claude-skills.sh not found — skipping"
fi

# --- Summary ---
echo -e "\n${BOLD}Ready!${RESET}\n"
echo "  Run tests:          uv run pytest"
echo "  Run full check:     bash tools/check.sh"
echo "  Run quick check:    bash tools/check.sh --quick"
echo ""
echo -e "  ${YELLOW}Optional:${RESET} add a pre-push hook to run checks automatically:"
echo "    echo 'bash tools/check.sh' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push"
echo ""
