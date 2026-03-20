"""Scatter CLI entry point — argument parsing and mode dispatch."""
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from scatter.cli_parser import build_parser, _build_cli_overrides
from scatter.cli import (
    ModeContext,
    apply_impact_graph_enrichment,
    dispatch_legacy_output,
    run_git_analysis,
    run_target_analysis,
    run_sproc_analysis,
    _build_metadata,
    _require_output_file,
)

from scatter.core.parallel import find_files_with_pattern_parallel
from scatter.compat.v1_bridge import map_batch_jobs_from_config_repo
from scatter.scanners.solution_scanner import (
    SolutionInfo,
    scan_solutions,
    build_project_to_solutions,
)

from scatter.config import load_config
from scatter.ai.router import AIRouter


def _populate_graph_solutions(graph, solution_index):
    """Post-process: set node.solutions from the solution reverse index."""
    if not solution_index:
        return
    for node in graph.get_all_nodes():
        matches = solution_index.get(node.name, [])
        node.solutions = sorted(set(si.name for si in matches))


def main():
    start_time = time.monotonic()
    parser = build_parser()

    args = parser.parse_args()

    # --- setup logging ---
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if args.verbose:
        logging.debug("Debug logging enabled.")

    is_git_mode = args.branch_name is not None
    is_target_mode = args.target_project is not None
    is_sproc_mode = args.stored_procedure is not None
    is_impact_mode = args.sow is not None or args.sow_file is not None
    is_graph_mode = args.graph
    is_dump_index = getattr(args, 'dump_index', False)

    # Handle --dump-index standalone mode
    if is_dump_index:
        if not args.search_scope:
            parser.error("--dump-index requires --search-scope.")
        search_scope_abs = Path(args.search_scope).resolve(strict=True)
        cli_overrides = _build_cli_overrides(args)
        config = load_config(repo_root=search_scope_abs, cli_overrides=cli_overrides)

        from scatter.analyzers.graph_builder import build_dependency_graph
        from scatter.store.graph_cache import cache_exists, get_default_cache_path, load_and_validate, save_graph
        from scatter.ai.codebase_index import build_codebase_index

        # Try cached graph first, build if needed
        if config.graph.cache_dir:
            cache_path = Path(config.graph.cache_dir) / "graph_cache.json"
        else:
            cache_path = get_default_cache_path(search_scope_abs)

        graph = None
        cache_result = load_and_validate(cache_path, search_scope_abs, config.graph.invalidation)
        if cache_result is not None:
            graph = cache_result[0]
            logging.info("Using cached dependency graph.")

        if graph is None:
            logging.info("Building dependency graph...")
            graph = build_dependency_graph(
                search_scope_abs,
                disable_multiprocessing=args.disable_multiprocessing,
                exclude_patterns=config.exclude_patterns,
            )
            # Populate solutions before caching
            dump_solutions = scan_solutions(search_scope_abs)
            dump_sol_index = build_project_to_solutions(dump_solutions)
            _populate_graph_solutions(graph, dump_sol_index)
            save_graph(graph, cache_path, search_scope_abs)

        index = build_codebase_index(graph, search_scope_abs)
        print(index.text)
        print(f"\n# {index.project_count} projects, {index.type_count} types, "
              f"{index.sproc_count} sprocs, {index.file_count} files, "
              f"{index.size_bytes:,} bytes")
        return

    # Validate that a mode was selected (since mode_group is not required for --dump-index)
    if not any([is_git_mode, is_target_mode, is_sproc_mode, is_impact_mode, is_graph_mode]):
        parser.error("A mode (--branch-name, --target-project, --stored-procedure, --sow, --sow-file, or --graph) must be selected, or use --dump-index.")

    if is_graph_mode and args.output_format == 'pipelines':
        parser.error("Pipeline output format is not supported in graph mode.")

    if not is_graph_mode and args.output_format == 'mermaid':
        parser.error("Mermaid output format is only supported in graph mode (--graph).")

    if args.output_format == 'pipelines' and not args.pipeline_csv:
        logging.warning("--output-format pipelines was requested without --pipeline-csv; output will be empty.")

    # --- load config and configure AI provider ---
    cli_overrides = _build_cli_overrides(args)
    # Resolve without strict=True — config loading tolerates missing dirs.
    # The real path validation with strict=True happens below.
    config_root = Path(args.search_scope).resolve() if args.search_scope else Path(args.repo_path).resolve()
    config = load_config(repo_root=config_root, cli_overrides=cli_overrides)
    router = AIRouter(config)

    ai_provider = None
    if args.summarize_consumers or args.enable_hybrid_git or is_impact_mode:
        reason = []
        if args.summarize_consumers:
            reason.append("summarization")
        if args.enable_hybrid_git:
            reason.append("hybrid git analysis")
        if is_impact_mode:
            reason.append("impact analysis")
        logging.info(f"{', '.join(reason).capitalize()} enabled. Configuring AI provider...")
        ai_provider = router.get_provider()
        if ai_provider is None:
            logging.error("AI provider configuration failed.")
            if args.summarize_consumers:
                logging.error("Summarization will be disabled.")
                args.summarize_consumers = False
            if args.enable_hybrid_git:
                logging.warning("Hybrid git analysis will fall back to regex extraction.")
                args.enable_hybrid_git = False
            if is_impact_mode:
                logging.error("Impact analysis requires a working AI provider. Exiting.")
                sys.exit(1)

    repo_path_abs: Optional[Path] = None
    search_scope_abs: Optional[Path] = None
    target_csproj_abs_path: Optional[Path] = None

    try:
        # validate search scope
        if args.search_scope:
            search_scope_abs = Path(args.search_scope).resolve(strict=True)
            logging.info(f"Using specified search scope: {search_scope_abs}")
        elif is_git_mode:
            repo_path_abs = Path(args.repo_path).resolve(strict=True)
            search_scope_abs = repo_path_abs
            logging.info(f"Using repository path as search scope: {search_scope_abs}")
        elif is_sproc_mode:
            parser.error("--search-scope is required when using --stored-procedure mode.")
        elif is_target_mode:
            parser.error("--search-scope is required when using --target-project mode.")
        elif is_impact_mode:
            parser.error("--search-scope is required when using --sow or --sow-file mode.")
        elif is_graph_mode:
            parser.error("--search-scope is required when using --graph mode.")
        else:
            parser.error("A mode (--branch-name, --target-project, --stored-procedure, --sow, or --sow-file) must be selected.")

        if is_sproc_mode:
            if args.repo_path != "." or args.base_branch != "main":
                if args.repo_path != Path(args.search_scope).resolve(strict=True).as_posix() and args.branch_name is None:
                    logging.warning("Arguments --repo-path and --base-branch are not applicable in --stored-procedure mode and will be ignored.")

        if is_git_mode:
            if not repo_path_abs:
                repo_path_abs = Path(args.repo_path).resolve(strict=True)

        if is_target_mode:
            target_path_input = Path(args.target_project).resolve()
            if target_path_input.is_dir():
                try:
                    target_csproj_abs_path = next(target_path_input.glob('*.csproj'))
                    logging.info(f"Found target project file: {target_csproj_abs_path}")
                except StopIteration:
                    raise FileNotFoundError(f"No .csproj file found in the target directory: {target_path_input}")
            elif target_path_input.is_file() and target_path_input.suffix.lower() == '.csproj':
                target_csproj_abs_path = target_path_input
                logging.info(f"Using target project file: {target_csproj_abs_path}")
            else:
                raise ValueError(f"Invalid target project path: '{args.target_project}'. Must be a .csproj file or a directory containing one.")

        pipeline_csv_path = Path(args.pipeline_csv).resolve() if args.pipeline_csv else None

        if args.method_name and not args.class_name:
            logging.warning("Ignoring --method-name because --class-name was not provided.")
            args.method_name = None

        if search_scope_abs is None:
            raise ValueError("Search scope could not be determined.")

    except (FileNotFoundError, ValueError) as e:
        logging.error(f"Input validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during input validation: {e}")
        sys.exit(1)

    # --- Step 1: Parse solution files ---
    logging.info(f"\n--- Caching solution files ---")
    solution_infos: List[SolutionInfo] = []
    solution_index: Dict = {}
    solution_file_cache: List[Path] = []
    if search_scope_abs:
        logging.info(f"Scanning for .sln files within '{search_scope_abs}'...")
        try:
            solution_infos = scan_solutions(search_scope_abs)
            solution_index = build_project_to_solutions(solution_infos)
            solution_file_cache = [si.path for si in solution_infos]
            logging.info(f"Found {len(solution_infos)} solution files")
        except Exception as e:
            logging.error(f"An error occurred while scanning for solution files: {e}")
    else:
        logging.warning("Search scope not defined, cannot cache solution files.")

    # --- Load batch job mapping if app-config-path is provided ---
    batch_job_map: Dict[str, List[str]] = {}
    if args.app_config_path:
        logging.info(f"\n--- Loading batch job data from app-config repo ---")
        try:
            app_config_repo_path = Path(args.app_config_path).resolve(strict=True)
            batch_job_map = map_batch_jobs_from_config_repo(app_config_repo_path)
        except FileNotFoundError:
            logging.error(f"The provided --app-config-path does not exist: {args.app_config_path}")
        except Exception as e:
            logging.error(f"An error occurred processing the --app-config-path: {e}")

    # --- load pipeline data ---
    logging.info(f"\n--- Loading pipeline data ---")
    pipeline_map: Dict[str, str] = {}
    if pipeline_csv_path:
        if not pipeline_csv_path.is_file():
            logging.warning(f"Pipeline CSV file not found: {pipeline_csv_path}. Proceeding without pipeline data.")
        else:
            try:
                with open(pipeline_csv_path, mode='r', newline='', encoding='utf-8-sig') as csvfile:
                    reader = csv.DictReader(csvfile)
                    required_headers = {'Application Name', 'Pipeline Name'}
                    if not required_headers.issubset(reader.fieldnames or set()):
                        missing = required_headers - set(reader.fieldnames or [])
                        logging.error(f"Pipeline CSV missing required columns: {', '.join(missing)}. Proceeding without pipeline data.")
                    else:
                        loaded_count = 0
                        duplicate_count = 0
                        for row in reader:
                            app_name = row.get('Application Name','').strip()
                            pipe_name = row.get('Pipeline Name','').strip()
                            if app_name and pipe_name:
                                if app_name in pipeline_map:
                                    duplicate_count += 1
                                    logging.debug(f"Duplicate application '{app_name}' in pipeline CSV. Overwriting.")
                                pipeline_map[app_name] = pipe_name
                                loaded_count += 1
                        log_msg = f"Loaded {loaded_count} pipeline mappings."
                        if duplicate_count > 0: log_msg += f" ({duplicate_count} duplicate application names found, last entry used)."
                        logging.info(log_msg)

            except Exception as e:
                logging.error(f"Error loading pipeline CSV '{pipeline_csv_path}': {e}. Proceeding without pipeline data.")
    else:
        logging.info("No pipeline CSV provided.")


    # --- main logic ---
    all_results: List[Dict[str, Union[str, Dict, List[str]]]] = []
    filter_pipeline = None  # populated by find_consumers() in git/target/sproc modes

    # Build graph context: auto-load from cache, or build if --graph-metrics requested.
    # Scope mismatch or corrupt cache → build_graph_context() returns None silently,
    # which is expected — auto-load is best-effort, not guaranteed.
    # Phase C: if no cache exists, graph is built after find_consumers() via _ensure_graph_context().
    graph_ctx = None
    graph_enriched = False
    if not args.no_graph and search_scope_abs and not is_graph_mode:
        from scatter.store.graph_cache import cache_exists
        from scatter.analyzers.graph_enrichment import build_graph_context
        if args.graph_metrics or cache_exists(search_scope_abs, config.graph.cache_dir):
            graph_ctx = build_graph_context(search_scope_abs, config, args, solution_index=solution_index)
            if graph_ctx:
                graph_enriched = True
            elif args.graph_metrics:
                # Only warn if user explicitly asked for metrics
                logging.warning("Graph context unavailable. Proceeding without graph metrics.")

    # Build ModeContext for legacy mode handlers
    ctx = ModeContext(
        search_scope=search_scope_abs,
        config=config,
        pipeline_map=pipeline_map,
        solution_file_cache=solution_file_cache,
        batch_job_map=batch_job_map,
        ai_provider=ai_provider,
        graph_ctx=graph_ctx,
        solution_index=solution_index,
        graph_enriched=graph_enriched,
        class_name=args.class_name,
        method_name=args.method_name,
        target_namespace=args.target_namespace,
        summarize_consumers=args.summarize_consumers,
        max_workers=args.max_workers,
        chunk_size=args.chunk_size,
        disable_multiprocessing=args.disable_multiprocessing,
        cs_analysis_chunk_size=args.cs_analysis_chunk_size,
        csproj_analysis_chunk_size=args.csproj_analysis_chunk_size,
        no_graph=args.no_graph,
    )

    # == GIT BRANCH ANALYSIS MODE ==
    if is_git_mode:
        assert repo_path_abs is not None and search_scope_abs is not None
        try:
            result = run_git_analysis(
                ctx, repo_path_abs, args.branch_name, args.base_branch,
                args.enable_hybrid_git,
            )
        except ValueError as e:
            logging.error(str(e))
            sys.exit(1)
        all_results = result.all_results
        filter_pipeline = result.filter_pipeline
        graph_enriched = result.graph_enriched

    # == TARGET PROJECT ANALYSIS MODE ==
    elif is_target_mode:
        assert target_csproj_abs_path is not None and search_scope_abs is not None
        try:
            result = run_target_analysis(ctx, target_csproj_abs_path)
        except ValueError as e:
            logging.error(str(e))
            sys.exit(1)
        all_results = result.all_results
        filter_pipeline = result.filter_pipeline
        graph_enriched = result.graph_enriched

    # == STORED PROCEDURE ANALYSIS MODE ==
    elif is_sproc_mode:
        assert search_scope_abs is not None
        result = run_sproc_analysis(ctx, args.stored_procedure, args.sproc_regex_pattern)
        all_results = result.all_results
        filter_pipeline = result.filter_pipeline
        graph_enriched = result.graph_enriched

    # == IMPACT ANALYSIS MODE ==
    elif is_impact_mode:
        assert search_scope_abs is not None
        logging.info(f"\n--- Running Impact Analysis Mode ---")

        # Resolve SOW text
        if args.sow_file:
            try:
                sow_file_path = Path(args.sow_file).resolve(strict=True)
                sow_text = sow_file_path.read_text(encoding='utf-8')
                logging.info(f"Loaded work request from file: {sow_file_path}")
            except FileNotFoundError:
                logging.error(f"SOW file not found: {args.sow_file}")
                sys.exit(1)
            except Exception as e:
                logging.error(f"Error reading SOW file: {e}")
                sys.exit(1)
        else:
            sow_text = args.sow

        logging.info(f"Work request: {sow_text[:200]}{'...' if len(sow_text) > 200 else ''}")

        from scatter.analyzers.impact_analyzer import run_impact_analysis
        from scatter.reports.console_reporter import print_impact_report
        from scatter.reports.json_reporter import write_impact_json_report
        from scatter.reports.csv_reporter import write_impact_csv_report

        impact_report = run_impact_analysis(
            sow_text=sow_text,
            search_scope=search_scope_abs,
            ai_provider=ai_provider,
            max_depth=config.max_depth,
            pipeline_map=pipeline_map,
            solution_file_cache=solution_file_cache,
            max_workers=args.max_workers,
            chunk_size=args.chunk_size,
            disable_multiprocessing=args.disable_multiprocessing,
            cs_analysis_chunk_size=args.cs_analysis_chunk_size,
            csproj_analysis_chunk_size=args.csproj_analysis_chunk_size,
            graph=ctx.graph_ctx.graph if ctx.graph_ctx else None,
            min_confidence=args.sow_min_confidence,
            solution_index=solution_index,
        )

        # Enrich consumers with graph metrics if available
        apply_impact_graph_enrichment(impact_report, ctx)
        graph_enriched = ctx.graph_enriched

        # Output impact report (separate from legacy all_results path)
        _gm_impact = graph_enriched
        if args.output_format == 'json':
            output_path = _require_output_file(args, "JSON")
            write_impact_json_report(impact_report, output_path,
                                     metadata=_build_metadata(args, search_scope_abs, start_time, graph_enriched=graph_enriched))
        elif args.output_format == 'csv':
            output_path = _require_output_file(args, "CSV")
            write_impact_csv_report(impact_report, output_path,
                                    graph_metrics_requested=_gm_impact)
        elif args.output_format == 'markdown':
            from scatter.reports.markdown_reporter import build_impact_markdown, write_impact_markdown_report
            md_metadata = _build_metadata(args, search_scope_abs, start_time, graph_enriched=graph_enriched)
            if args.output_file:
                write_impact_markdown_report(impact_report, Path(args.output_file),
                                             metadata=md_metadata,
                                             graph_metrics_requested=_gm_impact)
            else:
                print(build_impact_markdown(impact_report, metadata=md_metadata,
                                            graph_metrics_requested=_gm_impact))
        elif args.output_format == 'pipelines':
            from scatter.reports.pipeline_reporter import extract_impact_pipeline_names, format_pipeline_output, write_pipeline_report
            names = extract_impact_pipeline_names(impact_report)
            if args.output_file:
                write_pipeline_report(names, Path(args.output_file))
            else:
                output = format_pipeline_output(names)
                if output:
                    print(output)
        else:
            print_impact_report(impact_report)

        consumer_count = sum(len(ti.consumers) for ti in impact_report.targets)
        target_count = len(impact_report.targets)
        if args.output_format != 'pipelines':
            print(f"\nAnalysis complete. {consumer_count} consumer(s) found across {target_count} target(s).\n")
        return

    # == DEPENDENCY GRAPH ANALYSIS MODE ==
    # --graph-metrics is implicit in graph mode; flag ignored.
    elif is_graph_mode:
        assert search_scope_abs is not None
        logging.info(f"\n--- Running Dependency Graph Analysis Mode ---")

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

        # Resolve cache path
        if config.graph.cache_dir:
            cache_path = Path(config.graph.cache_dir) / "graph_cache.json"
        else:
            cache_path = get_default_cache_path(search_scope_abs)

        # Check cache (single-pass: read, validate, deserialize)
        graph = None
        if not config.graph.rebuild:
            cache_result = load_and_validate(
                cache_path, search_scope_abs, config.graph.invalidation
            )
            if cache_result is not None:
                graph = cache_result[0]  # (graph, file_facts, project_facts, git_head, project_set_hash)
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
            )
            _populate_graph_solutions(graph, solution_index)
            save_graph(graph, cache_path, search_scope_abs)

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
            graph, metrics, cycles, clusters=clusters,
            solution_metrics=sol_metrics if sol_metrics else None,
            bridge_projects=bridge_projs if bridge_projs else None,
        )

        # Output
        if args.output_format == "json":
            output_path = _require_output_file(args, "JSON")
            write_graph_json_report(
                graph, metrics, ranked, cycles, output_path,
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
            from scatter.reports.markdown_reporter import build_graph_markdown, write_graph_markdown_report
            md_metadata = _build_metadata(args, search_scope_abs, start_time, graph_enriched=True)
            if args.output_file:
                write_graph_markdown_report(
                    graph, metrics, ranked, cycles, Path(args.output_file),
                    clusters=clusters, metadata=md_metadata, dashboard=dashboard,
                )
                logging.info(f"Graph markdown report written to {args.output_file}")
            else:
                print(build_graph_markdown(
                    graph, metrics, ranked, cycles,
                    clusters=clusters, metadata=md_metadata, dashboard=dashboard,
                ))

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
                graph, ranked, cycles, clusters=clusters, dashboard=dashboard,
                solution_metrics=sol_metrics if sol_metrics else None,
            )

        node_count = graph.node_count
        edge_count = graph.edge_count
        cycle_count = len(cycles)
        print(f"\nAnalysis complete. {node_count} projects, {edge_count} dependencies, {cycle_count} cycle(s).\n")
        return

    # --- step: output combined results ---
    dispatch_legacy_output(
        all_results, filter_pipeline, args,
        search_scope_abs, start_time, graph_enriched,
    )


if __name__ == "__main__":
    main()
