# PR Risk Scoring — Change Risk on Every Pull Request

**Initiative**: PR Risk Integration
**Target branch**: `feature/pr-risk-scoring`
**Effort estimate**: 4–6 weeks across 4 phases (Phase 4 deferred until prediction data exists)
**Dependencies**: Risk Engine Phase 1 (`RISK_ENGINE_PLAN.md` — ✅ SHIPPED), graph engine (done), coupling analyzer (done), GitHub Actions (CI plan exists)
**Blockers**: GitHub API access for PR commenting, repo-level Actions permissions
**Related docs**: `RISK_ENGINE_PLAN.md` (unified risk model), `SOW_SCOPING_PLAN.md` (shared infrastructure)

---

## The Problem We're Solving

Here's what happens today: an engineer writes code, opens a PR, gets it reviewed, and
merges it. Somewhere downstream, a build breaks. Someone spends half a day figuring out
that the merge touched a class consumed by 14 projects across 3 teams, and nobody checked
because nobody knew to check.

Scatter already knows the answer. It can trace every consumer, compute coupling scores,
detect cycles, flag shared sprocs. But it only works if someone *thinks to run it*. That's
the gap. The tool exists. The adoption doesn't.

The real question was never "can Scatter tell me the risk?" It was always "does every
engineer see the risk before they click Merge?"

## What We're Building

A GitHub Action that runs Scatter on every PR and drops a risk comment. No opt-in, no CLI
knowledge, no Scatter installation. Engineer opens a PR, and within 90 seconds there's a
comment:

```
🔴 HIGH RISK — 14 consumers affected across 3 teams

Changed: GalaxyWorks.Data (PortalDataService, TenantContext)

Direct consumers (4):
  GalaxyWorks.Api          — coupling: 0.82, in cycle ⚠️
  GalaxyWorks.WebPortal    — coupling: 0.71
  GalaxyWorks.BatchProcessor — coupling: 0.45, shared sprocs ⚠️
  MyGalaxyConsumerApp      — coupling: 0.31

Transitive consumers (10): GalaxyWorks.Api → 6 downstream, GalaxyWorks.WebPortal → 4 downstream

Filter: 250[graph] → 4 project refs → 4 namespace → 3 class match

Risk factors:
  - PortalDataService is in a dependency cycle (GalaxyWorks.Data ↔ GalaxyWorks.Api)
  - 2 shared stored procedures (dbo.sp_InsertPortalConfiguration, dbo.sp_GetTenantConfig)
  - Fan-in of 4 (top 5% of codebase by coupling score)
```

That comment is Scatter's distribution mechanism. It's how we go from "Athena's side
project" to "division infrastructure." Nobody needs to install anything. Nobody needs to
know what a coupling score is. The comment shows up, and either it's green and you move on,
or it's red and you think twice. That's the whole product.

---

## What's Already Built

Most of the hard work is done. We're not inventing new algorithms here — we're composing
existing modules and putting them behind a GitHub Action. Plumbing, not science.

