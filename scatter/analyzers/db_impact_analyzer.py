"""Database impact assessment for SOW scoping.

Pure functions. Extracts shared sproc info from graph (Decision #4).
"""

from collections import defaultdict
from typing import TYPE_CHECKING, List, Optional, Set

from scatter.core.scoping_models import DatabaseImpact, SharedSprocGroup, collect_involved_names

if TYPE_CHECKING:
    from scatter.analyzers.graph_enrichment import GraphContext
    from scatter.core.models import ImpactReport


def assess_database_impact(
    report: "ImpactReport", graph_ctx: Optional["GraphContext"]
) -> DatabaseImpact:
    """Assess database migration impact from shared stored procedures.

    1. Collect project names from report (all targets + all consumers)
    2. Find sprocs shared across multiple projects where at least one is involved
    3. Classify migration complexity
    """
    if graph_ctx is None:
        return DatabaseImpact(migration_factors=["No graph available — database impact unknown"])

    involved = collect_involved_names(report)
    shared = _find_shared_sprocs(involved, graph_ctx)

    if not shared:
        return DatabaseImpact(migration_factors=[])

    complexity = _classify_migration_complexity(shared)

    factors: List[str] = []
    for sg in shared:
        factors.append(f"{sg.sproc_name} shared by {sg.project_count} project(s)")
    if complexity in ("moderate", "high"):
        factors.append(f"Migration complexity: {complexity}")

    # Estimate migration days: 1.0/sproc + 2.0/sproc with >3 consumers
    migration_days = 0.0
    for sg in shared:
        migration_days += 1.0
        if sg.project_count > 3:
            migration_days += 2.0

    return DatabaseImpact(
        shared_sprocs=shared,
        total_shared_sprocs=len(shared),
        migration_complexity=complexity,
        migration_factors=factors,
        estimated_migration_days=migration_days,
    )


def _find_shared_sprocs(
    involved_names: Set[str], graph_ctx: "GraphContext"
) -> List[SharedSprocGroup]:
    """Find sprocs shared by multiple projects where at least one is in our set."""
    sproc_to_projects: dict[str, set[str]] = defaultdict(set)
    for node in graph_ctx.graph.get_all_nodes():
        for sproc in node.sproc_references:
            sproc_to_projects[sproc].add(node.name)

    groups: List[SharedSprocGroup] = []
    for sproc, projects in sorted(sproc_to_projects.items()):
        if len(projects) > 1 and projects & involved_names:
            groups.append(
                SharedSprocGroup(
                    sproc_name=sproc,
                    projects=sorted(projects),
                    project_count=len(projects),
                )
            )
    return groups


def _classify_migration_complexity(sprocs: List[SharedSprocGroup]) -> str:
    """Classify migration complexity based on shared sproc sharing breadth."""
    if not sprocs:
        return "none"
    max_sharing = max(sg.project_count for sg in sprocs)
    if max_sharing > 3:
        return "high"
    if max_sharing >= 3:
        return "moderate"
    return "low"
