# SOW Scoping — Estimates That Finance Trusts

**Initiative**: SOW Scoping with Calibration
**Target branch**: `feature/sow-scoping`
**Effort estimate**: 6–8 weeks across 4 phases
**Dependencies**: Risk Engine (`RISK_ENGINE_PLAN.md`), impact analysis mode (done), graph engine (done), AI provider system (done)
**Blockers**: Access to historical SOW data for calibration; team-hours tracking system
**Related docs**: `RISK_ENGINE_PLAN.md` (unified risk model), `PR_RISK_SCORING_PLAN.md` (shared infrastructure)
**Team reviewers**: Priya (architecture), Marcus (metrics/observability), Fatima (failure modes), Devon (algorithms)

---

## The Problem

Every SOW that comes through the door starts the same way: someone reads a Word document,
opens a spreadsheet, and guesses. "This feels like a 3-sprint effort." Then it takes 7
sprints, and nobody's surprised because the original estimate was vibes.

The investigation phase alone — figuring out *what's actually affected* before you can
estimate *how long it takes* — burns 1–2 weeks of senior engineer time per SOW. For a team
like Athena handling multiple SOWs per quarter, that's a month of capacity spent on
archaeology instead of engineering.

Scatter already answers the archaeology question. The `--sow` mode takes a work request in
plain English, identifies affected targets, traces transitive consumers, and rates risk.
What it doesn't do is turn that analysis into a **scoping estimate that holds up against
actuals** — the kind of number you can put in front of finance and defend.

## The Opportunity

A SOW scoping pipeline that takes a work request and produces:

```
SOW: "Add tenant isolation to PortalDataService and related data access patterns"

SCOPE ASSESSMENT
  Affected targets: 3 (PortalDataService, TenantContext, IPortalRepository)
  Confidence: HIGH (all targets found in codebase index, avg 0.85)

  Direct consumers: 8 projects
  Transitive consumers: 14 projects (depth 2)
  Cross-domain impact: 2 domain clusters affected

  Shared database surface: 4 stored procedures
  Cycle involvement: yes (GalaxyWorks.Data ↔ GalaxyWorks.Api)

EFFORT ESTIMATE
  Investigation:     1–2 developer-days
  Implementation:    8–12 developer-days
  Testing:           4–6 developer-days
  Integration risk:  3–5 developer-days (cycle involvement, shared sprocs)
  ─────────────────────────────────────
  Total:             16–25 developer-days (3.2–5.0 developer-weeks)
  Confidence band:   ±30% (moderate — 2 domain clusters, cycle involvement)

  Comparable historical SOWs:
    - "Migrate session management to Redis" (actual: 22 dev-days, predicted: 18–26)
    - "Add audit logging to data access layer" (actual: 14 dev-days, predicted: 12–20)

RISK FACTORS
  - PortalDataService is in a dependency cycle — changes may require coordinated releases
  - 4 shared stored procedures need migration planning (database is the last monolith)
  - GalaxyWorks.BatchProcessor has instability 0.80 — fragile consumer, test carefully

TEAMS TO CONSULT
  - Platform team (owns GalaxyWorks.Api, GalaxyWorks.Core)
  - Batch Operations (owns GalaxyWorks.BatchProcessor)
  - Portal team (owns GalaxyWorks.WebPortal)
```

That output replaces 1–2 weeks of manual investigation. And because it's grounded in the
actual dependency graph — not someone's mental model of the codebase — it catches things
humans miss (the transitive consumer three hops away, the shared sproc nobody remembers).

---

## What Scatter Already Has

The SOW impact analysis mode (`--sow`) is the foundation. Here's what exists and what's
missing.

| Capability | Status | Module |
|-----------|--------|--------|
| Work request parsing (NL → targets) | Done | `ai/tasks/parse_work_request.py` |
| Codebase index for target validation | Done | `analyzers/impact_analyzer.py` |
| Consumer detection per target | Done | `analyzers/consumer_analyzer.py` |
| Transitive consumer tracing (BFS) | Done | `analyzers/impact_analyzer.py` |
| Risk assessment per target | Done | `ai/tasks/risk_assess.py` |
| Coupling narrative per consumer | Done | `ai/tasks/coupling_narrative.py` |
| Complexity rating (Low/Med/High/Crit) | Done | `ai/tasks/complexity_estimate.py` |
| Effort estimate (rough) | Done | `ai/tasks/complexity_estimate.py` |
| Impact narrative (exec summary) | Done | `ai/tasks/impact_narrative.py` |
| ImpactReport dataclass | Done | `core/models.py` |
| Coupling metrics + cycle detection | Done | `analyzers/coupling_analyzer.py` |
| Domain clustering | Done | `analyzers/domain_analyzer.py` |
| Graph cache + incremental patching | Done | `store/graph_cache.py` |

### What's Missing

| Gap | Difficulty | Why It Matters |
|-----|-----------|---------------|
| Structured effort breakdown (not just "3-5 dev-days") | Medium | Finance needs line items, not a single number |
| Confidence bands with justification | Medium | "±30% because cycle involvement" is defensible; "3-5 days" is a guess |
| Historical calibration (predicted vs actual) | Hard | The feature that builds trust over time |
| Comparable SOW retrieval | Hard | "Similar past work took X" is the strongest argument in a scoping meeting |
| Team/owner mapping for "who to consult" | Medium | Prevents the "we forgot to tell Platform team" failure mode |
| Database migration complexity scoring | Medium | Shared sprocs = database work = the thing estimates always miss |
| Structured output for spreadsheets | Low | Finance lives in Excel; JSON isn't enough |

---

## Architecture

### The Scoping Pipeline

```
SOW text (natural language)
  → AI: parse work request → List[AnalysisTarget] with confidence scores
  → Validate targets against codebase index
  → For each target:
      → Consumer detection (graph-accelerated)
      → Coupling metrics lookup
      → Cycle membership check
      → Domain cluster membership
      → Shared sproc enumeration
  → Aggregate into ScopingReport
  → AI: structured effort estimation (with graph context)
  → AI: risk narrative
  → Historical lookup: find comparable past SOWs
  → Format output (console, JSON, markdown, CSV)
```

### The ScopingReport

