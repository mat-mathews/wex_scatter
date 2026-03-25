# Benchmarks

Performance measurement tools and results. Everything here is reproducible on your own machine with the tools in `tools/`.

---

## Perf

Full graph build (`--mode full`, no tracemalloc, 3 runs with warmup, Apple Silicon):

| Scale | Projects | .cs Files | Median Build Time | Peak RSS |
|-------|----------|-----------|-------------------|----------|
| Medium | 250 | 4,760 | **2.6s** | 216 MB |
| XLarge | 800 | 19,040 | **25.8s** | 878 MB |
| XLarge (dense) | 800 | 29,627 | **38.7s** | 1,164 MB |

Incremental patches (the common case — editing method bodies, adding imports) run 10-954x faster than full rebuilds.

### Where the time goes (800 projects, 30K files)

| Stage | Time | % Total |
|-------|------|---------|
| build_dependency_graph | 30.8s | 80% |
| find_clusters (Louvain) | 6.8s | 17% |
| detect_cycles | 0.8s | 2% |
| compute_metrics | 0.2s | 1% |
| health_dashboard | <0.1s | <1% |

The graph build itself is dominated by file I/O and regex extraction (Step 4), now parallelized via ThreadPoolExecutor.

## Synthetic Codebase Generator

**Script**: `tools/generate_synthetic_codebase.py`

Generates a 'realistic' .NET monolith directory tree that exercises every scatter code path: type declarations, `using` statements, project references, sproc references, DbSet patterns, SQL strings, comments, and multiple `.sln` files.

### Presets

| Preset | Projects | Files | Coupling % | Sproc % | Avg File KB |
|--------|----------|-------|------------|---------|-------------|
| `small` | 100 | ~1,000 | 5% | 15% | 8 |
| `medium` | 250 | ~5,000 | 4% | 12% | 15 |
| `large` | 500 | ~15,000 | 3% | 10% | 20 |
| `xlarge` | 800 | ~32,000 | 2% | 8% | 25 |

### Usage

```bash
# Use a preset
python tools/generate_synthetic_codebase.py --preset large --output /tmp/synthetic_monolith

# Full control
python tools/generate_synthetic_codebase.py \
    --projects 300 \
    --files-per-project 25 \
    --coupling-pct 0.04 \
    --sproc-pct 0.10 \
    --avg-file-kb 12 \
    --seed 42 \
    --output /tmp/custom_monolith
```

### Topology

The first 10% of projects are "hub" projects — core libraries that everything references. This mimics real monoliths where `Common`, `Data`, and `Shared` projects have enormous fan-in. The remaining projects reference 1-3 hubs plus a coupling-percentage of non-hub projects. Deterministic via `--seed` (default: 42).

---

## Full Graph Build Benchmark

**Script**: `tools/benchmark_graph_build.py`

### Two modes

**`--mode full`** (recommended for performance measurement): Calls `build_dependency_graph()` as a black box. Uses ThreadPoolExecutor internally. tracemalloc off by default. This measures real production performance.

**`--mode stages`**: Re-implements graph building step-by-step with per-stage timing. Sequential, tracemalloc on by default. Useful for identifying which stage is slow, but numbers are inflated by instrumentation overhead. **Do not compare stages numbers to full numbers — they measure different things.**

### Usage

```bash
# Generate a codebase first
python tools/generate_synthetic_codebase.py --preset medium --output /tmp/medium

# Production-like benchmark (threaded, no tracemalloc)
python tools/benchmark_graph_build.py /tmp/medium --mode full --runs 3 --warmup

# Per-stage profiling (sequential, with tracemalloc)
python tools/benchmark_graph_build.py /tmp/medium --mode stages --runs 3 --warmup

# Force tracemalloc on/off regardless of mode
python tools/benchmark_graph_build.py /tmp/medium --mode full --tracemalloc
python tools/benchmark_graph_build.py /tmp/medium --mode stages --no-tracemalloc

# Include DB dependency scanning
python tools/benchmark_graph_build.py /tmp/medium --include-db

# JSON output
python tools/benchmark_graph_build.py /tmp/medium --json -o results.json
```

### Stage-level breakdown (--mode stages)

