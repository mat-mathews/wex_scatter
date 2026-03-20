# Focused SOW Index — Implementation Plan

**Initiative:** Two-Tier Solution-Scoped Index for SOW Analysis
**Ref:** Team brainstorm 2026-03-19 (Priya, Marcus, Tomas, Fatima, Sam) — see [FOCUSED_INDEX_BRAINSTORM.md](FOCUSED_INDEX_BRAINSTORM.md)
**Priority:** Follows Initiative 9 (Solution-Aware Graph) Phase 1-2
**Estimated effort:** 2-3 days across 4 phases
**Depends on:** Initiative 9 Phase 1 (solution parsing), Initiative 10 (codebase index — shipped)

---

## Problem Statement

The `--sow` mode sends the entire codebase index to the LLM. For a 500-project monolith
this works (the index fits in ~50KB), but it's noisy. The LLM sees 500 projects when
the SOW only touches 3 solutions (maybe 70 projects). This dilutes the LLM's attention
and increases the chance of false-positive target extraction.

Real-world scenario at WEX: a monolith contains 3 portals (admin, employer, consumer)
and several apps (e.g., CDEX — a data exchange API). A SOW comes in that the team knows
is admin + employer work. But CDEX has 6 project references from admin portal projects.
The team might not realize they need to test CDEX too.

### What we need

1. **Focus**: Give the LLM a tight index scoped to relevant solutions, not the whole monolith
2. **Discovery**: Don't let the user's assumptions blind the tool — surface non-obvious
   blast radius via cross-solution coupling signals
3. **Control**: Let users who know exactly what they want skip AI discovery and filter directly

---

## Solution: Two-Tier Index with Solution-Level Discovery

### Tier 1: Solution Summaries (~20 lines for the whole monolith)

A compact, auto-generated summary of each solution containing:
- Solution name and project count
- Top 5-10 most distinctive type names (semantic anchors for the LLM)
- Top stored procedures
- Cross-solution edge counts (the discovery signal)

```
=== Solution Index (8 solutions, 247 projects) ===
SOL=Solution P=ProjectCount T=TopTypes SP=TopSprocs REF=CrossSolutionEdges

SOL:AdminPortal P:34 T:AdminController,UserManagementService,ConfigEditor,RoleAuthorizationFilter,AdminAuditLogger SP:sp_GetAdminConfig,sp_UpdateUserRole REF->EmployerPortal(3) REF->CDEX(6) REF->GWS.Core(34)
SOL:EmployerPortal P:28 T:EmployerDashboard,BenefitPlanService,EnrollmentWorkflow,PlanComparisonEngine SP:sp_GetEmployerPlans,sp_ProcessEnrollment REF->AdminPortal(2) REF->CDEX(4) REF->GWS.Core(28)
SOL:ConsumerPortal P:22 T:ConsumerAccountView,ClaimStatusService,CardBalanceWidget SP:sp_GetConsumerClaims REF->GWS.Core(22)
SOL:CDEX P:12 T:DataExchangeController,CDEXClient,ExchangeJobRunner,FileTransferService,EnrollmentFeedProcessor SP:sp_QueueExchange,sp_GetPendingFeeds REF->GWS.Core(12)
SOL:GWS.Core P:45 T:PortalDataService,TenantContext,AuditFramework,CacheManager SP:sp_InsertPortalConfiguration
```

Key insight: the `REF->CDEX(6)` on AdminPortal tells the LLM (and the user) that admin
is heavily coupled to CDEX even if the SOW never mentions data exchange.

### Tier 2: Focused Project Index (same format as today, scoped to selected solutions)

The existing `build_codebase_index()` output, filtered to only include projects
belonging to the selected solutions. For 3 solutions averaging 25 projects each, this
is ~75 projects instead of 247 — a 70% reduction in index size.

---

## Phase 1: Solution Summary Builder (~0.5 day)

**Depends on:** Initiative 9 Phase 1 (SolutionInfo parsing) and Phase 2 (solution
membership on ProjectNode)

### 1.1 Create `scatter/ai/solution_index.py`

```python
@dataclass
class SolutionSummary:
    """Compact summary of a solution for Tier 1 index."""
    name: str
    project_count: int
    top_types: List[str]        # most distinctive type names
    top_sprocs: List[str]       # stored procedures
    cross_solution_refs: Dict[str, int]  # solution_name -> edge count

def build_solution_summaries(
    graph: DependencyGraph,
    max_types: int = 10,
    max_sprocs: int = 5,
) -> List[SolutionSummary]:
    """Build compact solution-level summaries from the graph.

    Groups ProjectNodes by their solution membership, aggregates types
    and sprocs, and counts cross-solution ProjectReference edges.
    """

def format_solution_index(summaries: List[SolutionSummary]) -> str:
    """Format summaries into compact text for LLM prompt."""
```

### 1.2 Type selection heuristic

