# Scatter Development Log

---

## What Scatter Does

Scatter is a dependency and risk analysis tool for .NET codebases. Point it at a project in a monolith and it tells you what depends on it, how tightly coupled those consumers are, and which CI/CD pipelines are involved.

The monolith in question has 500+ projects, thousands of C# files, and 20 years of organic growth. Nobody fully understands the dependency graph. Teams merge branches and find out what broke in production. Scatter exists to surface those dependencies before the merge — lightweight static analysis, no Roslyn, no .NET SDK, no compilation required.

It starts as a single question: "if I change this .csproj, who breaks?" And it answers that question by tracing dependency chains through `<ProjectReference>` entries, `using` statements, class/method usage, and stored procedure references. Database coupling is the invisible kind — no project reference points at a stored procedure — so tools that only look at project references miss it entirely.

---

## The Graph Engine

The dependency graph is scatter's core data structure. Everything interesting — coupling metrics, cycle detection, consumer lookup, domain clustering, impact analysis — runs on top of it.

### Single-pass construction

The builder follows a 6-step pipeline where P = number of .csproj files and F = number of .cs files:

1. **Discover files.** A single `os.walk` pass collects .csproj and .cs files, pruning excluded directories (`bin/`, `obj/`, dot-prefixed) during traversal so they're never entered.
2. **Parse each .csproj.** Extract `ProjectReference` includes, `TargetFramework`, `OutputType`, project style (SDK vs legacy).
3. **Build reverse directory index.** Map each .cs file to its parent project.
4. **Extract per-file facts.** Read each .cs file once, extract type declarations, sproc references, namespace usages. `ThreadPoolExecutor` parallelizes the I/O.
5. **Build edges.** Four types: `project_reference` (1.0 weight — hard compile-time), `sproc_shared` (0.8 — shared DB state), `namespace_usage` (0.5 — soft signal), `type_usage` (0.3 — softest). Weights are configurable.
6. **(Optional) DB dependency scan.** Stored procedure calls, `DbSet<T>`, `DbContext`, direct SQL, connection strings. A comment-stripping preprocessor cuts false positives.

`DependencyGraph` is a pure data structure — mutation, query, traversal, serialization. Every analysis algorithm is a standalone free function. The graph doesn't know about metrics. No god objects.

### Type usage: the inverted index

The original type_usage edge builder ran an O(F x T x S) triple nested loop — for every file, for every known type, scan the entire content with a freshly compiled regex. At 100 projects that's 1,170,320 regex operations. At 250 projects it doesn't finish.

The fix is an inverted index. Read the file once, tokenize into identifiers, intersect with the set of known type names:

```python
identifiers_in_file = set(re.findall(r'[A-Za-z_]\w*', content))
types_found = identifiers_in_file & all_known_type_names
```

One regex pass. One set intersection. The number of known types drops out of the equation. Tested against 15 C# edge cases — identical results to the per-type regex.

A comment stripper runs first to eliminate false positives from commented-out code. And the type-to-project mapping is multi-owner (a type name can exist in multiple projects), fixing a silent data-loss bug where the last writer won.

The alternative approaches that don't work: **mega-regex** (Python's NFA engine doesn't turn alternations into efficient lookups — maybe 5-10x, not 100x) and **Aho-Corasick** (textbook-correct but requires a C extension; the inverted index achieves the same complexity class with zero dependencies).

Result: 100 projects from 172s to 1.7s (101x). 800 projects / 30K files in 25.8s.

### Coupling metrics and cycle detection

`ProjectMetrics` on every node: fan-in, fan-out, instability (fan-out / total), coupling score (weighted sum across edge types), shared DB density. All configurable via `.scatter.yaml`.

Cycle detection uses Tarjan's strongly connected components algorithm. O(N+E), iterative implementation (Python's recursion limit of ~1000 blows up on a large graph). Default: only detect cycles along `project_reference` edges — namespace cycles are common and benign. For each cycle group, BFS extracts the shortest representative cycle. "Break the edge between A and B" is more useful than "these 15 projects form a cycle."

