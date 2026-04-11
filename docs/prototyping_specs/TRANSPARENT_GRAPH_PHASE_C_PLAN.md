# Transparent Graph — Phase C: First-Run Graph Build

## Context

After Phases A and B, scatter auto-loads and uses the graph when a cache exists. But the cache only exists if the user previously ran `--graph-metrics` or `--graph`. First-run users get no graph acceleration and no enrichment — they have to know the flag exists.

Phase C closes the loop: on first run, build the graph as a side effect of the normal analysis pipeline and cache it. Every subsequent run gets the fast path automatically. No flags, no documentation to read, it just works.

Ref: `docs/ADR_TRANSPARENT_GRAPH.md` (Phase C section)

## Behavior Changes

### Before (today)
```
First run (no cache):
  find_consumers() runs stages 1-5 via filesystem  → results
  graph_ctx = None (no cache, --graph-metrics not passed)
  → No enrichment, no graph columns in output
  → No cache created
  → Second run is identical (still no cache)

User must know to run:
  scatter --graph-metrics ...   (or)   scatter --graph ...
to create the cache. Then subsequent runs auto-load.
```

### After (Phase C)
```
First run (no cache):
  find_consumers() runs stages 1-5 via filesystem  → results
  graph_ctx = None initially
  → Build graph in background, save v2 cache with facts
  → Create GraphContext, enrich results
  → Output includes graph columns on first run
  → Cache exists for next run → Phase A auto-load + Phase B acceleration

Second run:
  Cache exists → auto-load (Phase A) → graph-accelerated lookup (Phase B)
  → Full fast path, zero user action required
```

### Key rules

1. **First run builds graph after `find_consumers()`.** The graph builder scans all `.csproj` and `.cs` files across the entire search scope (not just consumer directories), so the cost is higher than `find_consumers()` alone. One-time cost: ~1-5s depending on repo size, recovered many times over on subsequent runs via Phase B acceleration.
2. **`--no-graph` skips everything.** Existing escape hatch from Phase A applies — no build, no enrichment.
3. **Build happens once per mode invocation.** Git mode calls `find_consumers()` multiple times (per type), but the graph build happens once after all calls complete. The `_ensure_graph_context()` helper is idempotent.
4. **Impact mode also benefits.** Build graph after `run_impact_analysis()` returns if no graph was loaded.
5. **Graph mode unchanged.** `--graph` already builds and caches — no change needed.
6. **v2 cache with facts.** Always build with `capture_facts=True` so incremental patching works on subsequent runs.
7. **Silent on failure.** If the graph build fails, log a debug message and continue. First-run build is best-effort, not required.
8. **Pre-build user feedback.** Log an INFO message before starting the build: `"Building dependency graph cache for future acceleration..."` so users understand the one-time delay.

## Design Decision: Build Before or After Enrichment?

Two options:

**Option A: Build after `find_consumers()`, enrich on first run.**
- Build graph → create GraphContext → enrich `all_results` → report includes graph columns
- User sees enrichment on very first run
- Adds ~0-30% overhead to first run

**Option B: Build after `find_consumers()`, don't enrich until next run.**
- Build graph → save cache → next run auto-loads and enriches
- First run output is identical to today (no graph columns)
- Zero overhead to first run's output path (build can be deferred)

**Decision: Option A.** The whole point of Phase C is "it just works." If the user runs scatter and sees coupling scores on their first run, they understand the tool's value immediately. Making them run it twice defeats the purpose.

## Files to Modify

| File | Change |
|------|--------|
| `scatter/__main__.py` | Build graph after `find_consumers()` when `graph_ctx is None`, enrich results |
| `test_graph_enrichment.py` | ~5 new tests for first-run build behavior |

No new modules. No new flags. No new reporter changes. The graph build, save, and enrichment functions all already exist.

## Step 1: Refactor graph loading in `__main__.py`

### Current flow (lines 530-551):

```python
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
            logging.warning("Graph context unavailable. Proceeding without graph metrics.")
```

### New flow:

```python
graph_ctx = None
graph_enriched = False
if not args.no_graph and search_scope_abs and not is_graph_mode:
    from scatter.store.graph_cache import cache_exists
    from scatter.analyzers.graph_enrichment import (
        build_graph_context,
        enrich_legacy_results,
        enrich_consumers,
    )
    _has_cache = cache_exists(search_scope_abs, config.graph.cache_dir)
    if args.graph_metrics or _has_cache:
        graph_ctx = build_graph_context(search_scope_abs, config, args)
        if graph_ctx:
            graph_enriched = True
        elif args.graph_metrics:
            logging.warning("Graph context unavailable. Proceeding without graph metrics.")
```

