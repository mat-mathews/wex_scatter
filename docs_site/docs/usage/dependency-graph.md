# Dependency Graph

You want the full picture: every project, every dependency, every coupling hotspot, every potential service boundary. This isn't "who consumes this one thing?" -- it's "what does your entire dependency landscape look like, and where are the problems?"

Think of it as a codebase X-ray. Run it, stare at the results, and then have opinions about which refactors to prioritize.

## Basic Example

```bash
scatter --graph --search-scope .
```

```
============================================================
  Dependency Graph Analysis
============================================================
  Projects: 13
  Dependencies: 35
  Connected components: 3
  Circular dependencies: 0

  Top Coupled Projects:
  Project                                     Score   Fan-In  Fan-Out  Instab.
  ---------------------------------------- -------- -------- -------- --------
  GalaxyWorks.Data                             30.3        9        0     0.00
  GalaxyWorks.WebPortal                        12.7        1        1     0.50
  GalaxyWorks.BatchProcessor                   10.8        0        2     1.00
  GalaxyWorks.Common                           10.0        3        1     0.25
  ...

  Domain Clusters:
  Cluster                          Size   Cohesion   Coupling          Feasibility
  ------------------------------ ------ ---------- ---------- --------------------
  cluster_0                          10      0.367      0.000         easy (1.000)
    Members: GalaxyWorks.Api, GalaxyWorks.BatchProcessor, GalaxyWorks.Common, GalaxyWorks.Data, ...
  MyDotNetApp                         2      1.000      0.000         easy (1.000)
    Members: MyDotNetApp, MyDotNetApp.Consumer

  Observations:
    [warning] GalaxyWorks.Data: stable core (fan_in=9, instability=0.00) — change carefully
    [warning] GalaxyWorks.Data: high coupling score (30.3) — review dependencies
    [info] dbo.sp_InsertPortalConfiguration: shared by 3 projects — database coupling hotspot
    [warning] Directory.Build.props: imported by 12 projects — config change affects wide blast radius

Analysis complete. 13 projects, 35 dependencies, 0 cycle(s).
```

That's the whole codebase in one screen. Let's walk through what you're looking at.

## Reading the Output

### Top Coupled Projects

The project with the highest coupling score is the one you should worry about most before modifying. GalaxyWorks.Data sits at the top with fan-in of 9 and zero instability — a classic "stable core." Everything depends on it. It depends on nothing. Change it carefully.

The columns:

- **Score** -- weighted sum of all dependency edges touching this project. Higher means more coupled to the rest of the codebase.
- **Fan-In** -- how many projects depend on this one. High fan-in = lots of consumers.
- **Fan-Out** -- how many projects this one depends on. High fan-out = lots of dependencies.
- **Instability** -- `fan_out / (fan_in + fan_out)`. A score of 0.0 means fully stable (only depended upon). A score of 1.0 means fully unstable (only depends on others, nothing depends on it). Stable projects should be changed cautiously. Unstable projects are free to change.

### Domain Clusters

Scatter identifies clusters of projects that are tightly connected. The **Feasibility** column tells you whether extracting that cluster is realistic or a multi-quarter project:

- **easy** -- low coupling to outside, no cross-boundary cycles. Could extract in a sprint or two.
- **moderate** -- some coupling to break, maybe shared database state. Feasible with planning.
- **hard** -- significant cross-boundary dependencies. Requires interface extraction, database refactoring, or both.
- **very_hard** -- deeply entangled. Extracting this cluster is a multi-quarter project.

### Observations

Scatter flags specific concerns automatically:

- **stable core** -- high fan-in, low instability. Lots of things depend on it.
- **high coupling** -- coupling score above threshold. Too many dependency edges.
- **in cycle** -- participates in a circular dependency. Must break before extraction.
- **low cohesion cluster** -- high external coupling, low internal cohesion. Consider splitting.
- **db hotspot** -- a stored procedure shared by 3+ projects. Database coupling hotspot.
- **high_cross_solution_coupling** -- ratio > 0.5, meaning more edges cross the solution boundary than stay inside.
- **solution_bridge_project** -- a project in 3+ solutions with 5+ incoming dependencies, acting as a coupling bottleneck.

### Solution Coupling

When `.sln` files are present in the search scope, Scatter parses them and reports how self-contained each solution is:

