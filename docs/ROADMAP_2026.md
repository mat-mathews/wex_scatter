# Scatter Roadmap — 2026

*Last updated: May 7, 2026*

*This is the single source of truth for where scatter is heading. It supersedes `prototyping_specs/ROADMAP.md` (April 2026) and consolidates the roadmap sections scattered across `PRODUCT_DEFINITION.md`, `METHOD_LEVEL_ANALYSIS_PLAN.md`, `GAP_ANALYSYS.md`, and `FUTURE_RESEARCH.md`.*

---

## Where we are

Scatter started as a question: "what breaks if I change this?" It answers that now. Six ways to ask it, six edge types in the dependency graph (plus sproc and MSBuild metadata on every node), sub-second warm re-runs, AI-powered analysis reports. 18K lines of Python, 1,500+ tests, CI on every PR.

The short version of what's been built:

| Capability | Status |
|------------|--------|
| Six analysis modes (target-project, branch, sproc, SOW, graph health, PR risk) | Shipped |
| Dependency graph with incremental caching (110–954x warm speedup) | Shipped |
| 6 graph edge types (project_reference, namespace_usage, type_usage, config_di, rdl_sproc, sproc_shared) + node-level MSBuild import and sproc reference metadata | Shipped |
| 7-dimension risk engine (structural, instability, cycle, database, blast radius, domain boundary, change surface) | Shipped |
| PR risk comments in GitHub Actions (GREEN/YELLOW/RED) | Shipped |
| SOW impact analysis with AI parsing | Shipped |
| `--ai-summary` structured reports (exec summary, risk analysis, recommendations) | Shipped |
| Domain clustering via Leiden algorithm | Shipped |
| MSBuild implicit imports (Directory.Build.props/.targets ancestor walk) | Shipped |
| Soft references: config DI scanning, RDL→sproc scanning | Shipped |
| .vbproj, .fsproj, .rptproj project type support | Shipped |
| Test-project exclusion | Shipped |
| Method-level consumer filtering (`--class-name` + `--method-name`) | Shipped |
| Claude Code skills (5 slash commands) | Shipped |
| Pipeline resolver with layered matching | Shipped |
| CI pipeline (GitHub Actions: test matrix, lint, mypy, smoke) | Shipped |
| 22 end-to-end SOW integration tests | Shipped |

Performance on real data:

| Scale | Cold build | Warm re-run |
|-------|-----------|-------------|
| 250 projects | 2.6s | <2s |
| 800 projects | 38.7s | <2s |
| 1,591 projects (WEX monolith, consumer analysis) | ~45s | <2s |

That's a lot of shipped work. And it all has tests, runs in CI, and works against the sample projects.

But.

---

## The honest gaps

Three things keep me up at night.

### 1. It's never been fully validated on the actual monolith

The 1,591-project consumer analysis in `docs/SAMPLE_CONSUMER_REPORT.md`? That was one mode. The graph builder, the risk engine, the domain clustering, the SOW pipeline — none of those have been run against real WEX code at scale. Every benchmark is synthetic.

The adversarial critique (`LEADERSHIP_ADVERSARIAL_CRITIQUE.md`) put it plainly: *"Engineering is strong; product validation is absent. One real data run changes every conversation downstream."*

They're right. The 15% false-positive ceiling from the design review? Untested. The Leiden domain boundaries? Untested. We can't credibly quote accuracy numbers without measuring them on actual code.

### 2. Sproc coupling is the biggest blind spot

The SOW signal analysis (`SOW_SIGNAL_ANALYSIS.md`) studied two real WEX CSEs and found that scatter currently captures **50–60% of actual blast radius**. The missing 40–50%? Almost entirely stored procedure coupling — the invisible wiring through the database that project references don't show.

With the sproc inventory built, coverage jumps to **75–85%**. That's the single highest-leverage feature on this roadmap. It's the difference between "useful" and "trustworthy."

The detection strategy is designed — three tiers of signal reliability in `SPROC_DISCOVERY_BRAINSTORM.md`. It's just not built yet.

### 3. Method-level answers are what people actually want

Scatter tells you "7 projects reference `StorePortalConfigurationAsync`." What the person across the table wants to hear: "3 of those call it from controller actions that need UI changes, 2 call it from batch jobs that need config updates, and 2 are test projects that just need parameter additions. Here's the testing strategy."

