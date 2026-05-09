# Quick Tour

See what Scatter does in under 5 minutes. No API key needed. Run everything from the scatter repo root against the included [sample projects](reference/sample-projects.md).

## Find consumers of a project

```bash
uv run scatter \
  --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope .
```

```
Filter: 13 → 9 project refs[graph] → 7 test-excluded[graph] → 7 namespace

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  GalaxyWorks.WebPortal                       12.7       1       1    0.50 GalaxyWorks.sln
  GalaxyWorks.BatchProcessor                  10.8       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Api                              7.1       0       2    1.00 GalaxyWorks.sln
  ...

Analysis complete. 7 consumer(s) found across 1 target(s).
```

Read the filter line left to right — it's a funnel. 13 projects in scope → 9 have a `<ProjectReference>` to the target → test projects excluded → 7 actually import the namespace. Each arrow is a stage that ruled something out.

Consumers are ranked by coupling score — the number that answers "how painful is this consumer to update?" High fan-in means lots of things depend on it (stable core — change carefully). High instability means it depends on many things but nothing depends on it (leaf — change freely).

Want to narrow further? `--class-name PortalDataService` limits to consumers that reference a specific type. `--parser-mode hybrid` uses tree-sitter to filter out matches in comments and string literals. See [Target Project Analysis](usage/target-project.md).

## See the full dependency graph

```bash
uv run scatter --graph --search-scope .
```

```
  Projects: 13 | Dependencies: 35 | Circular dependencies: 0

  Top Coupled Projects:
  GalaxyWorks.Data                             30.3        9        0     0.00
  GalaxyWorks.WebPortal                        12.7        1        1     0.50
  GalaxyWorks.BatchProcessor                   10.8        0        2     1.00
```

That's the full codebase X-ray. Coupling scores tell you which projects are load-bearing (high score = lots of things depend on it). Zero circular dependencies is good — when that number isn't zero, Scatter tells you exactly which projects are in the cycle. See [Dependency Graph](usage/dependency-graph.md).

## Describe a change, get the blast radius

With a Google API key (`export GOOGLE_API_KEY=your-key`):

```bash
uv run scatter \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation" \
  --search-scope .
```

Plain English in, risk-rated blast radius tree out. The AI identifies which projects and types match your description, Scatter traces every consumer, and the report shows risk ratings, coupling narratives, and a complexity estimate. Add `--scope-estimate` for an effort breakdown with confidence bands. See [Impact Analysis](usage/impact-analysis.md) and [SOW Scoping](usage/scoping.md).

## Score a PR's risk

```bash
uv run scatter --branch-name feature/refactor-data --pr-risk --search-scope .
```

Deterministic score — same branch against the same graph always produces the same number. GREEN means low risk, YELLOW means review it, RED means it's touching core infrastructure. No AI needed. The [GitHub Action template](reference/github-action.md) posts this as a PR comment automatically. See [PR Risk Scoring](usage/pr-risk.md).

## Get an AI analysis report

Add `--ai-summary` to any consumer analysis command. One Gemini API call, structured markdown back.

```bash
uv run scatter \
  --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --ai-summary
```

Returns a multi-section report: executive summary for your manager, technical risk analysis with consumer categorization and coupling outliers, and 3-4 specific recommendations. No source code is sent — just project names and coupling metrics. See [AI Features](ai-features.md#report-level-ai-summary).

## All seven modes

| Mode | What it does | Needs AI? |
|------|-------------|-----------|
| `--target-project` | Find consumers of a specific .csproj | No |
| `--branch-name` | Diff a feature branch, trace changed types | No |
| `--stored-procedure` | Find C# consumers of a stored procedure | No |
| `--sow` / `--sow-file` | Natural language → blast radius | Yes |
| `--graph` | Full dependency graph with health metrics | No |
| `--pr-risk` | Score a branch across coupling, blast radius, and DB dimensions | No |
| `--sproc-inventory` | Catalog all sprocs: .sql definitions vs C# references, coverage metric | No |

## Try it on your code

```bash
uv run scatter --target-project ./path/to/Your.Project.csproj --search-scope /path/to/repo
```

See [CLI Reference](cli-reference.md) for every flag, or [Output Formats](output-formats.md) for JSON, CSV, Markdown, and Mermaid options.
