"""Reporters for dependency graph analysis output."""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.core.graph import DependencyGraph


def print_graph_report(
    graph: DependencyGraph,
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    clusters: Optional[List] = None,
) -> None:
    """Print graph analysis summary to console."""
    print(f"\n{'='*60}")
    print(f"  Dependency Graph Analysis")
    print(f"{'='*60}")
    print(f"  Projects: {graph.node_count}")
    print(f"  Dependencies: {graph.edge_count}")
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
        print(f"  Domain Clusters:")
        print(f"  {'Cluster':<30} {'Size':>6} {'Cohesion':>10} {'Coupling':>10} {'Feasibility':>20}")
        print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*10} {'-'*20}")
        for clu in clusters:
            label = f"{clu.extraction_feasibility} ({clu.feasibility_score:.3f})"
            print(f"  {clu.name:<30} {len(clu.projects):>6} {clu.cohesion:>10.3f} {clu.coupling_to_outside:>10.3f} {label:>20}")
        print()


def build_graph_json(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    clusters: Optional[List] = None,
    metadata: Optional[Dict] = None,
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
            }
            for name, m in sorted(metrics.items())
        },
        "graph": graph.to_dict(),
    })
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
            }
            for clu in clusters
        ]
    return report


def write_graph_json_report(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    output_path: Path,
    clusters: Optional[List] = None,
    metadata: Optional[Dict] = None,
) -> None:
    """Write graph analysis report as JSON."""
    report = build_graph_json(graph, metrics, ranked, cycles, clusters=clusters, metadata=metadata)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
