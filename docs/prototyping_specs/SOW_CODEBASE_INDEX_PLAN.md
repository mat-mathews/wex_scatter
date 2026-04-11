# SOW Codebase Index — Implementation Plan

**Initiative:** SOW Target Identification via Compact Codebase Index
**Ref:** Team debate 2026-03-18 (Priya, Devon, Sam, Fatima, Tomas, Kai, Marcus)
**Priority:** Tier 1.9 — critical for --sow mode credibility
**Estimated effort:** 2-3 days across 4 phases
**Depends on:** Dependency graph (shipped), optionally Initiative 9 (solution membership)

---

## Problem Statement

The `--sow` mode asks an LLM to extract .NET project names, class names, and stored
procedure names from a natural-language work request. The LLM receives zero context
about what actually exists in the codebase. It guesses names, and `_resolve_project_name()`
does a substring match against `.csproj` filenames on disk.

This works when the SOW explicitly names code artifacts:

> "Modify PortalDataService in GalaxyWorks.Data to add a parameter to sp_InsertPortalConfiguration"

It fails when the SOW uses business domain language — which is what real SOWs do:

> "Update the portal configuration workflow to support multi-tenant isolation.
> The configuration insert path needs to be tenant-aware, and downstream batch
> jobs that sync portal settings should filter by tenant ID."

No project names. No class names. No sproc names. The LLM hallucinates, the substring
match fails silently, and the user gets either zero targets or wrong targets.

### Root cause

The LLM needs a map between domain language and code artifacts. We don't give it one.
We can't send the whole codebase (300MB for a 500-project monolith). But we already
have a compact representation of the entire codebase: the dependency graph.

---

## Solution: Compact Codebase Index

Build a text index from the dependency graph that maps every project, type, sproc,
namespace, and file name into ~50KB of structured text. Send it alongside the SOW
in the LLM prompt. The LLM matches domain language to real artifacts using the index
as ground truth — it can't hallucinate names that aren't in the index.

### Signals by information density (per token)

| Signal | Source | Example | Cost |
|--------|--------|---------|------|
| **Project names** | `ProjectNode.name` | `GalaxyWorks.Data` | Free (already in graph) |
| **Type declarations** | `ProjectNode.type_declarations` | `PortalDataService`, `TenantConfigurationManager` | Free |
| **Sproc names + owners** | `ProjectNode.sproc_references` | `sp_InsertPortalConfiguration (GalaxyWorks.Data)` | Free |
| **Namespace hierarchy** | `ProjectNode.namespace` | `Company.Billing.Reconciliation` | Free |
| **File names** (stems, not content) | File scan during graph build | `TenantConfigurationManager.cs` in `Services/` | Cheap |
| **Solution membership** | Initiative 9 (when shipped) | `Billing.sln contains Billing.Core, Billing.Data` | Free (after Init 9) |

Items 1-5 fit in ~50KB for a 500-project codebase. Well within a single LLM context
window alongside the SOW text.

---

## Phase 1: Build the Codebase Index (~0.5 day)

### 1.1 Create `scatter/ai/codebase_index.py`

```python
@dataclass
class CodebaseIndex:
    """Compact text representation of a codebase for LLM context."""
    text: str                    # The formatted index string
    project_count: int
    type_count: int
    sproc_count: int
    file_count: int
    size_bytes: int              # Size of the text field

def build_codebase_index(
    graph: DependencyGraph,
    file_names: Optional[Dict[str, List[str]]] = None,  # project -> [file stems]
    solutions: Optional[Dict[str, List[str]]] = None,    # project -> [solution names]
) -> CodebaseIndex:
    """Build a compact codebase index from the dependency graph.

    The index is a structured text string designed to fit in an LLM prompt
    alongside a work request. It provides ground truth for target identification.
    """
```

### 1.2 Index format

The index is plain text, designed for LLM comprehension:

```
=== Codebase Index (247 projects, 2,841 types, 156 stored procedures) ===

PROJECT: GalaxyWorks.Data
  Namespace: GalaxyWorks.Data
  Types: PortalDataService, PortalConfiguration, UserActivityLog, IDataAccessor, StatusType, SystemModule
  Stored procedures: dbo.sp_InsertPortalConfiguration, dbo.sp_GetPortalConfigurationDetails
  Key files: PortalDataService.cs, PortalConfiguration.cs, FakeDatabaseHelper.cs
  Solutions: GalaxyWorks.sln, Master.Build.sln

PROJECT: GalaxyWorks.WebPortal
  Namespace: GalaxyWorks.WebPortal
  Types: PortalController, PortalCacheService
  Key files: PortalController.cs, PortalCacheService.cs
  Solutions: GalaxyWorks.sln

PROJECT: GalaxyWorks.BatchProcessor
  Namespace: GalaxyWorks.BatchProcessor
  Types: SyncJob
  Key files: SyncJob.cs
  Solutions: GalaxyWorks.sln, BatchJobs.sln

...

=== Stored Procedure Cross-Reference ===
dbo.sp_InsertPortalConfiguration -> GalaxyWorks.Data
dbo.sp_GetPortalConfigurationDetails -> GalaxyWorks.Data
dbo.sp_ProcessBillingCycle -> Billing.Data, Billing.Reconciliation
```

