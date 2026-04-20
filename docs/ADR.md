# Architecture Decision Records

The decisions that shape Scatter, in the order they were made.

---

## ADR-001: Regex for Type Extraction, Not Roslyn

The obvious move for parsing C# is Roslyn. Complete AST, handles every edge case, Microsoft maintains it. It also requires the .NET SDK (~200MB), needs compilable source with resolved NuGet packages, and doesn't run on a Mac without gymnastics.

Scatter runs in CI runners, on developer laptops, against repos that might not even build cleanly. Roslyn is a non-starter for that.

So: compiled regex patterns. `TYPE_DECLARATION_PATTERN` matches classes, structs, interfaces, enums, and records. `DELEGATE_DECLARATION_PATTERN` handles delegates. Both run per-line with `re.MULTILINE`, matching access modifiers, keyword combinations, and type names with a lookahead for braces, inheritance, or constraints.

The tradeoff is real. Regex can't tell a type declaration in code from one inside a comment or a string literal. It also can't distinguish between a class whose body changed and one that happens to share a file with a change. An optional tree-sitter validation layer handles the first problem. LLM diff analysis handles the second.

Zero dependencies. Works on broken builds. Works on a Mac. Good enough to ship, with a clear path to precision when it matters.

---

## ADR-002: One CLI, Multiple Modes

Scatter answers different questions: "what breaks if I merge this branch?", "what consumes this project?", "what references this stored procedure?", "what's the architecture health?", "what's the blast radius of this work request?", "what's the risk of this PR?" Each has different inputs and a different entry path. But they all converge on the same core: find consumers, enrich with graph data, format output.

One CLI entry point. Mutually exclusive mode flags: `--branch-name`, `--target-project`, `--stored-procedure`, `--graph`, `--sow`/`--sow-file`, `--pr-risk`.

One tool, one install. Shared infrastructure underneath. Each new mode extends the pattern instead of becoming a separate binary that drifts out of sync with the others.

---

## ADR-003: Five-Stage Consumer Detection Pipeline

The naive approach — scan every `.csproj` and `.cs` file for references to a target — is O(P * F) and produces garbage. A project might reference a namespace without actually using any types from it. A `.cs` file might import a namespace but only use an unrelated class.

Consumer detection works as a filter funnel. Each stage narrows the candidate set:

1. **Discovery** — find all `.csproj` files in scope
2. **Project Reference** — parse XML for `<ProjectReference>` pointing at the target
3. **Namespace** — scan `.cs` files for matching `using` statements
4. **Class** — grep for the target type name in surviving files
5. **Method** — optionally grep for a specific method name

A `FilterPipeline` records counts at each stage. The output looks like: `142 → 8 project refs → 5 namespace → 3 class match`. That arrow chain is one of the most useful things in the tool — it shows you exactly why results are narrow or wide, and it's the first thing people look at when the numbers seem off.

When the dependency graph is available, stages 1-2 use graph reverse lookups instead of filesystem scanning. Same results, fraction of the time.

---

## ADR-004: Parallel File Discovery

Enterprise .NET codebases have thousands of files across deep directory trees. Sequential scanning is the bottleneck — it's I/O-bound, not CPU-bound.

`multiprocessing.Pool` with adaptive scaling:
- Under 200 files: 4 workers (process creation overhead eats the savings)
- 200-999 files: 8 workers
- 1000+ files: up to `--max-workers` (default 14, cap 32)

Three parallelized operations: file pattern discovery, `.csproj` XML parsing, and `.cs` content analysis. Each has its own chunk size because the optimal batch size for "find files matching a glob" is different from "parse XML and extract references."

Measured result: 5-10x speedup at 500+ projects. The adaptive scaling matters — spinning up 14 workers to process 30 files in the sample projects is slower than doing it sequentially.

---

## ADR-005: LLM-Assisted Git Diff Analysis

In git branch mode, regex extraction has a fundamental problem. You touch one line inside `PortalDataService`, and Scatter reports all five classes declared in that file as changed. That's a 5x false positive rate on a single file.

`--enable-hybrid-git` sends each changed file plus its unified diff to Gemini. The LLM identifies which types actually have their body or signature modified. On a typical PR touching 15 files across 3 projects, regex reports ~40 types. Hybrid reports ~12. Same consumers found for the types it does report — the difference is in the starting set.

The non-negotiable: if the API call fails for any reason — bad key, rate limit, network timeout, hallucinated response — fall back silently to regex with a warning logged. This is safe to enable in CI because it degrades, never breaks. Without the flag, behavior is identical to pure regex. The feature is strictly additive.

