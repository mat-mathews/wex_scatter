"""Dependency graph analysis mode handler."""

import logging
from pathlib import Path

from scatter.analysis import ModeContext
from scatter.output import _build_metadata, _require_output_file
from scatter.modes.setup import populate_graph_solutions


def run_graph_mode(args, ctx: ModeContext, start_time: float) -> None:
    """Dependency graph analysis. Reads: args.output_format, args.output_file, args.include_graph_topology, args.full_type_scan"""
    logging.info("\n--- Running Dependency Graph Analysis Mode ---")

    from scatter.analyzers.graph_builder import build_dependency_graph
    from scatter.analyzers.coupling_analyzer import (
        compute_all_metrics,
        detect_cycles,
        rank_by_coupling,
    )
    from scatter.store.graph_cache import (
        get_default_cache_path,
        load_and_validate,
        save_graph,
    )
    from scatter.reports.graph_reporter import (
        print_graph_report,
        write_graph_json_report,
    )

    config = ctx.config
    search_scope_abs = ctx.search_scope

    # Resolve cache path
    if config.graph.cache_dir:
        cache_path = Path(config.graph.cache_dir) / "graph_cache.json"
    else:
        cache_path = get_default_cache_path(search_scope_abs)

    # Check cache
    graph = None
    if not config.graph.rebuild:
        cache_result = load_and_validate(
            cache_path,
            search_scope_abs,
            config.graph.invalidation,
            parser_mode=config.analysis.parser_mode,
        )
        if cache_result is not None:
            graph = cache_result[0]
            logging.info("Using cached dependency graph.")

    # Build if needed
    if graph is None:
        logging.info("Building dependency graph...")
        graph = build_dependency_graph(
            search_scope_abs,
            disable_multiprocessing=args.disable_multiprocessing,
            exclude_patterns=config.exclude_patterns,
            include_db_dependencies=config.db.include_db_edges,
            sproc_prefixes=config.db.sproc_prefixes,
            full_type_scan=getattr(args, "full_type_scan", False),
            analysis_config=config.analysis,
            discovered_files=ctx.discovered_files,
        )
        populate_graph_solutions(graph, ctx.solution_index)
        save_graph(graph, cache_path, search_scope_abs, parser_mode=config.analysis.parser_mode)

    # Compute metrics
    coupling_weights = config.graph.coupling_weights
    metrics = compute_all_metrics(graph, coupling_weights=coupling_weights)
    cycles = detect_cycles(graph)
    ranked = rank_by_coupling(metrics, top_n=10)

    # Domain analysis
    from scatter.analyzers.domain_analyzer import find_clusters

    clusters = find_clusters(graph, min_cluster_size=2, metrics=metrics, cycles=cycles)

    # Solution metrics
    from scatter.analyzers.coupling_analyzer import compute_solution_metrics

    sol_metrics, bridge_projs = compute_solution_metrics(graph)

    # Health dashboard
    from scatter.analyzers.health_analyzer import compute_health_dashboard

    dashboard = compute_health_dashboard(
        graph,
        metrics,
        cycles,
        clusters=clusters,
        solution_metrics=sol_metrics if sol_metrics else None,
        bridge_projects=bridge_projs if bridge_projs else None,
    )

    # Output
    if args.output_format == "json":
        output_path = _require_output_file(args, "JSON")
        write_graph_json_report(
            graph,
            metrics,
            ranked,
            cycles,
            output_path,
            clusters=clusters,
            metadata=_build_metadata(args, search_scope_abs, start_time, graph_enriched=True),
            include_topology=args.include_graph_topology,
            dashboard=dashboard,
            solution_metrics=sol_metrics if sol_metrics else None,
            bridge_projects=bridge_projs if bridge_projs else None,
        )
        logging.info(f"Graph report written to {args.output_file}")

    elif args.output_format == "csv":
        output_path = _require_output_file(args, "CSV")
        from scatter.reports.graph_reporter import write_graph_csv_report

        write_graph_csv_report(graph, metrics, output_path, clusters=clusters)
        logging.info(f"Graph CSV report written to {args.output_file}")

    elif args.output_format == "markdown":
        from scatter.reports.markdown_reporter import (
            build_graph_markdown,
            write_graph_markdown_report,
        )

        md_metadata = _build_metadata(args, search_scope_abs, start_time, graph_enriched=True)
        if args.output_file:
            write_graph_markdown_report(
                graph,
                metrics,
                ranked,
                cycles,
                Path(args.output_file),
                clusters=clusters,
                metadata=md_metadata,
                dashboard=dashboard,
            )
            logging.info(f"Graph markdown report written to {args.output_file}")
        else:
            print(
                build_graph_markdown(
                    graph,
                    metrics,
                    ranked,
                    cycles,
                    clusters=clusters,
                    metadata=md_metadata,
                    dashboard=dashboard,
                )
            )

    elif args.output_format == "mermaid":
        from scatter.reports.graph_reporter import generate_mermaid

        mermaid_output = generate_mermaid(graph, clusters=clusters)
        if args.output_file:
            output_path = Path(args.output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(mermaid_output, encoding="utf-8")
            logging.info(f"Mermaid diagram written to {args.output_file}")
        else:
            print(mermaid_output)

    else:
        print_graph_report(
            graph,
            ranked,
            cycles,
            clusters=clusters,
            dashboard=dashboard,
            solution_metrics=sol_metrics if sol_metrics else None,
        )

    node_count = graph.node_count
    edge_count = graph.edge_count
    cycle_count = len(cycles)
    print(
        f"\nAnalysis complete. {node_count} projects, {edge_count} dependencies, {cycle_count} cycle(s).\n"
    )
