# The Risk Engine — Unified Risk Analysis Across Scatter

**Initiative**: Unified Risk Engine
**Target branch**: `feature/risk-engine`
**Effort estimate**: 3–4 weeks (foundational; consumed by PR Risk Scoring and SOW Scoping)
**Dependencies**: Coupling analyzer (done), cycle detection (done), domain clustering (done), graph engine (done)
**Blockers**: None — all prerequisite modules exist
**Team reviewers**: Priya (architecture), Devon (algorithms), Marcus (observability), Fatima (failure modes)

---

## Team Review Decisions

The team reviewed the Phase 1 implementation plan. These decisions are resolved and baked
into the spec below. Rationale is preserved so future readers know *why*, not just *what*.

| # | Decision | Owner | Rationale |
|---|----------|-------|-----------|
| 1 | Risk types live in `scatter/core/risk_models.py`, not `models.py` | Priya | Risk types form a self-contained vocabulary (`RiskDimension` → `RiskProfile` → `AggregateRisk`). They don't reference `ImpactReport` or `EnrichedConsumer`. Keeping them in their own module prevents coupling the risk vocabulary to the impact vocabulary at the file level. When SOW scoping adds 6+ more dataclasses to `models.py`, the separation will pay for itself. |
| 2 | Piecewise linear scoring, not step functions | Devon | A project with instability 0.79 scoring 0.3 while 0.81 scores 0.9 is a cliff that confuses users. Dimension scorers interpolate between threshold inflection points. Same thresholds, smooth curves, no surprises at the boundaries. |
| 3 | Consistent `score_*` naming for all dimension functions | Devon | "Score" is more accurate than "assess" for functions that return a number. Pattern: `score_structural`, `score_instability`, `score_cycle`, `score_database`, `score_blast_radius`, `score_domain_boundary`. |
| 4 | `data_available` boolean on `RiskDimension` | Marcus | Downstream consumers (PR comment, SOW report) must distinguish "this is safe (0.0)" from "we don't know (0.0 because no data)." A dimension with `data_available=False` renders as "data unavailable" instead of "LOW", preventing the engine from lying about safety when it has no signal. |
| 5 | Structured logging at DEBUG/INFO from day one | Marcus | Every `compute_risk_profile` call logs target name, dimension scores, composite, risk level, wall-clock ms, and data quality flags. `DEBUG` for per-dimension detail, `INFO` for composite result. Standard `logging` module, no custom infrastructure. |
| 6 | Performance test: <100ms for full sample graph (13 projects) | Marcus | The engine is pure computation on in-memory data. 10 seconds is the full PR analysis budget — the engine alone must be sub-100ms. If it regresses, the test fails. |
| 7 | Unknown target → zeroed profile with `data_available=False` | Fatima | `compute_risk_profile` must never crash the caller. A target not in the graph returns a GREEN profile with all dimensions at 0.0 and `data_available=False`. Documented and tested explicitly. |
| 8 | Empty profile list → GREEN aggregate with all zeros | Fatima | `aggregate_risk([])` returns a safe aggregate instead of throwing `ValueError` from `max()` on empty sequence. This happens when a PR modifies only non-C# files. Tested explicitly. |
| 9 | `RiskContext.__post_init__` validation, fail-fast | Fatima | Weights outside [0.0, 1.0], `yellow_threshold >= red_threshold`, missing dimension keys — all caught at construction time with specific error messages, not at scoring time three layers deep. |
| 10 | Regression snapshot test for existing `--sow` mode | Fatima | Before and after the risk engine lands, the `--sow` output against sample projects must be byte-identical. This is our safety net that purely additive means purely additive. |

---

## The Problem

Scatter computes risk-relevant data in at least five places, but none of them talk to
each other.

| Module | Computes | Currently Used By |
|--------|----------|-------------------|
| `coupling_analyzer.py` | fan-in, fan-out, instability, coupling score | Graph reporter, console reporter |
| `coupling_analyzer.py` | Tarjan's cycle detection | Domain analyzer (feasibility scoring) |
| `domain_analyzer.py` | cluster cohesion, cross-boundary coupling, extraction feasibility | Graph reporter |
| `risk_assess.py` (AI) | per-consumer risk rating | Impact report |
| `complexity_estimate.py` (AI) | overall complexity, effort estimate | Impact report |
| `coupling_narrative.py` (AI) | coupling vectors per consumer | Impact report (display only) |
| `sproc_scanner.py` / `db_scanner.py` | shared stored procedures | Graph edges |

The risk assessment AI sees **consumer counts and depth** — that's it. It doesn't know
about cycles, coupling scores, instability, shared sprocs, domain boundaries, or API
surface area. It's making a risk call with 20% of the available signal.

Meanwhile, the coupling analyzer computes exactly the metrics that would make risk
assessment accurate — but that data stops at the graph reporter. It never reaches the
risk prompt.

The result: Scatter has a sophisticated structural analysis engine and a risk assessment
system that doesn't use it.

## The Opportunity

A unified risk engine that:

1. **Computes risk from the graph** — deterministic, reproducible, no AI needed
2. **Enriches with AI** — optional, adds narrative and context the graph can't see
3. **Works in every context** — PR risk, SOW scoping, local dev, graph analysis
4. **Produces the same risk vocabulary everywhere** — one `RiskProfile` dataclass, one
   set of risk dimensions, one scoring system

An engineer runs `scatter --branch-name feature/xyz` and sees risk factors. A GitHub
Action posts the same risk factors on the PR. A SOW scoping run includes the same risk
dimensions in the effort estimate. The vocabulary is consistent. The data model is shared.
The risk engine is one thing, consumed three ways.

---

## Risk Dimensions

Risk is multi-dimensional. A single "High" rating hides which dimensions are actually
dangerous. The risk engine should surface all dimensions and let the consumer (PR comment,
SOW report, console output) decide which to emphasize.

### The Seven Dimensions

```python
@dataclass
class RiskDimension:
    """A single axis of risk measurement."""
    name: str                # machine-readable identifier
    label: str               # human-readable label
    score: float             # 0.0 (safe) to 1.0 (dangerous)
    severity: str            # "low", "medium", "high", "critical"
    factors: list[str]       # human-readable explanations
    raw_metrics: dict        # underlying numbers for transparency
    data_available: bool = True  # False when metrics were missing (Decision #4)
```

> **Decision #4 (Marcus)**: `data_available=False` means "we had no data for this dimension,
> so the score is 0.0 by default — not because it's safe, but because we don't know."
> Reporters must render this differently from a true 0.0. Example: "Structural coupling:
> data unavailable" instead of "Structural coupling: 0.0 (LOW)".

| # | Dimension | What It Measures | Signal Source | Example Factor |
|---|-----------|-----------------|---------------|----------------|
| 1 | **Structural coupling** | How tightly bound is this to its consumers? | `coupling_score`, `fan_in`, `fan_out` | "Fan-in of 12 — top 3% of codebase" |
| 2 | **Instability** | How likely is change to propagate? | `instability` (Martin metric) | "Instability 0.85 — unstable AND highly depended on" |
| 3 | **Cycle entanglement** | Is this in a circular dependency? | Tarjan's SCC | "In cycle: Data ↔ Api ↔ Core (3 projects)" |
| 4 | **Database coupling** | Shared mutable state via stored procedures | `sproc_shared` edges, `shared_db_density` | "4 shared sprocs across 3 teams" |
| 5 | **Blast radius** | How far does change propagate? | Consumer count, transitive depth, BFS | "14 transitive consumers at depth 2" |
| 6 | **Domain boundary** | Does change cross service/team boundaries? | Louvain clusters, team mapping | "Crosses 3 domain clusters" |
| 7 | **Change surface** | What kind of change is this? | Diff analysis (delete/modify/add, interface/class) | "Interface deleted with 7 active implementors" |

