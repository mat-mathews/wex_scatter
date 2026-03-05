# Initiative 3: Modularization & AI Backend Foundation — Implementation Plan

## Context

`scatter.py` is a 2,357-line monolithic file containing 28 functions, 1 regex constant, 1 global variable, and a ~678-line `__main__` block. All 70 existing tests import directly from `scatter` (the file). The goal is to split this into a `scatter/` package with clean module boundaries while maintaining backward compatibility at every step.

This plan is deliberately conservative. Each phase produces a working system with all 70 tests passing. No phase introduces new dependencies (until Phase 5, which adds `pyyaml`). The existing `scatter.py` file is preserved as a thin CLI entry point throughout.

---

## Current Function Inventory

Every function in `scatter.py`, grouped by logical domain:

### Multiprocessing Infrastructure (lines 39-637)
| Function | Lines | Role |
|----------|-------|------|
| `chunk_list()` | 39-41 | Split list into chunks |
| `find_files_with_pattern_chunk()` | 43-53 | Worker: find files in directory list |
| `map_cs_to_projects_batch()` | 56-114 | Worker: map .cs files to .csproj |
| `parse_csproj_files_batch()` | 117-185 | Worker: parse csproj for ProjectReference |
| `parse_csproj_files_parallel()` | 188-252 | Orchestrator: parallel csproj parsing |
| `map_cs_to_projects_parallel()` | 255-319 | Orchestrator: parallel project mapping |
| `analyze_cs_files_batch()` | 322-405 | Worker: analyze .cs files for patterns |
| `analyze_cs_files_parallel()` | 408-479 | Orchestrator: parallel .cs analysis |
| `estimate_file_count()` | 482-535 | Estimate file count by sampling |
| `find_files_with_pattern_parallel()` | 538-637 | Orchestrator: parallel file discovery |

### Type Extraction (lines 639-666)
| Function | Lines | Role |
|----------|-------|------|
| `TYPE_DECLARATION_PATTERN` | 640-647 | Compiled regex constant |
| `extract_type_names_from_content()` | 651-666 | Extract C# type declarations from content |

### Git Operations (lines 669-951)
| Function | Lines | Role |
|----------|-------|------|
| `find_project_file()` | 670-771 | Find .csproj via git tree traversal |
| `find_project_file_on_disk()` | 774-801 | Find .csproj via filesystem walk |
| `analyze_branch_changes()` | 804-876 | Compare branches, return {project: [files]} |
| `get_diff_for_file()` | 879-892 | Get unified diff for single file |
| `get_affected_symbols_from_diff()` | 895-950 | LLM-based diff symbol extraction |

### Project/Namespace Analysis (lines 953-989)
| Function | Lines | Role |
|----------|-------|------|
| `derive_namespace()` | 954-989 | Derive namespace from .csproj XML |

### AI/Gemini Integration (lines 992-1151)
| Function | Lines | Role |
|----------|-------|------|
| `configure_gemini()` | 992-1017 | Configure Gemini API client (global state) |
| `summarize_csharp_file_with_gemini()` | 1112-1151 | Summarize C# file via Gemini |

### Result Processing (lines 1020-1110)
| Function | Lines | Role |
|----------|-------|------|
| `_process_consumer_summaries_and_append_results()` | 1020-1110 | Process consumer data, map to pipelines, append to results |

### Consumer Analysis Pipeline (lines 1154-1417)
| Function | Lines | Role |
|----------|-------|------|
| `find_consumers()` | 1154-1417 | 5-step consumer detection pipeline |

### Sproc Analysis (lines 1420-1557)
| Function | Lines | Role |
|----------|-------|------|
| `find_cs_files_referencing_sproc()` | 1420-1557 | Find stored procedure references |

### Utility Functions (lines 1560-1676)
| Function | Lines | Role |
|----------|-------|------|
| `find_enclosing_type_name()` | 1560-1595 | Find enclosing class for code position |
| `find_solutions_for_project()` | 1598-1635 | Find .sln files referencing a .csproj |
| `map_batch_jobs_from_config_repo()` | 1638-1676 | Map batch jobs from config repo |

### CLI Entry Point (lines 1679-2357)
| Block | Lines | Role |
|-------|-------|------|
| Argument parser definition | 1679-1798 | All CLI flag definitions |
| Input validation + setup | 1800-1958 | Logging, Gemini config, path validation, pipeline/batch loading |
| Git mode dispatch | 1964-2102 | Git branch analysis workflow |
| Target mode dispatch | 2104-2162 | Target project analysis workflow |
| Sproc mode dispatch | 2164-2244 | Stored procedure analysis workflow |
| Output formatting (JSON/CSV/Console) | 2246-2357 | Result serialization and display |

