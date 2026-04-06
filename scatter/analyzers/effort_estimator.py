"""Effort estimation heuristics for SOW scoping.

Pure functions. Core heuristic logic (Decision #3, #5, #7, #11).
All multipliers return 1.0 in Phase 1 (Decision #7).
"""

from typing import TYPE_CHECKING, Dict, List, Optional, Set

from scatter.core.scoping_models import (
    CONFIDENCE_BAND_PCT,
    ConfidenceBand,
    ConfidenceLevel,
    DatabaseImpact,
    EffortBreakdown,
    EffortCategory,
    collect_involved_names,
)

if TYPE_CHECKING:
    from scatter.analyzers.domain_analyzer import Cluster
    from scatter.analyzers.graph_enrichment import GraphContext
    from scatter.core.models import ImpactReport


def compute_confidence_band(
    composite_score: float,
    ambiguity_level: str,
) -> ConfidenceBand:
    """Derive confidence band from risk composite and ambiguity.

    - composite < 0.3 -> HIGH (+-20%)
    - composite < 0.6 -> MODERATE (+-30%)
    - composite >= 0.6 -> LOW (+-50%)
    - ambiguity == "vague" -> widen one step
    """
    if composite_score < 0.3:
        level = ConfidenceLevel.HIGH
    elif composite_score < 0.6:
        level = ConfidenceLevel.MODERATE
    else:
        level = ConfidenceLevel.LOW

    was_widened = False
    if ambiguity_level == "vague":
        if level == ConfidenceLevel.HIGH:
            level = ConfidenceLevel.MODERATE
            was_widened = True
        elif level == ConfidenceLevel.MODERATE:
            level = ConfidenceLevel.LOW
            was_widened = True

    return ConfidenceBand(
        level=level,
        band_pct=CONFIDENCE_BAND_PCT[level],
        composite_score=composite_score,
        ambiguity_level=ambiguity_level,
        was_widened=was_widened,
    )


def estimate_effort(
    report: "ImpactReport",
    graph_ctx: Optional["GraphContext"],
    db_impact: DatabaseImpact,
    confidence: ConfidenceBand,
    clusters: Optional[List["Cluster"]] = None,
    multipliers: Optional[Dict[str, float]] = None,
) -> EffortBreakdown:
    """Compute effort breakdown from impact report and graph context.

    All multipliers default to 1.0 in Phase 1 (Decision #7).
    """
    if multipliers is None:
        multipliers = {}

    band_pct = confidence.band_pct

    # Collect counts from report
    target_count = len(report.targets) if report.targets else 0
    direct_count = sum(ti.total_direct for ti in (report.targets or []))
    depth1_count = sum(
        sum(1 for c in ti.consumers if c.depth == 1) for ti in (report.targets or [])
    )
    depth2_count = sum(
        sum(1 for c in ti.consumers if c.depth >= 2) for ti in (report.targets or [])
    )

    # Graph-dependent data
    has_cycles = False
    fan_in_gt5 = False
    cross_domain = False
    extra_clusters = 0

    if graph_ctx is not None:
        has_cycles = _any_involved_in_cycles(report, graph_ctx)
        fan_in_gt5 = _any_fan_in_above(report, graph_ctx, threshold=5)

    if clusters is not None:
        involved = collect_involved_names(report)
        extra_clusters = _count_distinct_clusters(involved, clusters)
        cross_domain = extra_clusters > 1

    # Shared sproc count
    shared_sproc_count = db_impact.total_shared_sprocs
    high_sharing_sprocs = sum(1 for sg in db_impact.shared_sprocs if sg.project_count > 3)

    # --- Category calculations ---
    categories: List[EffortCategory] = []

    # 1. Investigation
    inv_base = _compute_investigation(target_count, extra_clusters, has_cycles)
    categories.append(
        _make_category(
            "investigation",
            inv_base,
            multipliers.get("investigation", 1.0),
            band_pct,
            _investigation_factors(target_count, extra_clusters, has_cycles),
        )
    )

    # 2. Implementation (sublinear past 5 — Marcus #11)
    impl_base = _compute_implementation(direct_count, depth1_count, depth2_count)
    categories.append(
        _make_category(
            "implementation",
            impl_base,
            multipliers.get("implementation", 1.0),
            band_pct,
            _implementation_factors(direct_count, depth1_count, depth2_count, extra_clusters),
        )
    )

    # 3. Testing
    test_base = _compute_testing(direct_count, shared_sproc_count, cross_domain)
    categories.append(
        _make_category(
            "testing",
            test_base,
            multipliers.get("testing", 1.0),
            band_pct,
            _testing_factors(direct_count, shared_sproc_count, cross_domain),
        )
    )

    # 4. Integration risk
    int_base = _compute_integration_risk(has_cycles, shared_sproc_count, extra_clusters, fan_in_gt5)
    categories.append(
        _make_category(
            "integration_risk",
            int_base,
            multipliers.get("integration_risk", 1.0),
            band_pct,
            _integration_risk_factors(has_cycles, shared_sproc_count, extra_clusters, fan_in_gt5),
        )
    )

    # 5. Database migration
    db_base = _compute_db_migration(shared_sproc_count, high_sharing_sprocs)
    categories.append(
        _make_category(
            "database_migration",
            db_base,
            multipliers.get("database_migration", 1.0),
            band_pct,
            _db_migration_factors(shared_sproc_count, high_sharing_sprocs),
        )
    )

    total_base = sum(c.base_days for c in categories)
    total_min = sum(c.min_days for c in categories)
    total_max = sum(c.max_days for c in categories)

    return EffortBreakdown(
        categories=categories,
        total_base_days=total_base,
        total_min_days=total_min,
        total_max_days=total_max,
    )