### Why These Seven

(Priya) "Every production outage I've seen traces back to one of these. Cycles cause
cascading builds. Database coupling causes data corruption. Blast radius causes 'we didn't
know that was a consumer.' Domain boundaries cause 'we didn't tell that team.' Change
surface — specifically deletions and interface changes — causes compile breaks."

(Devon) "Seven is the right number. Fewer and you lose signal. More and you're measuring
noise. Each dimension maps to a specific graph query or diff operation — none of them
require guessing."

### Dimensions Not Included (and Why)

| Excluded | Reason |
|----------|--------|
| Code complexity (cyclomatic) | Requires deep parsing; Scatter is a graph tool, not a linter |
| Test coverage | Scatter doesn't know about test coverage; that's a CI concern |
| Developer familiarity | Unmeasurable from the graph; this is a people/process signal |
| Business criticality | Requires external metadata Scatter doesn't have (yet) |
| Deployment frequency | Requires CI/CD telemetry Scatter doesn't have (yet) |

These could be added later as optional dimensions with external data sources. The engine
should be extensible, not exhaustive.

---

## The RiskProfile

> **Decision #1 (Priya)**: All risk types (`RiskDimension`, `RiskProfile`, `AggregateRisk`,
> `RiskContext`, `RiskLevel`) live in `scatter/core/risk_models.py` — not `models.py`.
> The risk vocabulary is self-contained and doesn't reference impact analysis types.

Every target (a changed type, a project, a sproc) gets a `RiskProfile` that captures
all seven dimensions plus an aggregate.

```python
@dataclass
class RiskProfile:
    """Multi-dimensional risk assessment for a single target."""

    # Identity
    target_name: str
    target_type: str                 # "class", "interface", "project", "sproc"
    target_path: Optional[Path]

    # Dimensions (always present — graph-derived, no AI needed)
    structural: RiskDimension        # coupling score, fan-in/out
    instability: RiskDimension       # Martin instability metric
    cycle: RiskDimension             # cycle membership and severity
    database: RiskDimension          # shared sproc surface
    blast_radius: RiskDimension      # consumer count and depth
    domain_boundary: RiskDimension   # cross-cluster impact
    change_surface: RiskDimension    # change type severity

    # Aggregate
    composite_score: float           # 0.0–1.0, weighted combination
    risk_level: RiskLevel            # RED, YELLOW, GREEN
    risk_factors: list[str]          # top N human-readable factors, sorted by severity

    # AI enrichment (optional — None if AI unavailable)
    risk_narrative: Optional[str]    # 2-3 sentence explanation
    mitigation_suggestions: Optional[list[str]]
    coupling_vectors: Optional[list[str]]  # HOW the dependency exists

    # Context
    consumer_count: int
    transitive_consumer_count: int
    consumers_in_cycles: int
    consumers_cross_domain: int
    shared_sprocs: list[str]

    @property
    def dimensions(self) -> list[RiskDimension]:
        """All dimensions as a list, for iteration."""
        return [
            self.structural, self.instability, self.cycle,
            self.database, self.blast_radius, self.domain_boundary,
            self.change_surface,
        ]

    @property
    def critical_dimensions(self) -> list[RiskDimension]:
        """Dimensions scoring 'high' or 'critical'."""
        return [d for d in self.dimensions if d.severity in ("high", "critical")]
```

### Composite Score

The composite score is a **weighted maximum** — not an average, not a sum.

```python
DIMENSION_WEIGHTS = {
    "cycle":            1.0,   # cycles are always dangerous — hard ceiling
    "change_surface":   0.9,   # deletions and interface changes break builds
    "database":         0.8,   # shared mutable state = silent corruption risk
    "structural":       0.7,   # tight coupling = change amplification
    "blast_radius":     0.7,   # wide reach = wide breakage
    "instability":      0.6,   # unstable + depended-on = fragile
    "domain_boundary":  0.5,   # cross-team = coordination overhead
}

def compute_composite_score(profile: RiskProfile) -> float:
    """
    Weighted maximum across dimensions.

    Why max, not average: A target with one critical dimension and six safe
    dimensions is still high-risk. Averaging dilutes the signal.

    The weight determines how much each dimension CAN contribute to the
    composite, not how much it DOES contribute. A cycle (weight 1.0) at
    severity 0.9 contributes 0.9. Blast radius (weight 0.7) at severity
    1.0 contributes 0.7.

    composite = max(weight_i * score_i) for all dimensions
    """
    return max(
        DIMENSION_WEIGHTS[d.name] * d.score
        for d in profile.dimensions
    )
```

(Devon) "Weighted max is the right aggregation. Here's the intuition: if you're standing
in a room and one wall is on fire, it doesn't matter that the other three walls are fine.
The room is on fire. Averaging the walls tells you the room is 'slightly warm.' Max tells
you to get out."

(Priya) "The weights encode domain knowledge about which dimensions are more dangerous.
Cycles get 1.0 because they cause cascading failures. Domain boundaries get 0.5 because
they cause coordination overhead, not breakage. These are starting points — calibration
will tune them."

### Risk Level from Composite Score

```python
def composite_to_risk_level(score: float) -> RiskLevel:
    """
    RED:    composite >= 0.7
    YELLOW: composite >= 0.4
    GREEN:  composite < 0.4
    """
```

(Marcus) "Three levels. Not four, not five. RED means 'stop and think.' YELLOW means
'proceed with awareness.' GREEN means 'go.' If you need more granularity than that for a
PR comment, you're overthinking it. The dimensions provide the granularity."

---

## Computing Each Dimension

Each dimension is a pure function: graph data in, `RiskDimension` out. No AI, no I/O,
no side effects. All six can run in parallel (change_surface is PR-only, not in engine).

> **Decision #3 (Devon)**: All dimension functions use `score_*` naming.
> **Decision #2 (Devon)**: All scoring uses piecewise linear interpolation between
> threshold inflection points — no step functions. A project with fan-in 4.5 scores
> between the fan-in-3 and fan-in-5 thresholds, not a hard jump.
>
> **Decision #7 (Fatima)**: If the target has no metrics (not in graph), all dimensions
> return `RiskDimension(score=0.0, data_available=False, factors=["data_unavailable"])`.
> The engine never crashes the caller.

### 1. Structural Coupling

```python
def score_structural(
    target: str,
    metrics: Optional[ProjectMetrics],
    all_metrics: dict[str, ProjectMetrics],
) -> RiskDimension:
    """
    Piecewise linear scoring on fan_in:
      fan_in >= 10                → 1.0 (critical)
      fan_in 5–10                 → 0.7–1.0 (interpolated)
      fan_in 3–5                  → 0.4–0.7 (interpolated)
      fan_in 0–3                  → 0.1–0.4 (interpolated)

    Also considers: coupling_score percentile within the codebase.
    A project in the top 5% by coupling score gets a bump.

    If metrics is None: returns score=0.0, data_available=False.
    """
```

**Factors generated:**
- "Fan-in of {n} (top {p}% of codebase by coupling)"
- "Coupling score {s:.2f} — {n} weighted dependency edges"
- "Afferent coupling {a}, efferent coupling {e}"

### 2. Instability