The cost is 1-3 seconds per file (API round-trip) and a Google API key.

---

## ADR-006: Decomposing the Monolith

The original `scatter.py` was 2,357 lines and 28 functions. Multiprocessing, type extraction, git operations, project analysis, AI integration, result processing, consumer analysis, sproc analysis, CLI handling — all in one file. It works, but adding features means scrolling through 2,000 lines to find the right spot, and testing means importing the entire world.

Decomposed into a package:

```
scatter/
  core/       — models, parallel infrastructure, graph, patterns
  scanners/   — file, project, type, sproc, solution scanners
  analyzers/  — consumer, coupling, domain, git, graph, health, impact, risk
  ai/         — provider protocol, router, task modules
  reports/    — console, CSV, JSON, markdown, mermaid, pipeline reporters
  store/      — graph cache, incremental patcher
  compat/     — v1 bridge (legacy result processing)
  modes/      — per-mode entry points
```

The import graph is acyclic: core → scanners → analyzers → ai → reports → modes → CLI. Each module has one job and can be tested without importing the others.

`compat/v1_bridge.py` exists because this refactoring happens incrementally. It bridges old result processing patterns. It's tech debt I'm aware of.

---

## ADR-007: AI Provider Protocol

Scatter uses LLMs for five things: consumer summarization, hybrid git extraction, SOW parsing, risk narratives, and coupling analysis. These have different quality requirements. Summarization can use a cheap model. SOW parsing needs a capable one.

An `AIProvider` protocol defines the interface. An `AIRouter` picks the right provider per task type. Providers are lazy-initialized and cached. An `AIBudget` caps total API calls per run so CI doesn't produce a surprise bill.

Currently Gemini only. The protocol means adding another provider is implementing an interface, not modifying call sites.

The important bit: when no AI provider is configured, every AI feature degrades gracefully. Core analysis — consumer detection, graph building, coupling metrics, cycle detection — never requires an API key.

---

## ADR-008: Layered YAML Configuration

Scatter has ~20 tunable parameters. Passing them all via CLI flags every time is painful. Teams sharing a repo need shared defaults.

Five layers, highest wins:

1. CLI flags
2. `.scatter.yaml` in the repo root (committed, shared with the team)
3. `~/.scatter/config.yaml` (user-level — typically holds API keys)
4. Environment variables (`GOOGLE_API_KEY`, etc.)
5. Built-in defaults

Missing config files are silently ignored. Malformed YAML logs a warning and uses defaults. No config file is ever required. Scatter works fine with zero configuration — the layers exist for convenience, not ceremony.

---

## ADR-009: The Graph Is a Data Structure, Not a God Object

Scatter's dependency graph powers coupling analysis, cycle detection, domain clustering, consumer acceleration, and health observations. The temptation is to put all those methods on the graph class.

`DependencyGraph` is a pure data structure. Mutation, query, traversal, serialization — that's it. Every analysis algorithm is a standalone free function in a separate module that takes a graph as input.

Four per-node edge indexes: `_outgoing`, `_incoming`, `_forward`, `_reverse`. That's more memory than a single adjacency list, but cycle detection and consumer lookups need reverse traversal constantly. O(1) reverse lookup is worth the memory.

Evidence on edges is capped at 10 entries with an `evidence_total` count. Without the cap, serializing a graph from a large monolith produces unbounded JSON. With it, you get enough evidence to understand the edge, and a count that tells you how much more there is.

The payoff: no circular imports between the graph and its analyzers. Each analyzer can be tested with a three-node synthetic graph. The graph class doesn't change despite constant additions to the analysis layer above it.

---

## ADR-010: Not All Dependencies Are Created Equal

A `<ProjectReference>` is a hard compile-time dependency. If you break the target, the consumer doesn't build. A shared stored procedure is nearly as hard — it's shared mutable state with no compile-time check. A `using` statement is softer. A single type reference is the weakest signal.

Four edge types with weights that reflect this:

| Edge Type | Weight | What it means |
|-----------|--------|---------------|
| `project_reference` | 1.0 | You literally can't build without this |
| `sproc_shared` | 0.8 | Shared database state — no compiler to save you |
| `namespace_usage` | 0.5 | `using` statement — might use one type, might use twenty |
| `type_usage` | 0.3 | References a specific type — could be an enum, could be a core service |

Weights are overridable in `.scatter.yaml`. Teams that care most about database coupling can crank `sproc_shared` up. Teams in a clean microservice world can drop it to zero.

