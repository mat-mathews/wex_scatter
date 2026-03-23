# Contributing

The page Anya asked for. How to add features, tests, and scanners to Scatter without breaking what already works.

---

## Development Setup

```bash
git clone <repo-url>
cd scatter

# One-command setup
bash tools/setup.sh
```

This checks Python >= 3.10, installs dependencies via [uv](https://docs.astral.sh/uv/), configures git, and links Claude Code skills. It's idempotent — run it again any time.

Verify everything works:

```bash
bash tools/check.sh
```

You should see all four checks pass (ruff check, ruff format, mypy, pytest). If anything fails, fix your environment before writing code.

---

## Code Organization

Full architecture details live in [Architecture Overview](architecture.md). Here's the quick mental model:

**Scanners discover.** They read files and extract facts. They don't transform or decide.

**Analyzers transform.** They take scanner output and build structured data -- graphs, metrics, clusters.

**Reporters output.** They take analyzer results and produce human/machine-readable formats.

All three layers are implemented as **free functions**, not methods on god objects. A scanner is a function that takes a path and returns data. An analyzer is a function that takes scanner output and returns richer data. A reporter is a function that takes analysis results and returns a string or writes a file.

```
scatter/
  scanners/        # file_scanner, project_scanner, type_scanner, sproc_scanner, db_scanner
  analyzers/       # graph_builder, consumer_analyzer, coupling_analyzer, domain_analyzer,
                   #   health_analyzer, impact_analyzer, git_analyzer, graph_enrichment
  reports/         # console_reporter, json_reporter, csv_reporter, markdown_reporter,
                   #   pipeline_reporter, graph_reporter
  ai/              # base (protocol + types), providers/{gemini,wex}_provider, router, tasks/*
  core/            # graph (DependencyGraph), models (dataclasses), patterns (regex), parallel
  store/           # graph_cache, graph_patcher
  cli.py           # Mode handlers and dispatch
  cli_parser.py    # Argument parser definition
  config.py        # Config loading and layering
```

---

## Adding a New Scanner

Scanners live in `scatter/scanners/`. They're the simplest things to add.

### Steps

1. **Create `scatter/scanners/your_scanner.py`**

```python
"""Scan for <whatever> patterns in .cs files."""
from pathlib import Path
from typing import List, Dict

def scan_your_thing(
    search_scope: Path,
    project_cs_map: Dict[str, List[Path]] | None = None,
) -> List[dict]:
    """Scan .cs files for <your pattern>.

    Args:
        search_scope: Root directory to scan.
        project_cs_map: Optional pre-computed project -> cs files mapping.
            If provided, avoids redundant file discovery.

    Returns:
        List of findings with project, file, and match details.
    """
    results = []
    # Your scanning logic here
    return results
```

2. **Export from `scatter/scanners/__init__.py`** if other modules need it:

```python
from scatter.scanners.your_scanner import scan_your_thing
```

3. **Wire into `graph_builder.py`** if your scanner produces edges. Add a stage after the existing extraction stages -- follow the pattern in `_build_type_usage_edges()` or the DB scanning stage.

4. **Wire into `cli.py` / `cli_parser.py`** if it needs a CLI flag. Add the flag in `cli_parser.py`, then handle it in the appropriate mode handler in `cli.py`.

5. **Add tests.** Create `test_your_scanner.py` at the repo root. Use `tmp_path` for fixture data.

### Design Principles

- Scanners are **pure functions** -- they take inputs and return outputs. No side effects, no mutation of shared state.
- Accept optional pre-computed data (like `project_cs_map`) to avoid redundant file discovery when called as part of the graph build pipeline.
- Return structured data (lists of dicts, dataclasses, NamedTuples). Not strings.

---

## Adding a New Reporter

Reporters live in `scatter/reports/`. They follow a two-function convention.

### Steps

1. **Create `scatter/reports/your_reporter.py`**

```python
"""Your output format reporter."""
from pathlib import Path
from typing import List, Optional

def build_your_report(
    consumers: List[dict],
    filter_pipeline,
    target_name: str,
    # ... whatever data your format needs
) -> str:
    """Build the report content as a string.

    Returns the formatted string -- does NOT write to disk.
    """
    lines = []
    # Build your output
    return "\n".join(lines)


def write_your_report(
    content: str,
    output_file: Optional[Path] = None,
) -> None:
    """Write report to file or stdout."""
    if output_file:
        output_file.write_text(content, encoding="utf-8")
    else:
        print(content)
```

The split between `build_*()` and `write_*()` is intentional. `build_*()` is testable without touching the filesystem. `write_*()` handles I/O.

2. **Add to `--output-format` choices in `cli_parser.py`**:

```python
parser.add_argument(
    "--output-format",
    choices=["console", "csv", "json", "markdown", "your_format"],
    default="console",
)
```

3. **Wire dispatch in `cli.py`**. Find the output dispatch section in the mode handler and add your format:

```python
if output_format == "your_format":
    content = build_your_report(consumers, filter_pipeline, target_name)
    write_your_report(content, output_file)
```

4. **Add tests.** Test `build_your_report()` directly -- pass it known inputs and assert the output string contains what you expect.

---

## Adding a New AI Task

AI tasks live in `scatter/ai/tasks/`. Each task is a focused prompt + response parser for a specific analytical question.

### Steps

1. **Create `scatter/ai/tasks/your_task.py`**

```python
"""AI task: <describe what it analyzes>."""
import json
import logging
from typing import Optional

from scatter.ai.base import AIProvider, AITaskType, AnalysisResult


def run_your_task(
    provider: AIProvider,
    context: str,
    # ... task-specific parameters
) -> Optional[dict]:
    """Run <your task> analysis.

    Returns parsed result dict, or None on failure.
    """
    if not provider.supports(AITaskType.YOUR_TASK_TYPE):
        return None

    prompt = f"Your prompt here with {context}"

    try:
        result: AnalysisResult = provider.analyze(
            prompt=prompt,
            context=context,
            task_type=AITaskType.YOUR_TASK_TYPE,
        )
        return json.loads(result.response)
    except (json.JSONDecodeError, Exception) as e:
        logging.warning(f"AI task failed: {e}")
        return None
```

2. **Add task type to `AITaskType` enum in `scatter/ai/base.py`**:

```python
class AITaskType(Enum):
    SUMMARIZATION = "summarization"
    SYMBOL_EXTRACTION = "symbol_extraction"
    # ... existing types ...
    YOUR_TASK_TYPE = "your_task_type"
```

3. **Implement `supports()` in the provider(s).** In `scatter/ai/providers/gemini_provider.py` (and `wex_provider.py` when implemented), add your task type to the supported set.

4. **Wire into the appropriate mode handler in `cli.py`.** Follow the pattern of existing AI tasks -- check if provider is available, call your task function, handle None return gracefully.

5. **Mock the provider in tests. Never make real API calls.** Note: `WexProvider(api_key="test")` can be instantiated for config validation tests, but all its analysis methods raise `NotImplementedError` until the API contract is implemented.

```python
from unittest.mock import MagicMock
from scatter.ai.base import AITaskType, AnalysisResult

def test_your_task_happy_path():
    provider = MagicMock()
    provider.supports.return_value = True
    provider.analyze.return_value = AnalysisResult(
        response='{"key": "value"}',
        confidence=0.9,
    )

    result = run_your_task(provider, context="test input")
    assert result == {"key": "value"}

def test_your_task_api_failure():
    provider = MagicMock()
    provider.supports.return_value = True
    provider.analyze.side_effect = Exception("API timeout")

    result = run_your_task(provider, context="test input")
    assert result is None
```

---

## Running Tests

```bash
# Full local CI check (lint + format + mypy + pytest) — run before pushing
bash tools/check.sh

# Quick lint-only (~2 seconds)
bash tools/check.sh --quick

# Just the test suite
uv run pytest

# Specific file
uv run pytest test_graph.py

# Specific test by name
uv run pytest test_impact_analysis.py -k "test_bfs_depth"

# With coverage
uv run pytest --cov=scatter --cov-report=term-missing

# Stop on first failure
uv run pytest -x
```

All AI tests use mocks. If your test needs an AI provider, mock it. The CI environment has no API keys and no network access to AI services.

---

## Linting & Formatting

Scatter uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting, configured in `pyproject.toml`.

```bash
# Check for lint errors
uv run ruff check scatter/

# Auto-fix what ruff can
uv run ruff check scatter/ --fix

# Format code
uv run ruff format scatter/

# Check formatting without changing files
uv run ruff format --check scatter/
```

Configuration highlights (see `[tool.ruff]` in `pyproject.toml`):

- **Line length 100** — middle ground between 88 and 120
- **Rules: E, F, W** — pycodestyle errors/warnings + pyflakes
- **E501 ignored** — long strings are fine; ruff format handles code structure
- **E741 ignored** — ambiguous variable names are a font problem, not a code problem
- **F401 ignored in `__init__.py`** — barrel re-exports are intentional

## Type Checking

[mypy](https://mypy.readthedocs.io/) is configured in `pyproject.toml` and runs in CI.

```bash
uv run mypy scatter --ignore-missing-imports
```

Current baseline: 0 errors. Keep it that way.

## Style Guide

Follow the patterns in the existing code:

- **Free functions preferred.** If you're reaching for a class, ask yourself if a function would work. It usually does.
- **Dataclasses for structured data.** Not dicts, not NamedTuples. Dataclasses give us type hints, defaults, and readability.
- **Type hints on public APIs.** Every function that another module imports should have parameter and return type annotations. Internal helpers can skip them if the types are obvious.
- **Docstrings on public functions.** One-liner is fine for simple functions. Multi-line for anything with non-obvious behavior.
- **Logging, not print.** Use `logging.info()`, `logging.warning()`, etc. The CLI controls the log level.
- **No hardcoded paths.** Everything flows from `search_scope` or `Path` arguments.

---

## CI Pipeline

GitHub Actions runs three parallel jobs on every push to `main` and every PR:

| Job | What it runs | Matrix |
|-----|-------------|--------|
| **test** | `uv run pytest --cov=scatter` | Python 3.10, 3.11 |
| **lint** | `uv run ruff check scatter/` + `uv run ruff format --check scatter/` | 3.11 |
| **type-check** | `uv run mypy scatter --ignore-missing-imports` | 3.11 |

The local `bash tools/check.sh` runs the exact same commands. If it passes locally, CI will pass.

## PR Checklist

Before opening a PR, verify:

- [ ] `bash tools/check.sh` passes (lint + format + mypy + tests)
- [ ] New code has tests
- [ ] No hardcoded file paths
- [ ] No secrets, API keys, or credentials in code
- [ ] Type hints on public function signatures
- [ ] `--disable-multiprocessing` produces identical results to parallel mode (if applicable)
- [ ] Coverage hasn't dropped below 70%

---

## Existing AI Task Types for Reference

The `AITaskType` enum currently defines these tasks:

| Task Type | Purpose | Used in |
|-----------|---------|---------|
| `SUMMARIZATION` | 2-3 sentence summary of a C# file | Consumer analysis with `--summarize-consumers` |
| `SYMBOL_EXTRACTION` | Identify changed types from a diff | Git branch mode with `--enable-hybrid-git` |
| `WORK_REQUEST_PARSING` | Extract targets from a SOW/work request | Impact analysis mode |
| `RISK_ASSESSMENT` | Rate risk of a consumer relationship | Impact analysis enrichment |
| `COUPLING_NARRATIVE` | Explain coupling vectors in plain English | Impact analysis enrichment |
| `IMPACT_NARRATIVE` | Manager-friendly impact summary | Impact analysis report |
| `COMPLEXITY_ESTIMATE` | Effort estimate for a change | Impact analysis report |
| `BOUNDARY_ASSESSMENT` | Evaluate domain boundary health | Graph mode enrichment |