```python
def score_instability(
    target: str,
    metrics: Optional[ProjectMetrics],
) -> RiskDimension:
    """
    Instability alone isn't dangerous. Instability + high fan-in is.

    Piecewise linear scoring (two inputs: instability × fan_in):
      instability >= 0.8 AND fan_in >= 3  → 0.9 (dangerous: unstable and depended on)
      instability 0.6–0.8 AND fan_in >= 3 → 0.5–0.9 (interpolated — Decision #2)
      instability >= 0.8 AND fan_in < 3   → 0.3 (unstable but leaf — acceptable)
      instability 0.5–0.6 AND fan_in >= 3 → 0.3–0.5 (moderate, interpolated)
      instability < 0.5                   → 0.1 (stable)

    If metrics is None: returns score=0.0, data_available=False.
    """
```

(Devon) "Pure instability is fine for leaf projects. A web app SHOULD have high instability
— it depends on things but nothing depends on it. The danger is when a highly-depended-on
project is also highly unstable. That's the 'fragile foundation' pattern."

**Factors generated:**
- "Instability {i:.2f} with fan-in {n} — fragile foundation pattern"
- "Instability {i:.2f} — unstable but low fan-in (acceptable for leaf projects)"

### 3. Cycle Entanglement

```python
def score_cycle(
    target: str,
    cycles: list[CycleGroup],
) -> RiskDimension:
    """
    Cycle membership is a hard risk signal. If you're in a cycle,
    any change can cascade back to you through the cycle.

    Scoring:
      in cycle of size >= 5         → 1.0 (critical — large cycle is systemic)
      in cycle of size 3-4          → 0.8 (high — tight coupling loop)
      in cycle of size 2            → 0.6 (medium — mutual dependency)
      not in any cycle              → 0.0 (safe)

    Multiple cycle membership multiplies: in 2+ cycles → cap at 1.0.
    """
```

**Factors generated:**
- "{target} is in a dependency cycle: {A} → {B} → {C} → {A}"
- "Cycle has {n} projects — changes can cascade back through {path}"
- "{target} is in {n} overlapping cycles — deeply entangled"

### 4. Database Coupling

```python
def score_database(
    target: str,
    graph: DependencyGraph,
    team_map: Optional[TeamMap],
) -> RiskDimension:
    """
    Shared stored procedures = shared mutable state = the coupling
    that doesn't show up in project references.

    Scoring:
      shared_db_density > 0.5 AND cross-team   → 1.0 (critical)
      shared_db_density > 0.3 OR cross-team     → 0.7 (high)
      any shared sprocs, same team              → 0.4 (medium)
      no shared sprocs                          → 0.0 (safe)
    """
```

**Factors generated:**
- "{n} stored procedures shared with {m} other projects"
- "Sprocs {names} are cross-team — changes require coordinated migration"
- "shared_db_density {d:.2f} — {p}% of sprocs are used by other projects"

### 5. Blast Radius

```python
def score_blast_radius(
    target: str,
    consumers: list[ConsumerResult],
    transitive_consumers: list[ConsumerResult],
) -> RiskDimension:
    """
    Consumer count and depth determine how far breakage propagates.

    Scoring:
      transitive >= 20              → 1.0 (critical — codebase-wide impact)
      transitive >= 10              → 0.7 (high)
      direct >= 5                   → 0.5 (medium)
      direct >= 2                   → 0.3 (low-medium)
      direct <= 1                   → 0.1 (contained)

    Depth matters: consumers at depth 2 are less actionable than depth 0.
    """
```

**Factors generated:**
- "{n} direct consumers, {m} transitive (depth {d})"
- "Blast radius reaches {n} projects — top {p}% widest in codebase"

### 6. Domain Boundary

```python
def score_domain_boundary(
    target: str,
    clusters: list[Cluster],
    consumers: list[ConsumerResult],
    team_map: Optional[TeamMap],
) -> RiskDimension:
    """
    Changes that cross domain/team boundaries require coordination.
    The risk isn't technical — it's organizational.

    Scoring:
      crosses 3+ clusters (or 3+ teams)  → 0.8 (high)
      crosses 2 clusters (or 2 teams)    → 0.5 (medium)
      crosses 1 cluster boundary         → 0.3 (low)
      stays within cluster               → 0.0 (safe)

    Team boundaries are weighted higher than domain clusters when
    team_map is available — organizational boundaries are harder to
    cross than code boundaries.
    """
```

**Factors generated:**
- "Change crosses {n} domain clusters"
- "Consumers span {n} teams: {team_names} — coordination required"
- "Consumer {name} is in cluster '{cluster}' — different domain from target"

### 7. Change Surface

```python
def score_change_surface(
    changed_types: list[ChangedType],
) -> RiskDimension:
    """
    What KIND of change matters as much as WHERE it changes.

    Severity order (highest to lowest):
      1. Interface deleted    → 1.0 (compile break for all implementors)
      2. Interface modified   → 0.8 (contract break for implementors)
      3. Class deleted        → 0.7 (compile break for all consumers)
      4. Class modified       → 0.4 (may break consumers, may not)
      5. Enum modified        → 0.3 (switch statements may miss new values)
      6. Class/enum added     → 0.1 (additive, low risk)

    Multiple changes: take the max severity across all changed types.
    """
```

(Fatima) "The interface-deleted case is the most dangerous change you can make to a
codebase. Every project that implements that interface will fail to compile. And unlike a
class deletion — where you get a clear 'type not found' error — interface changes can
cause subtle behavioral bugs when the contract changes but the code still compiles."

**Factors generated:**
- "Interface {name} deleted — {n} known implementors will fail to compile"
- "Interface {name} modified — contract change affects {n} implementors"
- "{name} deleted but has {n} active consumers"

---

## Risk Contexts

The same seven dimensions, weighted differently depending on who's asking.

```python
VALID_DIMENSION_NAMES = frozenset({
    "structural", "instability", "cycle",
    "database", "blast_radius", "domain_boundary",
    "change_surface",
})

@dataclass
class RiskContext:
    """Weighting profile for a specific risk analysis context."""
    name: str
    dimension_weights: dict[str, float]
    red_threshold: float
    yellow_threshold: float
    description: str

    def __post_init__(self):
        """Decision #9 (Fatima): fail fast at construction, not at scoring time."""
        if not self.name:
            raise ValueError("RiskContext.name must be non-empty")
        if self.yellow_threshold >= self.red_threshold:
            raise ValueError(
                f"yellow_threshold ({self.yellow_threshold}) must be < "
                f"red_threshold ({self.red_threshold})"
            )
        for dim, weight in self.dimension_weights.items():
            if dim not in VALID_DIMENSION_NAMES:
                raise ValueError(f"Unknown dimension '{dim}' in weights")
            if not 0.0 <= weight <= 1.0:
                raise ValueError(
                    f"Dimension weight '{dim}' is {weight}, must be in [0.0, 1.0]"
                )
```

### Three Contexts

