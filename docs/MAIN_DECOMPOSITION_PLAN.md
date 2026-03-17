# Decompose `scatter/__main__.py` (1,161 lines)

## Context

`scatter/__main__.py` has a ~960-line `main()` function containing 5 mode branches in a giant if/elif chain, repeated graph enrichment patterns, and output dispatch logic in 3 places. The team reviewed it and agreed on decomposition into testable, focused units. Impact and graph modes are already well-factored (delegating to `run_impact_analysis()` and `build_dependency_graph()` respectively). The three legacy modes (git, target, sproc) are not — they contain inline orchestration that follows identical patterns but is copy-pasted across branches.

## Team Review Decisions

The following amendments were approved by leadership (Priya + Marcus) after full team review:

1. **No raw `args` on the context object.** Mode handlers receive resolved, typed fields — not `argparse.Namespace`. `args` stays in `main()` for `parser.error()` and mode detection but does not leak into handlers.

2. **Result is a dataclass, not a bare tuple.** Use `ModeResult` with named fields instead of `Tuple[List[Dict], Optional[FilterPipeline], bool]`.

3. **Each step includes smoke tests** for the extracted function. Testability was a stated goal.

4. **Parser goes in its own file** (`scatter/cli_parser.py`), separate from mode orchestration (`scatter/cli.py`). Three files with clear single responsibilities.

5. **Document `graph_ctx` mutation explicitly.** `_apply_graph_enrichment` mutates `ctx.graph_ctx` and `ctx.graph_enriched` in place.

6. **Step 3 is a prerequisite for steps 4 and 5** (it moves shared helpers `_summarize_consumer_files` and `_ensure_graph_context` to `cli.py`).

### Out of scope (flagged as follow-ups)

- Extract input validation from `main()` into `validate_inputs()`
- Extract impact/graph inline blocks to one-line dispatches
- Migrate legacy `List[Dict]` results to typed dataclasses

---

## File layout after

```
scatter/
  __main__.py       ~250 lines  (entry point: parse, validate, dispatch)
  cli_parser.py     ~180 lines  (build_parser, _build_cli_overrides, _REDACTED_CLI_KEYS)
  cli.py            ~450 lines  (ModeContext, ModeResult, 3 mode handlers,
                                  dispatch_legacy_output, _build_metadata,
                                  _require_output_file, _summarize_consumer_files,
                                  _ensure_graph_context, _apply_graph_enrichment)
  # everything else unchanged
```

## Shared Context

Mode handlers receive resolved typed fields, not raw `args`:

```python
@dataclass
class ModeContext:
    search_scope: Path
    config: ScatterConfig
    pipeline_map: Dict[str, str]
    solution_file_cache: List[Path]
    batch_job_map: Dict[str, List[str]]
    ai_provider: Optional[Any]
    graph_ctx: Optional[GraphContext]   # mutable — updated by _apply_graph_enrichment
    graph_enriched: bool                # mutable — updated by _apply_graph_enrichment

    # Resolved from args — only fields mode handlers actually read
    class_name: Optional[str]
    method_name: Optional[str]
    target_namespace: Optional[str]
    summarize_consumers: bool
    max_workers: int
    chunk_size: int
    disable_multiprocessing: bool
    cs_analysis_chunk_size: int
    csproj_analysis_chunk_size: int
    no_graph: bool
```

## Return type

```python
@dataclass
class ModeResult:
    all_results: List[Dict]
    filter_pipeline: Optional[FilterPipeline]
    graph_enriched: bool
```

---

## Steps

### Step 1: Extract `build_parser()` into `scatter/cli_parser.py`

Create `scatter/cli_parser.py` with:
- `build_parser() -> argparse.ArgumentParser` (current lines 204-364)
- `_build_cli_overrides(args) -> Dict[str, Any]` (current lines 131-151)
- `_REDACTED_CLI_KEYS` constant

`__main__.py` imports `build_parser` and `_build_cli_overrides` from `cli_parser`.

**Tests:** Assert parser returns expected attributes for known arg combinations.

**Verify:** `python -m scatter --help` output identical. `python -m pytest -x`.

### Step 2: Extract `dispatch_legacy_output()` into `scatter/cli.py`

Create `scatter/cli.py` with:
- `dispatch_legacy_output(all_results, filter_pipeline, args, search_scope, start_time, graph_enriched) -> None` (current lines 1100-1158)
- `_build_metadata(args, search_scope, start_time, *, graph_enriched) -> Dict` (current lines 181-191)
- `_require_output_file(args, format_name) -> Path` (current lines 194-199)

**Tests:** Mock reporters, verify correct reporter called per output format.

**Verify:** Target mode with each `--output-format`, diff outputs. `python -m pytest -x`.

### Step 3: Extract `run_target_analysis()` + shared helpers

Add to `scatter/cli.py`:
- `ModeContext` dataclass
- `ModeResult` dataclass
- `_summarize_consumer_files()` (current lines 40-128)
- `_ensure_graph_context()` (current lines 157-178)
- `run_target_analysis(ctx: ModeContext, target_csproj: Path) -> ModeResult` (current lines 731-798)

This is the simplest legacy mode — single `find_consumers` call, no loops.

**Tests:** Mock `find_consumers`, verify `ModeResult` shape and that v1_bridge is called correctly.

**Verify:** `python -m scatter --target-project ./GalaxyWorks.Data --search-scope .` and `python -m pytest -x`.

