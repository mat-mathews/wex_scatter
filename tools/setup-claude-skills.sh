#!/bin/bash
# Symlink scatter Claude Code skills into the project's .claude/skills/ directory.
# Run from the repo root: bash tools/setup-claude-skills.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/tools/claude-skills"
TARGET_DIR="$REPO_ROOT/.claude/skills"

mkdir -p "$TARGET_DIR"

for skill_dir in "$SKILLS_DIR"/scatter-*/; do
    skill_name="$(basename "$skill_dir")"
    link_path="$TARGET_DIR/$skill_name"

    if [ -L "$link_path" ]; then
        echo "  exists: $skill_name (symlink)"
    elif [ -d "$link_path" ]; then
        echo "  exists: $skill_name (directory — skipping, remove manually to use symlink)"
    else
        ln -s "$skill_dir" "$link_path"
        echo "  linked: $skill_name"
    fi
done

echo ""
echo "Done. Skills available in Claude Code:"
echo "  /scatter-graph       — dependency health, coupling, cycles"
echo "  /scatter-consumers   — find who uses a project"
echo "  /scatter-impact      — SOW/change blast radius"
echo "  /scatter-sproc       — stored procedure consumers"
echo "  /scatter-branch      — git branch impact analysis"
