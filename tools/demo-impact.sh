#!/bin/bash
# Demonstrate scatter's impact analysis on the sample .NET projects.
# Works without an API key (shows blast radius tree).
# With a GOOGLE_API_KEY, shows full AI-enriched report.
# Windows: run from Git Bash (included with Git for Windows).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "Scatter Impact Analysis Demo"
echo "============================"
echo ""
echo "SOW: Modify PortalDataService in GalaxyWorks.Data to add tenant isolation"
echo ""

uv run scatter \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation parameter" \
  --search-scope "$REPO_ROOT" \
  --output-format markdown
