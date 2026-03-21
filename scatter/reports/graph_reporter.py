"""Reporters for dependency graph analysis output."""
import csv
import dataclasses
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.core.graph import DependencyGraph


def generate_mermaid(
    graph: DependencyGraph,
    clusters: Optional[List] = None,
    top_n: Optional[int] = None,
) -> str:
    """Render a Mermaid graph diagram from project_reference edges.

    Only includes project_reference edges (strongest signal).
    If top_n is set, include only the top-N nodes by degree.
    """
    lines = ["graph TD"]

    # Collect project_reference edges only
    ref_edges = [
        e for e in graph.all_edges if e.edge_type == "project_reference"
    ]

    if not ref_edges:
        return "graph TD\n"

    # Determine which nodes to include
    if top_n is not None:
        degree: Dict[str, int] = {}
        for e in ref_edges:
            degree[e.source] = degree.get(e.source, 0) + 1
            degree[e.target] = degree.get(e.target, 0) + 1
        top_nodes = set(
            name
            for name, _ in sorted(degree.items(), key=lambda x: -x[1])[:top_n]
        )
        ref_edges = [
            e for e in ref_edges if e.source in top_nodes and e.target in top_nodes
        ]
    else:
        top_nodes = None

    def sanitize(name: str) -> str:
        return name.replace(".", "_")

    # Build cluster membership lookup
    cluster_map: Dict[str, str] = {}
    if clusters:
        for clu in clusters:
            for proj in clu.projects:
                cluster_map[proj] = clu.name

    # Collect all nodes that appear in edges
    all_nodes = set()
    for e in ref_edges:
        all_nodes.add(e.source)
        all_nodes.add(e.target)

    if clusters and cluster_map:
        # Group nodes by cluster
        clustered: Dict[str, List[str]] = {}
        unclustered: List[str] = []
        for node in sorted(all_nodes):
            cname = cluster_map.get(node)
            if cname:
                clustered.setdefault(cname, []).append(node)
            else:
                unclustered.append(node)

        for cname, members in sorted(clustered.items()):
            lines.append(f"  subgraph {sanitize(cname)}[\"{cname}\"]")
            for m in members:
                lines.append(f"    {sanitize(m)}[\"{m}\"]")
            lines.append("  end")

        for node in unclustered:
            lines.append(f"  {sanitize(node)}[\"{node}\"]")
    else:
        for node in sorted(all_nodes):
            lines.append(f"  {sanitize(node)}[\"{node}\"]")

    for e in ref_edges:
        lines.append(f"  {sanitize(e.source)} --> {sanitize(e.target)}")

    lines.append("")
    return "\n".join(lines)


def write_graph_csv_report(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    output_path: Path,
    clusters: Optional[List] = None,
) -> None:
    """Write graph metrics as CSV."""
    fieldnames = [
        "Project", "Namespace", "Solutions", "FanIn", "FanOut", "Instability",
        "CouplingScore", "AfferentCoupling", "EfferentCoupling",
        "SharedDbDensity", "TypeExportCount", "ConsumerCount",
        "Cluster", "ExtractionFeasibility",
    ]

    # Build cluster lookup
    cluster_lookup: Dict[str, Tuple[str, str]] = {}
    if clusters:
        for clu in clusters:
            for proj in clu.projects:
                cluster_lookup[proj] = (clu.name, clu.extraction_feasibility)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, m in sorted(metrics.items()):
            node = graph.get_node(name)
            namespace = node.namespace if node else ""
            clu_name, feasibility = cluster_lookup.get(name, ("", ""))
            solutions_str = ";".join(node.solutions) if node else ""
            writer.writerow({
                "Project": name,
                "Namespace": namespace or "",
                "Solutions": solutions_str,
                "FanIn": m.fan_in,
                "FanOut": m.fan_out,
                "Instability": round(m.instability, 3),
                "CouplingScore": round(m.coupling_score, 3),
                "AfferentCoupling": m.afferent_coupling,
                "EfferentCoupling": m.efferent_coupling,
                "SharedDbDensity": round(m.shared_db_density, 3),
                "TypeExportCount": m.type_export_count,
                "ConsumerCount": m.consumer_count,
                "Cluster": clu_name,
                "ExtractionFeasibility": feasibility,
            })


