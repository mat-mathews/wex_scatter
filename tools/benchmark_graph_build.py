"""Benchmark scatter graph building at various scales.

Instruments scatter's actual graph builder and post-build analysis stages
with wall-clock timing and memory measurement (tracemalloc for Python heap,
resource.ru_maxrss for process peak RSS).

Usage:
    python tools/benchmark_graph_build.py /tmp/synthetic_monolith
    python tools/benchmark_graph_build.py /tmp/synthetic_monolith --include-db
    python tools/benchmark_graph_build.py /tmp/synthetic_monolith --runs 3
    python tools/benchmark_graph_build.py . --parser-mode hybrid
    python tools/benchmark_graph_build.py . --mode consumer --class-name PortalDataService

Note on --mode stages vs --mode full:
    'stages' re-implements graph building step-by-step with per-stage timing.
    It runs sequentially to give clean isolated measurements per stage.
    'full' calls build_dependency_graph() as a black box, which uses
    ThreadPoolExecutor internally for type extraction. This means stages-mode
    numbers will be higher than full-mode for I/O-bound stages. Compare
    stages-mode runs to other stages-mode runs, and full-mode to full-mode.

Note on --mode consumer:
    Runs find_consumers() in both regex and hybrid modes, compares results.
    Requires --target-project (defaults to GalaxyWorks.Data).
"""

import argparse
import gc
import json
import logging
import resource
import sys
import time
import tracemalloc
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def get_peak_rss_mb() -> float:
    """Get peak RSS (high-water mark) in MB. macOS returns bytes, Linux returns KB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / 1024 / 1024
    else:
        return usage.ru_maxrss / 1024


class StageTimer:
    """Context manager for timing a pipeline stage with memory tracking."""

    def __init__(self, name: str):
        self.name = name
        self.elapsed = 0.0
        self.heap_before = 0
        self.heap_after = 0
        self.heap_peak = 0

    def __enter__(self):
        gc.collect()
        if tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            self.heap_before = sum(stat.size for stat in snapshot.statistics("filename"))
            tracemalloc.clear_traces()
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start
        if tracemalloc.is_tracing():
            _, self.heap_peak = tracemalloc.get_traced_memory()
            snapshot = tracemalloc.take_snapshot()
            self.heap_after = sum(stat.size for stat in snapshot.statistics("filename"))

    @property
    def heap_delta_mb(self) -> float:
        return (self.heap_after - self.heap_before) / 1024 / 1024

    @property
    def heap_peak_mb(self) -> float:
        return self.heap_peak / 1024 / 1024


def run_benchmark(
    search_scope: Path,
    include_db: bool = False,
    full_type_scan: bool = False,
) -> dict:
    """Run scatter's actual graph builder with stage-level instrumentation."""

    from scatter.analyzers.graph_builder import build_dependency_graph
    from scatter.analyzers.coupling_analyzer import compute_all_metrics, detect_cycles
    from scatter.analyzers.domain_analyzer import find_clusters
    from scatter.analyzers.health_analyzer import compute_health_dashboard

    stages = {}

    # Count files first (not timed — just for reporting)
    csproj_count = len(list(search_scope.rglob("*.csproj")))
    cs_count = len(list(search_scope.rglob("*.cs")))

    # -------------------------------------------------------------------
    # Stage 1: Graph construction (scatter's actual build_dependency_graph)
    # -------------------------------------------------------------------
    with StageTimer("build_dependency_graph") as t:
        graph = build_dependency_graph(
            search_scope,
            include_db_dependencies=include_db,
            full_type_scan=full_type_scan,
        )
    stages["build_dependency_graph"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{graph.node_count} nodes, {graph.edge_count} edges",
    }

    # -------------------------------------------------------------------
    # Stage 2: Coupling metrics
    # -------------------------------------------------------------------
    with StageTimer("compute_metrics") as t:
        metrics = compute_all_metrics(graph)
    stages["compute_metrics"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(metrics)} project metrics",
    }

    # -------------------------------------------------------------------
    # Stage 3: Cycle detection
    # -------------------------------------------------------------------
    with StageTimer("detect_cycles") as t:
        cycles = detect_cycles(graph)
    stages["detect_cycles"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(cycles)} cycles",
    }

    # -------------------------------------------------------------------
    # Stage 4: Domain clustering
    # -------------------------------------------------------------------
    with StageTimer("find_clusters") as t:
        clusters = find_clusters(graph, metrics=metrics, cycles=cycles)
    stages["find_clusters"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(clusters)} clusters",
    }

    # -------------------------------------------------------------------
    # Stage 5: Health dashboard
    # -------------------------------------------------------------------
    with StageTimer("health_dashboard") as t:
        dashboard = compute_health_dashboard(graph, metrics, cycles, clusters=clusters)
    stages["health_dashboard"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(dashboard.observations)} observations",
    }

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    total_time = sum(s["elapsed"] for s in stages.values())
    peak_rss = get_peak_rss_mb()

    # Count edge types
    edge_types = {}
    for node_name in [n.name for n in graph.get_all_nodes()]:
        for edge in graph.get_edges_from(node_name):
            edge_types[edge.edge_type] = edge_types.get(edge.edge_type, 0) + 1

    return {
        "search_scope": str(search_scope),
        "file_counts": {"csproj": csproj_count, "cs": cs_count},
        "graph_summary": {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "edge_types": edge_types,
        },
        "peak_rss_mb": peak_rss,
        "total_time": total_time,
        "stages": stages,
    }