---

## ADR-011: Tarjan's for Cycle Detection

Circular dependencies in .NET create build-order violations. If A references B and B references A, you can't extract either into a separate deployment without breaking the other. Finding these is non-negotiable.

DFS back-edge detection finds *some* cycles but misses complex multi-project SCCs where A→B→C→A and A→D→C exist simultaneously.

Tarjan's strongly connected components algorithm finds *all* of them. O(N+E) time, O(N) space. The implementation is iterative (explicit call stack) because Python's recursion limit of ~1000 blows up on a large graph.

Default: only detect cycles along `project_reference` edges. Namespace and type usage cycles are common and benign — half the projects in a monolith share namespace imports. Build-order cycles are the ones that actually block extraction.

For each cycle group, Scatter extracts the shortest representative cycle via BFS. "Break the edge between GalaxyWorks.Data and GalaxyWorks.WebPortal" is more useful than "these 15 projects form a cycle."

---

## ADR-012: Git-Based Cache Invalidation

Rebuilding the dependency graph from scratch on every run wastes 1-60 seconds depending on codebase size. A stale cache produces wrong results. The question is how to know when the cache is still good.

`git diff --name-only <cached_hash> HEAD -- '*.csproj' '*.cs'`. If the only changes since the cache was built are README edits, docs, or config files — the cache is fine. If any `.csproj` or `.cs` file changed, invalidate.

Non-git directories fall back to mtime comparison (conservative but correct). `--rebuild-graph` provides an escape hatch when you don't trust the cache.

Cache format v2 stores per-file SHA-256 hashes alongside the graph. The incremental patcher uses content hashing to skip files that look changed (different timestamp) but aren't (same content).

---

## ADR-013: Making Database Coupling Visible

Here's the problem nobody talks about: your DBA changes a stored procedure parameter list, and there's no way to know which C# services just broke. No `<ProjectReference>` points at a stored procedure. The coupling lives in string literals — `"dbo.sp_InsertPortalConfiguration"` buried inside a data access layer somewhere.

Scatter scans `.cs` files for sproc references using configurable patterns: string literals with known prefixes (`sp_`, `usp_`, `proc_`), EF `DbSet<T>` patterns, `DbContext` subclasses, direct SQL patterns (`EXECUTE`, `EXEC`). A comment-stripping preprocessor cuts false positives from commented-out code.

Projects referencing the same stored procedure get `sproc_shared` edges in the graph with a weight of 0.8 — just below a project reference, because shared mutable state is nearly as tight as a compile-time dependency.

The full chain — sproc name to containing class to consumer projects to CI/CD pipelines — is something no other tool in this space does.

---

## ADR-014: Domain Clustering

Architects planning a monolith extraction need to know where the natural service boundaries are. The dependency graph has implicit clusters, but nobody wants to stare at a 500-node graph and squint.

Two-level clustering:

**Level 1: Connected components.** Always runs. Deterministic BFS, O(N+E). Handles the common case where project groups are already cleanly separated. For the sample projects, GalaxyWorks and MyDotNetApp fall into separate components immediately.

**Level 2: Label propagation.** Conditional — only fires for components with more than 20 nodes. Detects sub-communities within a large blob of connected projects. Deterministic: sorted iteration order, alphabetical tie-breaking, max 100 iterations. No randomness, no non-determinism, same input always produces same output.

Each cluster gets an extraction feasibility score from 0.0 (hopelessly entangled) to 1.0 (trivially separable). Four weighted penalties: cross-boundary coupling (0.40), shared DB objects (0.25), circular dependencies (0.20), API surface breadth (0.15). The score maps to a label: easy, moderate, hard, very hard.

It's not a recommendation. It's a starting point for a conversation with data behind it.

---

## ADR-015: Deterministic Health Observations

Raw metrics — fan-in 7, coupling score 12.3, instability 0.15 — require expertise to interpret. Most people look at numbers like that and go "is that bad?"

The health dashboard generates observations from fixed thresholds:

- **stable_core**: fan_in ≥ 5 AND instability ≤ 0.3 → "change carefully, everyone depends on this"
- **high_coupling**: coupling_score ≥ 8.0 → "this project is tangled up with too many things"
- **in_cycle**: project in any SCC → "circular dependency, must break before extraction"
- **low_cohesion_cluster**: high coupling, low cohesion → "this cluster is held together by duct tape"
- **db_hotspot**: sproc shared by 3+ projects → "database coupling hotspot"

