# Benchmark Results: xlarge (800 Projects / 30K Files)

> **Historical baseline.** These numbers were captured *before* Initiative 12 optimizations shipped. The same workload now completes in **38.7s** (down from 5:28 CLI / 39 min instrumented). See [documentation/docs/reference/benchmarks.md](../documentation/docs/reference/benchmarks.md) for current numbers. This document is preserved as the pre-optimization baseline that motivated the work.

**Date:** 2026-03-23
**Machine:** MacBook Pro (Apple Silicon)
**Codebase:** Synthetic monolith generated with `--preset xlarge` (800 projects, ~30K .cs files, ~30K types)
**Scatter version:** 2.1.0 (main branch, commit 195223d)

---

## Full Graph Build — Stage Breakdown

Benchmark script: `tools/benchmark_graph_build.py` with `--mode stages`

| Stage | Time | % of Total | Notes |
|-------|------|-----------|-------|
| `type_usage_edges` | **2,117s (35 min)** | 90.7% | 519,724 edges, 908 MB heap peak, 29,627 files re-read, 202,641 type matches via set intersection |
| `type_extraction` | 91s | 3.9% | 29,627 files read, 29,990 types extracted |
| `find_clusters` | 89s | 3.8% | Louvain community detection on 800 nodes / 544K edges |
| `cs_mapping` | 32s | 1.4% | Reverse directory index for 29,627 files |
| `graph_construction` | 2.4s | 0.1% | 800 nodes, 12,258 project_ref edges |
| `file_discovery` | 1.1s | <0.1% | rglob for .csproj + .cs |
| `compute_metrics` | 1.2s | <0.1% | Fan-in/out, instability, coupling for 800 projects |
| `csproj_parsing` | 0.4s | <0.1% | 800 .csproj files parsed |
| `namespace_edges` | 0.2s | <0.1% | 12,258 namespace_usage edges |
| `detect_cycles` | 0.07s | <0.1% | Tarjan's SCC — 1 cycle found |
| `health_dashboard` | 0.006s | <0.1% | 1,615 observations |
| **Total** | **2,334s (~39 min)** | 100% | Peak RSS: 2,732 MB |

### Graph Summary

- **Nodes:** 800
- **Edges:** 544,240 (12,258 project_ref + 12,258 namespace_usage + 519,724 type_usage)
- **Types:** 29,990
- **Cycles:** 1

Note: The benchmark runs single-threaded with tracemalloc instrumentation. Real CLI performance is faster (see below).

---

## End-to-End CLI Timing

These use the actual CLI with multiprocessing enabled (default settings).

| Operation | Time | Notes |
|-----------|------|-------|
| `--graph --rebuild-graph` (full build) | **5 min 28s** | Includes DB scanning (1,952 deps, 45,886 sproc_shared edges), JSON report write. Total edges: 590,126 |
| `--target-project` (cached graph) | **4 min 17s** | Admin.Data → 30 consumers. Most time spent loading 590K-edge JSON cache |

### Why CLI is faster than benchmark

The CLI graph build (5:28) is much faster than the benchmark (39 min) because:
1. Multiprocessing for file discovery, csproj parsing, and type extraction
2. No tracemalloc overhead
3. No per-stage measurement overhead

### Why cached analysis is still slow

The `--target-project` run with a cached graph took 4:17. The graph cache is indented JSON (~50-100MB at this scale). `json.load()` on a file this large blocks for minutes. This defeats the purpose of caching for interactive use.

---

## Incremental Updates

Benchmark script: `tools/benchmark_incremental.py --preset xlarge --runs 1`

Full build baseline: 119.7s (median of 1 run, multiprocessing enabled)

| Scenario | Time | Speedup | Status |
|----------|------|---------|--------|
| 1 file usage-only | **193ms** | **621x** | Fast path — re-read 1 file, splice edges |
| 5 files usage-only | 1,051ms | 114x | Fast path |
| 10 files usage-only | 2,068ms | 58x | Fast path |
| 1 csproj modified | **229ms** | **522x** | No structural change detected (comment only) |
| 1 file declaration change | 148,100ms | 0.8x | Triggers full type index rebuild |
| 5 files declaration change | 144,745ms | 0.8x | Triggers full type index rebuild |
| 1 new file | 139,028ms | 0.9x | Triggers type index rebuild |
| 5 new files | 138,810ms | 0.9x | Triggers type index rebuild |
| 1 file deleted | 145,187ms | 0.8x | Triggers type index rebuild |

---

## Key Findings

### 1. `type_usage_edges` is the wall

At 800 projects, this stage takes 35 minutes and consumes 90.7% of total build time. The inverted index optimization (introduced earlier) reduced this from O(P * T * F) to O(F * I), which was transformative at 100-250 projects. But at 800 projects with 30K types, set intersection across 30K files still dominates.

This is the blocker for the Leadership Review's "< 5 minutes" monolith readiness gate.