| Capability | Status | Module |
|-----------|--------|--------|
| Git branch diff analysis | Done | `git_analyzer.py` |
| Type declaration extraction from diffs | Done | `type_scanner.py` |
| Consumer detection (5-stage pipeline) | Done | `consumer_analyzer.py` |
| Graph-accelerated consumer lookup | Done | `consumer_analyzer.py` + `graph.py` |
| Coupling metrics (fan-in, instability) | Done | `coupling_analyzer.py` |
| Cycle detection (Tarjan's SCC) | Done | `coupling_analyzer.py` |
| Shared sproc detection | Done | `sproc_scanner.py` + `db_scanner.py` |
| AI risk assessment per target | Done | `ai/tasks/risk_assess.py` |
| AI coupling narrative | Done | `ai/tasks/coupling_narrative.py` |
| JSON/Markdown output | Done | `reports/json_reporter.py`, `reports/markdown_reporter.py` |
| Graph caching + incremental patching | Done | `store/graph_cache.py`, `store/graph_patcher.py` |

### What's Missing

| Gap | Difficulty | Notes |
|-----|-----------|-------|
| Aggregate risk scoring (PR-level, not target-level) | Medium | Need to combine per-target risk into single PR signal |
| GitHub Actions workflow | Low | Standard YAML, Scatter runs as CLI |
| PR comment formatter | Medium | Markdown template, needs to be scannable in 5 seconds |
| Risk signal thresholds (red/yellow/green) | Medium | Configurable, needs sensible defaults |
| Performance budget (<90s wall clock) | Medium | Graph cache is key — cold builds too slow for PR feedback |
| Historical tracking (predicted vs actual) | Hard | Phase 3 — needs incident/regression data to calibrate |

None of these are research problems. The unknowns are operational (will CI cache hit
rates hold? will the AI enrichment stay under budget?) not algorithmic. The math is
already proven.

---

## Architecture

### Data Flow

The whole thing is a straight pipeline. No branching, no async fan-out, no cleverness.
Diff in, comment out.

```
PR opened/updated
  → GitHub Action triggers
  → Checkout PR branch + base branch
  → Load or build graph (cached in Actions artifact)
  → Git diff: extract changed files
  → Type extraction: identify changed types/classes
  → For each changed type:
      → Consumer detection (graph-accelerated stages 1–2)
      → Coupling metrics lookup
      → Cycle membership check
      → Shared sproc check
  → Aggregate risk score across all targets
  → Format PR comment (markdown)
  → Post/update comment via GitHub API
```

### The Risk Score

The unified risk engine (`RISK_ENGINE_PLAN.md`) computes multi-dimensional risk profiles
for each changed type and aggregates them into a single PR-level signal. The PR risk
analyzer doesn't compute risk. It figures out *what changed*, hands it to the engine, and
wraps the result. Three jobs: diff extraction, engine invocation, report assembly.

```python
@dataclass
class PRRiskReport:
    """Aggregate risk assessment for a pull request."""

    # Identity
    pr_number: int
    branch_name: str
    base_branch: str

    # What changed
    changed_files: list[Path]
    changed_types: list[ChangedType]

    # Risk (from unified risk engine)
    risk_profiles: list[RiskProfile]   # per-target, 7-dimension profiles
    aggregate_risk: AggregateRisk      # aggregated across all targets
    risk_context: RiskContext           # PR_RISK_CONTEXT

    # Impact (derived from risk profiles)
    total_direct_consumers: int
    total_transitive_consumers: int
    unique_consumers: set[str]       # deduplicated across targets

    # Convenience accessors (delegate to aggregate_risk)
    @property
    def risk_level(self) -> RiskLevel:
        return self.aggregate_risk.risk_level

    @property
    def risk_factors(self) -> list[str]:
        return self.aggregate_risk.risk_factors

    @property
    def hotspots(self) -> list[RiskProfile]:
        return self.aggregate_risk.hotspots

    # Metadata
    filter_pipeline: FilterPipeline
    graph_hit: bool                  # true if graph cache was used
    duration_ms: int

@dataclass
class ChangedType:
    """A type declaration modified in this PR."""
    name: str
    file_path: Path
    change_kind: str                 # "modified", "added", "deleted", "renamed"
    declaration_type: str            # "class", "interface", "enum", "struct"
```

No `TargetRisk` dataclass. That's gone. `RiskProfile` from the risk engine replaces it —
7 dimensions instead of flat coupling/instability fields, and it's shared across PR risk,
SOW scoping, and local dev. One risk model, used everywhere.

### How the PR Risk Analyzer Calls the Risk Engine

```python
# In pr_risk_analyzer.py
def analyze_pr_risk(
    changed_files: list[Path],
    graph: DependencyGraph,
    metrics: dict[str, ProjectMetrics],
    cycles: list[CycleGroup],
    config: ScatterConfig,
) -> PRRiskReport:
    # 1. Extract changed types from diff
    changed_types = extract_changed_types(changed_files)

    # 2. Compute RiskProfile for each changed type (from risk engine)
    profiles = []
    for ct in changed_types:
        consumer_names = find_consumer_names(ct.name, graph, config)
        profile = compute_risk_profile(
            target=ct.name,
            graph=graph,
            metrics=metrics,
            consumers=consumer_names,
            cycles=cycles,
            context=PR_RISK_CONTEXT,         # PR-specific weights
            direct_consumer_count=len(consumer_names),
            transitive_consumer_count=count_transitive(ct.name, graph),
            team_map=config.team_map,
        )
        # PR analyzer populates change_surface (engine leaves it zeroed)
        profile.change_surface = score_change_surface([ct])
        profiles.append(profile)

    # 3. Aggregate across all targets (from risk engine)
    aggregate = aggregate_risk(profiles, context=PR_RISK_CONTEXT)

    return PRRiskReport(
        changed_types=changed_types,
        risk_profiles=profiles,
        aggregate_risk=aggregate,
        ...
    )
```

> "The PR risk analyzer doesn't compute risk. It figures out what changed, asks the engine
> to score it, and assembles the report. Three steps, no risk logic."

### Developer CLI Usage

Same engine, same output, whether you're running locally or in CI. The only difference:
CI posts it as a PR comment; locally it prints to stdout. You can preview exactly what the
bot will say before you push.

```bash
# Full risk analysis for current branch
scatter --pr-risk --branch-name feature/tenant-isolation --base-branch main

# Quick check — console output, no AI
scatter --pr-risk --branch-name feature/tenant-isolation --risk-details

# JSON output for scripting
scatter --pr-risk --branch-name feature/tenant-isolation --output-format json

# Custom risk context (e.g., migration-specific thresholds)
scatter --pr-risk --branch-name feature/tenant-isolation --risk-context migration
```

There's also a `--risk-only` flag for when you're mid-coding and just want the vibe check
without the full consumer table:

```bash
scatter --pr-risk --branch-name feature/tenant-isolation --risk-only
```

```
Scatter Risk: YELLOW (composite: 0.52)

  Dimensions:
    Cycle entanglement   █████░░░░░  0.60  HIGH    Data ↔ Api (2 projects)
    Blast radius         ████░░░░░░  0.45  MEDIUM  4 direct, 10 transitive
    Structural coupling  ████░░░░░░  0.40  MEDIUM  Fan-in of 4
    Database coupling    ███░░░░░░░  0.30  LOW     1 shared sproc
    Domain boundary      ██░░░░░░░░  0.20  LOW     1 cluster boundary
    Instability          ██░░░░░░░░  0.15  LOW     Instability 0.35
    Change surface       ████░░░░░░  0.40  MEDIUM  class modified

  Hotspot: PortalDataService (cycle involvement)
```

Five seconds. That's all you need to decide whether to keep coding or stop and think.

### Risk Level Thresholds

Risk levels come from the risk engine's composite score (see `RISK_ENGINE_PLAN.md`),
which uses weighted-maximum aggregation across 7 dimensions. The PR context weights
cycles and change_surface highest — those are the dimensions that actually break builds.

> "The thresholds need to be configurable per-repo. What's red for a leaf service is
> green for a shared library — a shared library *should* have high fan-in."

> "Start conservative. Too many false greens and people stop looking. Too many false reds
> and people stop caring. Err toward yellow."

Default thresholds and overrides (configurable in `.scatter.yaml`):

```yaml
risk:
  contexts:
    pr:
      red_threshold: 0.7            # composite score >= 0.7
      yellow_threshold: 0.4         # composite score >= 0.4
      dimension_weights:            # override defaults per-repo
        cycle: 1.0
        change_surface: 0.9
        database: 0.8
        structural: 0.7
        blast_radius: 0.7
        instability: 0.6
        domain_boundary: 0.5

  # Override: always green for these paths (test projects, docs, etc.)
  ignore_patterns:
    - "*.Tests.csproj"
    - "*.Benchmarks.csproj"

  # Override: always red for these projects (critical shared libs)
  critical_projects:
    - "GalaxyWorks.Data"
    - "GalaxyWorks.Core"
```

> "Don't average the dimension scores. The composite uses weighted max. One high-scoring
> dimension in a PR full of low-risk dimensions still means the PR is high-risk.
> Averaging hides the signal."

This is worth hammering on. If you're standing in a room and one wall is on fire, it does
not matter that the other three walls are fine. The room is on fire. Averaging the walls
tells you the room is "slightly warm." Max tells you to leave.

### Risk Factors (Human-Readable)

The comment needs to explain *why* it's red, not just *that* it's red. Nobody acts on
a color without a reason.

Risk factors are generated per dimension by the risk engine — each dimension assessor
produces its own factor strings (see `RISK_ENGINE_PLAN.md` for the full set). The PR
comment shows the top 5 factors sorted by `dimension_weight * score`. The most dangerous
signal floats to the top.

Examples of what the engine generates:
- "PortalDataService is in a dependency cycle: Data → Api → Core → Data"
- "Fan-in of 12 (top 3% of codebase by coupling score)"
- "4 shared stored procedures across 3 teams"
- "Interface IPortalRepository deleted with 7 active implementors"
- "Crosses 3 domain clusters — coordination required"
- "Instability 0.85 with fan-in 8 — fragile foundation pattern"

> "The deleted-type case is the most dangerous change and the easiest to miss. If someone
> deletes a class that's referenced by 6 projects, that's a build break across 6 pipelines.
> The change_surface dimension catches this automatically — deletions score 0.7–1.0."

Deletions are the thing I've watched bite teams the most. You delete a class, your project
compiles, you merge, and six other pipelines go red. The type scanner catches it. The
change_surface dimension scores it. The PR comment screams about it. That's the whole
point of this feature.

---

## PR Comment Format

Two rules: **scannable in 5 seconds** (the risk level and one-line summary) and
**useful in 60 seconds** (the details, for people who care). Everything else goes behind
a `<details>` fold because nobody wants to scroll past 30 rows of transitive consumers
to get to the next file in the PR diff.

### Template

```markdown
## Scatter Risk: 🔴 HIGH (0.78)

**3 changed types affect 14 consumers across the dependency graph.**

### Risk Dimensions
| Dimension | Score | Severity | Top Factor |
|-----------|:-----:|----------|------------|
| Database coupling | 0.85 | critical | 4 sprocs shared across 3 teams |
| Cycle entanglement | 0.80 | high | Data ↔ Api ↔ Core (3 projects) |
| Blast radius | 0.70 | high | 14 transitive consumers (depth 2) |
| Domain boundary | 0.50 | medium | Crosses 2 domain clusters |
| Change surface | 0.40 | medium | interface modified |
| Structural coupling | 0.45 | medium | Fan-in of 8 (top 5%) |
| Instability | 0.30 | low | Instability 0.35 |

### Hotspot
`PortalDataService` drives 4 of 7 risk dimensions (composite: 0.78).

### Changed Types
| Type | Kind | Composite | Direct Consumers | Critical Dimensions |
|------|------|:-:|:-:|-----|
| `PortalDataService` | class (modified) | 0.78 | 4 | cycle, database, blast radius |
| `IPortalRepository` | interface (modified) | 0.65 | 7 | cycle, blast radius |
| `TenantContext` | class (modified) | 0.41 | 3 | structural |

<details>
<summary>📋 Risk Factors (5)</summary>

- `PortalDataService` is in a dependency cycle (Data ↔ Api ↔ Core)
- 4 shared stored procedures across 3 teams (dbo.sp_InsertPortalConfiguration, ...)
- `IPortalRepository` has fan-in of 7 (top 3% of codebase by coupling score)
- Changes cross 2 domain clusters — coordination required
- `PortalDataService` has instability 0.85 with fan-in 8 — fragile foundation

</details>

<details>
<summary>💡 Mitigations (AI)</summary>

1. Coordinate with Platform team before merging — their Api project is in the cycle
2. Verify sproc backward-compatibility or coordinate cutover timing with BatchOps
3. Consider splitting PR: extract interface change into separate PR to isolate risk
4. Run `scatter --target-project GalaxyWorks.Data --risk-details` for full consumer analysis

</details>

<details>
<summary>📊 Consumer Impact — 4 direct, 10 transitive (click to expand)</summary>

**Direct:**
| Consumer | Coupling Score | Instability | In Cycle | Shared Sprocs |
|----------|:-:|:-:|:-:|:-:|
| GalaxyWorks.Api | 0.82 | 0.33 | yes | 1 |
| GalaxyWorks.WebPortal | 0.71 | 0.57 | yes | 0 |
| GalaxyWorks.BatchProcessor | 0.45 | 0.80 | no | 2 |
| MyGalaxyConsumerApp | 0.31 | 1.00 | no | 0 |

**Transitive (depth 1):**
| Consumer | Via | Depth |
|----------|-----|:-:|
| GalaxyWorks.Reporting | GalaxyWorks.Api | 1 |
| GalaxyWorks.Notifications | GalaxyWorks.Api | 1 |
| ... | ... | ... |

</details>

### Filter Pipeline
```
250[graph] → 4 project refs[graph] → 4 namespace → 3 class match
```

---
<sub>Scatter v0.12.0 · graph cache hit · completed in 4.2s</sub>
```

> "The `<details>` collapse is mandatory. Lead with the signal, hide the evidence."

> "Can we link the consumer names to their .csproj files in the repo? Makes it easy to
> click through and see what they actually do."

Good call on the linking. If someone sees a consumer name they don't recognize, they
should be one click from the project file. That's the kind of detail that makes people
trust the tool instead of dismissing it.

### Comment Update Strategy

When the PR gets updated (new commits pushed):

1. Find existing Scatter comment (search by bot user or comment marker)
2. **Update in place** (edit, don't create a new comment) — avoids comment spam
3. Add a timestamp: "Last updated: 2026-03-30 14:22 UTC (commit abc1234)"
4. If risk level changed, note it: "Risk changed: YELLOW → RED (new commit modifies PortalDataService)"

> "One comment, updated. If you post a new comment on every push, engineers will mute the
> bot within a week."

I've seen this happen with other bots. Three comments deep and people stop reading any of
them. One comment, always current, always in the same place. That's the contract.

---

## Implementation Plan

### Phase 1: Core Risk Engine + PR Mode (2 weeks) — ✅ SHIPPED (2026-04-03, PR #21)

**Goal**: `scatter --pr-risk` produces a `PRRiskReport` to JSON/markdown — runnable
locally and in CI, same output either way.

#### Deliverables

**1.1 Risk Engine** (prerequisite — ✅ SHIPPED, see `RISK_ENGINE_PLAN.md`)
- `RiskProfile`, `RiskDimension`, `AggregateRisk`, `RiskContext`, `RiskLevel` in `scatter/core/risk_models.py`
- `risk_engine.py` + `risk_dimensions.py` in `scatter/analyzers/`
- PR Risk depends on **Risk Engine Phase 1 only** — it calls `compute_risk_profile()`
  and `aggregate_risk()` directly, it does not need the impact analysis wiring from Phase 2

**1.2 PRRiskReport dataclass** (`scatter/core/models.py`)
- Add `PRRiskReport`, `ChangedType` to `scatter/core/models.py` (PR-specific wrappers,
  NOT in `risk_models.py` — risk vocabulary stays in `risk_models.py`, PR-specific
  report types go in `models.py` alongside `ImpactReport` and `ConsumerResult`)
- `PRRiskReport` wraps `AggregateRisk` (from `risk_models.py`) with PR-specific metadata
- No `TargetRisk` — `RiskProfile` from the engine handles that

**1.3 PR risk analyzer** (`scatter/analyzers/pr_risk_analyzer.py`)
- New module, ~150 lines (lean — all risk logic lives in the engine)
- Entry point: `analyze_pr_risk(changed_files, graph, config) -> PRRiskReport`
- Internally:
  1. Extract changed types from diff (reuse `type_scanner.extract_type_declarations`)
  2. For each changed type, run consumer detection (reuse `find_consumers` with graph acceleration)
  3. Call `compute_risk_profile()` from risk engine (scores 6 graph-derived dimensions; PR analyzer populates `change_surface` separately)
  4. Call `aggregate_risk()` from risk engine
  5. Assemble `PRRiskReport`

> "This module doesn't compute risk. It extracts what changed, asks the risk engine to
> score it, and assembles the report. Three steps, no risk logic."

**1.4 PR risk config** (`scatter/config.py`)
- Add `PRRiskConfig` dataclass with threshold defaults
- Wire into `ScatterConfig`
- Support `.scatter.yaml` overrides

**1.5 PR risk mode handler** (`scatter/cli.py`)
- New mode: `--pr-risk`
- Takes `--branch-name` (required) and `--base-branch` (default: main)
- Orchestration:
  1. Load/build graph
  2. Run git diff between branches
  3. Call `analyze_pr_risk`
  4. Dispatch to reporter

**1.6 PR risk reporters**
- **Markdown reporter** (`scatter/reports/pr_comment_reporter.py`): new module, generates
  the PR comment template above. Pure string formatting, no side effects.
- **JSON reporter**: extend existing `json_reporter.py` to handle `PRRiskReport`
- **Console reporter**: extend existing `console_reporter.py` for terminal preview

**1.7 Tests**
- `tests/unit/test_pr_risk_analyzer.py`: risk level computation, threshold edge cases,
  cycle detection integration, deleted-type detection
- `tests/unit/test_pr_comment_reporter.py`: **golden-file snapshot tests** — the markdown
  comment output is compared against committed `.expected.md` files. If the format changes,
  you update the golden file deliberately. No more "did the comment break?" surprises.
- **Empty result sanity check**: when no changed types are detected, the analyzer must
  return a clean "no C# type changes detected" report — not crash, not return an empty
  `PRRiskReport` with zeroed fields.
- **Performance regression test**: PR analysis against sample projects must complete in
  <10 seconds. This is a test, not a hope. If it regresses, the test fails.
- Test with sample projects: modify `GalaxyWorks.Data/PortalDataService.cs`, verify
  consumers detected and risk level computed correctly

#### Design Decisions

| Decision | Rationale |
|----------|-----------|
| Consume unified risk engine, don't reimplement | One risk model across PR, SOW, and local dev — no drift |
| Weighted-max aggregation (not average) | One critical dimension makes the whole PR critical |
| Separate markdown reporter module | PR comments have unique formatting needs, don't bloat existing reporters |
| Reuse `find_consumers` unchanged | Consumer detection is proven at scale; don't fork it |
| Graph cache required (no filesystem fallback) | Performance budget is 90s; cold filesystem scan won't make it for large repos |
| Same output locally and in CI | Engineers preview exactly what the bot will say before pushing |

### Phase 2: GitHub Actions Integration (1–2 weeks) — ✅ SHIPPED (2026-04-04, PR #22)

**Goal**: Scatter runs automatically on every PR and posts a risk comment. Zero
configuration for consuming teams — they drop the workflow file in their repo, done.

#### Deliverables

**2.1 GitHub Action workflow** (`.github/workflows/scatter-pr-risk.yml`)

```yaml
name: Scatter PR Risk
on:
  pull_request:
    types: [opened, synchronize, reopened]
    paths:
      - '**/*.cs'
      - '**/*.csproj'

jobs:
  risk-analysis:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write     # comment on PRs
      contents: read

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0       # full history for branch diff

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install scatter
        run: pip install .

      - name: Restore graph cache
        uses: actions/cache@v4
        with:
          path: .scatter/graph_cache
          key: scatter-graph-${{ hashFiles('**/*.csproj') }}
          restore-keys: scatter-graph-

      - name: Run risk analysis
        id: scatter
        run: |
          scatter --pr-risk \
            --branch-name ${{ github.head_ref }} \
            --base-branch ${{ github.base_ref }} \
            --search-scope . \
            --output-format markdown \
            --output-file pr_comment.md
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}  # optional, for AI enrichment

      - name: Post PR comment
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          path: pr_comment.md
```

> "The `sticky-pull-request-comment` action handles the update-in-place behavior. One
> comment per workflow, updated on every push. No comment spam."

The `paths` filter matters — we don't want Scatter running on docs-only or
markdown-only PRs. C# and project file changes only. Everything else is noise.

**2.2 Graph cache strategy for CI**
- Cache the graph pickle as a GitHub Actions artifact (keyed on .csproj hash)
- On PR, restore cache → run incremental patch → analyze → save updated cache
- If cache miss, full rebuild (one-time cost ~40s for 250 projects, acceptable)
- Cache invalidation: if .csproj files changed, rebuild graph (new key)

> "The cache key should be based on .csproj content, not branch name. Two PRs touching
> the same projects should share the graph. Branch-keyed caches have terrible hit rates."

This is the kind of decision that looks obvious in retrospect but will cost you a week of
debugging cache misses if you get it wrong. Content-keyed. Always.

**2.3 Performance budget**

| Step | Target | Notes |
|------|--------|-------|
| Checkout + setup | 15s | Standard Actions overhead |
| Graph cache restore | 2s | Actions cache is fast for small artifacts |
| Graph rebuild (cache miss) | 40s | One-time; subsequent runs use cache |
| Graph patch (cache hit) | <1s | Incremental update |
| Risk analysis | 5–10s | Consumer detection + metrics lookup |
| AI enrichment (optional) | 10–20s | Risk assessment + coupling narrative |
| Comment posting | 2s | GitHub API call |
| **Total (cache hit)** | **20–35s** | Well under 90s budget |
| **Total (cache miss)** | **60–90s** | First run only |

The 90-second budget is generous. On a warm cache, this should come in under 30 seconds.
That's fast enough that the PR comment appears before the reviewer finishes reading the
diff description. If it takes longer than that, people will form opinions before the risk
data arrives, and the data won't change their minds.

**2.4 Failure modes**

> "The action must never block a merge. If Scatter crashes, the PR comment should say
> 'Scatter analysis failed — see logs' and the workflow should exit 0, not 1."

This is non-negotiable. The moment this blocks a deploy, someone will rip it out and
we'll never get it back in. Advisory only. Always.

- Graph build fails → post "analysis unavailable" comment, exit 0
- AI provider unavailable → run without AI enrichment (risk factors from metrics only)
- Timeout (>5 min) → kill, post "timed out" comment, exit 0
- No changed types detected → post "no C# type changes detected, no risk analysis needed"

```yaml
      - name: Run risk analysis
        id: scatter
        continue-on-error: true    # never block merge
        timeout-minutes: 5
        run: ...

      - name: Post fallback comment on failure
        if: steps.scatter.outcome == 'failure'
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          message: |
            ## Scatter Risk: analysis unavailable
            Scatter encountered an error analyzing this PR. See [workflow logs](${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}) for details.
```

**2.5 Tests**
- Integration test: create a PR-like scenario (two branches, diff, graph), run
  `scatter --pr-risk`, verify JSON output structure
- Snapshot test: verify markdown comment output matches expected template
- Failure mode tests: missing graph, no changed types, AI unavailable
- **Backward compat regression test**: verify `--sow` mode still works identically after
  PR risk mode is added. New mode, no regressions.

### Phase 3: Prediction Logging (1 week)

**Goal**: Log every PR risk assessment as a prediction record. Start collecting data
from day one — you can't calibrate retroactively.

This is Sam's "20 lines" principle: append a JSON line on every `--pr-risk` run. No
webhooks, no dashboards, no infrastructure. Collect data first, argue about where it
goes later.

#### Key Design Decisions (from team brainstorm 2026-04-04)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Scatter owns the data** — JSONL file, not embedded in PR comments | Mat: "embedding central intelligence in a vendorific surface" is a liability. If WEX moves off GitHub, prediction history shouldn't go with it. The JSONL is portable, greppable, and lives on infrastructure we control. |
| 2 | **Same schema regardless of destination** | Fatima: local file, workflow artifact, future webhook — same JSON shape. No migration problem when we add centralized collection later. |
| 3 | **Prediction and outcome are separate concerns** | Marcus: the prediction is easy (scatter has the data). The outcome is hard (did this PR actually cause a problem?). Phase 3 logs predictions. Phase 4 adds outcomes. Don't conflate them. |
| 4 | **No full report in the record** | Devon: the record is metadata *about* a prediction, not the prediction itself. Keeps JSONL small, aggregation queries fast. Full reports are separate artifacts. |
| 5 | **Schema version field from day one** | Kai: lets us evolve without breaking old records. |
| 6 | **Nullable outcome fields** | Outcome starts null, gets filled in by Phase 4 calibration. The schema anticipates it so we don't need a migration. |

#### Deliverables

**3.1 Prediction record schema**

```python
@dataclass
class RiskPrediction:
    """A single PR risk prediction — one record per --pr-risk run."""

    # Schema
    schema_version: int = 1

    # Identity — SHAs are permanent, branch names aren't
    timestamp: str                   # ISO 8601
    repo: str                        # "org/repo" or local path
    pr_number: Optional[int]         # None for local CLI runs
    branch: str
    base_branch: str
    head_sha: str
    base_sha: str
    scatter_version: str

    # Prediction
    composite_score: float
    risk_level: str                  # "GREEN", "YELLOW", "RED"
    dimensions: dict[str, float]     # {"change_surface": 0.3, "blast_radius": 0.5, ...}
    dimension_data_available: dict[str, bool]  # which scores are real vs zero-because-no-data
    changed_type_count: int
    direct_consumer_count: int
    transitive_consumer_count: int
    graph_available: bool
    risk_factors: list[str]          # top 3 factors as strings
    duration_ms: int

    # Outcome — null until Phase 4 annotates
    outcome: Optional[str] = None    # "clean", "hotfix", "revert", "incident"
    outcome_signals: Optional[dict] = None
    merge_sha: Optional[str] = None
```

**Why `head_sha` and `base_sha`?** (Devon) Branches get deleted; SHAs are permanent.
The join key for calibration is `repo + head_sha`, not `repo + branch`.

**Why `dimension_data_available`?** (Devon) A 0.0 cycle score means different things
depending on whether the graph was available. Without this flag, calibration can't
distinguish "predicted no cycles" from "couldn't check for cycles."

**Why `risk_factors` limited to top 3?** (Devon) Qualitative context without bloating
the record. If you need all factors, read the full report.

**3.2 Prediction writer** (`scatter/store/prediction_log.py`)

~30 lines. Append-only JSONL writer.

```python
def log_prediction(report: PRRiskReport, path: Path) -> None:
    """Append a prediction record to the JSONL log."""
    record = _build_record(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
```

- Default location: `.scatter/predictions.jsonl`
- Called automatically at the end of `run_pr_risk_mode` (after report output)
- `--no-prediction-log` flag to disable (for testing or dry runs)
- Log a warning if file exceeds 10MB (~20K predictions)

**3.3 Wire into `--pr-risk` mode**

After the report is written/printed, call `log_prediction()`. One line in
`scatter/modes/pr_risk.py`. The prediction log is a side effect of analysis,
not a separate command.

**3.4 `scatter --predictions` reader**

Minimal reader for inspecting the log:

```bash
# Show last 10 predictions
scatter --predictions .scatter/predictions.jsonl --tail 10

# Show only RED predictions
scatter --predictions .scatter/predictions.jsonl --level RED

# Summary stats
scatter --predictions .scatter/predictions.jsonl --summary
```

This is the seed of the Phase 4 calibration command. Keep it simple — `jq` could do
most of this, but a built-in command means teams don't need to learn `jq`.

**3.5 GitHub Actions: upload as workflow artifact**

In the `scatter-pr-risk.yml` workflow, after analysis:

```yaml
- name: Upload prediction log
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: scatter-predictions
    path: .scatter/predictions.jsonl
    retention-days: 90
```

Artifacts persist for 90 days (Fatima). Not the long-term answer, but captures data
from CI runs without requiring `contents: write` permission. The JSONL file itself is
the portable record — artifacts are just a convenient transport.

**3.6 Tests**
- Unit test: `RiskPrediction` serialization round-trip (write JSONL → read back → compare)
- Unit test: `_build_record` populates all fields from a `PRRiskReport`
- Unit test: `dimension_data_available` correctly reflects graph availability
- Integration test: run `--pr-risk` → verify `.scatter/predictions.jsonl` exists with valid record
- Unit test: `--no-prediction-log` suppresses logging
- Unit test: 10MB warning threshold (mock file size)

**3.7 Log retention**

At ~500 bytes per record, a year of daily PRs is ~180KB. Rotation is not a year-one
concern. When it becomes one:

- If file exceeds 10MB (~20K PRs), log a warning suggesting manual archival
- Phase 4 calibration reads the full log, so rotation must preserve data
- Future: `scatter --prediction-archive` to move old entries to dated files

### Phase 4: Calibration and Trust (2+ weeks, deferred until prediction data exists)

**Goal**: Prove the signal is worth reading. Track prediction accuracy, annotate
outcomes, compute precision/recall, and tune thresholds.

This is the phase that separates a toy from a tool. Phases 1–3 produce a signal and log
it. Phase 4 proves the signal is worth reading. Without this phase, we're the boy who
cried wolf — and the moment someone gets a RED on a harmless change, they'll ignore
every RED after it.

**This phase is deferred** until we have enough prediction data to calibrate against.
No point building an accuracy dashboard with zero data points. Ship Phases 1–3, let the
log accumulate for a quarter, then come back here. Minimum: ~50 RED predictions for
statistical significance (Marcus).

#### Three Things Needed for Calibration (Marcus)

1. **The prediction** — score, level, dimensions (from Phase 3 JSONL)
2. **The outcome** — did this PR actually cause a problem?
3. **The join key** — `repo + head_sha` (not branch name — branches get deleted)

The prediction is easy. The outcome is the hard part.

#### Deliverables

**4.1 Automated outcome signals** (no human annotation)

Nobody's going to manually annotate 200 PRs. Use automated signals (Marcus):

| Signal | How to detect | Quality |
|--------|--------------|---------|
| Hotfix commit within 48h of merge | `git log --after` on the merge commit's files | Good |
| Revert of the merge commit | `git log --grep="Revert"` + parent SHA matching | Very good |
| CI failure on the merge commit | GitHub API check runs | Moderate (flaky tests) |
| Incident ticket linked to PR | Jira/Linear API if available | Best (requires integration) |

**4.2 `scatter --calibrate` command**

Not a dashboard. A CLI command that reads predictions, cross-references git for
outcomes, and prints metrics (Marcus):

```bash
scatter --calibrate .scatter/predictions.jsonl
```

```
Scatter Calibration Report
==========================
Predictions: 142 (87 GREEN, 43 YELLOW, 12 RED)
Outcomes annotated: 98/142 (69%)

Precision at RED:  8/12 (67%)  — target: >60%
Recall at RED:     8/11 (73%)  — target: >80%
False positive rate (RED): 33%
False negative rate:        3%

Score distribution: 61% GREEN, 30% YELLOW, 9% RED
  (healthy range: ~70/25/5)

Recommendation: RED threshold slightly too aggressive.
  Consider raising from 0.7 → 0.75 in .scatter.yaml.
```

Something you paste into a quarterly review. Not a webapp.

**4.3 Outcome annotator**

A command or GitHub Action that walks merged PRs and fills in the `outcome` and
`merge_sha` fields in the JSONL:

```bash
scatter --annotate-outcomes .scatter/predictions.jsonl
```

For each prediction with `outcome: null`:
1. Check if `head_sha` was merged (via `git log` or GitHub API)
2. If merged, check for hotfix/revert signals in the 48h window after merge
3. Write `outcome` and `outcome_signals` back into the record

**4.4 KPIs for leadership** (Devon)

The metric that matters to leadership isn't precision or recall. It's behavioral:

- **"What % of RED-scored PRs received additional review before merge?"** — measures
  whether the tool changes how people work
- **Time-to-merge for RED vs GREEN PRs** — did RED PRs get more scrutiny?
- **Review comment count on RED vs GREEN** — proxy for "did the team discuss it?"
- **Score distribution trending** — are we always saying GREEN? (useless) Is RED
  increasing over time? (codebase is getting riskier, or thresholds need tuning)

**4.5 Threshold tuning**

Use the calibration report to adjust thresholds:
- If false positive rate > 30%: raise RED thresholds (too sensitive)
- If false negative rate > 5%: lower RED thresholds (not sensitive enough)
- Per-repo tuning: different repos have different coupling profiles

This is where `.scatter.yaml` per-repo config pays off — each team tunes their own
sensitivity based on their own history.

#### Future: Centralized Collection (Phase 5, not scoped)

When Mat wants division-wide trend lines across dozens of repos, add a webhook
option (Fatima):

```bash
scatter --prediction-webhook https://internal.wex.com/scatter/ingest
```

Same JSONL record, different destination. One config line. The backend can be
anything WEX already has for internal telemetry — a Lambda writing to S3, a
simple Flask app writing to SQLite, a shared bucket with path conventions like
`s3://scatter-predictions/{org}/{repo}/{year}/{month}.jsonl`.

The schema is already destination-agnostic (Phase 3, Decision #2). Moving from
local file to centralized collection is a writer change, not a schema change.

Not scoped here because it requires infrastructure decisions that depend on what
WEX already has. But the prediction record format is ready for it.

---

## What This Means for Athena

### Short-term (Phase 1–2)
- We ship a GitHub Action that every .NET team in the division can adopt
- Zero-config for consuming teams (add the workflow file, done)
- Immediate visibility into change risk on every PR
- Athena's name is on every comment — attribution baked into the output

### Medium-term (Phase 3)
- Prediction accuracy data gives us a credibility story for leadership
- "Our tool predicted 87% of cross-team build breaks before merge" — that's a slide
  that writes itself
- Threshold tuning makes the signal better over time — it learns from the codebase

### Long-term
- PR risk scoring becomes the entry point for Scatter adoption
- Teams that see the PR comment start asking "can I run this locally?"
- That pulls them into target-project mode, SOW scoping, graph analysis
- Scatter becomes the division's dependency intelligence platform

> "The PR comment is a Trojan horse. It looks like a CI check. It's actually an adoption
> strategy."

That's exactly what this is. We're not going to send a division-wide email asking people
to install a CLI tool. We're going to put risk data in front of them on every PR until
they start thinking of Scatter as infrastructure they depend on. Then they'll come to us.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| False positives erode trust | High (initially) | Medium | Start conservative; track and tune in Phase 3 |
| Performance too slow for PR feedback | Low | High | Graph cache + incremental patching keeps it under 30s for cache hits |
| Engineers ignore the comment | Medium | Medium | Make GREEN the common case so RED is surprising and worth reading |
| Graph cache corruption in CI | Low | Low | Atomic writes, version headers, graceful fallback to full rebuild |
| AI rate limits in CI | Medium | Low | AI enrichment is optional; metrics-only mode works without API |
| Regex false positives in type extraction | Medium | Medium | Hybrid AST spike (in progress) directly addresses this |

The false positive risk is the one that keeps me up at night. Not because it's hard to fix
(Phase 3 calibration handles it), but because trust is a one-way door — it's easy to lose
and hard to earn back. The first month of RED comments need to be *right*. If we cry wolf
three times, nobody will read the comment ever again, and this whole initiative dies.

That's why the thresholds start conservative. Better to miss a real risk (which we'll
catch in Phase 3 and adjust for) than to flag a safe change as dangerous. People forgive
"you didn't warn me" more easily than "you warn me about everything."

---

## Open Questions

1. **Team ownership mapping**: Phase 1 counts consumers. The real value is counting
   *cross-team* consumers. Where does team→project ownership data live? Is it in a
   spreadsheet, a CODEOWNERS file, or nowhere yet?

2. **Monorepo vs multi-repo**: Does this need to work across repo boundaries? If
   NuGet packages are involved, the consumer detection pipeline needs to handle
   `<PackageReference>` in addition to `<ProjectReference>`.

3. **Notification escalation**: Should RED risk PRs trigger a Slack notification to
   the owning team's channel? Or is the PR comment sufficient?

4. **Merge blocking**: Should this ever be a required check (block merge on RED)? Or
   always advisory? Recommendation: always advisory in Phase 1–2. Let trust build
   before even considering enforcement. If we have to enforce it, we've failed at
   making the signal good enough that people want to read it voluntarily.

---

## Files Summary

### Already shipped (Risk Engine Phase 1)

| File | Status | Purpose |
|------|--------|---------|
| `scatter/core/risk_models.py` | ✅ Shipped | `RiskProfile`, `RiskDimension`, `AggregateRisk`, `RiskContext`, `RiskLevel` |
| `scatter/analyzers/risk_engine.py` | ✅ Shipped | `compute_risk_profile`, `aggregate_risk`, `format_risk_factors` |
| `scatter/analyzers/risk_dimensions.py` | ✅ Shipped | Six `score_*` dimension functions |
| `tests/unit/test_risk_engine.py` | ✅ Shipped | 26 tests: aggregation, composite scoring, edge cases |
| `tests/unit/test_risk_dimensions.py` | ✅ Shipped | 37 tests: per-dimension scoring, interpolation |

### PR Risk Phase 1 (new files)

| File | Action | Purpose |
|------|--------|---------|
| `scatter/core/models.py` | Modify | Add `PRRiskReport`, `ChangedType` (PR-specific wrappers) |
| `scatter/analyzers/pr_risk_analyzer.py` | Create | PR-specific: diff extraction, engine invocation, report assembly |
| `scatter/config.py` | Modify | Add `PRRiskConfig` with threshold defaults |
| `scatter/cli.py` | Modify | Add `--pr-risk` mode handler |
| `scatter/cli_parser.py` | Modify | Add `--pr-risk`, `--base-branch`, `--risk-context`, `--risk-details`, `--risk-only` |
| `scatter/reports/pr_comment_reporter.py` | Create | Markdown PR comment formatter (dimension table, collapsibles) |
| `scatter/reports/json_reporter.py` | Modify | Handle `PRRiskReport` with full `RiskProfile` serialization |
| `scatter/reports/console_reporter.py` | Modify | Terminal preview with dimension table |
| `tests/unit/test_pr_risk_analyzer.py` | Create | PR report assembly, threshold edges, deleted-type detection |
| `tests/unit/test_pr_comment_reporter.py` | Create | Golden-file snapshot tests for markdown output |

### PR Risk Phase 2 (GitHub Actions) — ✅ SHIPPED (2026-04-04, PR #22)

| File | Action | Purpose |
|------|--------|---------|
| `tools/github-action/scatter-pr-risk.yml` | Created | GitHub Actions workflow template |
| `tools/github-action/README.md` | Modified | Restructured for both workflows |
| `scatter/cli_parser.py` | Modified | Added `--collapsible` flag |
| `scatter/modes/pr_risk.py` | Modified | Wired `--collapsible` to markdown reporter |
| `.github/workflows/ci.yml` | Modified | YAML validation, smoke tests, backward compat |
| `tests/unit/test_backward_compat.py` | Created | Parser flags, dispatch, functional compat test |
| `tests/golden/pr_risk_green_collapsible.md` | Created | Golden file for collapsible output |

### PR Risk Phase 3 (Prediction logging)

| File | Action | Purpose |
|------|--------|---------|
| `scatter/core/models.py` | Modify | Add `RiskPrediction` dataclass |
| `scatter/store/prediction_log.py` | Create | Append-only JSONL writer + reader |
| `scatter/modes/pr_risk.py` | Modify | Call `log_prediction()` after report output |
| `scatter/cli_parser.py` | Modify | Add `--no-prediction-log`, `--predictions` flags |
| `tests/unit/test_prediction_log.py` | Create | Serialization, round-trip, integration, warning |

### PR Risk Phase 4 (Calibration)

| File | Action | Purpose |
|------|--------|---------|
| `scatter/store/prediction_log.py` | Modify | Add outcome annotator, calibration reader |
| `scatter/modes/calibrate.py` | Create | `--calibrate` and `--annotate-outcomes` mode handlers |
| `tests/unit/test_calibration.py` | Create | Outcome detection, precision/recall computation |
