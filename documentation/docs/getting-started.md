# Getting Started

This walks you through installation and your first real analysis. By the end you'll have traced a dependency chain, narrowed it with filters, and seen the graph cache in action. Takes about five minutes.

## Prerequisites

- **Python 3.10+** -- Scatter uses modern type hints and dataclass features
- **Git** -- needed for branch analysis mode and for incremental graph patching

That's it. The repo ships with 8 sample .NET projects, so you don't need a production codebase to start.

## Installation

```bash
git clone <repo-url>
cd wex_scatter

python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\Activate.ps1  # Windows

pip install -r requirements.txt
```

## Verify it works

```bash
python scatter.py --help
```

You should see the five analysis modes (`--target-project`, `--branch-name`, `--stored-procedure`, `--sow`, `--graph`) and all the common options. If you see that, you're good.

## Your first analysis

Let's trace a real dependency chain through the sample projects. Each step narrows the search so you can see the filter pipeline in action.

### Step 1: Find all consumers of GalaxyWorks.Data

```bash
python scatter.py \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope .
```

Expected output:

```
Search scope: /code/wex_scatter (scanned 11 projects, 42 files)
Filter: 11 -> 10 project refs -> 7 namespace -> 4 class match

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (4 consumer(s))
    Type/Level: PortalDataService
         -> Consumed by: MyGalaxyConsumerApp (MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj)
         -> Consumed by: MyGalaxyConsumerApp2 (MyGalaxyConsumerApp2/MyGalaxyConsumerApp2.csproj)
         -> Consumed by: GalaxyWorks.Api (GalaxyWorks.Api/GalaxyWorks.Api.csproj)
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)

--- Total Consuming Relationships Found: 4 ---
```

Four consumers. That's your blast radius for any change to GalaxyWorks.Data.

### Step 2: Narrow by class

Maybe you only touched `PortalDataService`, not the whole project. Let's filter:

```bash
python scatter.py \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . \
  --class-name PortalDataService
```

Now Scatter only reports projects that actually reference `PortalDataService` specifically. The consumer list gets shorter -- only the projects that use that class show up.

### Step 3: Build the full dependency graph

```bash
python scatter.py --graph --search-scope .
```

Expected output (truncated):

```
Dependency Graph Health Dashboard
=================================

Projects: 11 | Edges: 14 | Cycles: 0 | Clusters: 3

Top Coupled Projects:
  GalaxyWorks.Data           coupling=6.23  fan-in=4  fan-out=2  instability=0.33
  MyGalaxyConsumerApp        coupling=4.30  fan-in=1  fan-out=3  instability=0.75
  ...

Domain Clusters:
  [1] GalaxyWorks (5 projects) -- extraction feasibility: MODERATE
  [2] MyDotNet (2 projects) -- extraction feasibility: HIGH
  [3] Standalone (1 project) -- extraction feasibility: HIGH

Observations:
  - GalaxyWorks.Data has 4 inbound dependencies (highest fan-in)
  - No circular dependencies detected
```

This constructs the complete project dependency graph, computes coupling metrics, detects cycles, identifies domain clusters, and generates observations. On the sample projects it finishes in seconds. On a large monorepo, the first run takes longer -- but the cache means you only pay that cost once.

## What just happened

Here's what Scatter did behind the scenes. The filter pipeline works like a funnel:

1. **Discovery** -- found all `.csproj` files in the search scope (11 in the sample projects, maybe 200 in a real codebase)
2. **Project reference filter** -- kept only the ones with a `<ProjectReference>` pointing at `GalaxyWorks.Data` (narrowed to 10)
3. **Namespace filter** -- of those, kept only the ones whose `.cs` files contain a `using GalaxyWorks.Data...` statement (narrowed to 7)
4. **Type/class filter** -- of those, kept only the ones that actually reference specific types (narrowed to 4)

Each stage cuts aggressively. The numbers you see in the console report reflect exactly this pipeline, so you can tell where projects got filtered out and why.

Meanwhile, Scatter quietly built a dependency graph and cached it to disk. You didn't ask for it. On your next run, it loads the cache instead of rebuilding. If you've made changes since the last run, it reads `git diff` and patches only the affected nodes. First run is a few seconds, subsequent runs under a second, incremental patches around 10ms.

> **How this works:** The consumer detection pipeline uses a multi-stage filter funnel with parallel execution. See [Consumer Detection Pipeline](reference/consumer-pipeline.md) for the full story. The graph cache uses content-hashing and git-aware invalidation -- see [Graph Engine](reference/graph-engine.md).

## Verifying your installation

Run the test suite to confirm everything is wired correctly:

```bash
python -m pytest -q
```

Expected output:

```
683 passed, 1 xfailed in 9.12s
```

If you see 683 passed, your installation is solid. The single xfail is intentional -- it marks a known edge case that's tracked but not blocking.

## Next steps

- [Target Project Analysis](usage/target-project.md) -- deep dive into the most common mode
- [Git Branch Analysis](usage/git-branch.md) -- trace blast radius from a feature branch
- [Output Formats](output-formats.md) -- JSON, CSV, markdown, mermaid, pipelines
- [Workflows](workflows.md) -- real-world scenarios chaining analysis modes together
- [Configuration](configuration.md) -- YAML config, env vars, project-specific overrides