def run_instrumented_build(
    search_scope: Path,
    include_db: bool = False,
    full_type_scan: bool = False,
) -> dict:
    """Run graph builder with internal stage instrumentation.

    Monkeypatches the graph_builder to measure each internal stage
    (file discovery, csproj parsing, type extraction, type usage edges)
    separately, then runs the post-build analysis stages.
    """
    import scatter.analyzers.graph_builder as gb
    from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
    from scatter.core.parallel import find_files_with_pattern_parallel
    from scatter.scanners.project_scanner import derive_namespace, parse_csproj_all_references
    from scatter.scanners.type_scanner import extract_type_names_from_content
    from scatter.analyzers.coupling_analyzer import compute_all_metrics, detect_cycles
    from scatter.analyzers.domain_analyzer import find_clusters
    from scatter.analyzers.health_analyzer import compute_health_dashboard
    from collections import defaultdict

    stages = {}
    exclude_patterns = ["*/bin/*", "*/obj/*", "*/temp_test_data/*"]

    # -------------------------------------------------------------------
    # Stage 1: File discovery (uses scatter's parallel infrastructure)
    # -------------------------------------------------------------------
    with StageTimer("file_discovery") as t:
        all_csproj = find_files_with_pattern_parallel(search_scope, "*.csproj")
        csproj_files = gb._filter_excluded(all_csproj, exclude_patterns)
        all_cs = find_files_with_pattern_parallel(search_scope, "*.cs")
        cs_files = gb._filter_excluded(all_cs, exclude_patterns)
    stages["file_discovery"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(csproj_files)} .csproj, {len(cs_files)} .cs",
    }

    # -------------------------------------------------------------------
    # Stage 2: .csproj parsing
    # -------------------------------------------------------------------
    with StageTimer("csproj_parsing") as t:
        project_metadata = {}
        project_refs = {}
        for csproj_path in csproj_files:
            parsed = parse_csproj_all_references(csproj_path)
            if parsed is None:
                continue
            name = csproj_path.stem
            namespace = derive_namespace(csproj_path)
            project_metadata[name] = {
                "path": csproj_path,
                "namespace": namespace,
                "framework": parsed["target_framework"],
                "project_style": parsed["project_style"],
                "output_type": parsed["output_type"],
            }
            project_refs[name] = parsed["project_references"]
    stages["csproj_parsing"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(project_metadata)} projects parsed",
    }

    # -------------------------------------------------------------------
    # Stage 3: .cs-to-project mapping
    # -------------------------------------------------------------------
    with StageTimer("cs_mapping") as t:
        project_dir_index = gb._build_project_directory_index(csproj_files)
        project_cs_files = defaultdict(list)
        for cs_path in cs_files:
            mapped_name = gb._map_cs_to_project(cs_path, project_dir_index)
            if mapped_name:
                project_cs_files[mapped_name].append(cs_path)
    stages["cs_mapping"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{sum(len(v) for v in project_cs_files.values())} files mapped",
    }

    # -------------------------------------------------------------------
    # Stage 4: Type/namespace/sproc extraction + identifier caching
    # -------------------------------------------------------------------
    with StageTimer("type_extraction") as t:
        project_types = defaultdict(set)
        project_sprocs = defaultdict(set)
        project_using_ns = defaultdict(set)
        project_ns_evidence = defaultdict(lambda: defaultdict(list))
        file_identifier_cache = {}
        files_read = 0

        for project_name, cs_paths in project_cs_files.items():
            for cs_path in cs_paths:
                try:
                    content = cs_path.read_text(encoding="utf-8", errors="ignore")
                    files_read += 1
                except OSError:
                    continue
                file_identifier_cache[cs_path] = {
                    m.group() for m in gb._IDENT_PATTERN.finditer(content)
                }
                types = extract_type_names_from_content(content)
                project_types[project_name].update(types)
                for match in gb._SPROC_PATTERN.finditer(content):
                    project_sprocs[project_name].add(match.group().strip("\"'"))
                for match in gb._USING_PATTERN.finditer(content):
                    ns = match.group(1)
                    project_using_ns[project_name].add(ns)
                    project_ns_evidence[project_name][ns].append(str(cs_path))

    total_types = sum(len(v) for v in project_types.values())
    stages["type_extraction"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{files_read} files, {total_types} types extracted",
    }

    # -------------------------------------------------------------------
    # Stage 5: Build graph nodes + project reference edges
    # -------------------------------------------------------------------
    with StageTimer("graph_construction") as t:
        graph = DependencyGraph()
        for name, meta in project_metadata.items():
            node = ProjectNode(
                path=meta["path"],
                name=name,
                namespace=meta["namespace"],
                framework=meta["framework"],
                project_style=meta["project_style"],
                output_type=meta["output_type"],
                file_count=len(project_cs_files.get(name, [])),
                type_declarations=sorted(project_types.get(name, set())),
                sproc_references=sorted(project_sprocs.get(name, set())),
            )
            graph.add_node(node)
        gb._build_project_reference_edges(graph, project_refs, csproj_files, project_metadata)
    ref_edges = sum(
        1
        for n in graph.get_all_nodes()
        for e in graph.get_edges_from(n.name)
        if e.edge_type == "project_reference"
    )
    stages["graph_construction"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{graph.node_count} nodes, {ref_edges} project_ref edges",
    }

    # -------------------------------------------------------------------
    # Stage 6: Namespace usage edges
    # -------------------------------------------------------------------
    with StageTimer("namespace_edges") as t:
        ns_to_project = {}
        for name, meta in project_metadata.items():
            ns = meta.get("namespace") or meta.get("assembly_name")
            if ns:
                ns_to_project[ns] = name

        ns_edge_count = 0
        for source, usings in project_using_ns.items():
            if source not in graph._nodes:
                continue
            for ns in usings:
                target = ns_to_project.get(ns)
                if target and target != source and target in graph._nodes:
                    evidence = project_ns_evidence[source].get(ns, [])
                    graph.add_edge(
                        DependencyEdge(
                            source=source,
                            target=target,
                            edge_type="namespace_usage",
                            weight=len(evidence),
                            evidence=evidence,
                        )
                    )
                    ns_edge_count += 1
    stages["namespace_edges"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{ns_edge_count} namespace_usage edges",
    }

    # -------------------------------------------------------------------
    # Stage 7: Type usage edges (cached identifiers + reachable-set scoping)
    # -------------------------------------------------------------------
    with StageTimer("type_usage_edges") as t:
        type_to_projects = defaultdict(set)
        for pname, types in project_types.items():
            for tname in types:
                type_to_projects[tname].add(pname)

        type_name_set = set(type_to_projects.keys())
        type_edge_count = 0
        total_matches = 0

        # Build reachable targets from existing edges
        if not full_type_scan:
            reachable_targets = defaultdict(set)
            for source_name in [n.name for n in graph.get_all_nodes()]:
                for edge in graph.get_edges_from(source_name):
                    if edge.edge_type in ("project_reference", "namespace_usage"):
                        reachable_targets[source_name].add(edge.target)

        _empty = frozenset()
        for source_project, cs_paths in project_cs_files.items():
            if source_project not in graph._nodes:
                continue
            type_usage_evidence = defaultdict(list)
            for cs_path in cs_paths:
                file_identifiers = file_identifier_cache.get(cs_path)
                if file_identifiers is None:
                    continue
                matched_types = file_identifiers & type_name_set
                total_matches += len(matched_types)
                for type_name in matched_types:
                    for owner in type_to_projects[type_name]:
                        if (
                            owner != source_project
                            and owner in graph._nodes
                            and (
                                full_type_scan
                                or owner in reachable_targets.get(source_project, _empty)
                            )
                        ):
                            type_usage_evidence[owner].append(f"{cs_path}:{type_name}")

            for target, evidence in type_usage_evidence.items():
                graph.add_edge(
                    DependencyEdge(
                        source=source_project,
                        target=target,
                        edge_type="type_usage",
                        weight=len(evidence),
                        evidence=evidence,
                    )
                )
                type_edge_count += 1

        del file_identifier_cache

    stages["type_usage_edges"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{type_edge_count} edges, {total_matches:,} type matches via set intersection",
    }

    # -------------------------------------------------------------------
    # Stage 8: DB scanning (optional)
    # -------------------------------------------------------------------
    if include_db:
        with StageTimer("db_scanning") as t:
            from scatter.scanners.db_scanner import scan_db_dependencies, add_db_edges_to_graph

            db_deps = scan_db_dependencies(
                search_scope,
                project_cs_map=dict(project_cs_files),
            )
            add_db_edges_to_graph(graph, db_deps)
        stages["db_scanning"] = {
            "elapsed": t.elapsed,
            "heap_delta_mb": t.heap_delta_mb,
            "heap_peak_mb": t.heap_peak_mb,
            "detail": f"{len(db_deps)} DB dependencies",
        }

    # -------------------------------------------------------------------
    # Stage 9: Metrics
    # -------------------------------------------------------------------
    with StageTimer("compute_metrics") as t:
        metrics = compute_all_metrics(graph)
    stages["compute_metrics"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(metrics)} project metrics",
    }

    # -------------------------------------------------------------------
    # Stage 10: Cycles
    # -------------------------------------------------------------------
    with StageTimer("detect_cycles") as t:
        cycles = detect_cycles(graph)
    stages["detect_cycles"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(cycles)} cycles",
    }

    # -------------------------------------------------------------------
    # Stage 11: Clustering
    # -------------------------------------------------------------------
    with StageTimer("find_clusters") as t:
        clusters = find_clusters(graph, metrics=metrics, cycles=cycles)
    stages["find_clusters"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(clusters)} clusters",
    }

    # -------------------------------------------------------------------
    # Stage 12: Health dashboard
    # -------------------------------------------------------------------
    with StageTimer("health_dashboard") as t:
        dashboard = compute_health_dashboard(graph, metrics, cycles, clusters=clusters)
    stages["health_dashboard"] = {
        "elapsed": t.elapsed,
        "heap_delta_mb": t.heap_delta_mb,
        "heap_peak_mb": t.heap_peak_mb,
        "detail": f"{len(dashboard.observations)} observations",
    }

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    total_time = sum(s["elapsed"] for s in stages.values())
    peak_rss = get_peak_rss_mb()

    edge_types = {}
    for node in graph.get_all_nodes():
        for edge in graph.get_edges_from(node.name):
            edge_types[edge.edge_type] = edge_types.get(edge.edge_type, 0) + 1

    return {
        "search_scope": str(search_scope),
        "file_counts": {"csproj": len(csproj_files), "cs": len(cs_files)},
        "graph_summary": {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "edge_types": edge_types,
            "types": total_types,
        },
        "peak_rss_mb": peak_rss,
        "total_time": total_time,
        "stages": stages,
    }


