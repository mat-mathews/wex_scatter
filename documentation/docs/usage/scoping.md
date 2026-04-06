# SOW Scoping

A CSE (Customer Sponsored Enhancement) or work request lands on your desk. The first question in the scoping meeting isn't "how should we build it?" — it's "how long will this take?" Scatter's `--scope-estimate` flag turns an impact report into a structured effort breakdown with confidence bands, grounded in actual dependency data instead of gut feel.

## Basic usage

```bash
scatter \
  --sow "Add tenant isolation to the portal configuration system" \
  --search-scope . \
  --scope-estimate \
  --graph-metrics
```

```
=== Effort Estimate (MODERATE confidence, ±30%) ===
  Category               Base     Min     Max  Notes
  ────────────────────── ─────── ─────── ───────  ──────────────────────────────
  investigation            1.5     1.1     2.0  3 target(s); no cycles
  implementation           4.0     2.8     5.2  4 direct; 2 depth-1
  testing                  3.0     2.1     3.9  4 direct consumer(s); 1 shared sproc(s)
  integration_risk         1.5     1.1     2.0  1 shared sproc(s); high fan-in (>5)
  database_migration       1.0     0.7     1.3  1 shared sproc(s)
  ────────────────────── ─────── ─────── ───────  ──────────────────────────────
  TOTAL                   11.0     7.7    14.3  (1.5–2.9 dev-weeks)

Database: 1 shared sproc(s), migration complexity: low
Risk: YELLOW (composite 0.48) — 4 direct, 2 transitive consumer(s)

=== Impact Analysis Report ===
Work Request: Add tenant isolation to the portal configuration system
Overall Risk: Medium | Complexity: Medium (3-5 developer-days)
...
```

The effort table is the scoping artifact. The impact report prints below it with the full blast radius tree you're used to.

## What each category means

The five categories map to how engineering time actually gets spent — and not coincidentally, to how finance tracks project costs:

| Category | What it covers | How it's computed |
|----------|---------------|-------------------|
| **Investigation** | Reading code, understanding dependencies, spike work | 0.5 days per target + 0.5 per extra domain cluster + 1.0 if cycles exist. Clamped to 1–3 days. |
| **Implementation** | Writing the actual code changes across consumers | 1.0 day per direct consumer (sublinear past 5: 0.3/each beyond that). 0.5 per depth-1 transitive, 0.25 per depth-2. |
| **Testing** | Writing and running tests, especially for shared resources | 0.5 days per direct consumer + 1.0 per shared stored procedure + 0.5 if cross-domain. |
| **Integration risk** | Buffer for cycles, shared databases, coordination overhead | 1.0 if cycles exist + 0.5 per shared sproc + 1.0 per extra cluster + 0.5 if any consumer has fan-in > 5. |
| **Database migration** | Schema changes, sproc modifications, data migration | 1.0 per shared sproc + 2.0 extra per sproc shared by > 3 projects. |

Every number comes from the dependency graph. No LLM is involved in the base estimate.

## Why sublinear past 5?

If you have 3 direct consumers, each one probably needs unique attention — different calling patterns, different test setups, different team owners. But by consumer 8 or 12, you've likely figured out the pattern. The work per consumer flattens.

The formula: `min(n, 5) * 1.0 + max(0, n - 5) * 0.3`

So 3 consumers = 3.0 days, 5 = 5.0, 10 = 6.5, 15 = 8.0. This matches what we've seen in practice — the first five take a day each, the rest take a morning each.

## Confidence bands

Not all estimates are created equal. Scatter tells you how much to trust the numbers:

| Confidence | Band | When |
|------------|:----:|------|
| **HIGH** | ±20% | Low risk composite (< 0.3) and clear targets |
| **MODERATE** | ±30% | Moderate risk or moderate target ambiguity |
| **LOW** | ±50% | High risk (≥ 0.6) or vague targets |

If the SOW is vague (target quality = "vague"), confidence widens one step — HIGH becomes MODERATE, MODERATE becomes LOW. This is visible in the output:

```
=== Effort Estimate (LOW confidence, ±50%) ===
```

The min/max columns in the table already have the band applied:

```
  TOTAL                   11.0     5.5    16.5  (1.1–3.3 dev-weeks)
```

When confidence is LOW, present the range, not the base. "5 to 17 days" is honest. "11 days" is false precision.

## Database impact

If any stored procedures are shared across multiple projects in the blast radius, Scatter calls that out separately:

```
Database: 2 shared sproc(s), migration complexity: moderate
```

Migration complexity levels:

| Level | What it means |
|-------|---------------|
| **none** | No shared sprocs in the blast radius |
| **low** | All shared sprocs have ≤ 2 consumers |
| **moderate** | At least one sproc shared by 3 projects |
| **high** | At least one sproc shared by 4+ projects |

High-sharing sprocs are the ones that make database migrations painful — you can't change the schema without coordinating with every consumer.

## AI adjustment (optional)

When an AI provider is configured, Scatter asks the LLM to review the graph-derived estimate and suggest adjustments. This appears as a labeled overlay:

```
[AI Adjustment: 14–20 dev-days — "Graph baseline likely underestimates testing
effort due to cross-team API contract changes implied by the work request."]
```

The graph baseline is always authoritative. The AI adjustment is advisory — it's labeled separately so you know exactly what came from data and what came from inference. If AI is unavailable, the graph estimate ships as-is. No crash, no degradation.

## Output formats

Scoping supports all four output formats:

### Console (default)

The effort table + impact report shown above.

### JSON

```bash
scatter --sow "..." --search-scope . --scope-estimate \
  --output-format json --output-file scoping.json
```

Top-level structure:

```json
{
  "metadata": { ... },
  "scoping": {
    "effort": {
      "categories": [ ... ],
      "total_base_days": 11.0,
      "total_min_days": 7.7,
      "total_max_days": 14.3
    },
    "confidence": {
      "level": "MODERATE",
      "band_pct": 0.30
    },
    "database_impact": { ... },
    "ai_adjustment": { ... },
    "aggregate_risk": { ... }
  },
  "impact_report": { ... }
}
```

The `scoping` and `impact_report` sections are separate — parse what you need.

### CSV (for finance)

```bash
scatter --sow "..." --search-scope . --scope-estimate \
  --output-format csv --output-file scoping.csv
```

```csv
# Confidence: MODERATE (+-30%), composite score: 0.48
Category,Base Days,Multiplier,Min Days,Max Days,Factors
investigation,1.50,1.00,1.05,1.95,3 target(s); no cycles
implementation,4.00,1.00,2.80,5.20,4 direct; 2 depth-1
testing,3.00,1.00,2.10,3.90,4 direct consumer(s); 1 shared sproc(s)
integration_risk,1.50,1.00,1.05,1.95,1 shared sproc(s); high fan-in (>5)
database_migration,1.00,1.00,0.70,1.30,1 shared sproc(s)
TOTAL,11.00,,7.70,14.30,
```

The Multiplier column is 1.00 for now — it becomes meaningful once calibration data activates risk-driven multipliers in a future phase.

### Markdown

```bash
scatter --sow "..." --search-scope . --scope-estimate \
  --output-format markdown
```

Produces a Confluence/Teams-ready document with the effort table, database impact, risk summary, and the full impact report below.

## Without a graph

Scoping works without a dependency graph, but with reduced precision. Graph-dependent terms (cycles, fan-in, clusters, shared sprocs) default to zero, and a warning appears:

```
  Warning: No dependency graph available — effort estimate uses reduced heuristics
```

The consumer-count heuristics still work — investigation, implementation, and testing categories are still populated from the ImpactReport. But integration risk and database migration will be zero. Build the graph first (`--graph-metrics`) for the best results.

!!! note "AI is still required for SOW parsing"
    The scoping *computation* is pure graph math — no AI involved. But the impact pipeline underneath it still needs an AI provider to parse your work request into targets. You need `GOOGLE_API_KEY` to run `--sow --scope-estimate`. What you don't need AI for is the effort table itself.