### Global State
| Item | Line | Description |
|------|------|-------------|
| `gemini_model` | 30 | Global Gemini model instance |
| `DEFAULT_MAX_WORKERS` | 33 | Default worker count |
| `DEFAULT_CHUNK_SIZE` | 34 | Default chunk size |
| `MULTIPROCESSING_ENABLED` | 35 | Global multiprocessing toggle |

---

## Target Package Structure

Modules built in Initiative 3. Modules for later initiatives are not created.

```
scatter/                          # New package
    __init__.py                   # Re-exports for backward compat
    __main__.py                   # CLI entry point (moved from scatter.py)
    config.py                     # Phase 5: Config system

    core/
        __init__.py
        parallel.py               # Phase 1: Multiprocessing infrastructure
        models.py                 # Phase 1: Constants + shared types

    scanners/
        __init__.py
        file_scanner.py           # Phase 2: File discovery
        project_scanner.py        # Phase 2: .csproj parsing + namespace derivation
        type_scanner.py           # Phase 2: Type extraction + enclosing type
        sproc_scanner.py          # Phase 2: Sproc reference detection

    analyzers/
        __init__.py
        consumer_analyzer.py      # Phase 2: find_consumers() pipeline
        git_analyzer.py           # Phase 3: Git branch analysis

    ai/
        __init__.py
        base.py                   # Phase 4: AIProvider protocol
        router.py                 # Phase 5: Task router
        providers/
            __init__.py
            gemini_provider.py    # Phase 4: Migrated Gemini code

    reports/
        __init__.py
        console_reporter.py       # Phase 3: Console output
        json_reporter.py          # Phase 3: JSON output
        csv_reporter.py           # Phase 3: CSV output

    compat/
        __init__.py
        v1_bridge.py              # Phase 3: Pipeline/batch/solution helpers

scatter.py                        # Preserved as thin entry point
```

---

## Phased Implementation

### Phase 1: Package Skeleton + Core Infrastructure

**Goal:** Create the package directory, extract multiprocessing infrastructure and constants. All tests pass via re-exports.

**Dependency order:** This must be first because every other module depends on `core.parallel` and `core.models`.

#### Step 1.1: Create package skeleton

Create directory structure with empty `__init__.py` files for all subdirectories.

#### Step 1.2: Extract `scatter/core/models.py`

Move from `scatter.py`:
- `DEFAULT_MAX_WORKERS` constant
- `DEFAULT_CHUNK_SIZE` constant
- `MULTIPROCESSING_ENABLED` constant
- `TYPE_DECLARATION_PATTERN` compiled regex

No function dependencies. Pure constants and regex.

#### Step 1.3: Extract `scatter/core/parallel.py`

Move from `scatter.py`:
- `chunk_list()`
- `find_files_with_pattern_chunk()`
- `map_cs_to_projects_batch()`
- `parse_csproj_files_batch()`
- `parse_csproj_files_parallel()`
- `map_cs_to_projects_parallel()`
- `analyze_cs_files_batch()`
- `analyze_cs_files_parallel()`
- `estimate_file_count()`
- `find_files_with_pattern_parallel()`

These functions have no dependency on any other function in scatter.py (they only depend on each other, stdlib, and the constants). They are self-contained worker/orchestrator pairs.

#### Step 1.4: Update `scatter/__init__.py` for backward compatibility

Re-export every constant and function so that `from scatter import chunk_list` continues to work.

#### Step 1.5: Update `scatter.py` to import from package

Replace the extracted code blocks with imports from `scatter.core`.

#### Critical note: Python package vs module naming

`scatter.py` (file) and `scatter/` (directory) coexist. Python prefers the package directory for `import scatter`. This works in our favor:
- `import scatter` resolves to the package — tests work unchanged via `__init__.py` re-exports
- `scatter.py` is only used as a CLI entry point (`python scatter.py`), not as an importable module
- When run as `python scatter.py`, Python loads the script directly (not via import), so it can import from the `scatter` package

#### Testing checkpoint
- `python -m pytest` — all 70 tests pass
- All three CLI modes produce identical output

