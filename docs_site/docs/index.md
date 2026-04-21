# Scatter

You changed a class. Which projects could break?

```bash
scatter --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

```
Search scope: /code/scatter (scanned 13 projects, 35 files)
Filter: 13 → 9 project refs[graph] → 8 namespace

============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj)
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

Analysis complete. 8 consumer(s) found across 1 target(s).
```

Eight consumers. Now you know who to warn before you merge.

---

You wrote a work request. What's the blast radius?

```bash
scatter --sow "Add tenant isolation to PortalDataService" --search-scope .
```

Scatter parses your intent, identifies the affected types, traces transitive consumers, and rates the risk — from a plain English sentence. No flags to learn, no types to look up manually.

---

**Ready to try it?** [Getting Started](getting-started.md) gets you running in five minutes.

## Six analysis modes

| Flag | What it does |
|------|-------------|
| `--target-project` | Point at a `.csproj`, find every project consuming its types |
| `--branch-name` | Diff a feature branch, extract changed C# types, trace their consumers |
| `--stored-procedure` | Find C# projects calling a specific sproc, then trace their consumers |
| `--sow` / `--sow-file` | Describe a change in plain English, let AI identify targets and trace the blast radius |
| `--graph` | Build the full dependency graph with coupling metrics, cycles, and domain clusters |
| `--pr-risk` | Score a PR across coupling, blast radius, and database dimensions (GREEN/YELLOW/RED) |

Each mode feeds into the same enrichment pipeline. Same quality of output regardless of entry point.

## The graph builds itself

First time you run Scatter against a codebase, it constructs a full dependency graph. ~2.6s for 250 projects, ~39s for 800 projects. That graph gets cached to disk automatically.

Second run loads from cache: under 1 second.

After that, Scatter detects what changed via `git diff` and patches incrementally: ~10ms for typical edits.

You never pass a flag for this. You never configure it. It just happens.

> **How this works:** Scatter maintains a content-hashed graph cache with git-aware invalidation. See [Graph Engine](reference/graph-engine.md) for the full story.

## Built to last

Comprehensive test suite. Modular Python package. Actively developed by team Athena.

## Where to go from here

- **Try it** -- [Getting Started](getting-started.md) with Python/uv, or [Docker](usage/docker.md) if you don't have Python
- **See what it can do** -- [Quick Tour](quick-tour.md) walks through all six modes with real output
- **Run it in CI** -- [Docker](usage/docker.md) for containerized runs, [GitHub Action](reference/github-action.md) for PR comments
