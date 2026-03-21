# ConsumerResult Dataclass — Implementation Plan

**Branch:** feature/consumer-result-dataclass
**Initiative:** 7 Phase 1 (Leadership Review findings)
**Estimated effort:** 1 day
**Depends on:** Nothing
**Ref:** docs/LEADERSHIP_DESIGN_REVIEW.md
**Team review:** 2026-03-21 (Priya, Marcus, Tomás, Sam, Anya, Devon, Fatima, Jake, Kai)

---

## Problem

The consumer analysis pipeline passes results as `Dict[str, Union[str, Dict, List[str]]]`.
This untyped dict flows through 10+ files — 7 reporters, v1_bridge, cli.py,
graph_enrichment, and impact_analyzer. Keys are string literals like
`result["ConsumerProjectName"]`. No IDE autocompletion, no type checking,
no compile-time safety.

Every time we add a field (graph metrics, solutions, alignment) we touch 5-7
reporters and hope we spelled the key right. A typo silently produces `None`
from `.get()` and nobody notices until a user reports missing data.

---

## Solution

Replace the untyped dict with a `ConsumerResult` dataclass in
`scatter/core/models.py`. All reporters and enrichment functions consume
the typed object instead of string-keyed dicts.

---

## Field Inventory (14 fields)

Two dict shapes exist in the codebase:

### Shape 1: Raw consumer dicts from `find_consumers()`

Used by `impact_analyzer.py` and `cli.py` before the bridge function.

| Field | Type | Source |
|-------|------|--------|
| `consumer_path` | `Path` | consumer_analyzer.py |
| `consumer_name` | `str` | consumer_analyzer.py |
| `relevant_files` | `List[Path]` | consumer_analyzer.py |

These stay as-is — 3 fields, 2 callsites, not worth the ceremony (Tomás).
`find_consumers()` return type is unchanged.

### Shape 2: Enriched result dicts from `_process_consumer_summaries_and_append_results()`

This is what gets replaced with `ConsumerResult`.

| Field | Type | Source | Always present |
|-------|------|--------|----------------|
| `target_project_name` | `str` | v1_bridge | Yes |
| `target_project_path` | `str` | v1_bridge | Yes |
| `triggering_type` | `str` | v1_bridge | Yes |
| `consumer_project_name` | `str` | v1_bridge | Yes |
| `consumer_project_path` | `str` | v1_bridge | Yes |
| `consuming_solutions` | `List[str]` | v1_bridge | Yes (may be empty) |
| `pipeline_name` | `Optional[str]` | v1_bridge | Yes (None if no mapping) |
| `batch_job_verification` | `Optional[str]` | v1_bridge | Yes (None if no mapping) |
| `consumer_file_summaries` | `Dict[str, str]` | cli.py | Yes (empty dict default) |
| `coupling_score` | `Optional[float]` | graph_enrichment | No (graph-dependent) |
| `fan_in` | `Optional[int]` | graph_enrichment | No |
| `fan_out` | `Optional[int]` | graph_enrichment | No |
| `instability` | `Optional[float]` | graph_enrichment | No |
| `in_cycle` | `Optional[bool]` | graph_enrichment | No |

### Naming convention

Current dict keys use PascalCase (`ConsumerProjectName`). The dataclass uses
snake_case to match Python conventions and every other dataclass in scatter.
Reporter output keys stay PascalCase for backward compatibility in JSON/CSV.

---

## Deliverables

### 1. `ConsumerResult` dataclass in `scatter/core/models.py`

```python
@dataclass
class ConsumerResult:
    """A consuming relationship between a target and consumer project."""
    target_project_name: str
    target_project_path: str
    triggering_type: str
    consumer_project_name: str
    consumer_project_path: str
    consuming_solutions: List[str] = field(default_factory=list)
    pipeline_name: Optional[str] = None
    batch_job_verification: Optional[str] = None
    consumer_file_summaries: Dict[str, str] = field(default_factory=dict)
    # Graph enrichment fields (optional)
    coupling_score: Optional[float] = None
    fan_in: Optional[int] = None
    fan_out: Optional[int] = None
    instability: Optional[float] = None
    in_cycle: Optional[bool] = None
```

No `to_dict()` method — reporters map fields to output keys explicitly (Marcus,
Tomás). Each reporter owns its output schema; the dataclass owns its data model.
Clean separation.

### 2. Update `v1_bridge._process_consumer_summaries_and_append_results()`

Change from appending dicts to `List[Dict]` to appending `ConsumerResult`
objects to `List[ConsumerResult]`. This is the single construction point —
all downstream code receives typed objects.

### 3. Update `graph_enrichment.enrich_legacy_results()`

Change from `result["CouplingScore"] = ...` to `result.coupling_score = ...`.
Type signature changes from `List[Dict]` to `List[ConsumerResult]`.

### 4. Update `cli.py`

- `_summarize_consumer_files()`: access `result.consumer_project_path` and
  `result.consumer_file_summaries` instead of `result["ConsumerProjectPath"]`
- `dispatch_legacy_output()`: pass `List[ConsumerResult]` to reporters
- Type annotations on `all_results` variables

### 5. Update all 5 reporters

Each reporter changes from `result["KeyName"]` to `result.field_name`.
Reporters explicitly map field names to PascalCase output keys — no
`to_dict()`, no `dataclasses.asdict()` (Kai: that would produce snake_case
and break downstream consumers).

