# Testing

Scatter has ~820 tests organized into unit and integration suites, plus CLI smoke tests. This page covers the test layout, how to run them, and how to write new ones.

---

## Quick Reference

```bash
# Run everything (unit + integration)
bash tools/test.sh

# Run just unit tests (~6 seconds)
bash tools/test.sh unit

# Run just integration tests (~15 seconds)
bash tools/test.sh integration

# Smoke tests against the sample .NET projects
bash tools/test.sh smoke

# Full CI mirror: lint + format + mypy + all tests + smoke
bash tools/test.sh full

# Tests with coverage report (HTML output in htmlcov/)
bash tools/test.sh coverage
```

Or use pytest directly:

```bash
# All tests
uv run pytest

# Unit only
uv run pytest tests/unit

# Integration only
uv run pytest tests/integration

# Single file
uv run pytest tests/unit/test_graph.py

# Single test
uv run pytest tests/unit/test_graph.py::TestDependencyGraph::test_add_node

# Verbose with print output
uv run pytest tests/unit/test_graph.py -v -s

# Stop on first failure
uv run pytest -x

# Run tests matching a keyword
uv run pytest -k "coupling"
```

---

## Test Layout

```
tests/
├── conftest.py              # Shared fixtures (make_mode_context, make_consumer_result)
├── unit/                    # Fast, isolated tests (~640 tests, ~6s)
│   ├── test_cli_dispatch.py
│   ├── test_cli_modes.py
│   ├── test_cli_parser.py
│   ├── test_codebase_index.py
│   ├── test_config.py
│   ├── test_coupling.py
│   ├── test_db_scanner.py
│   ├── test_domain.py
│   ├── test_filter_pipeline.py
│   ├── test_find_enclosing_type.py
│   ├── test_graph.py
│   ├── test_graph_cache.py
│   ├── test_graph_enrichment.py
│   ├── test_hybrid_git.py
│   ├── test_impact_analysis.py
│   ├── test_markdown_reporter.py
│   ├── test_packaging.py
│   ├── test_pipeline_reporter.py
│   ├── test_report_quality.py
│   ├── test_reporters.py
│   ├── test_solution_scanner.py
│   ├── test_summarize_consumers.py
│   └── test_type_extraction.py
├── integration/             # Multi-module and filesystem tests (~175 tests, ~15s)
│   ├── test_consumer_analyzer_graph.py
│   ├── test_gemini_access.py
│   ├── test_graph_patcher.py
│   ├── test_impact_e2e.py
│   ├── test_multiprocessing_phase1.py
│   ├── test_new_samples.py
│   ├── test_phase2_3_project_mapping.py
│   └── test_solution_e2e.py
```

### What goes where

**Unit tests** (`tests/unit/`): Test a single module in isolation. Use hand-built data structures, mocks, and `tmp_path` for temp files. Don't read from the sample .NET projects on disk, don't call external APIs, don't invoke the full analysis pipeline. These should run in seconds.

**Integration tests** (`tests/integration/`): Test multiple modules working together. Includes tests that:
- Run `build_dependency_graph()` against the sample .NET projects
- Call `find_consumers()` against real `.csproj` files on disk
- Invoke scatter as a subprocess and check output
- Create synthetic codebases in temp dirs and run the full pipeline
- Exercise multiprocessing and parallel file discovery

---

## Shared Fixtures

Defined in `tests/conftest.py`:

### `make_mode_context()`

Factory for `ModeContext` objects with sensible test defaults. Override any field:

```python
def test_something(make_mode_context):
    ctx = make_mode_context(search_scope=Path("/tmp/test"))
    assert ctx.search_scope == Path("/tmp/test")
```

### `make_consumer_result()`

Factory for `ConsumerResult` objects. Every field has a default:

```python
def test_reporter(make_consumer_result):
    result = make_consumer_result(
        consumer_project_name="MyApp",
        coupling_score=12.5,
    )
    assert result.consumer_project_name == "MyApp"
```

