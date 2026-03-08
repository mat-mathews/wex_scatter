"""Reporters for dependency graph analysis output."""
import json
from pathlib import Path
from typing import Dict, List, Tuple

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.core.graph import DependencyGraph


def print_graph_report(
    graph: DependencyGraph,
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
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


def build_graph_json(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
) -> dict:
    """Build JSON-serializable dict for graph report."""
    return {
        "summary": {
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "cycle_count": len(cycles),
            "components": len(graph.connected_components),
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
    }


def write_graph_json_report(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    ranked: List[Tuple[str, ProjectMetrics]],
    cycles: List[CycleGroup],
    output_path: Path,
) -> None:
    """Write graph analysis report as JSON."""
    report = build_graph_json(graph, metrics, ranked, cycles)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