Not all types are equally useful as semantic anchors. Prefer types that:
- Appear in only one solution (distinctive, not shared utilities)
- Have names longer than 3 characters (skip `T`, `ID`, etc.)
- Are classes or interfaces, not enums (richer semantic signal)

Simple scoring: `score = 1.0 if unique_to_solution else 0.3`, then take top N by score.

### 1.3 Cross-solution edge aggregation

For each solution, iterate its projects' outgoing `ProjectReference` edges. For each
edge target, look up which solution the target belongs to. Increment the counter for
that target solution. Projects belonging to no solution are grouped under `(unaffiliated)`.

This is O(edges) — fast, no LLM needed, purely graph-derived.

### Tests (Phase 1)
- [ ] Solution summary includes correct project count
- [ ] Top types are selected by distinctiveness (unique-to-solution preferred)
- [ ] Cross-solution edge counts match manual calculation
- [ ] Projects in no solution are excluded from solution summaries (but included in Tier 2)
- [ ] Format output is parseable and under 2KB for 10 solutions

---

## Phase 2: Focused Index Filter (~0.5 day)

### 2.1 Add solution filter to `build_codebase_index()`

```python
def build_codebase_index(
    graph: DependencyGraph,
    search_scope: Optional[Path] = None,
    solution_filter: Optional[Set[str]] = None,  # NEW
) -> CodebaseIndex:
```

When `solution_filter` is provided, `graph.get_all_nodes()` results are filtered to
only include nodes where `node.solutions` intersects `solution_filter`. Nodes with
empty `solutions` (unaffiliated projects) are excluded.

This is the mechanical piece — small change, high leverage.

### 2.2 Add `--solutions` CLI flag

```python
parser.add_argument(
    "--solutions",
    type=str,
    help="Comma-separated solution names to scope the analysis "
         "(e.g., AdminPortal,EmployerPortal). Skips AI solution discovery.",
)
```

Compatible with `--sow` mode only. When provided, builds a focused index from just
those solutions and proceeds directly to target extraction (skips Pass 1).

### Tests (Phase 2)
- [ ] `solution_filter` correctly limits index to matching projects
- [ ] Projects in multiple solutions included if any solution matches
- [ ] Empty `solution_filter` (set()) returns empty index
- [ ] `None` filter returns full index (backward compat)
- [ ] `--solutions` flag parses comma-separated values correctly
- [ ] `--solutions` without `--sow` raises error

---

## Phase 3: LLM Pass 1 — Solution Discovery (~1 day)

### 3.1 Create `scatter/ai/tasks/select_solutions.py`

New AI task that takes a SOW and solution index, returns selected solutions:

```python
@dataclass
class SolutionSelection:
    """LLM's assessment of which solutions a SOW touches."""
    name: str
    confidence: float           # 0.0-1.0
    reason: str                 # why selected (for user transparency)
    match_type: str             # "direct" | "coupled" | "semantic"

def select_solutions(
    sow_text: str,
    solution_index: str,
    ai_provider: AIProvider,
    min_confidence: float = 0.3,
) -> List[SolutionSelection]:
```

### 3.2 Prompt design

The prompt instructs the LLM to:

1. Read the SOW and identify domain concepts (authentication, enrollment, data feeds, etc.)
2. Match domain concepts to solutions using type names as semantic anchors
3. Check cross-solution edges: if a directly-matched solution has high edge counts to
   another solution, flag the coupled solution too
4. Return each solution with confidence and reasoning

```
You are analyzing a Statement of Work against a solution index.

SOLUTION INDEX:
{solution_index_text}

STATEMENT OF WORK:
{sow_text}

For each solution, assess whether the SOW likely requires changes to projects
in that solution. Consider:
- Direct semantic matches (SOW mentions concepts that align with solution types)
- Coupled solutions (high cross-solution edge counts from directly matched solutions)
- Stored procedure overlap

Return JSON array of selected solutions with confidence and reasoning.
```

### 3.3 Auto-include coupled solutions (graph-based, no LLM)

After the LLM returns its selections, apply a graph-based expansion:

