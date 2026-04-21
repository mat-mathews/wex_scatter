"""Data models for SOW scoping effort estimation.

Dataclasses only — no business logic. Parallel to risk_models.py (Decision #9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, List, Optional, Set

if TYPE_CHECKING:
    from scatter.core.models import ImpactReport
    from scatter.core.risk_models import AggregateRisk


class ConfidenceLevel(Enum):
    """Confidence in the effort estimate."""

    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


CONFIDENCE_BAND_PCT = {
    ConfidenceLevel.HIGH: 0.20,
    ConfidenceLevel.MODERATE: 0.30,
    ConfidenceLevel.LOW: 0.50,
}


@dataclass
class EffortCategory:
    """One row of the effort breakdown table."""

    name: str  # "investigation", "implementation", "testing", "integration_risk", "database_migration"
    base_days: float  # graph-derived before multiplier
    multiplier: float  # always 1.0 in Phase 1
    min_days: float  # base * multiplier * (1 - band_pct)
    max_days: float  # base * multiplier * (1 + band_pct)
    factors: List[str] = field(default_factory=list)  # human-readable explanations


@dataclass
class EffortBreakdown:
    """Complete effort estimate across all categories."""

    categories: List[EffortCategory] = field(default_factory=list)
    total_base_days: float = 0.0
    total_min_days: float = 0.0
    total_max_days: float = 0.0


@dataclass
class ConfidenceBand:
    """How confident we are in the estimate — drives the +-% band."""

    level: ConfidenceLevel = ConfidenceLevel.MODERATE
    band_pct: float = 0.30
    composite_score: float = 0.0
    ambiguity_level: str = "moderate"
    was_widened: bool = False


@dataclass
class SharedSprocGroup:
    """A stored procedure shared across multiple projects."""

    sproc_name: str
    projects: List[str] = field(default_factory=list)
    project_count: int = 0


@dataclass
class DatabaseImpact:
    """Database dependency assessment for scoping."""

    shared_sprocs: List[SharedSprocGroup] = field(default_factory=list)
    total_shared_sprocs: int = 0
    migration_complexity: str = "none"  # none/low/moderate/high
    migration_factors: List[str] = field(default_factory=list)
    estimated_migration_days: float = 0.0


@dataclass
class ScopingReport:
    """Top-level scoping report. Wraps ImpactReport (composition, Decision #1)."""

    impact_report: "ImpactReport"
    effort: EffortBreakdown = field(default_factory=EffortBreakdown)
    confidence: ConfidenceBand = field(default_factory=ConfidenceBand)
    database_impact: DatabaseImpact = field(default_factory=DatabaseImpact)
    aggregate_risk: Optional["AggregateRisk"] = None
    ai_effort_adjustment: Optional[str] = None  # AI narrative
    ai_effort_min_days: Optional[float] = None
    ai_effort_max_days: Optional[float] = None
    warnings: List[str] = field(default_factory=list)  # degradation visibility
    comparable_sows: List[Any] = field(default_factory=list)  # Phase 3: List[ComparableSOW]
    teams_to_consult: List[Any] = field(default_factory=list)  # Phase 2: List[TeamConsultation]
    duration_ms: int = 0


def collect_involved_names(report: "ImpactReport") -> Set[str]:
    """Collect all project names involved in an impact report (targets + consumers).

    Shared helper used by db_impact_analyzer and effort_estimator.
    """
    names: Set[str] = set()
    for ti in report.targets:
        names.add(ti.target.name)
        for c in ti.consumers:
            names.add(c.consumer_name)
    return names
