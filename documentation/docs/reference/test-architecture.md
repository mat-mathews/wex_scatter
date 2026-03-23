# Test Architecture

For developers about to write or modify tests. This is the page Anya asked for.

---

## Running Tests

```bash
# Full suite
python -m pytest -v

# Specific file
pytest test_graph.py

# Specific test
pytest test_impact_analysis.py::test_something_specific

# With coverage
python -m pytest --cov=scatter
```

The full suite is 683 tests (1 xfail), and runs in roughly 9 seconds. No network calls, no database, no Docker. Just Python and your CPU.

Coverage is configured in `pyproject.toml` with `fail_under=70%`. The coverage source is the `scatter/` package only -- test files themselves are excluded from the metric.

---

## Full Test Inventory

25 test files. Here's every one of them, what it covers, and how many tests it contains.

| File | Tests | What it covers |
|------|------:|----------------|
| `test_cli_parser.py` | 15 | Argument parsing, flag combinations, defaults, mutual exclusivity |
| `test_cli_modes.py` | 16 | Mode handler dispatch (target-project, sproc, git-branch, graph, impact) |
| `test_cli_dispatch.py` | 13 | End-to-end CLI dispatch with mocked handlers, output format routing |
| `test_config.py` | 24 | Config loading, layering, CLI overrides, environment variable resolution |
| `test_consumer_analyzer_graph.py` | 14 | Graph-accelerated consumer detection vs filesystem fallback |
| `test_coupling.py` | 25 | Coupling metrics: fan-in, fan-out, instability, coupling score, cycles |
| `test_db_scanner.py` | 36 | DB pattern detection: sprocs, DbSet, SQL strings, connection strings, comment stripping |
| `test_domain.py` | 15 | Domain clustering: Louvain community detection, feasibility scoring, cluster membership |
| `test_filter_pipeline.py` | 21 | Filter funnel: stage counts, arrow-chain formatting, diagnostic hints |
| `test_find_enclosing_type.py` | 14 | `find_enclosing_type_name()`: nested types, generics, edge cases |
| `test_graph.py` | 46 | `DependencyGraph` data structure: add/remove nodes, edges, queries, connected components |
| `test_graph_cache.py` | 28 | Cache serialization (v2 fact-based), hash computation, staleness detection |
| `test_graph_enrichment.py` | 17 | Graph context enrichment: metrics injection, cycle detection, health dashboard |
| `test_graph_patcher.py` | 49 | Incremental graph updates: 6 mutation types, correctness vs full rebuild |
| `test_hybrid_git.py` | 7 | LLM-based symbol extraction: valid JSON, empty, invalid, markdown fences, exceptions |
| `test_impact_analysis.py` | 82 | Impact analysis: BFS traversal, confidence decay, depth limits, transitive chains |
| `test_markdown_reporter.py` | 39 | Markdown report generation: sections, tables, formatting, edge cases |
| `test_multiprocessing_phase1.py` | 7 | Parallel file discovery: consistency with sequential, worker count handling |
| `test_new_samples.py` | 54 | Extended sample project validation: GalaxyWorks.Common, Api, Data.Tests |
| `test_phase2_3_project_mapping.py` | 24 | Pipeline mapping and batch job verification |
| `test_pipeline_reporter.py` | 14 | Pipeline report output: CSV format, column ordering, missing data handling |
| `test_report_quality.py` | 24 | Cross-format consistency: JSON, CSV, console, markdown produce same core data |
| `test_reporters.py` | 21 | Reporter dispatch: format selection, file writing, stdout fallback |
| `test_summarize_consumers.py` | 7 | AI summarization with mocked providers, truncation at `MAX_SUMMARIZATION_CHARS` |
| `test_type_extraction.py` | 48 | Regex patterns: classes, structs, interfaces, enums, records, delegates, generics, edge cases |

---

## Test Patterns

### AI Mocking: No Real API Calls. Ever.

Every test that touches AI functionality uses `unittest.mock.MagicMock` as the provider. The pattern is consistent:

```python
from unittest.mock import MagicMock
from scatter.ai.base import AITaskType, AnalysisResult

mock_provider = MagicMock()
mock_provider.name = "mock-gemini"
mock_provider.supports.return_value = True
mock_provider.analyze.return_value = AnalysisResult(
    response='["MyClass", "IMyInterface"]',
    confidence=1.0,
)
```

Mock responses cover the full spectrum:
- **Valid JSON**: `'["TypeA", "TypeB"]'` -- happy path
- **Empty result**: `'[]'` -- comment-only or import-only changes
- **Invalid JSON**: `'not json at all'` -- tests fallback to regex
- **Markdown fence wrapping**: `'```json\n["TypeA"]\n```'` -- tests fence stripping
- **Exceptions**: `side_effect=Exception("API error")` -- tests error handling

