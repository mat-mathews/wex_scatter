# Scatter Roadmap

**Date:** 2026-04-07
**Purpose:** High-level view of outstanding design work. Granular task tracking lives in `tasks.txt` at the repo root — this doc is the strategic summary that links design specs (now archived under `prototyping_specs/`) to current priorities.

For a checkbox-level breakdown of every phase, see [`tasks.txt`](../tasks.txt).

---

## Outstanding initiatives

### Stored procedure inventory — HIGHEST PRIORITY for WEX
**Status:** Designed, not started
**Implementation spec:** [SPROC_DISCOVERY_BRAINSTORM.md](SPROC_DISCOVERY_BRAINSTORM.md) — detection strategies tiered by signal reliability
**Supporting evidence:** [SOW_SIGNAL_ANALYSIS.md](SOW_SIGNAL_ANALYSIS.md) — analysis of two real WEX CSEs (FID1010HD, FID460HD) showing the coverage gap this work closes
**Tasks:** `tasks.txt` → "INITIATIVE: STORED PROCEDURE INVENTORY"

Automatically discover every sproc referenced from C# without database access, then expose `{sproc → projects}` as graph edges. The SOW signal analysis estimates current Scatter misses 50%+ of blast radius on a sproc-heavy codebase because sproc-based coupling is invisible to project-reference and namespace tracing. This is the single largest accuracy gap on the WEX codebase.

Phases: Tier 1 signals (CommandType + EXEC + .sql catalog) → Tier 2 (gateway detection + EF patterns) → Tier 3 (config/attributes) → Scatter integration (`--sproc-inventory`, graph edges, SOW matching, PR risk DB dimension).

### Focused SOW index (Initiative 11)
**Status:** Designed, 4 phases not started
**Specs:** [FOCUSED_INDEX_PLAN.md](prototyping_specs/FOCUSED_INDEX_PLAN.md), [FOCUSED_INDEX_BRAINSTORM.md](prototyping_specs/FOCUSED_INDEX_BRAINSTORM.md)
**Tasks:** `tasks.txt` → "INITIATIVE 11: FOCUSED SOW INDEX"

Two-tier index for SOW analysis: Pass 1 narrows to candidate solutions; Pass 2 builds a focused index for just those solutions. Reduces noise and token cost on monolith-scale repos. Built on the (already shipped) Initiative 9 solution-aware graph and Initiative 10 codebase index.

### Pipeline registry (canonical format)
**Status:** Designed, blocked on DevOps repo access
**Spec:** [PIPELINE_REGISTRY_DESIGN.md](prototyping_specs/PIPELINE_REGISTRY_DESIGN.md)
**Tasks:** `tasks.txt` → "PIPELINE REGISTRY"

Replace the parallel CSV (`pipeline_to_app_mapping.csv`) and JSON (`app_to_directory_mapping.json`) with a single canonical YAML registry. Multi-source parsers feed it; staleness metadata exposed. Blocked on access to the DevOps repo with the source pipeline definitions.

### Structural improvements (post-leadership-review)
**Status:** In progress (Phase 5 shipped, Phases 1-4 + 6 outstanding)
**Spec:** [LEADERSHIP_DESIGN_REVIEW.md](prototyping_specs/LEADERSHIP_DESIGN_REVIEW.md)
**Tasks:** `tasks.txt` → "INITIATIVE 7: STRUCTURAL IMPROVEMENTS"

Type safety + API surface (ConsumerResult dataclass cleanup, lowercase `any` fixes, `__contains__` on DependencyGraph), CLI subcommands (`scatter git` / `scatter target` / etc.), graph builder perf (eliminate double file reads, compact serialization), test infrastructure (move into `tests/unit` + `tests/integration`), cleanup of `_legacy.py` shims.

### SOW scoping (Initiative 14)
**Status:** Phase 1 shipped, Phases 2-3 outstanding
**Spec:** [SOW_SCOPING_PLAN.md](prototyping_specs/SOW_SCOPING_PLAN.md)
**Tasks:** `tasks.txt` → "INITIATIVE: SOW SCOPING"

Phase 2: team mapping + risk-driven multipliers (`.scatter.yaml teams:`, CODEOWNERS fallback, per-team risk levels). Phase 3: calibration store (append-only JSONL of predictions vs. actuals, `--record-actual`, `--calibration-report`, activate measured multipliers).

### SOW differentiator polish
**Status:** Phase 1 shipped, Phases 2-3 outstanding
**Spec:** [SOW_DIFFERENTIATOR_PLAN.md](prototyping_specs/SOW_DIFFERENTIATOR_PLAN.md)
**Tasks:** `tasks.txt` → "INITIATIVE 11: SOW DIFFERENTIATOR" (Phase 2-3)

