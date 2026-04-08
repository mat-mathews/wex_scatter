# Initiative 6 Phase 1: Report Quality Fixes

## Context

The existing reporters have correctness/DX issues identified in `docs/OUTPUT_REPORT_EVALUATION.md`:
- JSON output stringifies `ConsumerFileSummaries` (dict→JSON string) and `ConsumingSolutions` (list→comma string) instead of passing native types
- Empty optional fields use `""` instead of `null`
- No metadata (version, timestamp, duration) in any JSON output
- Console says "done." with no useful summary
- `Type/Level: N/A (Project Reference)` shown when there's no class filter
- Legacy CSV includes a `ConsumerFileSummaries` column that's JSON-in-CSV (unusable in spreadsheets)
- Impact CSV uses commas inside list fields, colliding with the CSV delimiter

## Files to Modify

| File | Changes |
|------|---------|
| `scatter/__version__.py` (NEW) | Version constant `"2.1.0"` |
| `scatter/__init__.py` | Re-export `__version__` |
| `scatter/reports/json_reporter.py` | Fix serialization (1a), add metadata param (1b) |
| `scatter/reports/console_reporter.py` | Suppress N/A type line, add per-target count (1c) |
| `scatter/reports/csv_reporter.py` | Drop summaries column, semicolon list delimiters, handle native types (1d) |
| `scatter/reports/graph_reporter.py` | Add metadata param to `build_graph_json` + `write_graph_json_report` (1b) |
| `scatter/compat/v1_bridge.py` | Change `""` → `None` for PipelineName/BatchJobVerification defaults (1a) |
| `scatter/__main__.py` | Capture start time, build metadata dict, informative completion messages (1b, 1c) |
| `test_report_quality.py` (NEW) | ~19 tests for all 1a-1d changes |

## Step 1a: JSON Serialization Fixes

### `scatter/reports/json_reporter.py` — `prepare_detailed_results()`

Replace the stringification with pass-through of native types:

```python
def prepare_detailed_results(all_results):
    detailed_results = []
    for item in all_results:
        detailed_results.append({
            **item,
            'ConsumingSolutions': item.get('ConsumingSolutions', []),
            'ConsumerFileSummaries': item.get('ConsumerFileSummaries', {}),
            'PipelineName': item.get('PipelineName') or None,
            'BatchJobVerification': item.get('BatchJobVerification') or None,
        })
    return detailed_results
```

### `scatter/compat/v1_bridge.py` — origin of empty-string defaults

- Line 115: `batch_job_verification = ""` → `None`
- Line 143: `'PipelineName': ''` → `None`
- Line 144: `'BatchJobVerification': ''` → `None`

## Step 1b: Report Metadata

### New `scatter/__version__.py`

Single constant: `__version__ = "2.1.0"`

### `scatter/__init__.py`

Add `from scatter.__version__ import __version__` to imports.

### `scatter/__main__.py`

- Add `import time` + `from datetime import datetime, timezone` to imports
- `start_time = time.monotonic()` at top of `main()`
- New `_build_metadata(args, search_scope_abs, start_time)` helper returning dict with: `scatter_version`, `timestamp`, `cli_args`, `search_scope`, `duration_seconds`
- Pass `metadata=_build_metadata(...)` to all three JSON writer calls

### `scatter/reports/json_reporter.py`

- `write_json_report()`: add optional `metadata` param; conditionally include at top of output dict
- `write_impact_json_report()`: same; wrap `asdict(report)` with metadata

### `scatter/reports/graph_reporter.py`

- `build_graph_json()`: add optional `metadata` param; conditionally include
- `write_graph_json_report()`: add `metadata` param; pass through

## Step 1c: Console Polish

### `scatter/reports/console_reporter.py`

- Pre-compute `target_counts = Counter(item['TargetProjectName'] for item in all_results)`
- Target header includes count: `Target: Name (path) (4 consumer(s))`
- Only show `Type/Level:` when TriggeringType does NOT contain "N/A"

### `scatter/__main__.py` — replace `print("\ndone.\n")` x3

- Impact (line 715): `Analysis complete. {consumer_count} consumer(s) found across {target_count} target(s).`
- Graph (line 794): `Analysis complete. {node_count} projects, {edge_count} dependencies, {cycle_count} cycle(s).`
- Legacy (line 826): `Analysis complete. {len(all_results)} consumer(s) found across {len(target_names)} target(s).`

## Step 1d: CSV Cleanup

### `scatter/reports/csv_reporter.py`

**`write_csv_report()` (legacy):**
- Remove `ConsumerFileSummaries` from fieldnames
- Add `extrasaction='ignore'` to DictWriter
- Stringify native types for CSV: `'; '.join()` for lists, `''` for `None`

**`write_impact_csv_report()`:**
- Change `', '` → `'; '` in Solutions and CouplingVectors joins

## Step 1e: Tests — `test_report_quality.py` (NEW, ~19 tests)

**TestJsonSerializationFixes** (~6): ConsumingSolutions stays list, ConsumerFileSummaries stays dict, empty fields → None, populated fields preserved, full JSON roundtrip

**TestMetadata** (~5): legacy/impact/graph JSON includes metadata when provided, omits when None, all 5 keys present

**TestConsolePolish** (~3): N/A type suppressed, real type shown, per-target count in output

**TestCsvCleanup** (~4): legacy CSV omits summaries column, has 8 columns, impact CSV semicolons in Solutions and CouplingVectors

## Verification

```bash
python -m pytest test_report_quality.py -v
python -m pytest test_impact_analysis.py -v -k "Reporter or Csv or Json"
python -m pytest --tb=short   # full suite
```