No LLM involved. Same graph always produces the same observations. Thresholds are module constants — easy to tune when you have real codebase data to calibrate against.

---

## ADR-016: Typed Consumer Results

Consumer results are `Dict[str, Union[str, Dict, List[str]]]`. Fifty-eight access sites across eight files. Typo in a key name? Silent `None`. Missing a graph enrichment field? Nobody knows until it's in production output.

Replaced with a `ConsumerResult` dataclass. Fourteen fields: nine always-present (target name, path, triggering type, consumer name, path, solutions, pipeline, batch job, file summaries) and five optional graph fields (coupling score, fan-in, fan-out, instability, in-cycle).

No `to_dict()` method. Reporters own their output schema. If JSON wants PascalCase keys and CSV wants snake_case, that's the reporter's job, not the data model's.

The migration touches eight files. All 788 existing tests serve as regression checks. Nothing breaks.

---

## ADR-017: Incremental Graph Patching

At 500 projects, a full graph rebuild takes ~60 seconds. A typical PR touches 5-15 files across 1-3 projects. Rebuilding everything for that is absurd.

Three-step patch:

1. `git diff --name-only` identifies changed `.cs` and `.csproj` files, mapped to affected projects
2. SHA-256 content hash comparison against cached hashes — if the content is identical despite the timestamp changing (rebase, checkout), skip it. This idea comes from Bazel's content-addressable cache.
3. For genuinely changed projects: remove old outgoing edges, re-extract facts from current content, rebuild edges

Safety valve: if more than 50 projects are affected or more than 30% of files changed, do a full rebuild. The incremental path isn't designed for major refactors — it's designed for normal PRs.

Result: a 10-file PR on a 500-project repo goes from ~60 seconds to under 1 second.

---

## ADR-018: Cleaning Up the Reports

The early reporters are a mess. JSON stringifies nested objects instead of preserving native types. Optional fields use empty strings instead of `null`. No metadata — no version, no timestamp, no duration. The console says "done." with no useful summary. CSV has a `ConsumerFileSummaries` column that's a JSON blob inside a CSV cell.

Standardized everything:
- JSON: native types, `null` for absent optionals, metadata block (version, timestamp, duration, CLI args, search scope)
- CSV: semicolons as list delimiters within cells, comment headers showing the filter chain
- Console: per-target consumer counts, coupling score table when graph data is available, the filter arrow chain front and center

Added `scatter/__version__.py` for version tracking. The metadata in JSON output means you can diff reports across Scatter versions and know which version produces which numbers.

---

## ADR-019: Blast Radius as a Tree

Impact analysis displays consumers as a flat list with depth numbers. "MyApp, depth 0. BatchProcessor, depth 1. PortalUI, depth 2." That tells you depth but hides the propagation chain. Which depth-0 consumer exposes BatchProcessor? You have to guess.

`propagation_parent` on `EnrichedConsumer`, tracked during BFS traversal. Renders as a tree:

```
GalaxyWorks.Data  (target)
├── GalaxyWorks.WebPortal       [HIGH]  direct
│   └── GalaxyWorks.BatchProcessor  [MEDIUM]  via WebPortal
├── MyGalaxyConsumerApp         [MEDIUM] direct
└── MyGalaxyConsumerApp2        [LOW]    direct
```

The chain is visible instantly. Risk ratings and pipeline names are inline. JSON includes both a nested `propagation_tree` and the flat `consumers` array — backward compatible, strictly additive.

---

## ADR-020: Markdown Output

Console output doesn't paste well into PRs. JSON requires tooling to read. CSV is for Excel. Teams need something that renders natively in GitHub PRs, Jira, Confluence, and Azure DevOps wikis.

`--output-format markdown`. Three builder functions: one for consumer analysis (grouped targets with tables), one for impact analysis (tree + flat table), one for graph mode (stats, clusters, embedded Mermaid diagram).

Unlike JSON and CSV, markdown doesn't require `--output-file`. Pipe it straight to clipboard: `scatter ... --output-format markdown | pbcopy`. That single workflow — run scatter, pipe to clipboard, paste into PR — is how most people actually use this format.

---

## ADR-021: Solution-Aware Graph

`.sln` files are a human-authored statement: "these projects belong together and ship together." Scatter's graph ignores them entirely without this. That's leaving organizational signal on the table.

Proper `.sln` parsing — whitelisting C# project GUIDs, not substring matching (the old approach matches "Auth.Core" against "MyAuth.Core", which is wrong). `solutions: List[str]` on every `ProjectNode`, populated during graph build, serialized in the cache.

