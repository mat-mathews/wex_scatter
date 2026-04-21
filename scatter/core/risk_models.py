"""Risk analysis data models for Scatter.

All risk types live here — separate from models.py.
The risk vocabulary is self-contained: RiskDimension → RiskProfile →
AggregateRisk. No imports from scatter.core.models or any external package.

Stdlib-only imports so that importing this module can never break existing
code that imports from models.py.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# --- Constants ---

# DIMENSION SYNC: When adding a new dimension, update ALL of these locations:
#   1. VALID_DIMENSION_NAMES (below)
#   2. RiskProfile fields (named field + dimensions property)
#   3. AggregateRisk fields (named field + dimension aggregation in aggregate_risk)
#   4. aggregate_risk() dim_names list in risk_engine.py
#   5. compute_risk_profile() dimension scoring + dimensions list in risk_engine.py
#   6. Logging format string in compute_risk_profile() (risk_engine.py)
VALID_DIMENSION_NAMES = frozenset(
    {
        "structural",
        "instability",
        "cycle",
        "database",
        "blast_radius",
        "domain_boundary",
        "change_surface",
    }
)


# --- Enums ---


class RiskLevel(Enum):
    """Traffic-light risk classification."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


# --- Core dataclasses ---


@dataclass
class RiskDimension:
    """A single axis of risk measurement.

    When data_available is False, the score is 0.0 by default — not because
    the target is safe, but because we have no data. Reporters must render
    this differently from a true 0.0.
    """

    name: str  # machine-readable identifier
    label: str  # human-readable label
    score: float  # 0.0 (safe) to 1.0 (dangerous)
    severity: str  # "low", "medium", "high", "critical"
    factors: List[str]  # human-readable explanations
    raw_metrics: dict  # underlying numbers for transparency
    data_available: bool = True  # False when metrics were missing

    @classmethod
    def zero(cls, name: str, label: str) -> "RiskDimension":
        """Create a zeroed-out dimension (safe default)."""
        return cls(
            name=name,
            label=label,
            score=0.0,
            severity="low",
            factors=[],
            raw_metrics={},
            data_available=True,
        )


@dataclass
class RiskContext:
    """Weighting profile for a specific risk analysis context.

    Validates at construction time — fail fast
    with specific error messages, not at scoring time.

    Partial dimension_weights: dimensions not listed default to weight 0.0,
    meaning they are excluded from the weighted-max composite. This is
    intentional — a context can focus on a subset of dimensions. A warning
    is logged when a built-in dimension is missing from a custom context
    so misconfiguration is visible.
    """

    name: str
    dimension_weights: dict  # str → float
    red_threshold: float
    yellow_threshold: float
    description: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("RiskContext.name must be non-empty")
        if self.yellow_threshold >= self.red_threshold:
            raise ValueError(
                f"yellow_threshold ({self.yellow_threshold}) must be < "
                f"red_threshold ({self.red_threshold})"
            )
        for dim, weight in self.dimension_weights.items():
            if dim not in VALID_DIMENSION_NAMES:
                raise ValueError(
                    f"Unknown dimension '{dim}' in weights — valid: {sorted(VALID_DIMENSION_NAMES)}"
                )
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"Dimension weight '{dim}' is {weight}, must be in [0.0, 1.0]")
        missing = VALID_DIMENSION_NAMES - set(self.dimension_weights.keys())
        if missing:
            logger.warning(
                "RiskContext '%s' is missing weights for dimensions %s — "
                "these will default to 0.0 (excluded from composite)",
                self.name,
                sorted(missing),
            )


