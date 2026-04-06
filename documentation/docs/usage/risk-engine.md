# Risk Engine

Every analysis in Scatter can be risk-scored. The risk engine runs the same model whether you're reviewing a PR, scoping a SOW, or just poking at a branch — same dimensions, same math, different weights depending on context.

## Why a risk engine?

The old way: someone reads a diff, mentally traces the blast radius, and guesses "this feels risky." The problem is that "feels risky" doesn't scale past three consumers, and it definitely doesn't explain *why* it's risky in a way that survives a meeting.

Scatter's risk engine replaces gut feel with graph-derived scores across 7 dimensions. Every rating is reproducible — same input, same score, no LLM variance. AI can escalate a rating when it spots business context the graph can't see, but it can never lower one.

## The seven dimensions

| Dimension | What it measures | Example |
|-----------|-----------------|---------|
| **Structural coupling** | How connected the target is to other projects (weighted edge count) | A shared data library with 12 incoming edges scores higher than a leaf app with 1 |
| **Instability** | Martin's instability index: `fan-out / (fan-in + fan-out)` | 0.0 = stable core (change carefully), 1.0 = unstable leaf (safe to change) |
| **Cycle entanglement** | Whether the target participates in a circular dependency | Projects in cycles are harder to test and deploy in isolation |
| **Database coupling** | Shared stored procedure density across projects | A sproc called by 5 projects creates implicit coupling the project graph doesn't show |
| **Blast radius** | How many projects are affected (direct + transitive) | 2 direct consumers is routine; 15 with 8 transitive is not |
| **Domain boundary** | Whether the change crosses cluster boundaries | Changing a library used by 3 domain clusters means 3 teams to coordinate with |
| **Change surface** | How many types/files are modified (PR risk only) | Touching 1 method is safer than refactoring 12 classes across 4 files |

Each dimension produces a score from 0.0 (no risk) to 1.0 (maximum risk), plus a severity label (low / medium / high / critical) and a list of human-readable factors explaining the score.

## How scores combine

Scatter uses **weighted-max aggregation**, not averaging. The composite score is driven by the worst dimension, weighted by context:

```
composite = max(weight[d] * score[d] for d in dimensions)
```

Why not average? Because a project with 0.9 cycle risk and 0.0 everything else is genuinely dangerous — averaging would hide that behind a comfortable 0.13.

## Risk levels

| Level | Composite score | What it means |
|-------|:-:|---|
| **GREEN** | < 0.4 | Low risk. Standard review process. |
| **YELLOW** | 0.4 – 0.7 | Moderate risk. Extra review recommended. Consider staged rollout. |
| **RED** | ≥ 0.7 | High risk. Design review before proceeding. Coordinate affected teams. |

AI enrichment can escalate to **Critical** when it detects business context (e.g., the target handles payment processing), but graph-derived risk tops out at RED.

## Risk contexts

Different analysis modes weight dimensions differently because the question they answer is different:

| Context | Heaviest weights | Why |
|---------|-----------------|-----|
| **SOW scoping** | database (1.0), domain boundary (0.9), cycle (0.8) | Scoping cares about coordination cost and migration complexity |
| **PR risk** | cycle (1.0), change surface (0.9), database (0.8) | PRs care about what's actually changing and whether it's entangled |
| **Local dev** | cycle (1.0), change surface (0.9), blast radius (0.7) | Developers care about what might break when they build locally |

You don't configure these — Scatter picks the right context based on the mode you're running.

## Seeing risk data

Risk dimensions appear in different places depending on the mode:

**Impact analysis** (`--sow`):

```
Overall Risk: High | Complexity: Medium (3-5 developer-days)
```

Risk ratings appear on each consumer in the blast radius tree, with justification:

```
├── GalaxyWorks.WebPortal  [HIGH]  direct
│   Risk: High — "6 direct consumers including API and batch processor"
```

**PR risk** (`--pr-risk`):

```
PR Risk: RED (0.80)
  Dimension              Score  Severity
  ─────────────────────  ─────  ────────
  Change surface          0.70  high
  Cycle entanglement      0.80  critical
  Structural coupling     0.45  medium
```

**Scoping** (`--sow --scope-estimate`):

```
Risk: YELLOW (composite 0.48) — 3 direct, 7 transitive consumer(s)
```

## Graph-derived vs AI-enriched

The risk engine has two layers:

1. **Graph-derived** (deterministic) — computed from the dependency graph. Same input always produces the same score. This is the baseline.
2. **AI enrichment** (escalation-only) — the AI reviews the graph-derived rating and can escalate it when it sees business context. Example: a LOW-risk change to a billing service might get escalated to MEDIUM because the AI recognizes it processes payments. But the AI can **never downgrade** a graph-derived rating.

When no graph is available (e.g., first run before cache is built), AI provides the primary rating. Once a graph exists, it becomes authoritative.

## Risk profiles

Behind the scenes, Scatter computes a `RiskProfile` per target with all 7 dimension scores. Multiple targets aggregate into an `AggregateRisk` using the same weighted-max formula. You can see the full profile in JSON output:

```bash
scatter --sow "Modify PortalDataService" --search-scope . \
  --output-format json --output-file report.json
```

The JSON includes `risk_profiles` with per-dimension scores, severity labels, raw metrics, and factor explanations.

---

!!! info "Under the hood"
    The risk engine lives in `scatter/analyzers/risk_engine.py` (scoring functions) and `scatter/core/risk_models.py` (data models). Dimension weights are defined in `risk_models.py` as `SOW_RISK_CONTEXT`, `PR_RISK_CONTEXT`, and `LOCAL_DEV_CONTEXT`. The piecewise-linear scoring functions avoid step-function cliffs — small changes in input produce proportional changes in score.
