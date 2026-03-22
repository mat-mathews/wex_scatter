# Scatter

[![CI](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml/badge.svg)](https://github.com/mat-mathews/wex_scatter/actions/workflows/ci.yml)

*A .NET dependency graph engine and impact analysis tool*

Scatter builds a dependency graph of your .NET codebase and uses it to answer questions like "If I change this class, which projects are actually affected?" and "What's the blast radius of this work request?"

### Zero-Config Graph Acceleration

On first run, Scatter automatically builds a dependency graph from your `.csproj` and `.cs` files, caches it, and uses it to accelerate every subsequent analysis. No flags to learn, no setup steps — it just works.

```
First run:  filesystem scan → build graph → cache → enriched results  (~3-5s one-time cost)
Second run: load cache → O(1) graph lookup → enriched results         (~400-900ms faster)
Later runs: incremental patch via git diff → graph lookup              (~10ms for typical PRs)
```

The graph tracks four edge types — **project references**, **namespace usage**, **type usage**, and **shared stored procedures** — giving Scatter a complete picture of how your projects are connected. Consumer lookups that previously scanned every `.csproj` and `.cs` file on disk now resolve in microseconds via reverse-index lookup.

Every analysis result is automatically enriched with graph-derived metrics: **coupling score**, **fan-in/out**, **instability index**, and **circular dependency membership**. These appear in all output formats (console, JSON, CSV, markdown) with no extra flags.

Use `--no-graph` to skip graph operations entirely. Use `--rebuild-graph` to force a fresh build.

### Analysis Modes

Scatter works in five modes:

* **Git Branch Analysis** (`--branch-name`): Extracts type declarations from changed `.cs` files and finds consuming projects
* **Target Project Analysis** (`--target-project`): Finds all projects that reference and use a specific `.csproj`
* **Stored Procedure Analysis** (`--stored-procedure`): Traces C# consumers of a stored procedure
* **Impact Analysis** (`--sow`): Accepts a natural language work request, uses AI to trace transitive blast radius with risk ratings
* **Dependency Graph Analysis** (`--graph`): Full graph visualization with coupling metrics, cycle detection, and domain cluster extraction

The repository includes 8 sample .NET projects that form a realistic dependency graph, making it possible to test all analysis modes without an external codebase.

---

## Quick Start

### Installation

```bash
# Clone and set up
git clone <repository_url>
cd scatter

# One-command dev setup (Windows: run from Git Bash)
bash tools/setup.sh
```

If you don't have uv yet, the setup script will tell you how to install it.

### Development Workflow

```bash
# Run the local CI check before pushing (lint + format + mypy + pytest)
bash tools/check.sh

# Quick lint-only check (~2 seconds)
bash tools/check.sh --quick
```

### Using with Claude Code

If you have Claude Code, you can use scatter through natural language instead of CLI flags.
The setup script above already links the skills. Then ask Claude directly:

- "Show me the dependency health of this codebase"
- "Who uses GalaxyWorks.Data?"
- "What's the blast radius of adding tenant isolation to portal configuration?"

See [docs/CLAUDE_SKILLS.md](docs/CLAUDE_SKILLS.md) for all available skills and example prompts.

### CI/CD Integration

Drop a [GitHub Action workflow](tools/github-action/) into your .NET repo for automatic PR impact comments. One YAML file, no marketplace action, no org approvals.

### Try It with the Included Sample Projects

The repository ships with 8 sample .NET projects that form two dependency chains (see [Sample Project Structure](#sample-project-structure) for the full graph). You can run every analysis mode against them immediately — no external codebase needed.

#### Target Project Analysis

```bash
# Find all consumers of the core GalaxyWorks.Data library
# Expected: 4 consumers (WebPortal, BatchProcessor, MyGalaxyConsumerApp, MyGalaxyConsumerApp2)
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

# Narrow to only consumers that use PortalDataService
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService

# Narrow further to consumers calling StorePortalConfigurationAsync
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --method-name StorePortalConfigurationAsync

# Find consumers of a mid-tier library (WebPortal)
# Expected: 1 consumer (BatchProcessor references both Data and WebPortal)
python scatter.py --target-project ./GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj --search-scope .

# Find consumers of a leaf project with only one consumer
# Expected: 1 consumer (MyDotNetApp.Consumer)
python scatter.py --target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .

# Verify a standalone project has zero consumers
# Expected: 0 consumers
python scatter.py --target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .
```

#### Stored Procedure Analysis

```bash
# Trace who ultimately consumes the sproc sp_InsertPortalConfiguration
# Finds PortalDataService in GalaxyWorks.Data, then finds its consumers
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# Trace a different sproc — sp_GetPortalConfigurationDetails
python scatter.py --stored-procedure "dbo.sp_GetPortalConfigurationDetails" --search-scope .

# Sproc trace filtered to a specific containing class
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --class-name PortalDataService
```

#### Output Formats

```bash
# JSON output — structured data with pipeline summary
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format json --output-file /tmp/scatter_results.json

# CSV output — one row per consumer relationship
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format csv --output-file /tmp/scatter_results.csv

# Markdown output — paste-ready for PRs and wikis (prints to stdout if --output-file omitted)
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format markdown --output-file /tmp/scatter_results.md

# Verbose logging — see every step of the analysis pipeline
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . -v
```

#### AI-Powered Features (require `$GOOGLE_API_KEY`)

```bash
# AI consumer summarization — explains what each consumer file does with the dependency
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# AI summarization on sproc analysis
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# AI summarization with class filter + JSON output
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/summarized.json

# Impact Analysis — natural language work request → risk-rated impact report
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . --google-api-key $GOOGLE_API_KEY

# Impact Analysis with deeper transitive tracing
# BatchProcessor → WebPortal → GalaxyWorks.Data (2 hops deep)
python scatter.py \
  --sow "Refactor the FakeDatabaseHelper connection handling in GalaxyWorks.Data" \
  --search-scope . --max-depth 2 --google-api-key $GOOGLE_API_KEY

# Impact Analysis from a file containing a longer SOW description
python scatter.py \
  --sow-file docs/INITIATIVE_2_PLAN.md \
  --search-scope . --google-api-key $GOOGLE_API_KEY

# Impact Analysis with JSON output for programmatic consumption
python scatter.py \
  --sow "Add a new stored procedure sp_ArchivePortalConfiguration and integrate it into PortalDataService" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/impact_report.json

# Impact Analysis with CSV output — one row per affected consumer
python scatter.py \
  --sow "Modify the PortalConfiguration model to add a new IsArchived field" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format csv --output-file /tmp/impact_report.csv

# Impact Analysis as markdown — paste into PR or ticket
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format markdown
```

---

## Table of Contents

1. [Quick Start](#quick-start) — Installation, Claude Code integration, sample projects
2. [Sample Project Structure](#sample-project-structure)
3. [How the Graph Engine Works](#how-the-graph-engine-works) — Build pipeline, acceleration, incremental updates, metrics
4. [Analysis Modes](#analysis-modes)
5. [Workflow Examples](#workflow-examples) — End-to-end scenarios for common use cases
6. [AI Features](#ai-features)
7. [Impact Analysis (Mode 4)](#impact-analysis-mode-4)
8. [Parallel Processing](#parallel-processing)
9. [Configuration & Mapping](#configuration--mapping) — YAML config files, precedence, env vars
10. [Command-Line Reference](#command-line-reference)
11. [Output Formats](#output-formats)
12. [Testing](#testing) — Test suite, benchmarking (full build, incremental, parallel vs sequential)
13. [Technical Details](#technical-details)
14. [Dependency Graph Reference](#dependency-graph) — Programmatic API, serialization, construction pipeline details
15. [Roadmap](#roadmap)

---

## Sample Project Structure

The repository includes sample .NET projects that demonstrate realistic dependency patterns. These are used by the test suite and can be used to explore Scatter's features interactively.

### Dependency Graph

```
GalaxyWorks.Data                    (core library — no dependencies)
├── PortalDataService               calls sp_InsertPortalConfiguration
├── Models: PortalConfiguration, UserActivityLog, SystemModule, StatusType
└── Core: IDataAccessor interface
     │
     ├── GalaxyWorks.WebPortal      (references GalaxyWorks.Data)
     │   ├── PortalController       uses PortalDataService
     │   └── PortalCacheService     uses PortalConfiguration
     │        │
     │        └── GalaxyWorks.BatchProcessor  (references Data + WebPortal)
     │            └── SyncJob       uses PortalDataService + PortalCacheService
     │
     ├── MyGalaxyConsumerApp        (references GalaxyWorks.Data)
     │   └── Program               creates PortalDataService instance
     │
     └── MyGalaxyConsumerApp2       (references GalaxyWorks.Data)
         └── Program               creates PortalDataService instance

MyDotNetApp                         (independent library — no dependencies)
├── Person, DataService, IDataService
     │
     └── MyDotNetApp.Consumer       (references MyDotNetApp)
         └── Program               uses Person & DataService

MyDotNetApp2.Exclude                (standalone — no references, tests exclusion)
```

### What You Can Test

| Scenario | Command |
|----------|---------|
| Find all consumers of a core library | `--target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .` |
| Filter to a specific class | Add `--class-name PortalDataService` |
| Filter to a specific method | Add `--class-name PortalDataService --method-name InsertPortalConfiguration` |
| Trace stored procedure consumers | `--stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .` |
| Find consumers of a leaf project | `--target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .` |
| Verify no false positives | `--target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .` (should find 0 consumers) |
| Impact analysis with transitive tracing | `--sow "Modify PortalDataService" --search-scope . --max-depth 2 --google-api-key $KEY` |
| Build dependency graph with domain clusters | `--graph --search-scope .` |
| Graph analysis with JSON output | `--graph --search-scope . --output-format json --output-file graph.json` |
| Graph analysis as markdown (with Mermaid diagram) | `--graph --search-scope . --output-format markdown --output-file graph.md` |

---

## How the Graph Engine Works

Scatter's graph engine is the core of its performance and intelligence. Rather than scanning the filesystem from scratch on every run, Scatter builds a persistent dependency graph that serves as the single source of truth for all project relationships.

### The Three-Phase Lifecycle

**Phase 1: Build (first run only)**

On first analysis, after the filesystem-based consumer lookup completes, Scatter builds a full dependency graph in a single pass over all `.csproj` and `.cs` files:

```
search_scope/
  ├─ Discover .csproj files → parse project references, namespace, framework
  ├─ Discover .cs files → map to parent project via reverse directory index
  ├─ Extract type declarations, using statements, sproc references
  └─ Build edges: project_reference, namespace_usage, type_usage, sproc_shared
```

The graph is saved as a v2 JSON cache (`.scatter/graph_cache.json`) with per-file content hashes and per-project facts, enabling incremental updates on subsequent runs.

**Phase 2: Accelerate (every subsequent run)**

When a cache exists, consumer lookups bypass the filesystem entirely. Instead of scanning every `.csproj` for `<ProjectReference>` tags and every `.cs` for `using` statements, Scatter resolves consumers via O(1) reverse-index lookup on the graph:

```
Filesystem path:  O(P + F) — scan P projects, grep F files     (~2-5s)
Graph path:       O(1) reverse lookup via get_edges_to()        (~μs)
```

Stages 1-2 of the 5-stage filter pipeline (discovery + project reference matching) are replaced entirely. Stages 3-5 (namespace, class, method filtering) still run on the graph-sourced candidate set for precision.

**Phase 3: Patch (incremental updates)**

On runs after the first, Scatter uses `git diff` to identify files changed since the last build and surgically patches the graph instead of rebuilding:

```
git diff --name-only <cached_head> HEAD -- *.cs *.csproj
  ├─ Content hash early cutoff (unchanged hash → skip)
  ├─ Declaration early cutoff (same types → edge-only rebuild)
  └─ Safety valves: >50 projects or >30% files → full rebuild
```

| Scenario | 100 projects | 250 projects |
|----------|-------------|-------------|
| Full rebuild | 1.1s | 9.5s |
| 1 file change (body edit) | 10ms (110x faster) | 10ms (954x faster) |
| 10 file changes | 70ms (16x) | 315ms (30x) |
| 1 csproj modified | 9ms (122x) | 38ms (253x) |

### Automatic Enrichment

Every consumer result — in all five analysis modes — is automatically enriched with graph-derived metrics when the graph is available:

| Metric | What it tells you |
|--------|------------------|
| **Coupling Score** | Overall interconnectedness intensity (weighted sum of all edge types) |
| **Fan-In** | How many projects depend on this one (build-time risk indicator) |
| **Fan-Out** | How many projects this one depends on |
| **Instability** | 0.0 = stable core, 1.0 = volatile leaf (Martin's instability index) |
| **In Cycle** | Whether this project participates in a circular dependency |

These metrics appear in console output, JSON, CSV, and markdown reports. No `--graph-metrics` flag needed — enrichment happens automatically when graph data is available.

### Edge Types

The graph captures four types of relationships:

| Edge Type | What it represents | Weight |
|-----------|-------------------|--------|
| `project_reference` | `<ProjectReference>` in `.csproj` — hard compile-time dependency | 1.0 |
| `namespace_usage` | `using` statement matching a project's namespace | 0.5 |
| `type_usage` | Direct reference to a type declared in another project | 0.3 |
| `sproc_shared` | Stored procedure referenced by multiple projects (shared mutable state) | 0.8 |

Weights are configurable in `.scatter.yaml` under `graph.coupling_weights`.

### Controlling Graph Behavior

| Flag | Effect |
|------|--------|
| *(default)* | Auto-build on first run, auto-load from cache, incremental patching |
| `--no-graph` | Skip all graph operations (build, load, enrich) |
| `--rebuild-graph` | Force a full graph rebuild, ignoring the cache |
| `--graph` | Dedicated graph analysis mode with coupling metrics, cycles, and domain clusters |
| `--graph-metrics` | Explicitly request graph enrichment (redundant now — enrichment is automatic) |

---

## Analysis Modes

### Mode 1: Git Branch Analysis (`--branch-name`)

Analyzes the `.cs` files changed on a feature branch to identify potential downstream impact.

**How it works:**
1. Finds the merge base between the feature branch and base branch
2. Identifies all changed `.cs` files in the diff
3. Maps changed files to their parent `.csproj` projects
4. Extracts type declarations (`class`, `struct`, `interface`, `enum`, `record`, `delegate`) from changed files
5. Finds consuming projects for each changed type

**Type extraction** uses regex by default, matching C# type declarations with access modifiers, generics, and keywords like `static`, `abstract`, `sealed`, `partial`, `record`, `readonly`, and `ref`. With `--enable-hybrid-git`, Scatter sends both the full file content and the git diff to an LLM, which identifies only the types whose body, signature, or members were *actually changed* — ignoring types that merely appear in the same file. This significantly reduces false positives. See [AI-Enhanced Type Extraction](#ai-enhanced-type-extraction-hybrid-git) for details.

```bash
# Basic usage — regex type extraction
python scatter.py --branch-name feature/new-widget --repo-path .

# Against a different base branch
python scatter.py --branch-name feature/hotfix --base-branch develop --repo-path /path/to/repo

# With LLM-enhanced diff analysis (reduces false positives)
python scatter.py --branch-name feature/refactor --repo-path . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY

# Filter to a specific class
python scatter.py --branch-name feature/refactor --repo-path . --class-name WidgetFactory

# Full analysis with pipeline mapping and JSON output
python scatter.py --branch-name feature/new-api --repo-path . \
  --search-scope src/services \
  --pipeline-csv build/pipeline_map.csv \
  --output-format json --output-file reports/analysis.json
```

### Mode 2: Target Project Analysis (`--target-project`)

Finds all projects that consume a specific `.csproj` file.

**How it works:**
1. Parses the target `.csproj` to determine its namespace
2. Finds all `.csproj` files in the search scope with a `<ProjectReference>` to the target
3. Filters by namespace usage (`using` statements)
4. Optionally filters by class and method usage

When `--summarize-consumers` is enabled, Scatter sends each relevant consumer `.cs` file to the Gemini API and includes a 2-3 sentence AI-generated summary in the output explaining the file's purpose. See [AI Consumer Summarization](#ai-consumer-summarization) for details and example output.

> **Note:** AI summarization requires a Google API key. Set `GOOGLE_API_KEY` in your environment or pass `--google-api-key`.

```bash
# Basic usage
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

# Override namespace detection
python scatter.py --target-project ./LegacyLib/LegacyLib.csproj --search-scope . \
  --target-namespace Company.Product.OldStuff

# Filter by class and method
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --method-name InsertPortalConfiguration

# With AI summarization — explains what each consumer file does
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# AI summarization with JSON output
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file reports/summary.json
```

### Mode 3: Stored Procedure Analysis (`--stored-procedure`)

Finds C# projects that reference a stored procedure, then traces their consumers.

**How it works:**
1. Scans the search scope for `.cs` files containing the stored procedure name
2. Maps matching files to their parent `.csproj` projects and containing classes
3. For each class referencing the sproc, finds consumer projects

```bash
# Basic usage
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# Custom regex pattern
python scatter.py --stored-procedure "UpdateUser" --search-scope . \
  --sproc-regex-pattern "EXECUTE sp_prefix_{sproc_name_placeholder}"

# Filter by class
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --class-name PortalDataService

# JSON output
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --output-format json --output-file reports/sproc_consumers.json
```

### Mode 4: Impact Analysis (`--sow` / `--sow-file`)

Accepts a natural language work request and produces an AI-enriched impact report. See [Impact Analysis (Mode 4)](#impact-analysis-mode-4) for the full breakdown.

### Mode 5: Dependency Graph Analysis (`--graph`)

Builds a full dependency graph from the codebase, computes coupling metrics, detects circular dependencies, and identifies domain clusters with extraction feasibility scoring.

**How it works:**
1. Discovers all `.csproj` and `.cs` files in the search scope
2. Builds a `DependencyGraph` with project references, namespace usage, and type usage edges
3. Caches the graph to disk (smart git-based invalidation)
4. Computes coupling metrics (fan_in, fan_out, instability, coupling_score) per project
5. Detects circular dependencies via Tarjan's SCC algorithm
6. Identifies domain clusters via connected components + label propagation
7. Scores each cluster's extraction feasibility based on cross-boundary coupling, shared DB objects, cycles, and API surface

```bash
# Basic graph analysis with domain clusters and health observations
python scatter.py --graph --search-scope .

# Force rebuild (ignore cache)
python scatter.py --graph --search-scope . --rebuild-graph

# Include database dependency scanning (sproc_shared edges)
python scatter.py --graph --search-scope . --include-db

# JSON output (metrics, clusters, health dashboard — topology omitted by default for size)
python scatter.py --graph --search-scope . --output-format json --output-file graph_report.json

# JSON with full graph topology (nodes + edges included)
python scatter.py --graph --search-scope . --output-format json --output-file graph_report.json --include-graph-topology

# CSV output (one row per project with metrics, cluster assignment, feasibility)
python scatter.py --graph --search-scope . --output-format csv --output-file graph_metrics.csv
```

**Console output includes:**

```
============================================================
  Dependency Graph Analysis
============================================================
  Projects: 8
  Dependencies: 18
  Connected components: 2
  Circular dependencies: 0

  Top Coupled Projects:
  Project                                    Score   Fan-In  Fan-Out  Instab.
  ---------------------------------------- -------- -------- -------- --------
  GalaxyWorks.Data                              8.6        4        0     0.00

  Domain Clusters:
  Cluster                          Size   Cohesion   Coupling          Feasibility
  ------------------------------ ------ ---------- ---------- --------------------
  MyDotNetApp                         2      1.000      0.000         easy (1.000)
    Members: MyDotNetApp, MyDotNetApp.Consumer
  cluster_0                           3      0.167      0.600     moderate (0.760)
    Members: GalaxyWorks.Data, GalaxyWorks.WebPortal, GalaxyWorks.BatchProcessor

  Observations:
    [warning] GalaxyWorks.Data: stable core (fan_in=4, instability=0.00) — change carefully
```

See [Dependency Graph](#dependency-graph) for architecture details, and [Domain Boundary Detection](#domain-boundary-detection) for clustering and feasibility scoring.

---

## Workflow Examples

Real-world scenarios showing how to chain Scatter's analysis modes together.

### 1. Pre-Merge Blast Radius Check

**Persona**: Developer preparing a pull request
**When**: Before merging a feature branch that touches shared code
**Why**: Know exactly which downstream projects are affected so reviewers and downstream teams can be notified

Start with a quick blast radius scan:

```bash
python scatter.py --branch-name feature/new-widget --repo-path . --search-scope .
```

Review the consumer list in the output. If the list is larger than expected, drill into what each consumer actually does with the dependency:

```bash
python scatter.py --branch-name feature/new-widget --repo-path . --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY
```

For high-precision results (only types whose body/signature actually changed, not every type in the file), enable hybrid git analysis:

```bash
python scatter.py --branch-name feature/new-widget --repo-path . --search-scope . \
  --enable-hybrid-git --summarize-consumers --google-api-key $GOOGLE_API_KEY
```

**What to look for**: Consumer projects you didn't expect. If a "small change" surfaces 10+ consumers, it may need broader review or a phased rollout.

### 2. Stored Procedure Change Impact

**Persona**: Developer or DBA modifying a stored procedure
**When**: Before altering a sproc's signature, return type, or behavior
**Why**: Stored procedure callers are invisible in project references — Scatter finds them by scanning source code for the sproc name

Find every C# project that calls the sproc:

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```

Export the results as CSV for sharing with the DBA team or attaching to a change request:

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --output-format csv --output-file sproc_impact.csv
```

If you have pipeline mappings, add them to see which CI/CD pipelines need to be coordinated:

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --pipeline-csv build/pipeline_map.csv \
  --output-format csv --output-file sproc_impact.csv
```

**What to look for**: The containing class (e.g., `PortalDataService`) and all its consumers. A sproc change often requires coordinated deployment across multiple services.

### 3. Work Request Scoping with AI

**Persona**: Tech lead estimating a work request during sprint planning
**When**: A new feature request or change request arrives and you need to assess scope
**Why**: Get an AI-generated risk rating, effort estimate, and blast radius before committing to the work

Run impact analysis with the work request description:

```bash
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . --google-api-key $GOOGLE_API_KEY
```

For longer work requests, put the description in a file:

```bash
python scatter.py \
  --sow-file docs/work_request.md \
  --search-scope . --google-api-key $GOOGLE_API_KEY
```

Save the full report as JSON for attaching to a ticket or feeding into project tracking:

```bash
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file impact_report.json
```

**What to look for**: The `Overall Risk` and `Complexity` ratings in the report header, the number of direct vs. transitive consumers, and the AI-generated impact summary at the bottom.

### 4. Architecture Health Assessment

**Persona**: Architect evaluating the codebase before a modernization initiative
**When**: Planning a migration to microservices, evaluating tech debt, or identifying extraction candidates
**Why**: Identify tightly-coupled clusters, circular dependencies, and which groups of projects could realistically be separated

Build the full dependency graph and review the analysis:

```bash
python scatter.py --graph --search-scope .
```

**What to look for in the console output**:
- **Circular dependencies**: Any cycles indicate build-order violations that must be broken before extraction
- **Top Coupled Projects**: Projects with the highest coupling scores are the hardest to change safely
- **Domain Clusters table**: The `Feasibility` column rates each cluster as `easy`, `moderate`, `hard`, or `very_hard` for extraction
- **Cohesion vs. Coupling**: High internal cohesion + low external coupling = good extraction candidate

For a deeper dive, export the full graph data:

```bash
python scatter.py --graph --search-scope . \
  --output-format json --output-file architecture_review.json
```

The JSON output includes per-project metrics (fan_in, fan_out, instability, coupling_score), cycle details, and cluster feasibility breakdowns with individual penalty factors.

### 5. Target Project Dependency Audit

**Persona**: Developer planning to refactor a shared library
**When**: Before renaming types, changing method signatures, or restructuring a `.csproj` that other projects depend on
**Why**: Know every project that uses the library's types so you can update all call sites

Start with the full consumer list:

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

Narrow to a specific class you plan to change:

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService
```

Narrow further to a specific method:

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --method-name StorePortalConfigurationAsync
```

Add AI summaries to understand what each consumer does with the dependency:

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY
```

**What to look for**: The progression from broad (all consumers) to narrow (specific method callers) helps you gauge how many call sites you need to update. AI summaries explain the context of each usage.

### 6. Full Codebase Analysis Pipeline

**Persona**: DevOps engineer or architect running periodic health checks
**When**: Monthly or quarterly codebase review, or before a major release
**Why**: Track coupling trends over time, catch new circular dependencies early, and monitor domain boundary health

Generate a full graph report as JSON:

```bash
python scatter.py --graph --search-scope . \
  --output-format json --output-file reports/graph_$(date +%Y%m%d).json
```

Compare against a previous report to spot trends (e.g., rising coupling scores, new cycles):

```bash
# Quick comparison of key metrics between two reports
python -c "
import json
old = json.load(open('reports/graph_20260201.json'))
new = json.load(open('reports/graph_20260301.json'))
print(f\"Projects: {old['node_count']} -> {new['node_count']}\")
print(f\"Edges: {old['edge_count']} -> {new['edge_count']}\")
print(f\"Cycles: {len(old.get('cycles',[]))} -> {len(new.get('cycles',[]))}\")
"
```

Force a fresh rebuild if you suspect the cache is stale:

```bash
python scatter.py --graph --search-scope . --rebuild-graph \
  --output-format json --output-file reports/graph_$(date +%Y%m%d).json
```

**What to look for**: Increasing edge counts or coupling scores over time signal growing entanglement. New circular dependencies should be addressed immediately. Clusters shifting from `easy` to `moderate` feasibility indicate erosion of domain boundaries.

---

## AI Features

Scatter integrates with the Google Gemini API in three distinct ways. Each is optional and activated by specific flags. All require a Gemini API key via `--google-api-key` or the `GOOGLE_API_KEY` environment variable.

| Feature | Flag | Available In | Purpose |
|---------|------|-------------|---------|
| [Consumer Summarization](#ai-consumer-summarization) | `--summarize-consumers` | Git, Target, Sproc modes | Explain *what* each consumer file does |
| [Hybrid Type Extraction](#ai-enhanced-type-extraction-hybrid-git) | `--enable-hybrid-git` | Git mode only | Identify *which* types were actually changed in a diff |
| [Impact Analysis](#impact-analysis-mode-4) | `--sow` / `--sow-file` | Impact mode | Full AI-powered scoping: parse SOW, assess risk, estimate effort |
| [Graph Metrics Enrichment](#graph-metrics-enrichment) | `--graph-metrics` | All modes | Add coupling score, fan-in/out, instability, and cycle membership to consumer results |

### AI Consumer Summarization

When `--summarize-consumers` is enabled, Scatter identifies the specific `.cs` files in each consumer project that caused the match (e.g., the file containing the `using GalaxyWorks.Data;` statement and the `PortalDataService` reference). It sends each file's content to the Gemini API and gets back a concise 2-3 sentence summary of the file's purpose.

This is useful when you have dozens of consumers and want to quickly understand *what* each one does with the dependency, without opening every file.

**Try it with the sample projects:**

```bash
# Summarize what each consumer of GalaxyWorks.Data does with it
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarize consumers of a stored procedure
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Combine with class filter and JSON output
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file reports/summarized.json
```

**Example console output with summarization:**

```
Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
    Type/Level: PortalDataService
         -> Consumed by: MyGalaxyConsumerApp (MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj)
           Summaries:
             File: Program.cs
              This console application creates an instance of PortalDataService
              and calls its methods to insert and retrieve portal configuration
              data. It serves as a simple client for the GalaxyWorks.Data library.
```

**In JSON output**, summaries appear in the `ConsumerFileSummaries` field as a JSON object mapping file paths to summary text:

```json
{
  "ConsumerProjectName": "MyGalaxyConsumerApp",
  "ConsumerFileSummaries": "{\"Program.cs\": \"This console application creates an instance of...\"}"
}
```

### Graph Metrics Enrichment

Graph metrics are **automatic** — Scatter builds or loads the dependency graph on every run and enriches consumer results with structural metrics. No flags needed. See [How the Graph Engine Works](#how-the-graph-engine-works) for the full story.

Use `--no-graph` to disable graph operations entirely.

**Example console output with graph metrics:**

```
Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
    Type/Level: N/A (Project Reference)
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
           Graph: coupling=4.30, fan-in=1, fan-out=2, instability=0.667, in-cycle=no
```

### AI-Enhanced Type Extraction (Hybrid Git)

In Git Branch mode, Scatter needs to determine which C# types (`class`, `struct`, `interface`, `enum`) were modified in the diff. By default, it uses a regex pattern that extracts *every* type declaration found in any changed file. This can produce false positives — if you modify one class in a file that declares five classes, all five are flagged as changed.

With `--enable-hybrid-git`, Scatter sends the **full file content** and the **git diff** to the Gemini API. The LLM analyzes the diff to determine which types had their body, signature, or members *actually modified*, and returns only those. Types that merely appear in the same file but weren't touched are excluded.

**Regex extraction (default):**
- Finds all type declarations in every changed `.cs` file
- Fast, no API calls
- May over-report: a one-line change in a file with 5 classes flags all 5

**LLM-enhanced extraction (`--enable-hybrid-git`):**
- Analyzes the actual diff to identify meaningfully changed types
- Filters out comment-only and import-only changes (returns empty for those)
- Falls back to regex automatically if the LLM call fails
- Requires a Gemini API key

**Try it with the sample projects:**

```bash
# First, create a branch with changes to test against
git checkout -b feature/test-hybrid

# Make a change to a file in GalaxyWorks.Data (e.g., add a comment to PortalDataService)
# Then run with regex (default):
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope .

# Same analysis with LLM-enhanced extraction:
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY -v
```

With `--verbose`, you can see the LLM's analysis for each file:

```
Hybrid analysis for GalaxyWorks.Data/DataServices/PortalDataService.cs:
  1 affected type(s) identified by LLM: {'PortalDataService'}
```

If a change only affects comments or `using` statements, the LLM returns an empty list and no consumers are searched for that file — avoiding unnecessary analysis.

---

## Impact Analysis (Mode 4)

Impact analysis turns Scatter from a developer tool into a project-scoping tool. Instead of needing to know the exact `.csproj` or class name to analyze, you describe the change in natural language and get back a comprehensive risk assessment.

### Pipeline

```
Work request text
  → AI parses into structured AnalysisTargets
    → find_consumers() per target
      → BFS transitive tracing (consumers of consumers)
        → AI enrichment:
           • Risk assessment per target (Low/Medium/High/Critical)
           • Coupling narrative (why dependencies exist)
           • Complexity estimate with effort range
           • Manager-friendly impact summary
          → ImpactReport → console / JSON / CSV
```

### Usage

```bash
# Inline work request
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY

# Work request from file
python scatter.py \
  --sow-file docs/sample_sow.txt \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY

# Control transitive tracing depth (default: 2)
python scatter.py \
  --sow "Refactor GalaxyWorks.Data connection handling" \
  --search-scope . \
  --max-depth 3 \
  --google-api-key $GOOGLE_API_KEY

# JSON output for programmatic use
python scatter.py \
  --sow "Add caching to PortalDataService" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file impact_report.json
```

### Console Output Format

```
=== Impact Analysis Report ===
Work Request: Modify PortalDataService in GalaxyWorks.Data...
Overall Risk: High | Complexity: Medium (3-5 developer-days)

--- Target: GalaxyWorks.Data ---
Direct Consumers: 4 | Transitive: 1

  [HIGH] MyGalaxyConsumerApp (direct)
    Risk: Medium — "Uses PortalDataService directly..."
    Pipeline: consumer-app-pipeline

  [HIGH] GalaxyWorks.WebPortal (direct)
    Risk: High — "Core portal controller depends on this service..."
    Coupling: PortalController instantiates PortalDataService and calls multiple methods.
    Coupling vectors: Direct class instantiation, Method calls

  [MEDIUM] GalaxyWorks.BatchProcessor (depth: 1)
    Risk: Medium — "Transitive dependency through WebPortal..."

--- Complexity ---
Medium: Moderate blast radius with 4 direct and 1 transitive consumers.

--- Impact Summary ---
This change affects a core data access service used by 4 direct consumers
including the web portal and batch processing systems. Careful coordination
of deployments across the affected pipelines is recommended.
```

### Transitive Tracing

Impact analysis traces dependencies beyond direct consumers using BFS:

| Depth | Meaning | Confidence |
|-------|---------|------------|
| 0 | Direct consumer — has a `<ProjectReference>` and uses the target's namespace/class | HIGH (1.0) |
| 1 | Consumer of a consumer — one hop away from the change | MEDIUM (0.6) |
| 2+ | Deeply transitive — multiple hops, increasingly indirect | LOW (0.3) |

Cycle detection prevents infinite loops (A→B→A). The `--max-depth` flag controls how far the trace goes (default: 2).

### AI Enrichment

Impact mode makes several AI calls to enrich the raw dependency data:

| AI Task | Purpose | Output |
|---------|---------|--------|
| Work request parsing | Extract project names, classes, sprocs from natural language | `AnalysisTarget` list |
| Risk assessment | Rate risk per target based on consumer count, depth, pipelines | Low/Medium/High/Critical + justification |
| Coupling narrative | Explain *why* a dependency exists by reading consumer source code | Narrative text + coupling vectors |
| Complexity estimate | Estimate implementation effort based on blast radius metrics | Rating + effort range (e.g., "3-5 developer-days") |
| Impact narrative | Generate a manager-friendly summary of the full analysis | 1-2 paragraph summary |

All AI tasks require a Google Gemini API key (`--google-api-key` or `GOOGLE_API_KEY` env var).

---

## Parallel Processing

Scatter uses Python's `multiprocessing` module to parallelize file discovery and content analysis. This is enabled by default.

### What Gets Parallelized

| Phase | Operation | Default Chunk Size |
|-------|-----------|-------------------|
| File Discovery | Scanning directories for `.cs` and `.csproj` files | 75 directories |
| Content Analysis | Scanning `.cs` files for namespace usage, class references, sproc patterns | 50 files |
| XML Parsing | Parsing `.csproj` files to resolve `<ProjectReference>` dependencies | 25 files |
| Project Mapping | Mapping `.cs` files to their parent `.csproj` by directory walk | 50 files |

### Adaptive Worker Scaling

- < 200 files: up to 4 workers
- < 1000 files: up to 8 workers
- 1000+ files: up to `--max-workers` (default: CPU cores + 4, max 32)

If multiprocessing fails, processing falls back to sequential mode automatically.

### Multiprocessing Options

| Flag | Default | Description |
|------|---------|-------------|
| `--disable-multiprocessing` | `false` | Force sequential processing |
| `--max-workers N` | CPU cores + 4 (max 32) | Maximum worker processes |
| `--chunk-size N` | 75 | Directories per batch (file discovery) |
| `--cs-analysis-chunk-size N` | 50 | `.cs` files per batch (content analysis) |
| `--csproj-analysis-chunk-size N` | 25 | `.csproj` files per batch (XML parsing) |

```bash
# Tuning for a large codebase
python scatter.py --target-project src/Core/Core.csproj --search-scope /large/monorepo \
  --max-workers 16 --chunk-size 100 --cs-analysis-chunk-size 75

# Force sequential mode for debugging
python scatter.py --stored-procedure "dbo.sp_GetUser" --search-scope . --disable-multiprocessing
```

---

## Configuration & Mapping

Scatter loads configuration from multiple sources with layered precedence. You can set defaults in config files and override them per-invocation with CLI flags.

### Precedence Order

Settings are resolved from highest to lowest priority — the first source that provides a value wins:

| Priority | Source | Scope |
|----------|--------|-------|
| 1 (highest) | CLI flags (`--gemini-model`, etc.) | Single invocation |
| 2 | Repo config `.scatter.yaml` | Per-repository |
| 3 | User config `~/.scatter/config.yaml` | All repos for this user |
| 4 | Environment variables (`GOOGLE_API_KEY`, etc.) | Session / machine-wide |
| 5 (lowest) | Built-in defaults | Always present |

Missing config files are silently ignored — you don't need any config files to use Scatter.

### Config File Format

Both `.scatter.yaml` (repo-level) and `~/.scatter/config.yaml` (user-level) use the same schema:

```yaml
# .scatter.yaml — place in repo root (next to .git/)
ai:
  default_provider: gemini               # AI provider to use (currently only "gemini")
  gemini_model: gemini-2.0-flash         # Gemini model name
  task_overrides:                         # route specific AI tasks to specific providers
    work_request_parsing: gemini
    risk_assessment: gemini
  credentials:
    gemini:
      api_key: ""                         # prefer env var or user config for secrets

search:
  max_depth: 2                            # transitive tracing depth for impact analysis
  exclude_patterns:                       # glob patterns to skip during file scanning
    - "*/bin/*"                           # NOTE: this list REPLACES the defaults,
    - "*/obj/*"                           #       so re-list any defaults you want to keep
    - "*/node_modules/*"

multiprocessing:
  disabled: false
  max_workers: null                       # null = auto (CPU cores + 4, max 32)
  chunk_size: null                        # null = use built-in default (75)
```

### Typical Setup

**User-level config** (`~/.scatter/config.yaml`) — set your API key once, used across all repos:

```yaml
ai:
  credentials:
    gemini:
      api_key: "your-google-api-key-here"
```

**Repo-level config** (`.scatter.yaml`) — set repo-specific defaults:

```yaml
ai:
  gemini_model: gemini-2.0-flash
search:
  max_depth: 3
  exclude_patterns:
    - "*/bin/*"
    - "*/obj/*"
    - "*/test-fixtures/*"
```

CLI flags override everything — useful for one-off runs:

```bash
# Override the model for a single run, even if .scatter.yaml sets it differently
python scatter.py --sow "Modify PortalDataService" --search-scope . --gemini-model gemini-1.5-pro
```

### Environment Variables

| Variable | Maps to | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | `ai.credentials.gemini.api_key` | Google Gemini API key |
| `SCATTER_DEFAULT_PROVIDER` | `ai.default_provider` | Default AI provider name |

Environment variables sit below config files in precedence — a `.scatter.yaml` value overrides the env var, and a CLI flag overrides both.

### Google API Key

Required for AI summarization (`--summarize-consumers`), hybrid git analysis (`--enable-hybrid-git`), and impact analysis (`--sow` / `--sow-file`). Set it via any of these methods (highest precedence first):

```bash
# CLI flag (highest priority)
python scatter.py --sow "..." --search-scope . --google-api-key "your-key"

# Config file (user-level, recommended for persistent setup)
# ~/.scatter/config.yaml
# ai:
#   credentials:
#     gemini:
#       api_key: "your-key"

# Environment variable
export GOOGLE_API_KEY="your-key"
```

### Pipeline Mapping

Provide a CSV file (`--pipeline-csv`) to map project names to CI/CD pipelines. The CSV needs `Application Name` and `Pipeline Name` columns.

### Batch Job Verification

Use `--app-config-path` to verify if consumer projects correspond to known batch jobs in a configuration repository.

---

## Command-Line Reference

### Mode Selection (mutually exclusive, one required)

| Flag | Mode |
|------|------|
| `--branch-name BRANCH` | Git branch analysis |
| `--target-project PATH` | Target project analysis |
| `--stored-procedure NAME` | Stored procedure analysis |
| `--sow "TEXT"` | Impact analysis (inline) |
| `--sow-file PATH` | Impact analysis (from file) |
| `--graph` | Dependency graph analysis with domain clusters |

### Common Options

| Flag | Default | Description |
|------|---------|-------------|
| `--search-scope PATH` | (required) | Root directory to search for consumers |
| `--output-format FORMAT` | `console` | Output format: `console`, `csv`, `json`, `markdown`, `pipelines` |
| `--output-file PATH` | — | Output file path (required for csv/json; optional for markdown/pipelines — prints to stdout if omitted) |
| `--class-name NAME` | — | Filter by class/type name |
| `--method-name NAME` | — | Filter by method name (requires `--class-name`) |
| `--max-depth N` | `2` | Transitive tracing depth (impact mode) |
| `--graph-metrics` | `false` | Enrich consumer results with dependency graph metrics (coupling, fan-in/out, instability, cycle membership) |
| `--rebuild-graph` | `false` | Force graph rebuild, ignoring cache (`--graph` mode) |
| `--include-graph-topology` | `false` | Include raw graph nodes/edges in JSON output (`--graph` mode) |
| `--include-db` | `false` | Include database dependency scanning (`--graph` mode) |
| `--pipeline-csv PATH` | — | CSV file for pipeline mapping |
| `--app-config-path PATH` | — | App-config repo for batch job verification |
| `--target-namespace NS` | — | Override namespace detection |
| `-v, --verbose` | `false` | Enable DEBUG logging |

### Git Branch Options

| Flag | Default | Description |
|------|---------|-------------|
| `-r, --repo-path PATH` | `.` | Path to the Git repository |
| `-b, --base-branch BRANCH` | `main` | Base branch to compare against |
| `--enable-hybrid-git` | `false` | LLM-enhanced diff analysis |

### Stored Procedure Options

| Flag | Description |
|------|-------------|
| `--sproc-regex-pattern PATTERN` | Custom regex for finding sproc references |

### AI / Summarization Options

| Flag | Default | Description |
|------|---------|-------------|
| `--summarize-consumers` | `false` | AI-summarize relevant consumer files |
| `--google-api-key KEY` | `$GOOGLE_API_KEY` | Google Gemini API key |
| `--gemini-model MODEL` | `gemini-1.5-flash` | Gemini model to use |

Run `python scatter.py --help` for the full list with defaults.

---

## Output Formats

### Console (default)

Human-readable report listing each target and its consumers with pipeline mappings, solutions, and optional AI summaries.

### JSON (`--output-format json --output-file report.json`)

Structured JSON. For legacy modes (git/target/sproc), the output includes `pipeline_summary`, `all_results`, and an optional `filter_pipeline` object showing intermediate counts at each stage of the consumer detection pipeline. For impact mode, the output is the full `ImpactReport` structure:

```json
{
  "sow_text": "Modify PortalDataService...",
  "targets": [
    {
      "target": { "target_type": "project", "name": "GalaxyWorks.Data", ... },
      "consumers": [
        {
          "consumer_name": "MyGalaxyConsumerApp",
          "depth": 0,
          "confidence": 1.0,
          "confidence_label": "HIGH",
          "risk_rating": "Medium",
          "risk_justification": "...",
          "pipeline_name": "...",
          ...
        }
      ],
      "total_direct": 4,
      "total_transitive": 1
    }
  ],
  "complexity_rating": "Medium",
  "effort_estimate": "3-5 developer-days",
  "impact_narrative": "...",
  "overall_risk": "High"
}
```

### CSV (`--output-format csv --output-file report.csv`)

For legacy modes: one row per consumer relationship with columns for target, consumer, pipeline, etc. When filter pipeline data is available, a `#`-prefixed comment header is prepended with the search scope and filter arrow chain (most CSV parsers ignore `#` comment lines).

For impact mode: one row per consumer with columns: `Target`, `TargetType`, `Consumer`, `ConsumerPath`, `Depth`, `Confidence`, `ConfidenceLabel`, `RiskRating`, `RiskJustification`, `Pipeline`, `Solutions`, `CouplingVectors`.

### Markdown (`--output-format markdown`)

Paste-ready markdown for PRs, tickets, wikis, and Confluence. Unlike CSV and JSON, markdown does not require `--output-file` — when omitted, the report prints to stdout (pipe to `pbcopy` or `clip` for clipboard).

```bash
# Markdown to stdout (pipe to clipboard)
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format markdown

# Markdown to file
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format markdown --output-file /tmp/scatter_report.md

# Impact analysis as markdown
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format markdown --output-file /tmp/impact.md

# Graph analysis as markdown (includes Mermaid diagram)
python scatter.py --graph --search-scope . \
  --output-format markdown --output-file /tmp/graph.md
```

**Legacy modes** produce a markdown table per target with Consumer, Path, Pipeline, and Solutions columns plus a summary footer.

**Impact mode** includes a risk/complexity header, a blast radius tree in a fenced `text` code block (preserving the tree hierarchy from Phase 3), a consumer detail table with 7 columns, and optional complexity/narrative sections.

### Pipelines (`--output-format pipelines`)

Pipe-friendly output for release managers and deployment scripts. Prints sorted unique pipeline names to stdout, one per line, no headers or decoration. Requires `--pipeline-csv` to be useful (warns on stderr if omitted). Not supported in graph mode.

```bash
# Pipeline names to stdout — pipe to deployment scripts
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --pipeline-csv pipeline_to_app_mapping.csv --output-format pipelines

# Pipeline names to file
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --pipeline-csv pipeline_to_app_mapping.csv --output-format pipelines --output-file pipelines.txt

# Impact mode — which pipelines does this SOW affect?
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --pipeline-csv pipeline_to_app_mapping.csv --output-format pipelines

# Count affected pipelines
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --pipeline-csv pipeline_to_app_mapping.csv --output-format pipelines | wc -l
```

**Graph mode** includes a summary stats table, top coupled projects table, numbered cycles list, domain clusters table, health observations, and an inline Mermaid dependency diagram (rendered natively by GitHub, Azure DevOps, and Confluence).

---

## Testing

### Running Tests

```bash
# Full local CI check (lint + format + mypy + pytest)
bash tools/check.sh

# Quick lint-only check (~2 seconds)
bash tools/check.sh --quick

# Run just the test suite
uv run pytest

# Run specific test file
uv run pytest test_impact_analysis.py -v

# Run with coverage
uv run pytest --cov=scatter --cov-report=term-missing
```

### Test Suite Overview

The test suite includes **588 tests** across 20 test files (587 pass, 1 xfail):

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_config.py` | 24 | Config loading, YAML precedence, env vars, CLI overrides, AI router (caching, task overrides, unknown providers) |
| `test_coupling.py` | 25 | Coupling metrics (fan_in/out, instability, coupling_score, shared_db_density), Tarjan's SCC cycle detection, edge type filtering, rank_by_coupling |
| `test_db_scanner.py` | 36 | DB scanner: comment stripping, sproc/DbSet/DbContext/SQL/connection string detection, `_FileIndex` with struct/record/interface, cross-project matrix, graph edges, config, integration |
| `test_domain.py` | 15 | Domain boundary detection: two-level clustering, label propagation, determinism, cluster naming, extraction feasibility scoring, API surface penalty |
| `test_filter_pipeline.py` | 21 | Filter pipeline visibility: `FilterStage`/`FilterPipeline` dataclass construction, `format_arrow_chain()`, `filter_value_for_stage()`, `find_consumers()` tuple return, pipeline stages (discovery, project_ref, class), zero-results pipeline, console/JSON/CSV reporter integration, backward compatibility |
| `test_find_enclosing_type.py` | 14 | `find_enclosing_type_name()`: basic types (class/struct/interface/enum/record), nested types, generics, readonly/ref struct, edge cases (before-any-declaration, empty content) |
| `test_graph.py` | 46 | Graph data structures, construction, traversal, serialization, `.csproj` parsing, integration with sample projects |
| `test_graph_cache.py` | 28 | Graph persistence: save/load roundtrip, smart git-based cache invalidation, mtime fallback |
| `test_graph_patcher.py` | 49 | Incremental graph updates: v2 cache format, edge removal (4-index consistency), fact extraction, patch algorithm (usage-only, declaration, delete, new file, .csproj, thresholds, structural changes, content hash cutoff), property tests (incremental == full rebuild for 6 mutation types), integration |
| `test_hybrid_git.py` | 7 | LLM-enhanced git diff analysis |
| `test_impact_analysis.py` | 82 | Impact analysis: data models, CLI args, work request parsing, transitive tracing, risk assessment, coupling narrative, impact narrative, complexity estimate, reporters, end-to-end, blast radius tree view (model, BFS parent tracking, orphan re-parenting, console tree, JSON tree, CSV) |
| `test_multiprocessing_phase1.py` | 7 | Parallel file discovery, chunk utility, error handling, symbol search consistency, backwards compatibility |
| `test_new_samples.py` | 54 | Sample project validation: type extraction across all sample projects, consumer detection, project reference resolution |
| `test_phase2_3_project_mapping.py` | 24 | Batch project mapping, parallel orchestration, sproc integration |
| `test_report_quality.py` | 24 | JSON serialization fixes, metadata blocks, console polish, CSV cleanup, version constant, API key redaction |
| `test_reporters.py` | 21 | Mermaid output, health dashboard observations, console cluster members, CSV export columns, JSON topology flag |
| `test_markdown_reporter.py` | 39 | Markdown output: cell escaping, legacy/impact/graph builders, column-count validation, table edge cases, pipe-in-field escaping, narrative section absence, CLI dispatch (_require_output_file, markdown stdout fallback), file I/O |
| `test_summarize_consumers.py` | 7 | AI consumer summarization wiring: happy path, no provider, unsupported task, partial failure, no relevant files, results_start_index, stem collision |
| `test_graph_enrichment.py` | 17 | Graph enrichment: GraphContext construction, legacy result injection (matched/unmatched/idempotent), EnrichedConsumer population, no-graph reporter regression (console/JSON/CSV/markdown), schema stability with flag |
| `test_type_extraction.py` | 48 | Type declaration regex: class/struct/interface/enum/record variants, delegates, readonly/ref struct, primary constructors, attributes, nested types, record false positives, dedup, pathological input, comment filtering |

### What the Tests Cover

**Data model construction** — All 4 impact analysis dataclasses (`AnalysisTarget`, `EnrichedConsumer`, `TargetImpact`, `ImpactReport`) with defaults and field validation.

**CLI argument parsing** — Mutual exclusivity between modes (`--sow` vs `--branch-name` vs `--target-project` vs `--stored-procedure`), required argument validation.

**AI task modules** — Each AI task (work request parsing, risk assessment, coupling narrative, impact narrative, complexity estimate) is tested with mock AI responses for:
- Valid JSON responses
- Empty responses
- Invalid JSON / non-list responses
- Markdown code fence stripping
- API failures / exceptions
- No-provider graceful fallback

**Transitive tracing** — Depth-0 returns only direct consumers, depth-1 finds transitive, cycle detection (A→B→A), confidence decay by depth, max depth enforcement.

**Reporters** — Console output formatting, JSON serialization (including `Path` objects), CSV column structure, empty report handling.

**Hybrid git type extraction** — LLM-based symbol extraction with mock model responses, fallback to regex on failure, JSON parsing of model output, markdown fence stripping.

**End-to-end integration** — Full pipeline with all AI mocked: SOW text → parse → find_consumers → transitive tracing → enrichment → report generation.

**Parallel vs sequential consistency** — Every parallel operation is verified to produce identical results when run sequentially with `--disable-multiprocessing`.

All AI-dependent tests use mock models (no real API calls). The mocks simulate valid JSON responses, empty responses, malformed JSON, API exceptions, and markdown-fenced output to verify graceful handling of every failure mode.

### Testing with the Sample Projects

The sample .NET projects in the repository provide real-world test scenarios. Commands below are grouped by what they verify.

**Core analysis (no API key needed):**

```bash
# Verify GalaxyWorks.Data has 4 consumers (WebPortal, BatchProcessor, 2x ConsumerApp)
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

# Verify MyDotNetApp has exactly 1 consumer (MyDotNetApp.Consumer)
python scatter.py --target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .

# Verify MyDotNetApp2.Exclude has 0 consumers (standalone project)
python scatter.py --target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .

# Verify sproc tracing finds PortalDataService as the referencing class
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# Verify class filtering narrows results
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService

# Test output formats
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format json --output-file /tmp/test_output.json

python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format csv --output-file /tmp/test_output.csv
```

**AI Consumer Summarization (requires `$GOOGLE_API_KEY`):**

```bash
# Summarize what each consumer of GalaxyWorks.Data does with it
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarize with class filter — only PortalDataService consumers
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarize consumers of a stored procedure
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarization with JSON output — summaries in ConsumerFileSummaries field
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/summarized.json
```

**AI Hybrid Git Type Extraction (requires `$GOOGLE_API_KEY` + a feature branch):**

```bash
# Create a test branch, modify a file, then analyze
git checkout -b feature/test-hybrid
echo "// test change" >> GalaxyWorks.Data/DataServices/PortalDataService.cs
git add GalaxyWorks.Data/DataServices/PortalDataService.cs

# Regex extraction (default) — may flag all types in the file
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope . -v

# LLM extraction — only flags types whose body/signature actually changed
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY -v

# Clean up
git checkout main && git branch -D feature/test-hybrid
```

**AI Impact Analysis (requires `$GOOGLE_API_KEY`):**

```bash
# Natural language work request → risk-rated impact report
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . --google-api-key $GOOGLE_API_KEY

# Transitive tracing — BatchProcessor is a transitive consumer of WebPortal
python scatter.py \
  --sow "Modify PortalCacheService in GalaxyWorks.WebPortal" \
  --search-scope . --max-depth 1 --google-api-key $GOOGLE_API_KEY

# Impact report as JSON
python scatter.py \
  --sow "Refactor GalaxyWorks.Data connection handling" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/impact.json

# Impact report as CSV
python scatter.py \
  --sow "Refactor GalaxyWorks.Data connection handling" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format csv --output-file /tmp/impact.csv
```

### Benchmarking

Scatter includes three benchmark tools for measuring performance at various scales. All benchmarks use a synthetic codebase generator that creates realistic .NET monoliths with configurable project counts, coupling density, and file sizes.

#### Generate a Synthetic Codebase

```bash
# Generate with a preset (small=100, medium=250, large=500, xlarge=800 projects)
python tools/generate_synthetic_codebase.py --preset large --output /tmp/synthetic_monolith

# Custom parameters
python tools/generate_synthetic_codebase.py --projects 300 --files-per-project 25 \
  --coupling-pct 0.04 --avg-file-kb 15 --output /tmp/custom_monolith

# Reproducible generation (default seed=42)
python tools/generate_synthetic_codebase.py --preset medium --seed 123 --output /tmp/seeded
```

#### Benchmark Full Graph Build

Instruments each internal stage of the graph builder (file discovery, csproj parsing, type extraction, edge construction, metrics, clustering, health dashboard) with wall-clock timing and memory tracking.

```bash
# Stage-level instrumentation (default)
python tools/benchmark_graph_build.py /tmp/synthetic_monolith

# Black-box mode (calls build_dependency_graph() as a single stage)
python tools/benchmark_graph_build.py /tmp/synthetic_monolith --mode full

# Multiple runs with warmup for reliable median timing
python tools/benchmark_graph_build.py /tmp/synthetic_monolith --runs 3 --warmup

# Include DB dependency scanning stage
python tools/benchmark_graph_build.py /tmp/synthetic_monolith --include-db

# JSON output for programmatic consumption
python tools/benchmark_graph_build.py /tmp/synthetic_monolith --json -o results.json
```

#### Benchmark Incremental Graph Updates

Compares `patch_graph()` (incremental) vs `build_dependency_graph()` (full rebuild) across 9 mutation scenarios at configurable scales.

```bash
# Default: benchmark small (100 projects) and medium (250 projects)
python tools/benchmark_incremental.py

# Specific presets
python tools/benchmark_incremental.py --preset small medium large

# Multiple runs for reliable median timing
python tools/benchmark_incremental.py --runs 3

# JSON output
python tools/benchmark_incremental.py --json -o incremental_results.json
```

The 9 mutation scenarios tested:
- **Usage-only** (1/5/10 files) — editing method bodies, adding `using` statements
- **Declaration change** (1/5 files) — adding/renaming a class (triggers global type_usage rebuild)
- **New file** (1/5 files) — adding `.cs` files to existing projects
- **Deleted file** — removing a `.cs` file
- **csproj modified** — changing a project reference or framework

Example output:
```
Scenario                          small (100)    medium (250)
--------------------------------------------------------------
Full rebuild (baseline)              1137ms          9507ms
  1 file usage-only                   111x            954x
  10 files usage-only                  16x             30x
  1 file declaration change             2x              1x
  1 csproj modified                   122x            253x
```

#### Compare Parallel vs Sequential

```bash
# Compare on your own codebase
time python scatter.py --target-project ./MyLib/MyLib.csproj --search-scope /your/codebase -v
time python scatter.py --target-project ./MyLib/MyLib.csproj --search-scope /your/codebase --disable-multiprocessing -v
```

---

## Technical Details

### Type Extraction

In Git Branch mode, type declarations are extracted from changed `.cs` files. Scatter supports two extraction strategies:

**Regex extraction (default)** uses a compiled pattern to find type declarations with access modifiers, generics, and keywords like `static`, `abstract`, `sealed`, `partial`, `record`, `readonly`, and `ref`:

```python
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"  # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+|record\s+|readonly\s+|ref\s+)*"  # Optional keywords
    r"(?:class|struct|interface|enum|record)\s+"  # Type keyword
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)"  # Capture type name (non-greedy)
    r"\s*(?::|{|where|<|\(|;)",  # Look for end of declaration
    re.MULTILINE
)
```

This is fast and requires no API calls, but extracts *every* type declared in each changed file — even types whose code was not touched by the diff.

**LLM extraction (`--enable-hybrid-git`)** sends both the file content and the git diff to the Gemini API with a prompt asking it to identify only types whose body, signature, or members were meaningfully changed. The LLM returns a JSON array of affected type names. If the LLM call fails or returns invalid JSON, Scatter falls back to regex automatically.

| Aspect | Regex (default) | LLM (`--enable-hybrid-git`) |
|--------|-----------------|----------------------------|
| Speed | Instant (no API call) | ~1-2s per file (API round-trip) |
| Precision | Extracts all types in file | Only types with meaningful changes |
| Comment-only changes | Flags all types in file | Returns empty (no analysis needed) |
| API key required | No | Yes |
| Failure mode | N/A | Falls back to regex |

### Consumer Detection Pipeline

The core consumer detection runs in 5 stages, each progressively filtering:

1. **File Discovery** — Find all `.csproj` files in the search scope
2. **ProjectReference Filter** — Keep only projects with a `<ProjectReference>` to the target
3. **Namespace Filter** — Keep only projects with `using TargetNamespace;` statements
4. **Class Filter** (optional) — Keep only projects referencing the specific class name
5. **Method Filter** (optional) — Keep only projects calling the specific method

The intermediate counts at each stage are captured in a `FilterPipeline` object and surfaced in all output formats. This makes it easy to debug zero-result scenarios — you can see exactly which stage dropped the candidates and what filter value was applied. Console output shows a one-line arrow chain:

```
Search scope: /path/to/repo (scanned 200 projects, 1,847 files)
Filter: 200 → 12 project refs → 8 namespace → 4 class match → 2 method match
```

When a stage drops to zero, a diagnostic hint identifies the problematic filter:

```
Filter: 200 → 12 project refs → 8 namespace → 0 class match
  Hint: 0 of 8 namespace-matching projects contained 'WidgetFactory' — verify the class name
```

### Impact Analysis Architecture

Impact analysis adds an orchestrator layer (`scatter/analyzers/impact_analyzer.py`) on top of the existing consumer detection pipeline:

```
scatter/
├── config.py              # YAML config loading with layered precedence
├── core/
│   ├── models.py          # AnalysisTarget, EnrichedConsumer, TargetImpact, ImpactReport
│   ├── graph.py           # ProjectNode, DependencyEdge, DependencyGraph (pure data structure)
│   └── parallel.py        # Multiprocessing infrastructure
├── ai/
│   ├── base.py            # AIProvider protocol, AITaskType enum
│   ├── router.py          # AIRouter — provider selection per task type
│   ├── providers/
│   │   └── gemini_provider.py
│   └── tasks/
│       ├── parse_work_request.py    # SOW → AnalysisTarget list
│       ├── risk_assess.py           # Per-target risk rating
│       ├── coupling_narrative.py    # Dependency explanation
│       ├── impact_narrative.py      # Manager-friendly summary
│       └── complexity_estimate.py   # Effort/complexity rating
├── analyzers/
│   ├── consumer_analyzer.py   # Core find_consumers() pipeline
│   ├── coupling_analyzer.py   # Metrics (fan_in/out, instability, coupling_score) + Tarjan's SCC cycle detection
│   ├── domain_analyzer.py     # Domain boundary detection + extraction feasibility scoring
│   ├── git_analyzer.py        # Git branch diff analysis
│   ├── graph_builder.py       # Single-pass O(P+F) graph construction
│   └── impact_analyzer.py     # Impact analysis orchestrator + transitive tracing
├── scanners/                  # Type, project, sproc scanners
├── reports/
│   ├── console_reporter.py    # print_console_report() + print_impact_report() + render_tree()
│   ├── json_reporter.py       # write_json_report() + write_impact_json_report()
│   ├── csv_reporter.py        # write_csv_report() + write_impact_csv_report()
│   ├── graph_reporter.py      # print_graph_report() + build_graph_json() + generate_mermaid() + write_graph_csv_report()
│   └── markdown_reporter.py   # build_markdown() + build_impact_markdown() + build_graph_markdown() + write_*()
└── __main__.py                # CLI entry point with 5-mode dispatch
```

---

## Dependency Graph

The dependency graph is a persistent, in-memory data structure that captures the full project-to-project dependency topology of a .NET codebase. It replaces repeated calls to `find_consumers()` (each of which re-scans the filesystem) with a single upfront construction pass, after which all queries — consumers, dependencies, transitive impact, connected components — are answered from the graph in constant or linear time relative to the graph size, not the filesystem.

### Architecture

The graph follows a strict **Single Responsibility Principle** separation: `DependencyGraph` in `scatter/core/graph.py` is a pure data structure (mutation, query, traversal, serialization only), while all construction logic lives in `scatter/analyzers/graph_builder.py`. Analysis algorithms (cycle detection, coupling metrics, clustering) are standalone functions in their respective analyzer modules — they are never methods on the graph itself.

#### Data Structures

**`ProjectNode`** — A dataclass representing a single `.csproj` project:

| Field | Type | Description |
|-------|------|-------------|
| `path` | `Path` | Absolute path to the `.csproj` file |
| `name` | `str` | Project name (filename stem, e.g. `GalaxyWorks.Data`) |
| `namespace` | `Optional[str]` | Root namespace from `<RootNamespace>`, `<AssemblyName>`, or filename |
| `framework` | `Optional[str]` | Target framework (e.g. `net8.0`, `v4.7.2`) |
| `project_style` | `str` | `"sdk"` or `"framework"` — detected from `<Project Sdk="...">` attribute |
| `output_type` | `Optional[str]` | `Library`, `Exe`, etc. |
| `file_count` | `int` | Number of `.cs` files belonging to this project |
| `type_declarations` | `List[str]` | Sorted list of type names declared in this project's `.cs` files |
| `sproc_references` | `List[str]` | Sorted list of stored procedure names referenced in string literals |

Design note: `file_count` stores a count, not a `List[Path]` of file paths — this prevents unbounded memory growth in large codebases (thousands of `.cs` files per project would bloat the serialized graph).

**`DependencyEdge`** — A directed edge between two projects:

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Name of the project that *depends on* the target |
| `target` | `str` | Name of the project being depended upon |
| `edge_type` | `str` | One of `"project_reference"`, `"namespace_usage"`, `"type_usage"` |
| `weight` | `float` | Strength of the dependency (1.0 for project refs, evidence count for others) |
| `evidence` | `Optional[List[str]]` | File paths or `file:TypeName` pairs showing where the dependency occurs |
| `evidence_total` | `int` | Total evidence count (may exceed `len(evidence)` due to capping) |

Evidence is capped at `MAX_EVIDENCE_ENTRIES = 10` entries per edge. If an edge has 500 evidence entries (e.g., a utility project referenced from 500 `.cs` files), only the first 10 are stored and `evidence_total` records the true count of 500. This bounds serialization size while preserving the magnitude signal.

**`DependencyGraph`** — The container holding all nodes and edges with four internal indexes:

```
_nodes:    Dict[str, ProjectNode]        # name → node (O(1) lookup)
_outgoing: Dict[str, List[DependencyEdge]]  # source → edges leaving this node
_incoming: Dict[str, List[DependencyEdge]]  # target → edges arriving at this node
_forward:  Dict[str, Set[str]]           # source → set of dependency names (adjacency)
_reverse:  Dict[str, Set[str]]           # target → set of consumer names (reverse adjacency)
```

The dual index design (`_outgoing`/`_incoming` for full edge data, `_forward`/`_reverse` for fast adjacency checks) means every query — "what does project X depend on?", "what consumes project X?", "what are all edges between A and B?" — runs in O(degree) time without scanning all edges in the graph.

#### Edge Types

The graph captures four categories of inter-project dependency:

| Edge Type | Source | Meaning | Weight |
|-----------|--------|---------|--------|
| `project_reference` | `<ProjectReference Include="...">` in `.csproj` | Explicit build-time dependency | 1.0 (always) |
| `namespace_usage` | `using Namespace;` in `.cs` matching another project's root namespace | Import-level coupling | Count of `.cs` files with that `using` |
| `type_usage` | Inverted index: tokenize identifiers, intersect with known types (comment-stripped) | Code-level coupling (class/interface usage) | Count of `file:TypeName` matches |
| `sproc_shared` | Stored procedure name referenced by projects in both source and target | Shared mutable database state | Number of shared sprocs |

A single pair of projects may have multiple edges (e.g., A has a `project_reference` to B *and* a `namespace_usage` edge *and* a `type_usage` edge). The `get_edges_between(a, b)` method returns all of them.

### Performance and Big O

#### Graph Construction — `build_dependency_graph()`

Construction is a **single-pass O(P + F)** algorithm where P = number of `.csproj` files and F = number of `.cs` files:

| Step | Operation | Complexity |
|------|-----------|------------|
| 1 | Discover `.csproj` files (parallel glob) | O(dirs) |
| 2 | Parse each `.csproj` — XML parse, extract metadata | O(P × avg_xml_size) |
| 3 | Discover `.cs` files (parallel glob) | O(dirs) |
| 4 | Build reverse directory index, map `.cs` → parent project | O(F × P) worst-case, O(F × log P) typical |
| 5 | Read each `.cs` file, extract types + sprocs + usings | O(F × avg_file_size) |
| 6 | Build `project_reference` edges (resolve Include paths) | O(P × avg_refs) |
| 7 | Build `namespace_usage` edges (match usings to project namespaces) | O(P × U) where U = unique usings per project |
| 8 | Build `type_usage` edges (inverted index: tokenize + set intersection) | O(F × S) where S = avg file size |

Step 8 (`type_usage` edge construction) uses an **inverted index** approach: each `.cs` file is read once, comments are stripped via `_strip_cs_comments()`, identifiers are tokenized with a single regex pass (`[A-Za-z_]\w*`), and the resulting set is intersected with the set of all known type names. This eliminates the type count (T) from the equation entirely — performance depends only on file count and file size, not on how many types exist in the codebase.

This replaced an earlier O(F × T × S) approach that ran a separate regex search per type per file. At 100 projects that was 1.17M regex operations taking 172 seconds. The inverted index does the same work in 1.7 seconds — a **101x speedup**. At 500 projects, the full graph builds in under 60 seconds.

Comment stripping before tokenization prevents false dependency edges from type names appearing in `//` and `/* */` comments. Type names that appear in multiple projects are tracked via a multi-owner map (`type_to_projects: Dict[str, Set[str]]`) so no edges are silently dropped.

See `docs/ADR_GRAPH_PERFORMANCE.md` for the full architecture decision record including alternatives considered (mega-regex, Aho-Corasick), benchmark methodology, and the remaining optimization roadmap.

**Contrast with per-query scanning:** Without the graph, each call to `find_consumers("ProjectX")` rescans the entire filesystem — discovering `.csproj` files, parsing XML, scanning `.cs` files for namespace and class usage. For N target projects, this is O(N × (P + F)). The graph pays O(P + F) once and answers all N queries from memory.

#### Graph Queries

| Operation | Method | Complexity |
|-----------|--------|------------|
| Get a node by name | `get_node(name)` | O(1) dict lookup |
| Get all nodes | `get_all_nodes()` | O(N) |
| Direct dependencies | `get_dependencies(name)` | O(out-degree) |
| Direct consumers | `get_consumers(name)` | O(in-degree) |
| Outgoing edges (with full edge data) | `get_edges_from(name)` | O(out-degree) |
| Incoming edges (with full edge data) | `get_edges_to(name)` | O(in-degree) |
| All edges for a node | `get_edges_for(name)` | O(degree) |
| Edges between two nodes (both directions) | `get_edges_between(a, b)` | O(degree of a + degree of b) |
| Transitive consumers (BFS) | `get_transitive_consumers(name, max_depth)` | O(V + E) within depth bound |
| Transitive dependencies (BFS) | `get_transitive_dependencies(name, max_depth)` | O(V + E) within depth bound |
| Connected components | `connected_components` property | O(V + E) full BFS |
| Node count | `node_count` property | O(1) |
| Edge count | `edge_count` property | O(N) — iterates outgoing lists |
| All edges (flat list) | `all_edges` property | O(E) |

All traversal methods use a `visited` set to ensure cycle safety — even if the graph contains cycles (A → B → C → A), BFS never visits the same node twice.

#### Serialization

| Operation | Method | Complexity |
|-----------|--------|------------|
| Export to dict | `to_dict()` | O(V + E) |
| Import from dict | `DependencyGraph.from_dict(data)` | O(V + E) |

The `to_dict()` / `from_dict()` roundtrip produces JSON-compatible dicts. All `Path` objects are serialized as strings. The graph can be persisted to disk as JSON and reconstructed without rescanning the filesystem.

### Construction Pipeline

`build_dependency_graph()` in `scatter/analyzers/graph_builder.py` orchestrates a six-step pipeline:

```
search_scope (Path)
  │
  ├─ Step 1: Discover all .csproj files (parallel glob)
  │    └─ Filter by exclude_patterns (default: */bin/*, */obj/*, */temp_test_data/*)
  │
  ├─ Step 2: Parse each .csproj
  │    ├─ parse_csproj_all_references() → project_references, framework, style, output_type
  │    └─ derive_namespace() → root namespace (RootNamespace > AssemblyName > filename stem)
  │
  ├─ Step 3: Discover all .cs files (parallel glob)
  │    ├─ Filter by exclude_patterns
  │    └─ Map each .cs to parent project via reverse directory index
  │         (index sorted deepest-first so nested projects match before parents)
  │
  ├─ Step 4: For each project's .cs files, extract:
  │    ├─ Type declarations (class, struct, interface, enum names)
  │    ├─ Sproc references (sp_/usp_ in string literals)
  │    └─ Using statements (namespace imports)
  │
  ├─ Step 5: Build nodes (one ProjectNode per .csproj with aggregated metadata)
  │
  └─ Step 6: Build edges
       ├─ 6a: project_reference — resolve <ProjectReference Include="..."> paths
       ├─ 6b: namespace_usage — match using statements to project namespaces
       └─ 6c: type_usage — strip comments, tokenize identifiers, intersect with known types
```

**`.csproj` parsing** handles both SDK-style projects (`<Project Sdk="Microsoft.NET.Sdk">`) and legacy Framework-style projects (with MSBuild XML namespace `http://schemas.microsoft.com/developer/msbuild/2003`). The `parse_csproj_all_references()` function tries XPath queries without namespace first, then with the MSBuild namespace prefix, ensuring both styles are parsed correctly.

**Reverse directory index** maps `.cs` files to their parent `.csproj` by building a sorted list of `(project_directory, project_name)` pairs, sorted deepest-first by path depth. For each `.cs` file, it walks up the parent chain and returns the first matching project directory. This handles nested project structures where a `.cs` file under `src/Lib/SubLib/` should match the `SubLib.csproj` in that directory, not the `Lib.csproj` one level up.

**Exclude patterns** default to `["*/bin/*", "*/obj/*", "*/temp_test_data/*"]` and use `fnmatch.fnmatch()` for glob-style matching. They can be overridden via the `exclude_patterns` parameter or through `.scatter.yaml` config.

### Incremental Graph Updates

When the dependency graph is cached (v2 format), subsequent runs use git diff to identify changed files since the last build and surgically patch the graph instead of rebuilding from scratch. This is transparent — the cached graph is automatically updated on the next run.

**How it works:**

1. `get_changed_files()` runs `git diff --name-only <cached_head> HEAD -- *.cs *.csproj` to find changes
2. Changed `.cs` files are mapped to their parent projects via the reverse directory index
3. **Content hash early cutoff** — if the file's SHA-256 hash hasn't changed (e.g., whitespace-only edits), skip re-extraction
4. **Declaration early cutoff** — if `types_declared` are unchanged after re-extraction, only rebuild edges for the affected project (not globally)
5. **Edge rebuild** — remove and reconstruct namespace_usage, type_usage, and sproc_shared edges for affected projects
6. **Global rebuild triggers** — if any type declarations changed, all projects' type_usage edges are rebuilt (any project could reference the new/renamed type)

**Safety valves** (trigger full rebuild instead):
- Structural changes: `.csproj` added or removed
- Threshold exceeded: >50 affected projects or >30% of files changed
- Project set hash mismatch: external tool added/removed a project
- Git diff failure: unreachable commit, non-git directory

**Cache format:**

The v2 cache envelope extends v1 with per-file and per-project facts:

| Field | Description |
|-------|-------------|
| `file_facts` | `Dict[relative_path, FileFacts]` — types, namespaces, sprocs, content hash per `.cs` file |
| `project_facts` | `Dict[project_name, ProjectFacts]` — namespace, project references, csproj content hash |
| `project_set_hash` | SHA-256 of sorted project names — detects structural changes |
| `git_head` | Commit hash at time of build — used as git diff baseline |

v1 caches are automatically upgraded: loading a v1 cache triggers a full rebuild with `capture_facts=True`, saving the result as v2.

**Performance (synthetic codebase benchmarks):**

| Scenario | 100 projects | 250 projects |
|----------|-------------|-------------|
| Full rebuild | 1.1s | 9.5s |
| 1 file usage change | 10ms (110x) | 10ms (954x) |
| 10 files usage change | 70ms (16x) | 315ms (30x) |
| 1 csproj modified | 9ms (122x) | 38ms (253x) |
| 1 declaration change | 555ms (2x) | 7060ms (1.3x) |

Usage-only changes (the most common real-world scenario — editing method bodies, adding imports) see 10-954x speedups. Declaration changes trigger global type_usage rebuilds, giving more modest speedups.

### Programmatic API

#### Building a Graph

```python
from pathlib import Path
from scatter.analyzers.graph_builder import build_dependency_graph

# Build the graph from a codebase directory
graph = build_dependency_graph(
    search_scope=Path("/path/to/dotnet/solution"),
    max_workers=8,              # parallel workers (default: CPU cores + 4)
    chunk_size=75,              # directories per parallel batch
    disable_multiprocessing=False,
    exclude_patterns=["*/bin/*", "*/obj/*", "*/test-fixtures/*"],
)

print(f"Discovered {graph.node_count} projects, {graph.edge_count} edges")
```

#### Querying the Graph

```python
# Get a specific project node
node = graph.get_node("GalaxyWorks.Data")
print(f"Project: {node.name}")
print(f"Namespace: {node.namespace}")
print(f"Framework: {node.framework}")
print(f"Style: {node.project_style}")
print(f"Files: {node.file_count}")
print(f"Types: {node.type_declarations}")
print(f"Sprocs: {node.sproc_references}")

# Find direct consumers (who depends on this project?)
consumers = graph.get_consumers("GalaxyWorks.Data")
for c in consumers:
    print(f"  Consumer: {c.name} ({c.framework})")

# Find direct dependencies (what does this project depend on?)
deps = graph.get_dependencies("GalaxyWorks.BatchProcessor")
for d in deps:
    print(f"  Depends on: {d.name}")

# Get detailed edge information between two projects
edges = graph.get_edges_between("GalaxyWorks.WebPortal", "GalaxyWorks.Data")
for edge in edges:
    print(f"  {edge.source} → {edge.target} [{edge.edge_type}] weight={edge.weight}")
    if edge.evidence:
        for ev in edge.evidence:
            print(f"    Evidence: {ev}")
```

#### Transitive Traversal

```python
# Find all transitive consumers of a core library (up to 3 hops)
transitive = graph.get_transitive_consumers("GalaxyWorks.Data", max_depth=3)
for node, depth in transitive:
    print(f"  {'  ' * depth}{node.name} (depth {depth})")

# Example output for the sample projects:
#   GalaxyWorks.WebPortal (depth 1)
#   MyGalaxyConsumerApp (depth 1)
#   MyGalaxyConsumerApp2 (depth 1)
#     GalaxyWorks.BatchProcessor (depth 2)

# Find all transitive dependencies (what does this project ultimately rely on?)
deps = graph.get_transitive_dependencies("GalaxyWorks.BatchProcessor", max_depth=3)
for node, depth in deps:
    print(f"  {'  ' * depth}{node.name} (depth {depth})")

# Example output:
#   GalaxyWorks.Data (depth 1)
#   GalaxyWorks.WebPortal (depth 1)
```

Both traversal methods use BFS with a visited set, guaranteeing cycle safety. If the graph contains A → B → C → A, the BFS visits each node exactly once and terminates.

#### Connected Components

```python
# Find clusters of related projects
components = graph.connected_components
print(f"Found {len(components)} connected component(s)")
for i, component in enumerate(components):
    print(f"  Component {i+1}: {component}")

# For the sample projects (with namespace/type edges connecting everything):
#   Component 1: ['GalaxyWorks.BatchProcessor', 'GalaxyWorks.Data', 'GalaxyWorks.WebPortal',
#                  'MyDotNetApp', 'MyDotNetApp.Consumer', 'MyDotNetApp2.Exclude',
#                  'MyGalaxyConsumerApp', 'MyGalaxyConsumerApp2']
```

Components are sorted largest-first and alphabetically within each component. They treat all edges as undirected — if A → B exists, A and B are in the same component regardless of direction.

#### Serialization and Persistence

```python
import json

# Serialize to JSON-compatible dict
data = graph.to_dict()

# Persist to disk
with open("graph_cache.json", "w") as f:
    json.dump(data, f, indent=2)

# Reconstruct from disk (no filesystem scanning needed)
with open("graph_cache.json") as f:
    data = json.load(f)
graph2 = DependencyGraph.from_dict(data)

assert graph2.node_count == graph.node_count
assert graph2.edge_count == graph.edge_count
```

The `to_dict()` / `from_dict()` roundtrip is lossless — all nodes, edges, evidence, and metadata survive serialization. `Path` objects are serialized as strings and reconstructed on deserialization. This enables graph caching: build once, persist to disk, reload in subsequent runs without rescanning the filesystem.

#### Working with the Sample Projects

The repository's 8 sample projects produce this graph:

```
Nodes (8):
  GalaxyWorks.Data          (sdk, net8.0, Library, 4 types, 2 sprocs)
  GalaxyWorks.WebPortal     (framework, v4.7.2, Library)
  GalaxyWorks.BatchProcessor (framework, v4.7.2, Exe)
  MyDotNetApp               (framework, net8.0, Exe)
  MyDotNetApp.Consumer      (sdk, net8.0, Exe)
  MyDotNetApp2.Exclude      (sdk, net8.0, Exe)
  MyGalaxyConsumerApp       (sdk, net8.0, Exe)
  MyGalaxyConsumerApp2      (sdk, net8.0, Exe)

project_reference edges (6):
  GalaxyWorks.WebPortal       → GalaxyWorks.Data
  GalaxyWorks.BatchProcessor  → GalaxyWorks.Data
  GalaxyWorks.BatchProcessor  → GalaxyWorks.WebPortal
  MyDotNetApp.Consumer        → MyDotNetApp
  MyGalaxyConsumerApp         → GalaxyWorks.Data
  MyGalaxyConsumerApp2        → GalaxyWorks.Data
```

Additional `namespace_usage` and `type_usage` edges are generated automatically based on `using` statements and type references found in the `.cs` files.

### Coupling Metrics

`compute_all_metrics()` in `scatter/analyzers/coupling_analyzer.py` computes per-project structural metrics from the graph:

```python
from scatter.analyzers.coupling_analyzer import compute_all_metrics, rank_by_coupling

metrics = compute_all_metrics(graph)

# Inspect a specific project
m = metrics["GalaxyWorks.Data"]
print(f"fan_in={m.fan_in}, fan_out={m.fan_out}, instability={m.instability:.2f}")
print(f"coupling_score={m.coupling_score:.1f}, shared_db_density={m.shared_db_density:.1%}")
print(f"type_exports={m.type_export_count}, consumers={m.consumer_count}")

# Top-3 most coupled projects
for name, m in rank_by_coupling(metrics, top_n=3):
    print(f"  {name}: coupling_score={m.coupling_score:.1f}")
```

| Metric | Formula | Interpretation |
|--------|---------|---------------|
| `fan_in` | `project_reference` edges pointing TO this project | How many projects depend on me (build-time) |
| `fan_out` | `project_reference` edges pointing FROM this project | How many projects I depend on (build-time) |
| `instability` | `fan_out / (fan_in + fan_out)`, 0.0 if both are 0 | 0.0 = maximally stable, 1.0 = maximally unstable |
| `coupling_score` | Weighted sum of all edge weights (both directions) | Overall interconnectedness intensity |
| `afferent_coupling` | Total incoming edges (all types) | Broader than fan_in — includes namespace/type edges |
| `efferent_coupling` | Total outgoing edges (all types) | Broader than fan_out |
| `shared_db_density` | Sprocs shared with other projects / total sprocs | 0.0 = no shared DB state, 1.0 = all sprocs shared |
| `type_export_count` | Count of type declarations | API surface area |
| `consumer_count` | Unique projects with any incoming edge | Total dependents across all edge types |

**Coupling score weights** are configurable — pass `coupling_weights` to `compute_all_metrics()` or set them in `.scatter.yaml`:

```yaml
graph:
  coupling_weights:
    project_reference: 1.0   # hard compile-time dependency
    sproc_shared: 0.8        # shared mutable database state
    namespace_usage: 0.5     # import-level awareness
    type_usage: 0.3          # code-level reference (could be a single enum)
```

For the sample projects: `GalaxyWorks.Data` has the highest coupling score (fan_in=4, instability=0.0 — maximally stable core library). `GalaxyWorks.BatchProcessor` has instability=1.0 (depends on 2 projects, nothing depends on it).

### Cycle Detection

`detect_cycles()` uses iterative Tarjan's SCC algorithm (O(N+E), no recursion limit) to find circular dependency groups:

```python
from scatter.analyzers.coupling_analyzer import detect_cycles

cycles = detect_cycles(graph)
print(f"Found {len(cycles)} circular dependency group(s)")

for cg in cycles:
    print(f"  {cg.size} projects: {cg.projects}")
    print(f"  Shortest cycle: {' → '.join(cg.shortest_cycle)}")
    print(f"  Internal edges: {cg.edge_count}")
```

By default, only `project_reference` edges are considered — these represent build-order violations. `namespace_usage` cycles (two projects that both import each other's namespace) are common and benign, so they're excluded by default. Pass `edge_types` to include other edge types:

```python
# Include namespace_usage cycles too
cycles = detect_cycles(graph, edge_types={"project_reference", "namespace_usage"})
```

Each `CycleGroup` contains the SCC's projects (sorted alphabetically), the number of internal edges, and a representative shortest cycle extracted via BFS with predecessor tracking. Cycle groups are sorted smallest-first — the smallest cycles are typically the easiest to break.

The sample projects have zero circular dependencies.

### Domain Boundary Detection

`find_clusters()` in `scatter/analyzers/domain_analyzer.py` identifies natural service boundaries — groups of tightly-connected projects that could be extracted as independent deployable units.

#### Two-Level Clustering

**Level 1: Connected Components** (always runs) — treats all edges as undirected and finds groups of mutually reachable projects. O(N+E), deterministic. Handles the common case of separate project groups.

**Level 2: Label Propagation** (conditional) — for connected components with >20 nodes, applies weighted label propagation to detect sub-communities within large monolithic components. Deterministic via sorted iteration and lowest-label tie-breaking.

```python
from scatter.analyzers.domain_analyzer import find_clusters
from scatter.analyzers.coupling_analyzer import compute_all_metrics, detect_cycles

metrics = compute_all_metrics(graph)
cycles = detect_cycles(graph)
clusters = find_clusters(graph, min_cluster_size=2, metrics=metrics, cycles=cycles)

for c in clusters:
    print(f"{c.name}: {len(c.projects)} projects, feasibility={c.extraction_feasibility}")
    print(f"  Cohesion: {c.cohesion:.3f}, Coupling to outside: {c.coupling_to_outside:.3f}")
    print(f"  Score: {c.feasibility_score:.3f}")
    for k, v in c.feasibility_details.items():
        print(f"    {k}: {v:.3f}")
```

#### Cluster Naming

Cluster names are derived from the longest common dot-prefix of member project names. For example, `["GalaxyWorks.Data", "GalaxyWorks.WebPortal"]` produces `"GalaxyWorks"`. Projects without a common prefix get a sequential fallback name (`"cluster_0"`, `"cluster_1"`, etc.).

#### Extraction Feasibility Scoring

Each cluster receives a feasibility score from 0.0 (deeply entangled) to 1.0 (trivially extractable), computed from four weighted penalty factors:

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| Cross-boundary coupling | 0.40 | Ratio of external edges to total edges |
| Shared DB objects | 0.25 | Sprocs referenced by projects both inside and outside the cluster |
| Circular dependencies | 0.20 | Whether any cycle spans the cluster boundary |
| API surface breadth | 0.15 | Fraction of types used by external consumers |

The score maps to a label: `easy` (>= 0.75), `moderate` (>= 0.50), `hard` (>= 0.25), `very_hard` (< 0.25).

The `feasibility_details` dict breaks down each penalty, making it actionable — you can see exactly which factor is blocking extraction.

---

## Roadmap

### Completed

- **Multiprocessing** — Parallel file discovery, content analysis, XML parsing, and project mapping with adaptive worker scaling
- **Hybrid Git Analysis** — LLM-enhanced diff analysis for more precise symbol extraction
- **Modularization** — Extracted into `scatter/` package with clean module boundaries
- **Impact Analysis** — AI-powered work request parsing, transitive blast radius tracing, risk assessment, coupling narrative, complexity estimation, and impact reporting
- **Configuration System** — YAML config files (`.scatter.yaml`, `~/.scatter/config.yaml`) with layered precedence, environment variable support, and AI task router for provider selection
- **Dependency Graph (Phase 1)** — Graph model (`ProjectNode`, `DependencyEdge`, `DependencyGraph`) with per-node edge indexes, single-pass O(P+F) builder, BFS traversal, connected components, JSON serialization roundtrip, and 46 tests
- **Coupling Metrics & Cycle Detection (Phase 2)** — `ProjectMetrics` (fan_in/out, instability index, coupling_score with configurable weights, shared_db_density), iterative Tarjan's SCC cycle detection with edge type filtering, shortest-cycle extraction via BFS predecessor map, `rank_by_coupling()`, and 25 tests
- **Graph Persistence & CLI (Phase 3)** — Smart git-based cache invalidation, `--graph` CLI mode, `--rebuild-graph` flag, graph config integration, and 21 tests
- **Database Dependency Mapping (Phase 4)** — DB scanner with comment stripping, sproc/DbSet/DbContext/SQL/connection string detection, cross-project dependency matrix, `sproc_shared` edges, `--include-db` flag, `DbConfig` with configurable prefixes, and 32 tests
- **Domain Boundary Detection (Phase 5)** — Two-level clustering (connected components + label propagation), `Cluster` dataclass with cohesion and feasibility scoring, four weighted penalty factors (cross-boundary coupling, shared DB, cycles, API surface), `BOUNDARY_ASSESSMENT` AI task type, and 15 tests
- **Graph Reporters & Health Dashboard (Phase 6)** — Console, JSON, Mermaid, CSV output; `HealthDashboard` with deterministic observation rules (stable_core, high_coupling, in_cycle, low_cohesion_cluster, db_hotspot); `--include-graph-topology` flag; cluster member display; and 21 tests
- **Report Quality Fixes (Initiative 6 Phase 1)** — JSON serialization fixes (native objects, null for absent fields), metadata blocks with version stamp, console polish, CSV cleanup, and 24 tests
- **Filter Pipeline Visibility (Initiative 6 Phase 2)** — `FilterStage` and `FilterPipeline` dataclasses, `find_consumers()` returns pipeline alongside results, arrow-chain summary in console/JSON/CSV output, diagnostic hints for zero-result stages, and 21 tests
- **Graph Builder Performance Optimization** — Inverted index for type_usage edges (101x speedup at 100 projects), comment stripping for precision, multi-owner type map for correctness. Benchmark tooling: synthetic codebase generator and per-stage profiling harness. See `docs/ADR_GRAPH_PERFORMANCE.md`
- **Test Quality Cleanup** — Deleted 1 zombie file, fixed 5 ghost tests (replaced no-op assertions with real scatter API calls), strengthened 3 dead-end assertions, removed 8 redundant tests. Suite reduced from 464 to 456 tests with no coverage loss
- **Blast Radius Tree View (Initiative 6 Phase 3)** — `propagation_parent` field on `EnrichedConsumer`, BFS parent tracking in transitive tracing, shared `tree.py` builder (`build_adjacency` + `CONFIDENCE_LABEL_RANK`), orphan re-parenting, box-drawing console tree, nested `propagation_tree` in JSON, `PropagationParent` CSV column, and 20 tests
- **Markdown Output Format (Initiative 6 Phase 4)** — `scatter/reports/markdown_reporter.py` with build/write separation (`build_*()` returns string, `write_*()` writes file), stdout fallback for markdown format, `_require_output_file()` helper, cell escaping, blast radius tree reuse via `render_tree()`, Mermaid dependency diagrams, and 39 tests
- **`--summarize-consumers` wiring** — Connected the existing AI summarization code to the analysis pipeline. `ConsumerFileSummaries` now populates in all 3 legacy modes (git, target, sproc). Shared `SUMMARIZATION_PROMPT_TEMPLATE` in `scatter/ai/base.py`, per-file progress logging, and 7 tests
- **`--graph-metrics` enrichment** — `GraphContext` dataclass in `scatter/analyzers/graph_enrichment.py` bridges the dependency graph into all analysis modes. Post-processing enrichment injects coupling score, fan-in/out, instability, and cycle membership into consumer results. Schema stability: reporters include graph columns when the flag is present, regardless of match. 17 tests
- **Incremental Graph Updates** — `scatter/store/graph_patcher.py` replaces all-or-nothing cache invalidation with surgical per-file patching. Git diff identifies changed files, content hash and declaration early cutoffs minimize re-extraction, and edge rebuild is scoped to affected projects. Safety valves (>50 projects, >30% files, structural changes) fall back to full rebuild. Shared regex patterns in `scatter/core/patterns.py`. v2 cache format with per-file/project facts and automatic v1→v2 migration. Benchmarked: 10-954x speedup for usage-only changes, 122-253x for csproj modifications. 49 tests + performance benchmark harness (`tools/benchmark_incremental.py`)
- **Pipeline Output Format** — `--output-format pipelines` prints sorted unique pipeline names to stdout, one per line, for release managers and deployment scripts. Works in legacy modes (git, target, sproc) and impact mode (sow). Early rejection in graph mode via `parser.error()`. Warns on stderr when used without `--pipeline-csv`. `scatter/reports/pipeline_reporter.py` with 14 tests
- **Transparent Graph Acceleration (Phases A-C)** — The graph is now the default fast path for all analysis modes, with zero configuration required. Phase A: auto-load graph from cache, `graph_enriched` metadata field, `--no-graph` escape hatch (15 tests). Phase B: O(1) reverse-index consumer lookup replaces filesystem stages 1-2 of `find_consumers()`, with target-not-in-graph fallback and `FilterStage.source` tracking (14 tests). Phase C: first-run graph build via idempotent `_ensure_graph_context()` at all 4 enrichment sites — results enriched on the very first run with no flags needed (7 tests). See [How the Graph Engine Works](#how-the-graph-engine-works)
- **Claude Code Skills** — Five skills in `tools/claude-skills/` that let engineers use scatter through natural language in Claude Code. Three auto-invoked skills (graph health, consumer lookup, SOW impact analysis) and two manual slash commands (stored procedure tracing, git branch analysis). Setup: `bash tools/setup-claude-skills.sh`. See [docs/CLAUDE_SKILLS.md](docs/CLAUDE_SKILLS.md)
- **Solution-Aware Graph (Initiative 9)** — Structural `.sln` parsing via `scatter/scanners/solution_scanner.py` (GUID whitelist, path resolution, BOM tolerance). `ProjectNode.solutions` field with backward-compatible cache serialization. Cross-solution coupling metrics (`SolutionMetrics` dataclass, single-pass O(E) algorithm, bridge project detection). Solution alignment scoring on domain clusters (post-hoc, no clustering bias — low alignment surfaces accidental cross-team coupling). Two new health observations: `high_cross_solution_coupling` (warning) and `solution_bridge_project` (info). Console shows Solutions count, Solution Coupling table, and Align column. JSON/CSV include solution data throughout. 64 tests across 5 phases
- **ConsumerResult Dataclass** — Replaced untyped `Dict[str, Union[str, Dict, List[str]]]` with typed `ConsumerResult` dataclass throughout the consumer analysis pipeline. 14 fields, ~58 access sites migrated across 8 production files. PascalCase JSON/CSV output preserved for backward compatibility via explicit mapping in reporters. `make_consumer_result` factory fixture for tests
- **Python Packaging with uv** — `uv sync` installs everything, `uv run scatter` runs the tool, `uv.lock` for reproducible installs. Hatchling build backend, `pip install .` fallback for non-uv users. pandas moved to optional `pipeline-tools` dependency group. Version consistency test ensures `pyproject.toml` matches `__version__.py`

### Next

- **Focused SOW index** — Two-tier solution-scoped index for `--sow` mode, `--solutions` filter, LLM-driven solution discovery with cross-solution edge counts as the discovery signal
- **CI pipeline** — GitHub Actions with pytest + ruff + mypy, Python 3.10/3.11/3.12 matrix, coverage reporting

### Planned (Tier 2: CI/CD Governance)

- **CI/CD exit codes** — `--fail-on cycles`, `--fail-on risk:high`, `--fail-on coupling:15.0` for architecture governance gates
- **PR blast radius comments** — Post impact analysis as PR comment (GitHub / Azure DevOps)

### Later (Tier 3: Strategic Features)

- **Baselines & diff reports** — Snapshot graph + metrics, compare over time, track modernization progress
- **Extraction planning** — `scatter extract` with API surface analysis, consumer inventory, shared data dependencies
- **HTML reports** — Self-contained interactive reports with D3.js dependency visualization

### Deferred (Tier 4)

- Unified report data model, additional AI providers, watch mode, AI response caching, token budget manager — see `tasks.txt` for details