#### Files changed
| File | Action |
|------|--------|
| `scatter/` directory tree | Create (all `__init__.py` files) |
| `scatter/core/models.py` | Create (constants + regex) |
| `scatter/core/parallel.py` | Create (10 functions, ~500 lines) |
| `scatter/__init__.py` | Create (re-exports) |
| `scatter.py` | Modify (replace ~600 lines with imports) |

---

### Phase 2: Scanner + Analyzer Extraction

**Goal:** Extract scanning and analysis functions. `scatter.py` shrinks to ~750 lines (CLI + output + AI only).

#### Step 2.1: Extract `scatter/scanners/type_scanner.py`

- `extract_type_names_from_content()` (depends on `TYPE_DECLARATION_PATTERN` from `core.models`)
- `find_enclosing_type_name()` (standalone)

#### Step 2.2: Extract `scatter/scanners/file_scanner.py`

Thin re-export of `find_files_with_pattern_parallel` with a scanner-style interface.

#### Step 2.3: Extract `scatter/scanners/project_scanner.py`

- `derive_namespace()` (no scatter deps)
- `find_project_file_on_disk()` (no scatter deps)

#### Step 2.4: Extract `scatter/scanners/sproc_scanner.py`

- `find_cs_files_referencing_sproc()` (depends on: `parallel`, `type_scanner`)

#### Step 2.5: Extract `scatter/analyzers/consumer_analyzer.py`

- `find_consumers()` (depends on: `parallel`, `models`)

#### Step 2.6: Extract `scatter/compat/v1_bridge.py`

- `find_solutions_for_project()` (standalone)
- `map_batch_jobs_from_config_repo()` (standalone)
- `_process_consumer_summaries_and_append_results()` (depends on `find_solutions_for_project`)

These are v1-specific result-processing helpers that will be replaced by the reporter system later.

#### Step 2.7: Update `scatter/__init__.py` with new re-exports

#### Testing checkpoint
- `python -m pytest` — all 70 tests pass
- All three CLI modes produce identical output

#### Files changed
| File | Action |
|------|--------|
| `scatter/scanners/type_scanner.py` | Create (2 functions) |
| `scatter/scanners/file_scanner.py` | Create (re-export) |
| `scatter/scanners/project_scanner.py` | Create (2 functions) |
| `scatter/scanners/sproc_scanner.py` | Create (1 function) |
| `scatter/analyzers/consumer_analyzer.py` | Create (1 function) |
| `scatter/compat/v1_bridge.py` | Create (3 functions) |
| `scatter/__init__.py` | Modify (add re-exports) |
| `scatter.py` | Modify (replace ~800 lines with imports) |

---

### Phase 3: Git Analysis + Reporters + CLI Entry Point

**Goal:** Extract git analysis, output formatting, and move `__main__` block. After this, `scatter.py` is a ~10-line thin entry point.

#### Step 3.1: Extract `scatter/analyzers/git_analyzer.py`

- `find_project_file()` (depends on `git` library only)
- `analyze_branch_changes()` (depends on `find_project_file`)
- `get_diff_for_file()` (depends on `git` library only)

#### Step 3.2: Extract reporters from `__main__` block

**`scatter/reports/console_reporter.py`:** Console output formatting
**`scatter/reports/json_reporter.py`:** JSON output formatting
**`scatter/reports/csv_reporter.py`:** CSV output formatting

#### Step 3.3: Move CLI to `scatter/__main__.py`

Move the entire `if __name__ == "__main__":` block into `scatter/__main__.py`. AI functions (`configure_gemini`, `summarize_csharp_file_with_gemini`, `get_affected_symbols_from_diff`) remain in `__main__.py` temporarily until Phase 4.

#### Step 3.4: Reduce `scatter.py` to thin entry point

```python
#!/usr/bin/env python3
"""Scatter - .NET dependency analyzer. CLI entry point for backward compatibility."""
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("scatter", run_name="__main__", alter_sys=True)
```

#### Step 3.5: Update `scatter/__init__.py` with git analyzer re-exports

#### Testing checkpoint
- `python -m pytest` — all 70 tests pass
- `python scatter.py [args]` works (backward compat)
- `python -m scatter [args]` works (new)

#### Files changed
| File | Action |
|------|--------|
| `scatter/analyzers/git_analyzer.py` | Create (3 functions) |
| `scatter/reports/console_reporter.py` | Create |
| `scatter/reports/json_reporter.py` | Create |
| `scatter/reports/csv_reporter.py` | Create |
| `scatter/__main__.py` | Create (~550 lines) |
| `scatter/__init__.py` | Modify |
| `scatter.py` | Replace with thin entry point (~10 lines) |