This extends `ImpactReport` with estimation-specific fields. It doesn't replace
`ImpactReport` — it wraps it.

```python
@dataclass
class EffortBreakdown:
    """Line-item effort estimate with justification."""
    category: str                    # "investigation", "implementation", "testing", etc.
    min_days: float
    max_days: float
    justification: str               # why this range
    risk_multiplier: float           # 1.0 = normal, 1.5 = cycle involvement, etc.
    contributing_factors: list[str]   # what drives the estimate

@dataclass
class ConfidenceBand:
    """How much to trust the estimate."""
    level: str                       # "high", "moderate", "low"
    percentage: int                  # ±N%
    factors: list[str]               # what affects confidence
    # e.g., ["2 targets not found in index", "cycle involvement adds uncertainty"]

@dataclass
class ComparableSOW:
    """A historical SOW with known actuals."""
    sow_id: str
    description: str
    predicted_days: tuple[float, float]   # (min, max)
    actual_days: float
    accuracy: float                       # predicted_mid / actual
    similarity_score: float               # how similar to current SOW
    similarity_factors: list[str]         # why it's comparable

@dataclass
class TeamConsultation:
    """A team that should be consulted based on consumer ownership."""
    team_name: str
    reason: str                      # "owns GalaxyWorks.Api (direct consumer)"
    consumer_count: int              # how many of their projects are affected
    consumers: list[str]             # which projects
    risk_level: str                  # highest risk among their consumers

@dataclass
class DatabaseImpact:
    """Database-specific scoping for shared stored procedures."""
    shared_sprocs: list[str]
    owning_projects: dict[str, list[str]]  # sproc → projects that call it
    migration_complexity: str              # "low", "medium", "high"
    migration_notes: str                   # AI-generated migration guidance
    requires_coordinated_release: bool     # true if sproc changes affect multiple teams

@dataclass
class ScopingReport:
    """Complete SOW scoping output — the artifact finance sees."""

    # Identity
    sow_text: str
    sow_id: Optional[str]            # for tracking against actuals
    timestamp: datetime
    scatter_version: str

    # Impact (from existing ImpactReport)
    impact: ImpactReport

    # Risk (from unified risk engine — see RISK_ENGINE_PLAN.md)
    risk_profiles: list[RiskProfile]       # per-target, 7-dimension profiles
    aggregate_risk: AggregateRisk          # aggregated across all targets
    risk_context: RiskContext              # SOW_RISK_CONTEXT (weights DB + domain highest)

    # Effort
    effort_breakdown: list[EffortBreakdown]
    total_min_days: float
    total_max_days: float
    confidence_band: ConfidenceBand

    # Context
    comparable_sows: list[ComparableSOW]
    teams_to_consult: list[TeamConsultation]
    database_impact: Optional[DatabaseImpact]

    # Graph context (derived from aggregate_risk, kept for backward compat)
    domain_clusters_affected: int
    cycle_involvement: bool
    max_coupling_score: float

    # Metadata
    graph_hit: bool
    ai_calls_made: int
    duration_ms: int
```

### Effort Estimation Logic

This is the core of the scoping feature. The estimate comes from three sources:

1. **Risk-driven multipliers** (from the unified risk engine — see `RISK_ENGINE_PLAN.md`)
2. **Graph-derived heuristics** (deterministic, reproducible)
3. **AI-assisted estimation** (contextual, uses coupling narratives)

The risk engine provides the multipliers. The graph heuristics provide the base costs.
The AI adjusts for context neither can see (business logic complexity, test coverage
patterns, team familiarity).

#### Risk-Driven Effort Multipliers

The unified risk engine computes a `RiskProfile` for each target and an `AggregateRisk`
across all targets. Each risk dimension directly influences a category of effort:

```python
def risk_driven_multiplier(aggregate: AggregateRisk) -> dict[str, float]:
    """
    Map risk dimensions to effort category multipliers.

    Each dimension contributes to the categories it most affects.
    Higher risk scores → higher multipliers → wider effort ranges.

    IMPORTANT: In Phase 1, all multipliers return 1.0 (no effect).
    Risk-driven multipliers only activate after calibration data exists
    (Phase 3). Until then, the base costs from graph heuristics ARE the
    estimate. Applying untested multipliers to untested base costs
    compounds two sources of error — you get garbage with confidence.

    Phase 3 activates these by replacing the 1.0 defaults with the
    formulas below, once we have enough actuals to validate them.
    """
    # Phase 1: all 1.0 — multipliers are inert until calibrated
    # Phase 3+: uncomment the formulas below
    return {
        "investigation": 1.0,       # + (aggregate.domain_boundary.score * 0.5)
                                    # + (aggregate.cycle.score * 0.5),
        "implementation": 1.0,      # + (aggregate.structural.score * 0.3)
                                    # + (aggregate.cycle.score * 0.5),
        "testing": 1.0,             # + (aggregate.database.score * 0.5)
                                    # + (aggregate.instability.score * 0.3),
        "integration_risk": 1.0,    # + (aggregate.cycle.score * 0.5)
                                    # + (aggregate.domain_boundary.score * 0.5)
                                    # + (aggregate.database.score * 0.3),
        "database_migration": 1.0,  # + (aggregate.database.score * 1.0),
    }
```

This replaces the earlier hard-coded multipliers ("1.5x if cycle") with multipliers
derived from measured risk. Same intuition, but the numbers come from the graph instead
of being guessed. And because they flow from the risk engine, they're tunable by adjusting
dimension weights — not by rewriting heuristic rules.

**Why start at 1.0**: The multipliers are a function of dimension scores, and the
dimension scores are a function of thresholds we haven't validated yet. Applying
multipliers before calibration means compounding two sources of error through the entire
estimation chain. Start with base costs only, collect actuals, *then* activate the
multipliers with data behind them.

(Priya) "The mapping is explicit: cycles make implementation and integration harder.
Database coupling makes testing and migration harder. Domain boundaries make investigation
and integration harder. Each dimension affects the categories where it actually hurts."

#### Graph-Derived Base Costs

```python
def estimate_effort_from_graph(
    impact: ImpactReport,
    aggregate_risk: AggregateRisk,
    db_impact: Optional[DatabaseImpact],
) -> list[EffortBreakdown]:
    """
    Deterministic effort estimate based on graph topology and risk profile.

    Base costs come from consumer counts and depth.
    Multipliers come from the risk engine.
    """
```

