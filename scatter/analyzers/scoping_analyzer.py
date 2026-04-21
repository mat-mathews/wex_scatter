"""Scoping analysis orchestrator — composes on top of ImpactReport.

Produces a ScopingReport with effort breakdowns, confidence bands,
and database impact assessment (Decision #1, #8).
"""

import logging
import time
from typing import TYPE_CHECKING, Optional

from scatter.analyzers.db_impact_analyzer import assess_database_impact
from scatter.analyzers.effort_estimator import compute_confidence_band, estimate_effort
from scatter.core.scoping_models import ScopingReport

if TYPE_CHECKING:
    from scatter.analyzers.graph_enrichment import GraphContext
    from scatter.core.models import ImpactReport


def run_scoping_analysis(
    impact_report: "ImpactReport",
    graph_ctx: Optional["GraphContext"],
    ai_provider=None,
) -> ScopingReport:
    """Run scoping analysis on an already-computed ImpactReport.

    Pipeline:
    1. Read AggregateRisk from impact_report (Decision #10 — no recompute)
    2. Call find_clusters() once if graph available
    3. Assess database impact
    4. Compute confidence band
    5. Estimate effort
    6. Assemble ScopingReport with warnings
    7. Optional AI effort adjustment
    """
    start = time.monotonic()
    warnings = []

    # 1. Read stored risk data (Decision #10)
    agg = impact_report.aggregate_risk
    composite_score = agg.composite_score if agg else 0.0

    # 2. Domain clusters — called once, passed to effort estimator
    clusters = None
    if graph_ctx is not None:
        try:
            from scatter.analyzers.domain_analyzer import find_clusters

            clusters = find_clusters(
                graph_ctx.graph,
                metrics=graph_ctx.metrics,
                cycles=graph_ctx.cycles,
            )
        except Exception:
            logging.warning(
                "find_clusters() failed, continuing without cluster data", exc_info=True
            )
            warnings.append(
                "Cluster analysis failed — investigation and integration risk estimates may be understated"
            )
    else:
        warnings.append("No dependency graph available — effort estimate uses reduced heuristics")

    # 3. Database impact
    db_impact = assess_database_impact(impact_report, graph_ctx)

    # 4. Confidence band
    ambiguity = impact_report.ambiguity_level or "moderate"
    confidence = compute_confidence_band(composite_score, ambiguity)

    # 5. Effort estimation
    effort = estimate_effort(
        report=impact_report,
        graph_ctx=graph_ctx,
        db_impact=db_impact,
        confidence=confidence,
        clusters=clusters,
    )

    # 6. Assemble report
    report = ScopingReport(
        impact_report=impact_report,
        effort=effort,
        confidence=confidence,
        database_impact=db_impact,
        aggregate_risk=agg,
        warnings=warnings,
    )

    # 7. Optional AI adjustment (Decision #5 — labeled overlay)
    if ai_provider is not None:
        try:
            from scatter.ai.tasks.effort_adjustment import adjust_effort

            ai_result = adjust_effort(impact_report, effort, confidence, db_impact, ai_provider)
            if ai_result:
                report.ai_effort_adjustment = ai_result.get("adjustment_narrative")
                report.ai_effort_min_days = ai_result.get("min_days")
                report.ai_effort_max_days = ai_result.get("max_days")
        except Exception:
            logging.warning("AI effort adjustment failed", exc_info=True)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    report.duration_ms = elapsed_ms
    logging.info(f"Scoping analysis completed in {elapsed_ms}ms")

    return report
