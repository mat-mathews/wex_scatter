# Domain Clustering

This page covers the domain boundary detection algorithm and extraction feasibility scoring. Both live in `analyzers/domain_analyzer.py` as standalone free functions. The goal: given a dependency graph, find natural service boundaries and tell you how hard it would be to extract each cluster as an independent service.

---

## Two-Level Clustering

### find_clusters

```python
def find_clusters(
    graph: DependencyGraph,
    min_cluster_size: int = 2,
    metrics: Optional[Dict] = None,
    cycles: Optional[List] = None,
) -> List[Cluster]:
```

The algorithm uses two levels to handle both isolated project groups and large interconnected components.

### Level 1: Connected Components

First pass: treat all edges as undirected, find connected components via BFS. This is O(N + E), deterministic (nodes processed in sorted order), and handles the easy case -- projects that are completely disconnected from each other belong to different clusters.

```python
components = graph.connected_components
# Returns List[List[str]], sorted by size descending
```

For a codebase with three independent product lines that share no dependencies, level 1 cleanly separates them into three clusters. Done.

### Level 2: Label Propagation

For connected components with more than 20 nodes (`LABEL_PROPAGATION_THRESHOLD`), level 1 is too coarse -- it would lump everything into one giant cluster. Level 2 sub-divides using weighted label propagation.

```python
def _label_propagation(graph, component_nodes) -> List[List[str]]:
```

How it works:

1. Each node starts with its own name as its label
2. In each iteration, each node adopts the label that has the highest weighted vote from its neighbors
3. Edge weights determine vote strength -- a `project_reference` edge votes louder than a `type_usage` edge
4. Repeat until convergence or 100 iterations (`LABEL_PROPAGATION_MAX_ITERATIONS`)

**Determinism guarantees:**
- Nodes are iterated in sorted order
- Ties are broken by lowest label alphabetically
- No random initialization

```python
# Best label: highest vote, tie-break by lowest label alphabetically
best_label = min(
    label_votes, key=lambda lbl: (-label_votes[lbl], lbl)
)
```

This means the same graph always produces the same clusters. No seed sensitivity, no run-to-run variation.

---

## Cluster Naming

Cluster names are derived from the longest common dot-separated prefix of member project names:

```python
# "GalaxyWorks.Data" + "GalaxyWorks.WebPortal" -> "GalaxyWorks"
# "MyApp.Services.Auth" + "MyApp.Services.Billing" -> "MyApp.Services"
```

If the common prefix is shorter than 3 characters (or empty), the cluster gets a positional fallback name: `cluster_0`, `cluster_1`, etc.

After sorting clusters by size descending, fallback names are re-assigned so `cluster_0` is always the largest unnamed cluster.

---

## Extraction Feasibility Scoring

### score_extraction_feasibility

Given a cluster, how hard would it be to extract it as a standalone service?

```python
def score_extraction_feasibility(
    cluster: Cluster,
    graph: DependencyGraph,
    metrics: Optional[Dict] = None,
    cycles: Optional[List] = None,
) -> Tuple[str, float, Dict[str, float]]:
    # Returns (label, score, penalty_details)
```

### The Four Penalty Factors

The score starts at 1.0 and subtracts weighted penalties:

| Factor | Weight | What It Measures | How It Hurts |
|--------|--------|-----------------|--------------|
| Cross-boundary coupling | 0.40 | Ratio of external edges to total edges | High external coupling means you cannot extract without extensive refactoring of callers. |
| Shared DB objects | 0.25 | Ratio of shared sprocs to total sprocs in cluster | Shared database state is the hardest coupling to break. Two services writing to the same table is a distributed transaction waiting to happen. |
| Circular dependencies | 0.20 | Binary: does any cycle span inside and outside the cluster? | If a cycle crosses the extraction boundary, you cannot extract without breaking the cycle first. It is a hard blocker. |
| API surface breadth | 0.15 | Ratio of externally-used types to total types in cluster | Wide API surface means many external consumers depend on your types. Extracting means building and maintaining a public API contract. |

```python
FEASIBILITY_WEIGHTS = {
    "cross_boundary_penalty": 0.40,
    "shared_db_penalty": 0.25,
    "cycle_penalty": 0.20,
    "api_surface_penalty": 0.15,
}
```

### Score Calculation

```python
total_penalty = sum(details.values())
score = max(0.0, 1.0 - total_penalty)
```

### Score Labels

