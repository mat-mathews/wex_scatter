# Scatter

Someone asks "what breaks if we change this?" and three people get in a room to guess. Scatter replaces the room.

Point it at a .NET project, a feature branch, a stored procedure, or just a plain-English work request — it traces every consumer, scores the coupling, maps the pipelines, and tells you the risk. Not a guess. Structural data from the actual codebase.

[![CI](https://github.com/ORG/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/ORG/REPO/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## Try it

```bash
git clone https://github.com/ORG/REPO.git
cd REPO
docker build -t scatter .
```

The repo ships with 13 sample .NET projects. Analyze `GalaxyWorks.Data` to see who depends on it:

```bash
MSYS_NO_PATHCONV=1 docker run -v "$(pwd)":/workspace scatter \
    --target-project /workspace/samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope /workspace \
    --pipeline-csv /workspace/examples/pipeline_to_app_mapping.csv
```

> `MSYS_NO_PATHCONV=1` prevents Git Bash on Windows from rewriting `/workspace` paths.

```
Search scope: /workspace (scanned 13 projects, 33 files)
Filter: 13 → 9 project refs[graph] → 8 test-excluded[graph] → 7 namespace

============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj)
  Consumers: 7

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  GalaxyWorks.WebPortal                       12.7       1       1    0.50 GalaxyWorks.sln
  GalaxyWorks.BatchProcessor                  10.8       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Api                              7.1       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.DevTools                         4.9       0       1    1.00 GalaxyWorks.sln
  MyGalaxyConsumerApp                          4.3       0       2    1.00 GalaxyWorks.sln
  GalaxyWorks.Notifications                    2.8       0       1    1.00 GalaxyWorks.sln
  MyGalaxyConsumerApp2                         1.8       0       1    1.00 GalaxyWorks.sln

  Pipelines affected: 5
    galaxyworks-api-az-cd (1 project(s))
      • GalaxyWorks.Api
    galaxyworks-batch-az-cd (1 project(s))
      • GalaxyWorks.BatchProcessor
    galaxyworks-devtools-az-cd (1 project(s))
      • GalaxyWorks.DevTools
    galaxyworks-notifications-az-cd (1 project(s))
      • GalaxyWorks.Notifications
    galaxyworks-portal-az-cd (1 project(s))
      • GalaxyWorks.WebPortal

Analysis complete. 7 consumer(s) found across 1 target(s).
```

13 projects in scope. 7 actual consumers. Ranked by coupling. 5 pipelines mapped. Test projects excluded automatically. That's the answer to "what breaks?" in under 3 seconds.

### Pipeline mapping

The pipeline CSV maps consumer project names to CI/CD pipeline names. Generate it from your app-config repo:

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$(pwd)":/workspace \
    -v /path/to/app-config-repo:/config:ro \
    python:3.12-slim \
    python /workspace/tools/generate_pipeline_csv.py \
        --app-config-path /config \
        --output /workspace/examples/pipeline_to_app_mapping.csv
```

Scatter uses layered matching (exact → case-insensitive → suffix-stripped → prefix) to resolve names. When it can't match, add manual entries to `examples/pipeline_manual_overrides.csv`. Manual entries take precedence.

---

## Six ways in

| Mode | The question it answers |
|------|------------------------|
| `--target-project` | Who consumes this project? |
| `--branch-name` | What's the blast radius of this branch? |
| `--stored-procedure` | Which C# services call this sproc? |
| `--sow` / `--sow-file` | What's the blast radius of this work request? (plain English in, risk-rated tree out) |
| `--graph` | What's the health of this codebase? (coupling, cycles, domain clusters) |
| `--pr-risk` | How risky is this PR? (GREEN/YELLOW/RED across 7 dimensions) |

Stored procedures are the invisible coupling that project references don't show. Scatter traces sproc callers through string literals in `.cs` files:

```bash
MSYS_NO_PATHCONV=1 docker run -v "$(pwd)":/workspace scatter \
    --stored-procedure "dbo.sp_InsertPortalConfiguration" \
    --search-scope /workspace
```

---

## How it works

Scatter walks your `.csproj` files and traces dependency chains through project references, `using` statements, class usage, and stored procedure calls. Each stage narrows the set — the filter line in the output shows exactly where projects got ruled out.

First run builds a dependency graph and caches it (~2.6s for 250 projects, ~39s for 800). After that, Scatter detects changes via `git diff` and patches incrementally — typical edits take ~10ms, 100-950x faster than rebuilding.

You never configure this. It just happens.

---

## CI integration

Every PR can get an automatic risk score:

```bash
scatter --branch-name feature/my-change --pr-risk \
  --repo-path . --search-scope . \
  --output-format markdown --collapsible
```

GREEN/YELLOW/RED across 7 dimensions, posted as a PR comment. There's a [GitHub Action template](tools/github-action/scatter-pr-risk.yml) ready to drop in.

---

## Documentation

Full docs live in `docs_site/`. Serve them locally:

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

- [Quick Tour](docs_site/docs/quick-tour.md) — guided walkthrough of all six modes
- [CLI Reference](docs_site/docs/cli-reference.md) — every flag and option
- [Configuration](docs_site/docs/configuration.md) — YAML config, env vars, pipeline mapping
- [Architecture](docs_site/docs/reference/architecture.md) — system design and data flow
- [Docker](docs_site/docs/usage/docker.md) — container usage and caching

---

Proprietary — for internal WEX use only.
