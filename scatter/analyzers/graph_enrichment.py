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


def build_graph_context(search_scope, config, args) -> Optional["GraphContext"]:
    """Build or load a cached dependency graph and compute metrics.

    Returns GraphContext on success, None on failure. Caller should
    treat None as "enrichment unavailable" and continue without it.
    """
    from scatter.analyzers.graph_builder import build_dependency_graph
    from scatter.store.graph_cache import (
        get_default_cache_path,
        load_and_validate,
        save_graph,
    )
    from pathlib import Path

    try:
        # Resolve cache path
        if config.graph.cache_dir:
            cache_path = Path(config.graph.cache_dir) / "graph_cache.json"
        else:
            cache_path = get_default_cache_path(search_scope)

        # Check cache (exact scope match)
        graph = None
        if not config.graph.rebuild:
            graph = load_and_validate(
                cache_path, search_scope, config.graph.invalidation
            )
            if graph is not None:
                logging.info("Using cached dependency graph for metrics enrichment.")

        # Build if needed
        if graph is None:
            logging.info(
                f"Building dependency graph from {search_scope} for metrics enrichment..."
            )
            graph = build_dependency_graph(
                search_scope,
                disable_multiprocessing=args.disable_multiprocessing,
                exclude_patterns=config.exclude_patterns,
                include_db_dependencies=config.db.include_db_edges,
                sproc_prefixes=config.db.sproc_prefixes,
            )
            save_graph(graph, cache_path, search_scope)

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
    all_results: List[Dict],
    graph_ctx: GraphContext,
) -> None:
    """Inject graph metrics into legacy result dicts.

    Matches on ConsumerProjectName (csproj stem) — consistent with
    the graph's own node identity (DependencyGraph.nodes keyed by name).

    Idempotent: safe to call multiple times on the same results.
    """
    unmatched: Set[str] = set()

    for result_dict in all_results:
        consumer_name = result_dict.get("ConsumerProjectName")
        if not consumer_name:
            continue

        m = graph_ctx.metrics.get(consumer_name)
        if m is None:
            unmatched.add(consumer_name)
            result_dict.setdefault("CouplingScore", None)
            result_dict.setdefault("FanIn", None)
            result_dict.setdefault("FanOut", None)
            result_dict.setdefault("Instability", None)
            result_dict.setdefault("InCycle", None)
            continue

        result_dict["CouplingScore"] = round(m.coupling_score, 2)
        result_dict["FanIn"] = m.fan_in
        result_dict["FanOut"] = m.fan_out
        result_dict["Instability"] = round(m.instability, 3)
        result_dict["InCycle"] = consumer_name in graph_ctx.cycle_members

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