```python
PR_RISK_CONTEXT = RiskContext(
    name="pr",
    dimension_weights={
        "cycle":            1.0,
        "change_surface":   0.9,   # deletions are build-breakers
        "database":         0.8,
        "structural":       0.7,
        "blast_radius":     0.7,
        "instability":      0.6,
        "domain_boundary":  0.5,
    },
    red_threshold=0.7,
    yellow_threshold=0.4,
    description="Will this merge break things?",
)

SOW_RISK_CONTEXT = RiskContext(
    name="sow",
    dimension_weights={
        "database":         1.0,   # DB migration is where SOWs blow up
        "domain_boundary":  0.9,   # cross-team = coordination overhead = schedule risk
        "cycle":            0.8,
        "blast_radius":     0.8,   # wide reach = wide effort
        "structural":       0.6,
        "instability":      0.5,
        "change_surface":   0.4,   # less relevant for planning (you haven't written code yet)
    },
    red_threshold=0.7,
    yellow_threshold=0.4,
    description="How risky is this body of work?",
)

LOCAL_DEV_CONTEXT = RiskContext(
    name="local",
    dimension_weights={
        "cycle":            1.0,
        "change_surface":   0.9,
        "blast_radius":     0.7,
        "structural":       0.7,
        "database":         0.6,
        "instability":      0.6,
        "domain_boundary":  0.3,   # less relevant for individual dev (they'll discover this at PR time)
    },
    red_threshold=0.7,
    yellow_threshold=0.4,
    description="Should I be worried about this change?",
)
```

(Priya) "The SOW context weights database highest because that's where estimates blow up.
You can estimate code changes. You can estimate testing. You cannot estimate a database
migration that crosses three teams until you've actually mapped the sproc surface. Scatter
does that mapping — the SOW context makes sure it screams about it."

(Marcus) "The PR context weights change_surface high because deletions and interface
changes are immediate, objective build risks. The SOW context weights it low because at
scoping time you haven't written code yet — you don't know if the change will be a
deletion or an addition."

### Custom Contexts

Teams can define custom contexts in `.scatter.yaml`:

```yaml
risk:
  contexts:
    migration:
      description: "Monolith decomposition risk assessment"
      dimension_weights:
        database: 1.0
        cycle: 1.0
        domain_boundary: 0.9
        blast_radius: 0.8
        structural: 0.7
        instability: 0.5
        change_surface: 0.3
      red_threshold: 0.6      # lower threshold — more sensitive
      yellow_threshold: 0.3
```

Used via `--risk-context migration`.

---

## Aggregate Risk

Individual targets get `RiskProfile`s. A PR or SOW needs an **aggregate** across all
targets.

```python
@dataclass
class AggregateRisk:
    """Risk summary across multiple targets (PR, SOW, or any multi-target analysis)."""

    # Per-target profiles
    profiles: list[RiskProfile]

    # Aggregate dimensions (max across all targets per dimension)
    structural: RiskDimension
    instability: RiskDimension
    cycle: RiskDimension
    database: RiskDimension
    blast_radius: RiskDimension
    domain_boundary: RiskDimension
    change_surface: RiskDimension

    # Aggregate score and level
    composite_score: float          # max composite across all targets
    risk_level: RiskLevel           # RED, YELLOW, GREEN
    risk_factors: list[str]         # top factors across all targets, deduplicated

    # Summary stats
    targets_at_red: int
    targets_at_yellow: int
    targets_at_green: int
    total_consumers: int            # sum across all targets (NOT deduplicated — see note below)
    total_transitive: int

    # Hotspots — the targets driving the risk
    hotspots: list[RiskProfile]     # profiles sorted by composite_score, descending
```

> **Note on `total_consumers`**: This is `sum(p.consumer_count for p in profiles)`,
> not a unique count. If two targets share consumers, those consumers are counted
> twice. Callers that need unique consumer counts must deduplicate before passing
> counts to `compute_risk_profile()`. The engine receives consumer counts as ints,
> not consumer name lists, so deduplication at aggregation time is not possible.
>
> `teams_affected` and `clusters_affected` were removed from `AggregateRisk` — the
> aggregate function only sees `RiskProfile`s and shouldn't re-derive team/cluster
> data. These are reporter concerns: the SOW scoping reporter and PR comment
> reporter compute these from their own context (team map, cluster assignments).

### Aggregation Logic

```python
def aggregate_risk(
    profiles: list[RiskProfile],
    context: RiskContext,
) -> AggregateRisk:
    """
    Aggregate rule: MAX across all targets, per dimension.

    Why max: same reasoning as composite score. If one target is in a cycle,
    the PR/SOW is cycle-involved. If one target has 20 transitive consumers,
    the blast radius is 20. Averaging hides the signal.

    Risk factors: collect all factors from all profiles, deduplicate,
    sort by dimension weight * score descending, take top 5.

    Decision #8 (Fatima): If profiles is empty, returns a GREEN aggregate
    with all dimensions at 0.0, composite_score=0.0, and empty hotspots.
    This happens when a PR modifies only non-C# files (zero changed types).
    Never raises ValueError from max() on empty sequence.
    """
```

(Devon) "Hotspots are the key output. The aggregate tells you 'this is red.' The hotspots
tell you 'it's red because of PortalDataService — everything else is green.' That's
actionable. The engineer knows exactly which target to focus on."

---

## AI Enrichment Layer

The graph-derived risk profile is the foundation. AI adds three things the graph can't:

### 1. Risk Narrative

**What the graph says:** "Cycle entanglement: 0.8, blast radius: 0.7, database: 0.6"

**What the AI says:** "This change touches PortalDataService, which sits at the center of
a 3-project dependency cycle. The cycle means that changes to PortalDataService can
cascade through GalaxyWorks.Api and back, requiring coordinated releases. The 4 shared
stored procedures add database migration risk — these sprocs are called by projects owned
by three different teams, so migration timing needs cross-team coordination."

The graph gives you the score. The AI tells you the story.

```python
RISK_NARRATIVE_PROMPT = """
You are explaining dependency risk to a software engineer reviewing a pull request
or scoping a work request.

## Target
{target_name} ({target_type})

## Risk Dimensions
{dimensions_table}

## Consumer Details
{consumer_summary}

## Cycle Details (if applicable)
{cycle_path}

## Shared Stored Procedures (if applicable)
{sproc_details}

## Instructions
Write 2-3 sentences explaining WHY this target is risky in plain English. Focus on
the dimensions with the highest scores. Explain the concrete consequences — what
could go wrong, not just that something could go wrong.

Do not repeat the scores. The engineer can see those. Explain what they mean for
THIS specific target in THIS specific codebase.
"""
```

### 2. Mitigation Suggestions

Per-dimension, the AI suggests concrete actions:

```python
MITIGATION_PROMPT = """
Given the following risk profile, suggest 2-4 concrete actions the engineer
can take to reduce risk. Focus on the highest-scoring dimensions.

{risk_profile_summary}

Each suggestion should be:
- Specific to this target (not generic advice)
- Actionable (something they can do in this PR or SOW)
- Ordered by impact (highest-impact first)

Examples of good suggestions:
- "Add integration tests for the GalaxyWorks.Api → PortalDataService path before merging"
- "Coordinate with BatchOps team before merging — their BatchProcessor calls 2 shared sprocs"
- "Consider splitting this PR: extract the interface change into a separate PR to isolate risk"
- "Run scatter --target-project GalaxyWorks.Data to verify all consumers before merging"
"""
```

### 3. Coupling Vector Scoring

The existing `coupling_narrative.py` produces coupling vectors like "Direct class
instantiation" and "Interface implementation." The risk engine should score these:

| Coupling Vector | Risk Weight | Rationale |
|----------------|-------------|-----------|
| Interface implementation | 1.0 | Contract dependency — changes break implementors |
| Base class inheritance | 0.9 | Tight structural coupling |
| Direct class instantiation | 0.7 | Hard dependency, but only at call site |
| Static method calls | 0.6 | Functional coupling |
| Enum usage | 0.4 | Usually switch/match — additive changes are safe |
| Namespace import only | 0.2 | May not use anything from it |

