# SOW Differentiator — Implementation Plan

**Branch:** feature/sow-differentiator
**Status:** Ready to implement
**Date:** 2026-03-22
**Team review:** 2026-03-22 (Priya, Marcus, Anya, Sam, Fatima, Kai)
**Depends on:** CI pipeline (shipped), codebase index (shipped, Initiative 10)

---

## Goal

Get the SOW/impact analysis differentiator into evaluators' hands. Two
parallel efforts:

- **Effort A**: End-to-end CLI tests for SOW/impact mode
- **Effort B**: Polish the markdown report into a shareable artifact

Both efforts share a foundation of test fixtures and sample data.

---

## Current State

### What works
- 6-step LLM pipeline: SOW parse → consumer trace → risk → coupling →
  complexity → narrative
- 5 output formats: console, JSON, CSV, markdown, pipelines
- Codebase index grounds LLM against real project/type/sproc names
- BFS transitive tracing with confidence decay (1.0 → 0.6 → 0.3)
- Graph enrichment (coupling score, fan-in/out, instability, cycle membership)
- 70+ unit tests covering all AI tasks, data models, reporters, and tree views

### What's missing
- **No e2e test invokes `main()` or `run_impact_analysis()` against the sample
  .NET projects with real file discovery.** All existing tests use synthetic
  fixtures — no test proves the feature works on actual .csproj files on disk.
- **Markdown report is functional but not compelling.** No executive summary
  block, no total counts, no "what to do next" guidance. The blast radius tree
  is in a code block (good) but the report doesn't lead with the punchline.
- **No demo script.** Evaluators have to read docs to figure out how to try it.

---

## Implementation Sequence

Design the new markdown structure first. Write tests asserting the *new*
output structure from the start — tests are the spec, not a snapshot of
today's output. Tests start red, reporter changes make them green. (Priya)

### Step 1: Design markdown output structure on paper
- Finalize the new section names, order, and content (Effort B design)
- This informs what the e2e tests assert

### Step 2: Shared test fixtures and mock AI provider
- Create `test_impact_e2e.py` with fixtures (A2)
- Build `MOCK_RESPONSES` dict (A4)
- Verify mock provider dispatches correctly

### Step 3: All e2e tests (Effort A) — asserting new output structure
- Write all 20 tests at once (A3)
- Tests assert the *new* markdown structure (sections, names, content)
- Core pipeline tests pass immediately (they test data, not output format)
- Output format tests may start red until step 5-7 land

### Step 4: Executive summary + narrative placement (Effort B)
- Modify `build_impact_markdown()` in `markdown_reporter.py`
- Add summary stats computation (pure data, no AI)
- Place narrative *before* stats table (Sam) — prose first, numbers second
- Rename sections: "Consumer Detail" → "Affected Projects" (Sam)

### Step 5: Target confidence, evidence, and tree polish (Effort B)
- Add confidence/evidence line to each target section in markdown
- Add risk + pipeline inline in tree nodes (B3)
- Update console reporter to match

### Step 6: Next Steps footer (Effort B)
- Add template-driven "Next Steps" section to markdown (B4)
- Observational wording, not prescriptive (Fatima)
- Console output does not get this section — it's a document artifact

### Step 7: Demo script
- Create `tools/demo-impact.sh` (Kai)
- Works with or without API key

### Step 8: Verify all tests pass
- Run `bash tools/check.sh`
- All existing 789 tests still pass
- All 20 new e2e tests pass
- Ruff + mypy clean

---

## Effort A: End-to-End CLI Tests

### A1. Test file: `test_impact_e2e.py`

New test file at repo root. Tests invoke the real analysis pipeline against the
sample .NET projects (GalaxyWorks.Data, MyDotNetApp, etc.) that ship with the
repo. No mocks for file discovery, project scanning, or consumer detection —
only mock the AI provider (no API keys in CI).

### A2. Shared fixtures

```python
@pytest.fixture
def search_scope():
    """Repo root — contains the 8 sample .NET projects."""
    return Path(__file__).parent

@pytest.fixture
def mock_ai_provider():
    """AI provider that returns deterministic responses for all task types."""
    provider = MagicMock()
    provider.supports.return_value = True
    # Deterministic responses for each task type...
    return provider

@pytest.fixture
def galaxyworks_sow():
    """SOW text that targets GalaxyWorks.Data.PortalDataService."""
    return "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation parameter"

@pytest.fixture
def vague_sow():
    """SOW text using business language, not exact code names."""
    return "Add multi-tenant support to the portal data access layer"

@pytest.fixture
def no_match_sow():
    """SOW text that won't match any project."""
    return "Migrate the billing microservice to Kubernetes"
```