**Potential optimizations:**
- Cache extracted identifiers per file (currently re-reads every .cs file)
- Bloom filter pre-screen before set intersection
- Parallel set intersection across file batches
- Only compute type_usage edges for projects that have project_reference or namespace_usage edges (skip unrelated projects)

### 2. Graph cache serialization is a bottleneck

Loading a cached graph takes 4+ minutes due to `json.load()` on large indented JSON. The Leadership Review flagged this: "At minimum drop `indent=2`; for real scale, evaluate msgpack or SQLite."

**Immediate fix:** Drop `indent=2` from cache serialization (saves ~40% file size)
**Better fix:** Switch to msgpack or SQLite for O(1) node/edge lookups without loading the full graph into memory

### 3. Incremental patching is excellent for the common case

Usage-only changes (the vast majority of day-to-day development) patch in under 200ms — a 621x speedup over full rebuild. This validates the incremental strategy.

Declaration changes (new types, deleted files) trigger a near-full rebuild because the type-to-project inverted index needs updating globally. This is acceptable since these changes are less frequent, but the 0.8x "speedup" (actually slower than full rebuild due to patch overhead) should be investigated.

### 4. Clustering is expensive at dense scale

Louvain community detection takes 89 seconds on the 800-node / 544K-edge graph. This is 3.8% of total time — not the bottleneck, but worth profiling. The edge density (544K edges / 800 nodes = 680 edges per node average) is unusually high due to the synthetic topology. Real monoliths may have lower density.

### 5. The 5:28 vs 39 min gap shows multiprocessing value

The CLI with multiprocessing builds the graph in 5:28. The single-threaded benchmark takes 39 minutes. This is a ~7x speedup from parallelization, validating the multiprocessing investment. However, 5:28 still exceeds the 5-minute gate.

---

## Comparison to Previous Benchmarks

| Preset | Projects | .cs Files | Benchmark Time | CLI Time (est) |
|--------|----------|-----------|---------------|----------------|
| `small` | 100 | ~1,000 | ~1.1s | <1s |
| `medium` | 250 | ~5,000 | ~9.5s | ~3s |
| `large` | 500 | ~15,000 | ~42.8s | ~15s |
| **`xlarge`** | **800** | **~30,000** | **~2,334s** | **~328s (5:28)** |

The jump from `large` (500) to `xlarge` (800) is superlinear due to the O(F * I) type_usage_edges stage scaling with both file count and type count.

---

## Recommendations (Priority Order)

1. **Eliminate double file read in type_usage_edges** — Cache file contents or extracted identifiers from the type_extraction stage. This is the single highest-impact optimization.
2. **Compact cache serialization** — Drop `indent=2` immediately. Evaluate msgpack for the next cycle.
3. **Scope type_usage_edges to reachable projects** — Only compute type usage for projects connected via project_reference or namespace_usage edges. Skip the 700+ projects that have no relationship to a given target.
4. **Profile the declaration-change incremental path** — The 0.8x "speedup" means the patcher is slower than a full rebuild for declaration changes. Investigate whether a targeted index update (only types in changed files) can avoid the global rebuild.
5. **Profile Louvain at scale** — 89 seconds may be dominated by edge iteration. Consider sparse representations or approximate clustering for dense graphs.

---

## Team Performance Review (2026-03-23)

Full team review of the benchmark results. Nine voices, focused on actionable solutions.

### The Two Distinct Problems (Priya — Architect)

These are separate problems requiring separate solutions:

1. **First-run graph build** — 5:28 with multiprocessing. Gate is < 5 minutes. Close but not there.
2. **Cached graph load** — 4:17 for a `--target-project` query. This kills interactive use. Nobody waits 4 minutes for a consumer lookup.

Also flagged: **519K type_usage edges on 800 projects is suspiciously dense** (650 edges/project). The synthetic generator creates dense coupling intentionally. A real monolith may have far fewer type_usage edges because most projects don't reference types from most other projects. Should sanity-check edge density on the real WEX monolith before over-optimizing for a pathological case.

### The Double File Read (Marcus — Principal)

`graph_builder.py` line 120 reads every `.cs` file in Step 4 (type_extraction). Line 225 reads **every `.cs` file again** in Step 5c (type_usage_edges). That's 30K file reads × 2 = 60K I/O operations.

**Fix:** Cache the identifier set during Step 4. You're already reading the file — add one line:

```python
file_identifiers = set(_IDENT_PATTERN.findall(content))
```

Stash it in a dict keyed by `cs_path`. In Step 5c, look it up instead of re-reading. This cuts 30K file reads and 30K regex passes. Estimated 30-40% reduction in type_usage_edges time.

**But even halving type_usage_edges leaves ~17 min single-threaded.** The inner loop (per-project) is embarrassingly parallel — each project's type_usage computation is independent. Parallelizing Step 5c is the next lever.

### Algorithmic Analysis (Devon — Performance)

The current Step 5c inner loop:

```
For each source_project (800):
    For each cs_file in project (avg 37 files):
        Read file → comment strip → regex tokenize → set intersection with 30K type names
```

