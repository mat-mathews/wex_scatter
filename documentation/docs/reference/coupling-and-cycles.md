# Coupling & Cycle Detection

This page covers the two main structural analysis algorithms: coupling metrics and cycle detection. Both live in `analyzers/coupling_analyzer.py` as standalone free functions that take a `DependencyGraph` and return results. They do not mutate the graph.

---

## Coupling Metrics

### compute_all_metrics

Computes structural metrics for every node in the graph. Single pass: O(N + E).

```python
def compute_all_metrics(
    graph: DependencyGraph,
    coupling_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, ProjectMetrics]:
```

Returns a `Dict[str, ProjectMetrics]` keyed by project name.

### The Metrics

| Metric | Formula | What It Tells You |
|--------|---------|-------------------|
| `fan_in` | Count of incoming `project_reference` edges | How many projects depend on this one. High fan_in = widely depended upon. |
| `fan_out` | Count of outgoing `project_reference` edges | How many projects this one depends on. High fan_out = lots of dependencies. |
| `instability` | `fan_out / (fan_in + fan_out)` | Robert Martin's instability metric. 0.0 = maximally stable (everyone depends on you, you depend on nobody). 1.0 = maximally unstable (you depend on everyone, nobody depends on you). |
| `coupling_score` | Weighted sum of all edge weights touching this node | Total coupling intensity. Counts both incoming and outgoing. Bidirectional edges counted twice -- this is intentional, measuring total coupling load, not unique pairs. |
| `afferent_coupling` | Total incoming edges (all types) | Raw inbound coupling, all edge types. |
| `efferent_coupling` | Total outgoing edges (all types) | Raw outbound coupling, all edge types. |
| `shared_db_density` | Shared sprocs / total sprocs for this project | Fraction of stored procedures that are also used by other projects. 1.0 = every sproc is shared. |
| `type_export_count` | `len(node.type_declarations)` | Number of types declared. Proxy for API surface area. |
| `consumer_count` | Unique project names from incoming edges | Direct consumers across all edge types. |

### Coupling Score Calculation

The coupling score uses configurable weights per edge type:

```python
DEFAULT_COUPLING_WEIGHTS = {
    "project_reference": 1.0,
    "namespace_usage": 0.5,
    "type_usage": 0.3,
    "sproc_shared": 0.8,
}
```

For each node, the score is:

```
coupling_score = sum(weight[e.edge_type] * e.weight for e in outgoing_edges)
               + sum(weight[e.edge_type] * e.weight for e in incoming_edges)
```

Where `e.weight` is the edge's own weight (e.g., the number of files evidencing a namespace_usage edge). So a `namespace_usage` edge with evidence in 5 files contributes `0.5 * 5 = 2.5` to the coupling score.

Override these weights via `.scatter.yaml`:

```yaml
graph:
  coupling_weights:
    project_reference: 1.0
    sproc_shared: 0.8
    namespace_usage: 0.5
    type_usage: 0.3
```

### rank_by_coupling

Sorts projects by coupling_score descending and returns the top N:

```python
def rank_by_coupling(
    metrics: Dict[str, ProjectMetrics], top_n: int = 10
) -> List[Tuple[str, ProjectMetrics]]:
```

### Interpreting Metrics: An Example

Consider a codebase with these projects:

| Project | fan_in | fan_out | instability | coupling_score |
|---------|--------|---------|-------------|----------------|
| GalaxyWorks.Data | 4 | 0 | 0.0 | 12.8 |
| MyDotNetApp.Consumer | 0 | 2 | 1.0 | 3.2 |
| MyGalaxyConsumerApp | 0 | 1 | 1.0 | 1.5 |
| BatchProcessor | 0 | 3 | 1.0 | 4.1 |

GalaxyWorks.Data has the highest coupling score and instability of 0.0. It is the "stable core" -- everyone depends on it. Changing it has maximum blast radius.

BatchProcessor has instability 1.0 and moderate coupling. It depends on everything but nothing depends on it. It is a leaf node -- safe to change, easy to extract.

---

## Cycle Detection

### detect_cycles

Finds all circular dependency groups using Tarjan's strongly connected components algorithm.

```python
def detect_cycles(
    graph: DependencyGraph,
    edge_types: Optional[Set[str]] = None,
) -> List[CycleGroup]:
```

**Default behavior:** Only considers `project_reference` edges. Namespace and type usage cycles are common and benign -- they indicate shared conventions, not build-order violations. Pass `edge_types` explicitly to include other edge types.

**Returns:** `List[CycleGroup]` sorted by size ascending. Smallest cycles first because they are typically the easiest to break.

### The Algorithm: Iterative Tarjan's SCC

Standard Tarjan's SCC is recursive, which hits Python's recursion limit (~1000) on large graphs. The implementation uses an explicit call stack:

```python
# Explicit call stack: (node, neighbor_list, neighbor_index)
call_stack: List[Tuple[str, list, int]] = []
```

Each frame stores the node being processed and an index into its sorted neighbor list. When all neighbors are processed, the frame is popped and lowlink values propagate upward. This is functionally identical to the recursive version but handles graphs of any size.

**Complexity:** O(N + E) time, O(N) space.

**Determinism:** Nodes and neighbors are processed in sorted order, so the same graph always produces the same SCCs in the same order.

### CycleGroup

```python
@dataclass
class CycleGroup:
    projects: List[str]        # Project names in the SCC, sorted alphabetically
    shortest_cycle: List[str]  # One representative shortest cycle within the SCC
    edge_count: int            # Number of edges within the SCC

    @property
    def size(self) -> int:
        return len(self.projects)
```

The `shortest_cycle` is found via BFS from each node in the SCC (or just the first node for SCCs larger than 50 projects). It uses predecessor-based path reconstruction rather than storing full paths per node, keeping memory at O(N) instead of O(N^2):

```python
# BFS to find shortest path back to start
predecessor: Dict[str, str] = {}
queue: deque[str] = deque()

for neighbor in sorted(adjacency.get(start, set())):
    if neighbor == start:
        return [start]  # Self-loop
    predecessor[neighbor] = start
    queue.append(neighbor)

# ... standard BFS, reconstruct path from predecessor chain on hit
```

### Programmatic Usage

```python
from scatter.core.graph import DependencyGraph
from scatter.analyzers.coupling_analyzer import (
    compute_all_metrics,
    rank_by_coupling,
    detect_cycles,
)

# Load or build your graph
graph: DependencyGraph = ...

# Compute metrics for all nodes
metrics = compute_all_metrics(graph)

# Get the 5 most coupled projects
top_5 = rank_by_coupling(metrics, top_n=5)
for name, m in top_5:
    print(f"{name}: score={m.coupling_score:.1f}, instability={m.instability:.2f}")

# Detect cycles (project_reference edges only, the default)
cycles = detect_cycles(graph)
for cg in cycles:
    print(f"Cycle ({cg.size} projects): {' -> '.join(cg.shortest_cycle)}")
    print(f"  Projects: {', '.join(cg.projects)}")
    print(f"  Internal edges: {cg.edge_count}")

# Detect cycles including namespace_usage edges
all_cycles = detect_cycles(graph, edge_types={"project_reference", "namespace_usage"})
```

### Why Smallest-First Sorting

Cycles are sorted by size ascending because smaller cycles are:

1. Easier to understand (2-3 projects vs 15)
2. Easier to break (fewer edges to redirect)
3. Often the root cause of larger cycles (break the small one and the large one dissolves)

The `shortest_cycle` field within each CycleGroup gives you the tightest loop to focus on. If you are looking for which edge to cut, start there.