## Degradation warnings

Scatter tells you when it's working with incomplete data. Warnings appear in console output and in the JSON `warnings` array:

| Warning | What's missing | Impact on estimate |
|---------|---------------|-------------------|
| "No dependency graph available" | No graph built or `--no-graph` used | Cycles, fan-in, clusters, shared sprocs all default to zero. Integration risk and database migration will be understated. |
| "Cluster analysis failed" | Graph exists but `find_clusters()` errored | Investigation and integration risk categories may be understated — cluster count defaults to zero. |

The effort table still computes in both cases. Consumer-count heuristics (implementation, testing) work regardless. But if you see either warning, the numbers are a floor, not a midpoint.

## What it does NOT do

- **It's not a commitment.** The numbers are starting points for a scoping conversation, not a contract.
- **Multipliers are inert.** The Multiplier column reads 1.00. Once we collect actuals and calibrate (Phase 3), multipliers will adjust categories based on historical accuracy.
- **No team mapping yet.** The report doesn't say "talk to the WebPortal team" — that's Phase 2.
- **No comparable SOWs.** "Last time we did something like this it took 8 days" — that's Phase 3, once the calibration store has enough data.

## Example: small change

```bash
scatter --sow "Fix null check in PortalConfiguration.Validate()" \
  --search-scope . --scope-estimate
```

```
=== Effort Estimate (HIGH confidence, ±20%) ===
  Category               Base     Min     Max  Notes
  ────────────────────── ─────── ─────── ───────  ──────────────────────────────
  investigation            1.0     0.8     1.2  1 target(s); no cycles
  implementation           1.0     0.8     1.2  1 direct
  testing                  0.5     0.4     0.6  1 direct consumer(s)
  integration_risk         0.0     0.0     0.0  none
  database_migration       0.0     0.0     0.0  no shared sprocs
  ────────────────────── ─────── ─────── ───────  ──────────────────────────────
  TOTAL                    2.5     2.0     3.0  (0.4–0.6 dev-weeks)
```

Small change, one consumer, no database involvement. The estimate says 2–3 days. That feels right for investigation + fix + test + deploy.

## Example: cross-cutting change

```bash
scatter --sow "Migrate all portal services from synchronous to async database calls" \
  --search-scope . --scope-estimate
```

```
=== Effort Estimate (LOW confidence, ±50%) ===
  Category               Base     Min     Max  Notes
  ────────────────────── ─────── ─────── ───────  ──────────────────────────────
  investigation            3.0     1.5     4.5  5 target(s); cycle detected
  implementation           8.0     4.0    12.0  8 direct; 4 depth-1; sublinear past 5
  testing                  6.5     3.3     9.8  8 direct consumer(s); 2 shared sproc(s); cross-domain
  integration_risk         5.0     2.5     7.5  cycle; 2 shared sproc(s); 3 clusters; high fan-in (>5)
  database_migration       6.0     3.0     9.0  2 shared sproc(s); 1 with >3 consumers
  ────────────────────── ─────── ─────── ───────  ──────────────────────────────
  TOTAL                   28.5    14.3    42.8  (2.9–8.6 dev-weeks)

Database: 2 shared sproc(s), migration complexity: high
Risk: RED (composite 0.72) — 8 direct, 4 transitive consumer(s)
```

Cross-cutting, cycles, shared sprocs, multiple clusters. Confidence is LOW because the risk composite is high. The range is wide (14–43 days) — that's the estimate being honest. This SOW needs to be broken into phases before anyone commits to a number.

---

!!! info "Relationship to impact analysis"
    `--scope-estimate` is a flag on impact analysis, not a separate mode. It runs the full impact pipeline first (SOW parsing, consumer tracing, risk scoring), then layers effort estimation on top. Everything in the [Impact Analysis](impact-analysis.md) docs applies — `--scope-estimate` just adds the effort table at the top.
