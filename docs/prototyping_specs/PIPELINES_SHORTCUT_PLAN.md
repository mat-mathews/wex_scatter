# Pipelines Shortcut — Implementation Plan

## Context

Release managers need "which pipelines do I run tonight?" — not a full impact report. Today, pipeline names are buried inside consumer results (legacy: `PipelineName` field per result dict; impact: `EnrichedConsumer.pipeline_name`). The JSON reporter already computes `pipeline_summary` (sorted unique list), but there's no way to get just that list from the CLI.

Goal: `scatter --branch-name feature/X --repo-path . --pipeline-csv mapping.csv --output-format pipelines` prints one pipeline name per line to stdout, nothing else. Pipe-friendly for deployment scripts.

## Approach: `--output-format pipelines`

Add `pipelines` as a new output format choice. No subcommand, no new flags — fits cleanly into the existing dispatch pattern.

### Behavior
- Prints sorted unique pipeline names to **stdout**, one per line, no headers/decoration
- Works in **legacy modes** (git, target, sproc) and **impact mode** (sow)
- **Graph mode**: error + exit at argument validation time (before any graph work)
- `--output-file`: if provided, writes to file instead of stdout (same as markdown's dual behavior)
- No results or no `--pipeline-csv`: prints nothing (empty output, exit 0) with a `logging.warning` to stderr so users who forget the flag get a hint
- Suppresses the "Analysis complete..." footer line when format is `pipelines`

## Files to Modify

| File | Change |
|------|--------|
| `scatter/__main__.py` | Add `'pipelines'` to choices, early validation for graph mode, dispatch blocks in legacy + impact, suppress footer |
| `scatter/reports/pipeline_reporter.py` | **NEW** — `extract_pipeline_names()`, `extract_impact_pipeline_names()`, `write_pipeline_report()` |
| `test_pipeline_reporter.py` | **NEW** — ~14 tests |

## Step 1: Create `scatter/reports/pipeline_reporter.py`

Three functions. No `format_pipeline_output()` wrapper — `'\n'.join()` is a one-liner, not worth a function.

```python
from pathlib import Path
from typing import Dict, List

def extract_pipeline_names(all_results: List[Dict]) -> List[str]:
    """Extract sorted unique pipeline names from legacy result dicts.

    Works directly on raw all_results — no need for prepare_detailed_results().
    """
    return sorted(set(
        item['PipelineName']
        for item in all_results
        if item.get('PipelineName')
    ))


def extract_impact_pipeline_names(impact_report) -> List[str]:
    """Extract sorted unique pipeline names from ImpactReport.

    EnrichedConsumer.pipeline_name defaults to "" (not None),
    so filter on truthiness to exclude both.
    """
    return sorted(set(
        c.pipeline_name
        for t in impact_report.targets
        for c in t.consumers
        if c.pipeline_name
    ))


def write_pipeline_report(pipeline_names: List[str], output_path: Path) -> None:
    """Write pipeline list to file, one per line.

    Empty list writes an empty file (no trailing newline).
    Non-empty list ends with a trailing newline for POSIX compliance.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = '\n'.join(pipeline_names) + '\n' if pipeline_names else ''
    output_path.write_text(content, encoding='utf-8')
```

## Step 2: Wire into `scatter/__main__.py`

### 2a. Add to choices (line 308)
```python
choices=['console', 'csv', 'json', 'markdown', 'pipelines'],
help="Format for the output. 'console' prints to screen. 'csv', 'json', or 'markdown' writes to --output-file (markdown also prints to stdout if no file given). 'pipelines' prints unique pipeline names to stdout (one per line, for scripting)."
```

### 2b. Early validation — reject `--graph --output-format pipelines`

After argument parsing, before any analysis work begins (near the existing validation block where modes are checked), add:

```python
if args.graph and args.output_format == 'pipelines':
    parser.error("Pipeline output format is not supported in graph mode.")
```

This prevents building the entire graph + metrics + domain analysis just to error at the end.

### 2c. Legacy dispatch (after the markdown `elif`, before the `else:` console block)

```python
elif args.output_format == 'pipelines':
    from scatter.reports.pipeline_reporter import extract_pipeline_names, write_pipeline_report
    names = extract_pipeline_names(all_results)
    if not names:
        logging.warning("No pipeline names found. Did you provide --pipeline-csv?")
    if args.output_file:
        write_pipeline_report(names, Path(args.output_file))
    elif names:
        print('\n'.join(names))
```

Note: operates on raw `all_results` directly — no `prepare_detailed_results()` call needed since we only read the `PipelineName` field.

### 2d. Impact dispatch (after the markdown `elif`, before the `else:` console block)

```python
elif args.output_format == 'pipelines':
    from scatter.reports.pipeline_reporter import extract_impact_pipeline_names, write_pipeline_report
    names = extract_impact_pipeline_names(impact_report)
    if not names:
        logging.warning("No pipeline names found. Did you provide --pipeline-csv?")
    if args.output_file:
        write_pipeline_report(names, Path(args.output_file))
    elif names:
        print('\n'.join(names))
```

### 2e. Suppress footer

The "Analysis complete..." print statements (lines ~913 and ~1067) should be skipped when `output_format == 'pipelines'` to keep stdout clean for piping:

```python
if args.output_format != 'pipelines':
    print(f"\nAnalysis complete. ...")
```

## Step 3: Tests — `test_pipeline_reporter.py`

### TestExtractPipelineNames (~5)
- `test_extracts_unique_sorted`: 4 results with 3 pipelines (1 duplicate) -> sorted list of 3
- `test_empty_results`: [] -> []
- `test_no_pipeline_field`: results without PipelineName key -> []
- `test_skips_none_values`: results with PipelineName=None -> []
- `test_skips_empty_string`: results with PipelineName="" -> []

### TestExtractImpactPipelineNames (~4)
- `test_extracts_from_consumers`: 2 targets x 2 consumers -> unique sorted pipelines
- `test_skips_empty_string`: consumers with pipeline_name="" (the default) -> excluded
- `test_skips_none`: consumers with pipeline_name=None -> excluded
- `test_no_consumers`: targets with empty consumer lists -> []

### TestWritePipelineReport (~3)
- `test_writes_file_with_trailing_newline`: ["a", "b"] -> "a\nb\n" in file
- `test_empty_list_writes_empty_file`: [] -> empty file
- `test_creates_parent_dirs`: non-existent parent dir -> dirs created, file written

### TestPipelineOutputIntegration (~2)
- `test_legacy_pipeline_output` (capsys): build mock all_results with PipelineName, call the dispatch logic, verify stdout has one name per line
- `test_graph_mode_rejected`: verify parser.error when --graph + --output-format pipelines

**Total: ~14 tests**

## Implementation Order

1. Create `scatter/reports/pipeline_reporter.py` (no deps on __main__ changes)
2. Modify `scatter/__main__.py` (choices, early validation, 2 dispatch blocks, footer suppression)
3. Create `test_pipeline_reporter.py`
4. Run full test suite

## Verification

```bash
# Unit tests
python -m pytest test_pipeline_reporter.py -v

# Full regression
python -m pytest --tb=short

# Manual smoke tests:
# Legacy mode — prints pipeline names only
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines

# Impact mode
python -m scatter --sow "Modify PortalDataService" \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines --google-api-key $KEY

# Graph mode — should error immediately (no graph built)
python -m scatter --graph --search-scope . --output-format pipelines

# File output
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines --output-file pipelines.txt
cat pipelines.txt

# Pipe test
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines | wc -l

# No --pipeline-csv — should warn on stderr, print nothing to stdout
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format pipelines
```