| Score Range | Label | Meaning |
|-------------|-------|---------|
| >= 0.75 | `easy` | Low coupling, few shared resources. Could extract in a sprint or two. |
| >= 0.50 | `moderate` | Some coupling to manage. Needs planning but doable. |
| >= 0.25 | `hard` | Significant entanglement. Multi-sprint effort with risk. |
| < 0.25 | `very_hard` | Deeply coupled. Consider whether extraction is the right strategy. |

### API Surface Measurement

The API surface breadth penalty counts how many of the cluster's declared types are actually referenced by external projects via `type_usage` edges:

```python
def _compute_api_surface(cluster_projects, graph) -> Tuple[int, int]:
    # Returns (externally_used_type_count, total_type_count)
```

Evidence strings from `type_usage` edges follow the format `path:TypeName`. The function parses these to identify which specific types cross the cluster boundary.

---

## The Cluster Dataclass

```python
@dataclass
class Cluster:
    name: str                                   # Derived or fallback name
    projects: List[str]                         # Sorted project names
    internal_edges: int                         # Edges between cluster members
    external_edges: int                         # Edges crossing the boundary
    cohesion: float                             # internal_edges / max_possible_edges
    coupling_to_outside: float                  # external_edges / total_edges
    cross_boundary_dependencies: List[DependencyEdge]  # Capped at 20 entries
    shared_db_objects: List[str]                # Sprocs used inside and outside
    extraction_feasibility: str                 # "easy" | "moderate" | "hard" | "very_hard"
    feasibility_score: float                    # 0.0 - 1.0
    feasibility_details: Dict[str, float]       # Per-factor penalty breakdown
```

`cross_boundary_dependencies` is capped at `MAX_CROSS_BOUNDARY_EVIDENCE = 20` to keep output manageable. The full edge counts are in `internal_edges` and `external_edges`.

Cohesion is `internal_edges / (n * (n - 1))` where n = number of projects. A cohesion of 1.0 means every project has a direct dependency on every other project in the cluster (complete graph). Typical values are much lower.

---

## Programmatic Usage

```python
from scatter.core.graph import DependencyGraph
from scatter.analyzers.coupling_analyzer import compute_all_metrics, detect_cycles
from scatter.analyzers.domain_analyzer import find_clusters, score_extraction_feasibility

graph: DependencyGraph = ...

# Compute metrics and cycles first (optional but recommended)
metrics = compute_all_metrics(graph)
cycles = detect_cycles(graph)

# Find clusters
clusters = find_clusters(graph, min_cluster_size=2, metrics=metrics, cycles=cycles)

for cluster in clusters:
    print(f"\n{cluster.name} ({len(cluster.projects)} projects)")
    print(f"  Cohesion: {cluster.cohesion:.2f}")
    print(f"  External coupling: {cluster.coupling_to_outside:.2f}")
    print(f"  Feasibility: {cluster.extraction_feasibility} ({cluster.feasibility_score:.2f})")

    # The details dict tells you exactly which factor is the problem
    for factor, penalty in cluster.feasibility_details.items():
        if penalty > 0:
            print(f"    {factor}: -{penalty:.3f}")

    if cluster.shared_db_objects:
        print(f"  Shared DB objects: {', '.join(cluster.shared_db_objects)}")

# Re-score a cluster with different parameters (e.g., after breaking a cycle)
label, score, details = score_extraction_feasibility(clusters[0], graph, metrics, cycles)
```

---

## Interpreting Results

A few patterns to watch for:

**High feasibility + high cohesion = extraction candidate.** The cluster is tightly connected internally and loosely coupled externally. This is the ideal case. Ship it as a service.

**High feasibility + low cohesion = accidental grouping.** The cluster has low external coupling (good) but also low internal coupling (suspicious). It might be a grab bag of unrelated projects that happen to not depend on much. Check the project names -- if they do not share a domain, the cluster is not meaningful.

**Cycles spanning the extraction boundary = must break first.** The `cycle_penalty` is binary (0.0 or 0.20) and it shows up in `feasibility_details["cycle_penalty"]`. If this is non-zero, look at the cycle groups from `detect_cycles()` and find the one that crosses your cluster boundary. Break the cycle, then re-score.

**shared_db_penalty dominating = database coupling.** This is the hardest kind to break. Two services sharing a stored procedure is really two services sharing a database table. Solutions: introduce a data access service, duplicate the sproc, or accept the coupling and co-deploy.

**feasibility_details tells you where to focus.** Do not look at the total score and guess. The details dict breaks it down. If `cross_boundary_penalty` is 0.35 and everything else is near zero, your problem is external coupling, not shared state or cycles. Different problems need different solutions.
