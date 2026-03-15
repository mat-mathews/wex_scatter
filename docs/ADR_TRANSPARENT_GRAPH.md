# Transparent Graph Acceleration

**March 2026**

---

## The Problem

Scatter has two parallel paths to answer the same question ("who consumes project X?"):

1. **`find_consumers()`** — filesystem scan. Always runs, proven, O(P+F). Rediscovers every `.csproj`, re-parses XML, re-scans `.cs` files on every invocation.
2. **`DependencyGraph`** — cached, incrementally patched, O(degree) consumer lookups. But opt-in via `--graph-metrics`, and even then it's only used for post-hoc *enrichment* — the actual consumer detection still goes through `find_consumers()`.

The incremental graph patcher (`scatter/store/graph_patcher.py`) can update a cached graph in 10ms for typical changes. But branch/target/sproc modes ignore the graph for their core work and rescan the filesystem every time.

Meanwhile, the CLI is getting complicated. A user doing branch analysis could be staring at:

```
--branch-name, --base-branch, --repo-path, --search-scope,
--class-name, --method-name, --graph-metrics, --rebuild-graph,
--summarize-consumers, --google-api-key, --enable-hybrid-git,
--disable-multiprocessing, --output-format, --output-file, -v
```

Adding more flags to close the gap would make this worse.

---

## Current Code Flow

### Branch mode without `--graph-metrics` (today's default)

```
scatter --branch-name feature/foo --search-scope .
  1. git diff → changed files → extract type declarations
  2. For each changed project:
       find_consumers() → full filesystem scan O(P+F)
  3. Report results (no coupling metrics)
```

### Branch mode with `--graph-metrics`

```
scatter --branch-name feature/foo --search-scope . --graph-metrics
  1. build_graph_context()
       → load v2 cache → incremental patch (ms) → compute metrics
  2. git diff → changed files → extract type declarations
  3. For each changed project:
       find_consumers() → full filesystem scan O(P+F)  ← STILL RUNS
  4. enrich_legacy_results() → inject CouplingScore, FanIn, etc.
  5. Report results (with metrics)
```

The graph is loaded and patched efficiently, but `find_consumers()` still does its own independent filesystem scan. The graph's `get_consumers()` (which could answer in microseconds) is never called.

---

## Proposed Design: Transparent Graph Acceleration

Instead of adding flags, make the graph an **automatic acceleration layer** — like git's index, or Nx/Turborepo's cache. The user never thinks about it.

### User experience

```bash
# First run — same speed as today, builds graph cache as a side effect
python scatter.py --target-project ./Lib/Lib.csproj --search-scope .

# Second run — automatically fast, metrics included
python scatter.py --target-project ./Lib/Lib.csproj --search-scope .

# Escape hatch
python scatter.py --target-project ./Lib/Lib.csproj --search-scope . --no-graph
```

No new flags. `--graph-metrics` becomes unnecessary (deprecated, then removed). The mental model simplifies to:

> Scatter automatically caches a dependency graph. Subsequent runs are faster. Use `--no-graph` to bypass. Use `--rebuild-graph` to force a fresh build.

### Internal flow

```
Every analysis mode (branch, target, sproc):
  1. Does a valid v2 graph cache exist?
     YES → load + incremental patch (ms)
     NO  → fall through to filesystem scan, build cache for next time
  2. If graph available:
       Use graph.get_consumers() for project_ref + namespace stages (ms)
       Still text-search candidate files for class/method filtering
       Enrich results with metrics automatically
  3. If no graph:
       find_consumers() full pipeline (today's behavior)
  4. Report results
```

---

## Implementation Phases

### Phase A — Automatic graph loading (low risk, high value)

Make graph loading automatic on every run when a cache exists. No flag needed.

Changes:
- In `__main__.py`, attempt `build_graph_context()` whenever a v2 cache exists (not just when `--graph-metrics` is passed)
- If graph loads successfully, enrich results transparently
- `--graph-metrics` becomes a no-op with deprecation warning
- Add `"graph_enriched": true/false` to JSON metadata so downstream parsers can detect the new columns
- No change to `find_consumers()` — it still runs as today

Risk: Low. Only adds enrichment columns to output. Downstream parsers that don't expect CouplingScore/FanIn/etc. could break — mitigated by the metadata flag and by only enriching when cache exists (first run produces the same output as today).

### Phase B — Graph-accelerated consumer lookup (medium risk, high value)

Use the graph to replace the first 2-3 stages of `find_consumers()` when available.

