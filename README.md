# Scatter

Scatter is a dependency and risk analysis tool for .NET codebases. Point it at a project and it tells you what depends on it, how tightly coupled those consumers are, and which pipelines are involved.

[![CI](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml/badge.svg)](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## Try it

```bash
git clone https://github.com/mat-mathews/wex_scatter.git
cd wex_scatter
docker build -t scatter .
```

The repo ships with 13 sample .NET projects in the `samples/` directory. Analyze `GalaxyWorks.Data` to see what depends on it and which pipelines are involved:

```bash
MSYS_NO_PATHCONV=1 docker run -v "$(pwd)":/workspace scatter \
    --target-project /workspace/samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope /workspace \
    --pipeline-csv /workspace/examples/pipeline_to_app_mapping.csv
```

> `MSYS_NO_PATHCONV=1` prevents Git Bash on Windows from rewriting `/workspace` paths. It's a no-op on macOS and Linux — safe to include everywhere.

```
Search scope: /workspace (scanned 13 projects, 35 files)
Filter: 13 → 9 project refs → 8 namespace

============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
  Consumers: 8

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  GalaxyWorks.WebPortal                       12.7       1       1    0.50 GalaxyWorks.sln
  GalaxyWorks.BatchProcessor                  10.8       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Api                              7.1       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.DevTools                         4.9       0       1    1.00 GalaxyWorks.sln
  MyGalaryConsumerApp                          4.3       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Data.Tests                       3.5       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Notifications                    2.8       0       1    1.00 GalaxyWorks.sln
  MyGalaryConsumerApp2                         1.8       0       1    1.00 GalaxyWorks.sln

  Pipelines affected: 5
    galaxyworks-api-az-cd
    galaxyworks-batch-az-cd
    galaxyworks-devtools-az-cd
    galaxyworks-notifications-az-cd
    galaxyworks-portal-az-cd

Analysis complete. 8 consumer(s) found across 1 target(s).
```

Scatter narrowed 13 projects down to the 8 that actually consume GalaxyWorks.Data, ranked them by coupling, and resolved 5 CI/CD pipelines that would need to run.

### Pipeline mapping

The pipeline CSV maps application names to CI/CD pipeline names. Generate it from your app-config repo:

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$(pwd)":/workspace \
    -v /path/to/app-config-repo:/config:ro \
    python:3.12-slim \
    python /workspace/tools/generate_pipeline_csv.py \
        --app-config-path /config \
        --output /workspace/examples/pipeline_to_app_mapping.csv
```

For deployed apps the generator can't resolve, add manual entries to `examples/pipeline_manual_overrides.csv` (same schema, `source=manual`). Scatter loads both files; manual entries take precedence.

You can also trace stored procedures back to their consumers — coupling that's invisible in project references:

```bash
MSYS_NO_PATHCONV=1 docker run -v "$(pwd)":/workspace scatter \
    --stored-procedure "dbo.sp_InsertPortalConfiguration" \
    --search-scope /workspace
```

---

## Other workflows

- **PR risk scoring** — score a branch before merge across coupling, blast radius, and database dimensions. GREEN/YELLOW/RED composite with a [GitHub Action template](tools/github-action/scatter-pr-risk.yml) for automated PR comments. See [PR Risk Scoring](docs_site/docs/usage/pr-risk.md).

- **Impact analysis / SOW scoping** — analyze a plain-English work request, find affected targets and consumers, and generate a first-pass effort estimate. Requires `GOOGLE_API_KEY` for AI-assisted steps. Core analysis does not require an API key. See [Impact Analysis](docs_site/docs/usage/impact-analysis.md).

- **Dependency graph** — full project graph with coupling scores, cycle detection, and domain clustering. See [Dependency Graph](docs_site/docs/usage/dependency-graph.md).

For platform-specific Docker examples (PowerShell, macOS, Git Bash), cache volumes, and output file mounts, see [Docker](docs_site/docs/usage/docker.md).

---

## How it works

Scatter scans `.csproj` files and traces dependency chains through project references, `using` statements, and class/sproc usage. Each stage narrows aggressively — the filter line in the output shows exactly where projects were cut and why.

On first run it builds a dependency graph and caches it. Subsequent runs patch incrementally via `git diff`.

---

## Documentation

The full docs live in `docs_site/`. Serve them locally:

```bash
# Via Docker
MSYS_NO_PATHCONV=1 docker run --rm -it -p 8000:8000 \
    -v "$(pwd)":/docs -w /docs squidfunk/mkdocs-material \
    serve -f docs_site/mkdocs.yml -a 0.0.0.0:8000

# Or via uv (no Docker needed)
uv run --with-requirements docs_site/requirements-docs.txt \
    mkdocs serve -f docs_site/mkdocs.yml
```

Then open [http://localhost:8000](http://localhost:8000). Or browse the raw markdown:

- [Quick Tour](docs_site/docs/quick-tour.md) — guided walkthrough
- [Target Project](docs_site/docs/usage/target-project.md) — find all consumers of a project
- [Git Branch](docs_site/docs/usage/git-branch.md) — blast radius of a feature branch
- [Stored Procedure](docs_site/docs/usage/stored-procedure.md) — trace sproc callers
- [PR Risk Scoring](docs_site/docs/usage/pr-risk.md) — risk-score every pull request
- [Dependency Graph](docs_site/docs/usage/dependency-graph.md) — architecture health check
- [Docker](docs_site/docs/usage/docker.md) — container usage and caching
- [Output Formats](docs_site/docs/output-formats.md) — JSON, CSV, markdown, Mermaid, pipelines
- [Configuration](docs_site/docs/configuration.md) — YAML config, env vars, CLI flags
- [CLI Reference](docs_site/docs/cli-reference.md) — every flag and option
- [Architecture](docs_site/docs/reference/architecture.md) — system design and data flow
- [ADRs](docs/ADR.md) — architecture decision records

---

## License

Proprietary — for internal WEX use only. See [LICENSE](LICENSE) for terms.
