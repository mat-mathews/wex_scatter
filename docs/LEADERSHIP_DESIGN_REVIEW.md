# Leadership Design Review — Scatter

**Last updated**: 2026-03-26
**Scope**: Full codebase review, main branch
**Status**: ~11K lines Python, 877 tests (all pass), 5 analysis modes, CI green (pytest + ruff + mypy)

---

## 1. What Scatter Does That Nothing Else Does

> **Natural language change description → operational blast radius → pipeline-aware risk report**

SOW parsing → target identification → consumer tracing → sproc tracing → pipeline mapping → AI risk enrichment. No other tool does this end-to-end. Every investment should reinforce this chain.

Don't compete on static analysis depth (NDepend wins there). Compete on **operational blast radius** — which pipelines need to run, what's the risk, who owns the impacted code.

---

## 2. Monolith Readiness Gates

| Gate | Target | Status |
|------|--------|--------|
| **Scale** | Full graph build < 5 min on WEX monolith | Met on synthetic (38.7s at 800 projects / 30K files). Real monolith untested. |
| **Accuracy** | False positive rate < 15% on known dependency set | Untested on real data |
| **Integration** | GitHub Action comments on real PRs | **Deployed** to synthetic_monolith, real PR comments with risk highlights |
| **Adoption** | 3+ engineers use output for merge/deploy decisions | Not yet |

Priority order: anything that doesn't move a gate forward is tech debt, not a blocker.

---

## 3. Overall Assessment

### Grade: A-

The architecture is clean, the engineering is disciplined, the problem space is real. The graph engine handles 800 projects in under 40 seconds with threaded extraction and incremental patching. CI is wired. Since last review: GitHub Action deployed to a real repo with PR impact comments (including risk highlights and column legends), AI rate limiting shipped with budget caps and exponential backoff, and mypy is fully clean. The gap to A is running against the real WEX monolith and proving accuracy at scale.

### What's Strong
- Multi-mode CLI (git branch, target project, sproc, SOW impact, graph health) — product thinking, not just engineering
- Graph caching with git HEAD invalidation, incremental patching (10-954x speedup for usage changes)
- Threaded file extraction, identifier caching, reachable-set scoping — measured and benchmarked
- Clean filter pipeline with observability at each stage
- AI-enriched risk assessment and coupling narratives
- Ruff + mypy + pytest CI with smoke tests

### What Got Us to A-
- **PR integration deployed** — GitHub Action running on synthetic_monolith, real PR comments with risk highlights, column legends, and graph metrics
- **AI rate limiting shipped** — `--max-ai-calls` budget cap, exponential backoff with jitter on transient errors, `BudgetExhaustedError` caught gracefully by all task modules, 22 new tests
- **Mypy fully clean** — zero type errors across 63 source files
- **AI smoke test** — local `check.sh` exercises real Gemini API with budget cap when `GOOGLE_API_KEY` is set

### What's Missing for A
- **No real monolith validation** — all numbers are synthetic. Until it runs against the WEX monolith, scale and accuracy gates are theoretical.
- **No interactive exploration** — the graph is powerful but you can only access it through CLI flags and JSON dumps. A web UI or TUI would make it tangible.
- **AI is bolted on, not integrated** — could be doing semantic breaking change detection, test coverage gap identification, merge conflict prediction. Currently it summarizes files and parses SOWs.
- **No end-to-end CLI tests** — no tests invoke `main()` with real args against the sample .NET projects.

---

## 4. Technical Strengths (Don't Break These)

- **Module decomposition**: `core/`, `analyzers/`, `scanners/`, `ai/`, `reports/`, `store/` — proper separation of concerns
- **Pure data structures**: `DependencyGraph` is a container; analysis lives in standalone functions (testable, composable)
- **Bidirectional adjacency list** with forward/reverse indexes — O(1) lookups both directions
- **Tarjan's SCC** for cycle detection — O(V+E)
- **Layered config**: CLI > repo YAML > user YAML > env > defaults
- **Atomic cache writes** via temp file + `os.replace`
- **Threaded + multiprocess parallelism** with graceful sequential fallback
- **Incremental graph patching** — git diff scopes rebuild to affected projects; safety valves fall back to full rebuild
- Type hints on ~80% of signatures, factory fixtures for test isolation, good logging discipline

---

## 5. What Blocks Monolith Use

### No End-to-End CLI Tests
No tests invoke `main()` with real args against the sample .NET projects. Prerequisite for safely refactoring the entry point.

### No Real Monolith Validation
All benchmarks are synthetic. Regex-based parsing may have different false positive rates on real code. Need to run against the actual WEX monolith, document time / project count / accuracy.

---

## 6. Resolved (Since Last Review)

Issues previously flagged as blockers, now shipped:

| Issue | Resolution | Commit/PR |
|-------|-----------|-----------|
| **Double file read in graph builder** | Identifier cache in Step 4, reused in Step 5c | `3b25a05` |
| **Graph cache scalability** | Dropped `indent=2`, compact JSON, content hash passthrough | `3b25a05`, `183b4e7` |
| **No benchmarks** | Three benchmark tools, published numbers, CI smoke tests | Initiative 12 |
| **ConsumerResult migration** | Typed dataclass replaced untyped dicts across 8 production files | Shipped |
| **Tracemalloc inflating measurements** | Optional `--tracemalloc` flag, off by default in full mode | `986475d` |
| **No PR integration** | GitHub Action deployed to synthetic_monolith with risk highlights and column legends | PR #11, `78ba320` |
| **No AI rate limiting** | `AIBudget` + `RateLimitedModel` proxy, `--max-ai-calls`, backoff+jitter, 22 tests | PR #11, `cf170bc` |
| **Mypy errors** | All 5 errors fixed across budget, gemini_provider, markdown_reporter | `f1330ee` |

### Current Benchmark Numbers

`--mode full`, no tracemalloc, 3 runs with warmup:

| Scale | Projects | .cs Files | Median Build Time | Peak RSS |
|-------|----------|-----------|-------------------|----------|
| Medium | 250 | 4,760 | 2.6s | 216 MB |
| XLarge | 800 | 19,040 | 25.8s | 878 MB |
| XLarge (dense) | 800 | 29,627 | 38.7s | 1,164 MB |

---

## 7. Tech Debt (Should Fix, Doesn't Block)

### Entry Point Bloat
`__main__.py` knows about graph caching, AI provider setup, solution scanning, batch job mapping, and pipeline CSV loading — all before a mode handler runs. Should be CLI subcommands (`scatter git`, `scatter target`, etc.) with shared setup.

### Graph Builder / Consumer Analyzer Divergence
Both understand `.csproj` parsing, namespace matching, and type detection — but implement it differently. A fix in one may not propagate to the other. Need shared test fixtures asserting equivalence.

### `__init__.py` Re-exports
Re-exports 80+ symbols from every layer — internal worker functions, cache internals, deprecated wrappers. Makes everything de facto public API. Provide `scatter.api` for the stable surface.

### `compat/v1_bridge.py`
A compatibility bridge in a pre-1.0 product is dead weight. Complete the migration and delete it.

### Simplistic Confidence Model
Three levels (1.0, 0.6, 0.3) is coarse. Real dependency confidence should account for: compile-time vs. runtime, test projects, dead code, namespace-imported-but-unused. Improve as real-world usage reveals where it matters.

### Regex-Based C# Parsing
Known approximation, not a bug. Misses conditional compilation, source generators, nested types. Document limitations in output and revisit if false positive rate exceeds the 15% gate. If it does, evaluate tree-sitter.

### Sproc Detection Fragility
String literal matching misses parameterized SQL, ORM-generated queries, Dapper calls with proc names in constants. Acceptable for initial adoption; harden based on real-world miss rates.

---

## 8. Roadmap

Ordered by impact on monolith readiness gates.

### Now — Get in the Workflow

| # | Action | Gate | Status |
|---|--------|------|--------|
| 1 | **Deploy GitHub Action** to a real repo | Integration, Adoption | **Done** — deployed to synthetic_monolith |
| 2 | **Add end-to-end CLI tests** | Safety net | Not started |
| 3 | **Run against the WEX monolith** | Scale, Accuracy | Blocked on repo access |

### Next — Harden

| # | Action | Gate | Status |
|---|--------|------|--------|
| 4 | **AI rate limiter / budget cap** (`--max-ai-calls`) | Scale (reliability) | **Done** — PR #11 |
| 5 | **Focused SOW index** (solution-scoped two-tier index) | Accuracy, Adoption | Not started |
| 6 | **CI benchmark regression gate** (medium preset, fail on >2x regression) | Scale | Not started |

### Later — Differentiate

| # | Action | Gate |
|---|--------|------|
| 7 | **Interactive graph exploration** (web UI or TUI) | Adoption |
| 8 | **Deepen confidence model** with real-world data | Accuracy |
| 9 | **CLI subcommands** (`scatter git`, `scatter target`, etc.) | Maintainability |

### Deferred — Revisit Based on Data

| # | Action | Trigger |
|---|--------|---------|
| 10 | Tree-sitter C# parsing | False positive rate > 15% |
| 11 | Historical build failure correlation | Enough PR data to correlate predictions vs. outcomes |
| 12 | AI semantic breaking change detection | SOW pipeline stable and adopted |

---

## Appendix: Open Questions

These get answered by running against the real monolith. They should recalibrate priorities.

1. **How many projects are in the WEX monolith?** The 500/1000/5000 bracket changes optimization priorities.
2. **What's the actual false positive rate?** Regex might be fine. Or it might be 40%.
3. **How long does graph build take on real files?** Synthetic baseline is 38.7s at 800 projects. Real files have variable sizes, complex generics, conditional compilation — could be faster or slower.
4. **Which analysis mode do people actually want first?** Let usage decide.
5. **Does sproc tracing surface anything the existing tools can't?** If yes, that's a differentiator. If no, deprioritize.