Changes:
- `find_consumers()` gains `graph: Optional[DependencyGraph] = None` parameter
- When graph is passed, skip filesystem discovery + project_ref + namespace stages:
  ```python
  if graph:
      candidates = graph.get_consumers(target_name)  # O(degree), ms
  else:
      candidates = _discover_and_filter(...)          # O(P+F), seconds
  ```
- Class/method text-search stages still run on the candidate set (the graph doesn't index at that granularity)
- Add a `--verify-graph` diagnostic flag that runs BOTH paths and warns on divergence (transition safety net)
- Property tests: graph path == filesystem path for all sample project scenarios

Risk: Medium. The graph and `find_consumers()` must agree on what constitutes a "consumer." Edge cases to watch:
- Namespace matching (graph uses `RootNamespace`; `find_consumers()` uses `using` statement text search)
- Projects outside search scope (graph only contains nodes within its build scope)
- Exclude patterns applied differently

### Phase C — First-run graph build (low risk, completes the loop)

On first run (no cache), build the graph as part of the normal analysis pipeline and save it.

Changes:
- After `find_consumers()` completes, if no graph cache exists, build one with `capture_facts=True`
- The cost is roughly the same as `find_consumers()` since both scan the same files — we're just caching the results
- Future runs get the fast path automatically
- Alternative: build the graph in a background thread while `find_consumers()` runs, save when both complete

Risk: Low. Adds ~0-30% overhead to first run (the graph builder reads the same files `find_consumers()` already read, but also builds indexes). Could be made zero-overhead by sharing the already-read file contents.

---

## Backwards Compatibility Concerns

### Output schema changes

Adding CouplingScore/FanIn/FanOut/Instability/InCycle columns to output when they weren't there before could break downstream parsers.

Mitigations:
- Include graph columns **only** when the graph was actually used
- Add `"graph_enriched": true` field to JSON metadata
- CSV/markdown get the columns only when enriched
- Console output always shows them (human-readable, no parser risk)

### `--graph-metrics` flag

Options:
1. **Keep as no-op + deprecation warning.** "Graph metrics are now included automatically when a cache is available." Remove in next major version.
2. **Redefine as eager mode.** `--graph-metrics` = "build the graph NOW even on first run." Default behavior only uses an existing cache.

Option 2 is cleaner — it gives the flag a purpose during the transition and avoids a breaking change.

### Result correctness

The graph-based consumer lookup and `find_consumers()` should produce identical results. The existing property tests verify this for incremental updates. A `--verify-graph` flag (Phase B only) could run both paths and log divergence during the transition period.

---

## CLI Simplification Impact

Flags removed or simplified:
- `--graph-metrics` → deprecated (auto-detected from cache)
- `--rebuild-graph` → stays (diagnostic escape hatch)
- No new flags added in Phase A or C
- `--verify-graph` added temporarily in Phase B (diagnostic only, remove after confidence is established)
- `--no-graph` added as escape hatch (rarely needed)

Net effect: one less flag for normal usage. Power users retain full control.

---

## Decision Required

Which phases to implement, and in what order:

| Phase | Effort | Risk | Value | Prerequisite |
|-------|--------|------|-------|-------------|
| A — Auto graph loading | ~0.5 day | Low | Medium (auto-enrichment, simpler CLI) | None |
| B — Graph-accelerated lookup | ~2 days | Medium | High (ms consumer lookups) | Phase A |
| C — First-run graph build | ~0.5 day | Low | Medium (completes the loop) | Phase A |

**Recommended path:** A → C → B. Phase A is safe and immediately useful. Phase C completes the "it just works" experience. Phase B is the biggest win but needs more testing to ensure correctness parity.

**Alternative:** A only, defer B and C. This gives automatic enrichment with zero correctness risk, and we revisit the consumer lookup acceleration when there's a concrete performance complaint from a user.

---

## Open Questions

1. **Should first-run graph build (Phase C) be synchronous or background?** Synchronous is simpler but adds overhead. Background is zero-overhead but more complex (need to handle the case where the background build finishes after the main analysis completes).

2. **Namespace matching divergence.** The graph matches on `RootNamespace` (from `.csproj`). `find_consumers()` matches on `using` statements in `.cs` files. These are usually the same, but could diverge if a project's `RootNamespace` doesn't match what other projects `using`. Need to audit this before Phase B.

3. **Impact mode.** The impact analyzer (`impact_analyzer.py`) also calls `find_consumers()`. Should graph acceleration apply there too? Probably yes, but it has its own transitive tracing logic that partially overlaps with `graph.get_transitive_consumers()`.
