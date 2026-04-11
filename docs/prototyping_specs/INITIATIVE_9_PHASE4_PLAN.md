# Initiative 9 Phase 4: Solution-Informed Domain Clustering — Implementation Plan

**Branch:** feature/solution-aware-graph
**Estimated effort:** 0.5 day
**Depends on:** Phase 2 (solution membership on ProjectNode — shipped)
**Team review:** 2026-03-20 (Priya, Marcus, Tomás, Devon, Anya, Fatima, Sam)

---

## Goal

Report how well graph-derived clusters align with solution boundaries. Two
complementary signals for architects:
- **Feasibility** = "can we extract this based on code coupling?"
- **Solution alignment** = "does the org structure already think of this as a unit?"

Low alignment is *interesting and valuable* — it surfaces accidental coupling
across team boundaries, misplaced shared infrastructure, and stale solution files.

---

## Key Design Decision: No Label Propagation Affinity

The original plan included a 1.5x vote multiplier in label propagation for
neighbors sharing a solution. The team rejected this (Tomás, Priya, Marcus):

**Rationale:** The whole point of alignment is to surface divergence between
graph topology and org structure. Biasing clustering toward solution alignment
suppresses the signal we're trying to surface. If admin and employer projects
are truly tightly coupled, the cluster should reflect that — even if they're
in different solutions. That's the "accidental coupling" finding.

**Decision:** Pure topology clustering (no changes to `_label_propagation` or
`find_clusters` signature). Alignment is computed post-hoc as a reporting metric.
If someone later wants clustering to respect solutions, add affinity as an
opt-in flag.

---

## What Low Alignment Means

| Scenario | Example | Action |
|----------|---------|--------|
| **Accidental coupling** | AdminPortal.UserService references EmployerPortal.EnrollmentData | Flag for decoupling — coupling is real but unintended |
| **Misplaced shared infra** | A logging helper lives in AdminPortal.sln but is used everywhere | Project belongs in a shared solution, not a domain solution |
| **Stale solution files** | Solutions haven't been updated since 2019 | Graph reflects reality; solutions reflect history. Housekeep. |

All three scenarios surface identically (low alignment score). The architect
distinguishes them using the alignment score + dominant solution + cross-boundary
edges from Phase 3.

---

## Deliverables

### 1. Add alignment fields to `Cluster`

```python
@dataclass
class Cluster:
    # ... existing fields ...
    solution_alignment: float = 0.0         # 0.0-1.0, fraction sharing dominant solution
    dominant_solution: Optional[str] = None  # solution most members belong to
```

### 2. Compute alignment in `find_clusters()`

After clusters are built, compute alignment for each:

```python
def _compute_solution_alignment(
    projects: List[str],
    graph: DependencyGraph,
) -> Tuple[float, Optional[str]]:
    """Compute solution alignment for a cluster.

    Returns (alignment_score, dominant_solution).
    """
```

Algorithm:
1. For each project in the cluster, get `node.solutions`
2. Count occurrences of each solution name (a project in multiple solutions
   counts for each — Fatima)
3. Dominant solution = most common solution name
4. Alignment = projects that have dominant solution in their solutions list /
   total projects (Fatima: set membership, not equality)
5. If no projects have solutions → alignment=0.0, dominant=None

### 3. Surface in reporters

**Console** (`print_graph_report` domain clusters table):
- Add `Align` column showing alignment score (number only — Sam)
- Show dominant solution on the Members line in parentheses

```
Cluster                          Size   Cohesion   Coupling          Feasibility    Align
------------------------------ ------ ---------- ---------- -------------------- --------
cluster_0                          10      0.455      0.000         easy (1.000)     1.00
  Members: GalaxyWorks.Api, GalaxyWorks.BatchProcessor, ... (solution: GalaxyWorks)
```

Suppress `(solution: ...)` when dominant_solution is None.

**JSON** (cluster objects):
- Add `"solution_alignment"` and `"dominant_solution"` to each cluster

---

## Tests

| Test | What it validates |
|------|-------------------|
| **Solution alignment** | |
| `test_alignment_all_same_solution` | All members in same solution → alignment=1.0 |
| `test_alignment_no_solutions` | No members have solutions → alignment=0.0, dominant=None |
| `test_alignment_mixed` | 3 of 5 share a solution → alignment=0.6 |
| `test_dominant_solution_identified` | Correct dominant selected |
| `test_multi_solution_project_counts` | Project in {X,Y} counts for dominant X (Fatima) |
| **Reporters** | |
| `test_console_alignment_column` | Console shows Align column and dominant on Members line |
| `test_json_cluster_alignment` | JSON includes solution_alignment and dominant_solution |

---

## Files Changed

| File | Change |
|------|--------|
| `scatter/analyzers/domain_analyzer.py` | Cluster fields, `_compute_solution_alignment()`, call in `find_clusters()` |
| `scatter/reports/graph_reporter.py` | Alignment column in console, dominant on Members line, JSON cluster fields |
| `test_domain.py` | Alignment tests (~5 tests) |
| `test_reporters.py` | Console + JSON alignment tests (~2 tests) |

---

## What This Does NOT Change

- `_label_propagation()` — unchanged, pure topology
- `find_clusters()` signature — unchanged, no new parameters
- Feasibility scoring — unchanged, independent of solutions
- Level 1 clustering (connected components) — unchanged
- No new CLI flags

---

## Risk

**Minimal.** This is purely additive — two new fields on `Cluster` with defaults
(0.0, None), computed post-hoc. No changes to clustering algorithm, no changes to
feasibility scoring, no changes to existing function signatures. Existing tests
unaffected because new fields use `field(default_factory=...)` defaults.