Key change: imports moved outside the `if` block so they're available for the post-`find_consumers()` build step. The `_has_cache` variable captures whether we had a cache at startup (used later to decide whether to build).

## Step 2: Add first-run graph build after `find_consumers()`

### Legacy modes (branch, target, sproc)

After all `find_consumers()` calls complete and before enrichment/reporting, add:

```python
# Build graph on first run if not already loaded
if graph_ctx is None and not args.no_graph and search_scope_abs and not is_graph_mode:
    try:
        graph_ctx = build_graph_context(search_scope_abs, config, args)
        if graph_ctx:
            graph_enriched = True
            logging.info("Graph built and cached on first run.")
    except Exception as e:
        logging.debug(f"First-run graph build failed (non-fatal): {e}")
```

This goes in three places:
1. **Branch mode** — after the type-iteration loop completes (after line ~700)
2. **Target mode** — after `find_consumers()` returns (after line ~731)
3. **Sproc mode** — after the class-iteration loop completes (after line ~850)

Actually, all three modes converge at the enrichment section. There's a single enrichment point per mode. The cleanest approach is to add the build right before the existing enrichment check.

Wait — looking more carefully, the enrichment for legacy modes happens at a shared point. Let me check...

Actually, there are separate enrichment points per mode. But since the pattern is the same, I'll add it at each enrichment site.

### Better: Single build point

Looking at the flow, all legacy modes end up at the same reporting section. The graph build should happen **once**, right before enrichment, regardless of which mode ran.

The enrichment for legacy results happens at these lines:
- Branch mode: `if graph_ctx and all_results: enrich_legacy_results(all_results, graph_ctx)` (line ~700)
- Target mode: same pattern (line ~858)
- Sproc mode: same pattern

Each mode has its own enrichment block. The simplest change: at each enrichment block, if `graph_ctx is None`, try building it first.

```python
# At each legacy mode enrichment point, replace:
if graph_ctx and all_results:
    enrich_legacy_results(all_results, graph_ctx)

# With:
if not graph_ctx and not args.no_graph and search_scope_abs:
    try:
        graph_ctx = build_graph_context(search_scope_abs, config, args)
        if graph_ctx:
            graph_enriched = True
            logging.info("Graph built and cached on first run.")
    except Exception as e:
        logging.debug(f"First-run graph build failed (non-fatal): {e}")
if graph_ctx and all_results:
    enrich_legacy_results(all_results, graph_ctx)
```

### Impact mode

Same pattern before the impact enrichment block:

```python
# Before the existing impact enrichment:
if not graph_ctx and not args.no_graph and search_scope_abs:
    try:
        graph_ctx = build_graph_context(search_scope_abs, config, args)
        if graph_ctx:
            graph_enriched = True
            logging.info("Graph built and cached on first run.")
    except Exception as e:
        logging.debug(f"First-run graph build failed (non-fatal): {e}")
if graph_ctx:
    for ti in impact_report.targets:
        enrich_consumers(ti.consumers, graph_ctx)
```

## Step 3: Extract helper to avoid repetition

Since the first-run build block is identical across all 4 sites, extract a helper:

```python
def _ensure_graph_context(graph_ctx, graph_enriched, args, search_scope_abs, config):
    """Build graph on first run if not already loaded. Returns (graph_ctx, graph_enriched)."""
    if graph_ctx is not None or args.no_graph or not search_scope_abs:
        return graph_ctx, graph_enriched
    try:
        from scatter.analyzers.graph_enrichment import build_graph_context
        logging.info("Building dependency graph cache for future acceleration...")
        graph_ctx = build_graph_context(search_scope_abs, config, args)
        if graph_ctx:
            graph_enriched = True
            logging.info("Graph built and cached on first run.")
    except Exception as e:
        logging.debug(f"First-run graph build failed (non-fatal): {e}")
    return graph_ctx, graph_enriched
```

Then each enrichment site becomes:

```python
graph_ctx, graph_enriched = _ensure_graph_context(
    graph_ctx, graph_enriched, args, search_scope_abs, config
)
if graph_ctx and all_results:
    enrich_legacy_results(all_results, graph_ctx)
```

This function is idempotent — if `graph_ctx` is already set (from cache load), it returns immediately.

## Step 4: Update `graph_metrics_requested` logic

Phase A changed `_gm = graph_enriched` (instead of `args.graph_metrics`). This already works correctly for Phase C: when the first-run build succeeds, `graph_enriched = True`, and reporters include graph columns.

No change needed.

