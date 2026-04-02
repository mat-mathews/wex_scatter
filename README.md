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

**A .NET dependency analyzer that maps the blast radius of code changes.**

Point it at a `.csproj`, a branch, a stored procedure, or a plain-English work request — scatter tells you every project affected, which pipelines need to run, and how risky the change is.

[![CI](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml/badge.svg)](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## What it replaces

| Manual process | Scatter equivalent |
|----------------|-------------------|
| Search for class names across hundreds of projects | `scatter --target-project ./Shared.Data.csproj --search-scope .` |
| Track down every caller of a stored procedure | `scatter --stored-procedure "dbo.sp_UpdateUser" --search-scope .` |
| Review a branch diff and trace downstream impact | `scatter --branch-name feature/new-auth --repo-path .` |
| Read a work request and estimate blast radius | `scatter --sow "Add tenant isolation to portal config" --search-scope .` |

---

## Highlights

- **Five analysis modes** — git branch, target project, stored procedure, natural-language impact analysis, and full graph health
- **Zero-config graph acceleration** — builds a dependency graph on first run, caches it, patches incrementally via `git diff` on subsequent runs
- **Graph-enriched output** — coupling score, fan-in/out, instability index, and cycle membership on every result
- **Graph-derived risk engine** — 6-dimension risk profiles (structural coupling, instability, cycles, database coupling, blast radius, domain boundaries) with weighted-max composite scoring
- **AI-powered impact analysis** — describe a change in plain English, get affected projects, risk ratings, and effort estimates
- **Six output formats** — console, JSON, CSV, markdown, Mermaid diagrams, and a pipe-friendly pipeline list
- **CI-ready** — GitHub Action template for automatic PR impact comments

---

## Install

```bash
git clone https://github.com/mat-mathews/wex_scatter.git
cd wex_scatter
uv sync        # or: pip install .
```

After install, run via `uv run scatter` (or just `scatter` if you `pip install`). The repo ships with 13 sample .NET projects — every command below works out of the box.

For full development setup (uv, deps, git config, Claude Code skills): `bash tools/setup.sh` (or `pwsh tools/setup.ps1` on Windows)

### Docker

No Python required. Mount your repo and go:

```bash
docker build -t scatter .
docker run -v /path/to/repo:/workspace scatter \
  --target-project /workspace/MyApp/MyApp.csproj --search-scope /workspace
```

See [Docker usage](documentation/docs/usage/docker.md) for AI features, interactive sessions, and cache persistence.

---

## Quick tour

### Find consumers of a project

```bash
$ scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

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
  ...
```

`--search-scope` tells scatter where to look (recursively scans for `.csproj` and `.cs` files). Narrow further with `--class-name` or `--method-name`.

### Trace a stored procedure

```bash
$ scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
  Consumers: 6
  Triggering type: PortalDataService (via Sproc: dbo.sp_InsertPortalConfiguration)

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  GalaxyWorks.WebPortal                       12.7       1       1    0.50 GalaxyWorks.sln
  GalaxyWorks.BatchProcessor                  10.8       0       2    1.00 GalaxyWorks.sln
  ...
```

Stored procedure callers are invisible in project references — scatter finds them by scanning source.

### Check a branch's blast radius

```bash
$ scatter --branch-name feature/new-widget --repo-path .
```

Extracts type declarations from changed `.cs` files, maps them to projects, finds consumers. Compares against `main` by default (override with `--base-branch`). Add `--enable-hybrid-git` for LLM-enhanced diff analysis that filters to only the types whose body actually changed.

### Describe a change, get a risk report

```bash
$ scatter --sow "Add tenant isolation to the portal configuration system" --search-scope .

Impact Analysis — "Add tenant isolation to the portal configuration system"
──────────────────────────────────────────────────────────────────────────
Targets identified: 2 (confidence: clear)
  PortalDataService    → 6 direct consumers, 0 transitive
  PortalConfiguration  → 4 direct consumers, 0 transitive

Overall Risk: MEDIUM    Complexity: moderate    Estimated Effort: 3-5 days
```

Requires `GOOGLE_API_KEY` in your environment. Scatter builds a codebase index from the dependency graph and sends it as grounding context — the AI selects from known projects and types, not thin air. Risk ratings and effort estimates are AI-generated approximations, not engineering commitments. Accepts a file with `--sow-file`.

### Map your architecture

```bash
$ scatter --graph --search-scope .

============================================================
  Dependency Graph Analysis
============================================================
  Projects: 11    Dependencies: 31    Cycles: 0

  Top Coupled Projects:
  Project                        Score   Fan-In  Fan-Out  Instab.
  GalaxyWorks.Data                22.6        7        0     0.00
  GalaxyWorks.WebPortal           12.7        1        1     0.50
  GalaxyWorks.BatchProcessor      10.8        0        2     1.00

  Domain Clusters:
  Cluster       Size   Cohesion   Coupling    Feasibility
  cluster_0        8      0.518      0.000    easy (1.000)
  MyDotNetApp      2      1.000      0.000    easy (1.000)
```

**Coupling score** = weighted sum of dependency edges. **Instability** = fan-out / (fan-in + fan-out) — 0.00 means stable core, 1.00 means leaf. Feasibility scoring considers cross-boundary coupling, shared databases, cycles, and API surface area.

---

## Performance

Benchmarks on synthetic codebases (Apple M2 Pro, `--mode full`, median of 3 runs):

| Scenario | 250 projects (4.7K files) | 800 projects (30K files) |
|----------|:---:|:---:|
| Full rebuild | 2.6s | 38.7s |
| 1 file edit | ~10ms | ~10ms |
| 10 file changes | 315ms | — |

The common case — editing a method body or adding an import — patches in under 15ms regardless of codebase size. The graph cache is versioned; scatter rebuilds automatically on format mismatch. Safety valves trigger a full rebuild when changes exceed incremental thresholds (>50 projects or >30% of files modified).

---

## AI features

AI features are optional. Set `GOOGLE_API_KEY` in your environment (shell profile or CI secrets — never in committed files) and scatter picks it up automatically.

| Feature | Flag | What it does |
|---------|------|-------------|
| **Impact analysis** | `--sow "..."` | Parse a work request, trace blast radius, rate risk |
| **Consumer summaries** | `--summarize-consumers` | 2-3 sentence explanation of what each consumer does with the dependency |
| **Hybrid type extraction** | `--enable-hybrid-git` | LLM identifies which types *actually changed* in a diff |
| **Budget cap** | `--max-ai-calls N` | Cap total API calls per run |

Scatter sends project names, type declarations, and dependency structure to the AI provider. Source code contents are not sent. All calls go through a rate-limited proxy with exponential backoff. If the budget is exhausted or the provider is down, analysis continues without AI enrichment — no crash, no hang. Tune further with `--sow-min-confidence` and `--max-depth` ([details](documentation/docs/usage/impact-analysis.md)).

---

## Documentation

### Using scatter

- [Quick Tour](documentation/docs/quick-tour.md) — feature walkthrough
- [Target Project](documentation/docs/usage/target-project.md) — find all consumers of a project
- [Git Branch](documentation/docs/usage/git-branch.md) — blast radius of a feature branch
- [Stored Procedure](documentation/docs/usage/stored-procedure.md) — trace sproc callers
- [Impact Analysis](documentation/docs/usage/impact-analysis.md) — SOW-driven risk assessment
- [Dependency Graph](documentation/docs/usage/dependency-graph.md) — architecture health check
- [Output Formats](documentation/docs/output-formats.md) — JSON, CSV, markdown, Mermaid, pipelines
- [Workflows](documentation/docs/workflows.md) — seven real-world scenarios
- [Configuration](documentation/docs/configuration.md) — YAML config, env vars, CLI flags
- [CLI Reference](documentation/docs/cli-reference.md) — every flag and option

### Understanding scatter

- [Architecture](documentation/docs/reference/architecture.md) — system design and data flow
- [Graph Engine](documentation/docs/reference/graph-engine.md) — caching, patching, edge types
- [Consumer Pipeline](documentation/docs/reference/consumer-pipeline.md) — 5-stage filter funnel
- [Coupling & Cycles](documentation/docs/reference/coupling-and-cycles.md) — metrics and algorithms
- [Domain Clustering](documentation/docs/reference/domain-clustering.md) — boundary detection and feasibility
- [Incremental Updates](documentation/docs/reference/incremental-updates.md) — how graph patching works
- [Codebase Index](documentation/docs/reference/codebase-index.md) — how scatter grounds LLM prompts in real code artifacts
- [Type Extraction](documentation/docs/reference/type-extraction.md) — C# regex + LLM hybrid
- [Benchmarks](documentation/docs/reference/benchmarks.md) — performance methodology and results

### Contributing

- [Getting Started](documentation/docs/getting-started.md) — setup and first run
- [Development](documentation/docs/reference/development.md) — tooling, linting, CI
- [Contributing](documentation/docs/reference/contributing.md) — code organization, PR checklist
- [Test Architecture](documentation/docs/reference/test-architecture.md) — test strategy and patterns
- [Sample Projects](documentation/docs/reference/sample-projects.md) — the 11 .NET test fixtures
- [GitHub Action](documentation/docs/reference/github-action.md) — PR automation setup
- [Claude Skills](documentation/docs/reference/claude-skills.md) — Claude Code integration

---

## Roadmap

**Next** — PR risk scoring (GitHub Action posts risk comment on every PR), SOW scoping (effort estimates with confidence bands)

**Recently shipped** — Unified risk engine: 6-dimension graph-derived risk profiles with weighted-max composite scoring, piecewise linear interpolation, structured logging, 3 built-in contexts (PR, SOW, local dev)

**Planned** — CI/CD exit codes (`--fail-on cycles`, `--fail-on risk:high`), baselines & diff reports, extraction planning

**Deferred** — Unified report model, watch mode, AI response caching, HTML reports with D3.js visualization

---

## License

Internal tooling. See repository for details.