### Domain clustering

Two-level: connected components (always, deterministic BFS) then label propagation (only for components with 20+ nodes, also deterministic — sorted iteration, alphabetical tie-breaking, no randomness). Each cluster gets an extraction feasibility score from 0.0 (hopelessly entangled) to 1.0 (trivially separable). Four weighted penalties: cross-boundary coupling (0.40), shared DB objects (0.25), circular dependencies (0.20), API surface breadth (0.15).

Not a recommendation. A starting point for a conversation with data behind it.

### Health dashboard

Deterministic observations from fixed thresholds: `stable_core` (fan-in >= 5, instability <= 0.3), `high_coupling` (score >= 8.0), `in_cycle`, `low_cohesion_cluster`, `db_hotspot` (sproc shared by 3+ projects). No LLM involved. Same graph always produces the same observations.

### Solution awareness

`.sln` files are a human-authored statement: "these projects belong together and ship together." Scatter parses them with C# project GUID whitelisting (not substring matching — that matches "Auth.Core" against "MyAuth.Core"). `solutions: List[str]` on every `ProjectNode`, populated during graph build, serialized in the cache.

Solution-level metrics: internal edge count, external edge count, cross-solution ratio, bridge project detection (projects appearing in 3+ solutions). Cluster-solution alignment is diagnostic — it deliberately does not influence clustering. When the code structure and the org chart disagree about boundaries, that's interesting.

---

## The Transparent Graph

The graph is powerful but invisible if you need to know about `--graph-metrics`. Three design choices make it automatic:

**Auto-load.** If a graph cache exists, load it and enrich results. No flag needed. `--no-graph` for explicit opt-out.

**Graph-accelerated consumer lookup.** Stages 1-2 of the consumer pipeline (discovery + project reference lookup) use graph reverse indexes instead of scanning the filesystem. O(degree) instead of O(P + F). If the target isn't in the graph, fall back silently. The `FilterStage.source` field records which path ran: `Filter: 250[graph] -> 12 project refs[graph] -> 8 namespace`.

**First-run build.** On first analysis run, build the graph as a side effect of normal analysis and cache it. Every subsequent run gets auto-load and acceleration for free.

### Incremental patching

Rebuilding the whole graph for a 10-file PR is absurd. Three-step patch:

1. `git diff --name-only` identifies changed files, mapped to affected projects
2. SHA-256 content hash comparison — if the content is identical despite the timestamp changing (rebase, checkout), skip it
3. For genuinely changed projects: remove old edges, re-extract facts, rebuild edges

Safety valve: if more than 50 projects or 30% of files changed, full rebuild. The incremental path isn't for major refactors.

| Scenario | 100 projects | 250 projects |
|----------|-------------|-------------|
| 1 file usage-only | ~110x faster | ~954x faster |
| 5 files usage-only | ~95x | ~820x |
| 1 csproj modified | ~122x | ~253x |

Cache format v2 stores per-file SHA-256 hashes and `FileFacts`/`ProjectFacts` alongside the graph. v1 caches auto-upgrade on next full rebuild.

---

## Consumer Detection Pipeline

Five-stage filter funnel. Each stage narrows the candidate set:

1. **Discovery** — find all `.csproj` files in scope (or read them from the graph)
2. **Project Reference** — parse XML for `<ProjectReference>` pointing at the target (or graph reverse lookup)
3. **Namespace** — scan `.cs` files for matching `using` statements
4. **Class** — grep for the target type name in surviving files (optionally AST-confirmed via tree-sitter in hybrid mode)
5. **Method** — optionally grep for a specific method name

A `FilterPipeline` records counts at each stage. The output looks like: `142 -> 8 project refs -> 5 namespace -> 3 class match`. That arrow chain is one of the most useful things in the tool — it shows exactly why results are narrow or wide, and it's the first thing people look at when the numbers seem off.

---

## Multiprocessing

Three parallelized operations with adaptive worker scaling (4 workers under 200 files, 8 under 1000, full workers above):

