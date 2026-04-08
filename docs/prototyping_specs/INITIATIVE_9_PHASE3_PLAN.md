# Initiative 9 Phase 3: Cross-Solution Coupling Metrics — Implementation Plan

**Branch:** feature/solution-aware-graph
**Estimated effort:** 1 day
**Depends on:** Phase 2 (solution membership on ProjectNode — shipped)
**Blocks:** Init 11 Phase 1 (solution summary builder needs cross-solution edge counts)
**Team review:** 2026-03-20 (Priya, Marcus, Tomás, Devon, Anya, Fatima, Sam)

---

## Goal

Compute coupling metrics at the solution level — how self-contained each solution
is, which solutions depend on each other, and which projects bridge multiple
solutions. These metrics serve two purposes:

1. **Health dashboard**: Surface "this solution has more external edges than internal"
   as an observation — architects care about this.
2. **Initiative 11**: The cross-solution edge counts become the discovery signal in
   the focused SOW index. When AdminPortal has `REF->CDEX(6)`, the LLM can infer
   CDEX is in blast radius even if the SOW never mentions data exchange.

---

## Deliverables

### 1. `SolutionMetrics` dataclass in `coupling_analyzer.py`

```python
@dataclass
class SolutionMetrics:
    """Coupling metrics for a single solution."""
    name: str
    project_count: int
    internal_edges: int         # edges where both endpoints are in this solution
    external_edges: int         # edges where one endpoint is outside this solution
    cross_solution_ratio: float # external / (internal + external), 0.0 if no edges
    incoming_solutions: List[str]  # other solutions with edges INTO this one
    outgoing_solutions: List[str]  # other solutions this one has edges TO
```

Bridge projects are computed globally, not per-solution (Devon, Priya) — see
section 4 below.

### 2. `compute_solution_metrics()` in `coupling_analyzer.py`

```python
def compute_solution_metrics(
    graph: DependencyGraph,
) -> Tuple[Dict[str, SolutionMetrics], List[str]]:
    """Compute coupling metrics at the solution level.

    Uses ProjectNode.solutions (populated in Phase 2) to classify each edge.
    Returns (metrics_by_solution, bridge_projects).

    Bridge projects: projects appearing in 3+ solutions — computed once
    globally, not per-solution (Devon).
    """
```

**Algorithm — single-pass O(E) (Marcus, Devon):**

1. Build `solution_to_projects: Dict[str, Set[str]]` from `node.solutions` — O(N)
2. Build `node_solutions: Dict[str, Set[str]]` for fast per-node lookup — O(N)
3. Single pass over all edges — O(E):
   - For each edge, get `source_sols` and `target_sols`
   - For each solution in `source_sols`:
     - If target is also in that solution → increment internal
     - Else → increment external, record target's solutions as outgoing
   - For each solution in `target_sols`:
     - If source is also in that solution → already counted as internal above
     - Else → increment external, record source's solutions as incoming
   - Skip edges where either endpoint has no solutions (unaffiliated)
4. Compute `cross_solution_ratio` per solution — O(S)
5. Compute bridge projects: projects in 3+ solutions — O(N)

No per-solution edge iteration. Single pass over edges, O(1) set lookups per edge.

**Multi-solution edge classification (Fatima):**

A single edge can be internal to one solution and external to another. Example:
project A is in solutions X and Y, project B is in solution X only. Edge A→B is:
- Internal to X (both A and B are in X)
- External to Y (A is in Y, B is not)

The single-pass algorithm handles this naturally — it iterates source_sols and
target_sols independently.

### 3. `_classify_edge()` private helper

```python
def _classify_edge(
    source_sols: Set[str],
    target_sols: Set[str],
) -> str:
    """Classify an edge as 'intra-solution', 'cross-solution', or 'unaffiliated'.

    Private helper — tested through compute_solution_metrics() (Tomás, Anya).
    """
```

Private (`_classify_edge`), not public API. If Phase 4 (clustering) needs it,
promote then (Tomás).

### 4. Bridge projects — global, not per-solution

Computed once alongside solution metrics (Devon, Priya):

```python
bridge_projects = [
    name for name, sols in node_solutions.items()
    if len(sols) >= 3
]
```

The health observation for bridge projects also checks `fan_in >= 5` from
`ProjectMetrics` — so `compute_health_dashboard` needs both `solution_metrics`
and `project_metrics` (Fatima).

### 5. Health dashboard observations in `health_analyzer.py`

Two new observation rules. `compute_health_dashboard` signature updated to accept
optional `solution_metrics` and `bridge_projects` parameters.

**`high_cross_solution_coupling`** (warning):
- Fires when a solution has `cross_solution_ratio > 0.5`
- Message: `"{solution}: high cross-solution coupling (ratio {ratio:.2f}, {external} of {total} edges cross solution boundary)"`