---

### Phase 4: AI Provider Protocol + Gemini Migration

**Goal:** Define `AIProvider` protocol, migrate Gemini code into provider system, eliminate global `gemini_model`.

#### Step 4.1: Define `scatter/ai/base.py`

```python
from typing import Protocol, Optional, Set, runtime_checkable
from dataclasses import dataclass
from enum import Enum

class AITaskType(Enum):
    SUMMARIZATION = "summarization"
    SYMBOL_EXTRACTION = "symbol_extraction"

@dataclass
class AnalysisResult:
    response: str
    confidence: float = 1.0
    token_usage: Optional[dict] = None
    cost_estimate: Optional[float] = None

@runtime_checkable
class AIProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def max_context_size(self) -> int: ...
    def analyze(self, prompt: str, context: str, task_type: AITaskType) -> AnalysisResult: ...
    def supports(self, task_type: AITaskType) -> bool: ...
    def estimate_tokens(self, context: str) -> int: ...
```

#### Step 4.2: Create `scatter/ai/providers/gemini_provider.py`

Migrate and encapsulate:
- `configure_gemini()` logic (no more global state)
- `summarize_csharp_file_with_gemini()` logic
- `get_affected_symbols_from_diff()` logic

```python
class GeminiProvider:
    def __init__(self, api_key=None, model_name="gemini-1.5-flash"): ...
    def summarize_file(self, code, file_path) -> Optional[str]: ...
    def extract_affected_symbols(self, file_content, diff_text, file_path) -> Optional[Set[str]]: ...
    # ... AIProvider protocol methods ...
```

#### Step 4.3: Update `scatter/__main__.py`

Replace global `gemini_model` + `configure_gemini()` with `GeminiProvider` instance.

#### Step 4.4: Update `scatter/__init__.py`

Add backward-compatible re-exports wrapping the old function signatures around the new provider. Critical for `test_hybrid_git.py` which passes `MagicMock` as `model_instance`.

#### Testing checkpoint
- `python -m pytest` — all 70 tests pass (including 7 hybrid git tests with mock models)
- AI summarization works with real Gemini API key

#### Files changed
| File | Action |
|------|--------|
| `scatter/ai/base.py` | Create (protocol + types) |
| `scatter/ai/providers/gemini_provider.py` | Create (migrated Gemini code) |
| `scatter/__main__.py` | Modify (use GeminiProvider) |
| `scatter/__init__.py` | Modify (AI compat wrappers) |

---

### Phase 5: Configuration System + AI Router

**Goal:** Add `.scatter.yaml` config support and AI task router.

**New dependency:** `pyyaml` added to `requirements.txt`.

#### Step 5.1: Create `scatter/config.py`

```python
@dataclass
class ScatterConfig:
    ai: AIConfig          # default_provider, task_overrides, provider credentials
    budget: BudgetConfig  # max_tokens_per_run, warn_at_tokens, cache_ttl_hours
    max_workers: Optional[int] = None
    chunk_size: Optional[int] = None
    disable_multiprocessing: bool = False

def load_config(config_path=None, cli_overrides=None) -> ScatterConfig:
    """Load from: CLI flags > env vars > .scatter.yaml > ~/.scatter/config.yaml > defaults"""
```

#### Step 5.2: Create `scatter/ai/router.py`

```python
class AIRouter:
    def register_provider(self, provider: AIProvider) -> None: ...
    def analyze(self, prompt, context, task_type) -> Optional[AnalysisResult]: ...
    # Selects provider based on task type + config, with fallback logic
```

#### Step 5.3: Update `requirements.txt`

Add `pyyaml`.

#### Step 5.4: New tests

- `tests/test_config.py` — Config loading, YAML parsing, env var/CLI override priority
- `tests/test_ai_provider.py` — GeminiProvider protocol compliance, AIRouter selection/fallback
- `tests/test_scanners.py` — Each scanner importable and callable independently

#### Testing checkpoint
- `python -m pytest` — all 70 original tests pass + new tests

#### Files changed
| File | Action |
|------|--------|
| `scatter/config.py` | Create |
| `scatter/ai/router.py` | Create |
| `requirements.txt` | Modify (add pyyaml) |
| `tests/test_config.py` | Create |
| `tests/test_ai_provider.py` | Create |
| `tests/test_scanners.py` | Create |

---

## Module Dependency Graph