## Step 5: Tests

### TestFirstRunGraphBuild (~5 tests in `test_graph_enrichment.py`)

All subprocess tests use `--search-scope` pointing to the repo root but with cache isolation via `tmp_path` to avoid modifying the repo's `.scatter/` directory. Tests copy sample projects or use environment overrides to direct cache writes to temp directories.

#### `test_first_run_builds_and_enriches`
- Subprocess test with isolated search scope
- Assert `graph_enriched` is True in metadata (graph was built on first run)
- Assert `CouplingScore` key exists in results (enrichment happened)
- Assert cache file now exists (cache was saved)

#### `test_first_run_no_graph_skips_build`
- Subprocess test with `--no-graph` and isolated scope
- Assert `graph_enriched` is False
- Assert cache file does NOT exist

#### `test_first_run_then_graph_accelerated`
- Subprocess test with isolated scope
- Run once (first-run build creates cache)
- Run again (auto-load + graph-accelerated lookup)
- Compare consumer names between runs — should match
- Second run should have `filter_pipeline.stages[0].source == "graph"`

#### `test_first_run_no_graph_then_normal`
- Subprocess test: first run with `--no-graph` (no cache created)
- Second run without `--no-graph` (first-run build triggers)
- Assert second run has `graph_enriched: true`

#### `test_ensure_graph_context_idempotent`
- Unit test: call `_ensure_graph_context()` with an already-set `graph_ctx`
- Assert it returns immediately without building

**Total: ~5 tests**

## Backwards Compatibility

- **First run output now includes graph columns.** This is the intended behavioral change. Downstream parsers should already handle `CouplingScore` etc. from Phase A (they appear when cache exists).
- **`graph_enriched` metadata field** correctly reflects whether enrichment happened — same as Phase A.
- **`--no-graph` escape hatch** prevents the first-run build — same as Phase A.
- **No new flags.** No new CLI arguments.
- **One-time graph build cost on first run (~1-5s).** The graph builder scans all `.csproj` and `.cs` files across the entire search scope (not just consumer directories like `find_consumers()` does), so the cost is additive, not just "re-reading cached files." Subsequent runs recover this cost many times over via Phase B acceleration.

## Performance Expectations

- **First run:** Adds ~1-5s for graph build (scans all `.cs` files across the entire search scope, not just consumer directories). OS file cache helps but cost is real.
- **Second run onward:** Same as Phase B (graph-accelerated stages 1-2, ~400-900ms savings per call, compounding in impact mode)
- **`--no-graph`:** Zero overhead (no build, no enrichment)

## What Phase C Does NOT Do

- Does NOT build the graph in a background thread — synchronous build is simpler and the overhead is small
- Does NOT share file contents between `find_consumers()` and `build_dependency_graph()` — possible future optimization
- Does NOT change graph builder — same `build_dependency_graph()` with `capture_facts=True`
- Does NOT add new CLI flags

## Verification

```bash
# Unit tests
python -m pytest test_graph_enrichment.py -v -k "first_run"

# Full regression
python -m pytest --tb=short

# Manual smoke tests:

# 1. Delete cache, first run should build graph and enrich
rm -rf .scatter/
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/first_run.json
# Verify: graph_enriched=true, CouplingScore present, .scatter/graph_cache.json exists
cat /tmp/first_run.json | python -m json.tool | grep graph_enriched
ls -la .scatter/graph_cache.json

# 2. Second run should auto-load and use graph acceleration
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/second_run.json --verbose 2>&1 | grep -i graph
# Verify: graph_enriched=true, "graph-accelerated" in logs

# 3. --no-graph prevents first-run build
rm -rf .scatter/
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --no-graph --output-format json --output-file /tmp/no_graph.json
# Verify: graph_enriched=false, no .scatter/ directory
cat /tmp/no_graph.json | python -m json.tool | grep graph_enriched
ls .scatter/ 2>/dev/null || echo "No cache (expected)"

# 4. Full golden path: first run → second run → --no-graph
rm -rf .scatter/
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/golden1.json
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/golden2.json
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --no-graph --output-format json --output-file /tmp/golden3.json
# Compare consumer names (should all match):
diff <(jq -r '.all_results[].ConsumerProjectName' /tmp/golden1.json | sort) \
     <(jq -r '.all_results[].ConsumerProjectName' /tmp/golden2.json | sort)
```

## Implementation Order

1. Add `_ensure_graph_context()` helper to `__main__.py`
2. Wire it in at each enrichment site (branch, target, sproc, impact)
3. Move imports outside the cache-check `if` block
4. Write tests (~5)
5. Run full suite
