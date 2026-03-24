"""Domain boundary detection for dependency graphs.

All functions are standalone free functions that accept a DependencyGraph
as input — they are NOT methods on DependencyGraph (SRP).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from scatter.core.graph import DependencyEdge, DependencyGraph

MAX_CROSS_BOUNDARY_EVIDENCE = 20
LABEL_PROPAGATION_THRESHOLD = 20
LABEL_PROPAGATION_MAX_ITERATIONS = 100

FEASIBILITY_WEIGHTS = {
    "cross_boundary_penalty": 0.40,
    "shared_db_penalty": 0.25,
    "cycle_penalty": 0.20,
    "api_surface_penalty": 0.15,
}


@dataclass
class Cluster:
    """A group of tightly-connected projects — a candidate domain/service boundary."""

    name: str
    projects: List[str]
    internal_edges: int
    external_edges: int
    cohesion: float
    coupling_to_outside: float
    cross_boundary_dependencies: List[DependencyEdge]
    shared_db_objects: List[str]
    extraction_feasibility: str
    feasibility_score: float
    feasibility_details: Dict[str, float] = field(default_factory=dict)
    solution_alignment: float = 0.0
    dominant_solution: Optional[str] = None


def find_clusters(
    graph: DependencyGraph,
    min_cluster_size: int = 2,
    metrics: Optional[Dict] = None,
    cycles: Optional[List] = None,
) -> List[Cluster]:
    """Detect natural service boundaries via two-level clustering.

    Level 1: Connected components (treating edges as undirected).
    Level 2: Label propagation for large components (> LABEL_PROPAGATION_THRESHOLD).

    Returns List[Cluster] sorted by size descending, then name.
    """
    components = graph.connected_components

    # Build sproc map once for all clusters (O(V) instead of O(C*V))
    sproc_map: Dict[str, Set[str]] = defaultdict(set)
    for node in graph.get_all_nodes():
        for sproc in node.sproc_references:
            sproc_map[sproc].add(node.name)

    # Level 2: sub-divide large components
    all_groups: List[List[str]] = []
    for component in components:
        if len(component) > LABEL_PROPAGATION_THRESHOLD:
            sub_groups = _label_propagation(graph, component)
            all_groups.extend(sub_groups)
        else:
            all_groups.append(component)

    # Filter by min size and build clusters
    clusters = []
    for group in all_groups:
        if len(group) < min_cluster_size:
            continue
        cluster = _build_cluster(group, graph, 0, metrics, cycles, sproc_map)
        # Compute solution alignment post-hoc
        alignment, dominant = _compute_solution_alignment(cluster.projects, graph)
        cluster.solution_alignment = alignment
        cluster.dominant_solution = dominant
        clusters.append(cluster)

    clusters.sort(key=lambda c: (-len(c.projects), c.name))

    # Re-assign cluster_index after sort so fallback names match output order
    for i, cluster in enumerate(clusters):
        if cluster.name.startswith("cluster_"):
            cluster.name = f"cluster_{i}"

    return clusters


def score_extraction_feasibility(
    cluster: "Cluster",
    graph: DependencyGraph,
    metrics: Optional[Dict] = None,
    cycles: Optional[List] = None,
) -> Tuple[str, float, Dict[str, float]]:
    """Score how easy it would be to extract this cluster as a service.

    Returns (label, numeric_score, penalty_details).
    """
    cluster_set = set(cluster.projects)

    # 1. Cross-boundary coupling
    cross_boundary = cluster.coupling_to_outside

    # 2. Shared DB objects
    total_sprocs_in_cluster = 0
    for proj in cluster.projects:
        node = graph.get_node(proj)
        if node:
            total_sprocs_in_cluster += len(node.sproc_references)
    shared_db_ratio = len(cluster.shared_db_objects) / max(1, total_sprocs_in_cluster)

    # 3. Cycle penalty — any cycle spanning inside and outside the cluster
    has_cross_boundary_cycle = 0.0
    if cycles:
        for cg in cycles:
            cg_set = set(cg.projects)
            inside = cg_set & cluster_set
            outside = cg_set - cluster_set
            if inside and outside:
                has_cross_boundary_cycle = 1.0
                break

    # 4. API surface breadth
    ext_used, total_types = _compute_api_surface(cluster_set, graph)
    api_surface_ratio = ext_used / max(1, total_types)

    details = {
        "cross_boundary_penalty": cross_boundary * FEASIBILITY_WEIGHTS["cross_boundary_penalty"],
        "shared_db_penalty": shared_db_ratio * FEASIBILITY_WEIGHTS["shared_db_penalty"],
        "cycle_penalty": has_cross_boundary_cycle * FEASIBILITY_WEIGHTS["cycle_penalty"],
        "api_surface_penalty": api_surface_ratio * FEASIBILITY_WEIGHTS["api_surface_penalty"],
    }

    total_penalty = sum(details.values())
    score = max(0.0, 1.0 - total_penalty)

    label = _score_to_label(score)
    return label, score, details


def _score_to_label(score: float) -> str:
    """Map numeric score to feasibility label."""
    if score >= 0.75:
        return "easy"
    if score >= 0.50:
        return "moderate"
    if score >= 0.25:
        return "hard"
    return "very_hard"


def _label_propagation(
    graph: DependencyGraph,
    component_nodes: List[str],
) -> List[List[str]]:
    """Label propagation sub-clustering for large connected components.

    Deterministic: sorted iteration, lowest-label tie-breaking, max iterations capped.
    """
    component_set = set(component_nodes)
    sorted_nodes = sorted(component_nodes)
    labels = {node: node for node in sorted_nodes}

    # Pre-compute bidirectional weight matrix to avoid get_edges_between in inner loop.
    # For each outgoing edge A→B, we credit both (A,B) and (B,A). This gives the same
    # total as get_edges_between(a,b) which sums edges in both directions.
    pair_weights: Dict[Tuple[str, str], float] = defaultdict(float)
    for node in sorted_nodes:
        for edge in graph.get_edges_from(node):
            if edge.target in component_set:
                pair_weights[(node, edge.target)] += edge.weight
                pair_weights[(edge.target, node)] += edge.weight

    for _ in range(LABEL_PROPAGATION_MAX_ITERATIONS):
        changed = False
        for node in sorted_nodes:
            neighbors = sorted(
                (graph.get_dependency_names(node) | graph.get_consumer_names(node)) & component_set
            )
            if not neighbors:
                continue

            label_votes: Dict[str, float] = defaultdict(float)
            for neighbor in neighbors:
                total_weight = pair_weights.get((node, neighbor), 0.0)
                label_votes[labels[neighbor]] += total_weight

            # Best label: highest vote, tie-break by lowest label alphabetically
            best_label = min(label_votes, key=lambda lbl: (-label_votes[lbl], lbl))

            if best_label != labels[node]:
                labels[node] = best_label
                changed = True

        if not changed:
            break

    # Group nodes by final label
    groups: Dict[str, List[str]] = defaultdict(list)
    for node, label in labels.items():
        groups[label].append(node)

    return [sorted(members) for members in groups.values()]


def _compute_solution_alignment(
    projects: List[str],
    graph: DependencyGraph,
) -> Tuple[float, Optional[str]]:
    """Compute solution alignment for a cluster.

    Returns (alignment_score, dominant_solution).
    A project in multiple solutions counts for each (set membership check).
    """
    if not projects:
        return 0.0, None

    # Count solution occurrences across all cluster members
    solution_counts: Dict[str, int] = defaultdict(int)
    for proj in projects:
        node = graph.get_node(proj)
        if node:
            for sol in node.solutions:
                solution_counts[sol] += 1

    if not solution_counts:
        return 0.0, None

    # Dominant = most common solution (tie-break: lowest name alphabetically)
    dominant = min(solution_counts, key=lambda s: (-solution_counts[s], s))

    # Alignment = fraction of members that have the dominant solution
    members_with_dominant = sum(
        1 for proj in projects if (node := graph.get_node(proj)) and dominant in node.solutions
    )
    alignment = members_with_dominant / len(projects)

    return alignment, dominant


def _derive_cluster_name(projects: List[str], cluster_index: int) -> str:
    """Derive human-readable cluster name from longest common prefix."""
    if not projects:
        return f"cluster_{cluster_index}"

    # Split each project name by '.' into segments
    split_names = [p.split(".") for p in projects]
    prefix_segments: List[str] = []

    for parts in zip(*split_names):
        if len(set(parts)) == 1:
            prefix_segments.append(parts[0])
        else:
            break

    prefix = ".".join(prefix_segments)
    if len(prefix) >= 3:
        return prefix
    return f"cluster_{cluster_index}"


def _find_shared_db_objects(
    cluster_projects: Set[str],
    sproc_map: Dict[str, Set[str]],
) -> List[str]:
    """Find DB objects referenced by projects both inside and outside the cluster."""
    shared = []
    for sproc, refs in sproc_map.items():
        inside = refs & cluster_projects
        outside = refs - cluster_projects
        if inside and outside:
            shared.append(sproc)
    return sorted(shared)


def _compute_api_surface(
    cluster_projects: Set[str],
    graph: DependencyGraph,
) -> Tuple[int, int]:
    """Returns (externally_used_type_count, total_type_count)."""
    total_types: Set[str] = set()
    for proj_name in cluster_projects:
        node = graph.get_node(proj_name)
        if node:
            total_types.update(node.type_declarations)

    # Check type_usage edges crossing the boundary (incoming from outside)
    externally_used: Set[str] = set()
    for proj_name in cluster_projects:
        for edge in graph.get_edges_to(proj_name):
            if edge.source not in cluster_projects and edge.edge_type == "type_usage":
                if edge.evidence:
                    for ev in edge.evidence:
                        # Evidence format from graph_builder: "path:TypeName"
                        if ":" in ev:
                            type_name = ev.rsplit(":", 1)[-1]
                            if type_name in total_types:
                                externally_used.add(type_name)

    return len(externally_used), len(total_types)


def _compute_edge_counts(
    projects: List[str],
    graph: DependencyGraph,
) -> Tuple[int, int, List[DependencyEdge]]:
    """Compute internal/external edge counts and cross-boundary edges.

    Returns (internal_edges, external_edges, cross_boundary_deps).
    """
    project_set = set(projects)
    internal = 0
    external = 0
    cross_boundary: List[DependencyEdge] = []

    for proj in projects:
        for edge in graph.get_edges_from(proj):
            if edge.target in project_set:
                internal += 1
            else:
                external += 1
                if len(cross_boundary) < MAX_CROSS_BOUNDARY_EVIDENCE:
                    cross_boundary.append(edge)
        for edge in graph.get_edges_to(proj):
            if edge.source not in project_set:
                external += 1
                if len(cross_boundary) < MAX_CROSS_BOUNDARY_EVIDENCE:
                    cross_boundary.append(edge)

    return internal, external, cross_boundary


def _build_cluster(
    projects: List[str],
    graph: DependencyGraph,
    cluster_index: int,
    metrics: Optional[Dict] = None,
    cycles: Optional[List] = None,
    sproc_map: Optional[Dict[str, Set[str]]] = None,
) -> "Cluster":
    """Construct a Cluster with all computed fields."""
    sorted_projects = sorted(projects)
    project_set = set(sorted_projects)

    name = _derive_cluster_name(sorted_projects, cluster_index)
    internal, external, cross_boundary = _compute_edge_counts(sorted_projects, graph)

    n = len(sorted_projects)
    max_possible = n * (n - 1)
    cohesion = internal / max_possible if max_possible > 0 else 0.0

    total_edges = internal + external
    coupling_to_outside = external / total_edges if total_edges > 0 else 0.0

    if sproc_map is None:
        sproc_map = defaultdict(set)
        for node in graph.get_all_nodes():
            for sproc in node.sproc_references:
                sproc_map[sproc].add(node.name)
    shared_db = _find_shared_db_objects(project_set, sproc_map)

    cluster = Cluster(
        name=name,
        projects=sorted_projects,
        internal_edges=internal,
        external_edges=external,
        cohesion=cohesion,
        coupling_to_outside=coupling_to_outside,
        cross_boundary_dependencies=cross_boundary,
        shared_db_objects=shared_db,
        extraction_feasibility="",
        feasibility_score=0.0,
    )

    label, score, details = score_extraction_feasibility(cluster, graph, metrics, cycles)
    cluster.extraction_feasibility = label
    cluster.feasibility_score = score
    cluster.feasibility_details = details

    return cluster
