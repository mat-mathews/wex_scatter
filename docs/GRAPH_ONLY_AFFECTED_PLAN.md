# Graph-Only Path for Affected Targets

## Context

Run 6 on the monolith: 42 consumer analyses, 43 minutes. Root vs affected tiering already skips coupling/surface AI calls for affected targets and limits them to depth 0 (direct consumers only). But affected targets still go through `find_consumers()` — the expensive filesystem scan that walks .csproj references, reads .cs files, checks namespaces, etc. For 7 affected targets, that's ~15 minutes of scanning to produce consumer lists that don't get coupling narratives or transitive tracing anyway.

The graph already knows who depends on whom. `graph.get_consumers(name)` returns the answer in O(1) via a reverse adjacency lookup. For affected targets — where we only need the consumer names, counts, and pipeline assignments — the filesystem scan is pure waste.

## The change

When analyzing an affected target and a graph is available, skip `find_consumers()` entirely. Use `graph.get_consumers(target.name)` to get `ProjectNode` objects, convert them to `RawConsumerDict` format, and feed them into the existing enrichment pipeline (which already gates coupling/surface on `target_role == "root"`).

### Expected impact

| Metric | Before | After |
|--------|--------|-------|
| Affected target analysis | ~2 min each (filesystem scan) | <1s each (graph lookup) |
| 7 affected targets | ~15 min | <5s total |
| Total run time (est.) | ~43 min | ~28 min |
| Report output | Identical — affected targets already skip coupling/surface |

### What stays the same

- Root targets: unchanged, still use `find_consumers()` with full filesystem analysis
- Risk assessment: unchanged, runs on both tiers
- Consumer enrichment: unchanged, `trace_transitive_impact()` still called (with depth 0 it's a no-op loop)
- Report format: identical — consumer names, pipeline assignments, risk ratings all preserved
- Relevant files: already empty for affected targets (coupling gated on root), so graph path's empty `relevant_files` is correct

### Fallback

If no graph is available (e.g., user runs without `--graph`), affected targets fall back to `find_consumers()` as today. The optimization is opportunistic, not required.

## Changes

### 1. Add graph-only consumer path — `scatter/analyzers/impact_analyzer.py:505-560`

In `_analyze_single_target()`, before the existing `find_consumers()` call, add a fast path for affected targets when a graph is available:

```python
# Graph-only fast path for affected targets (O(1) reverse adjacency lookup)
if target.target_role == "affected" and graph is not None:
    consumer_nodes = graph.get_consumers(target.name)
    if consumer_nodes:
        direct_consumers_data = [
            RawConsumerDict(
                consumer_path=node.path,
                consumer_name=node.name,
                relevant_files=[],
            )
            for node in consumer_nodes
        ]
        logging.info(
            f"Graph fast path: {len(direct_consumers_data)} consumer(s) for affected "
            f"target {target.name}"
        )
    else:
        logging.info(f"No consumers in graph for affected target {target.name}.")
        return impact
    # Skip straight to enrichment — no transitive tracing needed (depth is 0)
    ...
```

The existing code path (filesystem `find_consumers()`) remains as the `else` branch, handling root targets and the no-graph fallback.

### 2. Skip transitive tracing for graph fast path — same location

When using the graph fast path, we still need to convert `RawConsumerDict` into `EnrichedConsumer` objects (for pipeline assignment, solution lookup, etc.). The existing `trace_transitive_impact()` already handles depth=0 correctly — it converts direct consumers to `EnrichedConsumer` and returns without recursing. So we still call it, but with `max_depth=0` guaranteed.

### 3. Add logging — same location

Log clearly when the graph path is used vs filesystem path, so monolith debug output shows the optimization working:

```
--- Analyzing target: WEX.Payments.Common (type: project, role: affected) ---
Graph fast path: 12 consumer(s) for affected target WEX.Payments.Common
```

vs root targets:

```
--- Analyzing target: WEX.Payments.Core (type: project, role: root) ---
Found 8 direct consumer(s) for WEX.Payments.Core.
```

### 4. Unit tests — `tests/unit/test_codebase_index.py`

Add tests verifying:
- Affected target with graph uses graph path (no `find_consumers()` call)
- Affected target without graph falls back to `find_consumers()`
- Root target with graph still uses `find_consumers()` (not graph path)
- Graph fast path produces correct `EnrichedConsumer` output

## Files touched

| File | Change |
|------|--------|
| `scatter/analyzers/impact_analyzer.py:505-560` | Add graph fast path branch in `_analyze_single_target()` |
| `tests/unit/test_codebase_index.py` | Add 3-4 tests for graph fast path behavior |

No changes to models, reporters, CLI, or config. Two files total.

## Risks

**Low.** The change is a conditional branch in one function. Root targets are completely untouched. Affected targets get the same consumer list (graph and filesystem agree on project references) with the same downstream processing. If the graph is unavailable, the existing path runs as before.

The one edge case: `find_consumers()` can filter by namespace/class/method, while `graph.get_consumers()` returns all reverse dependencies. But affected targets don't use class/method filters (they're project-level), and the namespace check is redundant when the graph was built from the same csproj references. The consumer list should be identical.