These scores feed back into the structural coupling dimension, replacing the generic
"coupling_score" with a more specific signal.

---

## Integration with PR Risk Scoring

The PR Risk Scoring doc (`PR_RISK_SCORING_PLAN.md`) currently defines its own risk logic.
With the unified engine, it becomes a consumer:

```python
# In pr_risk_analyzer.py (simplified)
def analyze_pr_risk(
    changed_files: list[Path],
    graph: DependencyGraph,
    metrics: dict[str, ProjectMetrics],
    cycles: list[CycleGroup],
    config: ScatterConfig,
) -> PRRiskReport:
    # 1. Extract changed types from diff
    changed_types = extract_changed_types(changed_files)

    # 2. Compute RiskProfile for each changed type
    profiles = []
    for ct in changed_types:
        consumer_names = find_consumer_names(ct.name, graph, config)
        profile = compute_risk_profile(
            target=ct.name,
            graph=graph,
            metrics=metrics,
            consumers=consumer_names,
            cycles=cycles,
            context=PR_RISK_CONTEXT,
            direct_consumer_count=len(consumer_names),
            transitive_consumer_count=count_transitive(ct.name, graph),
            team_map=config.team_map,
        )
        # PR analyzer populates change_surface (engine leaves it zeroed)
        profile.change_surface = score_change_surface([ct])
        profiles.append(profile)

    # 3. Aggregate across all targets
    aggregate = aggregate_risk(profiles, context=PR_RISK_CONTEXT)

    # 4. Build PR-specific report
    return PRRiskReport(
        changed_types=changed_types,
        risk_profiles=profiles,
        aggregate_risk=aggregate,
        ...
    )
```

The PR comment template consumes `AggregateRisk`:
- Header: `risk_level` + one-line summary
- Changed Types table: per-target `composite_score` and `critical_dimensions`
- Risk Factors: `aggregate.risk_factors` (top 5)
- Consumer Impact: from `aggregate.total_consumers` and `aggregate.total_transitive`
- Mitigations: `aggregate.mitigation_plan` (if AI available)

### What Changes in PR_RISK_SCORING_PLAN.md

- `TargetRisk` → replaced by `RiskProfile` (richer, multi-dimensional)
- `PRRiskReport.risk_level` → derived from `AggregateRisk.risk_level`
- `PRRiskReport.risk_factors` → derived from `AggregateRisk.risk_factors`
- Custom threshold config → replaced by `RiskContext` weights (more flexible)
- `RISK_FACTOR_TEMPLATES` → replaced by per-dimension factor generation (more systematic)

The PR comment format stays the same — it just has better data behind it.

---

## Integration with SOW Scoping

SOW Scoping gets the deepest risk integration because SOWs need risk data to drive
effort estimates.

```python
# In sow_scoping.py (simplified)
def scope_sow(
    sow_text: str,
    graph: DependencyGraph,
    metrics: dict[str, ProjectMetrics],
    cycles: list[CycleGroup],
    config: ScatterConfig,
) -> ScopingReport:
    # 1. Parse work request → targets
    targets = parse_work_request(sow_text, codebase_index)

    # 2. Compute RiskProfile for each target
    profiles = []
    for target in targets:
        consumer_names = find_consumer_names(target.name, graph, config)
        profile = compute_risk_profile(
            target=target.name,
            graph=graph,
            metrics=metrics,
            consumers=consumer_names,
            cycles=cycles,
            context=SOW_RISK_CONTEXT,
            direct_consumer_count=len(consumer_names),
            transitive_consumer_count=count_transitive(target.name, graph),
            team_map=config.team_map,
        )
        # change_surface stays zeroed — SOW doesn't have a diff
        profiles.append(profile)

    # 3. Aggregate risk
    aggregate = aggregate_risk(profiles, context=SOW_RISK_CONTEXT)

    # 4. Risk-informed effort estimation
    effort = estimate_effort(
        impact=impact_report,
        risk=aggregate,                 # risk dimensions drive multipliers
        ...
    )

    return ScopingReport(
        risk_profiles=profiles,
        aggregate_risk=aggregate,
        effort_breakdown=effort,
        ...
    )
```

### Risk-Driven Effort Multipliers

The effort estimator in `SOW_SCOPING_PLAN.md` defines multipliers for cycles, coupling,
and sprocs. With the unified risk engine, those multipliers come directly from the risk
dimensions:

```python
def risk_driven_multiplier(aggregate: AggregateRisk) -> dict[str, float]:
    """
    Map risk dimensions to effort multipliers.

    Each category of effort is influenced by specific dimensions:
    """
    return {
        "investigation": 1.0 + (aggregate.domain_boundary.score * 0.5)
                             + (aggregate.cycle.score * 0.5),
        "implementation": 1.0 + (aggregate.structural.score * 0.3)
                              + (aggregate.cycle.score * 0.5),
        "testing": 1.0 + (aggregate.database.score * 0.5)
                       + (aggregate.instability.score * 0.3),
        "integration_risk": 1.0 + (aggregate.cycle.score * 0.5)
                                + (aggregate.domain_boundary.score * 0.5)
                                + (aggregate.database.score * 0.3),
        "database_migration": 1.0 + (aggregate.database.score * 1.0),
    }
```

This is cleaner than the hard-coded multipliers in the SOW doc because:
1. The multipliers are derived from measured risk, not assumed risk
2. They're tunable by adjusting dimension weights, not rewriting heuristics
3. They work for any codebase topology, not just the one we tested against

### SOW Risk Report Section

The SOW scoping output includes a full risk breakdown that the PR comment collapses:

```
RISK ANALYSIS
═══════════════════════════════════════════════════════════

  Composite Risk: HIGH (0.78)

  ┌─────────────────────┬───────┬──────────┬────────────────────────────────────┐
  │ Dimension           │ Score │ Severity │ Top Factor                         │
  ├─────────────────────┼───────┼──────────┼────────────────────────────────────┤
  │ Database coupling   │  0.85 │ critical │ 4 sprocs shared across 3 teams     │
  │ Cycle entanglement  │  0.80 │ high     │ Data ↔ Api ↔ Core (3 projects)    │
  │ Blast radius        │  0.70 │ high     │ 14 transitive consumers (depth 2)  │
  │ Domain boundary     │  0.50 │ medium   │ Crosses 2 domain clusters          │
  │ Structural coupling │  0.45 │ medium   │ Fan-in of 8 (top 5% of codebase)  │
  │ Instability         │  0.30 │ low      │ Instability 0.35 — moderately stable│
  │ Change surface      │  n/a  │ n/a      │ (no diff available for SOW)        │
  └─────────────────────┴───────┴──────────┴────────────────────────────────────┘

  Risk Hotspots:
    1. PortalDataService    — composite 0.78 (cycle, database, blast radius)
    2. TenantContext         — composite 0.52 (structural, domain boundary)
    3. IPortalRepository     — composite 0.41 (structural)

  Mitigation Recommendations:
    1. Map sproc migration order before starting implementation — 4 sprocs
       need coordinated migration across Platform, BatchOps, and Portal teams
    2. Break the Data ↔ Api cycle before modifying PortalDataService to prevent
       cascading build failures
    3. Engage Platform team early — they own GalaxyWorks.Api (direct consumer,
       in cycle with target)
```

This level of detail is what makes SOW scoping defensible. Finance doesn't just see
"High Risk" — they see *which* dimensions are high, *why*, and *what to do about it*.

