# Getting Started

Install Scatter and verify it works. Takes about two minutes.

## Prerequisites

- **Python 3.10+** -- Scatter uses modern type hints and dataclass features
- **Git** -- needed for branch analysis mode and for incremental graph patching

That's it. The repo ships with 8 sample .NET projects, so you don't need a production codebase to start.

## Installation

```bash
git clone <repo-url>
cd scatter

# One-command dev setup (Windows: run from Git Bash)
bash tools/setup.sh
```

The setup script:

1. Checks Python >= 3.10 is available
2. Checks [uv](https://docs.astral.sh/uv/) is installed (prints install command if not)
3. Runs `uv sync` to install all dependencies
4. Configures git to use `.git-blame-ignore-revs`
5. Links Claude Code skills into `.claude/skills/`

It's idempotent — safe to run again any time.

!!! note "Manual setup"
    If you prefer to set things up yourself:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv
    uv sync                                             # install deps
    ```

## Verify it works

```bash
uv run scatter --help
```

You should see the five analysis modes (`--target-project`, `--branch-name`, `--stored-procedure`, `--sow`, `--graph`) and all the common options. If you see that, you're good.

## Using with Claude Code

If you use Claude Code, the setup script already linked five analysis skills. Ask Claude directly:

- "Show me the dependency health of this codebase"
- "Who uses GalaxyWorks.Data?"
- "What's the blast radius of adding tenant isolation to portal configuration?"

Three skills auto-invoke based on your question (graph, consumers, impact). Two are manual slash commands (`/scatter-sproc`, `/scatter-branch`).

See [Claude Code Skills documentation](reference/claude-skills.md) for details.

## Next: see it in action

Head to the [Quick Tour](quick-tour.md) to run your first analysis and see what the output looks like.