@dataclass
class RiskProfile:
    """Multi-dimensional risk assessment for a single target."""

    # Identity
    target_name: str
    target_type: str  # "class", "interface", "project", "sproc"
    target_path: Optional[Path] = None

    # Dimensions (always present — graph-derived, no AI needed)
    structural: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("structural", "Structural coupling")
    )
    instability: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("instability", "Instability")
    )
    cycle: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("cycle", "Cycle entanglement")
    )
    database: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("database", "Database coupling")
    )
    blast_radius: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("blast_radius", "Blast radius")
    )
    domain_boundary: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("domain_boundary", "Domain boundary")
    )
    change_surface: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("change_surface", "Change surface")
    )

    # Aggregate
    composite_score: float = 0.0  # 0.0–1.0, weighted combination
    risk_level: RiskLevel = RiskLevel.GREEN
    risk_factors: List[str] = field(default_factory=list)

    # AI enrichment (optional — None if AI unavailable)
    risk_narrative: Optional[str] = None
    mitigation_suggestions: Optional[List[str]] = None
    coupling_vectors: Optional[List[str]] = None

    # Context
    consumer_count: int = 0
    transitive_consumer_count: int = 0
    consumers_in_cycles: int = 0
    consumers_cross_domain: int = 0
    shared_sprocs: List[str] = field(default_factory=list)

    @property
    def dimensions(self) -> List[RiskDimension]:
        """All dimensions as a list, for iteration."""
        return [
            self.structural,
            self.instability,
            self.cycle,
            self.database,
            self.blast_radius,
            self.domain_boundary,
            self.change_surface,
        ]

    @property
    def critical_dimensions(self) -> List[RiskDimension]:
        """Dimensions scoring 'high' or 'critical'."""
        return [d for d in self.dimensions if d.severity in ("high", "critical")]


@dataclass
class AggregateRisk:
    """Risk summary across multiple targets (PR, SOW, or any multi-target analysis)."""

    # Per-target profiles
    profiles: List[RiskProfile]

    # Aggregate dimensions (max across all targets per dimension)
    structural: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("structural", "Structural coupling")
    )
    instability: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("instability", "Instability")
    )
    cycle: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("cycle", "Cycle entanglement")
    )
    database: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("database", "Database coupling")
    )
    blast_radius: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("blast_radius", "Blast radius")
    )
    domain_boundary: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("domain_boundary", "Domain boundary")
    )
    change_surface: RiskDimension = field(
        default_factory=lambda: RiskDimension.zero("change_surface", "Change surface")
    )

    # Aggregate score and level
    composite_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.GREEN
    risk_factors: List[str] = field(default_factory=list)

    # Summary stats
    targets_at_red: int = 0
    targets_at_yellow: int = 0
    targets_at_green: int = 0
    total_consumers: int = 0  # sum across profiles, NOT deduplicated
    total_transitive: int = 0  # sum across profiles, NOT deduplicated

    # Hotspots — targets driving the risk
    hotspots: List[RiskProfile] = field(default_factory=list)

    @property
    def dimensions(self) -> List[RiskDimension]:
        """All dimensions as a list, for iteration."""
        return [
            self.structural,
            self.instability,
            self.cycle,
            self.database,
            self.blast_radius,
            self.domain_boundary,
            self.change_surface,
        ]


# --- Built-in contexts ---

PR_RISK_CONTEXT = RiskContext(
    name="pr",
    dimension_weights={
        "cycle": 1.0,
        "change_surface": 0.9,
        "database": 0.8,
        "structural": 0.7,
        "blast_radius": 0.7,
        "instability": 0.6,
        "domain_boundary": 0.5,
    },
    red_threshold=0.7,
    yellow_threshold=0.4,
    description="Will this merge break things?",
)

SOW_RISK_CONTEXT = RiskContext(
    name="sow",
    dimension_weights={
        "database": 1.0,
        "domain_boundary": 0.9,
        "cycle": 0.8,
        "blast_radius": 0.8,
        "structural": 0.6,
        "instability": 0.5,
        "change_surface": 0.4,
    },
    red_threshold=0.7,
    yellow_threshold=0.4,
    description="How risky is this body of work?",
)

LOCAL_DEV_CONTEXT = RiskContext(
    name="local",
    dimension_weights={
        "cycle": 1.0,
        "change_surface": 0.9,
        "blast_radius": 0.7,
        "structural": 0.7,
        "database": 0.6,
        "instability": 0.6,
        "domain_boundary": 0.3,
    },
    red_threshold=0.7,
    yellow_threshold=0.4,
    description="Should I be worried about this change?",
)


# --- Helpers ---


def score_to_severity(score: float) -> str:
    """Map a 0.0–1.0 score to a severity label."""
    if score >= 0.8:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def composite_to_risk_level(
    score: float,
    context: RiskContext,
) -> RiskLevel:
    """Map composite score to RED/YELLOW/GREEN using context thresholds."""
    if score >= context.red_threshold:
        return RiskLevel.RED
    if score >= context.yellow_threshold:
        return RiskLevel.YELLOW
    return RiskLevel.GREEN
