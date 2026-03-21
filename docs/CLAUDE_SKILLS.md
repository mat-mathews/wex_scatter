# Scatter Claude Code Skills

These skills let engineers use scatter through Claude Code with natural language
instead of memorizing CLI flags.

## Setup

From the repo root:

```bash
bash tools/setup-claude-skills.sh
```

This symlinks the skills into `.claude/skills/` where Claude Code auto-discovers them.

## Available Skills

### Auto-invoked (Claude picks these based on your question)

| Skill | Slash command | Example prompts |
|-------|--------------|-----------------|
| **scatter-graph** | `/scatter-graph .` | "Show me the dependency health", "What's coupled to what?", "Are there circular dependencies?" |
| **scatter-consumers** | `/scatter-consumers ./MyProject.csproj .` | "Who uses GalaxyWorks.Data?", "What depends on this project?", "What would break if I changed X?" |
| **scatter-impact** | `/scatter-impact "Add tenant isolation"` | "What's the blast radius of changing X?", "Scope this SOW", "How many projects does this touch?" |

### Manual-only (invoke with slash command)

| Skill | Slash command | When to use |
|-------|--------------|-------------|
| **scatter-sproc** | `/scatter-sproc dbo.sp_X .` | Find stored procedure consumers specifically |
| **scatter-branch** | `/scatter-branch feature/x .` | Analyze a specific git branch's impact |

scatter-sproc and scatter-branch are manual-only to avoid confusion with the
auto-invoked skills that cover similar use cases (scatter-consumers and
scatter-impact respectively).

## How It Works

Each skill contains a SKILL.md with instructions for Claude Code:
1. How to invoke the scatter CLI with the right flags
2. How to read and interpret the JSON output
3. What to focus on when summarizing results
4. How to handle errors

Skills can be invoked two ways:
- **Explicit**: type `/scatter-graph` in Claude Code
- **Automatic**: ask a matching question and Claude picks the right skill
  (only for the three auto-invoked skills above)

## Smoke Tests

Verify the skill commands work against the sample projects:

```bash
bash tools/smoke-test-claude-skills.sh
```

This runs each scatter command (without Claude) and checks for non-empty output.
Set `GOOGLE_API_KEY` to include the impact analysis test.

## Prerequisites

- scatter must be runnable via `python -m scatter` in the repo
- Dependencies installed (`uv sync` or `pip install .`)
- For AI-enriched features (risk assessment, complexity): set `GOOGLE_API_KEY` env var
