# Solution-Aware Graph Integration — Implementation Plan

**Initiative:** Solution-Aware Graph
**Priority:** Tier 1.9 — ships alongside or immediately after production readiness work
**Estimated effort:** 3-4 days across 5 phases
**Depends on:** None (all prerequisites already shipped)

---

## Problem Statement

Scatter's dependency graph knows nothing about `.sln` files. The graph tracks four edge
types (project_reference, namespace_usage, type_usage, sproc_shared), computes coupling
metrics, detects cycles, and identifies domain clusters — all without ever looking at
a solution file.

Meanwhile, solution files are the single most explicit, human-authored statement of
"these projects belong together and ship together." An architect who created `Billing.sln`
containing 12 projects was telling you something important. Scatter currently ignores
that signal.

Today, solutions are a **reporting-only concern**: discovered in `__main__.py`, passed
through `v1_bridge.py` for text-based lookup, and emitted as a `ConsumingSolutions`
field in output. They have zero impact on analysis quality.

### What this costs us

1. **Domain clustering reinvents what solutions already declare.** `find_clusters()` uses
   edge connectivity and label propagation to guess at domain boundaries. Solution
   membership is a high-confidence ground truth that could confirm, refine, or challenge
   those guesses. We throw it away.

2. **Cross-solution coupling is invisible.** An edge between two projects in the same
   solution is a local concern. The same edge crossing a solution boundary is a deployment
   coordination risk — different teams, different pipelines, different release cycles.
   Scatter treats both edges identically.

3. **Graph reports can't answer "what's in my solution?"** Architects working with
   `--graph` mode see projects, clusters, and metrics — but no solution context. They
   can't filter by solution or see solution-level health.

4. **The health dashboard is blind to solution boundaries.** It flags high coupling and
   stable cores, but can't say "Billing.sln has 14 cross-solution edges, 3 of which are
   shared sprocs" — the kind of finding that actually changes a deployment plan.

5. **find_solutions_for_project() is naive.** It reads every `.sln` file and does a
   substring match on the `.csproj` filename. It doesn't parse the solution format, so
   a project named `Auth.Core.csproj` would false-match a solution containing only
   `MyAuth.Core.csproj` (substring hit on `Auth.Core.csproj`).

---

## Design Principles

1. **Solutions are metadata, not structure.** The graph's core topology (nodes = projects,
   edges = dependencies) stays unchanged. Solutions are an annotation layer on top.

2. **Zero new CLI flags.** If `.sln` files exist in the search scope, they're used
   automatically. If they don't exist, nothing changes.

3. **Backward compatible.** All existing output formats keep working. New solution
   fields are additive. Cache v2 → v3 migration is automatic.

4. **Solutions inform, but don't override.** Domain clustering uses solution membership
   as a signal, not a hard constraint. If the code-level edges disagree with the
   solution boundaries, that's an interesting finding — not an error.

---

## Phase 1: Parse Solutions Properly (~0.5 day)

### 1.1 Create `scatter/scanners/solution_scanner.py`

Replace the naive text search in `v1_bridge.py` with proper `.sln` parsing.

```python
@dataclass
class SolutionInfo:
    """Parsed metadata from a .sln file."""
    path: Path                    # absolute path to the .sln
    name: str                     # stem (e.g., "Billing" from "Billing.sln")
    project_entries: List[str]    # project names referenced in the .sln
    project_paths: List[str]     # relative .csproj paths from the .sln

def parse_solution_file(sln_path: Path) -> SolutionInfo:
    """Parse a .sln file and extract project references.

    Parses Project("...") = "Name", "path\\to\\Name.csproj", "{GUID}" lines.
    Handles both forward and backslash path separators.
    """

def scan_solutions(search_scope: Path, **parallel_kwargs) -> List[SolutionInfo]:
    """Discover and parse all .sln files in the search scope."""

def build_project_to_solutions(solutions: List[SolutionInfo]) -> Dict[str, List[str]]:
    """Build reverse index: project_name -> list of solution names."""
```

The parser extracts the project name and relative path from each `Project(...)` line
using a regex. This replaces substring matching with structural parsing.

### 1.2 Migrate `v1_bridge.find_solutions_for_project()`

Replace the text-search implementation with a lookup against the parsed index:

```python
def find_solutions_for_project(
    csproj_path: Path,
    solution_cache: List[Path],            # old API (backward compat)
    solution_index: Optional[Dict] = None,  # new API (preferred)
) -> List[Path]:
```

When `solution_index` is provided, use the O(1) dict lookup. When only `solution_cache`
is provided, fall back to the current text search for backward compatibility.

### Tests (Phase 1)
- [ ] Parse SDK-style .sln with multiple projects
- [ ] Parse .sln with backslash and forward-slash paths
- [ ] Parse .sln with nested solution folders
- [ ] Handle malformed .sln gracefully (no crash, warning logged)
- [ ] Handle empty .sln (zero projects)
- [ ] build_project_to_solutions reverse index correctness
- [ ] Migration: old text-search API still works when index not provided

---