The data is already flowing through the system. The AI already reads these files. We're just asking it the wrong question — "what does this file do?" instead of "how does this file use this specific method?"

No new parsers. No Roslyn. No tree-sitter. Better prompts to the same AI, with the same files it already reads.

---

## Tier 1: Ship now

Unblocked, high-impact. Next 2–4 weeks.

### Run on the real monolith

**What:** Point scatter's full analysis suite — all six modes — at the WEX monolith. Measure accuracy, performance, false positives.

**Why:** Everything downstream depends on this. Can't calibrate risk scores, can't quote accuracy numbers, can't demo to leadership. The adversarial critique calls it a "one-day activity that changes every conversation."

**Effort:** 1 day to run + 1 day to document findings.

**Blocker:** Repo access.

**Deliverable:** Accuracy baseline doc — false positive rate, performance on real data, issues found.

### Sproc inventory (Phase 1)

**What:** Discover stored procedure references in C# without database access. Tier 1 signals: `CommandType.StoredProcedure`, `EXEC`/`EXECUTE` in string literals, `.sql` file catalog.

**Why:** The numbers don't lie. SOW signal analysis: 50–60% blast radius coverage today → **75–85% with this feature**. On a sproc-heavy codebase like WEX's, this is the single biggest accuracy improvement available.

**Effort:** M. Detection engine + integration with graph edges, SOW matching, `--sproc-inventory` flag.

**Dependency:** None. `db_scanner.py` already does basic sproc detection; this extends it to a comprehensive inventory.

**Detail:** `prototyping_specs/SPROC_DISCOVERY_BRAINSTORM.md`

### Method-level AI analysis (Phase 1)

**What:** When `--method-name` and `--ai-summary` are both present, change the per-file prompt from "what does this file do?" to "how does this file use this specific method?" Returns structured JSON: caller methods, call pattern, change impact, risk level.

**Why:** Turns "7 projects reference it" into "here's exactly how each one uses it and what breaks." No new infrastructure — prompt change + conditional in `_summarize_consumer_files()`.

**Effort:** S. Prompt change only.

**Detail:** `docs/METHOD_LEVEL_ANALYSIS_PLAN.md`, Phase 1.

### End-to-end CLI tests per mode

**What:** Integration tests that run scatter's CLI end-to-end against the sample projects, one test suite per analysis mode. Not just SOW (which has 20 e2e tests), but target, branch, sproc, graph, and pr-risk.

**Why:** The adversarial critique flagged this as a blocker for safe refactoring. Can't restructure code if you can't verify all modes still work. Also surfaces accuracy issues that unit tests miss.

**Effort:** S. 1 day. Sample projects exist. Pattern established by the SOW tests.

---

## Tier 2: Ship next

Higher effort or with soft dependencies. Next 1–3 months.

### Focused SOW index (Initiative 11)

**What:** Two-tier solution index that scopes AI analysis to relevant solutions. Pass 1 builds compact solution summaries (~20 lines each). Pass 2 builds a focused index for only the candidate solutions. Typical 70% index size reduction.

**Why:** On a monolith-scale repo, the AI drowns in irrelevant context. Scoping to relevant solutions improves answer quality and cuts token cost. Phase 2 (`--solutions` CLI flag) is independently shippable.

**Effort:** M across 4 phases.

**Dependency:** Initiative 9 (solution-aware graph) — shipped.

**Detail:** `prototyping_specs/FOCUSED_INDEX_PLAN.md`

### CI governance: `--fail-on`

**What:** `scatter --fail-on cycles,risk:high,coupling:15.0,consumers:20` — exit 0 = pass, exit 1 = threshold violated. Reports still produced either way. Configurable via `.scatter.yaml`.