```
scatter/core/models.py          (no dependencies)
    ^
    |
scatter/core/parallel.py        (depends on: models)
    ^
    |
    +-- scatter/scanners/file_scanner.py      (depends on: parallel)
    +-- scatter/scanners/type_scanner.py      (depends on: models)
    +-- scatter/scanners/project_scanner.py   (no scatter deps)
    +-- scatter/scanners/sproc_scanner.py     (depends on: parallel, type_scanner)
    +-- scatter/analyzers/consumer_analyzer.py (depends on: parallel)
    |
    +-- scatter/analyzers/git_analyzer.py     (no scatter deps, uses gitpython)
    |
    +-- scatter/ai/base.py                   (no dependencies)
    +-- scatter/ai/providers/gemini_provider.py (depends on: base)
    +-- scatter/ai/router.py                 (depends on: base, config)
    |
    +-- scatter/config.py                    (no scatter deps, uses pyyaml)
    |
    +-- scatter/reports/*.py                 (no scatter deps)
    |
    +-- scatter/compat/v1_bridge.py          (depends on: parallel)
    |
    +-- scatter/__main__.py                  (depends on: everything above)
```

Extraction order follows this graph bottom-up: models first, then parallel, then scanners, then analyzers, then AI, then CLI.

---

## Backward Compatibility Strategy

### Import compatibility

All existing test files import from `scatter` using `import scatter` or `from scatter import some_function`. The `scatter/__init__.py` re-exports every public function, so all 70 tests work without modification.

### CLI compatibility

`python scatter.py [args]` continues to work — `scatter.py` delegates to `scatter/__main__.py`. The new `python -m scatter [args]` also works.

### Verification at each phase

After every phase, run:
1. `python -m pytest` (all 70 tests)
2. `python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .`
3. `python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .`

Capture output before starting Phase 1 as baseline for diff comparison.

---

## Risk Mitigation

### Multiprocessing pickle compatibility

Worker functions must remain module-level functions (not class methods or closures) for `ProcessPoolExecutor` to pickle them. Moving them to `scatter.core.parallel` as module-level functions is safe.

### Circular imports

The dependency graph has no cycles. Strict rule: no module in `core/` imports from `scanners/`, `analyzers/`, or `ai/`. No module in `scanners/` imports from `analyzers/`. If a circular dependency is discovered, introduce a new shared module in `core/`.

### Global state (`gemini_model`)

Phase 4 encapsulates it inside `GeminiProvider`. Backward-compat wrappers in `__init__.py` handle tests that pass `MagicMock` model instances.

---

## Post-Refactor File Summary

| File | Lines (approx) | Content |
|------|----------------|---------|
| `scatter.py` | ~10 | Thin entry point |
| `scatter/__init__.py` | ~80 | Re-exports for backward compatibility |
| `scatter/__main__.py` | ~550 | CLI argument parsing + mode dispatch |
| `scatter/config.py` | ~120 | Config loading from YAML/env/CLI |
| `scatter/core/models.py` | ~20 | Constants and regex pattern |
| `scatter/core/parallel.py` | ~500 | All multiprocessing infrastructure |
| `scatter/scanners/type_scanner.py` | ~80 | Type extraction + enclosing type detection |
| `scatter/scanners/file_scanner.py` | ~10 | Re-export of parallel file discovery |
| `scatter/scanners/project_scanner.py` | ~60 | Namespace derivation + project file lookup |
| `scatter/scanners/sproc_scanner.py` | ~150 | Sproc reference detection |
| `scatter/analyzers/consumer_analyzer.py` | ~280 | 5-step consumer detection pipeline |
| `scatter/analyzers/git_analyzer.py` | ~200 | Git branch analysis + diff extraction |
| `scatter/ai/base.py` | ~50 | AIProvider protocol + types |
| `scatter/ai/router.py` | ~60 | Task routing + provider selection |
| `scatter/ai/providers/gemini_provider.py` | ~120 | Migrated Gemini integration |
| `scatter/reports/console_reporter.py` | ~40 | Console output formatting |
| `scatter/reports/json_reporter.py` | ~30 | JSON output formatting |
| `scatter/reports/csv_reporter.py` | ~30 | CSV output formatting |
| `scatter/compat/v1_bridge.py` | ~120 | Pipeline mapping + result processing |

**Total: ~2,500 lines** across ~19 files (vs 2,357 in one file). Small increase from import statements, module docstrings, and the `__init__.py` re-export layer.
