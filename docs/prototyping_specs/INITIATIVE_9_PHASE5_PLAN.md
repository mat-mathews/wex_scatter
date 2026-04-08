# Initiative 9 Phase 5: Wire Together & End-to-End Validation

**Branch:** feature/solution-aware-graph
**Estimated effort:** 0.25 day (validation only — wiring already done in Phases 2-4)
**Depends on:** Phases 1-4 (all shipped on this branch)

---

## Status: Wiring Already Complete

The original Phase 5 plan called for wiring `scan_solutions()` into `__main__.py`,
passing solution data through to all analyzers and reporters. This was done
incrementally during Phases 2-4:

| Wiring point | Done in |
|---|---|
| `scan_solutions()` replaces raw `.sln` discovery in `__main__.py` | Phase 2 |
| `solution_index` on `ModeContext`, threaded to `v1_bridge` callers | Phase 2 |
| `solution_index` threaded to `impact_analyzer` (all 3 functions) | Phase 2 |
| `solution_index` passed to `build_graph_context()` in `graph_enrichment.py` | Phase 2 |
| `_populate_graph_solutions()` called after graph build in `--graph` and `--dump-index` modes | Phase 2 |
| `compute_solution_metrics()` called in `--graph` mode, passed to reporters + dashboard | Phase 3 |
| `_compute_solution_alignment()` called in `find_clusters()` | Phase 4 |

**What remains is validation only.** No new production code needed.

---

## Deliverables: End-to-End Validation Tests

### 1. `--graph` mode end-to-end

Run `--graph` against sample projects, verify:
- Console output includes "Solutions: 1"
- Console output includes "Solution Coupling" section
- Console output includes "Align" column in clusters
- JSON output includes `solution_metrics` section
- JSON output includes `solutions` on nodes (topology)
- JSON output includes `solution_alignment` on clusters
- CSV output includes `Solutions` column

### 2. `--target-project` mode end-to-end

Run `--target-project` against sample projects, verify:
- JSON output `ConsumingSolutions` is populated (not empty)
- `ConsumingSolutions` values come from the solution index (not text search)

### 3. Backward compatibility

Run against a directory with no `.sln` files, verify:
- No "Solutions:" line in console summary
- No "Solution Coupling" section
- No "Align" column in clusters table
- No crash, no warnings about missing solutions
- `--no-graph` flag still works

### 4. Update tasks.txt

Mark Init 9 Phases 1-5 complete with test counts and shipped date.
Update recommended execution order.

---

## Tests

| Test | File | What it validates |
|------|------|-------------------|
| `test_graph_mode_solution_output` | `test_solution_e2e.py` | `--graph --rebuild-graph` against sample projects — console has Solutions, Solution Coupling, Align |
| `test_graph_json_has_solution_data` | `test_solution_e2e.py` | JSON output includes solution_metrics, node solutions, cluster alignment |
| `test_graph_csv_has_solutions_column` | `test_solution_e2e.py` | CSV has Solutions column with values |
| `test_target_mode_consuming_solutions` | `test_solution_e2e.py` | `--target-project` JSON output has ConsumingSolutions populated |
| `test_no_sln_files_no_crash` | `test_solution_e2e.py` | Empty tmp_path with .csproj but no .sln → no crash, no solution sections |
| `test_no_graph_flag_works` | `test_solution_e2e.py` | `--no-graph` skips graph, solutions still discovered for v1_bridge |

---

## Files Changed

| File | Change |
|------|--------|
| **NEW** `test_solution_e2e.py` | 6 end-to-end validation tests |
| `tasks.txt` | Mark Init 9 complete |

---

## Risk

**None.** This is validation of already-shipped code. No production changes.
