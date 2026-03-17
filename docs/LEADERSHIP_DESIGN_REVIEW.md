# Leadership Design Review — Scatter Codebase

**Date**: 2026-03-17
**Reviewers**: Priya Chandrasekaran (Architect), Marcus Webb (Principal Engineer)
**Scope**: Full codebase review, feature/decompose-main branch
**Status**: 637 tests (all pass, 1 xfail), v2.1.0

---

## Priya Chandrasekaran (Architect)

### The Fundamental Question: What Is This Trying to Be?

I'll start where I always start: what's the bounded context, and does the code reflect it?

Scatter started as a blast-radius analyzer — "what breaks if I merge this?" That's a clear, valuable bounded context. But the codebase is now trying to be four things at once:

1. A consumer detection pipeline (the original tool)
2. A full dependency graph engine with coupling metrics, health dashboards, cycle detection, and domain clustering
3. An AI-powered impact analysis platform
4. An Azure DevOps pipeline mapping utility

These are different products with different lifecycles, and they're tangled at the hip through `__main__.py` and `cli.py`. The 506-line `__main__.py` is a dispatch table held together with `is_git_mode` / `is_target_mode` / `is_impact_mode` / `is_graph_mode` booleans. The decomposition into `cli.py` helped, but `__main__.py` still knows about graph caching, AI provider setup, solution file scanning, batch job mapping, and pipeline CSV loading — all before a single mode handler runs.

**The question I'd ask the team**: If graph mode and impact mode were separate CLI commands (subcommands or even separate entry points), would the code be simpler? I think the answer is obviously yes, and that's a signal.

### Coupling I Can See From the Architecture Diagram in My Head

**`__init__.py` is doing violence to encapsulation.** It re-exports 80+ symbols from every layer — internal worker functions (`analyze_cs_files_batch`, `chunk_list`), cache internals (`FileFacts`, `ProjectFacts`), deprecated wrappers (`gemini_model`, `configure_gemini`), and even `import argparse; import logging`. This is a "flat namespace" that makes everything public API. Any refactoring now risks breaking unknown callers. The `_legacy.py` wrappers reinforce this — you're paying a maintenance tax to keep dead interfaces alive. Who is calling `scatter.gemini_model` directly? If nobody, delete it. If somebody, they should be using `AIRouter`.

**The result dict is untyped.** All three legacy modes (`run_git_analysis`, `run_target_analysis`, `run_sproc_analysis`) produce `List[Dict[str, Union[str, Dict, List[str]]]]`. This dict has keys like `TargetProjectName`, `ConsumerProjectPath`, `PipelineName`, `BatchJobVerification`, `ConsumerFileSummaries` — but there's no dataclass, no schema, no validation. The bridge function `_process_consumer_summaries_and_append_results` constructs these dicts manually. Every reporter then reaches into them by string key. A single typo in a key name is a silent bug. At this scale (~7 reporters consuming this data), this is a guaranteed source of future regressions.

**Graph builder reads every `.cs` file twice** (`graph_builder.py:212-233`). The type_usage edge step re-reads every file that was already read in step 4 for type/namespace/sproc extraction. That's O(F) redundant I/O. At 10x scale (thousands of projects, hundreds of thousands of files), this doubles your build time. The content should be cached in memory during step 4 or the identifier extraction should happen in the same pass.

### Boundaries That Should Exist But Don't

The consumer analyzer (`consumer_analyzer.py`) and the graph builder (`graph_builder.py`) both understand `.csproj` parsing, namespace matching, and type detection — but they implement it differently. `find_consumers` uses a 5-stage filter pipeline; `build_dependency_graph` does a single-pass build. They share some low-level scanners but diverge at the integration level. If you fix a false-positive pattern in one, does it propagate to the other? I suspect not always.

The `ModeContext` dataclass is a step in the right direction (no raw `args`), but it's still carrying a grab-bag of settings that modes selectively read. The `types.SimpleNamespace` shim in `_ensure_graph_context` (line 279) is a code smell — it exists because `build_graph_context` wants an `args`-like object but `ModeContext` isn't the right shape. That's a sign the graph context builder should take explicit parameters, not an opaque namespace.

### What Happens at 10x Scale?

The parallel file discovery (`parallel.py`) uses `ProcessPoolExecutor` with `rglob` in each chunk. But the chunking is by directory, and `rglob` already recurses. So if you chunk `[dir_a, dir_b]` and `dir_b` is inside `dir_a`, you get duplicate results. The dedup at line 598 papers over this, but you're doing 2x the work for overlapping directories. The `estimate_file_count` function samples 5 directories and extrapolates — this is wildly inaccurate for monorepos with uneven directory structures. It's "good enough" for small repos, but at 10x it'll make bad worker-count decisions.

The graph cache (`graph_cache.py`) stores the entire graph as indented JSON. For a repo with 5,000 projects and 50,000 edges, that's potentially 50-100MB of JSON. The `json.load` call will block for seconds. Have you considered a more compact format (msgpack, SQLite, or at minimum non-indented JSON)?

---

## Marcus Webb (Principal Engineer)

### Show Me the Data

**No benchmarks in CI.** You have `tools/benchmark_graph_build.py` and `tools/benchmark_incremental.py`, but they're not wired into the test suite or CI. So when someone adds a new analysis step or changes the regex patterns, nobody knows if performance regressed until someone manually runs a benchmark on their laptop. For a tool whose value proposition is "fast analysis," this is flying blind.

**Coverage target is 70%.** That's a floor, not a ceiling. But more importantly, what's the test strategy? I see 25 test files (~5,000 lines), but the tests I've read are mostly unit tests against in-memory fixtures. Where are the integration tests that run the actual CLI end-to-end against the sample .NET projects in this repo? The `test_new_samples.py` file is closest, but it's testing internal functions, not `python -m scatter --branch-name ...`. If you refactor `__main__.py` (which you should), how do you know the CLI still works?