### 1.3 File name collection

Type declarations are already on `ProjectNode`. File names are not. Two options:

**Option A (preferred):** During graph build, collect `.cs` file stems per project
(we already iterate all `.cs` files in step 4). Store as `ProjectNode.file_stems: List[str]`.
Small memory cost, available for free on subsequent runs via cache.

**Option B (fallback):** Collect file names on-demand during index build via a quick
glob per project directory. Slower but requires no graph schema change.

Start with Option A. The graph builder already reads every `.cs` file — capturing
the stem is one line of code.

### Tests (Phase 1)
- [ ] Index built from sample projects contains all 8 project names
- [ ] Index contains type declarations for GalaxyWorks.Data (PortalDataService, etc.)
- [ ] Index contains sproc cross-reference section
- [ ] Index contains file stems when provided
- [ ] Index contains solution membership when provided
- [ ] Index size < 100KB for 500-project synthetic codebase
- [ ] Index size < 200KB for 1000-project synthetic codebase
- [ ] Empty graph produces empty index (no crash)

---

## Phase 2: Rewrite the SOW Prompt (~0.5 day)

### 2.1 Update `parse_work_request_with_model()` in `parse_work_request.py`

Replace the current prompt (which gives the LLM zero codebase context) with one
that includes the index:

```python
def parse_work_request_with_model(
    model_instance,
    sow_text: str,
    codebase_index: Optional[CodebaseIndex] = None,  # NEW
) -> Optional[List[Dict]]:
```

New prompt structure:

```
You are analyzing a work request against a .NET codebase. Below is a complete
index of every project, type, and stored procedure in the codebase. Use ONLY
names that appear in this index — do not invent project or class names.

{codebase_index.text}

---

Given the following work request, identify which projects, classes, and stored
procedures are likely affected. For each target, explain WHY you matched it
(which words in the work request correspond to which artifacts in the index).

Work request:
{sow_text}

Return a JSON array of objects:
- "type": "project", "sproc", or "class"
- "name": exact name from the index (not invented)
- "class_name": (optional) specific class from the index
- "method_name": (optional) method if mentioned in the SOW
- "confidence": 0.0-1.0
- "match_evidence": one sentence explaining what SOW language matched what index entry

Rules:
- ONLY return names that appear in the codebase index above
- If the work request is vague and many projects could be affected, return
  the most likely 5-10 with lower confidence scores
- If nothing in the index matches the work request, return an empty array
- Confidence 1.0 = exact name match; 0.7 = strong domain match; 0.4 = possible match
```

### 2.2 Backward compatibility

When no graph is available (first run, or `--no-graph`), fall back to the current
prompt without index. Log a warning: "No codebase index available — SOW target
identification will be less accurate. Run once with graph enabled for better results."

### Tests (Phase 2)
- [ ] Prompt includes codebase index when provided
- [ ] Prompt falls back to original when index is None
- [ ] Mock LLM response includes match_evidence field
- [ ] Response with names not in the index is flagged/filtered
- [ ] Vague SOW returns multiple targets with lower confidence

---

## Phase 3: Ambiguity Detection & Evidence Surfacing (~1 day)

### 3.1 Add match_evidence to AnalysisTarget

```python
@dataclass
class AnalysisTarget:
    # ... existing fields ...
    match_evidence: Optional[str] = None  # NEW: why the LLM matched this target
```

### 3.2 Ambiguity warning in impact report

When the LLM returns results, classify the response quality:

```python
@dataclass
class TargetParseQuality:
    """Assessment of how well the SOW mapped to code artifacts."""
    target_count: int
    avg_confidence: float
    high_confidence_count: int    # confidence >= 0.7
    low_confidence_count: int     # confidence < 0.4
    ambiguity_level: str          # "clear", "moderate", "vague"
```

- **clear**: <= 5 targets, avg confidence >= 0.7
- **moderate**: 6-10 targets, or avg confidence 0.4-0.7
- **vague**: > 10 targets, or avg confidence < 0.4

Surface in the impact report header:

```
=== Impact Analysis Report ===
Work Request: Update the portal configuration workflow...
Target Quality: moderate (7 targets, avg confidence 0.62)
  Matched: GalaxyWorks.Data / PortalDataService (0.9) — "portal configuration" matches type name
  Matched: GalaxyWorks.BatchProcessor / SyncJob (0.7) — "batch jobs that sync portal settings"
  Guessed: Billing.Data (0.3) — weak match on "configuration"
```