def print_report(results: dict, run_number: int = 0, total_runs: int = 1):
    """Print a formatted benchmark report."""
    header = "SCATTER GRAPH BUILD BENCHMARK"
    if total_runs > 1:
        header += f" (run {run_number}/{total_runs})"

    print("\n" + "=" * 90)
    print(header)
    print("=" * 90)

    print(f"\nSearch scope: {results['search_scope']}")
    fc = results["file_counts"]
    print(f"Files:        {fc['csproj']} .csproj, {fc['cs']} .cs")
    gs = results["graph_summary"]
    print(f"Graph:        {gs['nodes']} nodes, {gs['edges']} edges", end="")
    if "types" in gs:
        print(f", {gs['types']} types", end="")
    print()
    if "edge_types" in gs:
        et = gs["edge_types"]
        parts = [f"{k}: {v}" for k, v in sorted(et.items())]
        print(f"Edge types:   {', '.join(parts)}")
    print(f"Peak RSS:     {results['peak_rss_mb']:.1f} MB")
    print(f"Total time:   {results['total_time']:.2f}s")

    print(
        f"\n{'Stage':<25} {'Time':>8} {'% Total':>8} {'Heap +/-':>10} {'Heap Peak':>10} {'Detail'}"
    )
    print("-" * 90)

    for name, stage in results["stages"].items():
        pct = (stage["elapsed"] / results["total_time"] * 100) if results["total_time"] > 0 else 0
        heap_delta = f"{stage['heap_delta_mb']:+.1f} MB"
        heap_peak = f"{stage['heap_peak_mb']:.1f} MB"
        print(
            f"  {name:<23} {stage['elapsed']:>7.2f}s {pct:>7.1f}% {heap_delta:>10} {heap_peak:>10}  {stage['detail']}"
        )

    print("-" * 90)
    print(f"  {'TOTAL':<23} {results['total_time']:>7.2f}s {'100.0%':>8}")
    print()

    # Highlight bottleneck
    slowest = max(results["stages"].items(), key=lambda x: x[1]["elapsed"])
    pct = slowest[1]["elapsed"] / results["total_time"] * 100 if results["total_time"] > 0 else 0
    print(f"  Bottleneck: {slowest[0]} ({slowest[1]['elapsed']:.2f}s, {pct:.0f}% of total)")
    print()


