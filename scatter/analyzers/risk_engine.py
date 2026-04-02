"""Unified risk engine for Scatter.

Public API — three functions:
  compute_risk_profile()  — score a single target
  aggregate_risk()        — aggregate across multiple targets
  format_risk_factors()   — extract sorted human-readable factors

Pure functions. Data in, score out. No I/O (Decision: Devon).
Structured logging at DEBUG/INFO (Decision #5, Marcus).
"""

import logging
import time
from typing import Dict, List, Optional, Set, Union

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.analyzers.risk_dimensions import (
    score_blast_radius,
    score_cycle,
    score_database,
    score_domain_boundary,
    score_instability,
    score_structural,
)
from scatter.core.graph import DependencyGraph
from scatter.core.risk_models import (
    AggregateRisk,
    RiskContext,
    RiskDimension,
    RiskLevel,
    RiskProfile,
    _ZERO_DIMENSION,
    composite_to_risk_level,
)

logger = logging.getLogger(__name__)


def compute_risk_profile(
    target: str,
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    consumers: List[str],
    cycles: List[CycleGroup],
    context: RiskContext,
    direct_consumer_count: int = 0,
    transitive_consumer_count: int = 0,
    consumer_cluster_ids: Optional[List[str]] = None,
    target_cluster_id: Optional[str] = None,
    team_map: Optional[Dict[str, str]] = None,
) -> RiskProfile:
    """Compute full risk profile for a single target.

    Decision #7 (Fatima): if target is not in graph or metrics,
    returns a GREEN profile with all dimensions data_available=False.
    Never raises.

    Decision #5 (Marcus): logs dimension scores at DEBUG,
    composite result at INFO, wall-clock timing always.
    """
    start = time.monotonic()

    target_metrics = metrics.get(target)

    # Score all 6 dimensions
    structural = score_structural(target, target_metrics, metrics)
    instability = score_instability(target, target_metrics)
    cycle = score_cycle(target, cycles)
    database = score_database(target, graph, target_metrics, team_map)
    blast = score_blast_radius(
        target, direct_consumer_count, transitive_consumer_count, metrics,
    )
    domain = score_domain_boundary(
        target,
        consumer_cluster_ids or [],
        target_cluster_id,
        team_map,
        consumers,
    )

    # change_surface is not computed by the engine — it requires diff data
    # that only the PR analyzer has. data_available=False signals to reporters
    # that this dimension was not analyzed, not that it scored zero.
    change_surface = RiskDimension(
        name="change_surface",
        label="Change surface",
        score=0.0,
        severity="low",
        factors=[],
        raw_metrics={},
        data_available=False,
    )

    # Composite score: weighted max (not average)
    dimensions = [structural, instability, cycle, database, blast, domain, change_surface]
    composite = _compute_composite(dimensions, context)
    risk_level = composite_to_risk_level(composite, context)

    # Collect and sort risk factors
    all_factors = _collect_factors(dimensions, context)

    # Shared sprocs from database dimension
    shared_sprocs = database.raw_metrics.get("shared_sproc_names", [])

    # Count consumers in cycles
    cycle_members: Set[str] = set()
    for cg in cycles:
        cycle_members.update(cg.projects)
    consumers_in_cycles = sum(1 for c in consumers if c in cycle_members)

    # Count consumers crossing domains
    consumers_cross = 0
    if consumer_cluster_ids and target_cluster_id:
        consumers_cross = sum(1 for cid in consumer_cluster_ids if cid != target_cluster_id)

    elapsed_ms = (time.monotonic() - start) * 1000

    profile = RiskProfile(
        target_name=target,
        target_type="project",
        structural=structural,
        instability=instability,
        cycle=cycle,
        database=database,
        blast_radius=blast,
        domain_boundary=domain,
        change_surface=change_surface,
        composite_score=round(composite, 3),
        risk_level=risk_level,
        risk_factors=all_factors,
        consumer_count=direct_consumer_count,
        transitive_consumer_count=transitive_consumer_count,
        consumers_in_cycles=consumers_in_cycles,
        consumers_cross_domain=consumers_cross,
        shared_sprocs=list(shared_sprocs),
    )

    # Structured logging (Decision #5)
    logger.debug(
        "risk_profile target=%s structural=%.3f instability=%.3f cycle=%.3f "
        "database=%.3f blast_radius=%.3f domain_boundary=%.3f "
        "data_available=[%s]",
        target,
        structural.score, instability.score, cycle.score,
        database.score, blast.score, domain.score,
        ",".join(
            d.name for d in [structural, instability, cycle, database, blast, domain]
            if not d.data_available
        ) or "all",
    )
    logger.info(
        "risk_profile target=%s composite=%.3f level=%s elapsed_ms=%.1f",
        target, composite, risk_level.value, elapsed_ms,
    )

    return profile