**Investigation phase:**
- Base: 0.5 days per target
- +0.5 days per domain cluster affected (cross-boundary investigation)
- +1.0 day if cycle involvement (need to map the cycle before touching it)
- Cap: 1–3 days (investigation has diminishing returns)
- Multiplied by: `risk_driven_multiplier["investigation"]`

**Implementation phase:**
- Base: 1.0 day per direct consumer (code changes needed)
- +0.5 days per transitive consumer at depth 1 (API contract verification)
- +0.25 days per transitive consumer at depth 2 (smoke testing)
- Multiplied by: `risk_driven_multiplier["implementation"]`

**Testing phase:**
- Base: 0.5 days per direct consumer (unit/integration tests)
- +1.0 day per shared sproc (database testing is always slower)
- +0.5 days if cross-domain (need integration test environments)
- Multiplied by: `risk_driven_multiplier["testing"]`

**Integration risk buffer:**
- Base: 0 days if no cycles, no shared sprocs, single domain cluster
- +1.0 day per cycle involvement
- +0.5 days per shared sproc (migration coordination)
- +1.0 day per additional domain cluster (cross-team coordination)
- +0.5 days if max fan-in > 5 (high blast radius = cautious rollout)
- Multiplied by: `risk_driven_multiplier["integration_risk"]`

**Database migration (if applicable):**
- Base: 1.0 day per shared sproc
- +2.0 days if sproc is called by > 3 projects (staged migration)
- +1.0 day per team boundary crossed (coordination overhead)
- Multiplied by: `risk_driven_multiplier["database_migration"]`

(Devon) "These base costs are starting points, not gospel. The calibration loop in Phase 3
tunes both the base costs AND the risk-to-multiplier mapping. Two knobs, not one."

(Priya) "The categories matter more than the numbers. Finance doesn't care if 'testing' is
4.2 days or 5.1 days. They care that testing is called out separately from implementation,
because those are different budget lines and different people."

#### AI-Assisted Adjustment

After the graph heuristics produce a baseline, the AI sees:

- The full ImpactReport (targets, consumers, risk ratings)
- The graph-derived effort breakdown
- The coupling narratives for each consumer
- The database impact assessment

And produces an adjusted estimate with justification:

```python
AI_EFFORT_PROMPT = """
You are estimating development effort for a .NET codebase change.

## Work Request
{sow_text}

## Graph-Derived Baseline
{effort_breakdown_table}

## Impact Context
- Direct consumers: {direct_count}
- Transitive consumers: {transitive_count}
- Cycle involvement: {cycle_involvement}
- Domain clusters affected: {cluster_count}
- Shared stored procedures: {sproc_count}

## Coupling Details
{coupling_narratives}

## Instructions
Review the graph-derived baseline. Adjust if the coupling narratives reveal complexity
the heuristics can't capture (e.g., deep interface hierarchies, event-driven coupling,
configuration-dependent behavior).

Return a JSON object:
{
  "adjustments": [
    {
      "category": "implementation",
      "adjusted_min": 10,
      "adjusted_max": 14,
      "reason": "Coupling narrative for GalaxyWorks.Api reveals event-driven pattern..."
    }
  ],
  "additional_risks": ["..."],
  "confidence_adjustment": "moderate"  // "raise", "maintain", "lower"
}
"""
```

(Marcus) "The AI adjustment is optional and clearly labeled as such. The graph-derived
baseline is the number of record. The AI adjustment is a 'consider also' — it gets shown
in the report but it doesn't silently modify the baseline."

(Fatima) "If the AI is unavailable, the graph-derived estimate ships as-is. No degradation
in the core deliverable. The AI enrichment is bonus context, not load-bearing."

### Confidence Bands

The confidence band tells finance how much to trust the estimate. It's derived from
the risk engine's dimension scores — objective, graph-derived signals.

```python
def compute_confidence(
    aggregate_risk: AggregateRisk,
    impact: ImpactReport,
) -> ConfidenceBand:
    """
    Confidence is inverse of risk uncertainty.

    The risk engine's composite score directly drives the band width:
      composite < 0.3  → HIGH (±20%)  — contained, predictable change
      composite < 0.6  → MODERATE (±30%) — some risk dimensions elevated
      composite >= 0.6 → LOW (±50%)  — multiple risk dimensions elevated

    Additional widening:
      ambiguity_level == "vague" → one step wider (e.g., HIGH → MODERATE)
      > 2 critical dimensions    → one step wider
    """
```

The percentage isn't a statistical confidence interval — it's a calibrated uncertainty
range. Phase 3 calibration will tune these percentages against actuals.

(Priya) "Don't call it a confidence interval. That implies statistical rigor we don't have.
Call it an 'uncertainty range' or 'confidence band'. Finance knows what ±30% means without
needing to understand Monte Carlo simulations."

### Deep Risk Analysis in SOW Output

This is where SOW scoping diverges from PR risk. A PR comment needs risk in 5 seconds.
A SOW scoping report needs risk in 5 *dimensions*, with enough detail to drive a planning
conversation.

The SOW scoping report includes the **full risk engine output** from `RISK_ENGINE_PLAN.md`:
per-target `RiskProfile`, aggregated `AggregateRisk`, and all seven dimension scores.
But it also adds SOW-specific risk analysis that doesn't exist in the PR context.

#### Risk Categories for SOW Planning

SOW risk isn't just "will this break?" — it's "what kind of trouble will this cause?"
The risk engine dimensions map to four planning-relevant risk categories:

| Planning Category | Risk Dimensions Used | What It Answers |
|-------------------|---------------------|-----------------|
| **Technical risk** | structural, instability, cycle | "How hard is the code change itself?" |
| **Coordination risk** | domain_boundary, blast_radius | "How many teams/projects need to move together?" |
| **Data risk** | database, cycle | "Is the database migration going to blow up the timeline?" |
| **Regression risk** | blast_radius, instability, change_surface | "How likely is this to break something in production?" |