Solution-level metrics: internal edge count, external edge count, cross-solution ratio, bridge project detection (projects appearing in 3+ solutions).

Cluster-solution alignment is computed post-hoc as a diagnostic metric. It deliberately does not influence clustering. The graph topology determines clusters; solution alignment tells you whether the clusters agree with the org chart. When they diverge, that's interesting — it means the code structure and the team structure disagree about where the boundaries are.

Zero new CLI flags. If `.sln` files exist, solutions appear in the output automatically.

---

## ADR-022: The Graph Should Just Work

The graph is powerful but invisible without this. You have to know about `--graph-metrics` to get coupling scores, or `--graph` to get the full analysis. Most users never discover it.

Three changes to make it automatic:

**Auto-load.** If a graph cache exists, load it and enrich results. No flag needed. `--no-graph` for explicit opt-out.

**Graph-accelerated consumer lookup.** Stages 1-2 of the consumer pipeline (discovery + project reference lookup) go through the graph instead of scanning the filesystem. O(degree) reverse index lookup instead of XML parsing. If the target isn't in the graph — maybe it's new, maybe the cache is stale — fall back silently to filesystem. The `FilterStage.source` field records whether each stage uses "filesystem" or "graph" so you can tell which path runs.

**First-run build.** On first run, build the graph as a side effect of normal analysis and cache it. Takes 1-5 seconds depending on codebase size. Every subsequent run gets auto-load and acceleration for free.

Net effect: run Scatter once, pay a few seconds for graph build. Every run after that is faster, with richer output. No flags to remember, no setup to do.

---

## ADR-023: Pipeline Output Format

Release managers don't want a consumer analysis table. They want a list of pipeline names to trigger. One per line, sorted, deduplicated. That's it.

`--output-format pipelines`. Requires `--pipeline-csv` (Scatter warns if it's missing, but doesn't crash). Suppresses all other output to keep stdout clean for piping:

```bash
scatter ... --output-format pipelines | xargs -I {} ./trigger-pipeline.sh {}
```

Works in all modes except graph (graph analysis is about architecture, not deployment).

---

## ADR-024: Codebase Index for SOW Parsing

When you feed a natural language work request to an LLM and ask "which projects does this affect?", the LLM has zero context about what exists in the codebase. It guesses. Sometimes brilliantly. Often wrong — it invents project names that sound plausible but don't match anything.

A compact text index built from the dependency graph: all project names, type declarations, stored procedure names, namespaces, solution membership. ~50KB for a 250-project codebase. Sent alongside the SOW in the LLM prompt.

The LLM picks from a known set instead of guessing. A `match_evidence` field on each target includes the LLM's reasoning for why it's selected. Ambiguity classification (clear / moderate / vague) tells users when to trust the results and when to verify.

Accuracy goes from ~40% on business-domain SOWs to over 80%. When no graph exists, falls back to the original prompt — no regression.

---

## ADR-025: Unified Risk Engine

Risk-relevant data is everywhere. The coupling analyzer knows about fan-in and fan-out. The domain analyzer knows about cluster boundaries. The graph knows about cycles. The DB scanner knows about shared sprocs. Without a unified engine, nothing combines these signals. AI risk assessment works with maybe 20% of available information.

The engine computes seven dimensions, each scored 0.0-1.0:

| Dimension | What it measures |
|-----------|-----------------|
| Structural coupling | How tangled is this project relative to the codebase? |
| Instability | How likely is this project to change? (fan-out / total) |
| Cycle entanglement | Is this project stuck in a circular dependency? |
| Database coupling | Shared sprocs, cross-team DB access |
| Blast radius | How many projects break if this one changes? |
| Domain boundary | Do consumers cross cluster boundaries? |
| Change surface | How many files and types does this PR touch? |

Composite score uses weighted maximum, not average. That's a deliberate choice. If a project is in a dependency cycle (score 0.9) but has low coupling otherwise (score 0.1), the average is 0.5. The max is 0.9. The cycle is the risk. Averaging dilutes it.

Three risk levels: GREEN (< 0.4), YELLOW (0.4-0.7), RED (> 0.7).

Dimensions with missing data return `data_available=False` and are excluded from the composite. They're never scored as zero — zero means "no risk," missing means "we don't know." Reports show what isn't analyzed, not just what is.

Pure functions. Data in, score out. No I/O, no side effects. Every dimension scorer uses piecewise linear interpolation between thresholds — smooth, predictable, testable.

---

## ADR-026: PR Risk Scoring

