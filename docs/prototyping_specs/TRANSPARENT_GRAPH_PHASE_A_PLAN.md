# Transparent Graph — Phase A: Auto Graph Loading

## Context

Today, graph enrichment is opt-in via `--graph-metrics`. If you don't pass the flag, results contain no coupling score, fan-in/out, instability, or cycle membership — even when a cached graph sitting in `.scatter/graph_cache.json` could provide them in milliseconds.

Phase A makes graph loading automatic. When a v2 cache exists, scatter loads it, patches it incrementally, and enriches results — no flag needed. The user experience shifts from "remember to add `--graph-metrics`" to "it just works after the first graph build."

Ref: `docs/ADR_TRANSPARENT_GRAPH.md` (Phase A section)

## Behavior Changes

### Before (today)
```bash
# No graph metrics — user has to know the flag exists
scatter --target-project ./Lib/Lib.csproj --search-scope .

# Graph metrics — user must opt in
scatter --target-project ./Lib/Lib.csproj --search-scope . --graph-metrics
```

### After (Phase A)
```bash
# Graph cache exists → auto-enriched, no flag needed
scatter --target-project ./Lib/Lib.csproj --search-scope .

# No cache → same output as today (no graph columns), no side effects
scatter --target-project ./Lib/Lib.csproj --search-scope .

# Explicit opt-out
scatter --target-project ./Lib/Lib.csproj --search-scope . --no-graph

# Force build (even if no cache) — retains today's --graph-metrics semantics
scatter --target-project ./Lib/Lib.csproj --search-scope . --graph-metrics
```

### Key rules
1. **Cache exists → auto-load.** Attempt `build_graph_context()` automatically when search_scope has a `.scatter/graph_cache.json` (or config-specified cache dir).
2. **No cache → no build.** Don't build the graph from scratch just because we can. That's Phase C's job. Phase A is zero-overhead for first-run users.
3. **`--graph-metrics` → eager build.** Retains today's meaning: "I want graph metrics even if there's no cache — build one." This is the bridge from old behavior to new.
4. **`--no-graph` → skip everything.** Escape hatch. Don't load cache, don't enrich. Useful for debugging or when the cache is suspected corrupt.
5. **`--graph` mode unchanged.** Graph-only analysis mode is a separate code path and doesn't change.
6. **`graph_enriched` metadata field.** JSON output includes `"graph_enriched": true/false` so downstream parsers can detect whether graph columns are populated.

### Intentional behavioral note
If `--graph-metrics` is passed but the graph build fails (returns None), `graph_enriched` is False and reporters will not include graph columns. Today, the columns would appear with all-`None` values. The new behavior is an improvement — showing empty columns when the graph failed to build is confusing. Reporters now only include graph columns when enrichment actually succeeded.

## Files to Modify

| File | Change |
|------|--------|
| `scatter/__main__.py` | Add `--no-graph`, change graph loading condition, pass `graph_enriched` to metadata, update `graph_metrics_requested` logic, update `--graph-metrics` help text |
| `scatter/__main__.py` | `_build_metadata()` gains keyword-only `graph_enriched` param (default `False`) |
| `scatter/store/graph_cache.py` | Add `cache_exists()` helper |
| `test_graph_enrichment.py` | ~9 new tests for auto-loading behavior |
| `test_graph_cache.py` | ~2 new tests for `cache_exists()` |

## Step 1: Add `cache_exists()` to `scatter/store/graph_cache.py`

Quick predicate — avoids importing the full load machinery just to check.

```python
def cache_exists(search_scope: Path, config_cache_dir: Optional[str] = None) -> bool:
    """Check if a graph cache file exists for the given scope."""
    if config_cache_dir:
        path = Path(config_cache_dir) / "graph_cache.json"
    else:
        path = get_default_cache_path(search_scope)
    return path.is_file()
```

## Step 2: Add `--no-graph` flag and update `--graph-metrics` help text in `scatter/__main__.py`

After the existing `--graph-metrics` argument (line ~248):

```python
common_group.add_argument(
    "--no-graph", action="store_true",
    help="Skip automatic graph loading and enrichment, even when a cache exists."
)
```

Update `--graph-metrics` help text:

```python
"--graph-metrics", action="store_true",
help="Build dependency graph and enrich results with graph metrics (coupling, fan-in/out, instability, cycles). "
     "When a graph cache already exists, enrichment happens automatically without this flag."
```

## Step 3: Change graph loading condition in `scatter/__main__.py`

### Current (line 524-534):
```python
# Build graph context lazily if --graph-metrics requested
graph_ctx = None
if args.graph_metrics and search_scope_abs:
    ...
    graph_ctx = build_graph_context(search_scope_abs, config, args)
```