def print_summary(all_results: list[dict]):
    """Print a comparison summary across multiple runs."""
    if len(all_results) < 2:
        return

    print("=" * 90)
    print("MULTI-RUN SUMMARY")
    print("=" * 90)

    times = [r["total_time"] for r in all_results]
    print(
        f"\n  Total time:  min={min(times):.2f}s  max={max(times):.2f}s  median={sorted(times)[len(times) // 2]:.2f}s"
    )
    print(f"  Peak RSS:    {max(r['peak_rss_mb'] for r in all_results):.1f} MB")

    # Per-stage comparison
    stage_names = list(all_results[0]["stages"].keys())
    print(f"\n  {'Stage':<25} {'Min':>8} {'Max':>8} {'Median':>8}")
    print("  " + "-" * 55)

    for stage_name in stage_names:
        stage_times = [
            r["stages"][stage_name]["elapsed"] for r in all_results if stage_name in r["stages"]
        ]
        if stage_times:
            stage_times.sort()
            median = stage_times[len(stage_times) // 2]
            print(
                f"  {stage_name:<25} {min(stage_times):>7.2f}s {max(stage_times):>7.2f}s {median:>7.2f}s"
            )

    print()


def run_consumer_benchmark(
    search_scope: Path,
    target_project: str = "GalaxyWorks.Data",
    class_name: str | None = None,
    method_name: str | None = None,
) -> dict:
    """Run find_consumers() in regex and hybrid modes, compare results and timing."""
    from scatter.analyzers.consumer_analyzer import find_consumers
    from scatter.scanners.project_scanner import derive_namespace
    from scatter.config import AnalysisConfig

    # Find the target .csproj
    target_csproj = None
    for p in search_scope.rglob("*.csproj"):
        if p.stem == target_project:
            target_csproj = p.resolve()
            break

    if target_csproj is None:
        print(f"Error: could not find {target_project}.csproj in {search_scope}", file=sys.stderr)
        sys.exit(1)

    namespace = derive_namespace(target_csproj) or target_project

    modes = {}
    for mode in ("regex", "hybrid"):
        config = AnalysisConfig(parser_mode=mode)

        with StageTimer(f"find_consumers_{mode}") as t:
            consumers, pipeline = find_consumers(
                target_csproj_path=target_csproj,
                search_scope_path=search_scope,
                target_namespace=namespace,
                class_name=class_name,
                method_name=method_name,
                disable_multiprocessing=True,
                analysis_config=config,
            )

        consumer_names = sorted(c["consumer_name"] for c in consumers)
        file_counts = {}
        for c in consumers:
            name = str(c["consumer_name"])
            files = c.get("relevant_files", [])
            file_counts[name] = len(files)

        modes[mode] = {
            "elapsed": t.elapsed,
            "consumer_count": len(consumers),
            "consumer_names": consumer_names,
            "consumer_file_counts": file_counts,
            "pipeline_stages": [
                {"name": s.name, "input": s.input_count, "output": s.output_count}
                for s in pipeline.stages
            ],
        }

    # Compute delta
    regex_names = set(modes["regex"]["consumer_names"])
    hybrid_names = set(modes["hybrid"]["consumer_names"])
    eliminated = sorted(regex_names - hybrid_names)
    speedup = (
        modes["regex"]["elapsed"] / modes["hybrid"]["elapsed"]
        if modes["hybrid"]["elapsed"] > 0
        else 0
    )

    return {
        "search_scope": str(search_scope),
        "target_project": target_project,
        "class_name": class_name,
        "method_name": method_name,
        "namespace": namespace,
        "modes": modes,
        "delta": {
            "eliminated_consumers": eliminated,
            "eliminated_count": len(eliminated),
            "regex_count": len(regex_names),
            "hybrid_count": len(hybrid_names),
            "time_ratio": round(speedup, 2),
        },
    }


def print_consumer_report(results: dict):
    """Print formatted consumer benchmark comparison."""
    print("\n" + "=" * 90)
    print("CONSUMER ANALYSIS BENCHMARK — regex vs hybrid")
    print("=" * 90)

    print(f"\n  Target:     {results['target_project']}")
    print(f"  Namespace:  {results['namespace']}")
    if results["class_name"]:
        print(f"  Class:      {results['class_name']}")
    if results["method_name"]:
        print(f"  Method:     {results['method_name']}")
    print(f"  Scope:      {results['search_scope']}")

    print(f"\n  {'Mode':<10} {'Time':>10} {'Consumers':>12} {'Pipeline'}")
    print("  " + "-" * 75)

    for mode_name in ("regex", "hybrid"):
        m = results["modes"][mode_name]
        arrow = " → ".join(f"{s['output']}" for s in m["pipeline_stages"])
        print(f"  {mode_name:<10} {m['elapsed']:>9.3f}s {m['consumer_count']:>12}    {arrow}")

    delta = results["delta"]
    print("\n  Delta:")
    print(
        f"    Consumers:  {delta['regex_count']} → {delta['hybrid_count']} ({delta['eliminated_count']} false positive(s) eliminated)"
    )
    print(f"    Time ratio: {delta['time_ratio']}x (hybrid / regex)")

    if delta["eliminated_consumers"]:
        print("\n  Eliminated (false positives):")
        for name in delta["eliminated_consumers"]:
            print(f"    - {name}")

    # Per-consumer file counts comparison
    regex_files = results["modes"]["regex"]["consumer_file_counts"]
    hybrid_files = results["modes"]["hybrid"]["consumer_file_counts"]
    all_names = sorted(set(regex_files) | set(hybrid_files))

    if all_names:
        print(f"\n  {'Consumer':<35} {'Regex Files':>12} {'Hybrid Files':>13} {'Note'}")
        print("  " + "-" * 75)
        for name in all_names:
            rf = regex_files.get(name, 0)
            hf = hybrid_files.get(name, 0)
            note = ""
            if name in delta["eliminated_consumers"]:
                note = "← ELIMINATED"
            elif hf < rf:
                note = f"← {rf - hf} file(s) filtered"
            print(f"  {name:<35} {rf:>12} {hf:>13}  {note}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Benchmark scatter graph building.")
    parser.add_argument("search_scope", type=str, help="Directory to analyze")
    parser.add_argument(
        "--include-db", action="store_true", help="Include DB dependency scanning stage"
    )
    parser.add_argument("--runs", type=int, default=1, help="Number of benchmark runs (default: 1)")
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Run one untimed warmup pass first (populates OS file cache)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "stages", "consumer"],
        default="stages",
        help="'full' calls build_dependency_graph() as a black box (with threading); "
        "'stages' instruments each internal stage sequentially (default); "
        "'consumer' runs find_consumers() in regex vs hybrid and compares. "
        "Numbers are not directly comparable between modes.",
    )
    parser.add_argument(
        "--parser-mode",
        choices=["regex", "hybrid"],
        default="regex",
        help="Parser mode for graph building: regex (default) or hybrid (tree-sitter AST)",
    )
    parser.add_argument(
        "--full-type-scan",
        action="store_true",
        help="Compute type_usage edges between all project pairs (disables reachable-set scoping)",
    )
    parser.add_argument(
        "--target-project",
        type=str,
        default="GalaxyWorks.Data",
        help="Target project for consumer mode (default: GalaxyWorks.Data)",
    )
    parser.add_argument(
        "--class-name", type=str, default=None, help="Class name filter for consumer mode"
    )
    parser.add_argument(
        "--method-name", type=str, default=None, help="Method name filter for consumer mode"
    )
    parser.add_argument(
        "--tracemalloc",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable tracemalloc heap tracking (default: on for stages, off for full)",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--output-file", "-o", type=str, help="Write JSON results to file")

    args = parser.parse_args()

    search_scope = Path(args.search_scope)
    if not search_scope.is_dir():
        print(f"Error: {search_scope} is not a directory", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.WARNING)

    # Start memory tracing (default: on for stages, off for full)
    use_tracemalloc = args.tracemalloc if args.tracemalloc is not None else (args.mode == "stages")
    if use_tracemalloc:
        tracemalloc.start()

    # Consumer mode has its own flow
    if args.mode == "consumer":
        results = run_consumer_benchmark(
            search_scope,
            target_project=args.target_project,
            class_name=args.class_name,
            method_name=args.method_name,
        )
        if args.json or args.output_file:
            output = json.dumps(results, indent=2, default=str)
            if args.output_file:
                Path(args.output_file).write_text(output)
                print(f"Results written to {args.output_file}")
            else:
                print(output)
        else:
            print_consumer_report(results)

        if tracemalloc.is_tracing():
            tracemalloc.stop()
        return

    if args.parser_mode != "regex" and args.mode != "consumer":
        print(
            f"Note: --parser-mode {args.parser_mode} has no effect on graph build. "
            "Use --mode consumer to compare regex vs hybrid."
        )

    run_fn = run_instrumented_build if args.mode == "stages" else run_benchmark

    # Optional warmup (populates OS file cache, not timed)
    if args.warmup:
        print("Warmup run (not timed)...")
        run_fn(search_scope, include_db=args.include_db, full_type_scan=args.full_type_scan)
        print("Warmup complete.\n")

    # Benchmark runs
    all_results = []
    for i in range(args.runs):
        results = run_fn(
            search_scope, include_db=args.include_db, full_type_scan=args.full_type_scan
        )
        all_results.append(results)

        if args.json or args.output_file:
            continue  # print at the end
        print_report(results, run_number=i + 1, total_runs=args.runs)

    if args.json or args.output_file:
        output_data = all_results if len(all_results) > 1 else all_results[0]
        output = json.dumps(output_data, indent=2, default=str)
        if args.output_file:
            Path(args.output_file).write_text(output)
            print(f"Results written to {args.output_file}")
        else:
            print(output)
    elif len(all_results) > 1:
        print_summary(all_results)

    if tracemalloc.is_tracing():
        tracemalloc.stop()


if __name__ == "__main__":
    main()
