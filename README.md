# Scatter

```bash
$ scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

Search scope: /code/myrepo (scanned 11 projects, 27 files)
Filter: 11 → 7 project refs[graph] → 6 namespace

Target: GalaxyWorks.Data (6 consumers)
  → GalaxyWorks.Api            coupling=7.1   instability=1.00   in-cycle=no
  → GalaxyWorks.BatchProcessor coupling=10.8   instability=1.00   in-cycle=no
  → GalaxyWorks.WebPortal      coupling=12.7   instability=0.50   in-cycle=no
  → MyGalaxyConsumerApp        coupling=4.3   instability=1.00   in-cycle=no
  → MyGalaxyConsumerApp2       coupling=1.8   instability=1.00   in-cycle=no
  → GalaxyWorks.Data.Tests     coupling=3.5   instability=1.00   in-cycle=no
```

**A .NET dependency analyzer that maps the blast radius of code changes.**

Point it at a `.csproj`, a branch, a stored procedure, or a plain-English work request — scatter tells you every project affected, which pipelines need to run, and how risky the change is.

[![CI](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml/badge.svg)](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-2.1.0-green.svg)](https://github.com/mat-mathews/wex_scatter)

---

## What it replaces

| Manual process | Scatter equivalent |
|----------------|-------------------|
| Search for class names across hundreds of projects | `scatter --target-project ./Shared.Data.csproj --search-scope .` |
| Track down every caller of a stored procedure | `scatter --stored-procedure "dbo.sp_UpdateUser" --search-scope .` |
| Review a branch diff and trace downstream impact | `scatter --branch-name feature/new-auth --repo-path .` |
| Read a work request and identify affected teams | `scatter --sow "Add tenant isolation to portal config" --search-scope .` |
| Estimate blast radius for a change ticket | Coupling scores, instability metrics, risk ratings — in one command |

---

## Highlights

- **Five analysis modes** — git branch, target project, stored procedure, natural-language impact analysis, and full graph health
- **Zero-config graph acceleration** — builds a dependency graph on first run, caches it, patches incrementally via `git diff` on subsequent runs
- **Graph-enriched output** — every consumer result includes coupling score, fan-in/out, instability index, and cycle membership. Automatically.
- **AI-powered impact analysis** — describe a change in plain English, get back affected projects, risk ratings, and effort estimates
- **Six output formats** — console, JSON, CSV, markdown, Mermaid diagrams, and a pipe-friendly pipeline list
- **Parallel by default** — multiprocessing for file discovery, XML parsing, and content analysis
- **CI-ready** — GitHub Action template for automatic PR impact comments

---

## Table of Contents

1. [Install](#install)
2. [Quick Tour](#quick-tour) — five modes in 60 seconds
3. [How It Works](#how-it-works) — graph engine, filter pipeline, edge types
4. [Output Formats](#output-formats)
5. [AI Features](#ai-features) — impact analysis, consumer summaries, hybrid extraction
6. [Configuration](#configuration)
7. [CI/CD Integration](#cicd-integration)
8. [Development](#development) — setup, testing, benchmarks
9. [Sample Projects](#sample-projects)
10. [FAQ](#faq)
11. [Documentation](#documentation)
12. [Roadmap](#roadmap)

---

## Install

```bash
# With uv (recommended)
git clone https://github.com/mat-mathews/wex_scatter.git
cd wex_scatter
bash tools/setup.sh     # installs uv, deps, configures git, links Claude skills

# Or just uv sync if you already have uv
uv sync

# Or pip
pip install .
```

The repo ships with 11 sample .NET projects forming two dependency chains — every command on this page works out of the box.

---

## Quick tour

### Find consumers of a project

```bash
$ scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

Target: GalaxyWorks.Data (6 consumers)
  → GalaxyWorks.Api            coupling=7.1   instability=1.00
  → GalaxyWorks.BatchProcessor coupling=10.8   instability=1.00
  → GalaxyWorks.WebPortal      coupling=12.7   instability=0.50
  ...
```

Drill deeper with `--class-name PortalDataService` or `--method-name StorePortalConfigurationAsync`.

### Trace a stored procedure

```bash
$ scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

Target: GalaxyWorks.Data (6 consumers)
    Type/Level: PortalDataService (via Sproc: dbo.sp_InsertPortalConfiguration)
      → GalaxyWorks.Api
      → GalaxyWorks.BatchProcessor
      → GalaxyWorks.WebPortal
      ...
```

Stored procedure callers are invisible in project references — scatter finds them by scanning source.

### Check a branch's blast radius

```bash
$ scatter --branch-name feature/new-widget --repo-path .
```

Extracts type declarations from changed `.cs` files, maps them to projects, finds consumers. Add `--enable-hybrid-git` with an API key for LLM-enhanced diff analysis that filters to only the types whose body actually changed.

### Describe a change, get a risk report

```bash
$ scatter --sow "Add tenant isolation to the portal configuration system" \
    --search-scope . --google-api-key $GOOGLE_API_KEY

Impact Analysis — "Add tenant isolation to the portal configuration system"
──────────────────────────────────────────────────────────────────────────
Targets identified: 2 (confidence: clear)
  PortalDataService    → 6 direct consumers, 0 transitive
  PortalConfiguration  → 4 direct consumers, 0 transitive

Overall Risk: MEDIUM    Complexity: moderate    Estimated Effort: 3-5 days
```

Accepts plain text or a file (`--sow-file docs/work_request.md`). AI parses the request into targets, traces consumers transitively, and rates risk.

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

  Observations:
    [warning] GalaxyWorks.Data: stable core (fan_in=7, instability=0.00) — change carefully
```

Coupling metrics, Tarjan's cycle detection, domain clustering with extraction feasibility scoring. Output as console, JSON, CSV, markdown, or Mermaid.

---

## How it works

### The graph engine

On first run, scatter builds a dependency graph from your `.csproj` and `.cs` files in a single pass:

```
search_scope/
  ├─ Discover .csproj files → parse references, namespace, framework
  ├─ Discover .cs files → map to parent project
  ├─ Extract type declarations, using statements, sproc references
  └─ Build edges: project_reference, namespace_usage, type_usage, sproc_shared
```

The graph is cached to `.scatter/graph_cache.json`. On subsequent runs, scatter uses `git diff` to patch only what changed:

| Scenario | 250 projects | 800 projects (30K files) |
|----------|:---:|:---:|
| Full rebuild | 2.6s | 38.7s |
| 1 file change (body edit) | 10ms (954x faster) | ~10ms |
| 10 file changes | 315ms | — |
| 1 csproj modified | 38ms (253x) | — |

Consumer lookups that used to scan every file on disk now resolve via O(1) reverse-index lookup.

### The filter pipeline

Consumer detection runs a 5-stage pipeline with early exit:

```
All .csproj → project references → namespace usage → class usage → method usage
   11      →        7           →        6        →      4      →       2
```

Each stage narrows the candidate set. Add `-v` to see where candidates drop out and why.

### Edge types

| Edge | What it means | Weight |
|------|--------------|:------:|
| `project_reference` | `<ProjectReference>` in .csproj | 1.0 |
| `namespace_usage` | `using` statement match | 0.5 |
| `type_usage` | Direct type reference | 0.3 |
| `sproc_shared` | Stored procedure used by multiple projects | 0.8 |

Weights are configurable in `.scatter.yaml`.

### Graph controls

| Flag | Effect |
|------|--------|
| *(default)* | Auto-build on first run, cache, incremental patching |
| `--no-graph` | Skip all graph operations |
| `--rebuild-graph` | Force a full rebuild, ignore cache |
| `--graph` | Dedicated graph analysis mode with metrics and clusters |

---

## Output formats

```bash
# Console (default)
scatter --target-project ./Lib.csproj --search-scope .

# JSON — structured data with metadata
scatter ... --output-format json --output-file results.json

# CSV — one row per consumer, ready for spreadsheets
scatter ... --output-format csv --output-file results.csv

# Markdown — paste into a PR or wiki
scatter ... --output-format markdown --output-file results.md

# Mermaid — dependency diagram
scatter --graph --search-scope . --output-format mermaid

# Pipelines — just the CI/CD pipeline names, one per line
scatter ... --output-format pipelines
```

---

## AI features

AI features are optional and require an API key. Set `GOOGLE_API_KEY` in your environment or pass `--google-api-key`.

| Feature | Flag | What it does |
|---------|------|-------------|
| **Impact analysis** | `--sow "..."` | Parse a work request, trace blast radius, rate risk |
| **Consumer summaries** | `--summarize-consumers` | 2-3 sentence explanation of what each consumer does with the dependency |
| **Hybrid type extraction** | `--enable-hybrid-git` | LLM identifies which types *actually changed* in a diff (reduces false positives) |

### Providers

| Provider | Status |
|----------|--------|
| Google Gemini | Working default |
| WEX AI Platform | Stubbed — will be primary once API contract is finalized |

Switch via config (`ai.default_provider`) or env var (`SCATTER_DEFAULT_PROVIDER`).

---

## Configuration

Layered config with clear precedence:

```
CLI flags  >  .scatter.yaml (repo)  >  ~/.scatter/config.yaml (user)  >  env vars  >  defaults
```

```yaml
# .scatter.yaml
graph:
  coupling_weights:
    project_reference: 1.0
    namespace_usage: 0.5
    type_usage: 0.3
    sproc_shared: 0.8

ai:
  default_provider: gemini

db:
  include_db: true
  sproc_prefixes: ["sp_", "usp_", "fn_"]
```

See the [configuration docs](documentation/docs/configuration.md) for all options.

---

## CI/CD integration

### GitHub Action

Drop the [workflow template](tools/github-action/) into your .NET repo. On every PR, scatter posts an impact analysis comment — affected projects, pipelines, risk rating. One YAML file, no marketplace action, no org approvals.

### Pipeline mapping

Map consumer projects to their CI/CD pipelines via CSV:

```bash
scatter --target-project ./Shared.Data.csproj --search-scope . \
  --pipeline-csv build/pipeline_map.csv --output-format pipelines
```

Output: one pipeline name per line, ready to pipe into your deployment tool.

---

## Development

```bash
# One-command setup (installs uv, deps, git config, Claude skills)
bash tools/setup.sh
```

### Testing

```bash
# All tests (unit + integration, ~22 seconds)
bash tools/test.sh

# Unit tests only (~6 seconds)
bash tools/test.sh unit

# Integration tests only (~15 seconds)
bash tools/test.sh integration

# Smoke tests against sample projects
bash tools/test.sh smoke

# Full CI mirror (lint + format + mypy + all tests + smoke)
bash tools/test.sh full

# Coverage report
bash tools/test.sh coverage
```

Or use pytest directly:

```bash
uv run pytest                              # all tests
uv run pytest tests/unit                   # unit only
uv run pytest tests/integration            # integration only
uv run pytest tests/unit/test_graph.py -v  # single file, verbose
uv run pytest -k "coupling"               # keyword filter
```

#### Test layout

```
tests/
├── conftest.py          # Shared fixtures
├── unit/                # ~640 tests — isolated, fast (~6s)
└── integration/         # ~175 tests — multi-module, filesystem (~15s)
```

See [docs/TESTING.md](docs/TESTING.md) for the full testing guide.

### Local CI

```bash
# Full check (lint + format + mypy + pytest)
bash tools/check.sh

# Quick lint-only (~2 seconds)
bash tools/check.sh --quick
```

### Benchmarking

Scatter includes benchmark tooling for measuring performance at scale using a synthetic codebase generator:

```bash
# Generate a synthetic monolith
python tools/generate_synthetic_codebase.py --preset xlarge --output /tmp/synthetic

# Benchmark full graph build (threaded, production-like)
python tools/benchmark_graph_build.py /tmp/synthetic --mode full

# Benchmark incremental patching (9 mutation scenarios)
python tools/benchmark_incremental.py --preset small medium large
```

**Performance at scale (synthetic codebase, `--mode full`):**

| Scale | Projects | Files | Full rebuild |
|-------|:--------:|:-----:|:------------:|
| Medium | 250 | 4.7K | 2.6s |
| XLarge | 800 | 30K | 38.7s |

Incremental patches (the common case — editing method bodies, adding imports) run 10-954x faster than full rebuilds.

### Using with Claude Code

If you have Claude Code, the setup script links 5 skills automatically. Then just ask:

- *"Who uses GalaxyWorks.Data?"*
- *"What's the blast radius of adding tenant isolation to portal configuration?"*
- *"Show me the dependency health of this codebase"*

---

## Sample projects

The repo includes 11 .NET projects forming two dependency chains:

```
GalaxyWorks.Data                    ← stable core, 7 consumers
├── GalaxyWorks.WebPortal           ← mid-tier, 1 consumer
│   └── GalaxyWorks.BatchProcessor  ← leaf
├── GalaxyWorks.Api                 ← leaf
├── GalaxyWorks.Common              ← shared utilities
├── GalaxyWorks.Data.Tests          ← test project
├── MyGalaxyConsumerApp             ← leaf
└── MyGalaxyConsumerApp2            ← leaf

MyDotNetApp                         ← independent chain
└── MyDotNetApp.Consumer

MyDotNetApp2.Exclude                ← standalone (tests zero-consumer case)
```

Every command on this page runs against these projects. No external codebase needed.

---

## FAQ

**Does it work with .NET Framework, or only SDK-style projects?**
Both. Scatter parses `<ProjectReference>` tags regardless of project style. Type extraction uses regex on `.cs` files, so it works with any C# version.

**How accurate is the consumer detection?**
Scatter uses regex-based analysis, not Roslyn AST parsing. It can miss conditional compilation, source generators, and some nested type patterns. In practice, the 5-stage filter pipeline keeps false positive rates low. Known limitations are documented in the [architecture reference](documentation/docs/reference/architecture.md).

**How large a codebase can it handle?**
11 sample projects build in ~1 second. 250 projects in 2.6 seconds. 800 projects with 30K files in 38.7 seconds. Incremental patches run in 10-315ms. Performance at 1000+ projects is under active testing.

**Do I need an API key?**
Only for AI features (impact analysis, consumer summaries, hybrid type extraction). All graph, consumer detection, and stored procedure analysis features work without any API key.

**What's the `--no-graph` flag for?**
Skips the graph engine entirely for a filesystem-only scan. Useful for debugging — though `--rebuild-graph` is usually the better call.

---

## Documentation

Full docs: [scatter documentation site](documentation/docs/)

- [Getting Started](documentation/docs/getting-started.md) — setup and first run
- [Quick Tour](documentation/docs/quick-tour.md) — feature walkthrough
- [CLI Reference](documentation/docs/cli-reference.md) — every flag and option
- [Configuration](documentation/docs/configuration.md) — YAML config, env vars, precedence
- [Architecture](documentation/docs/reference/architecture.md) — how scatter works internally
- [Graph Engine](documentation/docs/reference/graph-engine.md) — caching, patching, edge types
- [Test Architecture](documentation/docs/reference/test-architecture.md) — test strategy and structure

---

## Roadmap

### Next

- **Focused SOW index** — solution-scoped index for `--sow` mode with LLM-driven solution discovery
- **CI/CD exit codes** — `--fail-on cycles`, `--fail-on risk:high`, `--fail-on coupling:15.0` for governance gates

### Planned

- **Baselines & diff reports** — snapshot graph + metrics, compare over time, track modernization progress
- **Extraction planning** — `scatter extract` with API surface analysis, consumer inventory, shared data dependencies
- **HTML reports** — self-contained interactive reports with D3.js dependency visualization

### Deferred

Unified report data model, watch mode, AI response caching, token budget manager — see `tasks.txt` for details.

---

## License

Internal tooling. See repository for details.