# ---------------------------------------------------------------------------
# Category formulas
# ---------------------------------------------------------------------------


def _compute_investigation(target_count: int, extra_clusters: int, has_cycles: bool) -> float:
    """0.5/target + 0.5/extra cluster + 1.0 if cycles; clamp [1.0, 3.0]."""
    raw = 0.5 * target_count + 0.5 * max(0, extra_clusters - 1) + (1.0 if has_cycles else 0.0)
    return max(1.0, min(3.0, raw))


def _compute_implementation(direct: int, depth1: int, depth2: int) -> float:
    """Sublinear past 5 direct consumers (Marcus #11)."""
    direct_days = min(direct, 5) * 1.0 + max(0, direct - 5) * 0.3
    return direct_days + depth1 * 0.5 + depth2 * 0.25


def _compute_testing(direct: int, shared_sprocs: int, cross_domain: bool) -> float:
    """0.5/direct + 1.0/shared sproc + 0.5 if cross-domain."""
    return 0.5 * direct + 1.0 * shared_sprocs + (0.5 if cross_domain else 0.0)


def _compute_integration_risk(
    has_cycles: bool, shared_sprocs: int, extra_clusters: int, fan_in_gt5: bool
) -> float:
    """1.0/cycle + 0.5/shared sproc + 1.0/extra cluster + 0.5 if fan-in>5. 0 if none apply."""
    total = 0.0
    if has_cycles:
        total += 1.0
    total += 0.5 * shared_sprocs
    total += 1.0 * max(0, extra_clusters - 1)
    if fan_in_gt5:
        total += 0.5
    return total


def _compute_db_migration(shared_sprocs: int, high_sharing_sprocs: int) -> float:
    """1.0/sproc + 2.0/sproc with >3 consumers. 0 if no shared sprocs."""
    return 1.0 * shared_sprocs + 2.0 * high_sharing_sprocs


# ---------------------------------------------------------------------------
# Factor descriptions
# ---------------------------------------------------------------------------


def _investigation_factors(target_count: int, extra_clusters: int, has_cycles: bool) -> List[str]:
    factors = [f"{target_count} target(s)"]
    if extra_clusters > 1:
        factors.append(f"{extra_clusters} clusters")
    if has_cycles:
        factors.append("cycle detected")
    if not has_cycles and extra_clusters <= 1:
        factors.append("no cycles")
    return factors


def _implementation_factors(
    direct: int, depth1: int, depth2: int, cluster_count: int = 0
) -> List[str]:
    factors = [f"{direct} direct"]
    if depth1:
        factors.append(f"{depth1} depth-1")
    if depth2:
        factors.append(f"{depth2} depth-2")
    if direct > 5:
        factors.append("sublinear past 5")
    if cluster_count > 1:
        factors.append(f"spans {cluster_count} clusters")
    return factors


def _testing_factors(direct: int, shared_sprocs: int, cross_domain: bool) -> List[str]:
    factors = [f"{direct} direct consumer(s)"]
    if shared_sprocs:
        factors.append(f"{shared_sprocs} shared sproc(s)")
    if cross_domain:
        factors.append("cross-domain")
    return factors


def _integration_risk_factors(
    has_cycles: bool, shared_sprocs: int, extra_clusters: int, fan_in_gt5: bool
) -> List[str]:
    factors: List[str] = []
    if has_cycles:
        factors.append("cycle")
    if shared_sprocs:
        factors.append(f"{shared_sprocs} shared sproc(s)")
    if extra_clusters > 1:
        factors.append(f"{extra_clusters} clusters")
    if fan_in_gt5:
        factors.append("high fan-in (>5)")
    if not factors:
        factors.append("none")
    return factors


def _db_migration_factors(shared_sprocs: int, high_sharing: int) -> List[str]:
    if shared_sprocs == 0:
        return ["no shared sprocs"]
    factors = [f"{shared_sprocs} shared sproc(s)"]
    if high_sharing:
        factors.append(f"{high_sharing} with >3 consumers")
    return factors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_category(
    name: str, base: float, multiplier: float, band_pct: float, factors: List[str]
) -> EffortCategory:
    """Build an EffortCategory with band applied."""
    adjusted = base * multiplier
    return EffortCategory(
        name=name,
        base_days=round(adjusted, 2),
        multiplier=multiplier,
        min_days=round(adjusted * (1 - band_pct), 2),
        max_days=round(adjusted * (1 + band_pct), 2),
        factors=factors,
    )


def _any_involved_in_cycles(report: "ImpactReport", graph_ctx: "GraphContext") -> bool:
    """Check if any involved project is in a cycle. O(1) per name via cycle_members."""
    involved = collect_involved_names(report)
    return bool(involved & graph_ctx.cycle_members)


def _any_fan_in_above(report: "ImpactReport", graph_ctx: "GraphContext", threshold: int) -> bool:
    """Check if any involved project has fan-in above threshold."""
    involved = collect_involved_names(report)
    for name in involved:
        m = graph_ctx.metrics.get(name)
        if m and m.fan_in > threshold:
            return True
    return False


def _count_distinct_clusters(involved: Set[str], clusters: List["Cluster"]) -> int:
    """Count distinct clusters that contain any involved project."""
    count = 0
    for cluster in clusters:
        if set(cluster.projects) & involved:
            count += 1
    return count
