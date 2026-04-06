# Scatter

```bash
$ scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

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

**If I change this project, what breaks?**

Scatter answers that question for .NET codebases. Point it at a `.csproj`, a branch, or a stored procedure name — it tells you every project affected and shows the work: `11 → 7 project refs → 6 namespace`. That filter chain is the whole idea. Instead of grepping and guessing, you get a progressive narrowing from hundreds of candidates down to the actual consumers.

[![CI](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml/badge.svg)](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## Install

```bash
git clone https://github.com/mat-mathews/wex_scatter.git
cd wex_scatter
uv sync        # or: pip install .
```

The repo ships with 13 sample .NET projects — every command below works out of the box.

---

## What it does

### Find consumers of a project

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

Five-stage filter: discover all `.csproj` files in scope, check project references, match namespaces, match class usage, optionally match method usage. Narrow further with `--class-name` or `--method-name`.

### Trace a stored procedure

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```

Stored procedure callers are invisible in project references — the coupling lives in string literals inside data access layers. Scatter scans source files, finds the containing class, then runs consumer detection on that class. The output shows the full chain: sproc → class → consumer projects.

### Check a branch's blast radius

```bash
scatter --branch-name feature/new-widget --repo-path .
```

Diffs against `main` (override with `--base-branch`), extracts type declarations from changed `.cs` files, finds consumers of each type. Add `--enable-hybrid-git` with a Google API key for LLM-assisted diff analysis that filters to only the types whose body actually changed.

### Map your architecture

```bash
scatter --graph --search-scope .
```

Builds a dependency graph of all projects in scope. Reports coupling scores, fan-in/out, instability, circular dependencies (via Tarjan's SCC), and domain clusters with extraction feasibility scoring. The graph uses four edge types — project references, namespace usage, type usage, and shared stored procedures — each with configurable weights.

### Map consumers to pipelines

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope . --pipeline-csv examples/pipeline_to_app_mapping.csv \
    --output-format pipelines

galaxyworks-portal-az-cd
```

Pipeline mapping works via solution stem — the CSV's `Application Name` column matches against `.sln` file stems. An example CSV ships at `examples/pipeline_to_app_mapping.csv`.

---

## The graph

Scatter builds a dependency graph on first run and caches it. Subsequent runs patch incrementally via `git diff` — a 10-file change on a 500-project repo patches in under a second. The graph accelerates consumer detection (stages 1-2 use reverse index lookups instead of filesystem scanning) and enriches every result with coupling score, fan-in/out, instability, and cycle membership.

No flags to remember. If a cache exists, it's used. If it's stale, it's patched. If it doesn't exist, it's built. `--no-graph` opts out; `--rebuild-graph` forces a fresh build.

---

## What else it does

Scatter has additional capabilities built on top of the core consumer detection and graph infrastructure:

- **PR risk scoring** — `--pr-risk` scores a branch's changes across multiple risk dimensions (structural coupling, cycles, blast radius, database coupling, domain boundaries, change surface). Outputs a GREEN/YELLOW/RED composite. A [GitHub Action template](tools/github-action/scatter-pr-risk.yml) automates this on every PR.

- **Impact analysis** — `--sow "Add tenant isolation to portal config"` parses a plain-English work request, identifies affected projects using a graph-derived codebase index, and traces consumers. Requires `GOOGLE_API_KEY`.

- **SOW scoping** — `--scope-estimate` adds structured effort breakdowns on top of impact analysis, with categories for investigation, implementation, testing, integration risk, and database migration.

- **Six output formats** — console, JSON, CSV, markdown, Mermaid diagrams, and a pipe-friendly pipeline list (`--output-format pipelines | xargs ...`).

- **AI consumer summaries** — `--summarize-consumers` generates short explanations of what each consumer does with the dependency.

---

## AI features

All AI features are optional. Core analysis — consumer detection, graph building, coupling metrics, cycle detection — never requires an API key.

Set `GOOGLE_API_KEY` in your environment and Scatter picks it up. All AI calls go through a rate-limited proxy with exponential backoff. If the provider is down or the budget is exhausted (`--max-ai-calls N`), analysis continues without AI enrichment.

---

## Documentation

- [Quick Tour](documentation/docs/quick-tour.md) — feature walkthrough
- [Target Project](documentation/docs/usage/target-project.md) — find all consumers of a project
- [Git Branch](documentation/docs/usage/git-branch.md) — blast radius of a feature branch
- [Stored Procedure](documentation/docs/usage/stored-procedure.md) — trace sproc callers
- [Impact Analysis](documentation/docs/usage/impact-analysis.md) — SOW-driven risk assessment
- [PR Risk Scoring](documentation/docs/usage/pr-risk.md) — risk-score every pull request
- [Dependency Graph](documentation/docs/usage/dependency-graph.md) — architecture health check
- [Output Formats](documentation/docs/output-formats.md) — JSON, CSV, markdown, Mermaid, pipelines
- [Configuration](documentation/docs/configuration.md) — YAML config, env vars, CLI flags
- [CLI Reference](documentation/docs/cli-reference.md) — every flag and option
- [Architecture](documentation/docs/reference/architecture.md) — system design and data flow
- [ADRs](docs/ADR.md) — architecture decision records

---

## License

Internal tooling. See repository for details.