def print_graph_report(
    graph: DependencyGraph,
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    clusters: Optional[List] = None,
    dashboard=None,
    solution_metrics: Optional[Dict] = None,
) -> None:
    """Print graph analysis summary to console."""
    print(f"\n{'='*60}")
    print(f"  Dependency Graph Analysis")
    print(f"{'='*60}")
    print(f"  Projects: {graph.node_count}")
    print(f"  Dependencies: {graph.edge_count}")
    solution_names = set()
    for node in graph.get_all_nodes():
        solution_names.update(node.solutions)
    if solution_names:
        print(f"  Solutions: {len(solution_names)}")
    print(f"  Connected components: {len(graph.connected_components)}")
    print(f"  Circular dependencies: {len(cycles)}")
    print()

    if ranked:
        print(f"  Top Coupled Projects:")
        print(f"  {'Project':<40} {'Score':>8} {'Fan-In':>8} {'Fan-Out':>8} {'Instab.':>8}")
        print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
        for name, m in ranked:
            print(f"  {name:<40} {m.coupling_score:>8.1f} {m.fan_in:>8} {m.fan_out:>8} {m.instability:>8.2f}")
        print()

    if cycles:
        print(f"  Circular Dependencies (build-order violations):")
        for i, cg in enumerate(cycles, 1):
            cycle_str = " -> ".join(cg.shortest_cycle + [cg.shortest_cycle[0]])
            print(f"    {i}. [{cg.size} projects] {cycle_str}")
        print()

    if clusters:
        # Check if any cluster has solution alignment data
        has_alignment = any(clu.solution_alignment > 0 for clu in clusters)
        print(f"  Domain Clusters:")
        if has_alignment:
            print(f"  {'Cluster':<30} {'Size':>6} {'Cohesion':>10} {'Coupling':>10} {'Feasibility':>20} {'Align':>8}")
            print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*10} {'-'*20} {'-'*8}")
        else:
            print(f"  {'Cluster':<30} {'Size':>6} {'Cohesion':>10} {'Coupling':>10} {'Feasibility':>20}")
            print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*10} {'-'*20}")
        for clu in clusters:
            label = f"{clu.extraction_feasibility} ({clu.feasibility_score:.3f})"
            if has_alignment:
                print(f"  {clu.name:<30} {len(clu.projects):>6} {clu.cohesion:>10.3f} {clu.coupling_to_outside:>10.3f} {label:>20} {clu.solution_alignment:>8.2f}")
            else:
                print(f"  {clu.name:<30} {len(clu.projects):>6} {clu.cohesion:>10.3f} {clu.coupling_to_outside:>10.3f} {label:>20}")
            # Show top 5 members + dominant solution
            members = sorted(clu.projects)[:5]
            suffix = ", ..." if len(clu.projects) > 5 else ""
            sol_suffix = f" (solution: {clu.dominant_solution})" if clu.dominant_solution else ""
            print(f"    Members: {', '.join(members)}{suffix}{sol_suffix}")
        print()

    if solution_metrics:
        print(f"  Solution Coupling:")
        print(f"  {'Solution':<30} {'Projects':>8} {'Internal':>10} {'External':>10} {'Ratio':>8}")
        print(f"  {'-'*30} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
        for sm in solution_metrics.values():
            print(f"  {sm.name:<30} {sm.project_count:>8} {sm.internal_edges:>10} {sm.external_edges:>10} {sm.cross_solution_ratio:>8.2f}")
        print()

    if dashboard and dashboard.observations:
        print(f"  Observations:")
        for obs in dashboard.observations:
            print(f"    [{obs.severity}] {obs.message}")
        print()


def build_graph_json(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    clusters: Optional[List] = None,
    metadata: Optional[Dict] = None,
    include_topology: bool = True,
    dashboard=None,
    solution_metrics: Optional[Dict] = None,
    bridge_projects: Optional[List[str]] = None,
) -> dict:
    """Build JSON-serializable dict for graph report."""
    report = {}
    if metadata is not None:
        report['metadata'] = metadata
    report.update({
        "summary": {
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "cycle_count": len(cycles),
            "components": len(graph.connected_components),
            "cluster_count": len(clusters) if clusters else 0,
        },
        "top_coupled": [
            {
                "project": name,
                "coupling_score": m.coupling_score,
                "fan_in": m.fan_in,
                "fan_out": m.fan_out,
                "instability": round(m.instability, 3),
            }
            for name, m in ranked
        ],
        "cycles": [
            {
                "projects": cg.projects,
                "size": cg.size,
                "shortest_cycle": cg.shortest_cycle,
                "edge_count": cg.edge_count,
            }
            for cg in cycles
        ],
        "metrics": {
            name: {
                "fan_in": m.fan_in,
                "fan_out": m.fan_out,
                "instability": round(m.instability, 3),
                "coupling_score": round(m.coupling_score, 3),
                "afferent_coupling": m.afferent_coupling,
                "efferent_coupling": m.efferent_coupling,
                "shared_db_density": round(m.shared_db_density, 3),
                "type_export_count": m.type_export_count,
                "consumer_count": m.consumer_count,
                "solutions": (graph.get_node(name).solutions
                              if graph.get_node(name) else []),
            }
            for name, m in sorted(metrics.items())
        },
    })
    if include_topology:
        report["graph"] = graph.to_dict()
    if clusters:
        report["clusters"] = [
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
                "feasibility_details": {
                    k: round(v, 3) for k, v in clu.feasibility_details.items()
                },
                "shared_db_objects": clu.shared_db_objects,
                "solution_alignment": round(clu.solution_alignment, 3),
                "dominant_solution": clu.dominant_solution,
            }
            for clu in clusters
        ]
    if solution_metrics:
        report["solution_metrics"] = {
            name: {
                "project_count": sm.project_count,
                "internal_edges": sm.internal_edges,
                "external_edges": sm.external_edges,
                "cross_solution_ratio": round(sm.cross_solution_ratio, 3),
                "incoming_solutions": sm.incoming_solutions,
                "outgoing_solutions": sm.outgoing_solutions,
            }
            for name, sm in sorted(solution_metrics.items())
        }
    if bridge_projects:
        report["bridge_projects"] = bridge_projects
    if dashboard is not None:
        report["health_dashboard"] = dataclasses.asdict(dashboard)
    return report


def write_graph_json_report(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    output_path: Path,
    clusters: Optional[List] = None,
    metadata: Optional[Dict] = None,
    include_topology: bool = True,
    dashboard=None,
    solution_metrics=None,
    bridge_projects=None,
) -> None:
    """Write graph analysis report as JSON."""
    report = build_graph_json(
        graph, metrics, ranked, cycles,
        clusters=clusters, metadata=metadata,
        include_topology=include_topology, dashboard=dashboard,
        solution_metrics=solution_metrics, bridge_projects=bridge_projects,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