For each selected solution with confidence >= 0.5, check its cross-solution edges.
If any edge count exceeds a threshold (default: 3), auto-include that target solution
at reduced confidence (0.5x the source's confidence, minimum 0.3).

This is the safety net Fatima asked about. Even if the LLM misses CDEX, the fact that
AdminPortal has 6 edges into CDEX will pull it in automatically.

### Tests (Phase 3)
- [ ] Mock LLM returns expected solution selections for sample SOW
- [ ] Auto-include expands to coupled solutions above threshold
- [ ] Auto-include does not double-add solutions LLM already selected
- [ ] Min confidence filter removes low-confidence solutions
- [ ] Confidence decay applied to auto-included solutions

---

## Phase 4: Orchestration and UX (~0.5 day)

### 4.1 Two-pass orchestration in `__main__.py`

When `--sow` is used without `--solutions`:

```python
# Pass 1: Solution discovery
solution_summaries = build_solution_summaries(graph)
solution_index_text = format_solution_index(solution_summaries)
selections = select_solutions(sow_text, solution_index_text, ai_provider)
selections = auto_include_coupled(selections, solution_summaries, threshold=3)

# Display selections to user
print_solution_selections(selections)

# Pass 2: Focused target extraction (existing flow)
solution_filter = {s.name for s in selections if s.confidence >= min_confidence}
codebase_index = build_codebase_index(graph, search_scope, solution_filter=solution_filter)
# ... continue with existing impact analysis ...
```

When `--solutions` is provided:

```python
# Skip Pass 1, go straight to focused index
solution_filter = set(args.solutions.split(","))
codebase_index = build_codebase_index(graph, search_scope, solution_filter=solution_filter)
# ... continue with existing impact analysis ...
```

### 4.2 Console output for solution discovery

```
=== Solution Discovery ===
Analyzed 8 solutions (247 projects total)

Selected solutions:
  + AdminPortal      (high confidence)   34 projects — direct semantic match: "admin user authentication"
  + EmployerPortal   (high confidence)   28 projects — direct semantic match: "employer enrollment changes"
  ! CDEX             (medium confidence) 12 projects — coupled: 6 project refs from AdminPortal, 4 from EmployerPortal

Focused index: 74 projects across 3 solutions (70% reduction from full index)

=== Impact Analysis ===
... (existing output) ...
```

### 4.3 JSON output extension

```json
{
  "solution_discovery": {
    "total_solutions": 8,
    "total_projects": 247,
    "selected_solutions": [
      {
        "name": "AdminPortal",
        "confidence": 0.9,
        "reason": "direct semantic match: admin user authentication",
        "match_type": "direct",
        "project_count": 34
      },
      {
        "name": "CDEX",
        "confidence": 0.55,
        "reason": "coupled: 6 project refs from AdminPortal",
        "match_type": "coupled",
        "project_count": 12
      }
    ],
    "focused_project_count": 74,
    "reduction_pct": 70
  },
  "targets": [ ... ],
  "consumers": [ ... ]
}
```

### Tests (Phase 4)
- [ ] Two-pass flow produces correct focused index
- [ ] `--solutions` flag skips Pass 1
- [ ] Console output shows selection reasoning
- [ ] JSON output includes `solution_discovery` section
- [ ] Backward compat: `--sow` without solutions and without `.sln` files uses full index

---

## Files Modified

| File | Change |
|------|--------|
| **NEW** `scatter/ai/solution_index.py` | SolutionSummary, builder, formatter |
| **NEW** `scatter/ai/tasks/select_solutions.py` | LLM Pass 1 prompt and parser |
| `scatter/ai/codebase_index.py` | Add `solution_filter` parameter |
| `scatter/cli_parser.py` | Add `--solutions` flag |
| `scatter/__main__.py` | Two-pass orchestration, console output |
| `scatter/reports/json_reporter.py` | `solution_discovery` section |
| **NEW** `test_solution_index.py` | Summary builder, formatter, filter tests |
| **NEW** `test_select_solutions.py` | LLM selection, auto-include, orchestration tests |

---

## Dependency Chain

```
Initiative 9 Phase 1 (solution parsing)
  -> Initiative 9 Phase 2 (solution membership on ProjectNode)
    -> This plan Phase 1 (solution summary builder)
      -> Phase 2 (focused index filter) — shippable standalone with --solutions flag
      -> Phase 3 (LLM Pass 1) — the AI discovery magic
        -> Phase 4 (orchestration + UX)
```

Phase 2 is independently valuable: even without LLM discovery, `--solutions` gives
teams explicit control over index scope. Ship it as soon as Initiative 9 Phase 2 lands.

---

## What This Does NOT Include

- **Interactive solution selection.** ("Here are 8 solutions — pick which ones to analyze.")
  Could be useful in a TUI mode but out of scope.
- **Solution-level risk scoring.** ("AdminPortal is high risk because it has the most
  cross-solution edges.") Interesting follow-on, not needed for focused index.
- **Multi-pass refinement.** ("Pass 2 found something in CDEX — go back and re-analyze
  with ConsumerPortal too.") Recursive expansion is complex and the auto-include
  mechanism covers the main case.
- **Custom solution groupings.** ("Treat these 3 solutions as one logical group.")
  Could be done via a manifest file but adds config burden.

---

## Risk Assessment

**Low risk.** This is additive to the existing SOW flow. The focused index is a strict
subset of the full index — same format, same downstream processing. The only new
failure mode is Pass 1 missing a solution, which is mitigated by:

1. Cross-solution edge auto-include (graph-based safety net)
2. User override via `--solutions` (explicit control)
3. Fallback to full index if no `.sln` files exist (backward compat)

The main risk is **LLM prompt quality for Pass 1.** Solution summaries are a novel
format and the LLM may struggle with the compact notation. Mitigation: the format is
simple enough to iterate on, and the auto-include mechanism reduces dependence on
perfect LLM performance.