### A3. Test cases

Each test calls `run_impact_analysis()` with the real `search_scope` (repo
root with sample projects) and a mock AI provider. The mock returns
deterministic `parse_work_request` responses pointing at known sample projects,
so the downstream file discovery, consumer detection, and transitive tracing
all run against real files.

Assert on structure, not exact strings. Assert `len(report.targets[0].consumers)`
not `"Found 4 consumer(s)"`. Assert section headers present in markdown, not
exact paragraph text. (Anya)

#### Core pipeline tests

| Test | What it proves |
|------|---------------|
| `test_sow_finds_galaxyworks_consumers` | SOW targeting GalaxyWorks.Data finds 4 known consumers (MyGalaxyConsumerApp, MyGalaxyConsumerApp2, GalaxyWorks.Api, GalaxyWorks.BatchProcessor) |
| `test_sow_finds_mydotnetapp_consumer` | SOW targeting MyDotNetApp finds 1 consumer (MyDotNetApp.Consumer) |
| `test_sow_no_consumers_for_isolated_project` | SOW targeting MyDotNetApp2.Exclude finds 0 consumers |
| `test_sow_with_class_filter` | SOW targeting PortalDataService class narrows results correctly |
| `test_sow_with_sproc_target` | SOW targeting dbo.sp_InsertPortalConfiguration finds sproc consumers |
| `test_transitive_depth` | Consumers at depth > 0 have correct confidence decay and propagation_parent |
| `test_impact_report_structure` | ImpactReport has all expected fields populated (targets, risk, complexity, narrative) |

#### Output format tests

| Test | What it proves |
|------|---------------|
| `test_markdown_output_has_all_sections` | `build_impact_markdown(report)` contains: `## Summary`, `## Targets`, `### Blast Radius`, `### Affected Projects`, `### Next Steps` |
| `test_markdown_summary_has_stats` | Summary section contains risk, complexity, consumer counts, pipeline names |
| `test_json_output_roundtrips` | `write_impact_json_report()` → read back → all fields present and correct types |
| `test_csv_output_has_all_columns` | `write_impact_csv_report()` → read back → expected column count and headers |
| `test_console_output_runs` | `print_impact_report(report)` completes without error, output contains target names |

#### No-AI and resilience tests

| Test | What it proves |
|------|---------------|
| `test_sow_no_ai_provider_still_traces` | `ai_provider=None` — core consumer tracing still works, blast radius tree populated, no crash. Risk/coupling/narrative fields are None but report is valid. (Marcus) |
| `test_report_without_enrichment` | Report renders correctly in all formats when risk/coupling/narrative fields are all None |
| `test_graph_enrichment_populates_metrics` | When graph is available, consumers get coupling_score, fan_in, etc. |
| `test_sow_determinism` | Run same analysis twice with same mock → identical outputs. Catches non-determinism from dict/set ordering or parallel execution. (Anya) |

#### Error handling tests (Fatima)

| Test | What it proves |
|------|---------------|
| `test_ai_parse_returns_empty` | AI returns empty target list → report has 0 targets, clear log message |
| `test_ai_parse_returns_invalid_json` | AI returns garbage → graceful fallback, empty targets, no traceback |
| `test_ai_risk_fails_midway` | Risk assessment fails for one target → other targets still have results |
| `test_nonexistent_project_in_sow` | AI returns a project name that doesn't exist on disk → target preserved with low confidence, logged warning |
| `test_ai_provider_partial_support` | Provider supports WORK_REQUEST_PARSING but not RISK_ASSESSMENT → report has targets and consumers, risk fields are None, no crash (Fatima) |
| `test_large_sow_text` | 10,000-character SOW → no crash, SOW truncated in display, prompt construction works (Fatima) |

### A4. Deterministic AI mock responses

The mock AI provider needs canned responses for each task type. These are
defined once in the fixture and reused across tests:

```python
MOCK_RESPONSES = {
    AITaskType.WORK_REQUEST_PARSING: json.dumps([{
        "type": "project",
        "name": "GalaxyWorks.Data",
        "class_name": "PortalDataService",
        "confidence": 0.95,
        "match_evidence": "SOW mentions PortalDataService which exists in GalaxyWorks.Data"
    }]),
    AITaskType.RISK_ASSESSMENT: json.dumps({
        "rating": "Medium",
        "justification": "4 direct consumers including API and batch processor",
        "concerns": ["Breaking API contract", "Batch job disruption"],
        "mitigations": ["Feature flag", "Staged rollout"]
    }),
    AITaskType.COUPLING_NARRATIVE: json.dumps({
        "narrative": "Direct class instantiation of PortalDataService in the consumer.",
        "vectors": ["Direct instantiation", "Method call"]
    }),
    AITaskType.COMPLEXITY_ESTIMATE: json.dumps({
        "rating": "Medium",
        "justification": "Moderate blast radius with 4 consumers",
        "effort_estimate": "3-5 developer-days",
        "factors": ["Multiple consumers", "API contract change"]
    }),
    AITaskType.IMPACT_NARRATIVE: json.dumps({
        "narrative": "This change to PortalDataService affects 4 consuming projects across the GalaxyWorks ecosystem. The primary risk is breaking the API contract used by consumer applications and the batch processor."
    }),
}
```

