# Incremental Graph Updates — Implementation Plan

**Initiative:** Incremental Graph Updates
**Ref:** docs/INCREMENTAL_GRAPH_BRAINSTORM.md (team debate and decisions)
**Priority:** Tier 2 prerequisite — must ship before CI/CD gates
**Estimated effort:** 3-4 days across 4 phases

---

## Overview

Replace the all-or-nothing graph cache invalidation with surgical incremental updates.
When scatter runs, it checks `git diff` for changes since the last graph build. If only
a few files changed, it patches the cached graph in milliseconds instead of rebuilding
from scratch in 60+ seconds.

**Target:** PR with 10 changed files in a 500-project repo → <1 second (vs 60s today).

---

## Phase 1: Cache Format v2 + Data Models (~0.5 day)

### 1.1 New dataclasses in `scatter/store/graph_cache.py`

```python
@dataclass
class FileFacts:
    """Per-.cs-file parsed facts for incremental invalidation."""
    path: str                     # relative to search_scope
    project: str                  # owning project name
    types_declared: List[str]     # type names declared in this file
    namespaces_used: List[str]    # using statement namespaces
    sprocs_referenced: List[str]  # stored procedure references
    content_hash: str             # sha256 of file contents

@dataclass
class ProjectFacts:
    """Per-project parsed facts for incremental invalidation."""
    namespace: Optional[str]      # derived namespace
    project_references: List[str] # resolved ProjectReference target names
    csproj_content_hash: str      # sha256 of .csproj contents
```

### 1.2 Cache envelope v2

Extend `save_graph()` to accept optional `file_facts` and `project_facts`.
Extend `load_and_validate()` to return them alongside the graph.

```python
CACHE_VERSION = 2  # bump from 1

def save_graph(
    graph: DependencyGraph,
    cache_path: Path,
    search_scope: Path,
    file_facts: Optional[Dict[str, FileFacts]] = None,
    project_facts: Optional[Dict[str, ProjectFacts]] = None,
) -> None

def load_and_validate(
    cache_path: Path,
    search_scope: Path,
    invalidation: str = "git",
) -> Optional[Tuple[DependencyGraph, Optional[Dict[str, FileFacts]],
                     Optional[Dict[str, ProjectFacts]]]]
```

### 1.3 Migration

- v1 cache files (version=1 or missing file_facts): return `(graph, None, None)`
- Caller treats `None` facts as "incremental unavailable, full rebuild needed"
- After rebuild, save as v2 with facts populated

### 1.4 project_set_hash

Add to cache envelope: `hashlib.sha256` of sorted `.csproj` relative paths.
On load, recompute and compare. Mismatch → full rebuild (structural change).

### Tests (Phase 1)
- [ ] FileFacts and ProjectFacts dataclass construction
- [ ] v2 save/load roundtrip with facts
- [ ] v1 cache loads as (graph, None, None) — backward compat
- [ ] project_set_hash mismatch triggers rebuild signal
- [ ] Content hash computation is deterministic

---

## Phase 2: Graph Mutation + Fact Extraction (~1 day)

### 2.1 Add `remove_edges_from()` to DependencyGraph

```python
def remove_edges_from(self, source: str,
                      edge_types: Optional[Set[str]] = None) -> int:
    """Remove outgoing edges from source, optionally filtered by edge_type.

    Updates _outgoing, _incoming, _forward, _reverse consistently.
    Returns count of edges removed.
    """
```

Also add `remove_edges_to()` for completeness (needed when a project's
namespace changes and incoming namespace_usage edges must be rebuilt).

### 2.2 Fact extraction functions in `scatter/store/graph_patcher.py`

Extract the per-file scanning logic from `graph_builder.py` into reusable
functions that can process a single file:

```python
def extract_file_facts(
    cs_path: Path,
    project_name: str,
    search_scope: Path,
) -> FileFacts:
    """Read a single .cs file and extract types, namespaces, sprocs, content hash."""

def extract_project_facts(
    csproj_path: Path,
    all_project_names: Set[str],
) -> ProjectFacts:
    """Parse a single .csproj and extract namespace, references, content hash."""
```

These call existing functions (`extract_type_names_from_content`,
`_USING_PATTERN`, `derive_namespace`, `parse_csproj_all_references`) but
wrap them in the FileFacts/ProjectFacts return types.

