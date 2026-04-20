"""Graph metrics enrichment for legacy and impact analysis modes.

Bridges the dependency graph (built by graph_builder) into consumer results
produced by find_consumers(). All enrichment is post-processing — no changes
to find_consumers() or the v1 bridge.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from scatter.core.graph import DependencyGraph
from scatter.analyzers.coupling_analyzer import (
    CycleGroup,
    ProjectMetrics,
    compute_all_metrics,
    detect_cycles,
)


@dataclass
class GraphContext:
    """Bundled graph analysis artifacts for enrichment lookups."""

    graph: DependencyGraph
    metrics: Dict[str, ProjectMetrics]
    cycles: List[CycleGroup]
    # Pre-computed for O(1) lookup during enrichment.
    # Upgrade to Dict[str, List[CycleGroup]] when reporters need cycle detail.
    cycle_members: Set[str]


def build_graph_context(
    search_scope, config, args, solution_index=None, discovered_files=None
) -> Optional["GraphContext"]:
    """Build or load a cached dependency graph and compute metrics.

    Returns GraphContext on success, None on failure. Caller should
    treat None as "enrichment unavailable" and continue without it.

    Supports incremental graph updates (v2 cache): if the cache has
    per-file/project facts, uses git diff to surgically patch the graph
    instead of rebuilding from scratch.
    """
    from scatter.analyzers.graph_builder import build_dependency_graph
    from scatter.store.graph_cache import (
        get_default_cache_path,
        load_and_validate,
        save_graph,
    )
    from scatter.store.graph_patcher import get_changed_files, patch_graph
    from pathlib import Path

    try:
        # Resolve cache path
        if config.graph.cache_dir:
            cache_path = Path(config.graph.cache_dir) / "graph_cache.json"
        else:
            cache_path = get_default_cache_path(search_scope)

        # Check cache (exact scope match)
        graph = None
        file_facts = None
        project_facts = None
        needs_full_rebuild = True

        if not config.graph.rebuild:
            cache_result = load_and_validate(
                cache_path,
                search_scope,
                config.graph.invalidation,
                parser_mode=config.analysis.parser_mode,
            )
            if cache_result is not None:
                graph, file_facts, project_facts, git_head, proj_set_hash = cache_result

                if file_facts is not None and project_facts is not None and git_head:
                    # v2 cache with git_head — try incremental patch
                    changed = get_changed_files(git_head, search_scope)
                    if changed is not None and len(changed) > 0:
                        result = patch_graph(
                            graph,
                            file_facts,
                            project_facts,
                            changed,
                            search_scope,
                            cached_project_set_hash=proj_set_hash,
                        )
                        if result.patch_applied:
                            save_graph(
                                result.graph,
                                cache_path,
                                search_scope,
                                result.file_facts,
                                result.project_facts,
                                parser_mode=config.analysis.parser_mode,
                            )
                            graph = result.graph
                            file_facts = result.file_facts
                            project_facts = result.project_facts
                            needs_full_rebuild = False
                            logging.info(
                                f"Incremental graph update: {result.files_processed} files, "
                                f"{result.projects_affected} projects ({result.elapsed_ms}ms)"
                            )
                        else:
                            graph = None  # fall through to full rebuild
                    elif changed is not None and len(changed) == 0:
                        logging.info("Using cached dependency graph (no changes detected).")
                        needs_full_rebuild = False
                    else:
                        graph = None  # git diff failed, full rebuild
                elif file_facts is not None and not git_head:
                    # v2 cache but no git_head (non-git dir) — fall back to mtime
                    from scatter.store.graph_cache import _is_cache_valid_mtime

                    if _is_cache_valid_mtime(cache_path, search_scope):
                        logging.info("Using cached dependency graph (mtime valid, no git).")
                        needs_full_rebuild = False
                    else:
                        logging.info("Cache stale (mtime). Full rebuild needed.")
                        graph = None
                elif file_facts is None:
                    # v1 cache (no facts) — force rebuild to upgrade to v2
                    logging.info("Using cached dependency graph (v1 cache, will upgrade to v2).")
                    graph = None  # force rebuild to capture facts
                else:
                    logging.info("Using cached dependency graph for metrics enrichment.")
                    needs_full_rebuild = False

        # Build if needed
        if graph is None or needs_full_rebuild:
            logging.info(f"Building dependency graph from {search_scope} for metrics enrichment...")
            build_result = build_dependency_graph(
                search_scope,
                disable_multiprocessing=args.disable_multiprocessing,
                exclude_patterns=config.exclude_patterns,
                include_db_dependencies=config.db.include_db_edges,
                sproc_prefixes=config.db.sproc_prefixes,
                capture_facts=True,
                full_type_scan=getattr(args, "full_type_scan", False),
                analysis_config=config.analysis,
                discovered_files=discovered_files,
            )
            graph, file_facts, project_facts = build_result
            # Post-process: populate solution membership
            if solution_index:
                for node in graph.get_all_nodes():
                    matches = solution_index.get(node.name, [])
                    node.solutions = sorted(set(si.name for si in matches))
            save_graph(
                graph,
                cache_path,
                search_scope,
                file_facts,
                project_facts,
                parser_mode=config.analysis.parser_mode,
            )

        logging.info(
            f"Graph built from search scope {search_scope} "
            f"— consumers outside this scope will not have graph metrics."
        )

        # Compute metrics and cycles
        coupling_weights = config.graph.coupling_weights
        metrics = compute_all_metrics(graph, coupling_weights=coupling_weights)
        cycles = detect_cycles(graph)

        # Pre-compute cycle membership set
        cycle_members: Set[str] = set()
        for cg in cycles:
            cycle_members.update(cg.projects)

        return GraphContext(
            graph=graph,
            metrics=metrics,
            cycles=cycles,
            cycle_members=cycle_members,
        )

    except Exception as e:
        logging.error(f"Failed to build graph context: {e}")
        return None


def enrich_legacy_results(
    all_results: list,
    graph_ctx: GraphContext,
) -> None:
    """Inject graph metrics into ConsumerResult objects.

    Matches on consumer_project_name (csproj stem) — consistent with
    the graph's own node identity (DependencyGraph.nodes keyed by name).

    Idempotent: safe to call multiple times on the same results.
    """
    unmatched: Set[str] = set()

    for result in all_results:
        consumer_name = result.consumer_project_name
        if not consumer_name:
            continue

        m = graph_ctx.metrics.get(consumer_name)
        if m is None:
            unmatched.add(consumer_name)
            continue

        result.coupling_score = round(m.coupling_score, 2)
        result.fan_in = m.fan_in
        result.fan_out = m.fan_out
        result.instability = round(m.instability, 3)
        result.in_cycle = consumer_name in graph_ctx.cycle_members

    if unmatched:
        logging.warning(
            f"Graph enrichment: {len(unmatched)} consumer(s) not found in graph: "
            f"{', '.join(sorted(unmatched))}"
        )


def enrich_consumers(
    consumers: list,
    graph_ctx: GraphContext,
) -> None:
    """Populate graph metric fields on EnrichedConsumer objects.

    Matches on consumer_name — consistent with graph node identity.
    """
    unmatched: Set[str] = set()

    for consumer in consumers:
        name = consumer.consumer_name
        m = graph_ctx.metrics.get(name)
        if m is None:
            unmatched.add(name)
            continue

        consumer.coupling_score = round(m.coupling_score, 2)
        consumer.fan_in = m.fan_in
        consumer.fan_out = m.fan_out
        consumer.instability = round(m.instability, 3)
        consumer.in_cycle = name in graph_ctx.cycle_members

    if unmatched:
        logging.warning(
            f"Graph enrichment: {len(unmatched)} consumer(s) not found in graph: "
            f"{', '.join(sorted(unmatched))}"
        )