## Phase 2: Solution Membership in the Graph (~0.5 day)

### 2.1 Add `solutions` field to `ProjectNode`

```python
@dataclass
class ProjectNode:
    path: Path
    name: str
    # ... existing fields ...
    solutions: List[str] = field(default_factory=list)  # NEW: solution names containing this project
```

### 2.2 Populate during graph build

In `graph_builder.py:build_dependency_graph()`, after all projects are discovered:

1. Call `scan_solutions(search_scope)` to parse all `.sln` files
2. Call `build_project_to_solutions()` to build the reverse index
3. For each `ProjectNode`, set `node.solutions = project_to_solutions.get(name, [])`

This adds one pass over `.sln` files during graph construction. At 100 solutions
averaging 20 projects each, this is ~100 file reads + parsing — negligible compared
to the thousands of `.cs` file reads already happening.

### 2.3 Serialize solutions in graph cache

`ProjectNode.solutions` is already a `List[str]` and will serialize via the existing
`to_dict()` / `from_dict()` roundtrip without any changes to graph_cache.py.

No cache version bump needed — `from_dict()` should handle the missing field gracefully
via `field(default_factory=list)`.

### 2.4 Add solution data to graph JSON/CSV reporters

- **Graph JSON**: `solutions` field appears on each node in the topology section
- **Graph CSV**: Add `Solutions` column (semicolon-delimited)
- **Console**: Show solution count per project in verbose mode

### Tests (Phase 2)
- [ ] ProjectNode.solutions populated correctly from parsed .sln data
- [ ] ProjectNode.solutions survives to_dict/from_dict roundtrip
- [ ] Graph cache with solutions loads correctly (new cache on old code = empty list)
- [ ] Graph CSV includes Solutions column
- [ ] Graph JSON includes solutions per node

---

## Phase 3: Cross-Solution Coupling Metrics (~1 day)

### 3.1 Solution-level metrics in `coupling_analyzer.py`

New dataclass and function:

```python
@dataclass
class SolutionMetrics:
    """Coupling metrics for a single solution."""
    name: str
    project_count: int
    internal_edges: int          # edges where both source and target are in this solution
    external_edges: int          # edges crossing the solution boundary
    cross_solution_ratio: float  # external / (internal + external)
    incoming_solutions: List[str]  # other solutions that depend on projects in this one
    outgoing_solutions: List[str]  # other solutions this one depends on
    shared_sprocs: List[str]     # sprocs referenced by projects both inside and outside

def compute_solution_metrics(
    graph: DependencyGraph,
    project_to_solutions: Dict[str, List[str]],
) -> Dict[str, SolutionMetrics]:
    """Compute coupling metrics at the solution level."""
```

### 3.2 Per-edge solution context

Add a helper that classifies any edge as intra-solution or cross-solution:

```python
def classify_edge(
    edge: DependencyEdge,
    project_to_solutions: Dict[str, List[str]],
) -> str:
    """Returns 'intra-solution', 'cross-solution', or 'unaffiliated'."""
```

This is useful for filtering and weighting. A `cross-solution` project_reference edge
represents a harder deployment dependency than an `intra-solution` one.

### 3.3 Surface in health dashboard

Add new observation rules to `health_analyzer.py`:

- **`high_cross_solution_coupling`**: Solution where `cross_solution_ratio > 0.5`
  (more external edges than internal — this solution is not self-contained)