Includes two supporting pieces:
- **Change-type classification** — file-extension → change-type taxonomy (SourceFile, ContentFile, SharedBuildFile) so `.props` changes don't gate CD but `.cs` changes do. CDH has this; scatter doesn't. (Gap #5 in `archive/GAP_ANALYSYS.md`)
- **Fail-safe output** — on error, write valid JSON error report + exit deterministic code, so PR checks never hang.

**Why:** This is what makes scatter sticky. Without CI gates, it's a thing people choose to run. With CI gates, it runs whether anyone remembers or not.

**Effort:** S-M. Risk engine already computes all scores; this is threshold checks + exit codes + the taxonomy.

**Detail:** `PRODUCT_DEFINITION.md` §12 Phase 5.

### Method-level analysis (Phases 2–3)

**What:** Phase 2: Method-aware report summary — the report prompt shifts from project-level coupling to method-level usage analysis. Groups consumers by risk. Recommends testing order and deployment sequence. Phase 3: Structured method evidence — extract line numbers and context windows around each call site, so the AI sees the exact code, not the whole file.

**Why:** Phase 1 gives method-focused per-file summaries. Phases 2–3 give the full answer to "how bad is it if we add a `tenantId` parameter?" in one command.

**Effort:** M (Phase 2) + M (Phase 3). Phase 2 needs Phase 1's caller data.

**Detail:** `docs/METHOD_LEVEL_ANALYSIS_PLAN.md`

### SOW effort estimation (SOW scoping Phase 1)

**What:** Graph-heuristic-based effort estimates: investigation, implementation, testing, integration, database. Confidence bands: HIGH (±20%), MODERATE (±30%), LOW (±50%). All multipliers start at 1.0 until calibration data exists.

**Why:** The question after "what's the blast radius?" is always "how long will this take?" Graph data gives us a defensible starting point instead of a shrug.

**Effort:** M. Two phases — Phase 1 is estimation from graph data, Phase 3 (deferred, see Tier 3) is historical calibration.

**Dependency:** Risk engine Phase 1 — shipped.

**Detail:** `prototyping_specs/SOW_SCOPING_PLAN.md`

### SOW differentiator (Phase 3)

**What:** CI badge, actionable no-API-key error message, smoke test job, Quick Tour docs. The "hand it to someone who's never seen scatter" cleanup.

**Effort:** S.

**Detail:** `prototyping_specs/SOW_DIFFERENTIATOR_PLAN.md`

### Quick performance wins

Three optimizations that are trivially small and worth doing:

| Fix | Effort | Impact |
|-----|--------|--------|
| Cache file identifiers in Step 4, reuse in Step 6 (eliminates redundant file reads) | 20 LOC | 30–40% build speedup |
| Drop `indent=2` from JSON cache serialization | 1 line | ~40% smaller cache file |
| Scope type_usage edges to projects with existing project_ref or namespace_usage edges | 15 LOC | 50x fewer project pairs evaluated |

---

## Tier 3: Ship when triggered

Each item has an explicit trigger condition. Don't start until the trigger fires.

### Pipeline registry

**What:** Replace CSV + JSON pipeline mapping with canonical YAML registry. Multi-source parsers, staleness detection, `scatter pipelines sync/status/list/lookup`.

**Trigger:** DevOps config repo access is granted.

**Effort:** M across 4 phases.

**Detail:** `prototyping_specs/PIPELINE_REGISTRY_DESIGN.md`

### Sproc inventory (Phases 2–3)

**What:** Tier 2 signals (gateway detection, EF patterns) and Tier 3 (config/attributes). The subtler sproc reference patterns.

**Trigger:** Phase 1 ships and we measure the remaining coverage gap. If Phase 1 gets us to 80%, the ROI on Phases 2–3 drops.

### SOW scoping: calibration store (Phase 3)

**What:** Append-only JSONL of predicted vs actual effort. `--record-actual`, `--calibration-report`. Activates measured multipliers instead of 1.0 defaults.

**Trigger:** 10+ SOWs with recorded actuals exist. Estimation without calibration is educated guessing. With calibration data, it becomes measurement.

### Plugin XML scanning

**What:** Port CDH's `Find-PluginXmlFilesReferencingTypes` for `AppMonitoringTypes.xml`, `RegisteredTypes.xml`.

**Trigger:** Actual plugin XML files from the monolith are available for testing. Can't write detection code without examples.

### Multi-repo Phase 1: multi-root `--search-scope`

**What:** Accept multiple directories in `--search-scope`. One graph, multiple source trees.

**Trigger:** WEX splits a repo, or a user needs cross-repo scanning.

**Why it's Phase 1 only:** The full multi-repo story — NuGet edges, API scanning, remote repos — is a large effort. Multi-root is a 2-hour no-regret first step. Build the rest when someone actually needs it.

**Detail:** `prototyping_specs/MULTI_REPO_BRAINSTORM.md`

---

## What's deferred and why

Items that are architecturally sound but premature, demand-absent, or dependent on things that don't exist yet.

| Item | Reason |
|------|--------|
| **Unified report data model** | No user sees the internal schema. Four output formats work. Build when inconsistency blocks a real feature. |
| **HTML interactive reports** | The plan calls for D3.js visualization. Nobody's asked for it. Claude Code skills + markdown are the actual UI. |
| **Diff reports / baselines** | Requires historical snapshots. Build after CI runs generate enough data to make diffs meaningful. |
| **Watch mode** | No demand. Cached re-runs are already near-instant. |
| **WEX AI Platform provider** | Build when the platform exists. Gemini works. |
| **Additional AI providers** (Anthropic, OpenAI, Azure, Ollama) | The protocol is built. Adding a provider is a one-file change. Build on demand. |
| **Token budget manager / AI response caching** | AI calls are infrequent and cheap ($0.01–$0.15/run). Build when costs matter. They don't yet. |
| **Streaming progress bars** | Most runs finish in <2s. A progress bar for a 2-second operation is overhead. |
| **Extraction planning** (`scatter extract`) | Good idea for later. Nobody's extracting services yet — they're still figuring out what depends on what. |
| **NuGet `<PackageReference>` edges** | Already parsed by the scanner, just not emitted as graph edges. Build when cross-repo NuGet tracing matters (multi-repo trigger). |
| **MCP server for Claude** | Skills are shipped and working. MCP server is the next step if other AI clients need access. No demand signal yet. |
| **Structural improvements** (CLI subcommands, `_legacy.py` cleanup, test directory reorganization) | Code hygiene. Important eventually, not urgent. Do it when the next refactoring push makes it natural. |

---

## The longer arc

Not committed. Not planned. But the architecture is heading here, and the shipped work makes each more feasible. Each section below includes the trigger that would promote it to real work.

### Near-term: builds on what exists

**Interface-aware method tracing.** The method filter already catches both direct and interface calls (it matches `.MethodName(`). But the AI summary should know the difference — "calls through the interface, decoupled" vs "calls the concrete class directly." Enriches Phase 1 method analysis with no new infrastructure.

**Cross-method analysis.** "I'm changing `StorePortalConfigurationAsync` AND `GetPortalConfiguration` — combined blast radius?" Currently two commands. Accept comma-separated `--method-name` values, deduplicate consumers, show the union.

**Method-level coupling score.** Not project-level — count distinct callers across all consumers. A method with 50 call sites across 7 projects is a different risk profile than one with 7 call sites. Computable from method evidence data, no new graph.

**PageRank for architectural centrality.** Fan-in counts direct dependents. PageRank captures transitive importance — a project depended on by other highly-depended-on projects scores higher than one depended on by leaf nodes. Small effort, high signal, additive metric on `ProjectMetrics`. Strongest near-term research candidate per `FUTURE_RESEARCH.md`.

**Layer enforcement.** Teams declare allowed dependencies in `.scatter.yaml`; scatter flags violations. Pairs with `--fail-on` CI gates. Medium effort, high value for architecture governance.

### Medium-term: tree-sitter method graph

A lightweight method-level dependency graph built with tree-sitter (local C# parser, no .NET SDK required). Extracts method declarations with signatures, method calls with receivers, class inheritance, DI wiring via constructor parameters.

**Scale math:** 1,591 projects × 100–200 methods each = 150K–300K method nodes. Tree-sitter parses at ~100ms/file, so cold build takes ~15 minutes. Incremental patching via the same git-diff approach as the project graph patcher makes subsequent runs fast.

**What it enables:** Fan-in/fan-out at the method level. Method-level instability indices. Call chain visualization: `Controller.Save → Service.Store → Repository.Insert → sproc`. "This method has fan-in of 23 — stable core. That method has fan-in of 1 — leaf."

**Risk:** Tree-sitter's C# grammar covers ~95% of real-world syntax. The 5% gap — advanced generics, pattern matching expressions, global usings — means some method calls get missed. Document the limitation, use regex as fallback.

**Trigger:** AI-assisted method analysis (Tier 1–2) proves the value of method-level insight. The tree-sitter graph makes it deterministic instead of AI-assessed.

### Long-term: graph database backend

The graph lives in a JSON file. For 1,591 nodes and ~20K edges, this is fine — loads in <1s. A method-level graph with 150K–300K nodes and 500K+ edges produces ~200MB of JSON with ~15s serialization. That's the ceiling.

PostgreSQL (or SQLite for local-only) enables: indexed queries, historical snapshots, concurrent CI access, `WITH RECURSIVE` graph traversal, coupling trend dashboards, snapshot diffing.

**Trigger (any of these):**
1. Graph cache exceeds 50MB or serialization exceeds 5 seconds
2. Multi-repo federated graph needed
3. Historical trend analysis requested (coupling over time)
4. Multiple CI runners contend on graph file locks

The migration is clean: implement as an alternative to `graph_cache.py`. The in-memory `DependencyGraph` stays the same — only the serialization layer changes. Everything above it (analyzers, reporters, AI tasks) is unaffected.

### Long-term: multi-repo federated graph

Cross-repo blast radius for the post-monolith world. Contract-based edge discovery with confidence layers:

| Layer | Signal | Confidence |
|-------|--------|------------|
| 1 | NuGet contract packages | Highest |
| 2 | Generated client detection | High |
| 3 | API controller routes | Medium |
| 4 | HttpClient URL matching | Lowest |

Four phases: multi-root `--search-scope` (Tier 3 above) → NuGet contract scanning → API controller scanning → remote repo scanning via DevOps API.

**Trigger:** WEX actually splits a repo. The monolith is still the monolith.

**Detail:** `prototyping_specs/MULTI_REPO_BRAINSTORM.md`

### Speculative: real-time IDE integration

An LSP extension that patches the graph on file save and shows coupling impact in the gutter. Rename a method → IDE shows "12 callers across 4 projects" before you commit.

Requires: method-level tree-sitter graph + persistent backend + LSP server + IDE extension (VS Code, JetBrains).

This is far out. But every tier of this roadmap makes it more feasible. The foundation is being laid now — whether or not we ever build the house.

---

## Appendix: where the details live

Every major item above has a longer design doc. These are the pointers.

**Design & strategy docs** (in `prototyping_specs/`):

| Topic | Location |
|-------|----------|
| Product vision & architecture | `PRODUCT_DEFINITION.md` |
| SOW coverage gap measurement | `SOW_SIGNAL_ANALYSIS.md` |
| Sproc discovery strategies | `SPROC_DISCOVERY_BRAINSTORM.md` |
| Focused SOW index | `FOCUSED_INDEX_PLAN.md` |
| Pipeline registry design | `PIPELINE_REGISTRY_DESIGN.md` |
| Multi-repo architecture | `MULTI_REPO_BRAINSTORM.md` |
| Architecture review & readiness gates | `LEADERSHIP_DESIGN_REVIEW.md` |
| Adversarial critique | `LEADERSHIP_ADVERSARIAL_CRITIQUE.md` |
| Risk engine (7 dimensions) | `RISK_ENGINE_PLAN.md` |
| PR risk scoring | `PR_RISK_SCORING_PLAN.md` |
| SOW effort estimation | `SOW_SCOPING_PLAN.md` |
| SOW differentiator / e2e tests | `SOW_DIFFERENTIATOR_PLAN.md` |
| Research candidates (PageRank, layer enforcement, etc.) | `FUTURE_RESEARCH.md` |
| Claude Code integration | `CLAUDE_INTEGRATION_EVALUATION.md` |
| Performance benchmarks | `PERFORMANCE_AT_SCALE.md`, `XLARGE_BENCHMARK_RESULTS.md` |
| Tool comparison (Scatter vs CodeGraphContext) | `CODEGRAPHCONTEXT_COMPARISON.md` |

**Reference docs** (in `docs/`):

| Topic | Location |
|-------|----------|
| Method-level analysis (3 phases + futures) | `METHOD_LEVEL_ANALYSIS_PLAN.md` |
| Gap analysis vs CDH scripts | `archive/GAP_ANALYSYS.md` |
| Technical debt with revisit triggers | `TECH_DEBT.md` |
| Monolith runbook (Docker + Git Bash) | `MONOLITH_RUNBOOK.md` |
| Leiden community detection vision | `archive/leiden_in_scatter_analysis_report.md` |
| Leiden implementation gap analysis | `archive/leiden_implementation_analysis.md` |
| ADR: graph builder 100x speedup | `archive/ADR_GRAPH_PERFORMANCE.md` |
| ADR: Docker/WSL2 performance fix | `archive/ADR_DOCKER_PERFORMANCE.md` |
| ADR: development log & design decisions | `archive/ADR_DEV_LOG.md` |
| Sample output: real monolith consumer report | `SAMPLE_CONSUMER_REPORT.md` |
| Sample output: AI-enriched analysis report | `SAMPLE_AI_CONSUMER_REPORT.md` |
