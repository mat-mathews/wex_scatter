"""Coupling metrics and cycle detection for dependency graphs.

All functions are standalone free functions that accept a DependencyGraph
as input — they are NOT methods on DependencyGraph (SRP).
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from scatter.core.graph import DependencyGraph

# --- Configurable weights ---
# Rationale: project references are "hard" coupling (compile-time dependency),
# sproc_shared is nearly as hard (shared mutable state), namespace usage is
# "soft" (may or may not indicate real coupling), type usage is softest
# (could be a single enum ref).
DEFAULT_COUPLING_WEIGHTS: Dict[str, float] = {
    "project_reference": 1.0,
    "namespace_usage": 0.5,
    "type_usage": 0.3,
    "sproc_shared": 0.8,
}


@dataclass
class ProjectMetrics:
    """Coupling and structural metrics for a single project."""

    fan_in: int  # projects that depend on this one (project_reference edges in)
    fan_out: int  # projects this one depends on (project_reference edges out)
    instability: float  # fan_out / (fan_in + fan_out), 0.0-1.0
    coupling_score: float  # weighted sum of all incoming + outgoing edge weights
    afferent_coupling: int  # total incoming edges (all types)
    efferent_coupling: int  # total outgoing edges (all types)
    shared_db_density: float  # fraction of sprocs shared with other projects
    type_export_count: int  # number of type declarations
    consumer_count: int  # total direct consumers (unique projects via reverse adj)


@dataclass
class CycleGroup:
    """A strongly connected component with size > 1 — a circular dependency."""

    projects: List[str]  # project names in the SCC, sorted alphabetically
    shortest_cycle: List[str]  # one representative shortest cycle within the SCC
    edge_count: int  # number of edges within the SCC

    @property
    def size(self) -> int:
        """Number of projects in this cycle group."""
        return len(self.projects)


def compute_all_metrics(
    graph: DependencyGraph,
    coupling_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, ProjectMetrics]:
    """Compute metrics for every node in the graph.

    Uses graph edge indexes for O(N + E) total traversal.

    coupling_score is the weighted sum of all edge weights touching this node
    (both incoming and outgoing). For bidirectional edges (A→B and B→A), both
    are counted — the score measures total coupling intensity, not unique
    pairwise relationships.
    """
    if coupling_weights is None:
        coupling_weights = DEFAULT_COUPLING_WEIGHTS

    # Build sproc-to-projects map for shared_db_density
    sproc_to_projects: Dict[str, Set[str]] = defaultdict(set)
    for node in graph.get_all_nodes():
        for sproc in node.sproc_references:
            sproc_to_projects[sproc].add(node.name)

    metrics: Dict[str, ProjectMetrics] = {}

    for node in graph.get_all_nodes():
        name = node.name
        outgoing = graph.get_edges_from(name)
        incoming = graph.get_edges_to(name)

        # fan_in / fan_out count only project_reference edges
        fan_in = sum(
            1 for e in incoming if e.edge_type == "project_reference"
        )
        fan_out = sum(
            1 for e in outgoing if e.edge_type == "project_reference"
        )

        total = fan_in + fan_out
        instability = fan_out / total if total > 0 else 0.0

        # coupling_score: weighted sum of all edge weights (both directions).
        # Bidirectional edges are counted twice — this measures total coupling
        # intensity touching this node, not unique pairwise relationships.
        coupling_score = 0.0
        for e in outgoing:
            w = coupling_weights.get(e.edge_type, 0.0)
            coupling_score += w * e.weight
        for e in incoming:
            w = coupling_weights.get(e.edge_type, 0.0)
            coupling_score += w * e.weight

        # shared_db_density
        total_sprocs = len(node.sproc_references)
        if total_sprocs > 0:
            shared_count = sum(
                1
                for sproc in node.sproc_references
                if len(sproc_to_projects.get(sproc, set())) > 1
            )
            shared_db_density = shared_count / total_sprocs
        else:
            shared_db_density = 0.0

        # consumer_count: unique projects that depend on this one (all edge types)
        consumer_names = {e.source for e in incoming}
        consumer_count = len(consumer_names)

        metrics[name] = ProjectMetrics(
            fan_in=fan_in,
            fan_out=fan_out,
            instability=instability,
            coupling_score=coupling_score,
            afferent_coupling=len(incoming),
            efferent_coupling=len(outgoing),
            shared_db_density=shared_db_density,
            type_export_count=len(node.type_declarations),
            consumer_count=consumer_count,
        )

    return metrics


def rank_by_coupling(
    metrics: Dict[str, ProjectMetrics], top_n: int = 10
) -> List[Tuple[str, ProjectMetrics]]:
    """Return the top-N most coupled projects by coupling_score."""
    ranked = sorted(
        metrics.items(), key=lambda item: item[1].coupling_score, reverse=True
    )
    return ranked[:top_n]


# ---------------------------------------------------------------------------
# Cycle detection — Tarjan's SCC (iterative)
# ---------------------------------------------------------------------------

# Default: only detect cycles along project_reference edges (build-order
# violations). namespace_usage and type_usage cycles are common and benign.
DEFAULT_CYCLE_EDGE_TYPES = frozenset({"project_reference"})


def detect_cycles(
    graph: DependencyGraph,
    edge_types: Optional[Set[str]] = None,
) -> List[CycleGroup]:
    """Find all circular dependency groups using Tarjan's SCC algorithm.

    Args:
        graph: The dependency graph to analyze.
        edge_types: Edge types to consider for cycle detection. Defaults to
            {"project_reference"} — only build-order violations. Pass None
            or a custom set to include other edge types.

    Returns CycleGroups (SCCs with size > 1), sorted by size ascending
    (smallest first — often the easiest to break).
    """
    if edge_types is None:
        edge_types = DEFAULT_CYCLE_EDGE_TYPES

    # Build filtered adjacency for cycle detection
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    for edge in graph.all_edges:
        if edge.edge_type in edge_types:
            adjacency[edge.source].add(edge.target)

    sccs = _tarjans_scc_iterative(graph, adjacency)

    # Filter to SCCs with size > 1 (actual cycles)
    cycle_groups: List[CycleGroup] = []
    for scc in sccs:
        if len(scc) < 2:
            continue

        scc_sorted = sorted(scc)
        scc_set = set(scc)

        # Count edges within the SCC (filtered by edge_types)
        edge_count = 0
        for name in scc:
            for target in adjacency.get(name, set()):
                if target in scc_set:
                    edge_count += 1

        # Find shortest cycle within the SCC
        shortest = _shortest_cycle_in_scc(adjacency, scc_sorted)

        cycle_groups.append(
            CycleGroup(
                projects=scc_sorted,
                shortest_cycle=shortest,
                edge_count=edge_count,
            )
        )

    # Sort by size ascending (smallest cycles first — easiest to break)
    cycle_groups.sort(key=lambda cg: cg.size)
    return cycle_groups


def _tarjans_scc_iterative(
    graph: DependencyGraph,
    adjacency: Dict[str, Set[str]],
) -> List[List[str]]:
    """Iterative Tarjan's strongly connected components algorithm.

    O(N + E) time, O(N) space. Uses an explicit call stack to avoid
    Python's recursion limit (~1000) on large graphs.

    Returns all SCCs (including singletons).
    """
    index_counter = 0
    stack: List[str] = []
    on_stack: Set[str] = set()
    index: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    result: List[List[str]] = []

    all_nodes = sorted(n.name for n in graph.get_all_nodes())

    for root in all_nodes:
        if root in index:
            continue

        # Explicit call stack: (node, neighbor_iterator, is_returning)
        # Each frame stores the node being processed and an iterator
        # over its sorted neighbors.
        call_stack: List[Tuple[str, list, int]] = []

        # "Call" root
        index[root] = lowlink[root] = index_counter
        index_counter += 1
        stack.append(root)
        on_stack.add(root)
        neighbors = sorted(adjacency.get(root, set()))
        call_stack.append((root, neighbors, 0))

        while call_stack:
            v, v_neighbors, ni = call_stack[-1]

            if ni < len(v_neighbors):
                # Advance the neighbor index for this frame
                call_stack[-1] = (v, v_neighbors, ni + 1)
                w = v_neighbors[ni]

                if w not in index:
                    # "Recurse" into w
                    index[w] = lowlink[w] = index_counter
                    index_counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    w_neighbors = sorted(adjacency.get(w, set()))
                    call_stack.append((w, w_neighbors, 0))
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])
            else:
                # All neighbors processed — "return" from this frame
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[v])

                if lowlink[v] == index[v]:
                    scc: List[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == v:
                            break
                    result.append(scc)

    return result


def _shortest_cycle_in_scc(
    adjacency: Dict[str, Set[str]],
    scc: List[str],
) -> List[str]:
    """Find shortest cycle within an SCC via BFS with predecessor map.

    Uses O(N) memory predecessor tracking instead of O(N^2) path copying.

    For small SCCs (typical), BFS from each node.
    For large SCCs (>50), BFS from first node only.
    """
    scc_set = set(scc)
    best_cycle: Optional[List[str]] = None

    # For large SCCs, limit search to first node
    search_nodes = scc if len(scc) <= 50 else scc[:1]

    for start in search_nodes:
        # BFS to find shortest path back to start using predecessor map
        predecessor: Dict[str, str] = {}
        queue: deque[str] = deque()

        for neighbor in sorted(adjacency.get(start, set())):
            if neighbor in scc_set:
                if neighbor == start:
                    return [start]
                predecessor[neighbor] = start
                queue.append(neighbor)

        found = False
        while queue and not found:
            current = queue.popleft()
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor not in scc_set:
                    continue
                if neighbor == start:
                    # Reconstruct path from predecessor chain
                    path = []
                    node = current
                    while node != start:
                        path.append(node)
                        node = predecessor[node]
                    path.append(start)
                    path.reverse()
                    if best_cycle is None or len(path) < len(best_cycle):
                        best_cycle = path
                    found = True
                    break
                if neighbor not in predecessor:
                    predecessor[neighbor] = current
                    queue.append(neighbor)

    return best_cycle if best_cycle is not None else scc[:2]