### Concrete Problems I'd Block a PR For

1. **`parallel.py:295` — `Dict[str, any]` (lowercase `any`).** This passes at runtime because `any` is a builtin function that happens to be truthy in `isinstance` checks — but it's semantically wrong. It should be `Any` from `typing`. The same pattern appears on lines 381-385.

2. **`graph_builder.py` accesses `graph._nodes` directly** (lines 187, 191, 213, 229, 316, 327). The graph has proper query methods (`get_node`, `get_all_nodes`), but the builder bypasses the public API to check membership. This means the graph's internal representation is de facto public. If someone refactors `_nodes` to a different structure, six callsites in the builder break silently. Either make `__contains__` a public method or use `get_node(name) is not None`.

3. **The `_process_consumer_summaries_and_append_results` function** (v1_bridge.py) is 80 lines of imperative dict construction with hardcoded pipeline names (`"cdh-batchprocesses-az-cd"` on line 115). This should be configuration, not code. What happens when you add a second batch pipeline?

4. **`consumer_analyzer.py:201` — Regex construction from user input.** `target_namespace` is user-controlled (via `--target-namespace`) and is passed through `re.escape`, which is correct. But the regex also appends `(?:\.[A-Za-z0-9_.]+)?` to match sub-namespaces. Low-risk today, but I'd prefer building the pattern without string interpolation for defense in depth.

5. **No timeout or circuit breaking on AI calls.** The `_summarize_consumer_files` function (cli.py:220-262) iterates over every consumer file and makes a synchronous AI call per file. If Gemini is slow or returns errors, you're serially retrying across potentially hundreds of files with no backoff, no rate limit, and no total-budget cap. One bad API day and your CLI hangs for 20 minutes.

### Things That Are Actually Good (Because I Should Say So)

The graph data structure (`core/graph.py`) is clean. Immutable-ish, O(1) lookups, proper separation of mutation from query. The evidence-capping at 10 entries is a pragmatic choice. The BFS traversal methods are correct and depth-limited. This is the part of the codebase that's been designed rather than accreted.

The config system (`config.py`) with layered precedence is solid — env vars < user config < repo config < CLI. Simple, predictable, no magic. The YAML loading with graceful fallback is production-quality.

The filter pipeline model (`FilterStage`, `FilterPipeline`) is a good abstraction. It gives you observability into the analysis funnel without coupling the stages to each other. More of the codebase should look like this.

---

## Joint Design Discussion

**Priya**: The central question is whether to treat the decomposition as cosmetic (split files, keep the same architecture) or structural (introduce proper bounded contexts). The current branch name is `feature/decompose-main`, which tells me you're doing the cosmetic version. I'd argue you're in a good position to do the structural version while you have things pulled apart.

**Marcus**: Agreed. Here's what we'd propose as concrete next steps, in priority order:

### Recommendation 1: Type the Result Dictionary
Create a `ConsumerResult` dataclass that replaces the `Dict[str, Union[str, Dict, List[str]]]` flowing through the legacy modes. This is the single highest-leverage change — it eliminates an entire class of key-typo bugs, makes the reporter contracts explicit, and enables IDE support.

### Recommendation 2: Introduce CLI Subcommands
Replace the five boolean mode flags with `scatter git`, `scatter target`, `scatter sproc`, `scatter impact`, `scatter graph`. Each subcommand gets its own parser and handler. The shared setup (config loading, AI provider init) stays in a common `setup()` function. This eliminates the if/elif chain in `__main__.py` and makes each mode independently testable.

### Recommendation 3: Eliminate the Double File Read in Graph Builder
Cache file contents (or at minimum, the extracted identifiers) during step 4 and reuse them in step 5c. This is a straightforward dict[Path, set[str]] that avoids re-reading every .cs file.

### Recommendation 4: Kill `__init__.py` Re-exports
Move to explicit imports everywhere. The backward-compatibility tax isn't worth it for a tool that's pre-1.0. If external consumers exist, provide a `scatter.api` module with the stable public surface and deprecate everything else.

### Recommendation 5: Add End-to-End CLI Tests
Write tests that invoke `main()` with real args against the sample .NET projects in this repo. Capture stdout/stderr and assert on the output format. These are your refactoring safety net.

### Recommendation 6: Add a Rate Limiter / Budget Cap to AI Calls
Before summarizing consumers, calculate the total number of API calls and log it. Add a `--max-ai-calls` flag (default: 50). After hitting the cap, skip remaining calls and warn. This prevents runaway costs and hangs.

### Recommendation 7: Consider Compact Cache Serialization
At minimum, drop `indent=2` from the graph cache JSON write. For large graphs, evaluate msgpack or SQLite. The cache is write-once-read-many, so read performance matters more than human readability.

### Recommendation 8: Converge Graph Builder and Consumer Analyzer
The graph builder and consumer analyzer need to converge on a single understanding of "what constitutes a dependency." Right now they can disagree on edge cases (MSBuild property references, conditional references, etc.) and there's no test that validates equivalence. A shared `ReferenceResolver` or at minimum a shared test fixture that asserts both paths produce the same consumer set for a known input would catch drift early.

### Recommendation 9: Organize Test Files
The 25 `test_*.py` files at the repo root are unwieldy. A `tests/` directory with subdirectories (`tests/unit/`, `tests/integration/`) would make it easier to run subsets and understand coverage.

### Meta-Observation

The bones are solid — the graph engine, the config system, the filter pipeline model. The problems are mostly structural: too much happening in the entry point, untyped data flowing through the system, and some performance cliffs waiting at scale. None of this is a rewrite — it's surgical improvement while the decomposition branch is in flight.