- **Content analysis**: parallel .cs file scanning for namespace checks, class usage, sproc patterns
- **XML parsing**: parallel .csproj `ProjectReference` checking with per-file error isolation
- **Project mapping**: parallel cs-to-csproj resolution with directory caching

Graph building uses `ThreadPoolExecutor` for file extraction (I/O-bound, GIL released during reads) and sequential aggregation (main thread, CPU-bound set operations).

For small codebases (< 50 projects), sequential is often faster — multiprocessing has a fixed startup cost of ~200ms. The crossover is typically around 80-100 projects.

---

## Risk Engine and PR Scoring

Seven dimensions, each scored 0.0-1.0:

| Dimension | What it measures |
|-----------|-----------------|
| Structural coupling | How tangled is this project? |
| Instability | How likely to change? (fan-out / total) |
| Cycle entanglement | Stuck in a circular dependency? |
| Database coupling | Shared sprocs, cross-team DB access |
| Blast radius | How many projects break? |
| Domain boundary | Do consumers cross cluster boundaries? |
| Change surface | How many files and types does this PR touch? |

Composite uses weighted maximum, not average. If a project is in a dependency cycle (0.9) but has low coupling otherwise (0.1), the average is 0.5. The max is 0.9. The cycle is the risk. Averaging dilutes it.

Three levels: GREEN (< 0.4), YELLOW (0.4-0.7), RED (> 0.7). Dimensions with missing data return `data_available=False` and are excluded — never scored as zero. Zero means "no risk." Missing means "we don't know."

Pure functions. Data in, score out. No I/O, no side effects. Every dimension scorer uses piecewise linear interpolation — smooth, predictable, testable.

`--pr-risk` mode produces a risk report for a branch's changes. A GitHub Actions workflow template posts a PR comment with a 5-second scan (badge + one-liner) and 60-second detail (dimensions, hotspots, risk factors — behind `<details>` tags so it doesn't clutter low-risk PRs).

---

## Impact Analysis and SOW Scoping

`--sow` / `--sow-file` takes a plain-English work request and finds affected targets and consumers. A compact codebase index (all project names, types, sprocs, namespaces, solutions — ~50KB for 250 projects) is sent alongside the SOW so the LLM picks from a known set instead of guessing. Accuracy goes from ~40% on business-domain SOWs to over 80%.

Risk assessment uses graph-derived scoring (deterministic) with AI escalation. AI can escalate risk, never downgrade it. Coupling narratives per consumer, impact narrative for the report, complexity estimate for effort sizing.

SOW scoping adds structured effort estimation with confidence bands.

---

## AI Provider System

`AIProvider` is a runtime-checkable protocol with five methods. `AIRouter` selects providers per task type with lazy creation and caching. `AIBudget` caps total API calls per run so CI doesn't produce a surprise bill.

Eight task types: summarization, symbol extraction, work request parsing, risk assessment, coupling narrative, impact narrative, complexity estimate, boundary assessment. Each task module in `ai/tasks/` owns its prompt template and response parsing.

Currently Gemini only, with a stubbed WEX AI Platform provider. Adding a new backend means implementing an interface, not modifying call sites. When no AI provider is configured, every AI feature degrades gracefully. Core analysis — consumer detection, graph building, coupling metrics, cycle detection — never requires an API key.

### Hybrid git analysis

`--enable-hybrid-git` sends each changed file plus its unified diff to an LLM. The model identifies which types actually have their body or signature modified, reducing false positives from the regex extractor (which reports all types in a changed file). On a typical PR touching 15 files, regex reports ~40 types; hybrid reports ~12.

The non-negotiable: if the API call fails for any reason, fall back silently to regex. The feature is strictly additive.

---

## Reports and Output

Six output formats:

| Format | `--output-file` required? | Where it runs |
|--------|--------------------------|---------------|
| Console | No | All modes |
| JSON | Yes | All modes |
| CSV | Yes | All modes |
| Markdown | No | All modes |
| Mermaid | No | Graph only |
| Pipelines | No | All except graph |