```python
Risk categories are **not a dataclass** — they're a reporter concern. The risk engine
provides the raw dimension scores; the scoping reporter groups them into planning-relevant
buckets for display. Adding a `SOWRiskCategories` dataclass would create a translation
layer between the engine's dimensions and the reporter's output that adds complexity
without adding data. The reporter reads dimension scores directly and formats them into
the four planning categories.

**Planning implications** are **AI-generated**, not hardcoded. The risk engine provides
dimension scores and factors. The AI sees those scores in context (which targets, which
teams, which sprocs) and generates implications specific to *this* SOW. Hardcoded templates
like "schedule cross-team sync" are generic enough to be useless — the AI can say "schedule
sync with Platform team before modifying PortalDataService because their Api project is in
the cycle." That specificity is what makes the implication actionable.

The reporter passes the dimension scores and risk factors to the AI implication prompt. If
AI is unavailable, the reporter falls back to the top risk factors from the engine —
still useful, just less specific.

(Fatima) "The planning implications are the part that makes this useful in a scoping
meeting. The risk scores tell the architect what to worry about. The implications tell the
project manager what to *do* about it. Different audience, same data."

#### Per-Target Risk Drill-Down

For each target in the SOW, the report includes the full 7-dimension breakdown:

```
TARGET: PortalDataService (class, GalaxyWorks.Data)
────────────────────────────────────────────────────

  Composite Risk: 0.78 (HIGH)

  Dimensions:
    Database coupling    ████████░░  0.85  CRITICAL  4 sprocs shared across 3 teams
    Cycle entanglement   ████████░░  0.80  HIGH      Data ↔ Api ↔ Core (3 projects)
    Blast radius         ███████░░░  0.70  HIGH      14 transitive consumers (depth 2)
    Structural coupling  ████░░░░░░  0.45  MEDIUM    Fan-in of 8
    Domain boundary      █████░░░░░  0.50  MEDIUM    Crosses 2 domain clusters
    Instability          ███░░░░░░░  0.30  LOW       Instability 0.35
    Change surface       ░░░░░░░░░░  n/a   n/a       (no diff available)

  Risk Narrative (AI):
    PortalDataService sits at the intersection of three risk patterns: it's
    in a dependency cycle with Api and Core, it shares 4 stored procedures
    with projects owned by 3 different teams, and it has 14 transitive
    consumers reaching depth 2. Changes here require coordinated releases
    across the cycle AND coordinated database migration across teams.

  Mitigations (AI):
    1. Break the cycle before modifying PortalDataService — extract shared
       interfaces into a new GalaxyWorks.Contracts project
    2. Map sproc migration order: which sprocs can be migrated independently
       vs which require coordinated cutover?
    3. Engage Platform team early — they own GalaxyWorks.Api, the direct
       consumer in the cycle

  Coupling Vectors:
    → GalaxyWorks.Api:           Direct instantiation, Interface implementation
    → GalaxyWorks.WebPortal:     Direct instantiation, Static method calls
    → GalaxyWorks.BatchProcessor: Shared sprocs (dbo.sp_InsertPortalConfiguration)
```

(Marcus) "The bar chart is a nice touch — it makes the dimension scores scannable. But the
real value is the mitigations. Every risk dimension that's HIGH or CRITICAL should have at
least one concrete mitigation. Otherwise you're just telling people to be scared."

#### Risk Heatmap Across Targets

When a SOW has multiple targets, a heatmap shows where risk concentrates:

```
RISK HEATMAP
══════════════════════════════════════════════════════════════════

                     Struct  Instab  Cycle   DB      Blast  Domain  Change
PortalDataService      ██      ░       ██      ███     ██     █       ·
TenantContext          █       ░       ░       ░       █      █       ·
IPortalRepository      █       ░       ██      ░       ██     █       ·

Legend: ███ critical  ██ high  █ medium  ░ low  · n/a

Hotspot: PortalDataService drives 4 of 6 risk dimensions.
         Consider scoping PortalDataService changes as a separate, sequenced deliverable.
```

(Devon) "The heatmap answers the question 'where should we focus our risk mitigation
effort?' If one target lights up across all dimensions, that's the one you plan around.
Everything else is ancillary."

#### Risk-Informed Team Consultation

The team consultation section gains risk data per team:

```
TEAMS TO CONSULT
═══════════════════════════════════════════════════════════════

  Platform (owns GalaxyWorks.Api, GalaxyWorks.Core)
    Risk exposure: HIGH
    Risk dimensions: cycle (their Api is in the Data ↔ Api cycle),
                     structural (coupling score 0.82 to target)
    Why they care: Any change to PortalDataService cascades through the
                   cycle to their Api project. They need to coordinate
                   releases and may need to update their side of the cycle.
    Action: Schedule sync BEFORE implementation begins.

  Batch Operations (owns GalaxyWorks.BatchProcessor)
    Risk exposure: MEDIUM
    Risk dimensions: database (shares 2 sprocs with target)
    Why they care: Their BatchProcessor calls dbo.sp_InsertPortalConfiguration
                   and dbo.sp_GetTenantConfig. Sproc signature changes will
                   break their batch jobs.
    Action: Include in database migration planning. Verify sproc
            backward-compatibility or coordinate cutover timing.

  Portal (owns GalaxyWorks.WebPortal)
    Risk exposure: MEDIUM
    Risk dimensions: structural (coupling score 0.71, direct instantiation)
    Why they care: WebPortal directly instantiates PortalDataService.
                   Constructor or method signature changes require their
                   code to update.
    Action: Include in PR review. May need coordinated merge.
```

(Priya) "Each team entry answers three questions: what's their risk exposure, why should
they care, and what do they need to do. If you can't answer all three, the consultation
is vague and nobody will act on it."

### Historical Calibration

This is the feature that transforms Scatter from a calculator into an oracle. Over time,
the estimates get better because they learn from outcomes.

#### The Calibration Loop

```
SOW arrives
  → Scatter produces ScopingReport with prediction
  → Prediction logged to calibration store
  → Work happens (weeks/months pass)
  → Actuals recorded (manually initially, automated later)
  → Calibration analysis: predicted vs actual
  → Heuristic multipliers adjusted
  → Next SOW benefits from updated multipliers