If you write a test that makes a real API call, something has gone wrong. The CI has no API keys and never will.

### conftest.py: Shared Fixtures

The root `conftest.py` provides a `make_mode_context` factory fixture for building `ModeContext` objects with sensible defaults:

```python
def test_something(make_mode_context):
    ctx = make_mode_context(class_name="Foo", no_graph=False)
```

This saves you from constructing a 15-field dataclass in every test. Override what you care about; the factory fills in the rest with safe defaults (`search_scope=/tmp/scope`, `disable_multiprocessing=True`, etc.).

### Parallel Consistency

Any operation that supports `--disable-multiprocessing` is verified to produce identical results in both modes. The `test_multiprocessing_phase1.py` suite runs file discovery with N workers and with 0, then asserts the results match exactly. This pattern extends into the graph builder tests -- parallel graph construction must produce the same graph as sequential.

### Property-Based Tests: Incremental == Full Rebuild

`test_graph_patcher.py` is the crown jewel of the test suite at 49 tests. It verifies a critical invariant: **applying an incremental patch to a graph must produce the same result as building the graph from scratch.**

Six mutation types are tested:
1. Usage-only change (add a `using` statement)
2. Declaration change (add a new class)
3. New file added
4. File deleted
5. `.csproj` modified
6. Multiple simultaneous mutations

For each mutation, the test:
1. Builds a full graph from the clean codebase
2. Captures v2 facts
3. Applies the mutation
4. Patches the existing graph incrementally
5. Builds a fresh graph from the mutated codebase
6. Asserts the patched graph equals the fresh graph (nodes, edges, metrics)

This is as close to property-based testing as you get without hypothesis. The synthetic codebase generator (see [Benchmarks](benchmarks.md)) can produce arbitrary-scale codebases for fuzz-like coverage.

---

## How to Add a New Test

### Unit Test for a Scanner or Analyzer

```python
# test_my_new_scanner.py
from scatter.scanners.my_scanner import scan_something

def test_scan_finds_expected_pattern(tmp_path):
    """Create fixture data in tmp_path, run scanner, assert results."""
    cs_file = tmp_path / "MyProject" / "Service.cs"
    cs_file.parent.mkdir()
    cs_file.write_text('public class FooService { /* ... */ }')

    results = scan_something(tmp_path)
    assert "FooService" in results
```

Use `tmp_path` (pytest built-in) for any test that needs files on disk. It's auto-cleaned after each test.

### Test Against Sample Projects

The 11 `.csproj` files in the repo root are real .NET projects designed for integration testing. Use them when you need realistic project references, namespace structures, and type declarations:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def test_against_sample_projects():
    from scatter.analyzers.graph_builder import build_dependency_graph
    graph = build_dependency_graph(REPO_ROOT, disable_multiprocessing=True)
    assert graph.node_count == 11
```

See [Sample Projects](sample-projects.md) for the full dependency tree and expected values.

### Test with Mocked AI

```python
from unittest.mock import MagicMock
from scatter.ai.base import AITaskType, AnalysisResult

def test_ai_summarization_with_mock():
    provider = MagicMock()
    provider.supports.return_value = True
    provider.analyze.return_value = AnalysisResult(
        response="This service handles portal data operations.",
        confidence=0.95,
    )

    # Pass provider to whatever function you're testing
    result = summarize_file(provider, "PortalDataService.cs", file_content)

    provider.analyze.assert_called_once()
    assert "portal" in result.lower()
```

Three rules:
1. Always mock. Never call real APIs.
2. Test the happy path AND the failure path (exception, bad JSON, empty response).
3. Assert that the provider was actually called -- catch regressions where someone bypasses the provider.

---

## Test Organization

All test files live at the repo root, not in a `tests/` subdirectory. This is configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["."]
python_files = "test_*.py"
addopts = "-q"
```

The `-q` (quiet) default keeps output manageable for 683 tests. Override with `-v` when debugging.

---

## Coverage

```bash
# Run with coverage report
python -m pytest --cov=scatter

# HTML report (useful for finding uncovered branches)
python -m pytest --cov=scatter --cov-report=html
open htmlcov/index.html
```

Configuration in `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["scatter"]

[tool.coverage.report]
show_missing = true
skip_empty = true
fail_under = 70
```

The `fail_under=70` threshold is a floor, not a target. Most modules are well above that. The threshold exists to catch regressions -- if you add a new module with zero tests, coverage will drop and CI will tell you about it.
