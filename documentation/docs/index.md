# Scatter

You changed a class. Which projects could break?

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

```
Search scope: /code/scatter (scanned 11 projects, 27 files)
Filter: 11 → 7 project refs[graph] → 6 namespace

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (6 consumer(s))
         -> Consumed by: GalaxyWorks.Api (GalaxyWorks.Api/GalaxyWorks.Api.csproj)
           Graph: coupling=7.1, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)
           Graph: coupling=10.8, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
           Graph: coupling=12.7, fan-in=1, fan-out=1, instability=0.500, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp (MyGalaxyConsumerApp/MyGalaryConsumerApp.csproj)
           Graph: coupling=4.3, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp2 (MyGalaxyConsumerApp2/MyGalaryConsumerApp2.csproj)
           Graph: coupling=1.8, fan-in=0, fan-out=1, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.Data.Tests (GalaxyWorks.Data.Tests/GalaxyWorks.Data.Tests.csproj)
           Graph: coupling=3.5, fan-in=0, fan-out=2, instability=1.000, in-cycle=no

--- Total Consuming Relationships Found: 6 ---
```

Six consumers. Now you know who to warn before you merge.

---

You wrote a work request. What's the blast radius?

```bash
scatter --sow "Add tenant isolation to PortalDataService" --search-scope .
```

Scatter parses your intent, identifies the affected types, traces transitive consumers, and rates the risk — from a plain English sentence. No flags to learn, no types to look up manually.

---

**Ready to try it?** [Getting Started](getting-started.md) gets you running in five minutes.

## Five analysis modes

| Flag | What it does |
|------|-------------|
| `--target-project` | Point at a `.csproj`, find every project consuming its types |
| `--branch-name` | Diff a feature branch, extract changed C# types, trace their consumers |
| `--stored-procedure` | Find C# projects calling a specific sproc, then trace their consumers |
| `--sow` / `--sow-file` | Describe a change in plain English, let AI identify targets and trace the blast radius |
| `--graph` | Build the full dependency graph with coupling metrics, cycles, and domain clusters |

Each mode feeds into the same enrichment pipeline. Same quality of output regardless of entry point.

## The graph builds itself

First time you run Scatter against a codebase, it constructs a full dependency graph. ~2.6s for 250 projects, ~39s for 800 projects. That graph gets cached to disk automatically.

Second run loads from cache: under 1 second.

After that, Scatter detects what changed via `git diff` and patches incrementally: ~10ms for typical edits.

You never pass a flag for this. You never configure it. It just happens.

> **How this works:** Scatter maintains a content-hashed graph cache with git-aware invalidation. See [Graph Engine](reference/graph-engine.md) for the full story.

## Built to last

~878 tests across 33 files. Modular Python package. Actively developed by team Athena.

## Where to go from here

- [Getting Started](getting-started.md) -- installation, first run, walkthrough
- [Output Formats](output-formats.md) -- console, JSON, CSV, markdown, mermaid, pipelines
- [CLI Reference](cli-reference.md) -- every flag, every option
- [Workflows](workflows.md) -- real-world scenarios chaining modes together
- [Configuration](configuration.md) -- YAML config, env vars, project-specific overrides
- [Claude Code Skills](getting-started.md#using-with-claude-code) -- ask Claude about dependencies in natural language
