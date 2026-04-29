# Getting Started

Two ways to run scatter:

- **Native install** (this page) — Python 3.10+, Git, and uv. Best for development and daily use.
- **[Docker](usage/docker.md)** — just Docker. No Python, no uv, nothing else to install.

This page covers the native install. The repo includes 13 sample .NET projects, so you don't need a production codebase to start.

!!! tip "Don't have Python?"
    Skip this page entirely — run scatter via Docker with no local dependencies:
    ```bash
    docker build -t scatter .
    docker run -v "$(pwd)":/workspace scatter --help
    ```
    See [Docker](usage/docker.md) for full usage, cache volumes, and platform-specific examples.

## Prerequisites

- **Python 3.10+** -- Scatter uses type hints and dataclass features
- **Git** -- needed for branch analysis mode and for incremental graph patching

## Installation

```bash
git clone <repo-url>
cd scatter
```

=== "Windows (PowerShell)"

    ```powershell
    pwsh tools/setup.ps1
    ```

=== "macOS / Linux"

    ```bash
    bash tools/setup.sh
    ```

The setup script:

1. Checks Python >= 3.10 is available
2. Checks [uv](https://docs.astral.sh/uv/) is installed (prints install command if not)
3. Runs `uv sync` to install all dependencies
4. Configures git to use `.git-blame-ignore-revs`
5. Copies Claude Code skills into `.claude/skills/`

It's idempotent — safe to run again any time.

!!! note "Optional: AST validation"
    For `--parser-mode hybrid` (tree-sitter false positive filtering), install the AST extra:
    ```bash
    uv sync --extra ast
    ```
    This is optional — without it, `--parser-mode hybrid` silently falls back to regex. The Docker image includes it by default.

!!! note "Manual setup"
    If you prefer to set things up yourself:

    **macOS / Linux:**
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv sync
    ```

    **Windows (PowerShell):**
    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    uv sync
    ```

## Verify it works

```bash
uv run scatter --help
```

You should see the five analysis modes (`--target-project`, `--branch-name`, `--stored-procedure`, `--sow`, `--graph`) and all the common options. If you see that, you're good.

## Next: see it in action

Head to the [Quick Tour](quick-tour.md) to run your first analysis and see what the output looks like.

## Using with Claude Code

If you use Claude Code, the setup script already linked five analysis skills. Ask Claude directly:

- "Show me the dependency health of this codebase"
- "Who uses GalaxyWorks.Data?"
- "What's the blast radius of adding tenant isolation to portal configuration?"

Three skills auto-invoke based on your question (graph, consumers, impact). Two are manual slash commands (`/scatter-sproc`, `/scatter-branch`).

See [Claude Code Skills documentation](reference/claude-skills.md) for details.