Engineers merge PRs without seeing cross-project impact. Scatter has the data, but nobody's going to run a CLI tool manually on every PR. The risk information needs to show up at the moment of decision — the PR review.

`--pr-risk` mode produces a risk report for a branch's changes. A GitHub Actions workflow template runs it on every PR and posts a comment with two levels:

**5-second scan:** Risk level badge (GREEN/YELLOW/RED), score, one-line summary. A reviewer glances at this and knows whether to care.

**60-second detail:** Dimensions table, hotspots, changed types, risk factors, affected consumers. All behind `<details>` tags (via `--collapsible`) so it doesn't clutter the PR conversation when risk is low.

Same risk engine that powers interactive use. Same scores, same dimensions, same factors. The only difference is the output goes into a PR comment instead of a terminal.

---

## ADR-027: Splitting the Entry Point

After the package decomposition, `__main__.py` grows back to 1,161 lines. It accumulates parser definition, mode dispatch, graph setup, AI configuration, output routing — classic "main as dumping ground."

Split into three modules:
- `cli_parser.py` (~180 lines) — parser definition, CLI override extraction
- `cli.py` (~450 lines) — mode handlers, output dispatch, shared helpers
- `__main__.py` (~250 lines) — entry point, validation, setup, dispatch

Mode handlers take a `ModeContext` dataclass and return a `ModeResult`. No more passing raw `argparse.Namespace` around and hoping the downstream code only reads the attributes it should. `ModeContext` is the contract: these are the resolved, typed fields you get. `ModeResult` is the receipt: these are the results, the filter pipeline, and whether graph enrichment runs.

---

## ADR-028: Tree-Sitter Validation Layer

Regex can't distinguish between a type declaration in real code and one inside a comment or string literal. In a data access layer full of SQL string builders, this produces false positives.

An optional tree-sitter validation layer. `--parser-mode hybrid` in config or CLI. The regex pass runs first (fast, finds candidates), then tree-sitter parses the file into an AST and confirms each match occurs in an actual code position — not a comment, not a string.

Two-pass is faster than AST-only because regex eliminates most non-matches before the heavier parse even runs. Tree-sitter is an optional dependency — core Scatter works without it. Falls back to regex on parse failure. Cache key includes parser mode, so regex and hybrid caches don't collide.

---

## ADR-029: uv for Python Packaging

`pyproject.toml` with hatchling as the build backend. uv as the package manager. `uv sync` creates the virtual environment and installs everything. `pip install .` still works if you don't have uv.

Optional dependency group for pandas — it's only used by the pipeline artifact parser, and requiring it for core analysis is silly.

`.python-version` pins the minimum. `uv.lock` ensures reproducible builds. One command to go from fresh clone to running tool.

---

## ADR-030: Six Output Formats

Different people need different things from the same data:

| Format | `--output-file` required? | Where it runs |
|--------|--------------------------|---------------|
| Console | No | All modes |
| JSON | Yes | All modes |
| CSV | Yes | All modes |
| Markdown | No | All modes |
| Mermaid | No | Graph only |
| Pipelines | No | All except graph |

Each reporter is a standalone module. Adding a format means writing a module and a dispatch branch. Existing reporters are untouched.

JSON and CSV require `--output-file` because dumping a multi-megabyte JSON payload to stdout and accidentally piping it into something is the kind of mistake you only make once. Markdown and console go to stdout by default — that's the workflow (`| pbcopy`, `| less`). Mermaid is graph-only because it produces a diagram, not a consumer list. Pipelines is all-except-graph because graph mode is about architecture, not deployments.

---

## ADR-031: Single-Walk File Discovery

Solution scanning and graph building each walked the same 32,156-directory tree independently. On Docker/WSL2, where every syscall crosses a 9P protocol bridge, that doubled the most expensive operation in the pipeline. Solution scanning also called `Path.resolve()` on every project reference inside every .sln file — ~7,500 filesystem stat calls for pure path normalization.

Combined all file discovery into a single `os.walk` in `__main__.py` that collects `.sln`, `.csproj`, and `.cs` files in one pass. Solution scanner and graph builder receive pre-discovered files via optional parameters, with standalone fallbacks for tests and scripts. Replaced `Path.resolve()` with `os.path.normpath()` in .sln parsing — same stems, zero syscalls.

Result: ~682s → ~311s on the OD monolith via Docker. The full story, including what we tried and what we didn't, is in [ADR_DOCKER_PERFORMANCE.md](ADR_DOCKER_PERFORMANCE.md).