The mock dispatches based on `task_type` argument to `provider.analyze()`.
This gives every test a complete, realistic ImpactReport to assert against.

---

## Effort B: Polish Markdown Report

### B1. Executive summary block

The markdown report currently jumps straight into per-target details. Add an
executive summary block at the top that gives evaluators the punchline in
3 seconds.

**Current structure:**
```markdown
# Impact Analysis

**Work Request:** Modify PortalDataService...

**Overall Risk:** Medium | **Complexity:** Medium (3-5 developer-days)

## GalaxyWorks.Data
...
```

**New structure:**
```markdown
# Impact Analysis

**Work Request:** Modify PortalDataService in GalaxyWorks.Data to add tenant
isolation parameter

## Summary

This change to PortalDataService affects 4 consuming projects across the
GalaxyWorks ecosystem. The primary risk is breaking the API contract used
by consumer applications and the batch processor.

| Metric | Value |
|--------|-------|
| Risk | Medium |
| Complexity | Medium (3-5 developer-days) |
| Direct consumers | 4 |
| Transitive consumers | 1 |
| Pipelines affected | cdh-galaxyworks-az-cd, cdh-batch-az-cd |
| Identification confidence | Clear (1 target, avg 0.95) |

## Targets

### GalaxyWorks.Data
...
```

Key decisions:
- **Narrative before stats** — prose first, numbers second (Sam)
- **Proper `Metric | Value` table** — no empty header columns (Sam)
- **"Identification confidence"** instead of "Target Quality" — less jargon (Sam)
- Summary block is computed from the report dataclass — no AI call needed.
  Aggregates: total direct/transitive consumers across all targets, unique
  pipeline names, risk/complexity ratings.

### B2. Target confidence and evidence

Each target section shows the AI's confidence and evidence for why it was
identified. Builds trust — evaluators see the LLM's reasoning:

**Current:**
```markdown
## GalaxyWorks.Data

Direct Consumers: 2 | Transitive: 1
```

**New:**
```markdown
### GalaxyWorks.Data

**Confidence:** 0.95 (HIGH) — SOW mentions PortalDataService which exists in GalaxyWorks.Data

Direct Consumers: 2 | Transitive: 1
```

### B3. Blast radius tree improvements

The tree already renders well. Minor improvements:

- Add risk rating inline with each consumer node in the tree:
  ```
  ├── MyGalaxyConsumerApp [HIGH] direct (Risk: Medium)
  ```
- Add pipeline name on the same line when available:
  ```
  ├── GalaxyWorks.Api [HIGH] direct (Risk: Medium) → cdh-api-az-cd
  ```

This makes the tree self-contained — you don't need to cross-reference the
detail table to get the important information.

### B4. "Next Steps" footer

After the targets section, add template-driven guidance. Called "Next Steps"
not "Recommendations" — scatter observes, the engineer decides. (Sam, Fatima)

```markdown
## Next Steps

- Review the **4 direct consumers** listed above for breaking changes
- Coordinate deployment with pipeline owners for: cdh-galaxyworks-az-cd, cdh-batch-az-cd
- Blast radius suggests staged rollout may reduce risk
```

Wording is observational, not prescriptive. (Fatima)

| Condition | Next Step |
|-----------|-----------|
| Any consumers | "Review the N direct consumers listed above for breaking changes" |
| Pipeline names present | "Coordinate deployment with pipeline owners for: ..." |
| Risk >= Medium | "Blast radius suggests staged rollout may reduce risk" |
| Risk >= High | "Consider a design review before proceeding" |
| Transitive consumers > 0 | "Verify transitive consumers (depth > 0) are not affected by contract changes" |
| Ambiguity = vague | "Target identification has low confidence — verify targets before acting on this report" |

### B5. Section renaming

| Current | New | Why |
|---------|-----|-----|
| "Consumer Detail" | "Affected Projects" | Less jargon, immediately clear (Sam) |
| "Target Quality" | (row in summary table: "Identification confidence") | Not a separate section — it's a stat (Sam) |
| "Recommendations" | "Next Steps" | Observational, not prescriptive (Sam, Fatima) |

