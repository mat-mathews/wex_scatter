# Initiative 9 Phase 2: Solution Membership in the Graph — Implementation Plan

**Branch:** feature/solution-aware-graph
**Estimated effort:** 0.5 day
**Depends on:** Phase 1 (solution scanner — shipped)
**Blocks:** Init 9 Phases 3-5, Init 11 (focused SOW index)

---

## Goal

Get solution membership onto `ProjectNode` so every downstream consumer — graph
reporters, the codebase index, health dashboard, domain clustering — can ask
"which solutions contain this project?" without re-parsing `.sln` files.

---

## Deliverables

### 1. Add `solutions` field to `ProjectNode`

```python
@dataclass
class ProjectNode:
    # ... existing fields ...
    solutions: List[str] = field(default_factory=list)
```

`field(default_factory=list)` means `from_dict()` gracefully handles old caches
that don't have the field — they get an empty list. No cache version bump needed.

### 2. Update `to_dict()` / `from_dict()` in `DependencyGraph`

**`to_dict()`** — add `"solutions": node.solutions` to the node serialization dict.

**`from_dict()`** — add `solutions=node_data.get("solutions", [])` to the
`ProjectNode` constructor call.

### 3. Populate solutions during graph build

In `graph_builder.py:build_dependency_graph()`, after Step 2 (parse .csproj files)
and before building nodes (line ~159):

```python
# Step 2b: Parse solutions and build reverse index
from scatter.scanners.solution_scanner import scan_solutions, build_project_to_solutions
solutions = scan_solutions(search_scope)
project_to_solutions = build_project_to_solutions(solutions)
```

Then in the node construction loop (line ~161), add:

```python
node = ProjectNode(
    # ... existing fields ...
    solutions=[si.name for si in project_to_solutions.get(project_name, [])],
)
```

### 4. Wire `scan_solutions()` into `__main__.py`

Replace the raw `find_files_with_pattern_parallel('*.sln')` call (lines 200-210)
with `scan_solutions()`. Build the reverse index and pass it through the context
so `v1_bridge` callers can use the indexed lookup.

```python
# --- Step 1: Parse solution files ---
from scatter.scanners.solution_scanner import scan_solutions, build_project_to_solutions

solution_infos: List[SolutionInfo] = []
if search_scope_abs:
    solution_infos = scan_solutions(search_scope_abs)
    logging.info(f"Found {len(solution_infos)} solution files")

solution_index = build_project_to_solutions(solution_infos)

# Backward compat: still need List[Path] for callers not yet migrated
solution_file_cache = [si.path for si in solution_infos]
```

Update the `AnalysisContext` (or equivalent) in `cli.py` to carry `solution_index`
alongside `solution_file_cache`.

### 5. Update graph reporters

**CSV** (`write_graph_csv_report`):
- Add `"Solutions"` column after `"ExtractionFeasibility"`
- Value: semicolon-delimited solution names (e.g., `"GalaxyWorks;Master"`)
- Empty string for unaffiliated projects

**JSON** (`build_graph_json`):
- When `include_topology=True`, solutions already flow through `graph.to_dict()`
  automatically (it serializes all ProjectNode fields we add)
- Add `"solutions"` to the per-project `metrics` section too for non-topology output

**Console** (`print_graph_report`):
- Add solution count to the summary line: `"11 projects (1 solution), 50 edges, ..."`
- No per-project solution listing in console (too noisy)

---

## Tests

| Test | What it validates |
|------|-------------------|
| **Graph model** | |
| `test_project_node_solutions_default` | New ProjectNode has empty solutions list |
| `test_project_node_solutions_set` | Solutions set and retrievable |
| `test_to_dict_includes_solutions` | `to_dict()` serializes solutions |
| `test_from_dict_with_solutions` | `from_dict()` deserializes solutions |
| `test_from_dict_without_solutions` | Old cache without solutions field → empty list |
| **Graph builder** | |
| `test_graph_build_populates_solutions` | Build against sample projects, verify GalaxyWorks.Data has ["GalaxyWorks"] |
| `test_graph_build_no_sln_files` | Build with no .sln files → all nodes have empty solutions |
| **Reporters** | |
| `test_csv_solutions_column` | CSV output includes Solutions column |
| `test_csv_solutions_semicolons` | Multi-solution project uses semicolons |
| `test_json_topology_includes_solutions` | JSON topology nodes have solutions field |
| `test_json_metrics_includes_solutions` | JSON metrics section has solutions |
| `test_console_solution_count` | Console summary shows solution count |
| **Integration** | |
| `test_cache_roundtrip_with_solutions` | Build graph → save → load → solutions preserved |

---

## Files Changed

| File | Change |
|------|--------|
| `scatter/core/graph.py` | Add `solutions` field to `ProjectNode`, update `to_dict()`/`from_dict()` |
| `scatter/analyzers/graph_builder.py` | Call `scan_solutions()` + populate `node.solutions` |
| `scatter/__main__.py` | Replace raw .sln discovery with `scan_solutions()` |
| `scatter/cli.py` | Add `solution_index` to context, pass to `v1_bridge` callers |
| `scatter/reports/graph_reporter.py` | Solutions column in CSV, solutions in JSON metrics |
| `test_graph.py` | Model + serialization tests |
| `test_reporters.py` | CSV + JSON + console tests |

---

## What This Does NOT Change (yet)

- No cross-solution coupling metrics. That's Phase 3.
- No solution-informed clustering. That's Phase 4.
- No new CLI flags. Solutions are auto-detected from `.sln` files in search scope.
- `v1_bridge` callers are migrated opportunistically — they receive `solution_index`
  but fall back to text search if not provided.

---

## Risk

**Low.** The `solutions` field default (empty list) ensures backward compatibility
with existing graph caches. The `scan_solutions()` call is fast (parsed in Phase 1,
~100ms for 100 .sln files). Reporter changes are additive columns/fields.

The main integration risk is `__main__.py` and `cli.py` wiring — multiple call sites
need the solution index threaded through. Careful testing of all analysis modes
(git, target, sproc, impact, graph) with and without `.sln` files present.