The set intersection itself is O(500) per file (avg identifiers) — fast. The cost is in the **per-file overhead**:
1. File I/O (30K reads)
2. Comment stripping (`_strip_cs_comments` — regex substitution on full content, 30K times)
3. Regex tokenization (`_IDENT_PATTERN.findall` — builds full identifier list, 30K times)
4. Set construction from the list

If identifiers and comment-stripped content are extracted **once** during Step 4 and cached, Step 5c becomes a pure in-memory loop with no I/O and no regex. **Estimated drop from 35 minutes to under a minute.**

### Scope Reduction (Tomás — Minimalism)

Edge breakdown: 12K project_reference + 12K namespace_usage + 520K type_usage. Type_usage is 95% of all edges.

**Proposal: only compute type_usage edges between projects that already have a `project_reference` or `namespace_usage` edge.** If Project A doesn't reference Project B via `.csproj` and doesn't import its namespace, a type_name collision is almost certainly a false positive.

This scopes the inner loop from 800 × 800 = 640K project pairs to ~800 × 15 = 12K reachable pairs. **~50x reduction in work.**

Trade-off: misses type usages via fully-qualified names without a `using` statement (rare in C#). Acceptable at this scale.

### SQLite Over msgpack (Fatima — Resilience)

**Cache serialization: drop `indent=2` immediately** (line 117 of `graph_cache.py`). Reduces ~100MB to ~60MB.

But the real fix is **SQLite**, not msgpack:
- Load individual nodes/edges without deserializing the entire graph
- Query "all edges where target = X" without scanning everything — milliseconds
- Atomic writes (no half-written cache on crash)
- Ships with Python (no new dependency)
- `--target-project` becomes a SQL query on an indexed table, not a 590K-edge JSON parse

Turns the cache from "load everything into memory" to "query what you need." For a query that only needs 30 consumers, loading 590K edges is absurd.

**Also:** The 0.8x incremental "speedup" on declaration changes means the patcher is slower than a full rebuild. Should fall back to full rebuild when declaration changes are detected rather than pretending to patch.

### Semantic Concern (Jake — Security/Correctness)

Tomás's scoping proposal **changes the graph semantics.** Today, type_usage edges surface hidden dependencies — "Project A uses a type from Project B even though there's no project reference." That's a valuable signal for finding missing `.csproj` references.

**Mitigation:** Add `--full-type-scan` flag to preserve current behavior for auditing. Default to scoped for performance.

### Effort vs. Impact Ranking (Sam — Simplicity)

| Fix | Effort | Impact | Risk |
|-----|--------|--------|------|
| Drop `indent=2` from cache | 1 line | ~40% smaller cache, faster load | Zero |
| Cache identifiers from Step 4 | ~20 lines | Eliminate 30K file re-reads + regex | Low |
| Scope type_usage to reachable pairs | ~15 lines | ~50x fewer project pairs | Medium (semantics change) |
| Parallelize Step 5c | ~30 lines | ~4-7x speedup on multi-core | Low |
| SQLite cache | ~200 lines | Millisecond queries vs. minute loads | Medium (migration) |

**Do the first three this week.** They compound. Measure after those before investing in SQLite or parallelization.

### Verification Strategy (Anya — Testing)

For each change:
1. Run `benchmark_graph_build.py` on xlarge — capture baseline
2. Make the change
3. Re-run benchmark — compare
4. Run full test suite — verify no regressions
5. **Correctness check:** Build graph with current code, build with new code, diff the edges. Any difference needs justification.

For the scoping proposal specifically: run both scoped and unscoped builds, diff edge sets, count type_usage edges between projects with **no** project_reference or namespace_usage edge. If < 1% of total, scoping is safe. If 10%, think harder.

### CI Integration (Kai — Tooling)

Get the `medium` preset benchmark into CI with a timing threshold. ~10 seconds per run — cheap enough to catch perf regressions before they ship.

---

## Agreed Action Plan

### Immediate (this week)

1. **Drop `indent=2`** from `graph_cache.py` line 117. One-line fix, zero risk.
2. **Cache file identifiers + comment-stripped content in Step 4** — stash `set(_IDENT_PATTERN.findall(content))` and stripped content during type_extraction, reuse in type_usage_edges. Eliminates 30K redundant file reads + regex passes.
3. **Scope type_usage to reachable project pairs** — only compute type_usage edges between projects connected by project_reference or namespace_usage. Add `--full-type-scan` flag to preserve current behavior for auditing.

### Measure, then decide

4. Re-run xlarge benchmark after fixes 1-3. If build < 3 min and cache load < 30s, defer SQLite and parallelization.
5. If still too slow: **parallelize Step 5c** — partition files across workers, merge evidence dicts.
6. **SQLite cache** — if cache load still bottlenecked after dropping indent.

### Later

7. Profile Louvain clustering at scale (89s, 3.8% of total).
8. Add `medium` preset benchmark to CI with regression threshold.
9. Validate edge density against the real WEX monolith — may recalibrate all priorities.