**`solution_bridge_project`** (info):
- Fires when a project is in `bridge_projects` list AND has `fan_in >= 5` in `ProjectMetrics`
- Message: `"{project}: bridge project across {n} solutions ({solutions}) with {fan_in} incoming dependencies"`
- Requires both `bridge_projects` and `metrics` — fires only when both available

### 6. Surface in reporters

**Console** (`print_graph_report`):
- Add "Solution Coupling" section after domain clusters, before observations (Sam)
- Only shown when solution metrics exist
- Format: table with Solution, Projects, Internal, External, Ratio columns

**JSON** (`build_graph_json`):
- Add `"solution_metrics"` section with per-solution metrics
- Add `"bridge_projects"` list
- Only included when solution data exists

**CSV**: No change — solution metrics are at solution level, not project level.
The existing Solutions column per project (Phase 2) is sufficient.

---

## Tests

| Test | What it validates |
|------|-------------------|
| **SolutionMetrics computation** | |
| `test_two_solutions_basic` | Two solutions, edges within and between — correct internal/external counts |
| `test_all_intra_solution` | All edges within one solution — ratio = 0.0 |
| `test_all_cross_solution` | All edges between solutions — ratio = 1.0 |
| `test_multi_solution_edge_classification` | Edge internal to X but external to Y (Fatima) |
| `test_unaffiliated_projects_skipped` | Projects with no solutions don't contribute |
| `test_incoming_outgoing_solutions` | Correct solution names in incoming/outgoing lists |
| **Bridge projects** | |
| `test_bridge_project_detected` | Project in 3+ solutions → in bridge list |
| `test_no_bridge_below_threshold` | Project in 2 solutions → not a bridge |
| **Health observations** | |
| `test_high_cross_solution_observation` | Ratio > 0.5 fires warning |
| `test_no_observation_below_threshold` | Ratio <= 0.5 does not fire |
| `test_bridge_project_observation` | Bridge project with fan_in >= 5 fires info |
| `test_bridge_no_observation_low_fan_in` | Bridge project with fan_in < 5 does not fire |
| **Reporters** | |
| `test_console_solution_coupling_section` | Console shows section when metrics exist |
| `test_console_no_section_without_solutions` | Section suppressed when no solutions |
| `test_json_solution_metrics` | JSON includes solution_metrics and bridge_projects |
| **Integration** | |
| `test_solution_metrics_from_sample_projects` | Compute against real GalaxyWorks.sln |

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| Single-pass O(E) algorithm | Simpler and faster than O(S×E) per-solution iteration. Set intersection is O(1) for typical 1-2 solutions per project. | Marcus, Devon |
| `_classify_edge()` is private | Only used inside `compute_solution_metrics()`. Test through public API. Promote if Phase 4 needs it. | Tomás, Anya |
| Bridge projects computed globally, not per-solution | A project in 3 solutions is a bridge regardless of which solution's perspective you take. Avoids redundant computation. | Devon, Priya |
| Bridge observation needs both solution_metrics and project_metrics | fan_in comes from ProjectMetrics, solution count from the bridge list. Update compute_health_dashboard signature. | Fatima |
| Console: solution coupling after clusters, before observations | Observations reference solutions — seeing the metrics table first gives context. | Sam |
| Multi-solution edge test | Edge A→B where A is in {X,Y} and B is in {X} must be internal to X, external to Y. Explicit test. | Fatima |

---

## Files Changed

| File | Change |
|------|--------|
| `scatter/analyzers/coupling_analyzer.py` | Add SolutionMetrics, compute_solution_metrics(), _classify_edge() |
| `scatter/analyzers/health_analyzer.py` | Add solution_metrics + bridge_projects params, two new rules |
| `scatter/reports/graph_reporter.py` | Solution coupling console section, JSON solution_metrics |
| `scatter/__main__.py` | Compute + pass solution metrics in --graph mode |
| `test_coupling.py` | SolutionMetrics computation + bridge tests (~8 tests) |
| `test_reporters.py` | Console + JSON solution metrics tests (~3 tests) |
| `test_graph.py` or `test_coupling.py` | Health observation tests (~4 tests) |

---

## What This Does NOT Change (yet)

- No solution-informed clustering (Phase 4)
- No changes to `__main__.py` wiring beyond --graph mode (Phase 5)
- No `--solutions` CLI flag (Init 11)

---

## Risk

**Low.** Additive — new dataclass, new functions, new observations. No changes to
existing coupling metrics or cycle detection. The `compute_solution_metrics` function
reads from `node.solutions` which is already populated and serialized.

The main edge case is projects in multiple solutions — a single edge can be "internal"
to solution A but "cross-solution" for solution B. The single-pass algorithm handles
this naturally by iterating source and target solution sets independently. Explicit
test covers this case (Fatima).
