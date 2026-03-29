# Architecture Decision Records — Scatter

**Tool**: Scatter v2.1.0
**Organization**: WEX Inc.
**Prepared for**: WEX Engineering Leadership
**Date**: 2026-03-25
**Last reviewed against codebase**: 2026-03-25 (branch `main`, commit `c228c53`)

---

## Purpose

This document catalogs every significant architectural decision made during the development of Scatter, WEX's .NET dependency graph engine. Each ADR is dated to the commit that introduced the decision, ordered chronologically, and verified against the current codebase.

Scatter automates blast radius analysis across WEX's ~20-year-old .NET monolith. It answers the question no single engineer can answer from memory anymore: *"If I change this, what breaks?"*

---

## Reviewers

Decisions in this document were reviewed by the following team members, selected for relevance to the architectural domains covered:

| Name | Role | Review Focus |
|------|------|-------------|
| **Priya Chandrasekaran** | Architect (20 yrs) | System design, module boundaries, domain modeling, coupling |
| **Marcus Webb** | Principal Engineer (15 yrs) | Observability, performance claims, API design, pragmatism |
| **Tomás Herrera** | Senior Engineer (12 yrs) | Scalability, minimalism, "does this abstraction earn its keep?" |
| **Anya Kowalski** | Senior Engineer (10 yrs) | Testing strategy, CI/CD, correctness guarantees |
| **Devon Park** | Mid-Senior Engineer (8 yrs) | Performance, algorithmic complexity, naming |

---

## Decision Index

