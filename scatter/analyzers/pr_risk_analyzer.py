"""PR risk analyzer — composes change extraction with risk scoring.

Orchestrates: extract changed types → score per project → aggregate.

Known limitation: _diff_type_sets marks all shared types as "modified" even if
only the file was touched (whitespace/comment change). This can inflate
change_surface scores. A future improvement could compare type bodies.
"""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from scatter.analyzers.git_analyzer import extract_pr_changed_types
from scatter.analyzers.risk_dimensions import score_change_surface
from scatter.analyzers.risk_engine import (
    aggregate_risk,
    compute_risk_profile,
    recompute_profile_composite,
)
from scatter.core.models import ChangedType, PRRiskReport
from scatter.core.risk_models import (
    AggregateRisk,
    PR_RISK_CONTEXT,
    RiskProfile,
)

if TYPE_CHECKING:
    from scatter.analyzers.graph_enrichment import GraphContext

logger = logging.getLogger(__name__)


def analyze_pr_risk(
    repo_path: Path,
    branch_name: str,
    base_branch: str,
    graph_ctx: Optional["GraphContext"] = None,
) -> PRRiskReport:
    """Analyze PR risk by extracting changed types and scoring them.

    Steps:
    1. Extract changed types from git diff
    2. Group by owning project
    3. Per project: compute risk profile + change_surface
    4. Aggregate across projects
    5. Assemble PRRiskReport
    """
    start = time.monotonic()
    warnings: List[str] = []
    graph_available = graph_ctx is not None

    # Step 1: Extract changed types
    changed_types = extract_pr_changed_types(str(repo_path), branch_name, base_branch)

    # Step 2: Empty diff → GREEN
    if not changed_types:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return PRRiskReport(
            branch_name=branch_name,
            base_branch=base_branch,
            changed_types=[],
            aggregate=AggregateRisk(profiles=[]),
            profiles=[],
            graph_available=graph_available,
            duration_ms=elapsed_ms,
        )

    # Step 3: Group by owning project
    by_project: Dict[str, List[ChangedType]] = {}
    for ct in changed_types:
        by_project.setdefault(ct.owning_project, []).append(ct)

    # Step 4: Per-project scoring
    profiles: List[RiskProfile] = []
    all_consumer_names: Set[str] = set()
    total_direct = 0
    total_transitive = 0

    for proj_name, proj_types in by_project.items():
        if graph_ctx:
            # Use graph for consumer lookup and full risk profile
            graph = graph_ctx.graph
            consumer_names = list(graph.get_consumer_names(proj_name))
            direct_count = len(consumer_names)

            # Compute transitive consumers (depth 2)
            # TODO: honor --max-depth when wired into CLI
            transitive_names: Set[str] = set()
            for cn in consumer_names:
                transitive_names.update(graph.get_consumer_names(cn))
            transitive_names -= set(consumer_names)
            transitive_names.discard(proj_name)
            transitive_count = len(transitive_names)

            all_consumer_names.update(consumer_names)
            all_consumer_names.update(transitive_names)

            # Get cluster IDs for domain boundary scoring
            consumer_cluster_ids = []
            target_cluster_id = None
            node = graph.get_node(proj_name)
            if node:
                target_cluster_id = getattr(node, "cluster_id", None)
            for cn in consumer_names:
                cn_node = graph.get_node(cn)
                if cn_node:
                    cid = getattr(cn_node, "cluster_id", None)
                    if cid:
                        consumer_cluster_ids.append(cid)

            profile = compute_risk_profile(
                target=proj_name,
                graph=graph,
                metrics=graph_ctx.metrics,
                consumers=consumer_names,
                cycles=graph_ctx.cycles,
                context=PR_RISK_CONTEXT,
                direct_consumer_count=direct_count,
                transitive_consumer_count=transitive_count,
                consumer_cluster_ids=consumer_cluster_ids,
                target_cluster_id=target_cluster_id,
            )

            total_direct += direct_count
            total_transitive += transitive_count
        else:
            # No graph — create minimal profile with only change_surface
            profile = RiskProfile(
                target_name=proj_name,
                target_type="project",
            )
            if not warnings:
                warnings.append(
                    "Run with --search-scope to enable full graph-derived risk analysis."
                )

        # Score change_surface and inject into profile, then recompute composite
        profile.change_surface = score_change_surface(changed_types, proj_name)
        recompute_profile_composite(profile, PR_RISK_CONTEXT)

        profiles.append(profile)

    # Step 5: Aggregate
    agg = aggregate_risk(profiles, PR_RISK_CONTEXT)

    elapsed_ms = int((time.monotonic() - start) * 1000)

    report = PRRiskReport(
        branch_name=branch_name,
        base_branch=base_branch,
        changed_types=changed_types,
        aggregate=agg,
        profiles=profiles,
        total_direct_consumers=total_direct,
        total_transitive_consumers=total_transitive,
        unique_consumers=sorted(all_consumer_names),
        graph_available=graph_available,
        warnings=warnings,
        duration_ms=elapsed_ms,
    )

    logger.info(
        "pr_risk branch=%s level=%s composite=%.3f types=%d projects=%d consumers=%d elapsed_ms=%d",
        branch_name,
        report.risk_level.value,
        agg.composite_score,
        len(changed_types),
        len(profiles),
        len(all_consumer_names),
        elapsed_ms,
    )

    return report