### B6. Console reporter alignment

Update `print_impact_report()` to mirror the markdown improvements:
- Print summary stats block at the top (risk, complexity, counts)
- Print target confidence + evidence
- Risk rating inline in tree output (already partially there via `render_tree`)

The console output does not get the "Next Steps" footer — that's a
markdown/document artifact.

---

## Demo Script

### `tools/demo-impact.sh` (Kai)

```bash
#!/bin/bash
# Demonstrate scatter's impact analysis on the sample .NET projects.
# Works without an API key (shows blast radius tree).
# With a GOOGLE_API_KEY, shows full AI-enriched report.
# Windows: run from Git Bash (included with Git for Windows).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Scatter Impact Analysis Demo"
echo "============================"
echo ""
echo "SOW: Modify PortalDataService in GalaxyWorks.Data to add tenant isolation"
echo ""

uv run scatter \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add tenant isolation parameter" \
  --search-scope "$REPO_ROOT" \
  --output-format markdown
```

If no API key: evaluator still sees the blast radius tree (consumer tracing is
pure code). If API key is set: full enriched report with risk, coupling
narratives, complexity estimate, and executive summary.

---

## Files Changed

| File | Change | Effort |
|------|--------|--------|
| **NEW** `test_impact_e2e.py` | 20 end-to-end tests with real sample projects | A |
| **NEW** `tools/demo-impact.sh` | One-command demo for evaluators | — |
| `scatter/reports/markdown_reporter.py` | Executive summary, narrative placement, target evidence, tree polish, next steps, section renames | B |
| `scatter/reports/console_reporter.py` | Summary stats block, target evidence, tree risk inline | B |
| `test_impact_analysis.py` | Update markdown/console test assertions for new structure | A+B |

### Files NOT changed
- `scatter/analyzers/impact_analyzer.py` — no pipeline changes
- `scatter/ai/tasks/*.py` — no prompt changes
- `scatter/core/models.py` — no dataclass changes
- `scatter/reports/json_reporter.py` — JSON structure unchanged
- `scatter/reports/csv_reporter.py` — CSV structure unchanged

---

## Test Count

| Category | New tests |
|----------|-----------|
| Core pipeline e2e | 7 |
| Output format e2e | 5 |
| No-AI and resilience | 4 |
| Error handling (Fatima) | 6 |
| **Total new** | **20** |
| Existing tests modified | ~3-5 (markdown/console assertion updates) |

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| Write tests asserting *new* structure from day one | Tests are the spec, not a snapshot. Avoids write-then-break cycle. | Priya |
| Test with `ai_provider=None` | Core tracing must work without AI. Evaluators may not have API keys. | Marcus |
| Assert on structure, not exact strings | `len(consumers) == 4` not `"Found 4"`. Section headers present, not paragraph text. | Anya |
| Add determinism test | Same input twice → identical output. Catches ordering bugs. | Anya |
| Add partial AI support test | Provider supports some tasks but not others → graceful degradation. | Fatima |
| Add large SOW text test | 10K chars → no crash, proper truncation. | Fatima |
| Observational "Next Steps" wording | "Blast radius suggests..." not "You should...". Scatter observes, engineer decides. | Fatima, Sam |
| Narrative before stats table | Lead with prose, follow with numbers. Evaluators read paragraphs first. | Sam |
| `Metric | Value` table headers | Proper markdown table, not empty-header hack. Renders correctly everywhere. | Sam |
| Rename to "Affected Projects", "Next Steps" | Drop jargon. Immediately clear to someone seeing scatter for the first time. | Sam |
| Demo script works without API key | Core tracing is pure code — blast radius tree always works. AI adds enrichment. | Kai, Marcus |

---

## Risk

**Low.** Effort A is purely additive (new test file). Effort B modifies only
the markdown and console reporters — the analysis pipeline, AI tasks, data
models, JSON reporter, and CSV reporter are untouched. Existing tests for
markdown output will need assertion updates, but those are mechanical.

The e2e tests will catch any regression from the reporter changes immediately.

---

## Success Criteria

1. `test_impact_e2e.py` proves the SOW → impact pipeline works end-to-end
   on real sample projects (not just synthetic fixtures)
2. Running `scatter --sow "Modify PortalDataService..." --search-scope . --output-format markdown`
   produces a report that an evaluator can paste into a PR or Confluence page
   and it looks professional, scannable, and actionable
3. Core tracing works without an API key — blast radius tree shows even when
   AI enrichment is unavailable
4. `bash tools/check.sh` passes (all existing + new tests, ruff, mypy)