### 2.3 Populate facts during full build

Modify `build_dependency_graph()` in `graph_builder.py` to optionally
return file_facts and project_facts alongside the graph. This is a
lightweight addition — the data is already computed during the build,
we just need to capture it instead of discarding it.

```python
def build_dependency_graph(
    search_scope: Path,
    ...,
    capture_facts: bool = False,
) -> Union[DependencyGraph, Tuple[DependencyGraph, Dict[str, FileFacts], Dict[str, ProjectFacts]]]:
```

### Tests (Phase 2)
- [ ] remove_edges_from removes correct edges, updates all 4 indexes
- [ ] remove_edges_from with edge_type filter removes only matching edges
- [ ] remove_edges_from on unknown source is no-op (returns 0)
- [ ] remove_edges_to symmetric behavior
- [ ] extract_file_facts produces correct types/namespaces/sprocs/hash
- [ ] extract_project_facts produces correct refs/namespace/hash
- [ ] build_dependency_graph with capture_facts=True returns facts
- [ ] Facts from full build match individually extracted facts

---

## Phase 3: Patch Algorithm (~1.5 days)

### 3.1 Core patch function in `scatter/store/graph_patcher.py`

```python
@dataclass
class PatchResult:
    """Result of an incremental graph patch."""
    graph: DependencyGraph
    file_facts: Dict[str, FileFacts]
    project_facts: Dict[str, ProjectFacts]
    patch_applied: bool          # True if patched, False if fell back to full rebuild
    files_processed: int         # number of files re-extracted
    projects_affected: int       # number of projects with edge rebuilds
    declarations_changed: bool   # whether type_to_projects was rebuilt

def patch_graph(
    graph: DependencyGraph,
    file_facts: Dict[str, FileFacts],
    project_facts: Dict[str, ProjectFacts],
    changed_files: List[str],    # relative paths from git diff
    search_scope: Path,
    rebuild_threshold_projects: int = 50,
    rebuild_threshold_pct: float = 0.30,
) -> PatchResult:
```

### 3.2 Algorithm steps

```
1. CLASSIFY changes
   - Split into changed_cs, changed_csproj
   - Detect added/removed .csproj (compare against project_facts keys)
   - If structural change → return PatchResult(patch_applied=False)

2. CHECK THRESHOLDS
   - Map changed .cs to affected projects
   - If >rebuild_threshold_projects or >rebuild_threshold_pct → full rebuild

3. HANDLE DELETED .cs files
   - Remove from file_facts
   - Add owning project to affected set

4. HANDLE NEW .cs files
   - Map to project via project_dir_index (rebuild from graph nodes)
   - Add to affected set

5. RE-EXTRACT FACTS for changed .cs files
   - Content hash early cutoff: if hash unchanged, skip
   - Compare types_declared old vs new
   - Track whether any declarations changed

6. HANDLE .csproj changes
   - Re-parse references and namespace
   - Content hash early cutoff
   - If namespace changed: flag for namespace_to_project rebuild
   - Update project_facts

7. REBUILD EDGES from affected projects
   - remove_edges_from(project, {'namespace_usage', 'type_usage', 'sproc_shared'})
   - Rebuild namespace_to_project map (if any namespace changed)
   - Rebuild type_to_projects map (if any declarations changed)
   - For each affected project: rebuild outgoing edges using current facts
   - For .csproj changes: rebuild project_reference edges

8. RECOMPUTE METRICS
   - compute_all_metrics(graph) — O(N+E), <1s
   - detect_cycles(graph) — O(N+E), <0.1s
```

### 3.3 Edge rebuild helpers

```python
def _rebuild_namespace_edges(
    graph: DependencyGraph,
    project: str,
    file_facts: Dict[str, FileFacts],
    namespace_to_project: Dict[str, str],
) -> None:
    """Rebuild namespace_usage edges from project based on current file facts."""

def _rebuild_type_usage_edges(
    graph: DependencyGraph,
    project: str,
    file_facts: Dict[str, FileFacts],
    type_to_projects: Dict[str, Set[str]],
    search_scope: Path,
) -> None:
    """Rebuild type_usage edges from project by re-tokenizing its .cs files."""

def _rebuild_sproc_edges(
    graph: DependencyGraph,
    project: str,
    file_facts: Dict[str, FileFacts],
    all_project_sprocs: Dict[str, Set[str]],
) -> None:
    """Rebuild sproc_shared edges for project based on current sproc refs."""

def _rebuild_project_reference_edges(
    graph: DependencyGraph,
    project: str,
    project_facts: Dict[str, ProjectFacts],
) -> None:
    """Rebuild project_reference edges from project based on current .csproj refs."""
```

