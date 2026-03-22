# Quick Tour

See what Scatter does in under 5 minutes. No API key needed.

## What you'll see

Scatter analyzes a .NET codebase and tells you which projects are affected by a change. You point it at a project, and it traces every consumer through project references, namespace usage, and type matching. The output shows the blast radius — who depends on what you're changing, and how tightly coupled they are.

## Run the demo

After [installing](getting-started.md), run this from the scatter repo root:

```bash
uv run scatter \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope .
```

This analyzes the sample `GalaxyWorks.Data` project and finds every project that consumes it.

## The output

```
Search scope: /code/wex_scatter (scanned 11 projects, 27 files)
Filter: 11 → 7 project refs[graph] → 6 namespace

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (6 consumer(s))
         -> Consumed by: GalaxyWorks.Api (GalaxyWorks.Api/GalaxyWorks.Api.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=6.2, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=10.8, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=12.7, fan-in=1, fan-out=1, instability=0.500, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp (MyGalaxyConsumerApp/MyGalaryConsumerApp.csproj)
           Solutions: GalaxyWorks.sln
         -> Consumed by: MyGalaryConsumerApp2 (MyGalaxyConsumerApp2/MyGalaryConsumerApp2.csproj)
           Solutions: GalaxyWorks.sln

--- Total Consuming Relationships Found: 6 ---
```

Here's what each part means:

**Filter line** — the analysis funnel. Started with 11 projects, narrowed to 7 that have a project reference to GalaxyWorks.Data, then to 6 that actually use its namespace. Each stage cuts aggressively so you see real consumers, not false positives.

**Consumer list** — every project that depends on GalaxyWorks.Data. If you change `PortalDataService`, these are the projects that might break.

**Graph metrics** — automatically computed from the dependency graph:

- **coupling** — how connected this project is (higher = more risk when changing)
- **fan-in / fan-out** — incoming vs outgoing dependencies
- **instability** — 0.0 (stable, many dependents) to 1.0 (unstable, depends on others)
- **in-cycle** — whether this project is part of a circular dependency

You didn't ask for graph metrics — Scatter builds the graph automatically on first run, caches it, and enriches every result.

!!! note
    Test projects (like `GalaxyWorks.Data.Tests`) appear as consumers because they reference the target. In production, exclude test directories via [`.scatter.yaml` configuration](configuration.md).

## Try it with markdown output

```bash
uv run scatter \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . \
  --output-format markdown
```

This produces a markdown report you can paste into a PR description, Confluence page, or Slack message.

## What AI adds

With a Google API key (`export GOOGLE_API_KEY=your-key`), Scatter unlocks impact analysis mode. Instead of pointing at a specific project, you describe the change in plain English:

```bash
uv run scatter \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation" \
  --search-scope .
```

The AI parses your work request into concrete targets, then Scatter traces the blast radius and enriches the report with:

- **Risk ratings** — Low / Medium / High / Critical per target, with justification
- **Coupling narratives** — plain English explanation of how each consumer depends on the target
- **Complexity estimate** — effort range (e.g., "3-5 developer-days") with contributing factors
- **Executive summary** — a paragraph you can paste into a ticket or email
- **Next Steps** — template-driven guidance based on the blast radius

The core consumer tracing is pure code — it works without AI. The AI adds context and risk assessment on top.

Here's what the AI-enriched markdown report looks like:

```markdown
# Impact Analysis

**Work Request:** Modify PortalDataService in GalaxyWorks.Data to add tenant isolation

## Summary

This change to PortalDataService affects 6 consuming projects across the
GalaxyWorks ecosystem. The primary risk is breaking the API contract used
by downstream services.

| Metric | Value |
|--------|-------|
| Risk | Medium |
| Complexity | Medium (3-5 developer-days) |
| Direct consumers | 6 |
| Transitive consumers | 0 |

## Targets

### GalaxyWorks.Data

**Confidence:** 0.95 (HIGH) — SOW explicitly names PortalDataService

Direct Consumers: 6 | Transitive: 0

#### Blast Radius

├── GalaxyWorks.WebPortal  [HIGH]  direct
│   Risk: Medium — "6 direct consumers including API and batch processor"
├── GalaxyWorks.Api  [HIGH]  direct
│   Risk: Medium
├── GalaxyWorks.BatchProcessor  [HIGH]  direct
│   Risk: Medium
└── ...

## Next Steps

- Review the 6 direct consumers listed above for breaking changes
- Blast radius suggests staged rollout may reduce risk
```

Every section is computed from real dependency data. The AI interprets and explains — it doesn't invent dependencies.

## Other modes

Scatter has five analysis modes. This tour showed `--target-project`. The others:

| Mode | What it does | Needs AI? |
|------|-------------|-----------|
| `--target-project` | Find consumers of a specific .csproj | No |
| `--branch-name` | Diff a feature branch, trace changed types | No |
| `--stored-procedure` | Find C# consumers of a stored procedure | No |
| `--sow` / `--sow-file` | Natural language → blast radius | Yes |
| `--graph` | Full dependency graph with health metrics | No |

## Try it on your code

Point Scatter at your own .NET codebase:

```bash
uv run scatter --target-project ./path/to/Your.Project.csproj --search-scope /path/to/repo
```

See [Getting Started](getting-started.md) for full installation and [CLI Reference](cli-reference.md) for every flag.
