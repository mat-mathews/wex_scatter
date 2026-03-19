# Consumer Detection Pipeline

The consumer pipeline is Scatter's answer to the question: "If I change this project, who is affected?" It is a 5-stage filter funnel that progressively narrows the candidate set from "every .csproj in the search scope" down to "projects that actually call this specific method." Each stage is cheaper to evaluate but stricter in its criteria.

The pipeline lives in `analyzers/consumer_analyzer.py`.

---

## The 5 Stages

### Stage 1: File Discovery

Find all `.csproj` files in the search scope.

- **Filesystem path:** Parallel glob for `*.csproj` across the search scope directory tree.
- **Graph path:** Read `graph.node_count` from the cached graph. No filesystem I/O.

### Stage 2: ProjectReference Filter

Keep only projects that have a `<ProjectReference>` to the target project.

- **Filesystem path:** Parse each candidate `.csproj` as XML, resolve the `Include` path, compare against the target. Parallelized via `ProcessPoolExecutor`.
- **Graph path:** `graph.get_edges_to(target_name)` filtered to `edge_type == "project_reference"`. O(in-degree).

This is typically the biggest drop. A 250-project codebase might have only 8-12 projects that directly reference any given target.

### Stage 3: Namespace Filter

Keep only projects that have `using TargetNamespace;` (or a sub-namespace) in their .cs files.

Always runs on the filesystem -- the graph does not cache file contents. For each surviving consumer, discover its .cs files, then search for the target namespace using a compiled regex:

```python
using_pattern = re.compile(
    rf"(?:^|;|\{{)\s*(?:global\s+)?using\s+{re.escape(target_namespace)}(?:\.[A-Za-z0-9_.]+)?\s*;",
    re.MULTILINE
)
```

This pattern handles standard `using`, `global using`, and sub-namespace imports (e.g., `using GalaxyWorks.Data.Models;` when the target namespace is `GalaxyWorks.Data`).

Files that match are tracked as `relevant_files` on the consumer and carried forward to later stages.

### Stage 4: Class Filter (Optional)

Keep only projects that reference the specific class/type name. Only runs if `--class-name` is provided.

Uses word-boundary regex on the `relevant_files` from stage 3:

```python
class_pattern = re.compile(rf"\b{re.escape(class_name)}\b")
```

### Stage 5: Method Filter (Optional)

Keep only projects that call the specific method. Only runs if `--method-name` is provided (requires `--class-name`).

Searches for the pattern `.MethodName(`:

```python
method_pattern = re.compile(rf"\.\s*{re.escape(method_name)}\s*\(")
```

---

## The FilterPipeline

Every run produces a `FilterPipeline` dataclass that records what happened at each stage:

```python
@dataclass
class FilterPipeline:
    search_scope: str
    total_projects_scanned: int
    total_files_scanned: int
    stages: List[FilterStage]
    target_project: str
    target_namespace: str
    class_filter: Optional[str]
    method_filter: Optional[str]
```

Each stage is a `FilterStage`:

```python
@dataclass
class FilterStage:
    name: str           # "discovery", "project_reference", "namespace", "class", "method"
    input_count: int    # Projects entering this stage
    output_count: int   # Projects passing this stage
    source: str         # "filesystem" or "graph"
```

### The Arrow Chain

The pipeline produces a human-readable arrow chain for reports:

```
Filter: 250 -> 12 project refs -> 8 namespace -> 4 class match -> 2 method match
```

With graph acceleration:

```
Filter: 250[graph] -> 12 project refs[graph] -> 8 namespace -> 4 class match
```

The `[graph]` annotation tells you which stages used the cached graph instead of the filesystem.

### Diagnostic Hints

When a stage drops to zero, it is useful to know which filter caused the dead end. The pipeline tracks `STAGE_INPUT_LABELS` so reporters can tell you "0 of 12 project-reference-matching projects use the target namespace" rather than just "0 projects found."

Stage name constants (`STAGE_DISCOVERY`, `STAGE_PROJECT_REFERENCE`, etc.) are defined in `core/models.py` and used everywhere instead of raw strings.

---

## Graph Acceleration

### How It Works

When a graph cache exists and the target project is in the graph, stages 1-2 are replaced with a reverse-index lookup:

```python
def _lookup_consumers_from_graph(graph, target_csproj_path):
    target_name = target_csproj_path.stem

    if graph.get_node(target_name) is None:
        return None  # Fall back to filesystem

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
```

Only `project_reference` edges are used for stage 2. The graph has four edge types, but using `namespace_usage` or `type_usage` edges would widen the consumer set beyond what the filesystem path finds, causing correctness divergence. The graph acceleration must produce the same candidate set as the filesystem path.

### Fallback Behavior

If the target is not in the graph (stale cache, new project, scope mismatch), `_lookup_consumers_from_graph` returns `None` and the pipeline transparently falls back to filesystem scanning. No caller code changes needed.

### When Does It Help?

The acceleration matters most on large codebases where stage 1-2 is expensive:

| Codebase Size | Filesystem Stages 1-2 | Graph Stages 1-2 |
|---------------|----------------------|-------------------|
| 50 projects | ~0.3s | ~0.001s |
| 250 projects | ~2.1s | ~0.001s |
| 500 projects | ~5.8s | ~0.001s |

Stages 3-5 still read .cs files from disk regardless of source, so the total speedup depends on how many consumers survive stage 2.

---

## Multiprocessing Details

Without the graph (first run or `--no-graph`), the pipeline parallelizes four operations using `ProcessPoolExecutor`:

1. **File discovery** (`find_files_with_pattern_parallel`): Glob for .csproj and .cs files
2. **XML parsing** (`parse_csproj_files_parallel`): Parse .csproj files to check ProjectReference
3. **Content analysis** (`analyze_cs_files_parallel`): Search .cs files for namespace/class/method patterns
4. **Project mapping** (`map_cs_to_projects_parallel`): Map .cs files to parent .csproj projects

### Adaptive Worker Scaling

Worker count scales with workload to avoid overhead on small tasks:

| File Count | Workers |
|------------|---------|
| < 200 | min(max_workers, 4) |
| < 1000 | min(max_workers, 8) |
| >= 1000 | max_workers (default: `min(32, cpu_count + 4)`) |

Below the chunk size threshold (50 for .cs files, 25 for .csproj files), the pipeline skips multiprocessing entirely and runs sequentially. The overhead of spawning processes is not worth it for small batches.

### Chunk Sizes

Configurable via CLI flags:

| Parameter | Default | What It Controls |
|-----------|---------|-----------------|
| `--chunk-size` | 75 | Directories per worker chunk (file discovery) |
| `--cs-analysis-chunk-size` | 50 | .cs files per worker batch (content analysis) |
| `--csproj-analysis-chunk-size` | 25 | .csproj files per worker batch (XML parsing) |

These can also be set via config:

```yaml
multiprocessing:
  disabled: false
  max_workers: 16
  chunk_size: 100
```

### Graceful Degradation

Every parallel operation has a try/except that falls back to sequential processing:

```python
try:
    # ... parallel execution ...
except Exception as e:
    logging.warning(f"Parallel analysis failed: {e}. Falling back to sequential.")
    return analyze_cs_files_batch((cs_files, analysis_config))
```

This means Scatter never crashes due to multiprocessing issues -- it just gets slower. The `--disable-multiprocessing` flag forces sequential mode for debugging or environments where `fork()` is problematic (some macOS configurations, some CI containers).

---

## Putting It All Together

A complete target-project analysis with all stages:

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
        --search-scope /path/to/monorepo \
        --class-name PortalDataService \
        --method-name GetPortalConfig
```

What happens:

1. **Discovery:** Find 247 .csproj files in `/path/to/monorepo`
2. **ProjectReference:** 247 candidates -> 11 have `<ProjectReference>` to GalaxyWorks.Data
3. **Namespace:** 11 candidates -> 8 have `using GalaxyWorks.Data;` in their .cs files
4. **Class:** 8 candidates -> 4 reference `PortalDataService`
5. **Method:** 4 candidates -> 2 call `.GetPortalConfig(`

Output:

```
Filter: 247 -> 11 project refs -> 8 namespace -> 4 class match -> 2 method match
```

If the graph cache exists, stages 1-2 produce the same result in microseconds:

```
Filter: 247[graph] -> 11 project refs[graph] -> 8 namespace -> 4 class match -> 2 method match
```

The FilterPipeline is included in all output formats (console, JSON, CSV, markdown) so you always know how the funnel narrowed.
