"""Dump codebase index mode handler."""

import logging
from pathlib import Path

from scatter.scanners.solution_scanner import scan_solutions, build_project_to_solutions
from scatter.modes.setup import populate_graph_solutions


def run_dump_index_mode(args) -> None:
    """Dump codebase index. Reads: args.search_scope, args.disable_multiprocessing, args.full_type_scan"""
    from scatter.cli_parser import _build_cli_overrides
    from scatter.config import load_config

    if not args.search_scope:
        # Can't use parser.error here — standalone mode, just exit
        print("Error: --dump-index requires --search-scope.")
        raise SystemExit(1)

    search_scope_abs = Path(args.search_scope).resolve(strict=True)
    cli_overrides = _build_cli_overrides(args)
    config = load_config(repo_root=search_scope_abs, cli_overrides=cli_overrides)

    from scatter.analyzers.graph_builder import build_dependency_graph
    from scatter.store.graph_cache import (
        get_default_cache_path,
        load_and_validate,
        save_graph,
    )
    from scatter.ai.codebase_index import build_codebase_index

    # Resolve cache path
    if config.graph.cache_dir:
        cache_path = Path(config.graph.cache_dir) / "graph_cache.json"
    else:
        cache_path = get_default_cache_path(search_scope_abs)

    # Try cached graph first, build if needed
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
            full_type_scan=getattr(args, "full_type_scan", False),
        )
        dump_solutions = scan_solutions(search_scope_abs)
        dump_sol_index = build_project_to_solutions(dump_solutions)
        populate_graph_solutions(graph, dump_sol_index)
        save_graph(graph, cache_path, search_scope_abs)

    index = build_codebase_index(graph, search_scope_abs)
    print(index.text)
    print(
        f"\n# {index.project_count} projects, {index.type_count} types, "
        f"{index.sproc_count} sprocs, {index.file_count} files, "
        f"{index.size_bytes:,} bytes"
    )