---

## Coverage

Coverage is configured in `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["scatter"]

[tool.coverage.report]
show_missing = true
skip_empty = true
fail_under = 70
```

Run with coverage:

```bash
# Terminal report
uv run pytest --cov=scatter --cov-report=term-missing

# HTML report (opens in browser)
uv run pytest --cov=scatter --cov-report=html
open htmlcov/index.html
```

The CI workflow runs coverage on every push and PR. The `fail_under = 70` threshold means CI fails if coverage drops below 70%.

---

## CI Integration

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs four parallel jobs:

| Job | What it runs | Python versions |
|-----|-------------|-----------------|
| **test** | `pytest --cov=scatter` | 3.10, 3.11 |
| **lint** | `ruff check` + `ruff format --check` | 3.11 |
| **type-check** | `mypy scatter --ignore-missing-imports` | 3.11 |
| **smoke** | Target-project and graph analysis against sample projects | 3.11 |

All jobs use `astral-sh/setup-uv@v4` with dependency caching.

### Running the full CI check locally

```bash
# Mirror exactly what CI runs
bash tools/test.sh full

# Or the quick version (lint + format only, ~2 seconds)
bash tools/check.sh --quick
```

---

## Writing New Tests

### Where to put it

- Testing a single function with mock/synthetic data? → `tests/unit/`
- Testing a pipeline that reads real files or runs scatter end-to-end? → `tests/integration/`

### Accessing the repo root

Tests that need to reference sample .NET projects (integration tests) use:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
```

This resolves from `tests/integration/test_foo.py` → `tests/integration/` → `tests/` → repo root.

### Accessing sample projects

The repo ships with 8 sample .NET projects for testing:

```python
REPO_ROOT = Path(__file__).parent.parent.parent
galaxy_csproj = REPO_ROOT / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
```

Available sample projects: `GalaxyWorks.Data`, `GalaxyWorks.WebPortal`, `GalaxyWorks.BatchProcessor`, `GalaxyWorks.Data.Tests`, `GalaxyWorks.Common`, `MyDotNetApp`, `MyGalaxyConsumerApp`, `MyGalaxyConsumerApp2`.

### Test naming

- Files: `test_<module_name>.py` — matches the module being tested
- Classes: `TestClassName` — group related tests
- Functions: `test_<behavior_being_tested>` — describe what's verified, not how

### Using tmp_path

For tests that create files:

```python
def test_cache_roundtrip(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    save_graph(graph, cache_file)
    loaded = load_graph(cache_file)
    assert loaded.node_count == graph.node_count
```

### Mocking AI providers

Tests that would call external AI APIs should mock the provider:

```python
from unittest.mock import MagicMock

def test_with_mocked_ai():
    provider = MagicMock()
    provider.generate.return_value = "mocked summary"
    result = summarize(provider, content="...")
    assert "mocked" in result
```

`test_gemini_access.py` in `tests/integration/` is the one exception — it's a manual smoke test that hits the real Gemini API and requires an API key argument. It is not collected by pytest's default run.

---

## Benchmarks

Benchmarks are separate from the test suite and live in `tools/`. They are not run in CI (too slow) but should be run before and after performance-sensitive changes.

```bash
# Generate a synthetic codebase
python tools/generate_synthetic_codebase.py --preset medium --output /tmp/scatter_bench

# Full graph build benchmark (threaded, no tracemalloc)
python tools/benchmark_graph_build.py /tmp/scatter_bench --mode full --runs 3 --warmup

# Per-stage instrumented benchmark (sequential, with tracemalloc)
python tools/benchmark_graph_build.py /tmp/scatter_bench --mode stages --runs 3 --warmup

# Incremental patching benchmark
python tools/benchmark_incremental.py --preset small medium
```

See the README benchmarking section for full details and current numbers.
