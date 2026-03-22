# Scatter

You changed a class. Which projects just broke?

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

```
Search scope: /code/scatter (scanned 11 projects, 42 files)
Filter: 11 -> 10 project refs -> 7 namespace -> 4 class match

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (4 consumer(s))
    Type/Level: PortalDataService
         -> Consumed by: MyGalaxyConsumerApp (MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj)
         -> Consumed by: MyGalaxyConsumerApp2 (MyGalaxyConsumerApp2/MyGalaxyConsumerApp2.csproj)
         -> Consumed by: GalaxyWorks.Api (GalaxyWorks.Api/GalaxyWorks.Api.csproj)
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)

--- Total Consuming Relationships Found: 4 ---
```

That took about three seconds. Now you know who to warn before you merge.

---

You wrote a work request. What's the blast radius?

```bash
scatter --sow "Add tenant isolation to PortalDataService" --search-scope .
```

Scatter parses your intent, identifies the affected types, traces transitive consumers, and rates the risk — all from a plain English sentence. No flags to learn, no types to look up manually.

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

First time you run Scatter against a codebase, it constructs a full dependency graph. Takes roughly 3-5 seconds depending on repo size. That graph gets cached to disk automatically.

Second run loads from cache: under 1 second.

After that, Scatter detects what changed via `git diff` and patches incrementally: around 10 milliseconds.

You never pass a flag for this. You never configure it. It just happens.

> **How this works:** Scatter maintains a content-hashed graph cache with git-aware invalidation. See [Graph Engine](reference/graph-engine.md) for the full story.

## Built to last

788 tests. Modular Python package. Actively developed by team Athena.

## Where to go from here

- [Getting Started](getting-started.md) -- installation, first run, walkthrough
- [Output Formats](output-formats.md) -- console, JSON, CSV, markdown, mermaid, pipelines
- [CLI Reference](cli-reference.md) -- every flag, every option
- [Workflows](workflows.md) -- real-world scenarios chaining modes together
- [Configuration](configuration.md) -- YAML config, env vars, project-specific overrides
- [Claude Code Skills](getting-started.md#using-with-claude-code) -- ask Claude about dependencies in natural language