```

#### Calibration Store

```python
@dataclass
class ScopingPrediction:
    """A prediction record for calibration tracking."""
    sow_id: str
    timestamp: datetime
    sow_text: str

    # Prediction
    predicted_min_days: float
    predicted_max_days: float
    confidence_band: str              # "high", "moderate", "low"
    effort_breakdown: list[EffortBreakdown]

    # Graph context at prediction time
    direct_consumers: int
    transitive_consumers: int
    cycle_involvement: bool
    domain_clusters_affected: int
    shared_sproc_count: int
    max_coupling_score: float

    # Actuals (filled in later)
    actual_days: Optional[float]
    actual_breakdown: Optional[dict[str, float]]  # category → days
    outcome_notes: Optional[str]
    recorded_at: Optional[datetime]

    # Calibration metrics (computed)
    accuracy: Optional[float]         # predicted_mid / actual
    within_band: Optional[bool]       # was actual within confidence band?
```

Stored as append-only JSONL. One file, simple, `grep`-able.

#### Comparable SOW Retrieval

When a new SOW comes in, Scatter searches the calibration store for similar past work.
Similarity is based on:

1. **Topological similarity** (weighted 60%): Same number of consumers, similar coupling
   scores, similar cycle involvement, same domain clusters
2. **Textual similarity** (weighted 40%): AI compares the SOW text to past SOW texts

```python
def find_comparable_sows(
    current: ScopingReport,
    history: list[ScopingPrediction],
    top_k: int = 3,
) -> list[ComparableSOW]:
    """
    Find past SOWs with similar blast radius topology.

    Topological features (normalized):
    - direct_consumer_count
    - transitive_consumer_count
    - cycle_involvement (bool → 0/1)
    - domain_clusters_affected
    - shared_sproc_count
    - max_coupling_score

    Similarity = weighted cosine of feature vectors.
    """
```

(Devon) "Cosine similarity on the topology vector is simple and works. Don't over-engineer
this with embeddings or learned similarity functions. You'll have maybe 20–50 historical
SOWs in the first year. Simple math on small data."

The comparable SOWs serve two purposes:

1. **Anchoring**: "A similar SOW last quarter took 22 dev-days" — this is the strongest
   possible argument in a scoping meeting because it's not a prediction, it's a fact
2. **Calibration signal**: If past predictions for similar SOWs were consistently 20% low,
   the current estimate should be adjusted upward

### Team Consultation Mapping

Scatter can identify *which* teams own the affected consumers. This requires a
team→project ownership mapping, which can come from:

1. **CODEOWNERS file** (if available) — standard GitHub convention
2. **Manual mapping file** (`.scatter.yaml` or separate YAML)
3. **Solution-level ownership** (`.sln` files often cluster by team)
4. **Directory convention** (e.g., `src/Platform/`, `src/Billing/`)

```yaml
# .scatter.yaml
teams:
  Platform:
    owns:
      - "GalaxyWorks.Core"
      - "GalaxyWorks.Api"
      - "GalaxyWorks.Infrastructure"
    contact: "#platform-eng"        # Slack channel

  BatchOps:
    owns:
      - "GalaxyWorks.BatchProcessor"
      - "GalaxyWorks.Scheduler"
    contact: "#batch-ops"

  Portal:
    owns:
      - "GalaxyWorks.WebPortal"
      - "GalaxyWorks.Portal.*"      # glob pattern
    contact: "#portal-team"
```

(Priya) "The team mapping is the highest-value, lowest-code feature in this initiative.
Every SOW scoping meeting asks 'who else needs to know?' The graph already knows which
projects are affected. Adding team ownership turns that into names and Slack channels."

(Fatima) "If no team mapping exists, the report should say 'team ownership not configured'
instead of silently omitting the section. Make the absence visible — it's a prompt to
fix it."

### Database Migration Complexity

For monolith-to-micro work, the database is where estimates blow up. Scatter already
detects shared sprocs. The scoping feature should assess migration difficulty.

```python
def assess_database_impact(
    graph: DependencyGraph,
    targets: list[AnalysisTarget],
    team_map: Optional[TeamMap],
) -> Optional[DatabaseImpact]:
    """
    Assess database migration complexity for shared stored procedures.

    Complexity levels:
    - LOW: sprocs are used by 1-2 projects within the same team
    - MEDIUM: sprocs are used by 3+ projects OR cross-team
    - HIGH: sprocs are used by 5+ projects across 3+ teams,
            or sprocs are in a call chain (sproc A calls sproc B)
    """
