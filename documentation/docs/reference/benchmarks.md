# Benchmarks

Performance measurement tools and results. Everything here is reproducible on your own machine with the tools in `tools/`.

---

## Synthetic Codebase Generator

**Script**: `tools/generate_synthetic_codebase.py`

Generates a realistic .NET monolith directory tree that exercises every scatter code path: type declarations, `using` statements, project references, sproc references, DbSet patterns, SQL strings, comments, and multiple `.sln` files.

### Presets

| Preset | Projects | Files | Coupling % | Sproc % | Avg File KB |
|--------|----------|-------|------------|---------|-------------|
| `small` | 100 | ~1,000 | 5% | 15% | 8 |
| `medium` | 250 | ~5,000 | 4% | 12% | 15 |
| `large` | 500 | ~15,000 | 3% | 10% | 20 |
| `xlarge` | 800 | ~32,000 | 2% | 8% | 25 |

### Custom Generation

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

### What Gets Generated

- **`.csproj` files**: Both SDK-style (`<Project Sdk="Microsoft.NET.Sdk">`) and legacy framework-style (`ToolsVersion="15.0"`) targeting net8.0, net6.0, net48, v4.7.2, and v4.6.1
- **`.cs` files**: Type declarations (class, interface, struct, enum, record) with realistic method bodies, sproc references in string literals, `using` statements, DbSet/DbContext patterns, SQL strings, and XML doc comments
- **`.sln` files**: Three tiers -- domain solutions (per namespace prefix), master solutions (30-50% of all projects, like every monolith's "everything" solution), and team solutions (small 5-15 project groupings)

### Topology

The first 10% of projects are designated "hub" projects -- core libraries that everything references. This mimics real monoliths where `Common`, `Data`, and `Shared` projects have enormous fan-in. The remaining projects reference 1-3 hubs plus a coupling-percentage of non-hub projects.

Sproc references are shared across 3-6 projects to trigger the `db_hotspot` detection in Scatter's DB scanner.

### Determinism

Pass `--seed` for reproducible output. The default seed is 42. Same seed + same parameters = identical file tree, every time. Useful for comparing benchmark runs across code changes.

---

## Full Graph Build Benchmark

**Script**: `tools/benchmark_graph_build.py`

Instruments Scatter's actual `build_dependency_graph()` and all post-build analysis stages with wall-clock timing and memory measurement (tracemalloc for Python heap, `resource.ru_maxrss` for process peak RSS).

### Usage

```bash
# Generate a codebase first
python tools/generate_synthetic_codebase.py --preset medium --output /tmp/medium

# Run the benchmark
python tools/benchmark_graph_build.py /tmp/medium

# Instrumented mode (default) -- breaks build into internal stages
python tools/benchmark_graph_build.py /tmp/medium --mode stages

# Black-box mode -- times build_dependency_graph() as a single call
python tools/benchmark_graph_build.py /tmp/medium --mode full

# Multiple runs with warmup (populates OS file cache)
python tools/benchmark_graph_build.py /tmp/medium --runs 5 --warmup

# Include DB dependency scanning
python tools/benchmark_graph_build.py /tmp/medium --include-db

# JSON output
python tools/benchmark_graph_build.py /tmp/medium --json -o results.json
```

### Stage-Level Instrumentation

In `--mode stages` (default), the benchmark measures each internal phase separately:

| Stage | What it does |
|-------|-------------|
| `file_discovery` | `rglob("*.csproj")` + `rglob("*.cs")` with parallel workers |
| `csproj_parsing` | Parse each `.csproj` for references, namespace, framework, output type |
| `cs_mapping` | Map `.cs` files to parent projects via reverse directory index |
| `type_extraction` | Read every `.cs` file, extract types + sprocs + using statements |
| `graph_construction` | Build `DependencyGraph` nodes + project reference edges |
| `namespace_edges` | Cross-reference `using` statements to add namespace_usage edges |
| `type_usage_edges` | Inverted index + set intersection to find type_usage edges |
| `db_scanning` | (optional) Scan for DB patterns: sprocs, DbSet, SQL, connection strings |
| `compute_metrics` | Fan-in, fan-out, instability, coupling score for every project |
| `detect_cycles` | Tarjan's algorithm for strongly connected components |
| `find_clusters` | Louvain community detection for domain clustering |
| `health_dashboard` | Aggregate health observations from metrics, cycles, clusters |

### Results

These numbers are from a 2023 MacBook Pro (M3 Pro), single run, no warmup. Your mileage will vary based on disk speed and CPU.

| Preset | Projects | .cs Files | Total Time | Bottleneck |
|--------|----------|-----------|------------|------------|
| `small` | 100 | ~1,000 | ~1.1s | type_usage_edges |
| `medium` | 250 | ~5,000 | ~9.5s | type_usage_edges |
| `large` | 500 | ~15,000 | ~42.8s | type_usage_edges |

### The Type Usage Story

Before the inverted index optimization, the `type_usage_edges` stage was an O(P * T * F) nested loop: for each project, for each declared type across all other projects, grep every `.cs` file. At 100 projects, that stage alone took 172 seconds. It was 91% of total build time.

The fix: build an inverted index of `type_name -> set(owning_projects)`, then for each `.cs` file, extract all identifiers via a fast regex (`[A-Za-z_]\w*`), intersect with the type name set, and look up owners. This flipped the algorithm to O(F * I) where I is the average identifier count per file. The same 100-project build dropped from 172s to 1.7s.

The lesson: when you see a stage consuming 90%+ of build time, the algorithm is wrong. The data structure is wrong. Measure first, then think about the shape of the data.

---

## Incremental Updates Benchmark

**Script**: `tools/benchmark_incremental.py`

The whole point of the graph patcher is to avoid full rebuilds. This benchmark measures exactly how much time that saves.

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

### How It Works

For each preset size:

1. Generate a synthetic codebase
2. Build a full graph (baseline timing)
3. Capture v2 facts (file hashes, project hashes)
4. For each of 9 mutation scenarios:
   a. Reset codebase to clean state
   b. Rebuild baseline graph + facts
   c. Apply the mutation
   d. Time `patch_graph()` (incremental)
   e. Calculate speedup vs full rebuild

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

### Key Findings

**Usage-only changes are the sweet spot.** 110-954x faster. The patcher re-reads only the changed files, recomputes their edges, and splices them into the existing graph. No type index rebuild needed.

**Declaration changes trigger a broader update.** When a new type appears (or an existing one disappears), the type-to-project inverted index needs updating, and every project that might reference the affected types needs its edges recomputed. Speedup drops to 1.3-2x -- still faster than a full rebuild, but the gains are modest.

**Csproj changes are handled efficiently despite the label.** A touched `.csproj` could mean new project references, but the patcher checks whether the structural content actually changed. Adding a comment (no structural change) gets the fast path; adding a new `<ProjectReference>` triggers a targeted rebuild of that project's edges.

---

## Running Your Own Benchmarks

### Parallel vs Sequential

Compare multiprocessing overhead on your own codebase:

```bash
# Sequential
time python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope . --disable-multiprocessing

# Parallel (default)
time python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope .
```

For small codebases (< 50 projects), sequential is often faster -- multiprocessing has a fixed startup cost of ~200ms for spawning workers and serializing tasks. The crossover point is typically around 80-100 projects.

### Profiling a Specific Stage

The `StageTimer` context manager in the benchmark script is reusable:

```python
from tools.benchmark_graph_build import StageTimer
import tracemalloc

tracemalloc.start()
with StageTimer("my_custom_stage") as t:
    # your code here
    pass
print(f"{t.name}: {t.elapsed:.2f}s, heap delta: {t.heap_delta_mb:+.1f} MB")
```

It gives you wall-clock time, heap allocation delta, and peak heap -- enough to identify both CPU-bound and memory-bound bottlenecks.