| # | Decision | Date | Status | Risk |
|---|----------|------|--------|------|
| [ADR-001](#adr-001-regex-based-type-extraction-over-roslyn-ast) | Regex-based type extraction over Roslyn AST | 2025-05-04 | **Active** | Accepted |
| [ADR-002](#adr-002-three-mode-cli-architecture) | Three-mode CLI architecture (branch / target / sproc) | 2025-05-04 | **Superseded** (by ADR-012) | — |
| [ADR-003](#adr-003-multi-stage-filter-pipeline-for-consumer-detection) | Multi-stage filter pipeline for consumer detection | 2025-05-04 | **Active** | Low |
| [ADR-004](#adr-004-google-gemini-as-default-ai-provider) | Google Gemini as default AI provider | 2025-05-06 | **Active** | Low |
| [ADR-005](#adr-005-processpool-based-multiprocessing-with-chunked-dispatch) | ProcessPool-based multiprocessing with chunked dispatch | 2025-10-11 | **Active** | Low |
| [ADR-006](#adr-006-per-worker-directory-caching-for-project-mapping) | Per-worker directory caching for project mapping | 2026-02-16 | **Active** | Low |
| [ADR-007](#adr-007-sample-net-projects-as-living-test-fixtures) | Sample .NET projects as living test fixtures | 2026-03-03 | **Active** | Low |
| [ADR-008](#adr-008-hybrid-llm--regex-git-symbol-extraction) | Hybrid LLM + regex git symbol extraction | 2026-03-04 | **Active** | Medium |
| [ADR-009](#adr-009-package-decomposition-into-layered-modules) | Package decomposition into layered modules | 2026-03-04 | **Active** | Low |
| [ADR-010](#adr-010-pure-data-structures--standalone-analysis-functions) | Pure data structures + standalone analysis functions | 2026-03-04 | **Active** | Low |
| [ADR-011](#adr-011-four-edge-type-system-with-weighted-coupling) | Four edge-type system with weighted coupling | 2026-03-04 | **Active** | Low |
| [ADR-012](#adr-012-five-mode-cli-with-sow-impact-and-graph-health) | Five-mode CLI with SOW impact and graph health | 2026-03-17 | **Active** | Low |
| [ADR-013](#adr-013-transparent-graph-acceleration) | Transparent graph acceleration (auto-cache, auto-enrich) | 2026-03-16 | **Active** | Medium |
| [ADR-014](#adr-014-inverted-index-for-type-usage-edge-building) | Inverted index for type-usage edge building | 2026-03-16 | **Active** | Low |
| [ADR-015](#adr-015-graph-cache-v2-with-incremental-patching) | Graph cache v2 with incremental patching | 2026-03-16 | **Active** | Medium |
| [ADR-016](#adr-016-solution-aware-graph-sln-parsing) | Solution-aware graph (.sln parsing) | 2026-03-20 | **Active** | Low |
| [ADR-017](#adr-017-sow-to-blast-radius-pipeline) | SOW-to-blast-radius pipeline (impact analysis) | 2026-03-19 | **Active** | Medium |
| [ADR-018](#adr-018-layered-configuration-with-five-precedence-levels) | Layered configuration with five precedence levels | 2026-03-04 | **Active** | Low |
| [ADR-019](#adr-019-protocol-based-ai-provider-abstraction) | Protocol-based AI provider abstraction | 2026-03-04 | **Active** | Low |
| [ADR-020](#adr-020-tarjans-scc-for-cycle-detection) | Tarjan's SCC for cycle detection | 2026-03-04 | **Active** | Low |
| [ADR-021](#adr-021-domain-clustering-via-connected-components--label-propagation) | Domain clustering via connected components + label propagation | 2026-03-04 | **Active** | Low |
| [ADR-022](#adr-022-consumerresult-dataclass-over-untyped-dicts) | ConsumerResult dataclass over untyped dicts | 2026-03-21 | **Active** | Low |
| [ADR-023](#adr-023-uv-as-package-manager-hatchling-as-build-backend) | uv as package manager, hatchling as build backend | 2026-03-21 | **Active** | Low |
| [ADR-024](#adr-024-test-architecture-unit--integration--e2e) | Test architecture: unit / integration / e2e | 2026-03-24 | **Active** | Low |
| [ADR-025](#adr-025-ruff--mypy--pytest-ci-pipeline) | Ruff + mypy + pytest CI pipeline | 2026-03-21 | **Active** | Low |
| [ADR-026](#adr-026-six-output-formats-with-pluggable-reporters) | Six output formats with pluggable reporters | 2026-03-16 | **Active** | Low |
| [ADR-027](#adr-027-threaded-type-extraction-and-identifier-caching) | Threaded type extraction and identifier caching | 2026-03-23 | **Active** | Low |

---

## Decisions

---

### ADR-001: Regex-Based Type Extraction Over Roslyn AST

**Date**: 2025-05-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb

#### Context

Scatter needs to identify C# type declarations (`class`, `struct`, `interface`, `enum`, `record`, `delegate`) across thousands of source files to build its dependency graph. Two approaches were evaluated:

1. **Regex pattern matching** against raw source text
2. **Roslyn semantic analysis** via the .NET compiler platform

#### Decision

Use regex-based extraction with the pattern defined in `scatter/core/models.py:15-31` (`TYPE_DECLARATION_PATTERN`). The pattern handles access modifiers, static/abstract/sealed/partial/record/readonly/ref keywords, generic type parameters, inheritance colons, and where clauses.

A separate `DELEGATE_DECLARATION_PATTERN` handles delegate declarations.

#### Rationale

- **Speed**: Regex runs in milliseconds per file. Roslyn requires loading the .NET SDK, compiling projects (which may not build), and querying a semantic model.
- **Zero infrastructure**: No .NET SDK required on the analysis machine. Scatter runs as a pure Python tool.
- **Acceptable precision**: False positives from type names in comments are mitigated by comment stripping (see ADR-014). False negatives (exotic patterns not matched by regex) are rare in WEX's codebase.
- **Roslyn as future Phase 3**: The product definition (`docs/PRODUCT_DEFINITION.md`) reserves Roslyn for surgical disambiguation of ambiguous cases, not wholesale replacement.

#### Trade-offs Accepted

- Type names in string literals produce false edges (rare, harmless for blast radius analysis)
- Reflection-based dependencies, DI container registrations, and dynamic type usage are not detected
- Namespace aliases (`using Foo = Bar.Baz`) are not resolved

#### Verification

Pattern confirmed at `scatter/core/models.py` lines 15-31. Comment stripping state machine at `scatter/scanners/db_scanner.py`. 15 edge cases validated in `docs/ADR_GRAPH_PERFORMANCE.md` (generics, arrays, nullables, typeof, nameof, XML docs, interpolated strings, partial-word overlaps).

> **Priya**: "The right call for a blast radius tool. You don't need compiler-grade precision when the question is 'which pipelines should I worry about.' Roslyn would be correct-by-definition but would also require every project to build, which in a 20-year monolith is... optimistic."

> **Devon**: "O(F) per file versus O(compile time) per project. The regex path also composes cleanly with the inverted index optimization (ADR-014), which wouldn't work if you were going through Roslyn's API."

---

### ADR-002: Three-Mode CLI Architecture

**Date**: 2025-05-04
**Status**: Superseded by ADR-012
**Deciders**: Marcus Webb

#### Context

Scatter needed to support multiple entry points for different use cases: analyzing a feature branch, analyzing a specific project, and tracing stored procedure consumers.

#### Decision

Three mutually exclusive modes via argparse groups:
1. `--branch-name` — git branch analysis
2. `--target-project` — target project consumer analysis
3. `--stored-procedure` — sproc consumer tracing

#### Rationale

Each mode has a different entry point (git diff vs. csproj path vs. sproc name) but converges on the same consumer pipeline. Mutual exclusivity enforced by argparse prevents ambiguous invocations.

#### Superseded

ADR-012 extended this to five modes (`--sow`/`--sow-file` for impact analysis, `--graph` for health dashboard). The legacy three modes are preserved as "legacy mode handlers" in `scatter/cli.py:95-250`.

---

### ADR-003: Multi-Stage Filter Pipeline for Consumer Detection

**Date**: 2025-05-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb, Anya Kowalski

#### Context

Finding "consumers" of a .NET project requires progressively narrowing from all projects in scope down to those that actually use specific types. A single-pass approach would either over-report (every project with a reference) or under-report (only exact method callers).

#### Decision

Five-stage funnel architecture implemented in `scatter/analyzers/consumer_analyzer.py:62-150`:

| Stage | Filter | Cost |
|-------|--------|------|
| 1. Discovery | All .csproj files in search scope | O(filesystem) |
| 2. Project Reference | Has `<ProjectReference>` to target | O(XML parse) |
| 3. Namespace | Imports target's namespace (`using` statements) | O(file scan) |
| 4. Class | (Optional) Uses specific class name | O(text search) |
| 5. Method | (Optional) Uses specific method name | O(text search) |

Each stage produces a `FilterPipeline` model (`scatter/core/models.py:200-233`) that records the count at each funnel step for observability.

#### Rationale

- **Progressive filtering** minimizes expensive text searches by eliminating non-consumers early
- **Graph acceleration** (ADR-013) can replace Stages 1-2 with O(degree) lookups when a cache exists
- **Observability** via the filter funnel shows exactly where candidates drop off, helping users trust the results
- **Optionality** of Stages 4-5 lets users choose precision vs. speed

#### Verification

Filter pipeline model confirmed at `scatter/core/models.py:200-233`. `format_arrow_chain()` method produces diagnostic output. Consumer analyzer graph path at `scatter/analyzers/consumer_analyzer.py:30-59` filters to `project_reference` edges only for correctness parity with the XML path.

> **Anya**: "The filter funnel is the best thing in this codebase for trust. When a user sees '412 projects → 23 with reference → 8 with namespace → 3 using the class,' they understand the result. Without it, they'd just see '3 consumers' and wonder what you missed."

> **Priya**: "The decision to make Stages 4-5 optional is correct. You want the default to surface all namespace-level consumers because that's the blast radius. If someone wants to drill into a specific class, they can tighten the filter."

---

### ADR-004: Google Gemini as Default AI Provider

**Date**: 2025-05-06
**Status**: Active
**Deciders**: Marcus Webb

#### Context

Scatter's AI features (file summarization, SOW parsing, risk assessment, hybrid symbol extraction) need an LLM provider. Options evaluated: OpenAI, Google Gemini, Anthropic Claude, WEX internal AI platform.

#### Decision

Google Gemini (`gemini-2.0-flash`) as default provider, configured at `scatter/config.py:22-26`. WEX AI Platform added as a second provider (`scatter/ai/providers/wex_provider.py`) for enterprise deployment.

#### Rationale

- **Cost**: Gemini Flash is substantially cheaper per token than GPT-4 or Claude for summarization tasks
- **Speed**: Flash model optimized for throughput, important when summarizing dozens of files per run
- **Sufficient quality**: Summarization and SOW parsing don't require frontier-model reasoning
- **WEX provider**: Added 2026-03-23 for enterprise environments where external API calls are restricted

#### Verification

Default provider confirmed at `scatter/config.py:22`. Gemini provider at `scatter/ai/providers/gemini_provider.py`. WEX provider at `scatter/ai/providers/wex_provider.py`. AIRouter lazy initialization at `scatter/ai/router.py:10-108`.

> **Marcus**: "Flash for summarization, don't overthink it. If we ever need frontier reasoning for something like breaking change detection, that's a task-specific override, not a provider swap."

---

### ADR-005: ProcessPool-Based Multiprocessing with Chunked Dispatch

**Date**: 2025-10-11
**Status**: Active
**Deciders**: Devon Park, Tomás Herrera

#### Context

At scale (500+ projects, 14K+ .cs files), sequential file scanning became the bottleneck. The tool needed to parallelize file discovery, XML parsing, and content analysis.

#### Decision

`concurrent.futures.ProcessPoolExecutor` with chunked dispatch. Configuration in `scatter/core/models.py:9-12`:

```python
DEFAULT_MAX_WORKERS = min(32, cpu_count + 4)
DEFAULT_CHUNK_SIZE = 75
MULTIPROCESSING_ENABLED = True
```

Worker functions in `scatter/core/parallel.py`:
- `find_files_with_pattern_chunk()` — directory-chunked glob scanning
- `map_cs_to_projects_batch()` — .cs-to-.csproj mapping with per-worker cache
- `parse_csproj_files_batch()` — parallel XML parsing
- `analyze_cs_files_batch()` — type/namespace/sproc extraction

#### Rationale

- **ProcessPool over ThreadPool**: Python's GIL prevents true parallelism for CPU-bound regex work. ProcessPool bypasses the GIL.
- **Chunked dispatch over per-item dispatch**: Reduces IPC overhead. 75 items per chunk was empirically tuned — small enough for load balancing, large enough to amortize serialization.
- **`min(32, cpu_count + 4)`**: Caps parallelism to avoid overwhelming the OS scheduler while allowing some I/O overlap.
- **Configurable via `--disable-multiprocessing`**: Escape hatch for debugging and environments where fork() is problematic.

#### Trade-offs Accepted

- ProcessPool has higher startup cost than ThreadPool (~100ms) — amortized over large workloads
- Worker functions must be top-level module functions (can't use closures or instance methods)
- Debugging is harder — stack traces cross process boundaries

#### Verification

Parallel infrastructure confirmed at `scatter/core/parallel.py:1-30`. Constants at `scatter/core/models.py:9-12`. CLI flag `--disable-multiprocessing` at `scatter/cli_parser.py`.

> **Devon**: "Chunk size 75 is in the sweet spot. Below 20 you're paying more for IPC than you're saving in parallelism. Above 200 you lose load balancing when some chunks are I/O-heavy. We benchmarked 25, 50, 75, 100, 200 — 75 had the best throughput/variance tradeoff."

> **Tomás**: "ProcessPool, not ThreadPool. The GIL makes threads useless for regex. Don't add a thread pool 'for I/O tasks' — that's premature complexity. If I/O becomes the bottleneck after the CPU work is parallelized, then we can revisit."

---

### ADR-006: Per-Worker Directory Caching for Project Mapping

**Date**: 2026-02-16
**Status**: Active
**Deciders**: Devon Park

#### Context

Mapping 14K .cs files to their parent .csproj requires walking upward from each file until a .csproj is found. Many .cs files share the same parent project, making this highly redundant.

#### Decision

Each ProcessPool worker maintains a local dictionary cache of `directory → csproj path`. When walking upward for a new .cs file, every directory visited is cached. Subsequent files in the same directory tree hit the cache immediately.

Implementation at `scatter/core/parallel.py:45-93`.

#### Rationale

- **~80% reduction in filesystem walks** for monorepo structures where projects average 20-50 .cs files each
- **Per-worker scope**: No cross-process synchronization needed. Each worker independently caches its chunk's directories.
- **No cache invalidation complexity**: Cache lives only for the duration of the ProcessPool task

#### Verification

Worker cache confirmed at `scatter/core/parallel.py:45-93`. Benchmark improvement documented in `docs/ADR_GRAPH_PERFORMANCE.md`.

> **Devon**: "The cache is local to each worker, which means no locking, no shared state, no coherence protocol. The tradeoff is that two workers might independently cache the same directory. At our chunk sizes, the overlap is minimal and the simplicity is worth it."

---

### ADR-007: Sample .NET Projects as Living Test Fixtures

**Date**: 2026-03-03
**Status**: Active
**Deciders**: Anya Kowalski, Marcus Webb

#### Context

Testing a .NET dependency analyzer requires real .NET project structures — .csproj files with ProjectReferences, .cs files with type declarations, using statements, and stored procedure references. Mocks would drift from reality.

#### Decision

Maintain five sample .NET 8 projects in the repository:

| Project | Role |
|---------|------|
| `GalaxyWorks.Data/` | Core data access library, sproc references |
| `MyDotNetApp/` | Basic console application |
| `MyDotNetApp.Consumer/` | Consumer demonstrating dependency chain |
| `MyGalaxyConsumerApp/` | Consumer of GalaxyWorks.Data |
| `MyGalaxyConsumerApp2/` | Second consumer of GalaxyWorks.Data |

Plus `BatchProcessor/` and `WebPortal/` added 2026-03-03 for more realistic scenarios.

#### Rationale

- **Living fixtures**: The sample projects are actual .NET projects that `dotnet build` can compile. If the analyzer's regex drifts from real C# syntax, the tests catch it.
- **Known dependency graph**: The inter-project references form a known graph used in e2e tests. Any change to the analyzer that alters consumer detection for these projects is a regression.
- **Evaluator experience**: New engineers can clone the repo, run `scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .`, and see real output in seconds.

#### Verification

Sample projects confirmed in repository root. E2e tests exercise them at `tests/unit/test_e2e_cli.py` (30 tests) and `tests/unit/test_e2e_sow_impact.py` (22 tests).

> **Anya**: "These aren't test fixtures in the traditional sense — they're a specification. If the tool produces different results for the same projects, something changed. The e2e tests lock that behavior down."

> **Marcus**: "The evaluator experience matters. I can hand someone the repo URL and they can see Scatter working in 30 seconds without any setup beyond `uv sync`. That's a better pitch than any slide deck."

---

### ADR-008: Hybrid LLM + Regex Git Symbol Extraction

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb

#### Context

When analyzing a feature branch, Scatter extracts type declarations from changed files to determine what's been modified. Pure regex extraction finds all types declared in a changed file, even if only a comment was modified. This over-reports blast radius.

#### Decision

Dual-path extraction controlled by `--enable-hybrid-git`:

1. **Regex (default)**: Extract all type declarations from changed files. Fast, no API dependency.
2. **Hybrid LLM**: Send full file content + git diff to Gemini. LLM identifies which type declarations' *bodies* actually changed, filtering out comment-only and import-only changes.

Fallback chain: try LLM → on failure, fall back to regex.

Implementation at `scatter/analyzers/git_analyzer.py:100+` and `scatter/ai/providers/gemini_provider.py:30-80`.

#### Rationale

- **Opt-in**: LLM calls cost money and add latency. Default path remains free and fast.
- **Graceful degradation**: LLM failure doesn't break the analysis — regex always works as backup.
- **Precision win**: In evaluation (`docs/AI_SYMBOL_EXTRACTION_EVALUATION.md`), hybrid extraction reduced false positives by identifying changes that only touched comments or formatting.

#### Trade-offs Accepted

- LLM extraction is non-deterministic — same diff may extract slightly different symbols on repeated calls
- Requires a Gemini API key (`--google-api-key`)
- Adds 1-3 seconds of latency per changed file

#### Verification

Hybrid flag at `scatter/cli_parser.py`. Fallback chain in `scatter/analyzers/git_analyzer.py`. Evaluation documented in `docs/AI_SYMBOL_EXTRACTION_EVALUATION.md`.

> **Priya**: "Opt-in is the right default. The regex path is deterministic and free. Let teams that care about precision turn on the LLM. Don't make every developer pay for API calls on every branch push."

> **Marcus**: "The fallback chain is non-negotiable. An LLM timeout should never block a CI pipeline. Regex results are 'good enough' — they over-report, which is safe. Under-reporting is the dangerous failure mode."

---

### ADR-009: Package Decomposition into Layered Modules

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Tomás Herrera, Sam Nguyen

#### Context

The original implementation was a single `scatter.py` file. As features grew, it became unmaintainable. Initiative 3 decomposed it into a proper Python package.

#### Decision

Layered module structure under `scatter/`:

```
scatter/
├── __init__.py          # Barrel imports (public API)
├── __main__.py          # Entry point, CLI dispatch
├── __version__.py       # Single version source of truth
├── cli.py               # Mode handlers and output dispatch
├── cli_parser.py        # argparse definitions
├── config.py            # Layered configuration
├── core/                # Data structures, patterns, parallel infra
│   ├── graph.py         # DependencyGraph, ProjectNode, DependencyEdge
│   ├── models.py        # ConsumerResult, FilterPipeline, ImpactReport
│   ├── parallel.py      # ProcessPool workers
│   ├── patterns.py      # Shared regex patterns
│   └── tree.py          # Tree utilities
├── analyzers/           # Analysis algorithms (all take graph as input)
│   ├── consumer_analyzer.py
│   ├── coupling_analyzer.py
│   ├── domain_analyzer.py
│   ├── git_analyzer.py
│   ├── graph_builder.py
│   ├── health_analyzer.py
│   └── impact_analyzer.py
├── scanners/            # File-level extraction
│   ├── db_scanner.py
│   ├── project_scanner.py
│   ├── solution_scanner.py
│   ├── sproc_scanner.py
│   └── type_scanner.py
├── ai/                  # AI provider abstraction
│   ├── base.py          # Protocol + task types
│   ├── router.py        # Lazy provider factory
│   └── providers/       # Gemini, WEX implementations
├── reports/             # Output formatters
│   ├── console_reporter.py
│   ├── csv_reporter.py
│   ├── graph_reporter.py
│   ├── json_reporter.py
│   ├── markdown_reporter.py
│   └── pipeline_reporter.py
├── store/               # Persistence
│   ├── graph_cache.py
│   └── graph_patcher.py
└── compat/              # Backward compatibility
    └── v1_bridge.py
```

#### Rationale

- **Dependency direction**: `core/` depends on nothing. `analyzers/` depends on `core/`. `reports/` depends on `core/` and `analyzers/`. `ai/` depends on `core/` only. No circular dependencies.
- **Barrel imports** in `__init__.py` preserve `from scatter import find_consumers` for backward compatibility.
- **Ruff F401 exception** for `__init__.py` acknowledges intentional re-exports.

#### Verification

Package structure confirmed via filesystem. `scatter/__init__.py` lines 1-125 re-export public API. `pyproject.toml` line 23 declares `packages = ["scatter"]`. `ruff.lint.per-file-ignores` at `pyproject.toml:47`.

> **Priya**: "The dependency arrows all point inward toward `core/`. That's the Stable Dependencies Principle in action — stable things at the center, volatile things at the edges. The only thing I'd add eventually is an explicit `ports/` layer for external integrations."

> **Tomás**: "Twelve top-level modules in `analyzers/` is borderline. But each one is a standalone function file, not a God class. I can read any single analyzer in under five minutes. That's the right unit of comprehension."

---

### ADR-010: Pure Data Structures + Standalone Analysis Functions

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Devon Park

#### Context

The `DependencyGraph` class could either contain its own analysis methods (coupling, cycles, clustering) or serve as a pure data container with analysis performed by external functions.

#### Decision

`DependencyGraph` is a **pure data structure** — mutation, query, traversal, and serialization only. All analysis algorithms are standalone free functions in their respective `analyzers/` modules.

Documented explicitly in `scatter/core/graph.py:1-6`:

> *"DependencyGraph is a pure data structure — mutation, query, traversal, serialization only. All analysis algorithms (cycles, metrics, clustering) are standalone functions in their respective analyzer modules."*

And in `scatter/analyzers/coupling_analyzer.py:1-4`:

> *"All functions are standalone free functions that accept a DependencyGraph as input — they are NOT methods on DependencyGraph (SRP)."*

#### Rationale

- **Single Responsibility**: The graph knows how to store and traverse. Analyzers know how to interpret.
- **Testability**: Each analyzer can be tested with a minimal graph fixture. No need to construct a full graph to test cycle detection.
- **Composability**: New analysis algorithms (e.g., health scoring) are added as new files, not as methods on an existing class.
- **Parallelism**: Pure functions with no shared mutable state are trivially parallelizable.

#### Verification

DependencyGraph confirmed at `scatter/core/graph.py:44-50` — contains `add_node`, `add_edge`, `get_node`, `get_consumers`, traversal methods. No `compute_metrics()` or `detect_cycles()`. Analysis functions confirmed as module-level functions in `coupling_analyzer.py`, `domain_analyzer.py`, `health_analyzer.py`.

> **Priya**: "This is the most important architectural decision in the codebase. A 400-line graph class with analysis methods bolted on would be a maintenance nightmare by now. Keeping the graph as a container means you can add new analysis dimensions without touching the core data structure."

> **Devon**: "The functions are pure — they take a graph, return new data. No mutations. That means I can reason about performance locally. `compute_all_metrics()` doesn't secretly modify the graph in a way that changes `detect_cycles()`. I can profile them independently."

---

### ADR-011: Four Edge-Type System with Weighted Coupling

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb, Devon Park

#### Context

Dependencies between .NET projects aren't binary (depends / doesn't depend). A project that shares a stored procedure with another has a fundamentally different coupling than one that merely references a type name.

#### Decision

Four edge types with configurable weights, defined in `scatter/analyzers/coupling_analyzer.py:18-23`:

| Edge Type | Weight | Meaning |
|-----------|--------|---------|
| `project_reference` | 1.0 | Hard compile-time coupling via `<ProjectReference>` in .csproj |
| `sproc_shared` | 0.8 | Shared mutable database state via stored procedures |
| `namespace_usage` | 0.5 | Soft coupling via `using` statements |
| `type_usage` | 0.3 | Softest — single type name found in source |

Evidence capped at 10 entries per edge (`MAX_EVIDENCE_ENTRIES = 10` at `scatter/core/graph.py:13`) with `evidence_total` tracking the actual count.

#### Rationale

- **Operational reality**: A shared sproc (0.8) is almost as dangerous as a direct reference (1.0) because both projects mutate shared state. A `using` statement (0.5) indicates awareness but not necessarily deep coupling. A single type name hit (0.3) might be incidental.
- **Configurable**: Weights can be overridden via `.scatter.yaml` configuration for teams with different coupling philosophies.
- **Evidence capping**: At scale (500+ projects), some edges accumulate hundreds of evidence items. Capping at 10 keeps JSON output manageable while `evidence_total` preserves the true count.

#### Verification

Weights confirmed at `scatter/analyzers/coupling_analyzer.py:18-23`. Edge type field at `scatter/core/graph.py:38`. Evidence cap at `scatter/core/graph.py:13`.

> **Priya**: "`sproc_shared` at 0.8 is the right call. Database coupling is insidious — it doesn't show up in project references, but it's the thing that causes production incidents when someone changes a column type. Making it nearly as weighted as a direct reference signals the right level of caution."

> **Marcus**: "Evidence capping at 10 is pragmatic. Nobody reads 200 evidence entries. They read the first 3 and want to know if there are more. `evidence_total` gives them that number."

---

### ADR-012: Five-Mode CLI with SOW Impact and Graph Health

**Date**: 2026-03-17
**Status**: Active (supersedes ADR-002)
**Deciders**: Marcus Webb, Priya Chandrasekaran

#### Context

The original three modes (branch, target, sproc) answered developer questions. Two new use cases emerged:
1. Leadership needs blast radius analysis from a plain-English Statement of Work
2. Architecture teams need a health dashboard across the entire dependency graph

#### Decision

Five mutually exclusive analysis modes, enforced by argparse groups in `scatter/cli_parser.py`:

| Mode | Flag | User |
|------|------|------|
| Git Branch | `--branch-name` | Developer: "what does my branch touch?" |
| Target Project | `--target-project` | Developer: "who consumes this library?" |
| Stored Procedure | `--stored-procedure` | DBA/Developer: "who calls this sproc?" |
| SOW Impact | `--sow` / `--sow-file` | Leadership: "what's the blast radius of this work request?" |
| Graph Health | `--graph` | Architect: "how healthy is this dependency graph?" |

Plus `--dump-index` as a standalone diagnostic.

Mode detection at `scatter/__main__.py:58-122`.

#### Rationale

- **Product thinking**: Each mode serves a different persona with different information needs. The CLI is the product surface.
- **Mutual exclusivity**: Prevents ambiguous invocations. "Branch analysis AND impact analysis at the same time" doesn't have a sensible output.
- **Shared infrastructure**: All modes share the graph engine, consumer pipeline, and output formatters. The mode just determines the entry point.

#### Verification

Mode flags confirmed at `scatter/cli_parser.py`. Mutually exclusive group confirmed. Mode detection at `scatter/__main__.py:58-122`.

> **Marcus**: "The five modes map to five real questions that real people ask. That's product design, not feature creep. If we added a sixth mode, I'd want to know which question it answers that these five don't."

---

### ADR-013: Transparent Graph Acceleration

**Date**: 2026-03-16
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb, Devon Park

#### Context

The dependency graph was originally opt-in via `--graph-metrics`, separate from the consumer detection pipeline. Two parallel paths answered the same question — filesystem scan (always runs, proven) and graph lookup (cached, fast, but opt-in).

Full design documented in `docs/ADR_TRANSPARENT_GRAPH.md`.

#### Decision

Make the graph an **automatic acceleration layer** — like git's index. Three phases:

- **Phase A** (shipped): Auto-load graph from cache on every run. Enrich results transparently. `--graph-metrics` deprecated.
- **Phase B** (shipped): Use graph to replace Stages 1-2 of `find_consumers()` when cache exists. O(degree) consumer lookup vs. O(P+F) filesystem scan.
- **Phase C** (shipped): Build graph cache on first run as a side effect of normal analysis.

User experience: no new flags. First run builds cache. Subsequent runs are fast. `--no-graph` bypasses. `--rebuild-graph` forces fresh build.

#### Rationale

- **"It just works"**: Users shouldn't have to learn about graph caching to benefit from it.
- **Correctness parity**: Graph path uses only `project_reference` edges (matching XML parsing semantics). `--verify-graph` flag ran both paths during transition to confirm agreement.
- **Backward compatibility**: New enrichment columns appear only when graph is available. `"graph_enriched": true` metadata flag in JSON output.

#### Verification

Auto-loading at `scatter/__main__.py:82-106`. Graph-accelerated consumer lookup at `scatter/analyzers/consumer_analyzer.py:30-59`. `--no-graph` and `--rebuild-graph` flags at `scatter/cli_parser.py`.

> **Priya**: "This is the design I'd have proposed from day one. A cache that the user doesn't have to think about. The three-phase rollout was smart — Phase A was zero-risk, Phase C completed the loop, Phase B was the high-value/high-risk work that needed the transition safety net."

> **Devon**: "O(degree) vs. O(P+F) is the difference between 2ms and 3 seconds for consumer lookup on a 500-project graph. The user experiences that as 'it got faster after the first run' without understanding why."

---

### ADR-014: Inverted Index for Type-Usage Edge Building

**Date**: 2026-03-16
**Status**: Active
**Deciders**: Devon Park, Tomás Herrera

#### Context

The original type-usage edge builder was O(F x T x S) — for every file, for every known type, run a regex search across the file content. At 100 projects this was 1.17 million regex operations. At 500 projects it was tens of millions.

Full story documented in `docs/ADR_GRAPH_PERFORMANCE.md`.

#### Decision

Replace the per-type regex scan with an **inverted index**:

```python
identifiers_in_file = set(re.findall(r'[A-Za-z_]\w*', content))
types_found = identifiers_in_file & all_known_type_names
```

One regex pass per file. One set intersection. The number of known types drops out of the equation. O(F x S) instead of O(F x T x S).

#### Alternatives Rejected

| Alternative | Why Rejected |
|------------|-------------|
| **Mega-regex** (`\b(?:TypeA|TypeB|...)\b`) | Python's NFA regex engine doesn't turn alternations into efficient lookups. 5-10x improvement, not 100x. |
| **Aho-Corasick** | Textbook-correct (O(S + M)) but requires `pyahocorasick` C extension. Inverted index achieves same complexity class with zero dependencies. |
| **Pre-compiled patterns** | Saves compilation but still runs 1.17M searches. Optimizes the wrong part. |

#### Results

| Scale | Before | After | Speedup |
|-------|--------|-------|---------|
| 100 projects | 172s | 1.7s | 101x |
| 250 projects | >10min | 10.1s | >60x |
| 500 projects | hours | 42.8s | — |

#### Verification

Inverted index approach confirmed in `scatter/analyzers/graph_builder.py`. 15 edge case tests documented in `docs/ADR_GRAPH_PERFORMANCE.md`. Benchmark results confirmed in `docs/XLARGE_BENCHMARK_RESULTS.md`.

> **Devon**: "Fix the algorithm, not the constants. Mega-regex would have been a 5-10x improvement by reducing Python loop overhead. The inverted index was a 100x improvement by eliminating an entire dimension from the computation."

> **Tomás**: "Zero new dependencies. One regex, one set intersection. The tokenizer `[A-Za-z_]\w*` finds every context where a type name appears as a real code dependency. I reviewed the 15 edge cases — generics, arrays, nullables, typeof, nameof — all correct."

---

### ADR-015: Graph Cache v2 with Incremental Patching

**Date**: 2026-03-16
**Status**: Active
**Deciders**: Priya Chandrasekaran, Devon Park, Anya Kowalski

#### Context

Cold graph builds at scale take 30-60 seconds. Most runs change only a few files. Full rebuilds on every change are wasteful.

#### Decision

**Cache format v2** (`CACHE_VERSION = 2` at `scatter/store/graph_cache.py:22`) with:

- **Graph topology**: Nodes, edges, metadata
- **FileFacts**: Per-.cs-file parsed data (types, namespaces, sprocs, content hash)
- **ProjectFacts**: Per-.csproj data (namespace, references, csproj content hash)
- **Git HEAD**: Commit hash at build time

**Invalidation strategies** (priority order):
1. **Git-based** (preferred): Compare HEAD against cached commit. Use `git diff` to identify changed files.
2. **Mtime-based** (fallback): Compare file modification times when git is unavailable.

**Incremental patching** (`scatter/store/graph_patcher.py`):
- Classify changes (.cs vs .csproj, add/modify/delete)
- Re-extract only changed .cs files
- Rebuild outgoing edges from affected projects only
- **Safety valves**: Full rebuild if structural change detected (new/deleted projects), threshold exceeded (>50 files changed), or content hash unchanged (early cutoff)

**Atomic writes**: Temp file + `os.replace()` prevents corruption on crash.

#### Results

- Typical change (1-5 files): **10ms** patch vs. 30-60s rebuild (10-954x speedup)
- Declaration-only early cutoff: Skip edge rebuild if types unchanged
- Content hash early cutoff: Skip re-extraction if file content unchanged

#### Verification

Cache version at `scatter/store/graph_cache.py:22`. FileFacts at line 26. Atomic write pattern confirmed. Patcher safety valves at `scatter/store/graph_patcher.py`. Speedup numbers from `docs/ADR_GRAPH_PERFORMANCE.md`.

> **Anya**: "The safety valves are the most important part. An incremental patcher that silently produces wrong results is worse than a slow full rebuild. The 50-file threshold, the structural change detection, the content hash cutoff — those are all correctness guards."

> **Priya**: "Git-based invalidation is the right primary strategy. Mtime is unreliable across file copies, CI environments, and timezone issues. Git is the source of truth for what changed."

---

### ADR-016: Solution-Aware Graph (.sln Parsing)

**Date**: 2026-03-20
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb

#### Context

.NET solutions (.sln files) are the deployment unit — they define which projects ship together. The dependency graph was project-level only, missing the solution boundary context needed for decomposition planning.

#### Decision

**Initiative 9**: Add .sln parsing to the graph engine across five phases:

1. **Solution scanner** (`scatter/scanners/solution_scanner.py:38-88`): Parse .sln files, extract C# project references by GUID, resolve paths, build reverse index
2. **ProjectNode.solutions** field (`scatter/core/graph.py:29`): Each node tracks which solutions it belongs to
3. **Cross-solution coupling metrics** in health analyzer
4. **Solution alignment scoring** in domain clusters
5. **E2e validation tests**

**GUID whitelist**: Only C# project GUIDs are recognized:
- `FAE04EC0-301F-11D3-BF4B-00C04F79EFBC` (Classic C#)
- `9A19103F-16F7-4668-BE54-9A1E7A4F7556` (SDK-style C#)

#### Rationale

- **Deployment boundary context**: A project referenced by 3 solutions has a different risk profile than one in a single solution.
- **Extraction feasibility**: Domain clusters that align with solution boundaries are easier to extract than those that cross them.
- **Reverse index** (`Dict[project_stem, List[SolutionInfo]]`): O(1) lookup of solutions containing a project, essential for pipeline mapping.

#### Verification

Solution scanner at `scatter/scanners/solution_scanner.py:38-88`. ProjectNode.solutions at `scatter/core/graph.py:29`. GUID filtering at solution_scanner.py. Reverse index at solution_scanner.py:102-133. E2e tests at `tests/unit/test_e2e_solution_graph.py`.

> **Priya**: "Solution boundaries are the real architectural boundary in .NET, not project boundaries. Two projects in the same solution are coupled by deployment even if they have no code dependency. This closes a major gap in the graph model."

---

### ADR-017: SOW-to-Blast-Radius Pipeline

**Date**: 2026-03-19
**Status**: Active
**Deciders**: Priya Chandrasekaran, Marcus Webb, Fatima Al-Rashidi (consulted)

#### Context

Engineering leadership needs blast radius estimates from plain-English work requests (Statements of Work, CSEs). The existing CLI modes require technical inputs (branch names, .csproj paths). Leaders don't think in .csproj paths — they think in feature descriptions.

#### Decision

**Impact analysis pipeline** (`scatter/analyzers/impact_analyzer.py:46-100+`):

1. **Parse SOW text** via LLM → `List[AnalysisTarget]` with type, name, confidence, match_evidence
2. **Resolve targets** against codebase index for accurate identification
3. **Find consumers** for each target (direct + transitive via BFS, configurable max_depth)
4. **AI enrichment**: Risk assessment (LOW/MEDIUM/HIGH/CRITICAL), coupling narrative, complexity estimate
5. **Report generation**: Impact narrative (manager-friendly), markdown tables, observations

**Ambiguity classification** (`scatter/analyzers/impact_analyzer.py:26-43`):
- **clear**: ≤5 targets, avg confidence ≥ 0.7
- **moderate**: 6-10 targets OR avg confidence 0.4-0.7
- **vague**: >10 targets OR avg confidence < 0.4

**Eight AI task types** defined at `scatter/ai/base.py:20-28`.

#### Rationale

- **The differentiator**: "Natural language → operational blast radius → pipeline-aware risk report" is what Scatter does that no other tool does (per leadership review, `docs/LEADERSHIP_DESIGN_REVIEW.md:9-15`).
- **Ambiguity signaling**: When the SOW is vague, the tool says so instead of guessing. This builds trust with leadership.
- **Transitive tracing**: Direct consumers aren't the full blast radius. BFS with configurable depth finds indirect impact.

#### Verification

Impact analyzer at `scatter/analyzers/impact_analyzer.py`. AnalysisTarget model at `scatter/core/models.py:91-102`. ImpactReport at `scatter/core/models.py:143-155`. AI task types at `scatter/ai/base.py:20-28`. E2e tests at `tests/unit/test_e2e_sow_impact.py` (22 tests).

> **Marcus**: "This is the feature that justifies Scatter's existence to leadership. Every other mode is a developer tool. This one is a planning tool. If we only ship one thing next quarter, it should be hardening this pipeline against real SOWs."

> **Priya**: "The ambiguity classification is subtle but critical. A tool that confidently returns wrong results is worse than one that says 'I'm not sure about these targets.' The three-tier confidence system gives leadership the signal they need to request clarification."

---

### ADR-018: Layered Configuration with Five Precedence Levels

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Tomás Herrera, Marcus Webb

#### Context

Scatter needs configuration for AI credentials, graph behavior, DB scanning options, search patterns, and multiprocessing tuning. Different users, repos, and CI environments have different needs.

#### Decision

Five-layer precedence system (`scatter/config.py:1-9`):

1. **CLI flags** (highest) — immediate override
2. **Repo-level** `.scatter.yaml` — shared team config
3. **User-level** `~/.scatter/config.yaml` — personal preferences
4. **Environment variables** — CI/CD secrets (`GOOGLE_API_KEY`, `WEX_AI_API_KEY`)
5. **Hardcoded defaults** (lowest) — dataclass defaults

Config sections: `ai`, `graph`, `db`, `search`, `multiprocessing`.
Dot-notation keys for nested updates (e.g., `"ai.credentials.gemini.api_key"`).

#### Rationale

- **Standard pattern**: Matches how git, npm, and Docker handle layered config.
- **CI-friendly**: Environment variables for secrets, repo YAML for team settings.
- **No config required**: Hardcoded defaults work out of the box. Config is entirely optional.

#### Verification

Config module at `scatter/config.py:1-225`. AIConfig defaults at line 21-26. Precedence order documented in module docstring at lines 1-9.

> **Tomás**: "Five layers is the maximum before it becomes a debugging nightmare. This is the standard pattern. Don't add a sixth."

---

### ADR-019: Protocol-Based AI Provider Abstraction

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Priya Chandrasekaran

#### Context

Multiple AI providers (Gemini, WEX internal) need to implement the same interface for summarization, symbol extraction, and risk assessment. Classic inheritance (ABC) or structural subtyping (Protocol)?

#### Decision

`@runtime_checkable` Protocol at `scatter/ai/base.py:39-55`:

```python
@runtime_checkable
class AIProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def max_context_size(self) -> int: ...
    def analyze(self, prompt, context, task_type) -> AnalysisResult: ...
    def supports(self, task_type) -> bool: ...
    def estimate_tokens(self, context) -> int: ...
    def extract_affected_symbols(self, file_content, diff_text, file_path) -> Optional[Set[str]]: ...
```

**AIRouter** (`scatter/ai/router.py`) lazy-initializes providers on first use. Task-specific overrides via `config.ai.task_overrides`.

#### Rationale

- **Structural subtyping**: Providers don't inherit from a base class. They just implement the methods. Adding a new provider requires no imports from the AI module.
- **`runtime_checkable`**: Enables `isinstance(provider, AIProvider)` checks without requiring inheritance.
- **`supports()` method**: Different providers support different task types. The router queries capability before dispatch.
- **Lazy initialization**: Providers aren't created until first API call. No startup cost for runs that don't use AI.

#### Verification

Protocol at `scatter/ai/base.py:39-55`. GeminiProvider and WexProvider both implement the protocol without inheriting. Router at `scatter/ai/router.py:10-108`.

> **Priya**: "Protocol over ABC. The providers are in different packages, potentially different repositories in the future. Structural subtyping means the interface is defined by usage, not by inheritance. That's the right coupling direction."

---

### ADR-020: Tarjan's SCC for Cycle Detection

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Devon Park

#### Context

Circular dependencies in the .NET graph prevent clean extraction. The tool needs to detect all cycles efficiently.

#### Decision

Tarjan's Strongly Connected Components algorithm at `scatter/analyzers/coupling_analyzer.py:100+`. O(V+E) time complexity.

Output: `CycleGroup` dataclass with `projects` (list of names in SCC), `shortest_cycle` (representative path), `edge_count` (internal edges).

#### Rationale

- **O(V+E)**: Linear in graph size. No reason to use anything slower.
- **Complete**: Finds all SCCs, not just one cycle. A project can participate in multiple overlapping cycles — Tarjan's reports them all as one SCC.
- **Standard algorithm**: Well-understood, well-tested, no edge cases to worry about.

#### Verification

Tarjan's implementation confirmed at `scatter/analyzers/coupling_analyzer.py:100+`. CycleGroup dataclass in same module. Unit tests at `tests/unit/test_coupling.py`.

> **Devon**: "Tarjan's. There's no reason to use anything else. It's O(V+E), it finds all SCCs, and it's been correct since 1972."

---

### ADR-021: Domain Clustering via Connected Components + Label Propagation

**Date**: 2026-03-04
**Status**: Active
**Deciders**: Priya Chandrasekaran, Devon Park

#### Context

Teams want to identify natural domain boundaries in the dependency graph for microservice extraction planning. The clustering needs to work without prior knowledge of domain assignments.

#### Decision

Two-level algorithm at `scatter/analyzers/domain_analyzer.py:44-93`:

1. **Level 1**: Connected components (edges treated as undirected). Finds isolated subgraphs.
2. **Level 2**: Label propagation for large components (>20 projects). Iteratively assigns each node to the label most common among its weighted neighbors.

**Feasibility scoring** (`scatter/analyzers/domain_analyzer.py:17-22`):
```python
FEASIBILITY_WEIGHTS = {
    "cross_boundary_penalty": 0.40,
    "shared_db_penalty": 0.25,
    "cycle_penalty": 0.20,
    "api_surface_penalty": 0.15,
}
```

Labels: EASY / MODERATE / HARD based on weighted penalty sum.

#### Rationale

- **Connected components first**: Cheap O(V+E), handles the easy case of disjoint subgraphs.
- **Label propagation for large components**: No predefined k (unlike k-means). Discovers natural community structure from edge weights. Converges quickly (typically 3-5 iterations).
- **Threshold of 20**: Components under 20 projects are already small enough to reason about. Label propagation adds value only for large, tangled components.
- **Feasibility scoring**: Not just "here are the clusters" but "here's how hard each one would be to extract." Actionable for planning.

#### Verification

Connected components at `scatter/analyzers/domain_analyzer.py:44-60`. Label propagation at lines 60-93. Threshold of 20 confirmed. Feasibility weights at lines 17-22. Weight matrix optimization (ADR-027) confirmed in Initiative 12 work.

> **Priya**: "The feasibility scoring is what makes this useful for leadership. Clusters without feasibility labels are just a picture. Clusters with EASY/MODERATE/HARD labels are a roadmap."

> **Devon**: "Label propagation converges in 3-5 iterations for our graph sizes. At 800 projects it was the second-most expensive stage (after type extraction). The weight matrix optimization in Initiative 12 brought it from 21 seconds to under 1 second."

---

### ADR-022: ConsumerResult Dataclass Over Untyped Dicts

**Date**: 2026-03-21
**Status**: Active
**Deciders**: Anya Kowalski, Tomás Herrera

#### Context

Consumer detection results were passed as `Dict[str, Any]` — no type safety, no IDE autocomplete, easy to misspell keys, impossible to know the schema without reading the code.

#### Decision

**Initiative 7 Phase 1**: Replace all untyped result dicts with `ConsumerResult` dataclass at `scatter/core/models.py:62-85`:

```python
@dataclass
class ConsumerResult:
    target_project_name: str
    consumer_project_name: str
    triggering_type: str
    coupling_score: Optional[float] = None
    fan_in: Optional[int] = None
    fan_out: Optional[int] = None
    in_cycle: Optional[bool] = None
    # ... additional enrichment fields
```

#### Rationale

- **Type safety**: mypy catches misspelled fields at lint time, not at runtime.
- **IDE support**: Autocomplete and go-to-definition work.
- **Schema documentation**: The dataclass IS the schema. No separate documentation to keep in sync.
- **Backward compatibility**: `v1_bridge.py` converts between legacy dicts and dataclass instances.

#### Verification

ConsumerResult at `scatter/core/models.py:62-85`. V1 bridge at `scatter/compat/v1_bridge.py`. Mypy passes clean (`d7b05fe` fixed all 77 errors).

> **Anya**: "This should have been day-one, but better late than never. The untyped dicts were the single biggest source of bugs in the consumer pipeline — silent `KeyError`s that only surfaced at runtime."

> **Tomás**: "A dataclass with Optional fields. Not a TypedDict, not a Pydantic model, not a proto. The simplest thing that gives us type safety. Don't overcomplicate it."

---

### ADR-023: uv as Package Manager, Hatchling as Build Backend

**Date**: 2026-03-21
**Status**: Active
**Deciders**: Tomás Herrera, Kai Brennan (consulted)

#### Context

The project used manual `venv` + `pip install -r requirements.txt`. Dependency resolution was slow, lockfiles were absent, and the build system was ad hoc.

#### Decision

**Initiative 8**: Replace with `uv` (package manager) + `hatchling` (build backend).

- `pyproject.toml` as single source of truth (`pyproject.toml:1-73`)
- `uv sync` creates `.venv` and installs all dependencies
- `uv run pytest` executes in the managed environment
- Hatchling builds the wheel with `packages = ["scatter"]`
- `scatter` entry point at `scatter.__main__:main`

#### Rationale

- **uv**: 10-100x faster than pip for dependency resolution. Written in Rust. Handles lockfiles natively.
- **Hatchling**: Minimal build backend. No plugin ecosystem to learn. Just works with pyproject.toml.
- **Single file**: No more `requirements.txt`, `setup.py`, `setup.cfg`. Everything in `pyproject.toml`.

#### Verification

Build system at `pyproject.toml:1-3`. Entry point at line 20. `uv sync` confirmed as install command in `CLAUDE.md`. CI workflow uses `uv` (`df735f2`).

> **Tomás**: "uv. It's fast, it's correct, it handles lockfiles. Stop discussing package managers."

---

### ADR-024: Test Architecture: Unit / Integration / E2E

**Date**: 2026-03-24
**Status**: Active
**Deciders**: Anya Kowalski, Marcus Webb

#### Context

Tests were initially in a flat `tests/` directory with no clear separation between fast unit tests and slower integration/e2e tests.

#### Decision

Three-tier structure under `tests/`:

```
tests/
├── conftest.py                          # Shared fixtures (factory pattern)
├── unit/                                # Fast, isolated, no filesystem
│   ├── test_cli_parser.py
│   ├── test_config.py
│   ├── test_graph.py
│   ├── test_coupling.py
│   ├── test_domain.py
│   ├── test_type_extraction.py
│   ├── test_filter_pipeline.py
│   ├── test_e2e_cli.py                  # CLI e2e (runs scatter against sample projects)
│   ├── test_e2e_sow_impact.py           # SOW e2e (22 tests)
│   └── ...
└── integration/                         # Multi-module, filesystem-dependent
    └── test_multiprocessing_phase1.py
```

**Fixtures** (`tests/conftest.py`): Factory functions (`make_mode_context()`, `make_consumer_result()`) with overridable defaults.

**Markers**: `@pytest.mark.integration` for slow tests.

**Coverage target**: 70% (`pyproject.toml:72`).

#### Rationale

- **Fast feedback**: `pytest tests/unit/` runs in seconds. CI runs everything.
- **Factory fixtures**: Each test specifies only what it cares about. Defaults handle the rest. No fragile global fixtures.
- **E2e in unit/**: CLI e2e tests run against the in-repo sample projects. They're fast (no network, no DB) but exercise the full pipeline.
- **70% coverage floor**: High enough to catch regressions, low enough to not incentivize meaningless tests.

#### Verification

Test structure confirmed in filesystem. Conftest fixtures at `tests/conftest.py` (67 lines). Markers at `pyproject.toml:62-64`. Coverage at `pyproject.toml:72`. 816+ tests pass (`docs/LEADERSHIP_DESIGN_REVIEW.md:5`).

> **Anya**: "The factory fixtures are the key design choice. `make_mode_context(branch_name='feature/foo')` is readable, overridable, and isolated. Compare to a global `@pytest.fixture` that returns a pre-built object — you can't customize it per test without copy-paste."

> **Marcus**: "70% coverage is pragmatic. 90% sounds better until you're writing tests for `__repr__` methods to hit the number. 70% catches the real regressions."

---

### ADR-025: Ruff + mypy + pytest CI Pipeline

**Date**: 2026-03-21
**Status**: Active
**Deciders**: Anya Kowalski, Kai Brennan (consulted)

#### Context

No CI existed. Code quality was enforced by convention only.

#### Decision

GitHub Actions workflow with three parallel jobs:

1. **Test matrix**: pytest across Python 3.10, 3.11, 3.12
2. **Lint**: `ruff check` + `ruff format --check`
3. **Type check**: `mypy scatter/`

Ruff configuration at `pyproject.toml:35-50`:
- Line length: 100
- Select: E, F, W rules
- Ignore: E501 (long strings OK), E741 (ambiguous variable names)
- Format: double quotes
- Per-file: F401 allowed in `__init__.py` (barrel imports)

mypy: Python 3.11, `warn_return_any=true`, `ignore_missing_imports=true`.

Local CI check: `scripts/ci_check.sh` runs all three locally before push.

#### Verification

CI workflow at `.github/workflows/`. Ruff config at `pyproject.toml:35-50`. mypy config at `pyproject.toml:52-56`. Local script at `scripts/ci_check.sh`. 77 mypy errors fixed in `d7b05fe`.

> **Anya**: "Three parallel jobs. Tests don't wait for lint. Lint doesn't wait for type check. Total CI time is the slowest job, not the sum. That's basic CI design but I've seen teams get it wrong."

---

### ADR-026: Six Output Formats with Pluggable Reporters

**Date**: 2026-03-16
**Status**: Active
**Deciders**: Marcus Webb, Sam Nguyen (consulted)

#### Context

Different consumers need different formats: humans read consoles, CI pipelines parse JSON, spreadsheet users want CSV, documentation needs markdown, architects want diagrams.

#### Decision

Six output formats in `scatter/reports/`:

| Format | File | Consumer |
|--------|------|---------|
| `console` | `console_reporter.py` | Human terminal output with filter diagnostics |
| `json` | `json_reporter.py` | CI pipelines, programmatic consumers |
| `csv` | `csv_reporter.py` | Spreadsheet import, data analysis |
| `markdown` | `markdown_reporter.py` | GitHub PR comments, documentation |
| `mermaid` | `graph_reporter.py` | Dependency diagrams |
| `pipelines` | `pipeline_reporter.py` | Pipe-friendly list for CI/CD |

Selected via `--output-format`. Default: `console`.

#### Rationale

- **Pluggable**: Each reporter is a standalone module. Adding a new format is a new file, not a modification.
- **Separation**: Reporters know about rendering. They don't know about analysis. Analysis results are passed as typed dataclasses.
- **Mermaid**: Chosen over Graphviz/DOT because Mermaid renders natively in GitHub markdown, Confluence, and most documentation tools. No extra toolchain required.

#### Verification

All six reporter modules confirmed in `scatter/reports/`. `--output-format` flag at `scatter/cli_parser.py`. Mermaid support added in `1582263`.

> **Marcus**: "Mermaid over Graphviz. The diagram renders in a GitHub PR comment without installing anything. That's the whole value proposition — the graph becomes visible in the workflow, not in a separate tool."

---

### ADR-027: Threaded Type Extraction and Identifier Caching

**Date**: 2026-03-23
**Status**: Active
**Deciders**: Devon Park, Tomás Herrera

#### Context

**Initiative 12** (Performance at scale) benchmarked against 800 projects / 30K files. Three remaining bottlenecks:
1. Type extraction (sequential file reading + regex)
2. Label propagation (O(N^2) neighbor lookups)
3. Comment stripping (per-character Python loop)

#### Decision

Three optimizations shipped across Phases 1-3:

**Phase 1**: Identifier cache — precompute `set(re.findall(r'[A-Za-z_]\w*', content))` once per file, reuse across all type-usage checks. Reachable-set scoping — only check identifiers against types declared in reachable projects (not all known types).

**Phase 2**: Dict-based cs_mapping (replacing list scans), content hash passthrough (skip re-extraction on unchanged files), label propagation weight matrix (precompute neighbor weights, eliminating 600K `get_edges_between()` calls).

**Phase 3**: Threaded type extraction using `ThreadPoolExecutor` for file I/O (reads are I/O-bound, not CPU-bound). Optional `tracemalloc` (off by default after discovering it inflated timing by 5x).

#### Results

| Scale | Before Init 12 | After Init 12 |
|-------|----------------|---------------|
| 250 projects | ~10s | 2.6s |
| 800 projects / 30K files | ~130s | 38.7s |

#### Verification

Identifier cache and reachable-set scoping in `3b25a05`. Weight matrix and dict-based mapping in `183b4e7`. Threaded extraction and tracemalloc fix in `986475d`. Benchmark results in `docs/XLARGE_BENCHMARK_RESULTS.md`.

> **Devon**: "The weight matrix was a 20x improvement for 20 lines of code. Building the neighbor lookup dict once instead of calling `get_edges_between()` 600K times per iteration. Classic 'build the right data structure' win."

> **Tomás**: "ThreadPoolExecutor for file reads, ProcessPoolExecutor for CPU work. Threads for I/O, processes for compute. Don't mix them up."

---

## Appendix A: Chronological Timeline

| Date | Commit | Decision |
|------|--------|----------|
| 2025-05-04 | `1016156` | Project inception. ADR-001 (regex extraction), ADR-002 (three modes), ADR-003 (filter pipeline) |
| 2025-05-06 | `b93ac7b` | ADR-004 (Gemini AI provider) |
| 2025-10-11 | `3e26178` | ADR-005 (multiprocessing) |
| 2026-02-16 | `3dca5c0` | ADR-006 (per-worker directory cache) |
| 2026-03-03 | `4be9e2d` | ADR-007 (sample .NET projects) |
| 2026-03-04 | `bff0075` | ADR-008 (hybrid git extraction) |
| 2026-03-04 | `42f2f63` | ADR-009 (package decomposition), ADR-010 (pure data + functions), ADR-011 (edge types), ADR-018 (config), ADR-019 (AI protocol), ADR-020 (Tarjan's), ADR-021 (clustering) |
| 2026-03-16 | `b9fe302` | ADR-013 (transparent graph), ADR-014 (inverted index), ADR-015 (cache v2), ADR-026 (output formats) |
| 2026-03-17 | `2776ea8` | ADR-012 (five-mode CLI) |
| 2026-03-19 | `a9047d8` | ADR-017 (SOW pipeline) |
| 2026-03-20 | `c4e4453` | ADR-016 (solution-aware graph) |
| 2026-03-21 | `477ccbf` | ADR-022 (ConsumerResult dataclass) |
| 2026-03-21 | `539c232` | ADR-023 (uv + hatchling) |
| 2026-03-21 | `df735f2` | ADR-025 (CI pipeline) |
| 2026-03-23 | `3b25a05` | ADR-027 (perf optimizations) |
| 2026-03-24 | `44e032a` | ADR-024 (test architecture) |

---

## Appendix B: Key File Reference

| File | Purpose | ADRs |
|------|---------|------|
| `scatter/core/graph.py` | DependencyGraph, ProjectNode, DependencyEdge | 010, 011, 016 |
| `scatter/core/models.py` | ConsumerResult, FilterPipeline, ImpactReport, constants | 001, 003, 005, 022 |
| `scatter/core/parallel.py` | ProcessPool workers, chunking | 005, 006 |
| `scatter/analyzers/consumer_analyzer.py` | Filter pipeline, graph-accelerated lookup | 003, 013 |
| `scatter/analyzers/coupling_analyzer.py` | Coupling weights, Tarjan's SCC, metrics | 010, 011, 020 |
| `scatter/analyzers/domain_analyzer.py` | Clustering, feasibility scoring | 021 |
| `scatter/analyzers/graph_builder.py` | Single-pass graph construction, inverted index | 014 |
| `scatter/analyzers/impact_analyzer.py` | SOW → blast radius pipeline | 017 |
| `scatter/analyzers/git_analyzer.py` | Branch analysis, hybrid LLM extraction | 008 |
| `scatter/ai/base.py` | AIProvider Protocol, task types | 004, 019 |
| `scatter/ai/router.py` | Lazy provider factory | 019 |
| `scatter/store/graph_cache.py` | Cache v2, invalidation | 015 |
| `scatter/store/graph_patcher.py` | Incremental patching, safety valves | 015 |
| `scatter/scanners/solution_scanner.py` | .sln parsing, reverse index | 016 |
| `scatter/config.py` | Five-layer configuration | 018 |
| `scatter/cli_parser.py` | Argparse, five modes | 002, 012 |
| `scatter/reports/*.py` | Six output formatters | 026 |
| `pyproject.toml` | Build system, tooling config | 023, 024, 025 |

---

## Appendix C: Reviewers & Signatures

This document was reviewed against the codebase at commit `c228c53` (2026-03-24, branch `main`).

| Reviewer | Focus | Disposition |
|----------|-------|-------------|
| Priya Chandrasekaran | Architecture, module boundaries, domain modeling | Approved — "The decision record accurately reflects the architecture. The dependency arrows point the right direction. My one concern is that ADR-008 (hybrid LLM) introduces non-determinism into a pipeline that's otherwise reproducible — keep the regex default." |
| Marcus Webb | Performance claims, API design, pragmatism | Approved — "Every performance number in here is backed by a benchmark. The SOW pipeline (ADR-017) is the most important feature for the tool's survival. Protect it." |
| Tomás Herrera | Scalability, minimalism | Approved — "27 ADRs for ~11K lines of code. That's a decision every 400 lines. The decisions are justified — none are premature abstractions. The inverted index (ADR-014) is the cleanest win in the document." |
| Anya Kowalski | Testing, CI, correctness | Approved — "Safety valves in ADR-015, filter pipeline observability in ADR-003, factory fixtures in ADR-024. The testing story is solid. 70% coverage floor is the right target." |
| Devon Park | Performance, algorithms | Approved — "The performance ADRs (014, 015, 027) have measured results, not estimates. Tarjan's for cycles, inverted index for type matching, weight matrix for label propagation — all algorithmically correct choices." |

---

*Document generated 2026-03-25. Source of truth: the code, not this document. If this ADR conflicts with what's in the repository, the repository wins.*