| Reporter | Access pattern change |
|----------|----------------------|
| `console_reporter.py` | `r["ConsumerProjectName"]` → `r.consumer_project_name` |
| `json_reporter.py` | Same + explicit PascalCase mapping in output dict |
| `csv_reporter.py` | Same + PascalCase CSV headers preserved |
| `markdown_reporter.py` | Same |
| `pipeline_reporter.py` | `r["PipelineName"]` → `r.pipeline_name` |

---

## Migration Strategy

The migration is mechanical — find every `result["KeyName"]` and replace with
`result.field_name`. The complete list of callsites from the inventory:

| File | Accesses | Count |
|------|----------|-------|
| `console_reporter.py` | 11 keys | ~15 sites |
| `json_reporter.py` | 9 keys | ~10 sites |
| `csv_reporter.py` | 8 keys | ~10 sites |
| `markdown_reporter.py` | 10 keys | ~12 sites |
| `pipeline_reporter.py` | 1 key | 1 site |
| `graph_enrichment.py` | 6 keys | ~6 sites |
| `cli.py` | 2 keys | ~3 sites |
| `v1_bridge.py` | construction | 1 site |
| **Total** | | **~58 sites** |

### Approach

1. Add `ConsumerResult` to `models.py`
2. Add `make_consumer_result` factory fixture to `conftest.py` (Anya)
3. Update `v1_bridge` to construct `ConsumerResult` instead of dict
4. Update `graph_enrichment` to set attributes instead of dict keys
5. Update `cli.py` access patterns
6. Update each reporter one at a time, running tests after each
7. Update test fixtures from dict construction to `make_consumer_result`
8. Update type annotations throughout

---

## Tests

### New tests

| Test | What it validates |
|------|-------------------|
| `test_consumer_result_defaults` | Optional fields default correctly |
| `test_consumer_result_graph_fields` | Graph enrichment fields set correctly |
| `test_bridge_produces_consumer_result` | v1_bridge returns ConsumerResult, not dict |
| `test_enrichment_sets_attributes` | graph_enrichment sets typed attributes |
| `test_json_output_schema_contract` | JSON output contains exact PascalCase keys (Marcus, Fatima) |
| `test_csv_headers_pascal_case` | CSV headers match legacy PascalCase schema |

### Test fixture migration

Tests that construct result dicts manually (in `test_report_quality.py`,
`test_filter_pipeline.py`, `test_markdown_reporter.py`, etc.) need to use
the `make_consumer_result` factory fixture instead (Anya, Tomás):

```python
# conftest.py
@pytest.fixture
def make_consumer_result():
    def _factory(**overrides):
        defaults = dict(
            target_project_name="TargetProject",
            target_project_path="TargetProject/TargetProject.csproj",
            triggering_type="SomeClass",
            consumer_project_name="ConsumerProject",
            consumer_project_path="ConsumerProject/ConsumerProject.csproj",
        )
        defaults.update(overrides)
        return ConsumerResult(**defaults)
    return _factory
```

### Existing tests

All 788 existing tests must pass. They exercise the full pipeline end-to-end
and will catch any missed migration site as an `AttributeError`.

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| No `to_dict()` method | Reporters own their output schema. No shared serialization method that becomes a dumping ground. | Marcus, Tomás |
| Raw consumer dicts stay untyped | 3 fields, 2 callsites. Not worth the ceremony. | Tomás, Priya |
| No `dataclasses.asdict()` for JSON | Would produce snake_case keys, breaking downstream consumers. Reporters map explicitly. | Kai, Marcus |
| `make_consumer_result` factory in conftest | Single place to update when fields change. All tests use it. | Anya, Tomás |
| JSON schema contract test | Assert exact PascalCase key names in output. Our contract with downstream consumers. | Marcus, Fatima |
| `triggering_type` naming kept | Fine as-is with docstring. Not worth the bikeshed. | Priya |

---

## Files Changed

| File | Change |
|------|--------|
| `scatter/core/models.py` | Add ConsumerResult dataclass |
| `scatter/compat/v1_bridge.py` | Construct ConsumerResult instead of dict |
| `scatter/analyzers/graph_enrichment.py` | Set attributes instead of dict keys |
| `scatter/cli.py` | Update access patterns + type annotations |
| `scatter/reports/console_reporter.py` | `r["Key"]` → `r.field` |
| `scatter/reports/json_reporter.py` | `r["Key"]` → `r.field` + explicit PascalCase mapping |
| `scatter/reports/csv_reporter.py` | `r["Key"]` → `r.field` + PascalCase headers |
| `scatter/reports/markdown_reporter.py` | `r["Key"]` → `r.field` |
| `scatter/reports/pipeline_reporter.py` | `r["Key"]` → `r.field` |
| `scatter/__init__.py` | Export ConsumerResult |
| `conftest.py` | Add `make_consumer_result` factory fixture |
| Test files | Migrate dict construction to factory fixture |

---

## What This Does NOT Change

- `find_consumers()` return type — stays `List[Dict]` (raw consumer dicts are
  a different shape, used only internally before the bridge)
- JSON/CSV output key names — stay PascalCase for downstream consumers
- `EnrichedConsumer` (impact mode) — separate dataclass, already typed
- No new CLI flags

---

## Risk

**Medium — mechanical but wide.** ~58 access sites across 8 files. The risk is
a missed migration site that compiles fine (Python doesn't check attribute
access at import time) but fails at runtime.

Mitigation:
1. 788 existing tests exercise the full pipeline — any missed site triggers
   an `AttributeError` in tests
2. Migrate one reporter at a time, run tests after each
3. JSON schema contract test explicitly asserts output key names
4. `make_consumer_result` factory prevents test fixtures from drifting
