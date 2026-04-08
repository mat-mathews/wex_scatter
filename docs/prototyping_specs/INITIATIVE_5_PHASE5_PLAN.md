# Initiative 5, Phase 5: Domain Boundary Detection — Detailed Implementation Plan

## Overview

Phase 5 adds **domain boundary detection** to the dependency graph pipeline. Given a `DependencyGraph` (Phase 1) with coupling metrics (Phase 2), cache layer (Phase 3), and optional DB edges (Phase 4), this phase clusters tightly-connected projects into logical "domains" and scores how feasible it would be to extract each cluster as an independent service.

The core deliverable is `scatter/analyzers/domain_analyzer.py` — standalone free functions (consistent with coupling_analyzer.py's SRP pattern) that accept a `DependencyGraph` and return `Cluster` objects with cohesion metrics and extraction feasibility ratings.

## Scope

**In scope:**
- `scatter/analyzers/domain_analyzer.py` — clustering + feasibility scoring
- `scatter/ai/base.py` — add `BOUNDARY_ASSESSMENT` to `AITaskType`
- `scatter/__main__.py` — integrate domain output into `--graph` mode (console + JSON)
- `scatter/__init__.py` — exports
- `test_domain.py` — ~14 tests

**Not in scope:**
- New CLI flags (domains run automatically in `--graph` mode)
- AI-powered boundary narratives (stub only, future phase)
- Config additions (hardcoded constants are sufficient)

---

## 1. Data Model

### 1.1 `Cluster` dataclass

```python
@dataclass
class Cluster:
    """A group of tightly-connected projects — a candidate domain/service boundary."""

    name: str
    # Auto-generated from longest common namespace prefix of member projects,
    # or "cluster_N" if no common prefix exists.

    projects: List[str]
    # Project names (sorted alphabetically) belonging to this cluster.

    internal_edges: int
    # Count of edges where both source AND target are within this cluster.

    external_edges: int
    # Count of edges where exactly one endpoint is in this cluster.

    cohesion: float
    # internal_edges / max_possible_internal_edges.
    # max_possible = n * (n - 1) for directed graph where n = len(projects).
    # 0.0 if cluster has fewer than 2 projects.

    coupling_to_outside: float
    # external_edges / (internal_edges + external_edges).
    # 0.0 if total edges == 0.

    cross_boundary_dependencies: List[DependencyEdge]
    # Edge objects crossing the cluster boundary (capped at 20).

    shared_db_objects: List[str]
    # Stored procedures / DB objects referenced by projects both inside
    # and outside this cluster.

    extraction_feasibility: str
    # One of: "easy", "moderate", "hard", "very_hard".

    feasibility_score: float
    # Numeric score 0.0 - 1.0.  1.0 = trivially extractable.

    feasibility_details: Dict[str, float] = field(default_factory=dict)
    # Breakdown: {"cross_boundary_penalty": 0.3, "shared_db_penalty": 0.2,
    #             "cycle_penalty": 0.0, "api_surface_penalty": 0.1}
```

### 1.2 Constants

```python
MAX_CROSS_BOUNDARY_EVIDENCE = 20
LABEL_PROPAGATION_THRESHOLD = 20    # component size above which label prop runs
LABEL_PROPAGATION_MAX_ITERATIONS = 100

FEASIBILITY_THRESHOLDS = {
    0.75: "easy",
    0.50: "moderate",
    0.25: "hard",
    0.00: "very_hard",
}
```

---

## 2. Clustering Algorithm

### 2.1 Two-Level Strategy

**Level 1: Connected Components (always runs)**

Reuses `DependencyGraph.connected_components` (graph.py:289-316). Treats all edges as undirected via BFS. O(N+E), deterministic. Handles the common case — separate project groups like GalaxyWorks vs MyDotNetApp.

**Level 2: Label Propagation (conditional, for large components)**

For any connected component with > `LABEL_PROPAGATION_THRESHOLD` (20) nodes, apply weighted label propagation to detect sub-communities.

```
function _label_propagation(graph, component_nodes):
    labels = {node: node for node in sorted(component_nodes)}

    for iteration in range(MAX_ITERATIONS):
        changed = False
        for node in sorted(component_nodes):  # sorted for determinism
            neighbor_labels = []
            for neighbor in sorted(get_all_neighbors(node)):
                if neighbor in component_set:
                    edges = graph.get_edges_between(node, neighbor)
                    total_weight = sum(e.weight for e in edges)
                    neighbor_labels.append((labels[neighbor], total_weight))

            if not neighbor_labels:
                continue

            # Weighted vote per label
            label_votes = defaultdict(float)
            for label, weight in neighbor_labels:
                label_votes[label] += weight

            # Tie-break: lowest label alphabetically (determinism)
            best_label = min(label_votes, key=lambda l: (-label_votes[l], l))

            if best_label != labels[node]:
                labels[node] = best_label
                changed = True

        if not changed:
            break  # converged

    # Group nodes by final label
    return [sorted(members) for members in groups.values()]
```

**Determinism guarantees:**
- Nodes iterated in sorted alphabetical order
- Ties broken by lowest label alphabetically
- Max iterations capped at 100

### 2.2 Cluster Name Derivation

```python
def _derive_cluster_name(projects: List[str], cluster_index: int) -> str:
    """Derive name from longest common prefix with '.' as separator.

    ["GalaxyWorks.Data", "GalaxyWorks.WebPortal"] -> "GalaxyWorks"
    ["Alpha", "Beta"] -> "cluster_0"
    """
```

Strategy:
1. Split each project name by `.` into segments
2. Find longest common prefix of segments
3. If prefix has >= 1 segment (and >= 3 chars), use it
4. Otherwise, fall back to `"cluster_{cluster_index}"`

### 2.3 Cluster Metric Computation

For each cluster after grouping:

```
internal_edges = count edges where BOTH source AND target ∈ cluster.projects
external_edges = count edges where EXACTLY ONE of source/target ∈ cluster.projects

n = len(cluster.projects)
max_possible = n * (n - 1)    # directed graph
cohesion = internal_edges / max_possible if max_possible > 0 else 0.0

total = internal_edges + external_edges
coupling_to_outside = external_edges / total if total > 0 else 0.0
```

---

## 3. Extraction Feasibility Scoring

### 3.1 Algorithm

`score_extraction_feasibility()` computes a score from 0.0 (deeply entangled) to 1.0 (trivially extractable) using four weighted penalties:

| Factor | Weight | Calculation | Rationale |
|--------|--------|-------------|-----------|
| Cross-boundary coupling | 0.40 | `coupling_to_outside` | More external edges = harder to extract |
| Shared DB objects | 0.25 | `len(shared_db_objects) / max(1, total_db_objects_in_cluster)` | Shared mutable state is hardest to break |
| Circular dependencies | 0.20 | `1.0 if any cycle includes both internal and external projects, else 0.0` | Cross-boundary cycles require simultaneous refactoring |
| API surface breadth | 0.15 | `externally_used_types / max(1, total_types_in_cluster)` | Large API surface = many consumers need updating |

**Score computation:**
```
penalties = {
    "cross_boundary_penalty": coupling_to_outside * 0.40,
    "shared_db_penalty": shared_db_ratio * 0.25,
    "cycle_penalty": has_cross_boundary_cycle * 0.20,
    "api_surface_penalty": api_surface_ratio * 0.15,
}
total_penalty = sum(penalties.values())
feasibility_score = max(0.0, 1.0 - total_penalty)
```

**Label mapping:**
```
score >= 0.75 → "easy"
score >= 0.50 → "moderate"
score >= 0.25 → "hard"
score <  0.25 → "very_hard"
```

### 3.2 Helper: Shared DB Objects

```python
def _find_shared_db_objects(cluster_projects: Set[str], graph: DependencyGraph) -> List[str]:
    """Find sprocs referenced by projects both inside and outside the cluster."""
    sproc_map: Dict[str, Set[str]] = defaultdict(set)
    for node in graph.get_all_nodes():
        for sproc in node.sproc_references:
            sproc_map[sproc].add(node.name)

    shared = []
    for sproc, refs in sproc_map.items():
        inside = refs & cluster_projects
        outside = refs - cluster_projects
        if inside and outside:
            shared.append(sproc)
    return sorted(shared)
```

### 3.3 Helper: API Surface

```python
def _compute_api_surface(cluster_projects: Set[str], graph: DependencyGraph) -> Tuple[int, int]:
    """Returns (externally_used_type_count, total_type_count).

    Checks type_usage edges crossing the boundary and matches evidence
    against the cluster's type_declarations.
    """
```

### 3.4 Cycle Penalty

Uses pre-computed `cycles: List[CycleGroup]` from `detect_cycles()`. A cycle contributes to the penalty if it contains at least one project inside the cluster AND at least one project outside. If `cycles` is `None` (not pre-computed), cycle penalty is 0.0.

---

## 4. Function Signatures

All in `scatter/analyzers/domain_analyzer.py`:

```python
def find_clusters(
    graph: DependencyGraph,
    min_cluster_size: int = 2,
    metrics: Optional[Dict[str, ProjectMetrics]] = None,
    cycles: Optional[List[CycleGroup]] = None,
) -> List[Cluster]:
    """Detect natural service boundaries via two-level clustering.

    Returns List[Cluster] sorted by size descending.
    """

def score_extraction_feasibility(
    cluster: Cluster,
    graph: DependencyGraph,
    metrics: Optional[Dict[str, ProjectMetrics]] = None,
    cycles: Optional[List[CycleGroup]] = None,
) -> Tuple[str, float, Dict[str, float]]:
    """Score extraction feasibility. Returns (label, score, details)."""

def _label_propagation(
    graph: DependencyGraph,
    component_nodes: List[str],
) -> List[List[str]]:
    """Label propagation sub-clustering for large components."""

def _derive_cluster_name(projects: List[str], cluster_index: int) -> str:
    """Derive human-readable cluster name from longest common prefix."""

def _find_shared_db_objects(
    cluster_projects: Set[str],
    graph: DependencyGraph,
) -> List[str]:
    """Find DB objects referenced both inside and outside the cluster."""

def _compute_api_surface(
    cluster_projects: Set[str],
    graph: DependencyGraph,
) -> Tuple[int, int]:
    """Returns (externally_used_type_count, total_type_count)."""

def _build_cluster(
    projects: List[str],
    graph: DependencyGraph,
    cluster_index: int,
    metrics: Optional[Dict[str, ProjectMetrics]] = None,
    cycles: Optional[List[CycleGroup]] = None,
) -> Cluster:
    """Construct a Cluster with all computed fields."""
```

---

## 5. CLI Integration

### 5.1 `__main__.py` Changes

Domain analysis runs automatically in `--graph` mode. No new CLI flag needed.

In the `is_graph_mode` block (currently lines 713-830), after computing metrics and cycles (~line 757), add:

```python
# Domain analysis
from scatter.analyzers.domain_analyzer import find_clusters

clusters = find_clusters(graph, min_cluster_size=2, metrics=metrics, cycles=cycles)
```

### 5.2 Console Output Addition

After the existing "Circular Dependencies" section (~line 827), add:

```
  Domain Clusters:
  Cluster                      Size  Cohesion  Coupling  Feasibility
  ----------------------------------------------------------------
  GalaxyWorks                     5     0.40      0.15  moderate (0.623)
  MyDotNetApp                     2     1.00      0.00  easy (1.000)
```

### 5.3 JSON Output Addition

Add to `graph_report` dict (after `"cycles"` key, ~line 796):

```python
"clusters": [
    {
        "name": clu.name,
        "projects": clu.projects,
        "size": len(clu.projects),
        "internal_edges": clu.internal_edges,
        "external_edges": clu.external_edges,
        "cohesion": round(clu.cohesion, 3),
        "coupling_to_outside": round(clu.coupling_to_outside, 3),
        "extraction_feasibility": clu.extraction_feasibility,
        "feasibility_score": round(clu.feasibility_score, 3),
        "feasibility_details": {k: round(v, 3) for k, v in clu.feasibility_details.items()},
        "shared_db_objects": clu.shared_db_objects,
    }
    for clu in clusters
],
```

Also add `"cluster_count": len(clusters)` to the `"summary"` dict.

---

## 6. AITaskType Extension

In `scatter/ai/base.py`, add one enum value:

```python
BOUNDARY_ASSESSMENT = "boundary_assessment"   # NEW
```

This enables future AI-generated boundary narratives. No provider changes needed now.

---

## 7. Exports

In `scatter/__init__.py`, add:

```python
from scatter.analyzers.domain_analyzer import (
    Cluster,
    find_clusters,
    score_extraction_feasibility,
)
```

---

## 8. Files to Create/Modify

| File | Action | Size |
|------|--------|------|
| `scatter/analyzers/domain_analyzer.py` | **Create** | ~250 lines |
| `scatter/ai/base.py` | **Modify** | +1 line |
| `scatter/__main__.py` | **Modify** | ~+40 lines |
| `scatter/__init__.py` | **Modify** | +5 lines |
| `test_domain.py` | **Create** | ~300 lines |

---

## 9. Test Plan — `test_domain.py`

### 9.1 Shared Fixtures

```python
def _make_graph(*edges) -> DependencyGraph:
    """Build a graph from (source, target, edge_type) tuples.
    Auto-creates ProjectNode for each unique name."""

def _galaxy_graph() -> DependencyGraph:
    """Graph mimicking sample projects:
    GalaxyWorks.Data (hub) -> WebPortal, BatchProcessor, ConsumerApp, ConsumerApp2
    MyDotNetApp -> MyDotNetApp.Consumer
    MyDotNetApp2.Exclude (isolated)
    """
```

### 9.2 TestFindClusters (8 tests)

| # | Test | What it verifies |
|---|------|-----------------|
| 1 | `test_two_clusters_in_sample_projects` | Real sample projects produce 2 clusters (GalaxyWorks + MyDotNetApp). MyDotNetApp2.Exclude excluded (size < 2). |
| 2 | `test_isolated_node_excluded` | Singleton nodes don't appear in any cluster with min_cluster_size=2. |
| 3 | `test_fully_connected_cohesion` | 3-node fully connected graph → cohesion = 1.0. |
| 4 | `test_min_cluster_size_filter` | With min_cluster_size=3, small clusters are excluded. |
| 5 | `test_single_component_graph` | 4 nodes all connected, below label prop threshold → exactly 1 cluster. |
| 6 | `test_empty_graph` | Empty graph → empty list. |
| 7 | `test_deterministic_results` | 5 calls on same graph produce identical results. |
| 8 | `test_large_component_triggers_label_propagation` | 25-node graph with two loosely-connected sub-groups → 2 clusters. |

### 9.3 TestClusterNameDerivation (2 tests)

| # | Test | What it verifies |
|---|------|-----------------|
| 9 | `test_common_prefix_name` | ["GalaxyWorks.Data", "GalaxyWorks.WebPortal"] → "GalaxyWorks" |
| 10 | `test_no_common_prefix_fallback` | ["Alpha", "Beta", "Gamma"] → "cluster_N" |

### 9.4 TestExtractionFeasibility (4 tests)

| # | Test | What it verifies |
|---|------|-----------------|
| 11 | `test_easy_extraction` | Isolated cluster → score >= 0.75, label "easy" |
| 12 | `test_hard_extraction` | High coupling + shared DB + cross-boundary cycle → "hard" or "very_hard" |
| 13 | `test_isolated_cluster_is_easy` | Zero external edges → "easy" |
| 14 | `test_feasibility_details_breakdown` | All 4 penalty keys present, sum matches 1.0 - score |

### 9.5 Summary

| Class | Count |
|-------|-------|
| TestFindClusters | 8 |
| TestClusterNameDerivation | 2 |
| TestExtractionFeasibility | 4 |
| **Total** | **14** |

---

## 10. Edge Cases and Design Decisions

**Singleton nodes:** Connected components of size 1 are filtered by `min_cluster_size=2`. Users can pass `min_cluster_size=1` to include them.

**Zero-edge graph:** Every node is its own component. With min_cluster_size=2, returns empty list.

**Phase 4 not run (no DB edges):** `shared_db_objects` relies on `ProjectNode.sproc_references`, which the graph builder populates from basic regex even without `--include-db`. The shared_db_penalty may be 0 if no sprocs exist — this is correct.

**Metrics/cycles not pre-computed:** Both are `Optional`. If not provided, cycle penalty is 0.0 and API surface uses just `type_declarations` counts without external-use filtering.

**Label propagation convergence:** Capped at 100 iterations. Typical convergence: 5-15 iterations for <1000 nodes.

---

## 11. Implementation Sequence

1. Add `BOUNDARY_ASSESSMENT` to `AITaskType` in `scatter/ai/base.py`
2. Create `scatter/analyzers/domain_analyzer.py` with all functions
3. Update `scatter/__main__.py` — call `find_clusters()` in graph mode, add console + JSON output
4. Update `scatter/__init__.py` with new exports
5. Create `test_domain.py` with 14 tests
6. Run full test suite to verify no regressions

---

## 12. Verification

```bash
# All existing tests pass
python -m pytest --tb=short

# New domain tests pass
python -m pytest test_domain.py -v

# Integration: graph mode shows domain clusters
python -m scatter --graph --search-scope . -v

# JSON output includes clusters
python -m scatter --graph --search-scope . --output-format json --output-file /tmp/graph.json
python -c "import json; d=json.load(open('/tmp/graph.json')); print(len(d['clusters']), 'clusters')"

# Exports work
python -c "from scatter import Cluster, find_clusters, score_extraction_feasibility; print('OK')"

# Determinism check
python -c "
from scatter.analyzers.graph_builder import build_dependency_graph
from scatter.analyzers.domain_analyzer import find_clusters
from pathlib import Path
g = build_dependency_graph(Path('.'), disable_multiprocessing=True, exclude_patterns=['*/bin/*','*/obj/*','*/temp_test_data/*'])
results = [find_clusters(g) for _ in range(5)]
names = [[c.name for c in r] for r in results]
assert all(n == names[0] for n in names), 'Non-deterministic!'
print('Determinism verified')
"
```
