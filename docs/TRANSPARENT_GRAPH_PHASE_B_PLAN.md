# Transparent Graph — Phase B: Graph-Accelerated Consumer Lookup

## Context

Today, `find_consumers()` runs a 5-stage filter pipeline that scans the entire filesystem on every invocation:

1. **Discovery** — glob for all `.csproj` files in search scope → O(dirs)
2. **ProjectReference** — parse each `.csproj` XML, check for `<ProjectReference>` to target → O(P)
3. **Namespace** — scan `.cs` files in each direct consumer for `using {namespace};` → O(F)
4. **Class** — regex `\b{class}\b` on namespace-matched files → O(F')
5. **Method** — regex `\.{method}\(` on class-matched files → O(F'')

When a cached graph exists, stages 1-2 are redundant — the graph already has `project_reference` edges with O(1) reverse lookup. Stage 3 is partially redundant — the graph has `namespace_usage` edges, though the matching algorithm differs slightly.

Phase B makes the graph the primary consumer lookup engine. When a graph is available, `find_consumers()` skips the expensive filesystem stages and starts from the graph's consumer set.

Ref: `docs/ADR_TRANSPARENT_GRAPH.md` (Phase B section)

## Behavior Changes

### Before (today)
```
find_consumers() always runs all 5 stages:
  Stage 1: glob *.csproj           → 200 projects  (500ms)
  Stage 2: parse XML references    → 12 consumers   (300ms)
  Stage 3: scan .cs for using      → 8 consumers    (800ms)
  Stage 4: regex class match       → 5 consumers    (200ms)
  Stage 5: regex method match      → 3 consumers    (100ms)
  Total: ~1.9s
```

### After (Phase B)
```
find_consumers(graph=graph) with cached graph:
  Graph lookup: get_consumers()    → 12 consumers   (<1ms)
  Stage 3: scan .cs for using      → 8 consumers    (800ms)  [still needed — see below]
  Stage 4: regex class match       → 5 consumers    (200ms)
  Stage 5: regex method match      → 3 consumers    (100ms)
  Total: ~1.1s (stages 1-2 eliminated)
```

Note: Stage 3's per-directory `.cs` file discovery cost remains — the graph eliminates the `.csproj` glob and XML parsing, not the `.cs` file scanning needed for namespace/class/method checks.

### What the graph replaces

| Stage | Replaced? | Why |
|-------|-----------|-----|
| 1 (Discovery) | **Yes** | Graph already knows all projects |
| 2 (ProjectReference) | **Yes** | Graph has `project_reference` edges with O(1) reverse lookup |
| 3 (Namespace) | **No** | See "Namespace divergence" below |
| 4 (Class) | **No** | Graph has `type_usage` edges but indexes all types, not specific ones. Class filter needs text search |
| 5 (Method) | **No** | Graph doesn't index methods at all |

### Why not replace stage 3?

The graph builder computes `namespace_usage` edges by matching a project's `RootNamespace` (from `.csproj` XML) against `using` statements. `find_consumers()` matches `using {target_namespace}` (with sub-namespace support via regex). These usually agree, but can diverge when:

- A project's `RootNamespace` differs from its actual code namespace
- `using` statements reference sub-namespaces (`using Target.Models;`)
- `global using` statements are in play

Replacing stage 3 would risk false negatives. The safe approach: **use the graph for stages 1-2 only**, then run stages 3-5 on the graph's consumer set. This gives the biggest performance win (eliminates filesystem discovery + XML parsing) with zero correctness risk.

A future optimization could use `namespace_usage` edges as a pre-filter hint, but that's not Phase B scope.

### Key rules

1. **Graph available → skip stages 1-2.** Use `graph.get_consumer_names(target_name)` to get direct consumers, then proceed to stage 3.
2. **No graph → unchanged behavior.** The filesystem path runs exactly as today. Zero risk for users without a cache.
3. **Target not in graph → fall back to filesystem.** If `target_csproj_path.stem` is not a node in the graph, the graph can't have consumer edges for it. Fall back silently to the filesystem path. Handles stale cache or scope mismatch.
4. **FilterPipeline still tracks all stages.** When graph is used, stages 1-2 get a `source="graph"` marker so console/JSON output shows the optimization took effect.
5. **Impact analyzer also benefits.** `impact_analyzer.py` calls `find_consumers()` per target — same speedup applies.

## Files to Modify

| File | Change |
|------|--------|
| `scatter/analyzers/consumer_analyzer.py` | Add `graph` param, graph-accelerated path for stages 1-2, target-not-in-graph fallback |
| `scatter/__main__.py` | Pass `graph_ctx.graph` to `find_consumers()` calls |
| `scatter/analyzers/impact_analyzer.py` | Pass `graph` through to `find_consumers()` |
| `scatter/core/models.py` | Add `source` field to `FilterStage` |
| `test_consumer_analyzer_graph.py` | **NEW** — ~15 tests for graph-accelerated path |

## Step 1: Add `source` field to `FilterStage`

A small addition so the filter pipeline can report whether a stage used the graph or filesystem.

In `scatter/core/models.py`:
```python
@dataclass
class FilterStage:
    name: str
    input_count: int
    output_count: int
    source: str = "filesystem"  # "filesystem" or "graph"
```

The default preserves backwards compatibility — existing stages auto-report "filesystem".

## Step 2: Add `graph` parameter to `find_consumers()`

### New signature

```python
def find_consumers(
    target_csproj_path: Path,
    search_scope_path: Path,
    target_namespace: str,
    class_name: Optional[str],
    method_name: Optional[str],
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
    csproj_analysis_chunk_size: int = 25,
    graph: Optional["DependencyGraph"] = None,
) -> Tuple[List[Dict[str, Union[Path, str, List[Path]]]], FilterPipeline]:
```

The parameter is keyword-only-style (last, with default None) so all existing callers work unchanged.

### Graph-accelerated stages 1-2

Extract stages 1-2 into two private helper functions with descriptive names, then branch at the top of `find_consumers()`:

```python
def _lookup_consumers_from_graph(
    graph: DependencyGraph,
    target_csproj_path: Path,
) -> Optional[Dict[Path, Dict]]:
    """Stages 1-2 via graph reverse lookup. Returns None if target not in graph.

    Filters to project_reference edges only — the graph has 4 edge types
    (project_reference, namespace_usage, type_usage, sproc_shared) but
    stage 2 semantics only check <ProjectReference> in .csproj XML.
    Using all edge types would widen the consumer set beyond what the
    filesystem path finds, causing correctness divergence.
    """
    target_name = target_csproj_path.stem

    # Target not in graph → caller should fall back to filesystem.
    # This handles stale cache, scope mismatch, or new projects.
    if graph.get_node(target_name) is None:
        logging.debug(f"Target '{target_name}' not found in graph, falling back to filesystem.")
        return None

    direct_consumers = {}
    for edge in graph.get_edges_to(target_name):
        if edge.edge_type == "project_reference":
            node = graph.get_node(edge.source)
            if node:
                direct_consumers[node.path.resolve()] = {
                    'consumer_name': edge.source,
                    'relevant_files': []
                }
    return direct_consumers


def _discover_consumers_from_filesystem(
    target_csproj_path: Path,
    search_scope_path: Path,
    max_workers: int,
    chunk_size: int,
    disable_multiprocessing: bool,
    csproj_analysis_chunk_size: int,
) -> Tuple[Dict[Path, Dict], int]:
    """Stages 1-2 via filesystem scan + XML parsing. Returns (consumers, total_scanned)."""
    ...  # existing stage 1 + stage 2 code, extracted
```

In `find_consumers()`, the branch:

```python
if graph:
    graph_result = _lookup_consumers_from_graph(graph, target_csproj_path)
    if graph_result is not None:
        direct_consumers = graph_result
        pipeline.total_projects_scanned = graph.node_count
        pipeline.stages.append(FilterStage(
            name=STAGE_DISCOVERY,
            input_count=graph.node_count,
            output_count=graph.node_count - 1,
            source="graph",
        ))
        pipeline.stages.append(FilterStage(
            name=STAGE_PROJECT_REFERENCE,
            input_count=graph.node_count - 1,
            output_count=len(direct_consumers),
            source="graph",
        ))
    else:
        # Target not in graph — fall back to filesystem
        direct_consumers, total_scanned = _discover_consumers_from_filesystem(...)
        # ... append filesystem-sourced FilterStages ...
else:
    direct_consumers, total_scanned = _discover_consumers_from_filesystem(...)
    # ... append filesystem-sourced FilterStages ...
```

Key details:
- **Filter to `project_reference` edges only.** Clearly commented: the graph has 4 edge types, but stage 2 only checks `<ProjectReference>`. Using all edges would widen the consumer set.
- **Target-not-in-graph fallback.** If the target project isn't a node in the graph (stale cache, scope mismatch, newly added project), return `None` and fall back to the filesystem path silently.
- **Resolve paths.** Graph nodes store `Path` objects; we resolve them to match the filesystem path's behavior.

### Stages 3-5 unchanged

After the branch, the code flows into stage 3 (namespace check) identically regardless of whether stages 1-2 used the graph or filesystem. The `direct_consumers` dict has the same structure either way.

## Step 3: Pass graph through call sites

### `scatter/__main__.py` — Legacy modes

All three legacy call sites (git, target, sproc) currently pass the same multiprocessing args. Add `graph=graph_ctx.graph if graph_ctx else None`:

```python
# Target mode (line ~720):
final_consumers_data, filter_pipeline = find_consumers(
    target_csproj_abs_path,
    search_scope_abs,
    target_namespace_str,
    args.class_name,
    args.method_name,
    ...,
    graph=graph_ctx.graph if graph_ctx else None,
)
```

Same pattern for git mode and sproc mode call sites.

### `scatter/analyzers/impact_analyzer.py`

`_analyze_single_target()` calls `find_consumers()`. Pass graph through:

```python
def _analyze_single_target(
    target: AnalysisTarget,
    search_scope: Path,
    ...,
    graph: Optional["DependencyGraph"] = None,
) -> TargetImpact:
    ...
    direct_consumers_data, _pipeline = find_consumers(
        ...,
        graph=graph,
    )
```

`analyze_impact()` (the public entry point) also needs the graph parameter to forward to `_analyze_single_target()`.

### `trace_transitive_impact()`

The transitive tracing function also calls `find_consumers()` for each consumer (to find consumers-of-consumers). Pass graph through here as well:

```python
def trace_transitive_impact(
    direct_consumers: List[Dict],
    search_scope: Path,
    ...,
    graph: Optional["DependencyGraph"] = None,
) -> List[EnrichedConsumer]:
```

This is important — without this, the speedup only applies to direct consumers, not transitive tracing.

## Step 4: Update `__main__.py` call to `analyze_impact()`

Pass graph through to impact analysis:

```python
impact_report = analyze_impact(
    ...,
    graph=graph_ctx.graph if graph_ctx else None,
)
```

## Step 5: FilterPipeline source display

### Console reporter

When printing the filter pipeline arrow chain, annotate graph-sourced stages:

```
Current:  Discovery(200) → ProjectRef(12) → Namespace(8) → Class(5)
New:      Discovery[graph](200) → ProjectRef[graph](12) → Namespace(8) → Class(5)
```

This is a display-only change in `scatter/reports/console_reporter.py`. Check the `source` field on each `FilterStage`:

```python
label = stage.name
if stage.source == "graph":
    label += "[graph]"
```

### JSON reporter

Add `"source"` to the filter pipeline stages in JSON output (already present via dataclass serialization if we add the field).

## Step 6: Tests — `test_consumer_analyzer_graph.py`

### TestGraphStages12 (~7 tests)

#### `test_graph_returns_same_consumers_as_filesystem` (parametrized)
- Build graph from sample projects
- **Parametrize across multiple targets:** `GalaxyWorks.Data`, `MyDotNetApp`, `MyDotNetApp.Consumer`
- For each target: call `find_consumers()` without graph → get filesystem results
- Call `find_consumers()` with graph → get graph results
- Assert consumer names match (the core correctness property)

#### `test_graph_skips_non_project_reference_edges`
- Build a `DependencyGraph` with `project_reference` AND `namespace_usage` edges
- Call `find_consumers()` with graph
- Assert only `project_reference` consumers returned (not namespace-only)

#### `test_graph_path_populates_filter_pipeline`
- Call with graph
- Assert pipeline stages exist for Discovery and ProjectReference
- Assert both stages have `source="graph"`

#### `test_filesystem_path_unchanged_without_graph`
- Call `find_consumers()` without graph param
- Assert behavior identical to today (regression guard)

#### `test_graph_path_with_stale_node`
- Build graph with node "X" that doesn't exist on disk
- Call `find_consumers()` with graph
- Assert "X" is not in results (graceful handling of stale cache)

#### `test_target_not_in_graph_falls_back_to_filesystem`
- Build graph that does NOT contain the target project as a node
- Call `find_consumers()` with graph
- Assert results match filesystem path (fallback worked)
- Assert pipeline stages have `source="filesystem"` (not "graph")

#### `test_graph_consumer_proceeds_to_namespace_check`
- Build graph, call `find_consumers()` with graph + target_namespace
- Assert stage 3 (namespace) still runs on graph consumers
- Assert final results are namespace-filtered (not just project_reference)

### TestGraphNamespaceBypass (~1 test)

#### `test_graph_path_with_unreliable_namespace`
- Build graph, call `find_consumers()` with graph + unreliable namespace (`NAMESPACE_ERROR_...`)
- Assert all graph-sourced direct consumers returned without namespace filtering
- Matches behavior of filesystem path when namespace is unreliable

### TestImpactAnalyzerGraph (~3 tests)

#### `test_impact_passes_graph_to_find_consumers`
- Mock `find_consumers` to capture kwargs
- Call `_analyze_single_target()` with graph
- Assert `graph=` kwarg was passed through

#### `test_transitive_tracing_passes_graph`
- Mock `find_consumers` to capture kwargs
- Call `trace_transitive_impact()` with graph
- Assert `graph=` kwarg was passed through on transitive calls

#### `test_impact_without_graph_unchanged`
- Call `_analyze_single_target()` without graph
- Assert `find_consumers` called without graph kwarg

### TestFilterStageSource (~2 tests)

#### `test_filter_stage_default_source`
- Create `FilterStage(name="test", input_count=10, output_count=5)`
- Assert `source == "filesystem"`

#### `test_filter_stage_graph_source`
- Create `FilterStage(name="test", input_count=10, output_count=5, source="graph")`
- Assert `source == "graph"`

**Total: ~14 tests**

## Backwards Compatibility

### `find_consumers()` signature
- `graph` is an optional keyword arg with default `None`
- All existing callers work without modification
- No changes to return type or result structure

### FilterPipeline
- `FilterStage.source` defaults to `"filesystem"` — existing code sees no change
- JSON output gains a `"source"` field in pipeline stages — additive, non-breaking

### Impact analyzer
- `graph` parameter is optional throughout the call chain
- When not passed, behavior is identical to today

### Reporter output
- Console shows `[graph]` annotation only when graph was used — additive
- JSON includes `source` field — additive
- CSV/markdown unchanged

## What Phase B Does NOT Do

- Does NOT replace stage 3 (namespace) — correctness risk too high for the marginal speedup
- Does NOT replace stages 4-5 (class/method) — graph doesn't index at that granularity
- Does NOT deprecate `--graph-metrics` — that's a Phase A follow-up when auto-loading is proven stable
- Does NOT change graph builder — no new edge types or indexes needed
- Does NOT make graph required — the filesystem path is always available as fallback
- Does NOT add `--verify-graph` flag — deferred to a follow-up if divergence is reported in practice. Parametrized integration tests provide the correctness verification.

## Performance Expectations

### Eliminated work (stages 1-2)
- **Stage 1 (Discovery):** Filesystem glob across entire search scope. Typically 200-500ms for large repos.
- **Stage 2 (ProjectReference):** Parse every `.csproj` XML file. Typically 200-400ms.
- **Graph lookup:** O(degree) hash set lookup. Sub-millisecond.
- **Savings:** ~400-900ms per `find_consumers()` call.

Note: Stage 3's per-directory `.cs` file glob cost remains unchanged. The savings above reflect only the elimination of `.csproj` discovery and XML parsing.

### Compounding in impact mode
Impact analysis calls `find_consumers()` once per target, then again for each transitive consumer. A 5-target analysis with 10 transitive levels could invoke `find_consumers()` 15+ times. Phase B savings compound: 15 calls × 600ms = **~9 seconds saved**.

### No regression without graph
When `graph=None`, the code path is identical to today — zero overhead.

## Verification

```bash
# Unit tests
python -m pytest test_consumer_analyzer_graph.py -v

# Full regression
python -m pytest --tb=short

# Manual smoke tests:

# 1. Without graph — should behave identically to today
rm -rf .scatter/
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/no_graph.json

# 2. With graph — build cache first, then run
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --graph-metrics --output-format json --output-file /tmp/with_graph.json
# Second run should use graph for stages 1-2
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file /tmp/graph_accel.json

# 3. Verify results match
diff <(jq '.results[].ConsumerProjectName' /tmp/no_graph.json | sort) \
     <(jq '.results[].ConsumerProjectName' /tmp/graph_accel.json | sort)

# 4. Filter pipeline shows [graph] annotation
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --verbose 2>&1 | grep -i "graph"
```

## Implementation Order

1. Add `source` field to `FilterStage` in `models.py`
2. Extract stages 1-2 into `_lookup_consumers_from_graph()` and `_discover_consumers_from_filesystem()` helper functions
3. Add `graph` param to `find_consumers()`, wire up the branch with target-not-in-graph fallback
4. Pass `graph` through all call sites (`__main__.py` legacy modes, `impact_analyzer.py`, `trace_transitive_impact()`)
5. Update console reporter to show `[graph]` annotation
6. Write tests (~14)
7. Run full suite

## Deferred

- **`--verify-graph` diagnostic flag** — Runs both graph and filesystem paths, logs divergence. Deferred from Phase B scope per team review: parametrized integration tests provide correctness verification, and no one would run the flag in CI. Will add if divergence is reported in practice.