- **`solution_bridge_project`**: Project that appears in 3+ solutions and has
  high fan-in (it's a coupling bottleneck across solution boundaries)

### Tests (Phase 3)
- [ ] SolutionMetrics computed correctly for simple graph with 2 solutions
- [ ] Cross-solution ratio = 0 when all edges are intra-solution
- [ ] Cross-solution ratio = 1 when all edges cross boundaries
- [ ] Solution bridge project detected (3+ solutions, high fan-in)
- [ ] Projects in no solution handled gracefully (unaffiliated)
- [ ] Health observation fires for high cross-solution coupling

---

## Phase 4: Solution-Informed Domain Clustering (~1 day)

### 4.1 Solution membership as clustering signal

Modify `domain_analyzer.py:find_clusters()` to accept an optional
`project_to_solutions` parameter. When provided:

**During Level 1 (connected components):** No change — pure graph connectivity.

**During Level 2 (label propagation):** Add a solution affinity bonus to the
label voting. When a node's neighbor has the same solution membership, its vote
weight gets a configurable multiplier (default: 1.5x). This biases the algorithm
toward keeping solution-aligned projects together, without hard constraints.

```python
def find_clusters(
    graph: DependencyGraph,
    min_cluster_size: int = 2,
    metrics: Optional[Dict] = None,
    cycles: Optional[List] = None,
    project_to_solutions: Optional[Dict[str, List[str]]] = None,  # NEW
    solution_affinity_weight: float = 1.5,  # NEW
) -> List[Cluster]:
```

### 4.2 Solution alignment score per cluster

Add to the `Cluster` dataclass:

```python
@dataclass
class Cluster:
    # ... existing fields ...
    solution_alignment: float = 0.0         # NEW: 0.0-1.0, how well cluster matches solutions
    dominant_solution: Optional[str] = None  # NEW: the solution most members belong to
```

**`solution_alignment`**: Fraction of cluster members that share the dominant solution.
1.0 = perfect alignment (every member is in the same solution). 0.0 = no alignment.

This is reported alongside feasibility scores, giving architects two complementary signals:
- **Feasibility** = "can we extract this based on code coupling?"
- **Solution alignment** = "does the org structure already think of this as a unit?"

High feasibility + high alignment = easy win.
High feasibility + low alignment = code says yes, org says no — investigate.
Low feasibility + high alignment = the team thinks it's independent, but the code disagrees.

### 4.3 Surface in console and JSON output

- Console: Add `Alignment` column to domain clusters table
- JSON: Add `solution_alignment` and `dominant_solution` to cluster objects
- CSV: Add columns

### Tests (Phase 4)
- [ ] Label propagation with solution affinity produces different clusters than without
- [ ] Solution alignment = 1.0 when all members share a solution
- [ ] Solution alignment = 0.0 when no members share a solution
- [ ] Dominant solution correctly identified
- [ ] Cluster with no solution data: alignment = 0.0, dominant_solution = None
- [ ] Console output includes Alignment column
- [ ] JSON output includes solution_alignment and dominant_solution

---

## Phase 5: Wire Everything Together (~0.5 day)

### 5.1 Update `__main__.py` / `cli.py`

Replace the raw `solution_file_cache: List[Path]` with a richer context:

1. Call `scan_solutions()` early (replaces current `find_files_with_pattern_parallel('*.sln')`)
2. Build `project_to_solutions` index
3. Pass to graph builder, domain analyzer, coupling analyzer, health analyzer
4. Pass `SolutionInfo` list to v1_bridge (backward compat via the migration in Phase 1)

### 5.2 Update graph enrichment

In `graph_enrichment.py`, when building graph context, include solution data
so it's available for enriching legacy mode results too.

### 5.3 Update synthetic codebase generator

Already done — `.sln` files are now generated with domain, master, and team solutions.
Verify the full pipeline works end-to-end against a synthetic codebase.

### Tests (Phase 5)
- [ ] End-to-end: generate synthetic codebase, run --graph, verify solution data in output
- [ ] End-to-end: run --target-project against synthetic, verify ConsumingSolutions populated
- [ ] Backward compat: codebase with zero .sln files produces same output as before
- [ ] --no-graph still works (solutions discovered but graph not built)

---

## Files Modified

| File | Change |
|------|--------|
| **NEW** `scatter/scanners/solution_scanner.py` | Parser, scanner, reverse index |
| `scatter/core/graph.py` | Add `solutions: List[str]` to ProjectNode |
| `scatter/analyzers/graph_builder.py` | Scan solutions, populate ProjectNode.solutions |
| `scatter/analyzers/coupling_analyzer.py` | Add SolutionMetrics, compute_solution_metrics |
| `scatter/analyzers/domain_analyzer.py` | Solution affinity in label propagation, alignment score |
| `scatter/analyzers/health_analyzer.py` | Cross-solution coupling observation |
| `scatter/compat/v1_bridge.py` | Accept parsed solution index, backward compat |
| `scatter/reports/graph_reporter.py` | Solution column in CSV, solutions in JSON |
| `scatter/reports/console_reporter.py` | Solution metrics in graph output |
| `scatter/__main__.py` | Wire scan_solutions into startup |
| `scatter/cli.py` | Pass solution context through modes |
| **NEW** `test_solution_scanner.py` | Parser, index, migration tests |
| **NEW** `test_solution_metrics.py` | Cross-solution coupling, health observations |
| `test_domain.py` | Solution alignment, affinity weight tests |
| `test_graph.py` | ProjectNode.solutions roundtrip |
| `test_reporters.py` | Solution columns in output |

---

## What This Does NOT Include

- **Solution-level blast radius.** ("If I change this project, which solutions need
  to be rebuilt?") Useful but separate — it's a reporting feature on top of this work.
- **Solution dependency graph.** (Solutions as nodes, cross-solution edges as edges.)
  Interesting visualization but premature before the base data is in place.
- **Solution-level CI/CD gates.** ("Fail if this solution's cross-solution coupling
  exceeds threshold.") Depends on Initiative 7 (CI/CD exit codes) which hasn't shipped.
- **.sln file modification.** Scatter reads solutions, never writes them.

---

## Risk Assessment

**Low risk overall.** This is additive — new fields, new metrics, new signals. No
existing behavior changes unless you pass solutions to the clustering algorithm, and
even then the default affinity weight (1.5x) is a gentle bias, not a hard constraint.

The main risk is **scope creep.** Solution-level metrics are interesting and it's
tempting to keep adding computed fields. The plan above is deliberately scoped to
the minimum that provides real analytical value: membership on nodes, cross-solution
coupling, clustering alignment, and two health observations. Everything else can be
built incrementally on top of this foundation.