### 3.4 Git diff integration

```python
def get_changed_files(
    cached_git_head: str,
    search_scope: Path,
) -> Optional[List[str]]:
    """Return list of changed .cs/.csproj files since cached_git_head.

    Returns None if git is unavailable or cached_git_head is unreachable
    (e.g., after a force push). Caller should fall back to full rebuild.
    """
```

### Tests (Phase 3)
- [ ] Patch with usage-only .cs changes: edges updated, types_declared unchanged
- [ ] Patch with declaration change: type_to_projects rebuilt, broader edges updated
- [ ] Patch with .csproj reference change: project_reference edges rebuilt
- [ ] Patch with .csproj namespace change: namespace_to_project rebuilt
- [ ] Patch with deleted .cs file: edges from project rebuilt without deleted file
- [ ] Patch with new .cs file: new file's facts extracted and edges created
- [ ] Content hash early cutoff: unchanged content → no re-extraction
- [ ] Threshold exceeded → PatchResult(patch_applied=False)
- [ ] Structural change (.csproj added) → PatchResult(patch_applied=False)
- [ ] Empty changed_files list → no-op, return unchanged graph
- [ ] Git head unreachable → returns None, caller does full rebuild

---

## Phase 4: Integration + Property Tests (~1 day)

### 4.1 Wire into `graph_enrichment.py`

Update `build_graph_context()` to use incremental path:

```python
def build_graph_context(search_scope, config, args) -> Optional[GraphContext]:
    # ... existing cache loading ...

    cache_result = load_and_validate(cache_path, search_scope, config.graph.invalidation)

    if cache_result is not None:
        graph, file_facts, project_facts = cache_result

        if file_facts is not None and not config.graph.rebuild:
            # v2 cache — try incremental patch
            changed = get_changed_files(cached_git_head, search_scope)
            if changed is not None and len(changed) > 0:
                result = patch_graph(graph, file_facts, project_facts,
                                     changed, search_scope)
                if result.patch_applied:
                    save_graph(result.graph, cache_path, search_scope,
                               result.file_facts, result.project_facts)
                    graph = result.graph
                    logging.info(f"Incremental graph update: {result.files_processed} files, "
                                 f"{result.projects_affected} projects ({result.elapsed_ms}ms)")
                else:
                    graph = None  # fall through to full rebuild
            elif changed is not None and len(changed) == 0:
                logging.info("Using cached dependency graph (no changes detected).")
            else:
                graph = None  # git diff failed, full rebuild
        else:
            # v1 cache or --rebuild-graph
            graph = None  # fall through to full rebuild

    if graph is None:
        # Full rebuild (captures facts for v2 cache)
        graph, file_facts, project_facts = build_dependency_graph(
            search_scope, ..., capture_facts=True)
        save_graph(graph, cache_path, search_scope, file_facts, project_facts)

    # ... compute metrics, cycles, return GraphContext ...
```

### 4.2 CLI surface

- No new flags needed. Incremental is automatic and transparent.
- `--rebuild-graph` forces full rebuild (bypasses incremental).
- Logging messages distinguish "cached (no changes)" vs "incremental update (Xms)" vs "full rebuild (Xs)".

### 4.3 Property-based tests

