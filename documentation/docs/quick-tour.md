# Quick Tour

See what Scatter does in under 5 minutes. No API key needed.

## What you'll see

Scatter analyzes a .NET codebase and tells you which projects are affected by a change. You point it at a project, and it traces every consumer through project references, namespace usage, and type matching. The output shows the blast radius — who depends on what you're changing, and how tightly coupled they are.

## Step 1: Find all consumers

After [installing](getting-started.md), run this from the scatter repo root:

```bash
uv run scatter \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope .
```

This analyzes the sample `GalaxyWorks.Data` project and finds every project that consumes it:

```
Search scope: /code/scatter (scanned 11 projects, 27 files)
Filter: 11 → 7 project refs[graph] → 6 namespace

============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
  Consumers: 6

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  GalaxyWorks.WebPortal                       12.7       1       1    0.50 GalaxyWorks.sln
  GalaxyWorks.BatchProcessor                  10.8       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Api                              7.1       0       2    1.00 GalaxyWorks.sln
  MyGalaryConsumerApp                          4.3       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Data.Tests                       3.5       0       2    1.00 GalaxyWorks.sln
  MyGalaryConsumerApp2                         1.8       0       1    1.00 GalaxyWorks.sln

Analysis complete. 6 consumer(s) found across 1 target(s).
```

**Filter line** — the analysis funnel. Started with 11 projects, narrowed to 7 that have a project reference to GalaxyWorks.Data, then to 6 that actually use its namespace. Each stage cuts aggressively so you see real consumers, not false positives.

**Consumer table** — every project that depends on GalaxyWorks.Data, sorted by coupling score (highest risk first). If you change `PortalDataService`, these are the projects that might break.

**Graph columns** — automatically computed from the dependency graph:

- **Score** — coupling score: how connected this project is (higher = more risk when changing)
- **Fan-In / Fan-Out** — incoming vs outgoing dependencies
- **Instab.** — instability index: 0.00 (stable, many dependents) to 1.00 (unstable, depends on others)

You didn't ask for graph metrics — Scatter builds the graph automatically on first run, caches it, and enriches every result.

!!! note
    Test projects (like `GalaxyWorks.Data.Tests`) appear as consumers because they reference the target. In production, exclude test directories via [`.scatter.yaml` configuration](configuration.md).

## Step 2: Narrow by class

Maybe you only touched `PortalDataService`, not the whole project:

```bash
uv run scatter \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . \
  --class-name PortalDataService
```

Now Scatter only reports projects that actually reference `PortalDataService` specifically. The consumer list gets shorter — only the projects that use that class show up.

## Step 3: See the full dependency graph

```bash
uv run scatter --graph --search-scope .
```

```
============================================================
  Dependency Graph Analysis
============================================================
  Projects: 11
  Dependencies: 31
  Solutions: 1
  Connected components: 3
  Circular dependencies: 0

  Top Coupled Projects:
  Project                                     Score   Fan-In  Fan-Out  Instab.
  ---------------------------------------- -------- -------- -------- --------
  GalaxyWorks.Data                             22.6        7        0     0.00
  GalaxyWorks.WebPortal                        12.7        1        1     0.50
  GalaxyWorks.BatchProcessor                   10.8        0        2     1.00
  GalaxyWorks.Common                           10.0        3        1     0.25
  GalaxyWorks.Api                               7.1        0        2     1.00

  Domain Clusters:
  Cluster                          Size   Cohesion   Coupling          Feasibility    Align
  ------------------------------ ------ ---------- ---------- -------------------- --------
  cluster_0                           8      0.518      0.000         easy (1.000)     1.00
  MyDotNetApp                         2      1.000      0.000         easy (1.000)     0.50

  Observations:
    [warning] GalaxyWorks.Data: stable core (fan_in=7, instability=0.00) — change carefully
    [warning] GalaxyWorks.Data: high coupling score (22.6) — review dependencies
    [info] dbo.sp_InsertPortalConfiguration: shared by 3 projects — database coupling hotspot
```

This builds the complete dependency graph, computes coupling metrics, detects cycles, identifies domain clusters, and generates observations.

## What just happened

The filter pipeline works like a funnel:

1. **Discovery** — found all `.csproj` files in the search scope
2. **Project reference filter** — kept only the ones with a `<ProjectReference>` pointing at the target
3. **Namespace filter** — of those, kept only the ones whose `.cs` files contain the target's `using` statement
4. **Type/class filter** — of those, kept only the ones that actually reference specific types

Each stage cuts aggressively. The numbers in the filter line show exactly where projects got filtered out and why.

Meanwhile, Scatter quietly built a dependency graph and cached it to disk. On your next run, it loads from cache (under 1 second). After that, it detects changes via `git diff` and patches incrementally (~10ms).

## Get a shareable report

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

## All five modes

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

See [CLI Reference](cli-reference.md) for every flag, or dive into a specific mode:

- [Target Project Analysis](usage/target-project.md)
- [Git Branch Analysis](usage/git-branch.md)
- [Impact Analysis](usage/impact-analysis.md)
- [Output Formats](output-formats.md)
- [Configuration](configuration.md)