Reporters are pure transforms — structured data in, formatted output. No reporter queries the filesystem or touches the graph. Blast radius uses box-drawing trees showing the full propagation chain with risk ratings inline. Markdown prints to stdout when no output file is given — `scatter ... --output-format markdown | pbcopy` is the workflow.

---

## Docker and WSL2 Performance

The scatter runs via Docker on Windows against the monolith, which means WSL2 with a 9P protocol bridge between the Linux VM and the Windows filesystem. Every `stat`, `readdir`, `open` crosses that bridge.

Solution scanning and graph building used to walk the same 32,156-directory tree independently. Two walks, double the bridge toll. On top of that, `parse_solution_file` called `Path.resolve()` on every project reference — ~7,500 filesystem stat calls for pure path normalization.

Now `__main__.py` does a single `os.walk` that collects `.sln`, `.csproj`, and `.cs` in one pass. The result dict feeds into both phases via optional parameters. `Path.resolve()` is replaced with `os.path.normpath()` — same stems, zero syscalls. Both components fall back to their own walks when called standalone.

| Phase | Before | After |
|-------|--------|-------|
| Solution discovery | ~150-200s | 0s (shared walk) |
| .sln parsing + resolve() | ~175-225s | ~5-10s (normpath) |
| Graph file discovery | ~151s | 0s (shared walk) |
| **Total** | **~682s (~11 min)** | **~311s (~5 min)** |

`Path.resolve()` is fine on native Linux. It's a disaster on 9P over WSL2. The function doesn't change — the cost per call does.

---

## Package Structure

```
scatter/
├── core/              # Data models, graph, parallel infrastructure, patterns
├── parsers/           # tree-sitter AST validation (hybrid mode)
├── scanners/          # File, project, type, sproc, solution, DB scanning
├── analyzers/         # Consumer, git, graph builder, impact, coupling, domain, health, risk
├── ai/                # Provider protocol, router, budget, task modules
├── reports/           # Console, JSON, CSV, markdown, graph, pipeline reporters
├── store/             # Graph cache, incremental patcher
├── compat/            # V1 bridge (solution lookup, pipeline mapping)
├── modes/             # Per-mode entry points
├── config.py          # YAML config with layered precedence
├── cli_parser.py      # Argument parsing
├── analysis.py        # ModeContext, ModeResult, shared analysis logic
└── __main__.py        # Entry point, file discovery, mode dispatch
```

The import graph is acyclic: core -> scanners -> analyzers -> ai -> reports -> modes -> CLI. Each module has one job.

Configuration is layered: CLI flags > repo config (`.scatter.yaml`) > user config (`~/.scatter/config.yaml`) > environment variables > built-in defaults. Missing config files are silently ignored. No config file is ever required.

---

## Type Safety and Tooling