```python
def test_incremental_matches_full_rebuild():
    """The core correctness invariant: patched graph == fresh build."""
    for seed in range(100):
        # Generate synthetic codebase
        codebase = generate_synthetic_codebase(projects=30, seed=seed)

        # Full build
        graph_v1, facts_v1, pfacts_v1 = build_dependency_graph(
            codebase, capture_facts=True)

        # Apply random mutations
        changed_files = mutate_codebase(codebase, num_changes=10, seed=seed)

        # Incremental patch
        result = patch_graph(graph_v1, facts_v1, pfacts_v1,
                             changed_files, codebase)

        # Fresh full build on mutated codebase
        graph_full, _, _ = build_dependency_graph(codebase, capture_facts=True)

        # Compare
        assert_graphs_equivalent(result.graph, graph_full)

def mutate_codebase(path, num_changes, seed):
    """Apply random mutations to .cs files in a synthetic codebase.

    Mutation types:
    - Add/remove a using statement
    - Add/remove a type declaration
    - Add/remove a sproc reference
    - Change method body (usage-only change)
    - Delete a .cs file
    - Add a new .cs file
    Returns list of changed file paths (relative).
    """
```

### 4.4 Regression tests

- [ ] Analysis output (consumer lists, coupling scores) identical with cached vs fresh graph
- [ ] `--rebuild-graph` always produces a full rebuild
- [ ] Incremental update logging shows correct file/project counts
- [ ] v1 cache triggers full rebuild, saves as v2
- [ ] Cache file size at 500 projects is <15 MB

### Tests (Phase 4)
- [ ] Property test: incremental == full rebuild (100 iterations, 30 projects)
- [ ] Property test: incremental == full rebuild with declaration changes
- [ ] Property test: incremental == full rebuild with .csproj changes
- [ ] Regression: coupling scores identical after incremental
- [ ] Regression: cycle detection identical after incremental
- [ ] CLI: --rebuild-graph bypasses incremental
- [ ] CLI: logging distinguishes cached/incremental/full
- [ ] End-to-end: target-project analysis with incremental graph

---

## Module Changes Summary

| File | Change | Size |
|------|--------|------|
| `scatter/store/graph_cache.py` | Add FileFacts/ProjectFacts dataclasses, v2 save/load, project_set_hash | ~80 lines added |
| `scatter/core/graph.py` | Add `remove_edges_from()`, `remove_edges_to()` | ~40 lines added |
| `scatter/store/graph_patcher.py` | **NEW** — patch_graph(), extract helpers, git diff, edge rebuilders | ~300 lines |
| `scatter/analyzers/graph_builder.py` | Add `capture_facts=True` option, return facts | ~30 lines added |
| `scatter/analyzers/graph_enrichment.py` | Wire incremental path into build_graph_context() | ~25 lines changed |
| `test_graph_cache.py` | v2 format tests, migration tests | ~40 lines added |
| `test_graph.py` | remove_edges_from/to tests | ~30 lines added |
| `test_graph_patcher.py` | **NEW** — patch algorithm, edge cases, property tests | ~400 lines |
| `tools/generate_synthetic_codebase.py` | Add `mutate_codebase()` function | ~80 lines added |

**Total:** ~1,025 lines across 9 files (1 new module, 1 new test file).

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Incremental produces wrong graph | Medium | High | Property-based testing (100 iterations) |
| Cache file too large at enterprise scale | Low | Medium | Measure at 2,000 projects; compress if needed |
| Git diff unavailable (shallow clone, non-git) | Low | None | Falls back to full rebuild automatically |
| Edge removal breaks graph invariants | Medium | High | Explicit tests for all 4 index updates |
| Performance regression on full rebuild path | Low | Medium | Full rebuild path unchanged; facts capture is O(0) overhead |

---

## Success Criteria

1. PR with 10 changed files, 500-project repo: graph update <1 second
2. Property test passes: incremental == full rebuild for 100 random mutations
3. No regression in existing 539 tests
4. Cache v1 → v2 migration is seamless (one full rebuild, then incremental)
5. `--rebuild-graph` always bypasses incremental (escape hatch)
6. Zero new external dependencies

---

## Dependencies

- **Depends on:** Nothing — can start immediately
- **Blocks:** Tier 2 CI/CD gates (--fail-on) — incremental makes CI viable
- **Related:** Graph builder performance optimization (benefits from faster full rebuilds as fallback)

---

## Execution Order

1. Phase 1 (cache format) — must land first, v1→v2 migration
2. Phase 2 (graph mutation + extraction) — can develop in parallel with Phase 1
3. Phase 3 (patch algorithm) — depends on Phase 1 + 2
4. Phase 4 (integration + property tests) — depends on Phase 3
