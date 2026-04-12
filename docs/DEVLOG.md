# Development Log — Scatter

## 2026-03-23 — AI Provider & Theme Polish
Stubbed out the WEX AI Platform provider so the protocol abstraction actually has two implementations now. Switched mkdocs to material theme with dark mode default because life's too short for light mode.

## 2026-03-22 — SOW Differentiator & GitHub Action
Big day. Wrote the SOW differentiator implementation plan, then backed it up with 22 new e2e tests for SOW/impact mode. Found and fixed a direct consumer parent bug that was quietly wrong — the kind that passes all your existing tests and then bites you in prod. Built a GitHub Action workflow template so scatter can post impact comments directly on PRs. Polished the evaluator experience: CI badge, Quick Tour rewrite, smoke tests that actually assert things. Restructured Getting Started vs Quick Tour because they'd drifted into saying the same thing twice.

## 2026-03-21 — The Cleanup Reckoning
Decided it was time to pay down the debt. Replaced every untyped result dict with a proper ConsumerResult dataclass (Init 7 Phase 1) — 0 dicts survived. Ripped out manual venv and replaced with uv packaging. Fixed all 77 mypy errors in one sitting. Ran ruff across everything: unused imports, formatting, dead vars — gone. Rebuilt CI from scratch: uv-based workflow with matrix testing across 3.10/3.11, lint job, type-check job. Added `tools/setup.sh` and `tools/check.sh` so anyone can bootstrap and validate locally in one command. Wrote up the Pipeline Registry design doc. Updated all the docs to reflect the new world.

## 2026-03-20 — Initiative 9: Solution-Aware Graph
Five phases, one day. Built a structured .sln parser (Phase 1), wired solution membership into ProjectNode (Phase 2), added cross-solution coupling metrics and health observations (Phase 3), scored domain clusters against solution boundaries (Phase 4), and wrote end-to-end validation tests proving it all works together (Phase 5). The question "which solutions does this coupling cross?" now has a real answer.

## 2026-03-19 — SOW Index, Claude Skills, Docs Restructure
Initiative 10: built a codebase index so the SOW parser can actually identify targets accurately instead of guessing from names alone. 'Shipped' 5 Claude Code skills (branch, consumers, impact, sproc, graph) so you can run scatter from inside Claude. Nuked the old monolithic API reference and restructured the docs properly.

## 2026-03-17 — CLI Decomposition & Documentation
Decomposed `__main__.py` into `cli.py` (mode handlers) and `cli_parser.py` (argument parsing). The main file was doing too many things and everyone (me) knew it. Added the leadership design review doc. Scaffolded the mkdocs documentation site — real docs, not just a README.

## 2026-03-16 — Transparent Graph Phase C, Mermaid, CI
Finished the transparent graph work: Phase C makes scatter build the graph automatically on first run, no flags needed. Added `--output-format mermaid` for anyone who wants diagrams. Set up the CI pipeline with coverage config and pinned all dependency versions. The tool is now installable, testable, and deployable without tribal knowledge.

## 2026-03-15 — Transparent Graph A & B, Personas
Transparent Graph Phase A: scatter now auto-loads the cached graph silently. Phase B: consumer lookups hit the graph first, falling back to filesystem only when needed. This is where the "101x speedup" actually lands for end users. Also added 9 team personas to CLAUDE.md for multi-perspective code reviews — turns out having a fictional architect yell at your code is surprisingly useful.

## 2026-03-14 — Incremental Updates & New Flags
Wired `--summarize-consumers` to the AI provider so it actually does something now. Added `--graph-metrics` for enrichment across all analysis modes. The big one: implemented incremental graph updates with per-file content-hash patching. Changed files get re-extracted; unchanged files get skipped. Full rebuild takes seconds, incremental takes milliseconds. Also added `--output-format pipelines` for anyone piping scatter output into other tools.