### 3.3 Filter low-confidence targets

Add a `--sow-min-confidence` flag (default: 0.3). Targets below this threshold are
logged but excluded from analysis. This prevents a vague SOW from triggering analysis
on 50 projects.

### Tests (Phase 3)
- [ ] match_evidence populated from LLM response
- [ ] TargetParseQuality computed correctly for clear/moderate/vague scenarios
- [ ] Ambiguity warning appears in console output
- [ ] --sow-min-confidence filters low-confidence targets
- [ ] Filtered targets logged as "excluded due to low confidence"
- [ ] JSON output includes match_evidence and parse quality

---

## Phase 4: Wire Into the Pipeline (~0.5 day)

### 4.1 Build index during impact analysis

In `run_impact_analysis()`, before calling `parse_work_request()`:

1. Load or build the graph (already happens via transparent graph acceleration)
2. Call `build_codebase_index(graph, file_names, solutions)` to build the index
3. Pass the index to `parse_work_request()`

### 4.2 Add `--dump-index` debug flag (Kai's suggestion)

`scatter --dump-index --search-scope .` prints the codebase index to stdout and exits.
Useful for debugging when SOW parsing gives unexpected results. Also useful for
reviewing what the LLM will see.

### 4.3 Add file stems to ProjectNode

In `graph_builder.py`, during step 4 where we already iterate all `.cs` files per
project, collect file stems:

```python
# Already reading the file for type extraction — just capture the stem
file_stems_by_project[project_name].append(cs_path.stem)
```

Store as `ProjectNode.file_stems: List[str]` (sorted, deduplicated).

### Tests (Phase 4)
- [ ] End-to-end: SOW with domain language against sample projects, verify correct targets
- [ ] End-to-end: SOW with exact project names still works (regression)
- [ ] --dump-index prints index to stdout
- [ ] file_stems populated during graph build
- [ ] file_stems survive cache roundtrip
- [ ] Backward compat: no graph available falls back to original prompt

---

## Files Modified

| File | Change |
|------|--------|
| **NEW** `scatter/ai/codebase_index.py` | CodebaseIndex dataclass, build_codebase_index() |
| `scatter/ai/tasks/parse_work_request.py` | Accept CodebaseIndex, rewrite prompt, add match_evidence parsing |
| `scatter/core/models.py` | Add match_evidence to AnalysisTarget, add TargetParseQuality |
| `scatter/core/graph.py` | Add file_stems to ProjectNode |
| `scatter/analyzers/graph_builder.py` | Collect file stems during step 4 |
| `scatter/analyzers/impact_analyzer.py` | Build index, pass to parser, compute parse quality |
| `scatter/reports/console_reporter.py` | Display match evidence and ambiguity warning |
| `scatter/reports/json_reporter.py` | Include match_evidence and parse quality in output |
| `scatter/cli_parser.py` | Add --sow-min-confidence and --dump-index flags |
| `scatter/cli.py` | Wire --dump-index, pass min_confidence |
| **NEW** `test_codebase_index.py` | Index building, size constraints, format validation |
| `test_impact_analysis.py` | Updated mocks for new prompt format, evidence, quality |

---

## What This Does NOT Include

- **RAG / vector search.** The codebase index is small enough to fit in a single prompt.
  Vector search adds infrastructure complexity for no gain at our scale. Revisit if
  codebases exceed 2000 projects (where the index might hit context limits).
- **Code content in the index.** We send names and structure, not implementation.
  Sending method bodies would balloon the index past context limits.
- **Multi-turn refinement.** "The LLM wasn't sure, so ask follow-up questions."
  Adds latency and complexity. Start with single-shot, add refinement if accuracy
  data warrants it.
- **Caching the index.** The index is built from the graph in milliseconds. No need
  to persist it separately.

---

## Success Metrics

Before this change: SOW mode requires exact .NET project/class/sproc names to work.
A SOW written in business domain language produces zero or wrong targets.

After this change:
- SOW with business domain language correctly identifies targets in >80% of cases
  (measured against sample projects + synthetic codebases)
- match_evidence lets users understand and verify the LLM's reasoning
- ambiguity warnings prevent silent failures on vague SOWs
- --dump-index gives full visibility into what the LLM sees

## Risk Assessment

**Low risk.** This is a prompt engineering change with a small supporting data structure.
The fallback to the original prompt (when no graph exists) means no regression. The
index is derived from data we already have. No new external dependencies.

The main risk is **LLM response quality.** The prompt is longer (50KB index + SOW vs
just SOW), which could affect response time and quality. Mitigated by: the index is
structured text (not code), Gemini handles large prompts well, and we strip the index
on fallback if the prompt is too large.
