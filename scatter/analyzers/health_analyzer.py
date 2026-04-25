"""Health dashboard and observation rules for dependency graphs.

Produces deterministic, rule-based observations (no AI) from graph metrics.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics, SolutionMetrics
from scatter.core.graph import DependencyGraph

# --- Thresholds (module constants) ---
HIGH_FAN_IN_THRESHOLD = 5
LOW_INSTABILITY_THRESHOLD = 0.3
HIGH_COUPLING_THRESHOLD = 8.0
LOW_COHESION_THRESHOLD = 0.3
HIGH_CLUSTER_COUPLING_RATIO = 0.6
WIDE_BLAST_RADIUS_IMPORT_THRESHOLD = 5


@dataclass
class Observation:
    """A single health observation about a project or cluster."""

    project: str  # project name, cluster name, sproc name, or file path depending on rule
    rule: str  # machine-readable id: "stable_core", "high_coupling", etc.
    message: str  # human-readable message
    severity: str  # "info" | "warning" | "critical"


@dataclass
class HealthDashboard:
    """Aggregated health metrics for the entire dependency graph."""

    total_projects: int
    total_edges: int
    total_cycles: int
    total_clusters: int
    avg_fan_in: float
    avg_fan_out: float
    avg_instability: float
    avg_coupling_score: float
    max_coupling_project: Optional[str]
    max_coupling_score: float
    db_hotspots: List[str] = field(default_factory=list)
    observations: List[Observation] = field(default_factory=list)


def compute_health_dashboard(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    cycles: List[CycleGroup],
    clusters: Optional[List] = None,
    solution_metrics: Optional[Dict[str, SolutionMetrics]] = None,
    bridge_projects: Optional[List[str]] = None,
) -> HealthDashboard:
    """Build a HealthDashboard from graph data and computed metrics."""
    n = len(metrics)

    if n == 0:
        return HealthDashboard(
            total_projects=graph.node_count,
            total_edges=graph.edge_count,
            total_cycles=len(cycles),
            total_clusters=len(clusters) if clusters else 0,
            avg_fan_in=0.0,
            avg_fan_out=0.0,
            avg_instability=0.0,
            avg_coupling_score=0.0,
            max_coupling_project=None,
            max_coupling_score=0.0,
        )

    total_fan_in = sum(m.fan_in for m in metrics.values())
    total_fan_out = sum(m.fan_out for m in metrics.values())
    total_instability = sum(m.instability for m in metrics.values())
    total_coupling = sum(m.coupling_score for m in metrics.values())

    max_proj = max(metrics, key=lambda k: metrics[k].coupling_score)

    # Single pass over nodes to build reverse indexes
    sproc_to_projects: Dict[str, List[str]] = defaultdict(list)
    import_to_projects: Dict[str, List[str]] = defaultdict(list)
    node_solutions_lookup: Optional[Dict[str, List[str]]] = None
    if bridge_projects:
        node_solutions_lookup = {}

    for node in graph.get_all_nodes():
        for sproc in node.sproc_references:
            sproc_to_projects[sproc].append(node.name)
        for imp in node.msbuild_imports:
            import_to_projects[imp].append(node.name)
        if node_solutions_lookup is not None and node.solutions:
            node_solutions_lookup[node.name] = node.solutions

    db_hotspots = sorted(sproc for sproc, projs in sproc_to_projects.items() if len(projs) >= 3)

    observations = _generate_observations(
        metrics,
        cycles,
        clusters,
        sproc_to_projects,
        solution_metrics=solution_metrics,
        bridge_projects=bridge_projects,
        node_solutions=node_solutions_lookup,
        import_to_projects=import_to_projects,
    )

    return HealthDashboard(
        total_projects=graph.node_count,
        total_edges=graph.edge_count,
        total_cycles=len(cycles),
        total_clusters=len(clusters) if clusters else 0,
        avg_fan_in=total_fan_in / n,
        avg_fan_out=total_fan_out / n,
        avg_instability=total_instability / n,
        avg_coupling_score=total_coupling / n,
        max_coupling_project=max_proj,
        max_coupling_score=metrics[max_proj].coupling_score,
        db_hotspots=db_hotspots,
        observations=observations,
    )


def _generate_observations(
    metrics: Dict[str, ProjectMetrics],
    cycles: List[CycleGroup],
    clusters: Optional[List],
    sproc_to_projects: Dict[str, List[str]],
    solution_metrics: Optional[Dict[str, SolutionMetrics]] = None,
    bridge_projects: Optional[List[str]] = None,
    node_solutions: Optional[Dict[str, List[str]]] = None,
    import_to_projects: Optional[Dict[str, List[str]]] = None,
) -> List[Observation]:
    """Apply deterministic rules to generate observations."""
    obs: List[Observation] = []

    # Per-project rules
    for name, m in sorted(metrics.items()):
        # Stable core: high fan_in + low instability
        if m.fan_in >= HIGH_FAN_IN_THRESHOLD and m.instability <= LOW_INSTABILITY_THRESHOLD:
            obs.append(
                Observation(
                    project=name,
                    rule="stable_core",
                    message=f"{name}: stable core (fan_in={m.fan_in}, instability={m.instability:.2f}) \u2014 change carefully",
                    severity="warning",
                )
            )

        # High coupling score
        if m.coupling_score >= HIGH_COUPLING_THRESHOLD:
            obs.append(
                Observation(
                    project=name,
                    rule="high_coupling",
                    message=f"{name}: high coupling score ({m.coupling_score:.1f}) \u2014 review dependencies",
                    severity="warning",
                )
            )

    # Cycle rules
    cycle_projects: set = set()
    for cg in cycles:
        cycle_projects.update(cg.projects)
    for name in sorted(cycle_projects):
        obs.append(
            Observation(
                project=name,
                rule="in_cycle",
                message=f"{name}: participates in circular dependency \u2014 must break before extraction",
                severity="critical",
            )
        )

    # Cluster rules
    if clusters:
        for clu in clusters:
            if (
                clu.coupling_to_outside >= HIGH_CLUSTER_COUPLING_RATIO
                and clu.cohesion <= LOW_COHESION_THRESHOLD
            ):
                obs.append(
                    Observation(
                        project=clu.name,
                        rule="low_cohesion_cluster",
                        message=f"{clu.name}: high coupling + low cohesion ({clu.cohesion:.3f}) \u2014 consider splitting",
                        severity="warning",
                    )
                )

    # DB hotspot rules
    for sproc, projs in sorted(sproc_to_projects.items()):
        if len(projs) >= 3:
            obs.append(
                Observation(
                    project=sproc,
                    rule="db_hotspot",
                    message=f"{sproc}: shared by {len(projs)} projects \u2014 database coupling hotspot",
                    severity="info",
                )
            )

    # Solution coupling rules
    if solution_metrics:
        for sol_name, sm in sorted(solution_metrics.items()):
            if sm.cross_solution_ratio > 0.5:
                total = sm.internal_edges + sm.external_edges
                obs.append(
                    Observation(
                        project=sol_name,
                        rule="high_cross_solution_coupling",
                        message=(
                            f"{sol_name}: high cross-solution coupling "
                            f"(ratio {sm.cross_solution_ratio:.2f}, "
                            f"{sm.external_edges} of {total} edges cross solution boundary)"
                        ),
                        severity="warning",
                    )
                )

    if bridge_projects and node_solutions:
        for name in bridge_projects:
            bridge_m = metrics.get(name)
            if bridge_m and bridge_m.fan_in >= HIGH_FAN_IN_THRESHOLD:
                sols = node_solutions.get(name, [])
                sol_str = ", ".join(sols) if sols else "multiple"
                obs.append(
                    Observation(
                        project=name,
                        rule="solution_bridge_project",
                        message=(
                            f"{name}: bridge project across {len(sols)} solutions "
                            f"({sol_str}) with {bridge_m.fan_in} incoming dependencies"
                        ),
                        severity="info",
                    )
                )

    # MSBuild import blast radius rules
    if import_to_projects:
        for imp, projs in sorted(import_to_projects.items()):
            if len(projs) >= WIDE_BLAST_RADIUS_IMPORT_THRESHOLD:
                obs.append(
                    Observation(
                        project=imp,
                        rule="wide_blast_radius_import",
                        message=(
                            f"{imp}: imported by {len(projs)} projects "
                            f"— config change affects wide blast radius"
                        ),
                        severity="warning",
                    )
                )

    return obs