**Note:** Steps 4 and 5 depend on this step (shared helpers land here).

### Step 4: Extract `run_sproc_analysis()` (depends on step 3)

Add to `scatter/cli.py`:
- `run_sproc_analysis(ctx: ModeContext, sproc_name: str, sproc_regex: Optional[str]) -> ModeResult`

Loops over `project_class_sproc_map`, calls `find_consumers` per class, accumulates results, enriches.

**Tests:** Mock `find_cs_files_referencing_sproc` + `find_consumers`, verify accumulation across classes.

**Verify:** `python -m scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .` and `python -m pytest -x`.

### Step 5: Extract `run_git_analysis()` (depends on step 3)

Add to `scatter/cli.py`:
- `run_git_analysis(ctx: ModeContext, repo_path: Path, branch_name: str, base_branch: str, enable_hybrid: bool) -> ModeResult`

Most complex legacy mode — nested loops (projects x types), hybrid AI extraction, per-type consumer finding. Extract without refactoring internals. If this gets hairy, split into 5a (extract with `args` temporarily) and 5b (resolve to typed fields).

**Tests:** Mock `analyze_branch_changes` + `find_consumers`, verify multi-project/multi-type accumulation.

**Verify:** `python -m scatter --branch-name main --repo-path . --base-branch main` and `python -m pytest -x`.

### Step 6: Consolidate graph enrichment (depends on steps 3-5)

Replace 3x repeated `_ensure_graph_context` + `enrich_legacy_results` with:

```python
def _apply_graph_enrichment(all_results: List[Dict], ctx: ModeContext) -> None:
    """Build graph context if needed, enrich results in place.

    Mutates ctx.graph_ctx and ctx.graph_enriched.
    """
```

Each mode handler calls this once at the end, before returning.

**Tests:** Verify graph_ctx mutation, verify enrichment fields appear in results.

**Verify:** `--graph-metrics` produces identical JSON output. `python -m pytest -x`.

### Step 7: Clean up `main()` (depends on all previous)

After all extractions, `main()` becomes ~200-250 lines:

```python
def main():
    start_time = time.monotonic()
    parser = build_parser()
    args = parser.parse_args()
    # ~15 lines: logging setup + mode flags
    # ~5 lines: config + AI provider setup
    # ~60 lines: input validation (paths, search scope — stays here, uses parser.error())
    # ~30 lines: cache precomputation (sln files, batch jobs, pipeline CSV)
    # ~5 lines: build ModeContext from resolved values
    # ~10 lines: graph context pre-load

    if is_git_mode:
        result = run_git_analysis(ctx, repo_path_abs, args.branch_name, ...)
    elif is_target_mode:
        result = run_target_analysis(ctx, target_csproj_abs_path)
    elif is_sproc_mode:
        result = run_sproc_analysis(ctx, args.stored_procedure, ...)
    elif is_impact_mode:
        # ~30 lines inline (already well-factored, own output path, early return)
    elif is_graph_mode:
        # ~40 lines inline (already well-factored, own output path, early return)

    dispatch_legacy_output(result.all_results, result.filter_pipeline, ...)
```

**Verify:** `python -m pytest -x` (full suite green).

---

## Sequencing and risk

| Step | Risk | Depends on | Notes |
|------|------|-----------|-------|
| 1 (parser) | Near-zero | — | Pure declaration extraction |
| 2 (output dispatch) | Low | — | Pure extraction |
| 3 (target mode) | Low | — | Simplest mode; also lands shared helpers |
| 4 (sproc mode) | Low | 3 | Uses shared helpers from step 3 |
| 5 (git mode) | Medium | 3 | Most complex; split into 5a/5b if needed |
| 6 (graph enrichment) | Low | 3, 4, 5 | Mechanical dedup |
| 7 (cleanup) | Near-zero | all | Wiring only |

Each step = one commit. Steps 1, 2, and 3 can proceed in parallel. Steps 4 and 5 depend on 3 but are independent of each other. Step 6 depends on 3-5. Step 7 depends on all.

**Rollback:** Steps 3, 4, 5 are independently revertible as long as step 6 hasn't landed.

## What NOT to do

- No Mode enum/strategy pattern — 5 `if/elif` branches is fine for 5 modes
- No merging impact/graph output dispatch with legacy — different reporter APIs
- No extracting input validation from `main()` — uses `parser.error()`, out of scope
- No migrating `List[Dict]` to typed dataclasses — separate initiative

## Verification

```bash
python -m pytest -x                    # after every step
python -m scatter --help               # after step 1
python -m scatter --target-project ./GalaxyWorks.Data --search-scope .          # after step 3
python -m scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .  # after step 4
python -m scatter --branch-name main --repo-path . --base-branch main           # after step 5
```

## Critical files

- `scatter/__main__.py` — source being decomposed
- `scatter/cli_parser.py` — new: parser definition
- `scatter/cli.py` — new: mode handlers, output dispatch, shared helpers
- `scatter/analyzers/impact_analyzer.py` — reference pattern for well-factored mode handler
- `scatter/compat/v1_bridge.py` — key dependency (`_process_consumer_summaries_and_append_results`)
- `scatter/core/models.py` — `FilterPipeline` type used in `ModeResult`
- `scatter/analyzers/graph_enrichment.py` — `build_graph_context`, `enrich_legacy_results`
