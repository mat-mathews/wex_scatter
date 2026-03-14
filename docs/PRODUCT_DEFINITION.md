# Scatter

## AI-Powered Monolith Analysis & Decomposition

**Internal Tool - WEX Inc**
**Version:** 2.0 Vision
**Last Updated:** February 2026
**Status:** Planning

---

## Table of Contents

1. [Summary](#1-summary)
2. [Problem Statement](#2-problem-statement)
3. [Product Vision](#3-product-vision)
4. [How Scatter Works - The Big Picture](#4-how-scatter-works--the-big-picture)
5. [What Scatter Does Today (v1.0)](#5-what-scatter-does-today-v10)
6. [Target Architecture (v2.0)](#6-target-architecture-v20)
7. [Feature Set](#7-feature-set)
8. [AI Engine](#8-ai-engine)
9. [Reporting & Developer Experience](#9-reporting--developer-experience)
10. [Technical Design](#10-technical-design)
11. [AI-Powered Legacy Analysis: Value, Savings & Future Vision](#11-ai-powered-legacy-analysis-value-savings--future-vision)
12. [Roadmap](#12-roadmap)
13. [Glossary](#13-glossary)

---

## 1. Summary

**Scatter** is an internal tool that automates dependency analysis across WEX's ~20-year-old .NET monolith. It identifies the blast radius of a code change, helps scope CSEs against actual dependency data, and supports microservice extraction planning.

### The Problem

The core codebase has grown to a point where no single person fully understands the dependency graph. This creates three practical problems:

- **Knowledge silos:** Impact analysis depends on tribal knowledge from a small number of senior engineers. That knowledge doesn't scale and leaves with attrition.
- **Imprecise scoping:** CSE and modernization scoping regularly misses hidden dependencies, leading to budget overruns, timeline slips, and mid-project surprises.
- **Modernization friction:** Teams can't confidently identify clean extraction boundaries because the coupling isn't visible.

### How Scatter Works

Scatter scans the codebase, discovers projects, traces dependency chains (via `ProjectReference`, `using` statements, and class/sproc usage), and identifies coupling. When a team receives a CSE or modernization initiative, Scatter analyzes the impacted components and produces a blast radius report. AI can optionally layer on risk assessments, complexity analysis, and decomposition recommendations.

Note: Scatter's coverage is bounded by what it can detect through static text analysis — reflection-based dependencies, DI container registrations, and dynamic type usage are not currently caught (see Section 5, "Where v1.0 Stops Short" and Section 7.2 for planned Roslyn-based semantic analysis).

### Current State vs. Target State

| Today (Manual) | With Scatter |
|----------------|-------------|
| Senior devs spend days manually tracing code | Automated dependency analysis in seconds to minutes (varies with codebase size) |
| Scoping based on memory and best guesses | Complexity scores based on actual code analysis |
| Breaking changes reach production undetected | Statically-detectable downstream consumers identified before merge |
| Weeks/months of ramp-up for new team members | AI-generated explanations of modules and dependency chains on demand |
| Extraction boundaries debated from intuition | Domain boundary detection based on measured coupling data |

---

## 2. Problem Statement

### What Makes the Monolith Hard

WEX's core .NET codebase has been under continuous development for ~20 years. The characteristics that make dependency analysis difficult:

| Characteristic | What It Means |
|---------------|---------------|
| **Hundreds of C# projects** | Deep, intertwined dependency chains where a change to one project can silently break dozens of others |
| **Shared stored procedures** | Multiple applications call the same database sprocs with no clear ownership — invisible coupling through the data layer |
| **Mixed frameworks** | Legacy .NET Framework 4.x projects alongside modern .NET 8 projects, each with different project file formats, conventions, and tooling |
| **Concentrated knowledge** | A small number of senior engineers hold the institutional understanding of how things connect — knowledge that doesn't scale and is lost on attrition |

### The Work That Triggers Analysis

Engineering teams encounter three scenarios where they need to understand impact across the monolith:

| Scenario | The Question |
|----------|-------------|
| **CSE arrives** | "This customer enhancement modifies a stored procedure used by 4 different applications — which teams need to be involved?" |
| **Modernization initiative** | "We want to extract the portal module into a target-state service — but we don't know everything that depends on it or shares its database." |
| **Feature branch in progress** | "I changed 3 files — what's the blast radius? Did I accidentally break a consumer I didn't know about?" |

In all three cases, the fundamental question is the same: **"What is the full scope of impact?"** Today, answering that question requires deep institutional knowledge, manual code tracing, and significant time.

### Consequences of Incomplete Analysis

| Failure Mode | Impact |
|-------------|----------------|
| Breaking changes reach production undetected | Revenue impact, incident response costs |
| CSE scoping misses hidden dependencies | Budget overruns, timeline slips |
| Modernization projects hit unexpected complexity | Delivered value falls short of investment |
| Only senior engineers can assess impact | Bottleneck on key people, fragile to attrition |
| Teams avoid modifying unfamiliar areas of the codebase | Technical debt compounds |

---

## 3. Product Vision

### Vision Statement

Scatter evolves from a developer CLI utility into a dependency analysis platform — accepting work requests as input and producing scoped impact assessments, and supporting modernization planning with actual dependency data and AI analysis.

### Core Principles

| Principle | What It Means |
|-----------|---------------|
| **AI-integrated analysis** | AI is part of the analysis pipeline, not an afterthought. Each analysis mode can use AI for natural language explanations, risk assessment, migration strategies, and complexity estimates. |
| **Work request in, impact analysis out** | Scatter is oriented around the actual workflow: a team receives a SOW/CSE or modernization initiative, feeds the details into Scatter, and gets back an impact report. |
| **Runs on developer machines** | No servers to maintain. Core analysis runs locally. The default AI provider (WEX AI Platform) runs within WEX infrastructure. Authorized external providers receive only targeted code excerpts, not entire repositories. |
| **Speed through parallelism** | Multiprocessing is a first-class design concern. A scan of ~5,000 files completes in under 30 seconds on a typical dev machine. |
| **Pluggable AI backend** | WEX AI Platform is the default provider and works without configuration. With authorization, additional providers (OpenAI, Anthropic, Google Gemini, Azure OpenAI, local models via Ollama) can be enabled based on cost, capability, or policy. |

### User Personas

| Persona | Primary Workflow |
|---------|-----------------|
| **Developer** | "I'm working on a feature branch - show me the blast radius before I open a PR." |
| **Tech Lead** | "We received a CSE to modify portal configuration - run it through Scatter so I can see the full impact and assign the right people." |
| **Architect** | "We're planning to extract the payments domain - give me the dependency map, coupling analysis, and AI risk assessment." |
| **Engineering Manager** | "I need to communicate scope and risk for this SOW to leadership - give me a report I can share." |
| **New Team Member** | "I don't know this codebase yet - Scatter, explain what this project does, what depends on it, and what I need to be careful about." |

---

## 4. How Scatter Works - The Big Picture

### The Input → Analysis → Output Flow

```
        ┌──────────────────────────────────────────────┐
        │               WORK REQUEST INPUT              │
        │                                               │
        │  "We received a CSE to modify the stored      │
        │   procedure dbo.sp_InsertPortalConfiguration   │
        │   and update the PortalDataService class"      │
        └───────────────────────┬──────────────────────┘
                                │
                                ▼
        ┌──────────────────────────────────────────────┐
        │            SCATTER ANALYSIS ENGINE             │
        │                                               │
        │  1. Scans the codebase via parallel file walk   │
        │  2. Builds a map of discovered projects and   │
        │     how they reference each other             │
        │  3. Traces the specific components mentioned   │
        │     in the work request through the map       │
        │  4. Identifies affected projects, database    │
        │     objects, and pipelines                    │
        │  5. AI analyzes the results and produces      │
        │     natural language insights                 │
        └───────────────────────┬──────────────────────┘
                                │
                                ▼
        ┌──────────────────────────────────────────────┐
        │              IMPACT ANALYSIS OUTPUT            │
        │                                               │
        │  • 4 consuming projects affected               │
        │  • 2 CI/CD pipelines need testing             │
        │  • 3 stored procedures share the same tables  │
        │  • AI Risk Assessment: MEDIUM - "The sproc    │
        │    is consumed by WebPortal and BatchProcessor │
        │    in addition to the primary consumers.      │
        │    WebPortal uses it in a caching layer that  │
        │    may mask changes. Recommend coordinated    │
        │    testing across all 4 consumer projects."   │
        └──────────────────────────────────────────────┘
```

---

## 5. What Scatter Does Today (v1.0)

Scatter v1.0 is a working Python CLI tool. A developer can run it locally, point it at the WEX monolith, and get dependency and blast radius results against the actual codebase.

### What You Can Do With Scatter Today

The examples below use the `GalaxyWorks.*` projects that are included with this repository. These are small but real .NET 8 projects — a data access library, a web portal, a batch processor, and a couple of consumer apps — designed to exercise Scatter's analysis modes with realistic dependency patterns without need to access the entire monolith during testing.

#### "I need to know who consumes this project"

A tech lead receives a CSE that requires changes to `GalaxyWorks.Data`. They run:

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

Scatter scans the entire codebase and reports back:

```
Target: GalaxyWorks.Data
    -> Consumed by: GalaxyWorks.WebPortal
    -> Consumed by: GalaxyWorks.BatchProcessor
    -> Consumed by: MyGalaryConsumerApp
    -> Consumed by: MyGalaryConsumerApp2

Total Consuming Relationships Found: 4
```

The tech lead now has a concrete list of affected teams and pipelines.

#### "I need to know who calls this stored procedure"

A CSE requires modifying `dbo.sp_InsertPortalConfiguration`. Before scoping the work, the team runs:

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```

Scatter searches all C# files for references to the sproc, identifies the containing class, and traces downstream consumers:

```
Target: GalaxyWorks.Data — PortalDataService (via Sproc)
    -> Consumed by: GalaxyWorks.WebPortal
    -> Consumed by: GalaxyWorks.BatchProcessor
    -> Consumed by: MyGalaryConsumerApp
    -> Consumed by: MyGalaryConsumerApp2

Target: GalaxyWorks.WebPortal — PortalCacheService (via Sproc)
    -> Consumed by: GalaxyWorks.BatchProcessor

Total Consuming Relationships Found: 5
```

This shows that the sproc change affects more than the obvious consumers — `PortalCacheService` in `WebPortal` also calls it, and `BatchProcessor` depends on that as well. This kind of transitive dependency through the data layer is easy to miss manually.

#### "I'm about to open a PR — what's the blast radius?"

A developer working on a feature branch checks impact before pushing:

```bash
scatter --branch-name feature/multi-tenant --repo-path .
```

Scatter compares the branch to main, extracts changed C# type declarations (classes, interfaces, structs, enums), and traces consumers of those types. The developer sees which projects reference the changed types before the PR is opened.

#### Additional capabilities already working:

- **CI/CD pipeline mapping** — maps discovered consumers to their Azure DevOps pipelines via CSV lookup, so you know not just *which* projects are affected but *which pipelines need testing*
- **Batch job verification** — validates whether consumer projects correspond to known batch jobs in the app-config repository
- **AI summarization** — Google Gemini integration can generate 2-3 sentence summaries of relevant C# files in consuming projects, helping developers quickly understand unfamiliar code
- **Multiple output formats** — Console for quick checks, CSV for sharing with teams and importing into Excel, JSON for programmatic consumption
- **Filter by class or method** — narrow results to specific types (`--class-name PortalDataService`) or methods (`--method-name StorePortalConfigurationAsync`)

### How It's Built

The analysis engine uses Python's multiprocessing to parallelize five distinct operations:

| Operation | What It Does | Why It's Parallel |
|-----------|-------------|-------------------|
| **File discovery** | Finds all `.cs` and `.csproj` files across the codebase | Thousands of directories to walk |
| **Project mapping** | Resolves which `.cs` file belongs to which `.csproj` project | Hundreds of files to map with directory-to-project caching |
| **XML parsing** | Parses `.csproj` files for `ProjectReference` tags | Handles both modern SDK-style and legacy Framework 4.x format with MSBuild XML namespaces |
| **Namespace analysis** | Scans files for `using` statement matches | Hundreds of files to scan for specific namespace patterns |
| **Class/sproc analysis** | Scans files for type usage and stored procedure references | Regex pattern matching across hundreds of files |

All operations use adaptive worker scaling (fewer workers for small workloads, more for large), progress reporting, and graceful fallback to sequential processing if multiprocessing encounters issues. On a typical developer workstation, a scan of ~5,000 files completes in under 30 seconds; larger codebases scale roughly linearly with file count.

### Where v1.0 Stops Short

v1.0 is functional but has known gaps. These are the limitations that v2.0 aims to address:

| Gap | What It Means in Practice |
|-----|--------------------------|
| **No SOW/CSE input workflow** | Developers must manually figure out which scatter command to run for a given work request — there's no "here's the SOW, tell me the impact" mode |
| **Single AI provider (Gemini only)** | Not connected to WEX AI Platform, cannot leverage Claude, GPT-4, Azure OpenAI, or local models — no flexibility based on WEX's AI strategy |
| **AI limited to summarization** | AI can describe code but can't assess risk, explain coupling, recommend migration strategies, or estimate complexity |
| **No dependency graph** | Every run re-scans the entire codebase from scratch — no persistent map of the monolith's structure |
| **No interactive reports** | Console, CSV, and JSON only — no visual dependency graphs, no HTML reports to share with managers |
| **No domain boundary analysis** | Can find consumers of a specific project but cannot identify natural service boundaries across the whole codebase |
| **No baseline or progress tracking** | Cannot save a snapshot and compare later — no way to measure whether modernization is reducing coupling |
| **Single monolithic file** | All ~2,200 lines in one `scatter.py` file — difficult to extend, test individual components, or add new analysis types |

---

## 6. Target Architecture (v2.0)

### Architectural Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                             CLI / Entry Point                              │
│                                                                            │
│  scatter impact --sow "Modify sp_InsertPortalConfiguration" --scope .      │
│  scatter analyze --target-project ./Billing/Billing.csproj --scope .       │
│  scatter extract --project ./Portal/Portal.csproj --scope .                │
│  scatter health --scope .                                                  │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────────────────┐
│                          ANALYSIS ENGINE                                    │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Scanners    │  │  Dependency  │  │   Domain     │  │   Impact     │  │
│  │              │  │   Resolver   │  │   Analyzer   │  │   Analyzer   │  │
│  │ • File       │  │              │  │              │  │              │  │
│  │ • Project    │  │ • Reference  │  │ • Coupling   │  │ • Blast      │  │
│  │ • Namespace  │  │ • Namespace  │  │ • Clustering │  │   Radius     │  │
│  │ • Type       │  │ • Sproc/DB   │  │ • Boundaries │  │ • What-If    │  │
│  │ • Sproc      │  │ • Transitive │  │ • Ownership  │  │ • Risk       │  │
│  │ • SQL/EF     │  │              │  │              │  │ • Migration  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │               Multiprocessing Infrastructure                         │   │
│  │     (ProcessPoolExecutor, chunking, adaptive scaling, caching)       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌────────▼──────────┐  ┌────────▼──────────┐  ┌────────▼──────────┐
│    AI ENGINE       │  │  REPORT ENGINE    │  │   DATA STORE      │
│                    │  │                   │  │                   │
│ ┌───────────────┐ │  │ • Console         │  │ • Dependency      │
│ │  Task Router  │ │  │ • JSON / CSV      │  │   Graph Cache     │
│ │  + Budget Mgr │ │  │ • HTML + Graphs   │  │ • Analysis Run    │
│ └──┬──┬──┬──┬───┘ │  │ • Mermaid         │  │   History         │
│    │  │  │  │     │  │ • Impact Report   │  │ • Baselines       │
│ ┌──▼──────────┐  │  │                   │  │ • AI Response     │
│ │ WEX AI      │  │  │                   │  │   Cache           │
│ │ Platform    │  │  │                   │  │                   │
│ │ (DEFAULT)   │  │  │                   │  │                   │
│ └─────────────┘  │  │                   │  │                   │
│ ┌──▼┐┌──▼┐┌──▼┐ │  │                   │  │                   │
│ │OAI││CLD││GEM│ │  │                   │  │                   │
│ └───┘└───┘└───┘ │  │                   │  │                   │
│ ┌────┐┌──────┐  │  │                   │  │                   │
│ │AzOA││Ollama│  │  │                   │  │                   │
│ └────┘└──────┘  │  │                   │  │                   │
│ (authorized     │  │                   │  │                   │
│  providers)     │  │                   │  │                   │
└──────────────────┘  └───────────────────┘  └───────────────────┘
```

### Key Architectural Decisions

**1. AI Engine as a core component**

In v1.0, AI (Gemini) was an optional summarization add-on. In v2.0, the AI Engine is available across all analysis modes (and can be disabled per-run with `--no-ai`). It defaults to WEX AI Platform for zero-configuration use and includes a task router, token budget manager, response cache, and pluggable provider system.

The AI Engine is called at multiple points in the analysis pipeline:
- **During analysis:** To enrich findings with natural language explanations
- **After analysis:** To assess risk, suggest migration strategies, and generate narratives
- **On demand:** To answer follow-up questions about the analysis results

**2. Work request input as a supported input type**

v2.0 introduces "impact mode" — the input is a description of the work to be done (CSE details, or a list of affected components), and the output is an impact analysis. The AI Engine parses natural language work descriptions into the specific projects, sprocs, and types that need to be traced.

**3. Dependency graph as persistent data structure**

Rather than re-scanning the entire codebase on each run, Scatter builds and caches a dependency graph. Subsequent analyses query the cached graph, avoiding the scan cost. The graph is invalidated when the codebase changes (detected via git status or file modification times).

---

## 7. Feature Set

### Category 1: Understand the Monolith

Features that build a picture of the codebase — its structure, dependencies, and complexity.

#### 7.1 Full Dependency Graph Generation

**What it does:** Scans the WEX codebase and builds a dependency map of project-to-project relationships — through `ProjectReference` entries, namespace usage, and database dependencies.

**Why it matters:** This is the foundation for all other analysis. Today, dependency knowledge lives in people's heads. A generated graph makes it explicit and queryable.

**What the AI adds:** After building the graph, the AI Engine produces a **codebase narrative** - a natural language summary of the major domains, their interconnections, and areas of concern. *"The codebase contains 247 projects organized roughly into 8 domain clusters. The largest cluster (Payments) has 43 projects and is the most interconnected, with 127 cross-cluster dependencies. The Portal and Configuration domains are tightly coupled through 23 shared stored procedures..."*

#### 7.2 Coupling & Cohesion Metrics

**What it does:** Computes numeric coupling scores for each project based on its dependency relationships with the rest of the codebase.

**Key metrics:**

| Metric | What It Measures | Plain English |
|--------|-----------------|---------------|
| **Fan-in** | How many projects depend on this one | "If this breaks, how many other things break?" |
| **Fan-out** | How many projects this one depends on | "How many things does this project need to work?" |
| **Coupling score** | Weighted measure of interconnectedness | "How hard would it be to extract this into its own service?" |
| **Instability index** | Ratio of outgoing to total dependencies | "Is this a stable foundation or a volatile leaf?" |
| **Shared DB density** | Database objects shared with other projects | "How entangled is this project through the database?" |

**What the AI adds:** For each high-coupling project, the AI generates a **coupling narrative**: *"GalaxyWorks.Data has the highest fan-in (23 consumers) because it contains the core data access layer and entity models used by nearly every domain. Extracting it would require establishing API contracts with 23 consumer projects. The primary coupling vectors are the PortalConfiguration model (used by 18 consumers) and the PortalDataService class (used by 12 consumers)."*

#### 7.3 Domain Boundary Detection

**What it does:** Automatically identifies clusters of projects that form natural domains - groups that are tightly connected internally but loosely connected externally. These represent the natural "cut lines" for decomposition.

**Why it matters:** When the question is "where do we split the monolith?", this provides an answer based on actual coupling data rather than intuition. Scatter shows where the boundaries already exist in the code.

**What the AI adds:** The AI evaluates each proposed boundary and generates a **boundary assessment**: *"The Portal cluster (7 projects) has 4 cross-boundary dependencies — 2 shared sprocs and 2 namespace references — all through GalaxyWorks.Data. Estimated extraction complexity: MEDIUM. The main risk is the shared stored procedure dbo.sp_InsertPortalConfiguration, which is also called by BatchProcessor."*

#### 7.4 Database Dependency Mapping

**What it does:** Maps which projects reference which database objects — stored procedures, tables (via Entity Framework), views, and direct SQL.

**Why it matters:** In WEX's monolith, the database is the hidden coupling layer. Two projects that have no direct code dependency might still be tightly coupled because they both read from and write to the same tables through shared stored procedures.

**What it finds:**
- Stored procedure consumers (enhanced from v1.0)
- Entity Framework model-to-table mappings
- Direct SQL references (table names, view names in string literals)
- Connection string analysis (which projects connect to which databases)
- **Cross-project DB object matrix:** A table showing "Project A and Project B both use these 15 stored procedures" — surfaces shared data dependencies that are otherwise hard to find

**What the AI adds:** *"The stored procedure dbo.sp_InsertPortalConfiguration is called by 3 projects across 2 different domain clusters. This creates implicit coupling between the Portal domain and the Batch Processing domain through the shared PortalConfigurations table. Any schema change to this table or sproc signature would require coordinated changes across both domains."*

#### 7.5 Codebase Health Dashboard

**What it does:** A single-view summary of the monolith's structural metrics.

**Intended audience:** Engineering managers and architects who need an overview without running individual analyses.

**What it shows:**
- Total project count, file count, rough LOC estimate
- Top 10 highest-risk projects (by coupling score)
- Circular dependency count and the worst offenders
- Orphan projects (nothing references them - deletion candidates?)
- Shared DB hotspots (database objects used by the most projects)
- Domain cluster summary with coupling scores
- Trend lines (if baseline history exists): "Coupling has decreased 12% since Q3"

**What the AI adds:** A **health summary narrative**: *"The core data layer (GalaxyWorks.Data) remains the highest-coupling project with 23 direct consumers. Since the last baseline, 2 consumers have been migrated to direct service calls, reducing fan-in by 8%. The Batch Processing cluster has 4 circular dependencies that should be resolved before further extraction work."*

---

### Category 2: Analyze Work Requests

Features that take incoming CSEs and modernization initiatives and produce impact analyses.

The core workflow: work request in, impact analysis out.

#### 7.6 SOW / CSE Impact Analysis

**What it does:** Takes a work request description — a CSE, or free-text description of planned changes — and produces an impact analysis listing affected projects, database dependencies, and CI/CD pipelines.

**How it works:**

```
INPUT (any of these):
  • "Modify stored procedure dbo.sp_InsertPortalConfiguration to add a new parameter"
  • "Update PortalDataService to support multi-tenant configuration"
  • "Extract GalaxyWorks.WebPortal into a standalone service"
  • --sow-file ./sow_2026_q1_portal_upgrade.txt  (full SOW document)

                    ↓ AI parses work request into analysis targets ↓

SCATTER IDENTIFIES:
  • Specific projects to trace (from project names, class names, or sproc names in the request)
  • Analysis mode(s) to run (target project, sproc tracing, or both)
  • Scope of impact search

                    ↓ Analysis engine runs ↓

OUTPUT:
  • List of affected projects with relationship type
  • Database dependency map for all affected components
  • CI/CD pipelines that need testing
  • AI-generated risk assessment and recommended approach
  • AI-generated complexity estimate
  • Formatted impact report (HTML, JSON, or console)
```

**AI's role in this mode.** When a developer inputs free text like "Modify the portal configuration sproc to support multi-tenancy", the AI:
1. **Parses the intent:** Identifies that `dbo.sp_InsertPortalConfiguration` (and related sprocs) are the targets
2. **Enriches the analysis:** After Scatter traces dependencies, the AI reads the actual code in affected projects and assesses whether each consumer would actually be impacted by the proposed change
3. **Generates the narrative:** Produces a natural language impact assessment that a manager can read and understand
4. **Flags hidden risks:** Identifies non-obvious concerns - *"Note: BatchProcessor calls this sproc inside a retry loop with no parameter validation - adding a required parameter will cause silent failures unless the retry logic is also updated."*

#### 7.7 Enhanced Blast Radius Analysis

**What it does:** Given a code change (feature branch, specific files, or a target project), identifies projects that reference the changed types — with depth, confidence levels, and optional AI risk assessment.

**Enhancements over v1.0:**
- **Transitive impact:** Consumers of consumers, up to N hops deep
- **Confidence scoring:** "Definitely affected" (uses the specific changed types) vs. "Possibly affected" (references the project but may not use the changed code)
- **AI risk narrative:** Natural language explanation of the blast radius and recommended testing strategy

**What the AI adds:** *"This branch modifies PortalDataService.StorePortalConfigurationAsync(). Blast radius: 4 direct consumers, 1 transitive consumer. HIGH CONFIDENCE impacts: PortalController (directly calls StorePortalConfigurationAsync), SyncJob (calls via PortalDataService constructor). MEDIUM CONFIDENCE: AdminApiController (references PortalDataService but only calls read methods - verify if behavior changed). Recommended testing: Run integration tests for WebPortal and BatchProcessor pipelines."*

#### 7.8 Extraction Planning ("What-If")

**What it does:** For modernization initiatives - "We want to extract Project X into a standalone microservice" - Scatter computes the complete extraction scope.

**What it produces:**

| Section | Content |
|---------|---------|
| **API Surface** | Types, methods, and interfaces from the target project that are referenced by external consumers — these become the service's API contract |
| **Consumer Inventory** | Projects that would need to switch from direct code references to service calls |
| **Shared Data Dependencies** | Database objects that the target project uses that are also used by other projects - these need ownership decisions |
| **Circular Dependencies** | Any dependency cycles involving the target that must be broken before extraction |
| **Migration Sequence** | AI-recommended order of operations for the extraction |
| **Risk Assessment** | AI-generated risk analysis with specific concerns and mitigations |
| **Complexity Estimate** | Data-driven complexity rating (Low / Medium / High / Critical) based on consumer count, API surface size, and data entanglement |

**What the AI adds:** The AI generates a complete **extraction strategy document**: *"Extracting GalaxyWorks.WebPortal requires breaking 4 integration points. Recommended approach: (1) Create an anti-corruption layer by introducing an IPortalService interface that the 1 consumer (BatchProcessor) programs against. (2) Move the PortalCacheService behind this interface. (3) Extract the WebPortal project with the interface implementation. (4) Update BatchProcessor to call the new service via HTTP. The primary risk is the shared stored procedure dbo.sp_InsertPortalConfiguration - recommend establishing a data ownership boundary where WebPortal owns this sproc and BatchProcessor calls it through the new service API rather than directly."*

---

### Category 3: Track Progress

Features that measure whether modernization efforts are reducing coupling over time.

#### 7.9 Baseline & Diff Analysis

**What it does:** Saves a snapshot of the dependency graph and all metrics at a point in time (a "baseline"). Future analyses can be compared against baselines to show progress.

**Why it matters:** Answers the quarterly question: "Is modernization actually reducing coupling?"

**What the AI adds:** Given a baseline comparison, the AI generates a **progress narrative**: *"Since the Q4 2025 baseline: Overall coupling decreased 8%. Two consumers of GalaxyWorks.Data were migrated to direct service calls (down from 25 to 23 consumers). One new circular dependency was introduced between BatchProcessor and WebPortal - this should be resolved before the next extraction phase. Net assessment: On track, with one new concern to address."*

#### 7.10 CI/CD Integration

**What it does:** Scatter can run in CI/CD pipelines to automatically analyze PRs and flag concerns.

**Use cases:**
- PR check that shows blast radius in a comment
- Gate that warns when a PR increases coupling across domain boundaries
- Automatic baseline updates when main branch changes
- Scheduled full-codebase health reports

---

## 8. AI Engine

### Design Philosophy

The AI layer sits on top of deterministic static analysis. Static analysis identifies the dependencies; AI explains what they mean, assesses risk, and suggests next steps.

| What Static Analysis Provides | What AI Adds |
|------------------------------|-------------|
| "Project A references Project B" | "Project A uses Project B's billing calculation engine - any change to the calculation logic will directly impact A's invoice generation" |
| "4 projects are affected" | "Of the 4 affected projects, 2 are high-risk (direct method calls in production code paths) and 2 are low-risk (only referenced in test utilities)" |
| "Coupling score: 0.73" | "This coupling score is driven primarily by shared database access patterns. The most impactful decoupling action would be to establish an API boundary around the 3 shared stored procedures" |
| "Consumer list: [...]" | "Recommended migration order: Start with MyGalaxyConsumerApp (fewest dependencies, only 2 call sites) before tackling BatchProcessor (complex retry logic, 12 call sites)" |

### Plugin Architecture

WEX's internal AI Platform is the **default provider** — it's pre-approved, runs within WEX infrastructure, and requires no additional authorization. All other providers (OpenAI, Anthropic, Google Gemini, Ollama, etc.) are available as plugins but **require explicit authorization** per WEX's AI governance policies before use.

```
┌──────────────────────────────────────────────────────────────────┐
│                         AI TASK ROUTER                            │
│                                                                   │
│  • Receives: analysis context + task type + priority              │
│  • Selects: provider based on task, config, and availability      │
│  • Manages: token budgets, chunking, retry, cost tracking         │
│  • Caches: responses to avoid redundant calls                     │
│  • Returns: structured result with confidence score               │
└──┬───────────┬──────────┬──────────┬──────────┬─────────────────┘
   │           │          │          │          │
┌──▼────────┐  │          │          │          │
│  WEX AI   │  │          │          │          │
│ Platform  │  │          │          │          │
│ (DEFAULT) │  │          │          │          │
│           │  │          │          │          │
│ Pre-      │  │          │          │          │
│ approved, │  │          │          │          │
│ no auth   │  │          │          │          │
│ required  │  │          │          │          │
└───────────┘  │          │          │          │
               │          │          │          │
  ┌────────────▼──────────▼──────────▼──────────▼──────────────┐
  │          REQUIRES AUTHORIZATION (per WEX AI policy)         │
  │                                                             │
  │  ┌────────┐ ┌─────────┐ ┌────────┐ ┌───────┐ ┌─────────┐ │
  │  │ OpenAI │ │Anthropic│ │ Google │ │ Azure │ │  Ollama │ │
  │  │        │ │         │ │ Gemini │ │OpenAI │ │ (Local) │ │
  │  │ GPT-4o │ │ Claude  │ │        │ │       │ │         │ │
  │  │ GPT-4.1│ │ Sonnet  │ │ Flash  │ │ GPT-4o│ │ Llama   │ │
  │  │ o3     │ │ Haiku   │ │ Pro    │ │ o3    │ │ Mistral │ │
  │  │        │ │ Opus    │ │        │ │       │ │ DeepSeek│ │
  │  └────────┘ └─────────┘ └────────┘ └───────┘ └─────────┘ │
  └────────────────────────────────────────────────────────────┘
```

Scatter works with WEX AI Platform by default — no configuration needed. Teams with authorization for additional providers can enable them via configuration for specific tasks (e.g., using a larger context window model for migration strategy analysis).

### Provider Interface

Each AI provider plugin implements:

| Method | Purpose |
|--------|---------|
| `analyze(prompt, context, task_type) → AnalysisResult` | Core analysis call - sends code context with a specific task prompt |
| `supports(task_type) → bool` | Declares which tasks this provider can handle |
| `estimate_tokens(context) → int` | Pre-call token estimation for cost awareness |
| `max_context_size → int` | Provider's context window limit |
| `stream(prompt, context) → Iterator` | Streaming responses for real-time output |

### AI Task Types

| Task Type | When It Fires | What It Produces |
|-----------|--------------|-----------------|
| **Work Request Parsing** | SOW/CSE input mode | Extracts project names, sproc names, class names, and change intent from natural language work descriptions |
| **Code Summarization** | Any analysis mode | Natural language description of what a project, class, or file does |
| **Coupling Narrative** | Dependency graph analysis | Explains *why* projects are coupled and what the primary coupling vectors are |
| **Risk Assessment** | Impact analysis, extraction planning | Risk rating (Low/Medium/High/Critical) with specific concerns and mitigations |
| **Impact Narrative** | Blast radius, CSE impact | Natural language explanation of the full impact of a change, suitable for sharing with managers |
| **Migration Strategy** | Extraction planning | Step-by-step recommended approach for extracting a component, including sequencing and risk mitigation |
| **Complexity Estimate** | CSE impact, extraction planning | Data-informed complexity rating with justification - feeds directly into CSE scoping |
| **Progress Narrative** | Baseline diff | Natural language summary of what changed since the last baseline and whether modernization is on track |
| **Code Explanation** | On-demand, any mode | Detailed explanation of legacy code — useful for onboarding and unfamiliar modules |
| **Contract Generation** | Extraction planning | Drafts interface definitions / API contracts for extraction boundaries |

### Configuration

```yaml
# .scatter.yaml (in repo root) or ~/.scatter/config.yaml (user-level)
# All examples below are illustrative — actual values TBD
ai:
  # WEX AI Platform is the default — works out of the box, no auth needed
  default_provider: wex_ai_platform

  # Task-specific overrides (requires authorization for non-default providers)
  task_overrides:
    summarization:
      provider: wex_ai_platform           # Fast, low-cost tasks stay on default
    migration_strategy:
      provider: anthropic                 # Requires authorization
      model: claude-opus-4-6              # Larger context for complex analysis
    code_explanation:
      provider: openai                    # Requires authorization
      model: gpt-4o

  # Provider configurations
  providers:
    wex_ai_platform:
      # Default — uses WEX internal AI infrastructure
      # No API key needed, authenticates via WEX SSO / internal auth
      endpoint: https://ai-platform.internal.wex.com/v1
      max_tokens: 8192

    # --- Providers below require explicit authorization ---
    anthropic:
      # API key from environment: SCATTER_ANTHROPIC_API_KEY
      max_tokens: 8192
    openai:
      # API key from environment: SCATTER_OPENAI_API_KEY
      max_tokens: 4096
    gemini:
      # API key from environment: SCATTER_GOOGLE_API_KEY
      max_tokens: 4096
    azure_openai:
      endpoint: https://wex-openai.openai.azure.com/
      deployment: gpt-4o
      # API key from environment: SCATTER_AZURE_OPENAI_API_KEY
    ollama:
      base_url: http://localhost:11434
      model: llama3.2
      # No API key needed — runs locally on developer machine

  # Budget controls
  budget:
    max_tokens_per_run: 100000       # Safety cap per analysis run
    warn_at_tokens: 50000            # Warn before proceeding
    cache_ttl_hours: 24              # Cache AI responses for 24 hours
    enable_cost_tracking: true       # Log estimated costs
```

```bash
# CLI overrides (WEX AI Platform is used when no --ai-provider is specified)
scatter impact --sow "..."                                                    # Uses WEX AI Platform
scatter impact --sow "..." --ai-provider anthropic --ai-model claude-opus-4-6 # Requires auth
scatter analyze --target-project ./Billing.csproj --no-ai                     # Disable AI entirely
scatter analyze --target-project ./Billing.csproj --ai-tasks risk             # Only risk assessment
```

### Token Budget Management

WEX codebases are large. A single project might have hundreds of files. The AI Engine handles this through:

- **Smart context selection:** Rather than sending entire projects to the AI, Scatter identifies the most relevant files and excerpts based on the analysis being performed. A blast radius analysis sends the changed code + the specific consumer call sites, not the entire consumer project.
- **Automatic chunking:** When context exceeds a model's window, Scatter splits the work into multiple calls and synthesizes results.
- **Cost tracking:** Each AI call logs estimated token usage and cost. Developers see `[AI] Estimated cost for this analysis: $0.12 (4,200 input tokens, 800 output tokens)` before proceeding.
- **Response caching:** Identical analysis requests (same code, same task) return cached responses. Cache invalidates when code changes.
- **Provider routing by task:** All tasks default to WEX AI Platform. With authorization, simple tasks (summarization) can be routed to cheaper/faster models (Gemini Flash, Haiku) while complex tasks (migration strategy) can use larger context models (Claude Opus, GPT-4).

---

## 9. Reporting & Developer Experience

### Output Formats

| Format | Audience | Best For |
|--------|----------|----------|
| **Console** | Developer at terminal | Quick checks, iterative exploration |
| **JSON** | Automation, CI/CD | Pipeline integration, programmatic consumption |
| **CSV** | Anyone with Excel | Filtering, pivot tables, sharing with non-developers |
| **HTML** | Everyone | Comprehensive interactive reports, sharing with management |
| **Mermaid** | Documentation | Embedding dependency diagrams in wikis, Confluence, READMEs |

### HTML Interactive Report

A **self-contained single HTML file** that can be opened in any browser, emailed, or dropped into a SharePoint/Confluence page. No server required.

**Report sections:**
- **Executive Summary** - AI-generated narrative of the analysis findings (1 paragraph for managers)
- **Dependency Graph** - interactive, zoomable, filterable visualization (click a project to see its connections)
- **Impact Table** - sortable, searchable table of all affected projects with metrics
- **Risk Assessment** - AI-generated risk analysis with color-coded severity
- **Database Dependency Map** - which projects share which DB objects
- **Pipeline Impact** - which CI/CD pipelines need testing
- **Recommended Actions** - AI-generated next steps
- **Detailed Findings** - collapsible sections with per-project detail (expandable for developers who want the full picture)

### CLI Experience

```bash
# ─── SOW / CSE Impact Analysis ───
# Feed in a work request description, get back full impact analysis
scatter impact --sow "Modify dbo.sp_InsertPortalConfiguration to add TenantId parameter" --scope /path/to/monolith
scatter impact --sow-file ./cse_2026_0142.txt --scope . --output-format html --output-file cse_impact.html

# ─── Existing Analysis Modes (preserved from v1) ───
scatter blast-radius --branch-name feature/multi-tenant --repo-path .
scatter analyze --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --scope .
scatter sproc --name "dbo.sp_InsertPortalConfiguration" --scope .

# ─── Extraction Planning ───
scatter extract --project ./GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj --scope .
scatter extract --project ./GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj --scope . --output-format html

# ─── Health & Monitoring ───
scatter health --scope .
scatter health --scope . --output-format html --output-file health_q1_2026.html

# ─── Baselines & Progress Tracking ───
scatter baseline save --scope . --name "q1-2026-start"
scatter baseline diff --name "q1-2026-start" --scope .
scatter baseline list

# ─── Dependency Visualization ───
scatter graph --scope . --output-format mermaid --output-file deps.mmd
scatter graph --scope . --cluster --output-format html --output-file clusters.html

# ─── AI Controls ───
scatter impact --sow "..." --scope .                                 # Uses WEX AI Platform (default)
scatter impact --sow "..." --scope . --ai-provider anthropic         # Use Claude (requires auth)
scatter impact --sow "..." --scope . --ai-provider ollama            # Use local model (requires auth)
scatter impact --sow "..." --scope . --no-ai                         # Static analysis only
scatter impact --sow "..." --scope . --ai-tasks risk,migration       # Specific AI tasks only
```

### Developer Workflow Integration

| Integration | What It Does |
|-------------|-------------|
| **Pre-PR check** | Developer runs `scatter blast-radius --branch-name $(git branch --show-current)` before opening a PR |
| **CI/CD gate** | Automated `scatter impact` runs on PR, posts blast radius as a PR comment |
| **IDE paths** | All output includes clickable file paths for VS Code / Rider / Visual Studio |
| **Quiet mode** | `--quiet` suppresses logs, outputs only structured data - for scripting and piping |
| **Watch mode** | `scatter analyze --watch` re-runs on file changes for interactive exploration |

---

## 10. Technical Design

### Module Structure

```
scatter/
├── __main__.py                  # CLI entry point, argument parsing
├── config.py                    # Configuration management (.scatter.yaml, env vars, CLI flags)
│
├── core/
│   ├── graph.py                 # Dependency graph data structure
│   ├── models.py                # Shared data models (Project, Dependency, Metric, etc.)
│   └── parallel.py              # Multiprocessing infrastructure (preserved from v1)
│
├── scanners/                    # Code scanning - pure analysis, no AI
│   ├── base.py                  # Scanner protocol
│   ├── file_scanner.py          # File discovery (*.cs, *.csproj)
│   ├── project_scanner.py       # .csproj parsing (SDK-style + Framework 4.x MSBuild)
│   ├── namespace_scanner.py     # using statement analysis
│   ├── type_scanner.py          # Class/struct/interface/enum extraction
│   ├── sproc_scanner.py         # Stored procedure reference detection
│   └── db_scanner.py            # Direct SQL / EF table / connection string references
│
├── analyzers/                   # Higher-level analysis - builds on scanners, calls AI
│   ├── base.py                  # Analyzer protocol
│   ├── consumer_analyzer.py     # Consumer detection pipeline (core of v1.0)
│   ├── coupling_analyzer.py     # Coupling/cohesion metrics
│   ├── domain_analyzer.py       # Domain boundary detection / clustering
│   ├── impact_analyzer.py       # SOW/CSE impact analysis + extraction "what-if"
│   └── health_analyzer.py       # Health metrics and dashboard data
│
├── ai/                          # AI Engine - pluggable provider system
│   ├── base.py                  # AIProvider protocol, AnalysisResult model
│   ├── router.py                # Task routing, provider selection, fallback logic
│   ├── budget.py                # Token budget management, context chunking
│   ├── cache.py                 # AI response caching (file-based, TTL-aware)
│   ├── providers/
│   │   ├── wex_platform_provider.py  # WEX AI Platform (DEFAULT — no auth required)
│   │   ├── openai_provider.py        # OpenAI (requires authorization)
│   │   ├── anthropic_provider.py     # Anthropic (requires authorization)
│   │   ├── gemini_provider.py        # Google Gemini (requires authorization)
│   │   ├── azure_provider.py         # Azure OpenAI (requires authorization)
│   │   └── ollama_provider.py        # Local models via Ollama (requires authorization)
│   └── tasks/                   # Task-specific prompt engineering
│       ├── parse_work_request.py  # SOW/CSE text → analysis targets
│       ├── summarize.py           # Code/project summarization
│       ├── risk_assess.py         # Risk assessment with severity rating
│       ├── coupling_narrative.py  # Explain coupling relationships
│       ├── impact_narrative.py    # Generate impact report narrative
│       ├── migration_strategy.py  # Extraction approach recommendation
│       ├── complexity_estimate.py # Data-informed complexity rating
│       ├── progress_narrative.py  # Baseline diff summary
│       ├── code_explain.py        # Deep code explanation
│       └── contract_gen.py        # API contract / interface drafting
│
├── reports/                     # Output formatting
│   ├── base.py                  # Reporter protocol
│   ├── console_reporter.py      # Terminal output (preserved from v1)
│   ├── json_reporter.py         # JSON output (preserved from v1)
│   ├── csv_reporter.py          # CSV output (preserved from v1)
│   ├── html_reporter.py         # Interactive HTML report (new)
│   └── mermaid_reporter.py      # Mermaid diagram output (new)
│
├── store/                       # Persistence
│   ├── graph_cache.py           # Dependency graph caching
│   ├── baseline.py              # Baseline save/load/compare
│   └── run_history.py           # Analysis run history
│
└── compat/
    └── v1_bridge.py             # Backward compatibility with scatter.py v1 CLI
```

### Multiprocessing Architecture (Preserved & Enhanced)

The multiprocessing patterns from v1 are preserved and extended:

**Pattern:** `ProcessPoolExecutor` with chunked batch processing, adaptive worker scaling, and graceful sequential fallback.

```
Workload → Chunk → Distribute → Collect → Merge
             │
             ├── < 50 items: sequential (no process overhead)
             ├── < 200 items: 4 workers
             ├── < 1000 items: 8 workers
             └── 1000+ items: max workers (CPU count + 4)
```

**v2.0 enhancements:**
- **Pipeline parallelism:** Downstream analysis stages start consuming results while upstream scanning is still running
- **Progress bars:** Visual progress indication for long-running codebase scans (using `tqdm`)
- **AI call parallelism:** Multiple AI requests (e.g., summarize 10 projects) execute concurrently with configurable concurrency limits

### Data Model

```
Project
├── path: Path                        # /path/to/Project.csproj
├── name: str                         # "GalaxyWorks.WebPortal"
├── namespace: str                    # "GalaxyWorks.WebPortal"
├── framework: str                    # "v4.7.2" or "net8.0"
├── project_style: SDK | Framework    # Determines XML parsing strategy
├── references: List[ProjectRef]      # Direct ProjectReference entries
├── types: List[TypeDeclaration]      # Classes, interfaces, enums, structs
├── sproc_calls: List[SprocRef]       # Stored procedure references found in code
├── files: List[Path]                 # All .cs files belonging to this project
└── metrics: ProjectMetrics           # Computed: fan_in, fan_out, coupling_score, etc.

DependencyGraph
├── nodes: Dict[str, Project]
├── edges: List[DependencyEdge]       # (source, target, type, weight)
│
├── get_consumers(project, depth=1) → List[Project]
├── get_dependencies(project) → List[Project]
├── get_transitive_closure(project, max_depth) → List[(Project, depth)]
├── detect_cycles() → List[List[Project]]
├── find_clusters() → List[Cluster]   # Domain boundary candidates
├── compute_metrics() → Dict[str, ProjectMetrics]
├── diff(baseline: DependencyGraph) → GraphDiff
│
├── save(path) / load(path)           # Persistence
└── to_mermaid() / to_json()          # Export
```

---

## 11. AI-Powered Legacy Analysis: Value, Savings & Future Vision

### Context

WEX operates a ~20-year-old .NET monolith with hundreds of interconnected projects, shared stored procedures, and dependency chains that no single engineer fully understands. This is common in the industry — **92% of financial services firms** still rely on legacy technology ([Financial Conduct Authority, 2024](https://www.fintech-consultant.com/post/hidden-costs-of-legacy-banking-infrastructure-on-financial-institutions)), and the payments industry faces legacy platform costs projected to reach **$57 billion by 2028** ([Fintech Consultant, 2024](https://www.fintech-consultant.com/post/hidden-costs-of-legacy-banking-infrastructure-on-financial-institutions)).

Scatter combines deterministic code analysis with AI-powered insights. This section documents the industry data behind the approach, quantifies expected savings, and outlines future AI capabilities.

---

### 11.1 The Cost of the Status Quo

#### Developer Time Lost to Legacy Comprehension

Industry data on developer time allocation:

| Metric | Data Point | Source |
|--------|-----------|--------|
| **Time reading vs. writing code** | Developers spend time reading code at a ratio of **10:1 over writing** | Robert C. Martin, *Clean Code* (2008) |
| **Time spent on technical debt** | **42% of every developer's working week** (17.3 hours) is spent dealing with technical debt and bad code | [Stripe Developer Coefficient Report](https://stripe.com/files/reports/the-developer-coefficient.pdf) |
| **Time writing new code** | Developers spend **less than one-third of their time (32%)** writing new code or improving existing code | [The New Stack](https://thenewstack.io/how-much-time-do-developers-spend-actually-writing-code/) |
| **Legacy system patching** | IT teams spend **5-25 hours per week** patching legacy systems, equivalent to **13-65% productivity loss** per engineer | [SnapLogic 2024 Survey, via Pragmatic Coders](https://www.pragmaticcoders.com/resources/legacy-code-stats) |

**Applied to WEX:** If 10 developers spend an average of 5 hours/week on manual dependency tracing and impact analysis, that's **2,600 hours/year** — roughly 1.25 FTEs spent answering "what will this change break?"

#### The Price of Getting It Wrong

| Impact Area | Industry Cost | Source |
|------------|--------------|--------|
| **Production downtime** | Average **$300,000+/hour** across enterprises; **$5M+/hour** in banking/finance | [ITIC 2024 Hourly Cost of Downtime](https://itic-corp.com/itic-2024-hourly-cost-of-downtime-part-2/) |
| **Per-minute downtime** | **$14,056/minute** average, **$23,750/minute** for large enterprises | [BigPanda 2024](https://www.bigpanda.io/blog/it-outage-costs-2024/) |
| **IT outage root cause** | **23% of impactful outages** caused by complexity-driven change management failures | [Uptime Institute 2024 Annual Outage Analysis](https://uptimeinstitute.com/resources/research-and-reports/annual-outage-analysis-2024) |
| **Legacy modernization budget overruns** | **52.7% of projects** run **189% over original cost estimates** | [Standish Group CHAOS Report](https://www.opendoorerp.com/the-standish-group-report-83-9-of-it-projects-partially-or-completely-fail) |
| **Project failure rate** | **83.9% of IT projects** partially or completely fail | [Standish Group CHAOS Report](https://www.opendoorerp.com/the-standish-group-report-83-9-of-it-projects-partially-or-completely-fail) |

**Applied to WEX:** A single undetected breaking change to a core data access library — like the one modeled by the example project `GalaxyWorks.Data`, which has 4+ direct consumers and touches shared stored procedures — can cascade into payment processing failures. In financial services, that also carries regulatory risk.

#### Legacy Maintenance Budget Drain

| Metric | Data Point | Source |
|--------|-----------|--------|
| **IT budget allocation** | **60-80% of IT budgets** go to maintaining legacy systems rather than innovation | [Gartner, via Profound Logic](https://www.profoundlogic.com/true-cost-maintaining-legacy-applications-industry-analysis/) |
| **Global maintenance spend** | **$1.14 trillion** spent annually on legacy system maintenance globally | [Mechanical Orchard](https://www.mechanical-orchard.com/insights/1-14-trillion-to-keep-the-lights-on-legacys-drag-on-productivity) |
| **Technical debt as share of estate** | **40% of the technology estate** in large enterprises is technical debt | [McKinsey, via Synchrony Systems](https://sync-sys.com/what-is-the-true-cost-of-technical-debt-in-legacy-applications/) |
| **GDP impact** | Developer misallocation to technical debt has a **$3 trillion impact on global GDP** over 10 years | [Stripe Developer Coefficient Report](https://stripe.com/files/reports/the-developer-coefficient.pdf) |

---

### 11.2 Expected Savings

#### Developer Time Savings

| Activity | Without Scatter (estimated) | With Scatter (measured/estimated) | Estimated Reduction |
|----------|----------------|-------------|------------|
| **"Who consumes this project?"** | 2-4 hours of manual "Find All References" across the monolith, likely incomplete | **< 30 seconds** for ~5,000 files (parallel scan of .csproj references, namespace usage, class references). Covers statically-detectable references only. | **~98%** |
| **"What's the blast radius of my branch?"** | Half a day asking senior engineers, searching Confluence, reading code | **< 1 minute** for git-diff extraction + consumer tracing. AI risk narrative adds ~30-60 seconds per AI call. | **~95%** |
| **"Which pipelines need testing?"** | Cross-referencing code consumers against CI/CD pipeline spreadsheets | **Automatic** — pipeline-to-consumer mapping built into output (requires pipeline CSV to be current) | **~100%** |
| **CSE impact scoping** | 1-2 weeks of manual analysis, subject to developer bias, rapidly outdated | **Minutes** for deterministic analysis. AI risk assessment adds additional time per consumer project. Still requires human review of results. | **~80-90%** |
| **New team member onboarding** | Weeks to months of tribal knowledge transfer | AI-generated explanations of modules and dependency chains on demand. Reduces but does not eliminate need for senior engineer context. | **~50-70%** |

**Annual savings estimate (with assumptions):**
- Assumes 15 developers, each spending an average of 3 hours/week on dependency-related analysis (tracing, scoping, impact assessment)
- Assumes Scatter reduces that by ~60-80% on average (not 100% — human review and non-detectable dependencies still require manual work)
- **1,400-1,870 hours/year recovered** → equivalent to **$168,000-$374,000/year** at $120-$200/hr fully loaded cost
- Incident avoidance is harder to quantify but significant: industry data shows **$300K+/hour** downtime cost in financial services (ITIC 2024). Even one prevented incident per year would exceed the annual savings estimate above.
- These numbers are estimates, not guarantees. Actual savings depend on codebase size, team workflow, and how frequently dependency analysis is needed.

#### Cost to Operate

| Cost Component | Details | Estimated Cost |
|---------------|---------|---------------|
| **Scatter runtime** | Python CLI, runs on developer machines — no servers, no infrastructure | **$0** |
| **WEX AI Platform** (default) | Uses existing WEX internal AI infrastructure — no additional licensing | **$0 incremental** |
| **AI API costs** (if using external providers) | Typical analysis run: ~5,000-10,000 input tokens + ~1,000-2,000 output tokens | **$0.01-$0.15 per analysis run** |
| **Developer time to maintain Scatter** | Open-source Python, minimal dependencies | **< 0.1 FTE** |

At $0 infrastructure cost, the payback period depends on actual adoption and usage patterns. Under the assumptions above ($168K-$374K/year in recovered developer time), the development investment is likely recovered within the first 1-2 quarters.

---

### 11.3 Scatter vs. Generic AI Tools

A reasonable question: "Can't we just ask Copilot or ChatGPT about our dependencies?"

In short, no. The research on AI coding tools in large codebases is worth understanding:

| Finding | Data Point | Source |
|---------|-----------|--------|
| **AI tools slow down experienced devs on real codebases** | AI coding tools made experienced developers **19% slower** on real-world tasks in large, familiar codebases — while developers *perceived* a 20% speedup (a **43-point perception gap**) | [METR 2025 Study](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/) |
| **Success rate drops with complexity** | AI tool success rates **drop from 70% on simple tasks to 23%** on enterprise-complexity scenarios requiring multi-file edits | [Augment Code 2025](https://www.augmentcode.com/tools/ai-coding-assistants-for-large-codebases-a-complete-guide) |
| **Context window limitations** | Even 100K+ token windows can't hold a legacy codebase; the model has no visibility into code outside the current context | [AlgoMaster](https://blog.algomaster.io/p/using-ai-effectively-in-large-codebases) |
| **AI adoption doesn't automatically improve metrics** | 2024 DORA Report: deploying AI showed a **1.5% decrease in throughput** and **7.2% decrease in stability** | [DORA / Google, via RedMonk](https://redmonk.com/rstephens/2024/11/26/dora2024/) |
| **Code quality concerns** | **62% of AI-generated code** contains design flaws or known security vulnerabilities | [Augment Code 2025](https://www.augmentcode.com/tools/ai-coding-assistants-for-large-codebases-a-complete-guide) |

**Comparison:**

| Capability | Generic AI (Copilot / ChatGPT) | Scatter |
|-----------|-------------------------------|---------|
| Cross-codebase dependency scan | Limited by context window; requires manual feeding | Deterministic scan of all .csproj, `using` statements, and class references |
| Blast radius detection | Hallucination-prone; no guarantee of completeness | Parallel static analysis of 5,000+ files in <30 seconds; covers statically-detectable references |
| Stored procedure tracing | Must be asked per-procedure, one at a time | Automated end-to-end tracing from sproc → class → project → consumer → pipeline |
| CI/CD pipeline mapping | Not possible without manual context | Maps consumers to pipelines and batch jobs automatically |
| Reproducibility | Different answer every prompt | Deterministic, auditable output (JSON/CSV/HTML) |
| AI summarization | Raw LLM output with no structural foundation | AI summarization layered **on top of** verified, deterministic dependency data |

The design principle: deterministic analysis first, AI enrichment second. The AI does not guess at dependency relationships — it explains and assesses relationships that the analysis engine has already identified.

---

### 11.4 Future AI-Powered Features

Beyond the v2.0 roadmap, the architecture supports additional AI-powered capabilities:

#### Natural Language Codebase Querying

**What:** Developers ask questions in plain English and get answers grounded in the actual dependency graph.

```
> scatter ask "What happens if I add a required parameter to sp_InsertPortalConfiguration?"

Based on dependency analysis:
- 3 projects directly call this stored procedure
- GalaxyWorks.Data.PortalDataService — calls it in StorePortalConfigurationAsync()
- GalaxyWorks.WebPortal.PortalCacheService — calls it in a background refresh loop
- GalaxyWorks.BatchProcessor.SyncJob — calls it inside a retry block with no parameter validation

Risk: HIGH — BatchProcessor's retry loop will silently fail on the new required parameter.
Recommended: Update all 3 call sites before deploying the sproc change.
Affected pipelines: WebPortal-CI, BatchProcessor-Nightly
```

**How it differs from generic AI:** Responses are grounded in a deterministic scan of the actual codebase. The AI explains what the analysis engine found — it doesn't invent relationships.

#### AI-Driven Migration Sequencing

**What:** Given a modernization target (e.g., "extract the Portal domain into a microservice"), Scatter's AI generates a step-by-step migration plan with sequencing, risk mitigation, and effort estimates — informed by the actual dependency graph.

**Value:** Reduces modernization planning from weeks of manual analysis to a data-driven exercise. The AI identifies extraction order, flags circular dependencies that must be resolved first, and drafts API contracts for new service boundaries.

#### Automated Code Change Suggestions

**What:** After identifying blast radius, Scatter's AI generates draft code changes for affected consumers — updating method signatures, adding new parameters, adjusting stored procedure calls.

**Value:** Extends Scatter from identifying affected code to suggesting fixes. A developer changing a sproc signature gets not just a list of affected files, but AI-generated pull request drafts for each consumer project.

#### Continuous Codebase Health Monitoring

**What:** Scatter runs on a schedule (nightly or on merge to main), tracks coupling metrics over time, and alerts teams when coupling increases or new circular dependencies are introduced.

**Value:** Catches coupling regressions while modernization is in progress. Example weekly output: *"Coupling increased 3% this week due to 2 new cross-domain dependencies introduced in PR #1247 and PR #1253. Recommend reviewing before next release."*

#### Intelligent CSE Effort Estimation

**What:** When a CSE arrives, Scatter analyzes the blast radius, evaluates code complexity, considers historical data from similar changes, and produces an AI-powered effort estimate with confidence intervals.

**Value:** Provides a data-informed starting point for CSE scoping. Example output: *"This change affects 4 consumer projects with a combined 12 call sites. Based on complexity analysis: estimated 3-5 developer-days. Primary risk: BatchProcessor's retry logic requires careful testing (adds ~1 day)."*

#### Multi-Repository Dependency Intelligence

**What:** Extends Scatter's analysis across repository boundaries — mapping dependencies between separate Git repositories that share NuGet packages, database schemas, or API contracts.

**Value:** As WEX decomposes the monolith into separate repositories, the dependency graph needs to extend across repo boundaries. Scatter would track cross-repo dependencies through shared packages and database objects.

#### AI-Powered Code Archaeology

**What:** For legacy code with no documentation, Scatter's AI reads the code, traces its history through git blame, and produces comprehensive documentation: what the code does, why it exists, who has modified it, and what depends on it.

**Value:** Addresses the hardest knowledge gap — code that nobody currently on the team understands. New team members can request an AI-generated summary of any module, including dependency context and known risks.

---

### 11.5 Summary of Expected Impact

| Dimension | Expected Impact | Assumptions / Caveats |
|-----------|--------|--------|
| **Developer productivity** | **1,400-1,870 hours/year** recovered — estimated **$168K-$374K/year** | 15 devs, 3 hrs/week on dependency analysis, 60-80% reduction |
| **Incident prevention** | Each prevented incident avoids **$300K+/hour** in financial services downtime (ITIC 2024) | Scatter catches statically-detectable dependency issues; reflection/DI-based coupling requires additional tooling |
| **Modernization scoping** | Data-driven scoping addresses dependency blind spots — a contributing factor to the **83.9% project failure/overrun rate** (Standish Group) | Scatter reduces but does not eliminate scoping risk; human judgment still required |
| **Knowledge distribution** | AI-generated explanations reduce reliance on tribal knowledge; onboarding time reduced | Effectiveness depends on AI provider quality and codebase complexity |
| **Operating cost** | **Near-zero** — runs on developer machines, defaults to WEX AI Platform | External AI providers incur per-call costs ($0.01-$0.15/run) |
| **vs. generic AI tools** | Deterministic, reproducible results vs. generic AI tools that are **19% slower on real codebases** (METR 2025) and **succeed 23% of the time** on enterprise-complexity tasks (Augment Code 2025) | Scatter and generic AI solve different problems; this comparison applies specifically to cross-codebase dependency analysis |

Scatter provides the dependency data engineers need to make informed decisions in minutes rather than days. The AI layer adds context and explanation but does not replace engineering judgment.

---

## 12. Roadmap

### Phase Summary

| Phase | Focus | Scatter Evolves From → To | Status |
|-------|-------|--------------------------|--------|
| **Phase 1** | Modularize the engine, set up the AI backend | Single script → modular package | ✅ Complete |
| **Phase 2** | Add "Impact Mode" for CSE scoping | CLI utility → work-request analysis tool | ✅ Complete |
| **Phase 3** | Full dependency graph, domain discovery, metrics | Point analysis → whole-codebase analysis | ✅ Complete |
| **Phase 4a-d** | Report quality, filter visibility, tree view, markdown | Raw output → polished, shareable reports | ✅ Complete |
| **Phase 4.5** | **Credibility & adoption** — fix broken features, graph integration, Claude skills, pipeline shortcut | Developer tool → adopted team tool | **Next** |
| **Phase 5** | CI/CD integration, automated gates | Manual runs → continuous analysis | After adoption |
| **Phase 4e-f** | Unified report model, diff reports, baselines, HTML | Snapshots → monitoring over time | After CI/CD |

**Sequencing rationale (updated 2026-03-13):** Phase 5 (CI/CD) is promoted ahead of Phase 4e-f because CI/CD gates drive stickier adoption than internal refactoring or diff reports. A new Phase 4.5 captures credibility fixes and adoption enablers (broken `--summarize-consumers` wiring, graph integration into analysis modes, Claude Code skills, deployment checklist shortcut) that should ship before any infrastructure features. The unified report model (Phase 4e) is deferred — it's architecturally correct but no user sees it, and it can wait until schema inconsistency blocks a concrete feature.

### Phase 1: Modularization & AI Backend Foundation ✅ Complete

**Goal:** Restructure the codebase and establish the pluggable AI backend. Existing functionality continues to work.

| Work Item | Description | Status |
|-----------|-------------|--------|
| Module extraction | Split `scatter.py` into `scanners/`, `analyzers/`, `core/`, `reports/`, `ai/` | ✅ |
| AI provider protocol | Define `AIProvider` interface with `analyze()`, `supports()`, `estimate_tokens()` | ✅ |
| AI task router | Implement provider selection, fallback logic, and configuration system | ✅ |
| Gemini migration | Move existing Gemini code into `providers/gemini_provider.py` | ✅ |
| Configuration system | `.scatter.yaml` config file, env vars, CLI flags | ✅ |
| Backward compatibility | `scatter.py` entry point preserved, delegates to new modules | ✅ |
| Test suite | Unit tests for each module | ✅ |
| WEX AI Platform provider | Implement default provider against WEX internal AI infrastructure | Deferred (Tier 4 — build when platform exists) |
| Anthropic provider | Implement Claude plugin (requires authorization) | Deferred (Tier 4 — build on demand) |
| OpenAI provider | Implement OpenAI/Azure OpenAI plugin (requires authorization) | Deferred (Tier 4 — build on demand) |
| Ollama provider | Local model support (requires authorization) | Deferred (Tier 4 — build on demand) |
| AI response caching | File-based cache with TTL and code-change invalidation | Deferred (Tier 4 — premature; AI calls are infrequent and cheap) |
| Token budget manager | Context chunking, priority selection, cost estimation logging | Deferred (Tier 4 — premature) |

### Phase 2: CSE Impact Analysis & AI Enrichment

**Goal:** Work request in, impact analysis out, with AI enrichment.

| Work Item | Description |
|-----------|-------------|
| Impact analysis mode | New `scatter impact` command accepting CSE / work request descriptions |
| AI work request parsing | AI extracts analysis targets (projects, sprocs, types) from natural language input |
| AI risk assessment | Risk rating with natural language justification for each analysis |
| AI coupling narrative | Explain *why* dependencies exist and what the coupling vectors are |
| AI impact narrative | Manager-friendly natural language impact summary |
| Enhanced blast radius | Transitive impact, confidence scoring, depth tracking |
| AI complexity estimate | Data-informed complexity rating for CSE scoping |

### Phase 3: Dependency Graph, Metrics & Domain Analysis

**Goal:** Full dependency graph with persistence, coupling metrics, and domain boundary detection. Shifts from analyzing individual targets to mapping the entire monolith.

| Work Item | Description |
|-----------|-------------|
| Dependency graph model | `DependencyGraph` data structure with all operations |
| Graph persistence | Save/load graph, invalidation on code changes |
| Coupling metrics | Fan-in, fan-out, instability index, coupling score per project |
| Transitive analysis | N-hop consumer tracing with depth tracking |
| Circular dependency detection | Find and report cycles |
| Domain boundary detection | Graph clustering to identify natural service boundaries |
| AI boundary assessment | AI evaluates each proposed boundary with extraction feasibility |
| Database dependency mapping | Enhanced sproc analysis + EF table refs + connection strings |
| Health dashboard data | All metrics computed and available for reporting |

### Phase 4: Reporting & Extraction Planning

**Goal:** Fix existing report quality issues, add missing output formats, build interactive reports, extraction planning tools, and baseline tracking. Informed by the report evaluation in `docs/OUTPUT_REPORT_EVALUATION.md`.

**Sub-phases** (resequenced 2026-03-13 by adoption impact):

| Sub-phase | Focus | Key Deliverables | Status |
|-----------|-------|-------------------|--------|
| **4a: Report quality fixes** | Fix correctness issues in existing reporters | Native JSON objects, `null` for absent fields, metadata block, console polish, CSV cleanup | ✅ Complete |
| **4b: Filter pipeline visibility** | Surface the multi-stage filter funnel in all output | FilterPipeline dataclass, zero-results debugging hints | ✅ Complete |
| **4c: Blast radius tree view** | Render propagation path as a tree, not a flat list | Tree console output, BFS parent tracking, `propagation_tree` in JSON | ✅ Complete |
| **4d: Markdown output** | Paste-ready format for PRs, tickets, wikis | `--output-format markdown`, inline Mermaid diagrams for graph mode | ✅ Complete |
| **4.5: Credibility & adoption** | Fix broken features, integrate graph, enable adoption | Fix `--summarize-consumers`, graph→analysis integration, Claude skills, `scatter pipelines` | **Next** |
| **4e: Unified report data model** | One `AnalysisReport` object, many formatters | Normalized schema across all modes, `--schema-version` for migration | Deferred (Tier 4) |
| **4f: Diff reports** | Compare two analyses over time | `--compare-to`, DiffReport, coupling trend tracking | After CI/CD (Tier 3) |

**Note:** Phase 4e (unified report model) demoted to Tier 4. It is architecturally correct but no user sees it — the current four output formats work. Phase 4.5 is a new insertion capturing adoption-critical items that should ship before any further infrastructure work. Phase 5 (CI/CD) is now prioritized ahead of 4e and 4f.

| Work Item | Description |
|-----------|-------------|
| Report quality fixes | Fix JSON serialization (stringified dicts/lists), use `null` for absent fields, add metadata block (timestamp, version, CLI args), console polish ("done." removal, filter display), CSV cleanup |
| Filter pipeline visibility | Surface intermediate filter counts in all output; zero-results debugging hints |
| Blast radius tree view | Tree rendering of propagation paths in console and JSON; BFS parent tracking |
| Markdown output | `--output-format markdown` for all modes; inline Mermaid for graph mode |
| Unified report data model | `AnalysisReport` dataclass normalizing all modes; snake_case schema; `--schema-version` flag |
| Diff reports | `--compare-to <previous.json>` producing coupling deltas, new/resolved cycles, consumer changes |
| Baseline save/load | Snapshot dependency graph and metrics at a point in time |
| Baseline diff | Compare current state against baseline, compute deltas |
| AI progress narrative | Natural language summary of changes since baseline |
| HTML report engine | Self-contained single-file HTML reports with embedded JS/CSS |
| Dependency graph visualization | Interactive D3.js dependency diagrams in HTML |
| Metric dashboard view | Color-coded health indicators, sortable project tables |
| Extraction planning mode | `scatter extract` with full extraction scope analysis |
| AI migration strategy | Step-by-step extraction approach with sequencing and risk mitigation |
| AI contract generation | Draft interface definitions for extraction boundaries |
| Mermaid output | Standalone `--output-format mermaid` with cluster subgraphs |

### Phase 5: CI/CD Integration & Workflow (promoted to Tier 2 — ship after Phase 4.5)

**Goal:** Integrate Scatter into CI/CD for continuous, automated analysis. Exit codes and `--fail-on` flags (from `docs/OUTPUT_REPORT_EVALUATION.md`, Section F) are the entry point — they turn Scatter from a reporting tool into an enforceable architecture governance tool.

**Priority note (2026-03-13):** Phase 5 CI/CD gates and PR comments are now prioritized ahead of Phase 4e-f (unified report model, diff reports, baselines, HTML). CI/CD integration makes scatter sticky — it runs without anyone remembering to use it. The unified report model and diff reports are Tier 3-4 items that should wait for real adoption to inform their design.

| Work Item | Description | Priority |
|-----------|-------------|----------|
| CI/CD check mode | `--fail-on` flags with multiple triggers: `cycles`, `risk:high`, `coupling:15.0`, `consumers:20`. Exit 0 = pass, exit 1 = threshold violated. Reports still produced. Configurable via `.scatter.yaml` | **Tier 2 — ship first** |
| PR blast radius comments | Post impact analysis as PR comment (Azure DevOps / GitHub) | **Tier 2 — ship first** |
| Coupling thresholds | Configurable gates in `.scatter.yaml` (max_blast_radius, max_coupling_increase, block_new_cycles) | Tier 2 |
| Automatic baseline updates | Update baseline on main branch merges | Tier 3 (depends on baselines) |
| Streaming progress | `tqdm` progress bars on stderr for long-running scans; suppress in `--quiet` and CI mode | Tier 4 — deferred (graph cache means most runs <2s) |
| Watch mode | File-watching for iterative local exploration | Tier 4 — deferred (no user demand) |

---

## 13. Glossary

Terms used throughout this document.

| Term | Plain English Definition |
|------|------------------------|
| **Monolith** | A large application where all code is built and deployed as a single unit. Like a building with no internal walls - renovating one room requires shutting down the whole building. WEX's core .NET codebase is a monolith. |
| **Microservice** | A small, independent application that does one thing and communicates with others through defined interfaces. Like separate buildings that communicate via mail - you can renovate one without affecting the others. |
| **Decomposition** | The process of breaking a monolith into microservices. The long-term goal for WEX's modernization effort. |
| **SOW (Statement of Work)** | A formal document describing work to be done - feature changes, system modifications, or service extractions. SOWs are *input* to Scatter: you feed in the SOW, and Scatter tells you the full impact. |
| **CSE (Customer Supported Enhancement)** | A customer-requested change to WEX systems. Like an SOW, this is *input* to Scatter for impact analysis. |
| **Dependency** | When one piece of code relies on another to function. If Project A uses code from Project B, A "depends on" B. If B breaks, A breaks too. |
| **Blast Radius** | The set of all systems affected by a change. Small blast radius = safe change. Large blast radius = risky change that needs careful coordination. |
| **Coupling** | How tightly connected two pieces of code are. High coupling = deeply intertwined, hard to change independently. Low coupling = relatively independent. |
| **Cohesion** | How focused a single project is. High cohesion = does one thing well. Low cohesion = grabs responsibilities from many different areas. |
| **Fan-in** | How many other projects depend on a given project. High fan-in = many things break if this breaks. These are "handle with extreme care" projects. |
| **Fan-out** | How many projects a given project depends on. High fan-out = this project needs many other things to work. These are complex and hard to test. |
| **Stored Procedure (Sproc)** | A pre-written database operation stored in the database server. When multiple applications call the same sproc, they're invisibly coupled through the database - even if they have no direct code relationship. |
| **Transitive Dependency** | An indirect dependency chain. If A depends on B and B depends on C, then A is *transitively* dependent on C - a change to C can break A even though A never directly references C. |
| **Circular Dependency** | When A depends on B and B depends on A (or longer loops). These must be untangled before a clean extraction is possible. |
| **Domain Boundary** | A logical dividing line between areas of business functionality (e.g., payments vs. portal vs. batch processing). The natural places to "cut" when decomposing a monolith. |
| **Strangler Fig Pattern** | A migration strategy where new code gradually replaces old code piece by piece, rather than a risky "big bang" rewrite. Named after fig vines that slowly grow around and replace a host tree. |
| **Anti-Corruption Layer** | A translation layer between old and new code during migration. Prevents the old system's design from "infecting" the new service. Like an adapter plug between different electrical standards. |
| **API Contract** | A formal specification of how two services communicate - what data goes in, what comes back, what errors can happen. When code that used to be a direct function call becomes a service call, that function signature becomes an API contract. |
| **Baseline** | A saved snapshot of the codebase's dependency metrics at a point in time. Used to measure progress: "Coupling has decreased 15% since Q4 baseline." |
| **CI/CD Pipeline** | The automated system that builds, tests, and deploys code when developers push changes. Scatter can plug into this to automatically flag risky changes before they're merged. |
| **Token** | The unit AI models use to measure text size. Relevant because AI calls have size limits and cost is based on token usage. Scatter manages this automatically. |
| **Context Window** | The maximum amount of text an AI model can process at once. Scatter's token budget manager ensures code excerpts fit within the window and uses the most relevant excerpts when space is limited. |
