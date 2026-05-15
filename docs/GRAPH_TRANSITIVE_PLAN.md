# Graph-Only Transitive Tracing for SOW Mode

## Context

Run 7 on the monolith: 29 minutes total. The graph-only path for affected targets worked perfectly (8 targets resolved in <1s). But root targets still took 28 minutes — not because finding direct consumers is slow (graph handles that instantly), but because **transitive tracing calls `find_consumers()` on every direct consumer**, triggering full namespace scans.

Example: Root target `Lighthouse1.ReceiptImage` has 6 direct consumers. One of them is `Lighthouse1.LH1OnDemand.Data.Daab`. Transitive tracing asks "who consumes Data.Daab?" — this triggers a namespace scan of 226 projects reading thousands of .cs files. Result: a list of 226 project names. That's it. We never use their `relevant_files` because coupling narratives only run on depth-0 consumers of root targets.

The graph already knows the answer to "who consumes Data.Daab?" — `graph.get_consumers("Lighthouse1.LH1OnDemand.Data.Daab")` returns 350 nodes in microseconds.

## What transitive tracing produces vs what we actually use

| Output | Source | Used by |
|--------|--------|---------|
| Transitive consumer names | `find_consumers()` → namespace scan | Report counts, tree rendering |
| Transitive consumer count | `find_consumers()` → namespace scan | Risk scoring, report |
| Transitive `relevant_files` | `find_consumers()` → namespace scan | **Nothing** — coupling is depth-0 + root only |
| Propagation parent | BFS tree structure | Tree rendering |
| Pipeline/solution assignment | `find_solutions_for_project()` | Report |

The namespace scan at depth 1+ is pure waste in SOW mode. We scan .cs files to produce `relevant_files` that nobody reads.

## The change

In `trace_transitive_impact()`, when a graph is available and `depth > 0`, use `graph.get_consumers()` instead of `find_consumers()`. This replaces the expensive namespace scan with an O(1) lookup for the transitive layer.

### What stays the same

- **Depth 0 (direct consumers)**: unchanged. `find_consumers()` with full namespace scan still runs for root targets' direct consumers. This produces `relevant_files` needed for coupling narratives.
- **Enrichment**: `EnrichedConsumer` objects at depth 1+ get the same fields (pipeline, solutions, confidence, propagation_parent).
- **Report output**: identical consumer counts, tree structure, risk scores.
- **Non-SOW modes** (target-project mode): unchanged — they don't use this code path.

### What changes

- **Depth 1+ consumer discovery**: `graph.get_consumers(consumer_name)` replaces `find_consumers(target_csproj_path=...)`. Returns `List[ProjectNode]` → convert to `List[RawConsumerDict]` with empty `relevant_files`.
- **No namespace filtering at depth 1+**: The graph returns all project-reference consumers. Currently `find_consumers()` also does a namespace check, but for transitive tracing we don't need that precision — a ProjectReference IS the signal.
- **No `.cs` file reads at depth 1+**: zero filesystem I/O for the transitive layer.

### Expected impact

| Metric | Before (run 7) | After |
|--------|----------------|-------|
| Transitive trace for 6 root targets | ~20 min (namespace scans) | <1s (graph lookups) |
| Total runtime (est.) | 29 min | ~10 min |
| Report output | Unchanged | Unchanged |

The remaining ~10 min is: file discovery (2.5 min), depth-0 `find_consumers()` namespace scans for root targets (5-6 min), AI enrichment (1 min), complexity/narrative (seconds).

## Implementation

### 1. Modify `trace_transitive_impact()` — `scatter/analyzers/impact_analyzer.py:704-731`

Replace the transitive `find_consumers()` call with a graph lookup when graph is available:

```python
# For next depth: find consumers of this consumer
if depth < max_depth:
    if graph is not None:
        # Graph-only transitive lookup — no filesystem I/O
        transitive_nodes = graph.get_consumers(consumer_name)
        transitive_data: List[RawConsumerDict] = [
            RawConsumerDict(
                consumer_path=node.path,
                consumer_name=node.name,
                relevant_files=[],
            )
            for node in transitive_nodes
        ]
    elif consumer_path.is_file():
        # Filesystem fallback (no graph available)
        ns = derive_namespace(consumer_path)
        if ns:
            if consumer_cache is not None and consumer_path in consumer_cache:
                transitive_data, _t_pipeline = consumer_cache[consumer_path]
            else:
                transitive_data, _t_pipeline = find_consumers(...)
                if consumer_cache is not None:
                    consumer_cache[consumer_path] = (transitive_data, _t_pipeline)
        else:
            transitive_data = []
    else:
        transitive_data = []

    for td in transitive_data:
        td_path = td["consumer_path"]
        if td_path not in visited and td_path not in parent_map:
            parent_map[td_path] = consumer_name
    next_level_raw.extend(transitive_data)
```

### 2. Remove `consumer_path.is_file()` guard for graph path

The current code guards transitive tracing with `if consumer_path.is_file()` — this is needed for filesystem-based tracing (to derive namespace from the .csproj). The graph path doesn't need the file to exist locally, since it looks up by name.

### 3. Tests

- Graph available + depth 1 → `find_consumers` not called for transitive layer, `graph.get_consumers` called
- No graph + depth 1 → `find_consumers` still called (fallback)
- Graph transitive produces correct propagation_parent chain
- Consumer count matches (graph returns same or superset of namespace-filtered results)

## Why the consumer count might differ (and why that's fine)

The current namespace-filtered transitive count might be slightly *lower* than the graph count. Example: Project A references Project B, but no .cs file in A has `using B.Namespace;` — the current code would exclude A, the graph path would include it.

This is actually more correct for SOW impact analysis. A ProjectReference means "this project depends on that project at build time." Whether it has a `using` statement is an implementation detail — the dependency is real either way. The namespace filter was designed for target-project mode where you want precision about runtime coupling. For SOW mode, build-time dependency IS the blast radius signal.

## Files touched

| File | Change |
|------|--------|
| `scatter/analyzers/impact_analyzer.py:704-731` | Graph-only transitive in `trace_transitive_impact()` |
| `tests/unit/test_codebase_index.py` | 3-4 tests for graph transitive behavior |

## Risk

Low. The change is inside `trace_transitive_impact()` only, gated on `graph is not None`. Depth 0 is completely untouched. Non-SOW modes that don't pass a graph are unaffected. The fallback to `find_consumers()` remains for the no-graph case.