def aggregate_risk(
    profiles: List[RiskProfile],
    context: RiskContext,
) -> AggregateRisk:
    """Aggregate risk across multiple targets.

    Decision #8 (Fatima): empty list → GREEN aggregate, all zeros.
    Never raises ValueError from max() on empty sequence.

    Note: total_consumers and total_transitive are sums across profiles,
    NOT deduplicated. If two targets share consumers, those consumers are
    counted twice. Callers that need unique counts must deduplicate before
    passing consumer counts to compute_risk_profile().
    """
    if not profiles:
        return AggregateRisk(profiles=[])

    # Per-dimension: take the highest-scoring dimension across all profiles
    dim_names = [
        ("structural", "Structural coupling"),
        ("instability", "Instability"),
        ("cycle", "Cycle entanglement"),
        ("database", "Database coupling"),
        ("blast_radius", "Blast radius"),
        ("domain_boundary", "Domain boundary"),
        ("change_surface", "Change surface"),
    ]

    agg_dims = {}
    for attr, label in dim_names:
        candidates = [getattr(p, attr) for p in profiles]
        best = max(candidates, key=lambda d: d.score)
        agg_dims[attr] = best

    # Composite: max across all profile composites
    composite = max(p.composite_score for p in profiles)
    risk_level = composite_to_risk_level(composite, context)

    # Collect unique risk factors across all profiles, sorted by weight * score
    all_factors = _collect_factors(list(agg_dims.values()), context)

    # Consumer totals (sum, not deduplicated — see docstring)
    total_transitive = 0
    for p in profiles:
        total_transitive += p.transitive_consumer_count

    # Risk level counts
    red = sum(1 for p in profiles if p.risk_level == RiskLevel.RED)
    yellow = sum(1 for p in profiles if p.risk_level == RiskLevel.YELLOW)
    green = sum(1 for p in profiles if p.risk_level == RiskLevel.GREEN)

    # Hotspots: sorted by composite descending
    hotspots = sorted(profiles, key=lambda p: p.composite_score, reverse=True)

    total_consumers = sum(p.consumer_count for p in profiles)

    return AggregateRisk(
        profiles=profiles,
        structural=agg_dims["structural"],
        instability=agg_dims["instability"],
        cycle=agg_dims["cycle"],
        database=agg_dims["database"],
        blast_radius=agg_dims["blast_radius"],
        domain_boundary=agg_dims["domain_boundary"],
        change_surface=agg_dims["change_surface"],
        composite_score=round(composite, 3),
        risk_level=risk_level,
        risk_factors=all_factors,
        targets_at_red=red,
        targets_at_yellow=yellow,
        targets_at_green=green,
        total_consumers=total_consumers,
        total_transitive=total_transitive,
        hotspots=hotspots,
    )


def format_risk_factors(
    profile_or_aggregate: Union[RiskProfile, AggregateRisk],
    top_n: int = 5,
) -> List[str]:
    """Extract and sort human-readable risk factors."""
    return profile_or_aggregate.risk_factors[:top_n]


# --- Internal helpers ---


def _compute_composite(
    dimensions: List[RiskDimension],
    context: RiskContext,
) -> float:
    """Weighted maximum across dimensions.

    composite = max(weight_i * score_i) for all dimensions.
    Only considers dimensions with data_available=True.
    """
    weighted = []
    for d in dimensions:
        if not d.data_available:
            continue
        weight = context.dimension_weights.get(d.name, 0.0)
        weighted.append(weight * d.score)

    if not weighted:
        return 0.0
    return max(weighted)


def _collect_factors(
    dimensions: List[RiskDimension],
    context: RiskContext,
    top_n: int = 5,
) -> List[str]:
    """Collect factors from all dimensions, deduplicate, sort by weight * score."""
    scored_factors: List[tuple] = []
    seen: Set[str] = set()

    for d in dimensions:
        if not d.data_available:
            continue
        weight = context.dimension_weights.get(d.name, 0.0)
        for factor in d.factors:
            if factor not in seen:
                seen.add(factor)
                scored_factors.append((weight * d.score, factor))

    scored_factors.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored_factors[:top_n]]