Phase 2: report polish (per-target-not-per-consumer risk text, varied coupling narratives, evaluate Affected Projects table). Phase 3: evaluator experience (worked example walkthrough, harden failure modes, demo script as CI smoke test).

### Multi-repo federated graph — DEFERRED
**Status:** Exploratory brainstorm
**Spec:** [MULTI_REPO_BRAINSTORM.md](prototyping_specs/MULTI_REPO_BRAINSTORM.md)
**Tasks:** `tasks.txt` → "INITIATIVE: MULTI-REPO FEDERATED GRAPH"

Cross-repo blast radius for the post-monolith world. Requires contract-based edge discovery (HTTP, message queues, NuGet) since project references no longer span repo boundaries. Don't start until WEX actually splits a repo.

---

## Cross-cutting

A few non-initiative items in `tasks.txt` worth surfacing:

- **AI prompt security review** — audit all new risk/effort prompts (cross-cutting)
- **JSON output schema versioning** — version header for risk data

---

## Research candidates

Speculative ideas that aren't committed work but are worth tracking. Full write-ups (rationale, fit with existing code, effort estimates, risks) live in [FUTURE_RESEARCH.md](FUTURE_RESEARCH.md). These are intentionally **not** in `tasks.txt` — promoting them there would imply commitment that doesn't yet exist. When one of these graduates to a real initiative, it gets a tasks.txt entry and a roadmap section above.

| Item | Effort | Strongest fit |
|---|---|---|
| **PageRank for architectural centrality** | Small | Risk Engine — additive metric on `ProjectMetrics`, surfaces transitive importance that fan-in misses. Strongest near-term candidate. |
| **Architectural layer enforcement** | Medium | Pairs with `--fail-on` CI gates. Teams declare allowed dependencies in `.scatter.yaml`; Scatter flags violations. |
| **Cyclomatic complexity per type** | Medium | Risk Engine change-surface enrichment. Distinguishes a 10-line data class from a 500-line state machine in the same project. |
| **Token-budgeted AI context assembly** | Medium-large | SOW Scoping Phase 2 — when AI context quality starts mattering more than convenience. |
| **Symbol-level importance scoring** | Large | Defer until project-level PageRank proves the centrality signal is useful. |

PageRank and layer enforcement are the strongest near-term candidates per the FUTURE_RESEARCH.md priority table. Both fit naturally into work already on the roadmap (Risk Engine, CI gates).

---

## Suggested sequencing

Bias: highest WEX impact + lowest blockers first.

1. **Sproc inventory Phase 1** — biggest single SOW accuracy improvement on the WEX codebase, no dependencies. Ship first.
2. **Structural improvements Phase 1** (type safety) and **Phase 2** (CLI subcommands) — code-quality groundwork that makes everything else easier. Cheap, mostly mechanical.
3. **Focused SOW index** — second SOW accuracy pass, after sproc inventory has closed the database-coupling gap.
4. **SOW scoping Phase 2** (team mapping) — small, complements Initiative 11.
5. **SOW differentiator Phase 2-3** — evaluator-facing polish before any external demo.
6. **Sproc inventory Phase 2-3** — driven by coverage gap measured after Phase 1.
7. **Pipeline registry** — when DevOps repo access is unblocked.
8. **SOW scoping Phase 3** (calibration store) — after enough SOWs have run to make calibration meaningful.
9. **Multi-repo** — wait for the trigger event (first WEX repo split).

---

## What's archived

All completed prototyping plans live under [`prototyping_specs/`](prototyping_specs/). They're kept for historical context — every plan in there represents shipped work or design decisions that informed shipped work, with one exception (`MULTI_REPO_BRAINSTORM.md`, the only purely exploratory doc).

The following items appeared in earlier roadmap drafts as "outstanding" but are actually **shipped** per `tasks.txt`:

- Incremental graph updates (Initiative 5 — completed)
- Transparent graph A/B/C (all phases completed)
- Solution-aware graph (Initiative 9 — all 5 phases completed)
- `__main__.py` decomposition (Initiative 8 Phase 1 — completed 2026-03-25)
- Hybrid AST spike + Phase 2 (completed)
- SOW codebase index (Initiative 10 — shipped)
- Risk engine Phases 1-2, PR risk Phases 1-3 (all shipped)
- CI pipeline, mypy baseline, uv packaging (all shipped)

Reference docs that stay in `docs/`: ADR.md, PERSONAS.md, TESTING.md, FUTURE_RESEARCH.md, SOW_SIGNAL_ANALYSIS.md, SPROC_DISCOVERY_BRAINSTORM.md. The runnable SOW example lives at `examples/sample_sow.md`.
