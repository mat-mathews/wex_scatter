# Getting Started

Two options:

- **Native install** (this page) — Python 3.10+, Git, and uv. Best for development and daily use.
- **[Docker](usage/docker.md)** — just Docker. Nothing else to install.

The repo includes 13 sample .NET projects, so you can start analyzing before you point it at a real codebase.

!!! tip "Don't have Python?"
    Skip this page entirely and run Scatter via Docker:
    ```bash
    docker build -t scatter .
    docker run -v "$(pwd)":/workspace scatter --help
    ```
    See [Docker](usage/docker.md) for full usage.

## Prerequisites

- **Python 3.10+** — for the type hints and dataclass features Scatter uses internally
- **Git** — branch analysis and incremental graph patching both need it

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

The setup script checks for Python 3.10+ and uv, syncs dependencies, configures git blame ignores, and wires up Claude Code skills if you use them. Run it multiple times without breaking anything.

!!! note "Optional: AST validation"
    For more precise type detection (tree-sitter filters false positives from comments and string literals):
    ```bash
    uv sync --extra ast
    ```
    Optional — without it, Scatter falls back to regex automatically. The Docker image includes it by default.

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

You should see the six analysis modes (`--target-project`, `--branch-name`, `--stored-procedure`, `--sow`, `--graph`, `--pr-risk`) and all the common options. If you see that, you're good.

## Next: see it in action

Head to the [Quick Tour](quick-tour.md) to run your first analysis against the sample projects.

## Using with Claude Code

If you use Claude Code, the setup script already linked five analysis skills. Ask Claude directly:

- "Show me the dependency health of this codebase"
- "Who uses GalaxyWorks.Data?"
- "What's the blast radius of adding tenant isolation to portal configuration?"

Three skills auto-invoke based on your question (graph, consumers, impact). Two are manual slash commands (`/scatter-sproc`, `/scatter-branch`). See [Claude Code Skills](reference/claude-skills.md) for details.