### New:
```python
# Build graph context: auto-load from cache, or build if --graph-metrics requested.
# Scope mismatch or corrupt cache → build_graph_context() returns None silently,
# which is expected — auto-load is best-effort, not guaranteed.
graph_ctx = None
graph_enriched = False
if not args.no_graph and search_scope_abs and not is_graph_mode:
    from scatter.store.graph_cache import cache_exists
    should_load_graph = args.graph_metrics or cache_exists(
        search_scope_abs, config.graph.cache_dir
    )
    if should_load_graph:
        from scatter.analyzers.graph_enrichment import (
            build_graph_context,
            enrich_legacy_results,
            enrich_consumers,
        )
        graph_ctx = build_graph_context(search_scope_abs, config, args)
        if graph_ctx:
            graph_enriched = True
        elif args.graph_metrics:
            # Only warn if user explicitly asked for metrics
            logging.warning("Graph context unavailable. Proceeding without graph metrics.")
```

Key changes:
- `cache_exists()` check added alongside `args.graph_metrics`
- `graph_enriched` boolean tracks whether enrichment actually happened
- Warning only fires when user explicitly asked (not on silent auto-load failure)
- `is_graph_mode` excluded — `--graph` has its own path
- `--no-graph` is the escape hatch

### Impact mode enrichment (line ~883)

Currently gated on `args.graph_metrics`. Change to use the already-loaded `graph_ctx`:

```python
# Current:
if args.graph_metrics and search_scope_abs:
    if graph_ctx is None:
        ...
        graph_ctx = build_graph_context(search_scope_abs, config, args)
    if graph_ctx:
        for ti in impact_report.targets:
            enrich_consumers(ti.consumers, graph_ctx)

# New:
if graph_ctx:
    for ti in impact_report.targets:
        enrich_consumers(ti.consumers, graph_ctx)
```

The graph context was already loaded at the top. No need to re-check `args.graph_metrics` or rebuild.

## Step 4: Derive `graph_metrics_requested` from actual enrichment

Currently, `_gm = args.graph_metrics` is used to tell reporters whether to include graph columns. After Phase A, this should reflect whether enrichment actually happened, not just whether the flag was passed.

### Legacy dispatch (line ~1047):
```python
# Current:
_gm = args.graph_metrics

# New:
_gm = graph_enriched
```

### Impact dispatch (line ~895):
```python
# Current:
_gm_impact = args.graph_metrics

# New:
_gm_impact = graph_enriched
```

This means:
- Cache exists + auto-loaded → reporters include graph columns
- No cache + no `--graph-metrics` → reporters exclude graph columns (same as today)
- `--graph-metrics` + build succeeds → reporters include graph columns
- `--graph-metrics` + build fails → reporters exclude graph columns (improvement: no empty columns)
- `--no-graph` → reporters exclude graph columns

## Step 5: Add `graph_enriched` to metadata

### `_build_metadata()` (line 157):

`graph_enriched` is a keyword-only parameter with default `False` to avoid breaking existing callers and tests.

```python
def _build_metadata(args, search_scope_abs, start_time, *, graph_enriched=False):
    cli_args = {k: v for k, v in vars(args).items() if k not in _REDACTED_CLI_KEYS}
    return {
        'scatter_version': __version__,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'cli_args': cli_args,
        'search_scope': str(search_scope_abs) if search_scope_abs else None,
        'duration_seconds': round(time.monotonic() - start_time, 2),
        'graph_enriched': graph_enriched,
    }
```

All call sites pass `graph_enriched=graph_enriched`. There are 7 call sites:
- Impact JSON (line ~899) — `graph_enriched=graph_enriched`
- Impact markdown (line ~906) — `graph_enriched=graph_enriched`
- Graph JSON (line ~1002) — `graph_enriched=True` (graph mode always has graph data)
- Graph markdown (line ~1016) — `graph_enriched=True`
- Legacy JSON (line ~1054) — `graph_enriched=graph_enriched`
- Legacy markdown (line ~1068) — `graph_enriched=graph_enriched`
- Legacy CSV uses `_build_metadata` indirectly — not applicable, no metadata in CSV

## Step 6: Tests

### TestAutoGraphLoading (~9 new tests in `test_graph_enrichment.py`)

All tests mock `cache_exists()` and `build_graph_context()` to avoid real filesystem/graph operations.

#### 6a. `test_auto_loads_when_cache_exists`
- Mock `cache_exists()` → True
- Mock `build_graph_context()` → returns a GraphContext
- Call the graph loading logic with `args.graph_metrics=False`, `args.no_graph=False`
- Assert `build_graph_context` was called
- Assert `graph_enriched` is True

#### 6b. `test_skips_when_no_cache_and_no_flag`
- Mock `cache_exists()` → False
- `args.graph_metrics=False`, `args.no_graph=False`
- Assert `build_graph_context` was NOT called
- Assert `graph_enriched` is False

#### 6c. `test_builds_when_graph_metrics_flag_no_cache`
- Mock `cache_exists()` → False
- `args.graph_metrics=True`, `args.no_graph=False`
- Assert `build_graph_context` was called (flag forces build even without cache)

#### 6d. `test_no_graph_flag_skips_everything`
- Mock `cache_exists()` → True
- `args.no_graph=True`
- Assert `build_graph_context` was NOT called
- Assert `graph_enriched` is False