```

**Migration patterns to detect:**

| Pattern | Complexity | Indicator |
|---------|-----------|-----------|
| Single-owner sproc | Low | 1 project references it |
| Shared-team sproc | Low | 2-3 projects, same team |
| Cross-team sproc | Medium | Multiple teams reference it |
| High-fan-in sproc | High | 5+ projects, staged migration needed |
| Sproc chain | High | Sproc A calls Sproc B (detected by DB scanner) |
| Schema-coupled sproc | High | Sproc uses tables that other sprocs also use |

(Marcus) "Every monolith decomposition I've seen underestimates the database work by 2–3x.
If Scatter can surface the database complexity *before* the scoping meeting, that alone
justifies the feature."

---

## Implementation Plan

### Phase 1: Structured Effort Estimation (2 weeks)

**Goal**: `scatter --sow "..." --scope-estimate` produces a `ScopingReport` with effort
breakdown and confidence band.

#### Deliverables

**1.1 ScopingReport dataclass** (`scatter/core/models.py`)
- Add `ScopingReport`, `EffortBreakdown`, `ConfidenceBand`, `DatabaseImpact`
- `ScopingReport` wraps `ImpactReport` (composition, not inheritance)

**1.2 Effort estimator** (`scatter/analyzers/effort_estimator.py`)
- New module, ~300 lines
- Entry point: `estimate_effort(impact, metrics, cycles, clusters, db_impact) -> list[EffortBreakdown]`
- Pure function: graph data in, effort breakdown out
- Implements the heuristic multipliers described above
- Returns both graph-derived baseline and AI-adjusted estimate (if AI available)

**1.3 Confidence calculator** (`scatter/analyzers/effort_estimator.py`)
- `compute_confidence(impact, cycles, clusters, db_impact) -> ConfidenceBand`
- Deterministic — no AI needed

**1.4 Database impact assessor** (`scatter/analyzers/db_impact_analyzer.py`)
- New module, ~150 lines
- Entry point: `assess_database_impact(graph, targets, team_map) -> DatabaseImpact`
- Queries graph for `sproc_shared` edges, groups by project and team
- Assigns complexity rating based on fan-out and team boundaries

**1.5 AI effort adjustment task** (`scatter/ai/tasks/effort_adjustment.py`)
- New AI task type: `EFFORT_ADJUSTMENT`
- Prompt template that takes graph-derived baseline + coupling context
- Returns adjustments per category with justification
- Graceful degradation: if AI unavailable, graph-derived baseline ships as-is

**1.6 Scoping mode handler** (`scatter/cli.py`)
- Extend existing `--sow` mode: add `--scope-estimate` flag
- When enabled, runs effort estimation after impact analysis
- New output dispatch for `ScopingReport`

**1.7 Scoping reporters**
- **Console**: summary table with effort breakdown, confidence band, risk factors
- **JSON**: full `ScopingReport` serialization
- **Markdown**: formatted report suitable for pasting into Confluence/Teams/Slack
- **CSV**: one row per effort category for spreadsheet import

**1.8 Performance budget**

SOW scoping is not latency-sensitive like PR comments (nobody's waiting 90 seconds for a
scoping estimate). But it shouldn't take 10 minutes either. Budget:

| Step | Target | Notes |
|------|--------|-------|
| Graph load/build | 2–40s | Depends on cache hit |
| Impact analysis | 5–15s | Existing pipeline, graph-accelerated |
| Risk engine (all targets) | 2–5s | 6 dimensions × N targets, all graph queries |
| Effort estimation | <1s | Pure math on risk scores |
| AI enrichment (optional) | 10–30s | Narrative + mitigations + effort adjustment |
| **Total (no AI)** | **10–60s** | Acceptable |
| **Total (with AI)** | **20–90s** | Acceptable for scoping workflow |

The AI enrichment is the long pole. If it's too slow, it runs async and the graph-derived
estimate ships immediately with "AI analysis pending" placeholder.

**1.9 Tests**
- `tests/unit/test_effort_estimator.py`: heuristic calculations, multiplier edge cases
- `tests/unit/test_db_impact_analyzer.py`: sproc grouping, complexity levels
- Integration: run against sample projects with known topology, verify estimates
- Performance test: scoping against sample projects must complete in <60s without AI

#### Design Decisions

| Decision | Rationale | Persona |
|----------|-----------|---------|
| Graph-derived baseline as primary, AI as optional overlay | Reproducibility — same graph = same estimate | Marcus |
| Effort categories match finance budget lines | Investigation, implementation, testing, integration risk, DB migration | Priya |
| ConfidenceBand from topology, not AI sentiment | Defensible — "it's ±30% because there are cycles" vs "the AI said moderate" | Devon |
| `ScopingReport` wraps `ImpactReport` (composition) | Impact analysis is proven; don't refactor it, extend it | Tomas |
| Database impact as separate analyzer | Keeps effort_estimator focused on time; DB impact is structural analysis | Sam |

### Phase 2: Team Mapping and Consultation Lists (1–2 weeks)

**Goal**: SOW scoping report includes "teams to consult" with contact info.

#### Deliverables

**2.1 Team map loader** (`scatter/config.py`)
- Add `TeamConfig` to configuration system
- Load from `.scatter.yaml` `teams:` section
- Support glob patterns for project matching
- Fallback: parse CODEOWNERS if available

**2.2 Team resolver** (`scatter/analyzers/team_resolver.py`)
- New module, ~100 lines
- `resolve_teams(consumers, team_map) -> list[TeamConsultation]`
- Groups consumers by owning team
- Computes per-team risk level (max of their consumers' risk)
- Returns sorted by risk level (highest first)

**2.3 Integration into ScopingReport**
- Wire `teams_to_consult` into the scoping pipeline
- Add to all reporters
- If no team map configured, report shows "team ownership not configured — add a `teams:`
  section to .scatter.yaml to enable"

**2.4 Tests**
- `tests/unit/test_team_resolver.py`: ownership matching, glob patterns, missing config

### Phase 3: Historical Calibration (2–3 weeks)

**Goal**: Track predictions against actuals. Surface comparable past SOWs.

#### Deliverables

**3.1 Calibration store** (`scatter/store/calibration_store.py`)
- New module, ~200 lines
- Append-only JSONL storage
- `save_prediction(report: ScopingReport) -> str` (returns sow_id)
- `record_actual(sow_id: str, actual_days: float, breakdown: dict, notes: str)`
- `load_history() -> list[ScopingPrediction]`
- Location configurable in `.scatter.yaml` (default: `.scatter/calibration/`)

**3.2 CLI commands for actuals**
- `scatter --record-actual --sow-id SOW-2026-001 --actual-days 22 --notes "..."`
- `scatter --calibration-report` — show prediction accuracy dashboard

**3.3 Comparable SOW finder** (`scatter/analyzers/comparable_finder.py`)
- New module, ~150 lines
- `find_comparable_sows(current, history, top_k=3) -> list[ComparableSOW]`
- Topological cosine similarity (60%) + optional AI text similarity (40%)
- Only returns SOWs that have recorded actuals (predictions without actuals aren't comparable)

**3.4 Integration into scoping pipeline**
- After effort estimation, search calibration store for comparable SOWs
- Include in ScopingReport and all reporters
- If no history exists, report shows "no historical data yet — run `scatter --record-actual`
  after SOW completion to enable calibration"

**3.5 Calibration dashboard** (`scatter/reports/calibration_reporter.py`)
- Shows: total predictions, predictions with actuals, accuracy distribution
- Flags systematic bias: "estimates tend to be 15% low for SOWs with cycle involvement"
- Suggests multiplier adjustments: "consider raising cycle multiplier from 1.5x to 1.8x"
- Output formats: console table, JSON, markdown

**3.6 Tests**
- `tests/unit/test_calibration_store.py`: JSONL read/write, actual recording
- `tests/unit/test_comparable_finder.py`: similarity computation, edge cases
- `tests/unit/test_calibration_reporter.py`: accuracy metrics, bias detection

### Phase 4: Multiplier Auto-Tuning (1–2 weeks) — DEFERRED

**Deferred until**: 20+ SOWs with recorded actuals in the calibration store.

**Goal**: Automatically adjust heuristic multipliers based on calibration data.

This is the phase where the system starts learning. But learning requires data, and data
requires adoption, and adoption requires Phases 1–3 to be shipped and earning trust.
Don't build the auto-tuner before you have anything to tune.

#### Deliverables

**4.1 Multiplier tuner** (`scatter/analyzers/calibration_tuner.py`)
- New module, ~200 lines
- Analyzes calibration history to detect systematic bias
- Groups predictions by topological features (cycle involvement, sproc count, cluster count)
- Computes per-feature accuracy and suggests multiplier adjustments

```python
def suggest_multiplier_updates(
    history: list[ScopingPrediction],
    min_samples: int = 5,
) -> list[MultiplierSuggestion]:
    """
    Analyze calibration data and suggest heuristic adjustments.

    Only suggests changes when:
    - At least min_samples SOWs have recorded actuals
    - Systematic bias detected (mean accuracy < 0.85 or > 1.15)
    - Bias is attributable to a specific feature (not random noise)

    Returns suggestions, never auto-applies. Human reviews and accepts.
    """