- **Projects** -- number of projects declared in the solution
- **Internal** -- edges where both endpoints are in this solution
- **External** -- edges crossing the solution boundary
- **Ratio** -- external / (internal + external). Low ratio = self-contained. High ratio = heavily coupled to other solutions.

The **Align** column on domain clusters shows how well each cluster aligns with solution boundaries. 1.0 means every cluster member is in the same solution. Lower values surface accidental cross-solution coupling -- projects that the graph says are tightly coupled but the org structure thinks belong to different teams.

Two health observations fire automatically:

- **high_cross_solution_coupling** (warning) -- ratio > 0.5, meaning more edges cross the solution boundary than stay inside
- **solution_bridge_project** (info) -- a project in 3+ solutions with 5+ incoming dependencies, acting as a coupling bottleneck

## Force Rebuild

```bash
scatter --graph --search-scope . --rebuild-graph
```

Scatter caches the graph after the first build. Subsequent runs load the cache and skip the expensive construction step. Use `--rebuild-graph` after major structural changes (new projects added, projects removed, renamed namespaces) when you suspect the cache is stale.

The cache also accelerates other modes -- when you run `--target-project` and a graph cache exists, the first two pipeline stages use the graph's reverse index instead of scanning the filesystem.

## Include Database Dependencies

```bash
scatter --graph --search-scope . --include-db
```

Adds `sproc_shared` edges by scanning `.cs` files for stored procedure references, EF model patterns, and direct SQL strings. Without this flag, the graph only tracks project references, namespace usage, and type usage.

Database edges expose hidden coupling. Two projects that share no code references but both call `sp_InsertPortalConfiguration` are coupled through shared mutable state -- and that coupling is nearly as hard as a project reference.

## Output Formats

**JSON** -- structured report with summary stats, top coupled projects, cycle details, per-project metrics, cluster analysis, and observations:

```bash
scatter --graph --search-scope . \
  --output-format json --output-file graph_report.json
```

Add `--include-graph-topology` to include the full node and edge data in the JSON. Omitted by default to keep file size manageable. Include it when you need the raw graph for visualization tools or custom analysis.

**CSV** -- one row per project with columns for all metrics (FanIn, FanOut, Instability, CouplingScore, Cluster, ExtractionFeasibility, etc.). Sort in a spreadsheet and find outliers:

```bash
scatter --graph --search-scope . \
  --output-format csv --output-file graph_metrics.csv
```

**Markdown** -- includes a Mermaid diagram of the dependency graph. Paste it into a PR, a wiki, or any documentation that renders Mermaid blocks:

```bash
scatter --graph --search-scope . \
  --output-format markdown --output-file graph.md
```

**Mermaid** -- just the diagram, nothing else. Projects are grouped into subgraph blocks when clusters are present:

```bash
scatter --graph --search-scope . \
  --output-format mermaid --output-file graph.mmd
```

See [Output Formats](../output-formats.md) for detailed structure of each format.

## When to Use This

- **Architecture reviews** -- run before a planning session. Print the top coupled projects table and the cluster feasibility scores. Now your discussion starts with evidence.
- **Pre-modernization assessments** -- before proposing a microservice extraction, run with `--include-db` to see the real coupling (including database state). The feasibility column will tell us if the extraction is a sprint or a quarter.
- **Tracking coupling trends** -- run periodically and compare the JSON reports. Is coupling going up or down? Are new cycles appearing?

## Controlling Graph Behavior

The graph has four modes across the tool:

| Flag | Behavior |
|------|----------|
| *(default)* | Auto-builds graph if needed, caches for later |
| `--no-graph` | Skip graph entirely, even if cached |
| `--rebuild-graph` | Force rebuild, ignore cache |
| `--graph` | Dedicated graph analysis mode (this page) |

---

!!! info "How this works"
    Scatter builds a full dependency graph tracking four edge types (project references, namespace usage, type usage, shared stored procedures), computes coupling metrics per project, detects circular dependencies, and identifies domain clusters with extraction feasibility scoring. See [Graph Engine](../reference/graph-engine.md) for the construction pipeline, [Coupling & Cycles](../reference/coupling-and-cycles.md) for metric formulas, and [Domain Clustering](../reference/domain-clustering.md) for the clustering algorithm.