---

## The RiskEngine Module

All risk computation lives in one module with a clean API.

### Module Structure

```
scatter/core/risk_models.py            # RiskProfile, RiskDimension, AggregateRisk, RiskContext, RiskLevel
scatter/analyzers/risk_engine.py       # Core: compute_risk_profile, aggregate_risk, format_risk_factors
scatter/analyzers/risk_dimensions.py   # Six score_* dimension assessors
scatter/ai/tasks/risk_narrative.py     # AI: narrative, mitigations (Phase 2+ — replaces risk_assess.py role)
```

### Public API

```python
# The three functions the rest of Scatter calls:

def compute_risk_profile(
    target: str,
    graph: DependencyGraph,
    metrics: dict[str, ProjectMetrics],   # pre-computed, never fetched internally (Devon)
    consumers: list[str],                 # consumer project names
    cycles: list[CycleGroup],
    context: RiskContext,
    direct_consumer_count: int = 0,       # caller pre-counts (not derived from consumers list)
    transitive_consumer_count: int = 0,
    consumer_cluster_ids: Optional[list[str]] = None,   # for domain_boundary scoring
    target_cluster_id: Optional[str] = None,
    team_map: Optional[dict[str, str]] = None,          # project → team name
) -> RiskProfile:
    """
    Compute full risk profile for a single target.

    Scores 6 graph-derived dimensions. change_surface is always zeroed —
    it's a PR-only modifier populated by pr_risk_analyzer, not the engine.

    Decision #7 (Fatima): if target is not in graph or metrics,
    returns a GREEN profile with all dimensions at 0.0 and
    data_available=False. Never raises.

    Decision #5 (Marcus): logs dimension scores at DEBUG,
    composite result at INFO, wall-clock timing always.
    """

def aggregate_risk(
    profiles: list[RiskProfile],
    context: RiskContext,
) -> AggregateRisk:
    """
    Aggregate risk across multiple targets.

    Decision #8 (Fatima): empty list → GREEN aggregate, all zeros.

    Note: total_consumers is sum(p.consumer_count), not deduplicated.
    Callers that need unique consumer counts across targets must
    deduplicate before passing counts to compute_risk_profile().
    """

def format_risk_factors(
    profile_or_aggregate: Union[RiskProfile, AggregateRisk],
    top_n: int = 5,
) -> list[str]:
    """Extract and sort human-readable risk factors."""
```

(Priya) "Three functions. That's the public API. Everything else is internal. If you
need more than three functions to consume risk, the engine is too complicated."

> **Note on inputs (Devon)**: `metrics` and `cycles` are required parameters, not
> fetched internally. The engine is a pure function — data in, score out, no I/O.
> The caller (mode handler) is responsible for running `compute_all_metrics` and
> `detect_cycles` before invoking the engine. This keeps the engine testable without
> a graph or filesystem.
>
> **Note on consumer counts**: `consumers` is a list of project names (for cycle
> membership checks and domain boundary scoring). `direct_consumer_count` and
> `transitive_consumer_count` are pre-computed ints for blast_radius scoring. The
> engine does not derive counts from the `consumers` list — the caller owns that
> arithmetic.

### Backward Compatibility

The existing `risk_assess.py` AI task still works — it just gets richer input. The
`EnrichedConsumer.risk_rating` field is populated from `RiskProfile.risk_level` instead
of the AI-only assessment. If AI is unavailable, the graph-derived risk level fills in.

This means existing `--sow` runs without `--scope-estimate` still work identically.
The risk engine is additive, not breaking.

---

## Testing Strategy

### Unit Tests (per-dimension)