## 2026-03-13 — Initiative 6: Report Polish
Four phases of making the output not embarrassing. Filter pipeline visibility so you can see where candidates drop out (Phase 2). Blast radius tree view with propagation tracking (Phase 3). Markdown output format for all modes (Phase 4). Also reprioritized the roadmap from "what's architecturally next" to "what gets people using this" — adoption-driven sequencing.

## 2026-03-12 — 101x Performance
Graph builder went from painfully slow to 101x faster. Turns out doing fewer redundant filesystem walks helps. Documented the numbers because claims without benchmarks are just vibes.

## 2026-03-10 — Reports & Health Dashboard
Initiative 6 Phase 1: fixed report quality issues that made the output hard to trust. Initiative 5 Phase 6: added graph reporters, health dashboard, and CSV export. The tool now tells you things like "this project has 14 inbound dependencies and an instability score of 0.12 — it's load-bearing and you should be nervous about changing it."

## 2026-03-09 — Regex Hardening
Found gaps in the C# type extraction regex — `readonly struct` and `ref struct` were being missed. Fixed them and expanded the test suite to 398 tests. Regex bugs are the worst kind of silent.

## 2026-03-08 — Initiative 5: The Graph Engine
Five phases in one day. Built the dependency graph model and builder (Phase 1). Added coupling metrics and Tarjan's cycle detection (Phase 2). Graph persistence with cache invalidation and `--graph` CLI mode (Phase 3). Database dependency scanner (Phase 4). Domain boundary detection (Phase 5). Added 6 workflow examples to the README. This is where scatter went from "finds consumers" to "understands your architecture."

## 2026-03-07 — Graph Planning
Wrote the detailed plan for Initiative 5: graph model, metrics, domain analysis. Needed to think before building — the data model choices here ripple through everything downstream.

## 2026-03-06 — Config & Impact Analysis
Initiative 3 Phase 5: layered configuration system (CLI > repo > user > env > defaults) and AI task router. Initiative 4: impact analysis pipeline with AI enrichment. Tests cleaned up. The tool can now take a statement of work and tell you what breaks.

## 2026-03-05 — AI Provider Protocol
Initiative 3 Phase 4: defined the AIProvider protocol and migrated Gemini behind it. Duck-typed, runtime-checkable. Adding a new AI backend is now "implement 3 methods" instead of "grep for google-generativeai and hope."

## 2026-03-04 — Initiatives 1-3: The Big Restructure
Three initiatives in one day. Initiative 1: parallelized method filtering, benchmarked Phases 2.2/2.3. Initiative 2: hybrid git analysis with LLM-enhanced diff symbol extraction — instead of just finding changed files, scatter now understands what types changed. Initiative 3 (Phases 1-3): extracted the scatter package from a single-file script into a proper package structure — core, scanners, analyzers, reporters, CLI. This is the day the codebase grew up.

## 2026-03-03 — Samples & Product Definition
Added BatchProcessor and WebPortal .NET sample projects so the test suite exercises real-ish dependency patterns. Wrote the product definition doc — what scatter is, who it's for, why it exists.

## 2026-02-16 — Multiprocessing Phase 2
Parallel content analysis for consumer and sproc scanning (Phase 2.1). Parallel XML parsing of .csproj files (Phase 2.2). Parallel project mapping with directory-to-csproj caching (Phase 2.3). The single-threaded scanner was the bottleneck and now it isn't.

## 2025-10-26 — Stabilization
Bug fixes and benchmarking before starting Phase 2. Measured first, then decided what to parallelize.

## 2025-10-11 — Multiprocessing Phase 1
First phase of multiprocessing support. The codebase had been sequential and it was starting to hurt on real-sized repos.

## 2025-05-14 — Stored Procedure Debugging
Debugged the sproc analysis path. Added fake projects for testing because you can't test database dependency tracing without something that references a stored procedure.

## 2025-05-04 — Day One
Initial commit. First working implementation with mock .NET example projects. A single Python script that could answer "who uses this .csproj?" — everything from here on out... making these answers faster, richer, and more trustworthy. Let's hope.
