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

The filter line shows the funnel: 13 projects in scope, 9 with a `<ProjectReference>` to the target, test projects excluded, 7 that actually use the namespace. Consumers are sorted by coupling score — highest risk first. Graph metrics (Score, Fan-In, Fan-Out, Instability) are computed automatically from the cached dependency graph.

Add `--class-name PortalDataService` to narrow to consumers that reference a specific type. Add `--parser-mode hybrid` to use tree-sitter AST validation and eliminate false positives in comments and string literals. See [Target Project Analysis](usage/target-project.md).

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

Builds the full graph, computes coupling metrics, detects cycles, and identifies domain clusters. See [Graph Engine](reference/graph-engine.md).

## Describe a change, get the blast radius

With a Google API key (`export GOOGLE_API_KEY=your-key`):

```bash
uv run scatter \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation" \
  --search-scope .
```

The AI parses your work request into concrete targets, Scatter traces the blast radius, and the report includes risk ratings, coupling narratives, and a complexity estimate. Add `--scope-estimate` for an effort breakdown with confidence bands. See [Impact Analysis](usage/impact-analysis.md) and [SOW Scoping](usage/scoping.md).

## Score a PR's risk

```bash
uv run scatter --branch-name feature/refactor-data --pr-risk --search-scope .
```

Deterministic score (GREEN/YELLOW/RED) across structural coupling, database coupling, blast radius, and change surface dimensions. No AI needed. The [GitHub Action template](reference/github-action.md) posts this as a PR comment automatically. See [PR Risk Scoring](usage/pr-risk.md).

## All six modes

| Mode | What it does | Needs AI? |
|------|-------------|-----------|
| `--target-project` | Find consumers of a specific .csproj | No |
| `--branch-name` | Diff a feature branch, trace changed types | No |
| `--stored-procedure` | Find C# consumers of a stored procedure | No |
| `--sow` / `--sow-file` | Natural language → blast radius | Yes |
| `--graph` | Full dependency graph with health metrics | No |
| `--pr-risk` | Score a branch across coupling, blast radius, and DB dimensions | No |

## Try it on your code

```bash
uv run scatter --target-project ./path/to/Your.Project.csproj --search-scope /path/to/repo
```

See [CLI Reference](cli-reference.md) for every flag, or [Output Formats](output-formats.md) for JSON, CSV, Markdown, and Mermaid options.