```

(Priya) "Auto-tuning suggests, it doesn't auto-apply. The multipliers are human-reviewed
because the sample size will be small (maybe 10–20 SOWs) and a single outlier could skew
the adjustment. Show the suggestion, let someone decide."

**4.2 Tuning report**
- `scatter --calibration-tune` — shows current multipliers, suggested adjustments,
  supporting data (which SOWs drove the suggestion)
- If accepted: updates `.scatter.yaml` with new multipliers
- If rejected: no change, suggestion is logged for future review

**4.3 Tests**
- `tests/unit/test_calibration_tuner.py`: bias detection, small sample handling,
  outlier resistance

---

## Output Formats

### Console Output

```
╔══════════════════════════════════════════════════════════════════╗
║  SOW SCOPE ASSESSMENT                                          ║
╠══════════════════════════════════════════════════════════════════╣
║  "Add tenant isolation to PortalDataService and related        ║
║   data access patterns"                                        ║
║                                                                ║
║  Targets: 3 (confidence: HIGH, avg 0.85)                       ║
║  Direct consumers: 8 │ Transitive: 14 (depth 2)                ║
║  Domain clusters: 2  │ Cycle involvement: yes                  ║
║  Shared sprocs: 4                                              ║
╠══════════════════════════════════════════════════════════════════╣
║  EFFORT ESTIMATE                           Confidence: ±30%    ║
╠──────────────────────────────────┬─────────┬───────────────────╣
║  Category                       │  Days   │  Notes            ║
╠──────────────────────────────────┼─────────┼───────────────────╣
║  Investigation                  │  1 – 2  │                   ║
║  Implementation                 │  8 – 12 │  1.5x (cycle)    ║
║  Testing                        │  4 – 6  │  +sproc testing  ║
║  Integration risk               │  3 – 5  │  cycle + sprocs  ║
║  Database migration             │  4 – 6  │  4 shared sprocs ║
║──────────────────────────────────┼─────────┼───────────────────║
║  TOTAL                          │ 20 – 31 │  4.0–6.2 weeks   ║
╠══════════════════════════════════════════════════════════════════╣
║  TEAMS TO CONSULT                                              ║
╠────────────────────┬──────────────────────┬────────────────────╣
║  Team              │  Affected Projects   │  Risk Level        ║
╠────────────────────┼──────────────────────┼────────────────────╣
║  Platform          │  GalaxyWorks.Api,    │  HIGH              ║
║                    │  GalaxyWorks.Core    │                    ║
║  BatchOps          │  GW.BatchProcessor   │  MEDIUM            ║
║  Portal            │  GW.WebPortal        │  MEDIUM            ║
╠══════════════════════════════════════════════════════════════════╣
║  COMPARABLE PAST SOWS                                          ║
╠────────────────────────────────────┬──────────┬────────────────╣
║  Description                      │  Actual  │  Predicted     ║
╠────────────────────────────────────┼──────────┼────────────────╣
║  Migrate session mgmt to Redis    │  22 days │  18–26 (✓)     ║
║  Add audit logging to DAL         │  14 days │  12–20 (✓)     ║
╚══════════════════════════════════════════════════════════════════╝
```

### CSV Output (for Finance)

```csv
# SOW Scope Assessment - scatter v0.12.0
# SOW: "Add tenant isolation to PortalDataService and related data access patterns"
# Generated: 2026-03-30T14:22:00Z
# Confidence: ±30% (moderate)
Category,Min Days,Max Days,Notes,Risk Multiplier
Investigation,1.0,2.0,,1.0
Implementation,8.0,12.0,1.5x cycle involvement,1.5
Testing,4.0,6.0,includes sproc testing,1.0
Integration Risk,3.0,5.0,cycle + shared sprocs,1.0
Database Migration,4.0,6.0,4 shared sprocs,1.0
TOTAL,20.0,31.0,4.0-6.2 developer-weeks,
```

This drops straight into a spreadsheet. No JSON-to-Excel conversion needed.

### JSON Output (for Programmatic Consumption)

Full `ScopingReport` serialization — everything above plus raw data for dashboards,
tracking systems, or downstream tooling.

### Markdown Output (for Confluence/Teams)

Formatted version of the console output, suitable for pasting into documentation or
Slack threads. Uses tables, headers, and callout blocks.

---

## What This Means for Athena

### Immediate Value (Phase 1)
- SOW investigation drops from 1–2 weeks to 30 minutes
- Effort estimates are grounded in the actual dependency graph, not tribal knowledge
- Database complexity is surfaced *before* the scoping meeting, not discovered mid-sprint
- Output format works for engineers (JSON/console) AND finance (CSV/markdown)

### Growing Value (Phase 2–3)
- "Teams to consult" prevents the "we forgot to tell Platform" failure mode
- Historical calibration means estimates get better with every SOW
- Comparable SOWs are the strongest argument in a scoping meeting — "similar work took X"
- Athena builds a track record: "our predictions were within ±25% for 12 consecutive SOWs"

### Strategic Value (Phase 4)
- Self-tuning estimates that improve with usage
- Calibration data becomes institutional knowledge — it survives team turnover
- Other SOW teams in the division adopt Scatter because the estimates are defensible
- Athena becomes the team that brought rigor to scoping across the org

(Priya) "The investigation cost savings alone justify Phase 1. Everything after that is
about building the kind of tooling that makes an engineering organization measurably
better at planning. That's how Athena gets visibility at the division level."

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Heuristic multipliers are wrong initially | High | Medium | Phase 3 calibration loop; start conservative (overestimate > underestimate) |
| AI effort adjustment contradicts graph baseline | Medium | Low | AI adjustments shown separately, clearly labeled; graph baseline is the number of record |
| Finance takes estimates as commitments | High | High | Confidence bands are mandatory in all output; train stakeholders that ±30% means ±30% |
| Too few historical SOWs for calibration | High (year 1) | Medium | Comparable SOW feature degrades gracefully; show "insufficient data" instead of bad comparisons |
| Team ownership data is incomplete | Medium | Low | Graceful: "team ownership not configured"; partial data still useful |
| Database complexity assessment misses schema coupling | Medium | Medium | Phase 1 covers sproc-level; schema-level analysis is Phase 2 extension |
| Estimates anchor too strongly on graph topology | Medium | Medium | AI adjustment exists to catch non-topological complexity; calibration catches systematic bias |

---

## Relationship to PR Risk Scoring

These two features share infrastructure and reinforce each other:

| Shared Component | PR Risk Scoring | SOW Scoping |
|-----------------|----------------|-------------|
| Consumer detection pipeline | Per-PR, graph-accelerated | Per-target, graph-accelerated |
| Coupling metrics | Risk signal input | Effort multiplier input |
| Cycle detection | Auto-red risk factor | Effort multiplier + confidence reducer |
| Database impact | Shared sproc flag | Migration complexity assessment |
| Team mapping | Cross-team consumer count | "Teams to consult" list |
| Calibration store | Prediction log (PR outcomes) | Prediction log (SOW actuals) |

**Build PR Risk Scoring first** — it's simpler, ships faster, and creates the adoption
flywheel. SOW Scoping benefits from the same graph cache, coupling metrics, and team
mapping infrastructure.

**The calibration stores are separate** (PRs and SOWs have different prediction shapes)
but the calibration *patterns* are identical: log prediction → record actual → compute
accuracy → suggest adjustments.

---

## Open Questions

1. **Where do SOW actuals come from?** Jira time tracking? Sprint retrospectives? Manual
   entry? Phase 3 needs a source of truth for actual effort. Manual entry is fine for
   year 1 — automation can come later.

2. **Granularity of actuals**: Do we track total days only, or per-category
   (investigation, implementation, testing)? Per-category is better for calibration but
   harder to collect. Recommendation: start with total days, add categories as adoption
   grows.

3. **Multi-repo SOWs**: Some work requests span multiple repositories. Can the SOW be
   scoped across repos, or is each repo analyzed independently and then combined?
   Recommendation: per-repo initially, with a manual aggregation step.

4. **SOW versioning**: SOWs change during scoping ("actually, also include the Billing
   module"). Should the calibration store track versions? Recommendation: re-run Scatter
   on the updated SOW, generate a new prediction with a new ID. Keep it simple.

5. **Effort unit**: Developer-days or story points? Recommendation: developer-days.
   Story points are team-specific and don't translate across teams or to finance.
   Developer-days are universally understood.

### Deferred Features (post-adoption)

These are real features that need real usage data before they're worth building:

- **Comparable SOW retrieval**: Find similar past SOWs by topological cosine similarity.
  Requires 20+ SOWs with recorded actuals before similarity search is meaningful.
- **Multiplier auto-tuning**: Phase 4 (above). Needs calibration data.
- **Multi-repo SOW analysis**: Some work spans repositories. Per-repo analysis with manual
  aggregation is the Phase 1 answer. Cross-repo graph integration is a v3 problem.
- **Automated actuals collection**: Pull actual effort from Jira, sprint boards, or time
  tracking. Manual entry is fine for year 1 — the friction of manual entry is lower than
  the friction of integrating with every team's tracking tool.

---

## Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `scatter/core/models.py` | Modify | Add `ScopingReport`, `EffortBreakdown`, `ConfidenceBand`, `DatabaseImpact`, `TeamConsultation`, `ComparableSOW` |
| `scatter/analyzers/effort_estimator.py` | Create | Graph-derived effort heuristics + confidence computation |
| `scatter/analyzers/db_impact_analyzer.py` | Create | Database migration complexity assessment |
| `scatter/analyzers/team_resolver.py` | Create | Consumer → team mapping + consultation list |
| `scatter/analyzers/comparable_finder.py` | Create | Historical SOW similarity search |
| `scatter/analyzers/calibration_tuner.py` | Create | Multiplier auto-tuning suggestions |
| `scatter/ai/tasks/effort_adjustment.py` | Create | AI effort adjustment prompt |
| `scatter/store/calibration_store.py` | Create | JSONL prediction + actuals storage |
| `scatter/reports/scoping_reporter.py` | Create | Console/markdown scoping output |
| `scatter/reports/calibration_reporter.py` | Create | Calibration accuracy dashboard |
| `scatter/config.py` | Modify | Add `TeamConfig`, `ScopingConfig` |
| `scatter/cli.py` | Modify | Add `--scope-estimate`, `--record-actual`, `--calibration-report`, `--calibration-tune` |
| `scatter/cli_parser.py` | Modify | Add new CLI arguments |
| `.scatter.yaml` (example) | Modify | Add `teams:` and `scoping:` config sections |
| `tests/unit/test_effort_estimator.py` | Create | Heuristic calculation tests |
| `tests/unit/test_db_impact_analyzer.py` | Create | Database impact tests |
| `tests/unit/test_team_resolver.py` | Create | Team mapping tests |
| `tests/unit/test_calibration_store.py` | Create | Prediction storage tests |
| `tests/unit/test_comparable_finder.py` | Create | Similarity search tests |
| `tests/unit/test_calibration_tuner.py` | Create | Auto-tuning tests |