Each dimension scorer gets its own test suite. Naming follows `score_*` convention
(Decision #3):

```python
class TestScoreStructural:
    def test_high_fan_in_returns_critical(self): ...
    def test_low_fan_in_returns_low(self): ...
    def test_interpolation_between_thresholds(self): ...      # Decision #2
    def test_no_cliff_at_boundary(self): ...                  # Decision #2
    def test_none_metrics_returns_data_unavailable(self): ... # Decision #7

class TestScoreCycle:
    def test_not_in_cycle_returns_zero(self): ...
    def test_two_project_cycle_returns_medium(self): ...
    def test_large_cycle_returns_critical(self): ...
    def test_multiple_cycles_caps_at_one(self): ...

class TestScoreDatabase:
    def test_no_shared_sprocs_returns_zero(self): ...
    def test_cross_team_sprocs_returns_high(self): ...
    def test_same_team_sprocs_returns_medium(self): ...

# ... same pattern for all 6 dimensions
```

### Piecewise Linear Interpolation Tests (Decision #2)

```python
def test_fan_in_interpolation_midpoint():
    """fan_in=4 (midpoint of 3–5 range) scores ~0.55 (midpoint of 0.4–0.7)."""

def test_instability_no_cliff_at_08():
    """instability 0.79 and 0.81 produce scores within 0.05 of each other."""

def test_score_monotonically_increasing():
    """For each dimension, higher input always produces >= score."""
```

### Data Availability Tests (Decision #4, #7)

```python
def test_unknown_target_returns_safe_profile():
    """Target not in graph → GREEN, all dimensions 0.0, data_available=False."""

def test_data_unavailable_dimension_has_factor():
    """Dimension with data_available=False includes 'data_unavailable' factor."""

def test_data_unavailable_not_counted_as_safe():
    """Reporters can distinguish 0.0+data_available from 0.0+data_unavailable."""
```

### Edge Case Tests (Decision #8, #9)

```python
def test_aggregate_empty_profiles_returns_green():
    """aggregate_risk([]) → GREEN, composite 0.0, empty hotspots. No ValueError."""

def test_risk_context_invalid_weight_raises():
    """Weight of 1.5 → ValueError with message naming the dimension."""

def test_risk_context_yellow_gte_red_raises():
    """yellow_threshold >= red_threshold → ValueError."""

def test_risk_context_unknown_dimension_raises():
    """Misspelled dimension key → ValueError."""
```

### Property Tests (aggregation invariants)

```python
def test_aggregate_risk_level_never_lower_than_max_target():
    """If any target is RED, aggregate must be RED."""

def test_composite_score_bounded_zero_to_one():
    """Composite score is always in [0.0, 1.0]."""

def test_risk_factors_are_unique():
    """No duplicate factors in the output list."""

def test_dimensions_sum_to_profile():
    """Every dimension in profile.dimensions is accessible by name."""

def test_weighted_max_not_average():
    """Decision #2 proof: 6 dimensions at 0.0 + 1 cycle at 0.9 → composite 0.9."""
```

### Performance Tests (Decision #6)

```python
def test_risk_engine_under_100ms():
    """
    Full risk profile computation for all 13 sample projects
    completes in under 100ms. This is pure in-memory computation —
    if it regresses, the test fails.
    """
```

### Integration Tests

```python
def test_portal_data_service_risk_profile():
    """
    GalaxyWorks.Data/PortalDataService is known to be in a cycle,
    have shared sprocs, and high fan-in. Verify the risk profile
    reflects all three dimensions.
    """

def test_leaf_project_low_risk():
    """
    A project with no consumers, no cycles, no shared sprocs
    should have composite score < 0.2 (GREEN).
    """

def test_pr_context_vs_sow_context():
    """
    Same target analyzed with PR_RISK_CONTEXT and SOW_RISK_CONTEXT
    may produce different risk levels due to different weights.
    """

def test_risk_models_import_stdlib_only():
    """
    `scatter.core.risk_models` imports only stdlib types.
    No external dependencies that could break existing model imports.
    """
```

### Regression Safety Net (Decision #10)

```python
def test_existing_sow_mode_unchanged():
    """
    Run --sow against sample projects and snapshot the output.
    Must be byte-identical before and after the risk engine lands.
    This proves 'purely additive' means purely additive.
    """
```

### AI Enrichment Tests (Phase 2+)

```python
def test_risk_narrative_without_ai():
    """Profile is complete without AI — narrative fields are None."""

def test_risk_narrative_with_mock_ai():
    """AI adds narrative and mitigations without changing scores."""

def test_ai_failure_graceful():
    """AI exception doesn't affect graph-derived risk profile."""
```

---

## Migration Path

### Phase 1: Build the Engine ✅ COMPLETED (2026-04-01, PR #15)

**Scope**: New modules only. Zero modifications to existing code paths. No CLI changes,
no mode changes, no reporter changes. Existing `--sow`, `--branch-name`, `--graph` modes
work identically before and after.

**New files:**
- `scatter/core/risk_models.py` — all risk dataclasses (Decision #1: separate from `models.py`)
- `scatter/analyzers/risk_engine.py` — public API: `compute_risk_profile`, `aggregate_risk`, `format_risk_factors`
- `scatter/analyzers/risk_dimensions.py` — six `score_*` functions (Decision #3)
- `tests/unit/test_risk_engine.py` — aggregation, composite scoring, edge cases
- `tests/unit/test_risk_dimensions.py` — per-dimension scoring, interpolation, data availability

**Design constraints (from team review):**
- **6 graph-derived dimensions**: structural, instability, cycle, database, blast_radius, domain_boundary
- `change_surface` is a field on `RiskProfile` and `AggregateRisk` (so the data model is always 7-dimensional), but the engine always defaults it to a zeroed dimension. The PR risk analyzer is responsible for populating it — it requires diff data the engine doesn't have
- **Piecewise linear scoring** (Decision #2): smooth interpolation between thresholds, no cliffs at boundaries
- **`score_*` naming** (Decision #3): `score_structural`, `score_instability`, `score_cycle`, `score_database`, `score_blast_radius`, `score_domain_boundary`
- **`data_available` on RiskDimension** (Decision #4): distinguishes "safe" from "unknown"
- **Structured logging** (Decision #5): `DEBUG` for per-dimension scores, `INFO` for composite result, standard `logging` module
- **Pure functions** (Devon): `metrics` and `cycles` are required parameters passed in by caller, never fetched internally — no I/O in the engine
- **Graceful on unknown target** (Decision #7): returns zeroed profile with `data_available=False`
- **Graceful on empty profiles** (Decision #8): `aggregate_risk([])` returns GREEN aggregate
- **`RiskContext.__post_init__` validation** (Decision #9): fail-fast with specific error messages
- **Performance budget** (Decision #6): full sample graph (13 projects) in <100ms
- **Regression safety net** (Decision #10): snapshot test proving `--sow` output is byte-identical before and after
- **stdlib-only imports** in `risk_models.py` (Fatima): `dataclass`, `Optional`, `Path`, `Enum` — no external deps that could break existing `models.py` importers

### Phase 2: Wire into Impact Analysis (1 week)

**Goal**: Existing `--sow` mode gains graph-derived risk scoring. The current AI-only
risk rating (from `risk_assess.py`) becomes a fallback when graph context is unavailable.
When graph context IS available, the risk engine provides a deterministic, reproducible
risk level that the AI then enriches with narrative.

**How it works today** (Step 3 of `impact_analyzer.py`, lines 170-181):
```python
# Current: AI-only risk per target
for target_impact in report.targets:
    risk_result = assess_risk(target, consumers, ai_provider)
    for consumer in target_impact.consumers:
        consumer.risk_rating = risk_result.get("rating")     # "Low"|"Medium"|"High"|"Critical"
        consumer.risk_justification = risk_result.get("justification")
```

**How it will work** (graph-derived first, AI optional enrichment):
```python
# New: graph-derived risk per target, AI adds narrative
from scatter.analyzers.risk_engine import compute_risk_profile
from scatter.core.risk_models import SOW_RISK_CONTEXT

for target_impact in report.targets:
    consumers = target_impact.consumers

    # Graph-derived risk (deterministic, no AI needed)
    if graph_ctx is not None:
        profile = compute_risk_profile(
            target=target_impact.target.name,
            graph=graph_ctx.graph,
            metrics=graph_ctx.metrics,
            consumers=[c.consumer_name for c in consumers],
            cycles=graph_ctx.cycles,
            context=SOW_RISK_CONTEXT,
            direct_consumer_count=target_impact.total_direct,
            transitive_consumer_count=target_impact.total_transitive,
        )
        # Map RiskLevel.RED → "High", etc.
        risk_label = _risk_level_to_label(profile.risk_level)
        for consumer in consumers:
            if consumer.risk_rating is None:
                consumer.risk_rating = risk_label
                consumer.risk_justification = "; ".join(profile.risk_factors[:3])

    # AI enrichment (optional — enhances graph-derived result)
    risk_result = assess_risk(target_impact.target, consumers, ai_provider)
    if risk_result:
        for consumer in consumers:
            # AI can override rating or add justification
            if consumer.risk_rating is None:
                consumer.risk_rating = risk_result.get("rating")
            if consumer.risk_justification is None:
                consumer.risk_justification = risk_result.get("justification")
```

**Key design point**: Graph-derived risk fills in first. AI enrichment adds narrative
where the graph can't (business context, code intent). If AI is unavailable, the
graph-derived risk stands alone — this is the upgrade over the current AI-only path.

#### Deliverables

**2.1 Modify `scatter/analyzers/impact_analyzer.py`**
- Add `graph_ctx` parameter to `run_impact_analysis()` (already has `graph=None`)
- In Step 3, compute `RiskProfile` per target when `graph_ctx` is available
- Map `RiskLevel` → existing label strings ("Low"/"Medium"/"High"/"Critical")
- Existing AI risk assessment becomes fallback/enrichment, not primary
- `ImpactReport.overall_risk` derived from max `RiskProfile.risk_level`

**2.2 Modify `scatter/analyzers/graph_enrichment.py`**
- Add `risk_profiles: Dict[str, RiskProfile]` to `GraphContext` (optional, computed lazily)
- No changes to existing `enrich_legacy_results()` or `enrich_consumers()` — they
  continue enriching with coupling metrics, separate from risk scoring

**2.3 Modify `scatter/modes/impact.py`**
- Pass `graph_ctx` through to `run_impact_analysis()` (it's already available in mode context)

**2.4 Helper function**
```python
def _risk_level_to_label(level: RiskLevel) -> str:
    """Map graph-derived RiskLevel to existing AI-compatible label."""
    return {
        RiskLevel.RED: "High",
        RiskLevel.YELLOW: "Medium",
        RiskLevel.GREEN: "Low",
    }[level]
```

**2.5 Tests**
- `tests/unit/test_impact_risk_integration.py`:
  - `test_sow_with_graph_uses_risk_engine`: graph available → risk_rating from engine
  - `test_sow_without_graph_uses_ai_only`: no graph → falls back to AI assess_risk
  - `test_sow_with_graph_and_ai_enriches`: graph fills rating, AI adds justification
  - `test_risk_level_to_label_mapping`: RED→High, YELLOW→Medium, GREEN→Low
  - `test_overall_risk_derived_from_profiles`: max of per-target RiskLevel
  - `test_backward_compat_sow_output_structure`: JSON schema unchanged

**2.6 Backward compatibility**
- `EnrichedConsumer` fields unchanged — same `risk_rating` and `risk_justification` strings
- `ImpactReport` fields unchanged — same `overall_risk` string
- JSON output schema unchanged — consumers still have `risk_rating` as a string
- Only difference: risk_rating populated even without AI (was None without AI before)

### Phase 3: Expose via CLI (1 week)

**Goal**: Users can see risk dimension breakdowns in console output and control
risk context via CLI flags.

#### Deliverables

**3.1 CLI flags** (`scatter/cli_parser.py`)
- `--risk-context {pr,sow,local}` — selects dimension weight profile (default: auto-detect from mode)
- `--risk-details` — shows full dimension breakdown in console/JSON output
- `--risk-only` — shows just the composite score and top factors (no consumer table)

**3.2 Console risk output** (`scatter/reports/console_reporter.py`)

When `--risk-details` is used with any mode that has graph context:

```
Risk Profile: GalaxyWorks.Data
══════════════════════════════════════════════════════════════
  Composite: 0.78 (RED)

  Dimension            Score  Severity  Top Factor
  ─────────────────── ────── ───────── ──────────────────────────────────
  Cycle entanglement    0.80  high      Data ↔ Api ↔ Core (3 projects)
  Blast radius          0.70  high      8 direct, 12 transitive
  Structural coupling   0.55  medium    Fan-in of 5 (top 10% of codebase)
  Database coupling     0.40  medium    2 shared sprocs
  Instability           0.30  medium    Instability 0.70 with fan-in 5
  Domain boundary       0.20  low       Crosses 1 domain cluster
```

**3.3 JSON risk output** (`scatter/reports/json_reporter.py`)

When `--risk-details` is used, JSON output includes:
```json
{
  "risk_profile": {
    "target_name": "GalaxyWorks.Data",
    "composite_score": 0.78,
    "risk_level": "RED",
    "risk_factors": ["..."],
    "dimensions": {
      "structural": {"score": 0.55, "severity": "medium", "data_available": true, "factors": ["..."]},
      "cycle": {"score": 0.80, "severity": "high", "data_available": true, "factors": ["..."]},
      ...
    }
  }
}
```

**3.4 Config integration** (`scatter/config.py`)
- Add `RiskConfig` dataclass:
  ```python
  @dataclass
  class RiskConfig:
      default_context: str = "auto"      # "auto" | "pr" | "sow" | "local"
      show_details: bool = False          # --risk-details default
      red_threshold: Optional[float] = None   # override built-in contexts
      yellow_threshold: Optional[float] = None
  ```
- Wire into `ScatterConfig`
- Support `.scatter.yaml` `risk:` section

**3.5 Auto-detect risk context**
- `--sow` mode → `SOW_RISK_CONTEXT`
- `--branch-name` or `--pr-risk` → `PR_RISK_CONTEXT`
- `--target-project`, `--graph` → `LOCAL_DEV_CONTEXT`
- `--risk-context` flag overrides auto-detection

**3.6 Tests**
- `tests/unit/test_risk_cli.py`:
  - `test_risk_context_auto_detection`: each mode maps to correct context
  - `test_risk_context_flag_override`: `--risk-context sow` with `--target-project`
  - `test_risk_details_console_output`: snapshot test of dimension table
  - `test_risk_details_json_output`: verify schema with dimensions object
  - `test_risk_only_output`: only composite + factors, no consumer table
  - `test_risk_config_from_scatter_yaml`: custom thresholds loaded

### Integration with PR Risk Scoring and SOW Scoping
- **PR Risk Scoring Phase 1** depends on **Risk Engine Phase 1 only**
  (PR Risk calls `compute_risk_profile` and `aggregate_risk` directly —
  it does NOT need the impact analysis wiring from Phase 2)
- **SOW Scoping Phase 1** depends on **Risk Engine Phase 1–2**
  (SOW Scoping builds on the impact analysis pipeline, which Phase 2 enriches)
- **SOW Scoping Phase 2+** benefits from **Risk Engine Phase 3** (CLI flags,
  risk config) but does not strictly require it

### Deferred (post-calibration / post-adoption)
- **Dimension correlation analysis**: once we have enough real profiles, check whether any dimensions are redundant (always move together). Not worth analyzing without production data.
- **Coupling vector scoring**: weight the structural dimension by coupling vector type (interface impl = 1.0, namespace import = 0.2). Adds precision but adds complexity — defer until structural dimension proves too coarse.
- **Custom risk contexts**: let teams define their own weight profiles in `.scatter.yaml`. The three built-in contexts (PR, SOW, local) cover the launch. Custom contexts are a v2 feature.
- **Dict-based dimension storage**: `RiskProfile` uses named fields (`self.structural`, `self.cycle`, etc.) — clean for 6 dimensions with autocomplete and type checking (Priya). Switch threshold: 10+ dimensions. Not needed now.

---

## What This Means for Athena

The risk engine is the intellectual core of Scatter's value proposition. Consumer detection
tells you *what's connected*. The risk engine tells you *what's dangerous*.

Every feature Scatter builds from here — PR comments, SOW scoping, migration planning,
architecture health dashboards — needs risk data. Building it once, as a unified engine
with a clean three-function API, means every future feature gets risk for free.

(Priya) "The risk engine is the thing that makes Scatter more than a dependency lister.
Any tool can find consumers. Scatter tells you which consumers to worry about, why, and
what to do about it. That's the differentiator."

---

## Files Summary

### Phase 1 (purely additive — no existing files modified)

| File | Action | Purpose |
|------|--------|---------|
| `scatter/core/risk_models.py` | **Create** | `RiskDimension`, `RiskProfile`, `AggregateRisk`, `RiskContext`, `RiskLevel` (Decision #1) |
| `scatter/analyzers/risk_engine.py` | **Create** | Public API: `compute_risk_profile`, `aggregate_risk`, `format_risk_factors` |
| `scatter/analyzers/risk_dimensions.py` | **Create** | Six `score_*` dimension functions (Decision #3) |
| `tests/unit/test_risk_engine.py` | **Create** | Aggregation, composite scoring, edge cases, performance |
| `tests/unit/test_risk_dimensions.py` | **Create** | Per-dimension scoring, interpolation, data availability |

### Phase 2 (wire into impact analysis)

| File | Action | Purpose |
|------|--------|---------|
| `scatter/analyzers/impact_analyzer.py` | Modify | Compute `RiskProfile` per target in Step 3, graph-derived first, AI fallback |
| `scatter/analyzers/graph_enrichment.py` | Modify | Add optional `risk_profiles` to `GraphContext` |
| `scatter/modes/impact.py` | Modify | Pass `graph_ctx` through to `run_impact_analysis()` |
| `tests/unit/test_impact_risk_integration.py` | Create | Graph+AI risk integration, backward compat |

### Phase 3 (expose via CLI)

| File | Action | Purpose |
|------|--------|---------|
| `scatter/config.py` | Modify | Add `RiskConfig` dataclass with context + threshold defaults |
| `scatter/cli_parser.py` | Modify | Add `--risk-context`, `--risk-details`, `--risk-only` flags |
| `scatter/reports/console_reporter.py` | Modify | Risk dimension table for `--risk-details` |
| `scatter/reports/json_reporter.py` | Modify | Risk dimension object in JSON output |
| `tests/unit/test_risk_cli.py` | Create | Context auto-detection, CLI flags, output snapshots |