All consumer results use typed `ConsumerResult` dataclasses — zero untyped dicts survive. [uv](https://docs.astral.sh/uv/) handles packaging. mypy enforces zero type errors. ruff handles lint and formatting.

CI pipeline: GitHub Actions with Python version matrix, pytest + coverage (threshold 70%, currently ~87%), ruff lint, ruff format, mypy. `tools/check.sh` mirrors CI exactly — if it passes locally, CI passes.

Optional tree-sitter validation layer (`--parser-mode hybrid`): regex finds candidates, tree-sitter confirms each match occurs in actual code — not a comment, not a string. Falls back to regex on parse failure.

---

## Key Design Decisions

**Regex over Roslyn.** Roslyn requires the .NET SDK, needs compilable source, and doesn't run on a anything other than a PC without gymnastics. Scatter runs in CI runners, on developer laptops, against repos that might not build. Zero dependencies. Works on broken builds.

**One CLI, multiple modes.** Mutually exclusive flags: `--branch-name`, `--target-project`, `--stored-procedure`, `--graph`, `--sow`/`--sow-file`, `--pr-risk`. One tool, one install. New modes extend the pattern.

**Four edge types with configurable weights.** Not all dependencies are equal. A project reference is hard compile-time. A shared sproc is nearly as hard. A `using` statement is softer. A type reference is softest.

**Free functions over god objects.** No class accumulates responsibilities across multiple concerns. Reporters are pure transforms. Mode handlers compose scanners, analyzers, and reporters.

**Git-based cache invalidation.** `git diff --name-only` against the cached hash. Content hashing catches false positives from rebases. Non-git directories fall back to mtime.

**Weighted maximum for composite risk.** Not average. If one dimension screams, the composite screams.

---

## Known Limitations

- **DB scanner comment stripping** is a char-by-char Python state machine. CPU-bound, ~30-50s on large codebases. Fix when it exceeds 60s.
- **normpath vs resolve on symlinks.** `normpath` won't follow symlinks. The stem-based fallback covers most cases.
- **Zero namespace_usage edges on the monolith.** Either `derive_namespace()` doesn't match the convention or namespaces don't align with project names. The scope gate fallback fires more often than ideal. Worth investigating.
- **Scope gate misses fully-qualified type usage.** `new GalaxyWorks.Data.Foo()` without a `using` won't be detected. `full_type_scan=True` bypasses the scope gate entirely.
- **`find_files_with_pattern_parallel` has overlapping rglob walks.** Graph building replaced it, but other callers still use it. Fix when any of them become a measured bottleneck.

---

## What's Next

### Highest priority

**Deeper stored procedure detection.** Basic sproc detection works — string-literal pattern matching (`"sp_XXX"`), EF `DbSet<T>` and `DbContext` patterns, direct SQL, connection strings. The `--stored-procedure` mode traces a named sproc to its consumers. `sproc_shared` edges in the graph link projects referencing the same sprocs. What's missing is comprehensive discovery without knowing sproc names upfront: CommandType-based detection, `EXEC`/`EXECUTE` parsing, `.sql` catalog file scanning, and gateway/repository pattern detection. That's the gap that costs 50%+ of blast radius accuracy on sproc-heavy codebases.

### Not started

- **Focused SOW index** — two-tier index: narrow to candidate solutions, then build a focused index. Reduces noise and token cost at monolith scale.
- **Pipeline registry** — the current pipeline mapping is CSV-based (`pipeline_to_app_mapping.csv` with manual overrides). The design calls for a single canonical YAML registry with multi-source parsers and staleness metadata. Blocked on DevOps repo access.
- **SOW scoping Phase 2-3** — team mapping with risk-driven multipliers, calibration store (predictions vs. actuals).

### Research candidates

| Item | Effort | Fit |
|------|--------|-----|
| PageRank for architectural centrality | Small | Risk Engine — transitive importance that fan-in misses |
| Architectural layer enforcement | Medium | CI gates — declare allowed dependencies, flag violations |
| Cyclomatic complexity per type | Medium | Risk Engine — distinguishes a data class from a state machine |
| Token-budgeted AI context assembly | Medium-large | SOW Scoping — when context quality matters more than convenience |
| Symbol-level importance scoring | Large | Defer until project-level PageRank proves the signal |

### Deferred indefinitely

**Multi-repo federated graph.** Cross-repo blast radius for the post-monolith world. Needs contract-based edge discovery (HTTP, message queues, NuGet). Don't start until a repo actually splits.

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Test count | ~1,490 across unit and integration |
| Coverage | ~87% |
| Output formats | 6 (console, JSON, CSV, markdown, Mermaid, pipelines) |
| Analysis modes | 6 (target, branch, sproc, graph, impact, pr-risk) |
| Edge types | 4 (project_reference, namespace_usage, type_usage, sproc_shared) |
| Risk dimensions | 7 |
| AI task types | 8 |
| Graph build (250 projects) | 2.6s |
| Graph build (800 projects) | 25.8s |
| Incremental patch (1 file) | 10ms |
| Docker monolith full run | ~5 min (down from ~11 min) |