#### 6e. `test_graph_enriched_in_metadata`
- Build metadata with `graph_enriched=True`
- Assert `metadata['graph_enriched']` is True
- Build metadata with `graph_enriched=False`
- Assert `metadata['graph_enriched']` is False
- Build metadata WITHOUT `graph_enriched` param (test keyword default)
- Assert `metadata['graph_enriched']` is False

#### 6f. `test_silent_failure_on_auto_load`
- Mock `cache_exists()` → True
- Mock `build_graph_context()` → returns None (failure — corrupt cache, scope mismatch, etc.)
- `args.graph_metrics=False` (auto-load, not explicit)
- Assert no WARNING logged (silent failure for auto-load)
- Assert `graph_enriched` is False

#### 6g. `test_impact_mode_auto_enrichment`
- Mock `cache_exists()` → True
- Mock `build_graph_context()` → returns a GraphContext with metrics
- Run impact mode analysis (mocked)
- Assert impact consumers gain graph metric fields (coupling_score, fan_in, etc.)
- Verifies the impact enrichment guard change (`if graph_ctx:` instead of `if args.graph_metrics`)

#### 6h. `test_graph_metrics_flag_builds_without_cache`
- Mock `cache_exists()` → False
- `args.graph_metrics=True`
- Mock `build_graph_context()` → returns GraphContext
- Assert `build_graph_context` was called
- Assert `graph_enriched` is True
- Verifies backwards compat: `--graph-metrics` still forces a full build

#### 6i. `test_json_output_contains_graph_enriched_field`
- Subprocess test (like `test_graph_mode_rejects_pipelines_format`)
- Run scatter with `--output-format json --output-file <tmp>` against sample projects
- Parse JSON output
- Assert `metadata.graph_enriched` field exists and is boolean

### TestCacheExists (~2 new tests in `test_graph_cache.py`)

#### `test_cache_exists_true`
- Create a file at the expected cache path (`tmp_path / ".scatter" / "graph_cache.json"`)
- Assert `cache_exists(tmp_path)` returns True

#### `test_cache_exists_false`
- Empty tmp_path (no `.scatter/` dir)
- Assert `cache_exists(tmp_path)` returns False

**Total: ~11 new tests**

## Backwards Compatibility

### Output schema
- **No cache → identical output.** First-run users see exactly the same columns as today.
- **Cache exists → graph columns appear automatically.** This is new, but columns use `None`/null for unmatched consumers (same schema as `--graph-metrics` today).
- **`graph_enriched` metadata field** lets downstream parsers detect the change programmatically.

### CLI flags
- `--graph-metrics` retains its meaning: "build the graph even if no cache exists." Help text updated to note auto-loading. No breakage.
- `--no-graph` is new, additive.
- No flags are removed or renamed.

### Reporter `graph_metrics_requested` parameter
- Now driven by `graph_enriched` (actual enrichment state) instead of `args.graph_metrics` (flag state). Functionally identical when using `--graph-metrics`. When auto-loading, reporters correctly include/exclude graph columns based on whether enrichment happened.

## What Phase A Does NOT Do

- Does NOT change `find_consumers()` — still runs full filesystem scan (that's Phase B)
- Does NOT build the graph on first run (that's Phase C)
- Does NOT deprecate `--graph-metrics` with a warning (defer to Phase B/C when the flag is truly unnecessary)
- Does NOT modify any reporter internals — just changes what value `graph_metrics_requested` gets

## Verification

```bash
# Unit tests
python -m pytest test_graph_enrichment.py -v
python -m pytest test_graph_cache.py -v

# Full regression
python -m pytest --tb=short

# Manual smoke tests:

# 1. No cache — should produce output without graph columns
rm -rf .scatter/
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/no_cache.json
# Verify: graph_enriched=false, no CouplingScore in results
cat /tmp/no_cache.json | python -m json.tool | grep graph_enriched

# 2. Build cache explicitly
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --graph-metrics --output-format json --output-file /tmp/with_flag.json
# Verify: graph_enriched=true, CouplingScore present

# 3. Auto-load — no --graph-metrics flag, cache exists from step 2
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/auto_load.json
# Verify: graph_enriched=true, CouplingScore present (auto-loaded!)

# 4. --no-graph escape hatch
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --no-graph --output-format json --output-file /tmp/no_graph.json
# Verify: graph_enriched=false, no CouplingScore

# 5. Console output — should show graph metrics when cache exists
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope .
# Verify: CouplingScore/FanIn/FanOut visible in console

# 6. Impact mode — auto-enrichment
python -m scatter --sow "Modify PortalDataService" \
  --search-scope . --google-api-key $KEY --output-format json \
  --output-file /tmp/impact_auto.json
# Verify: graph_enriched=true in metadata
```

## Implementation Order

1. Add `cache_exists()` to `graph_cache.py`
2. Add `--no-graph` flag and update `--graph-metrics` help text in `__main__.py`
3. Change graph loading condition (the core change)
4. Update impact mode enrichment guard
5. Change `_gm` / `_gm_impact` to use `graph_enriched`
6. Add keyword-only `graph_enriched` param to `_build_metadata()` and update all 7 call sites
7. Write tests (~11)
8. Run full suite
