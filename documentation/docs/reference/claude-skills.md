# Claude Code Skills

Scatter ships with five Claude Code skills that let engineers interact with the analysis engine through natural language instead of CLI flags.

## Setup

```bash
bash tools/setup-claude-skills.sh
```

This symlinks the skills from `tools/claude-skills/` into `.claude/skills/` where Claude Code auto-discovers them.

## Available Skills

### Auto-invoked

Claude picks these automatically based on your question:

| Skill | Example prompts |
|-------|----------------|
| **scatter-graph** | "Show me the dependency health", "What's coupled to what?", "Are there circular dependencies?" |
| **scatter-consumers** | "Who uses GalaxyWorks.Data?", "What depends on this project?" |
| **scatter-impact** | "What's the blast radius of changing X?", "Scope this SOW" |

### Manual slash commands

Invoke explicitly when you need a specific mode:

| Skill | Command | When to use |
|-------|---------|-------------|
| **scatter-sproc** | `/scatter-sproc dbo.sp_X .` | Find stored procedure consumers |
| **scatter-branch** | `/scatter-branch feature/x .` | Analyze a git branch's impact |

## How It Works

Each skill contains a `SKILL.md` with instructions for Claude Code:

1. How to invoke scatter with the right CLI flags
2. How to read and interpret the JSON output
3. What to focus on when summarizing results
4. How to handle errors

Claude runs the scatter command, reads the structured output, and responds with a narrative summary tailored to your question.

## Smoke Testing

Verify the skill commands work:

```bash
bash tools/smoke-test-claude-skills.sh
```

This runs each scatter command (without Claude) against the sample projects. Set `GOOGLE_API_KEY` to include the impact analysis test.

## Prerequisites

- Scatter runnable via `python -m scatter`
- Dependencies installed (`pip install -r requirements.txt` or `uv sync`)
- For AI-enriched features: set `GOOGLE_API_KEY` env var