| Stage | What it does |
|-------|-------------|
| `file_discovery` | `rglob("*.csproj")` + `rglob("*.cs")` with parallel workers |
| `csproj_parsing` | Parse each `.csproj` for references, namespace, framework, output type |
| `cs_mapping` | Map `.cs` files to parent projects via reverse directory index |
| `type_extraction` | Read every `.cs` file, extract types + sprocs + using statements + identifiers |
| `graph_construction` | Build `DependencyGraph` nodes + project reference edges |
| `namespace_edges` | Cross-reference `using` statements to add namespace_usage edges |
| `type_usage_edges` | Cached identifiers + set intersection to find type_usage edges (scoped to reachable pairs) |
| `db_scanning` | (optional) Scan for DB patterns: sprocs, DbSet, SQL, connection strings |
| `compute_metrics` | Fan-in, fan-out, instability, coupling score for every project |
| `detect_cycles` | Tarjan's algorithm for strongly connected components |
| `find_clusters` | Louvain community detection for domain clustering |
| `health_dashboard` | Aggregate health observations from metrics, cycles, clusters |

### The tracemalloc caveat

Python's `tracemalloc` hooks every allocation. Stages that do millions of small allocations (identifier extraction, Louvain clustering) appear 3-7x slower under tracemalloc than in uninstrumented runs. Always verify performance claims with `--mode full` (tracemalloc off).

Example: `find_clusters` reports 47s under tracemalloc but runs in 6.8s without it.

---

## Incremental Updates Benchmark

**Script**: `tools/benchmark_incremental.py`

### Usage

```bash
# Default: small + medium presets
python tools/benchmark_incremental.py

# Specific presets
python tools/benchmark_incremental.py --preset small medium large

# Multiple runs for stable medians
python tools/benchmark_incremental.py --runs 3

# JSON output
python tools/benchmark_incremental.py --json -o results.json
```

### 9 Mutation Scenarios

| Scenario | What changes | Triggers global rebuild? |
|----------|-------------|------------------------|
| 1 file usage-only | Add a `using` statement to 1 file | No |
| 5 files usage-only | Add `using` to 5 files | No |
| 10 files usage-only | Add `using` to 10 files | No |
| 1 file declaration change | Add a new class to 1 file | Yes (new type in index) |
| 5 files declaration change | Add new classes to 5 files | Yes |
| 1 new file | Create a new `.cs` file in an existing project | No |
| 5 new files | Create 5 new `.cs` files | No |
| 1 file deleted | Remove a `.cs` file | No |
| 1 csproj modified | Touch a `.csproj` file (add comment) | Yes (project structure change) |

### Results

Speedup factors (median of 3 runs):

| Scenario | 100 projects | 250 projects |
|----------|-------------|-------------|
| 1 file usage-only | ~110x | ~954x |
| 5 files usage-only | ~95x | ~820x |
| 10 files usage-only | ~80x | ~690x |
| 1 file declaration | ~1.3x | ~2.0x |
| 5 files declaration | ~1.2x | ~1.8x |
| 1 new file | ~100x | ~900x |
| 5 new files | ~85x | ~750x |
| 1 file deleted | ~105x | ~920x |
| 1 csproj modified | ~122x | ~253x |

Usage-only changes are the sweet spot (110-954x faster). Declaration changes trigger a broader update of the type inverted index — still faster than a full rebuild, but modest gains. The 0.8x "speedup" seen at xlarge scale for declaration changes is a known issue (patcher overhead exceeds rebuild cost).

---

## Running Your Own Benchmarks

### Quick comparison

```bash
# Generate a test codebase
python tools/generate_synthetic_codebase.py --preset medium --output /tmp/bench

# Real performance (what users experience)
python tools/benchmark_graph_build.py /tmp/bench --mode full --runs 3 --warmup

# Per-stage profiling (for optimization work)
python tools/benchmark_graph_build.py /tmp/bench --mode stages --runs 3 --warmup
```

### Parallel vs Sequential

```bash
# Sequential
time python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope . --disable-multiprocessing

# Parallel (default)
time python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope .
```

For small codebases (< 50 projects), sequential is often faster — multiprocessing has a fixed startup cost of ~200ms. The crossover point is typically around 80-100 projects.

### Using StageTimer in your own code

```python
from tools.benchmark_graph_build import StageTimer

with StageTimer("my_custom_stage") as t:
    # your code here
    pass
print(f"{t.name}: {t.elapsed:.2f}s, heap delta: {t.heap_delta_mb:+.1f} MB")
```

Note: heap metrics require `tracemalloc.start()` before use. Without it, heap values are 0 (this is by design).

---

## Remaining Bottlenecks

| Bottleneck | Current cost | Notes |
|------------|-------------|-------|
| File I/O + regex in type extraction | ~31s at 800 proj / 30K files | Threaded, but still the biggest stage |
| Louvain clustering | 6.8s at 800 projects | Now #2 after tracemalloc fix. Sensitive to edge density. |
| Declaration-change incremental path | 0.8x (slower than full rebuild) | Patcher overhead exceeds rebuild cost at xlarge |
