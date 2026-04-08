# Initiative 5: Dependency Graph, Metrics & Domain Analysis

## Context

Initiatives 1-4 built a parallelized, AI-enriched dependency analyzer that works one-target-at-a-time: you specify a project (or SOW text), and Scatter finds its consumers. Initiative 5 inverts the model — scan the *entire* codebase once, build a persistent dependency graph, and answer structural questions: coupling hotspots, circular dependencies, natural service boundaries, and database ownership.

This is the shift from "point analysis" to "whole-codebase analysis."

### What exists today

- `find_consumers()` — 5-step pipeline, one target at a time, returns `List[Dict]`
- `trace_transitive_impact()` — BFS with visited-set cycle avoidance (not detection)
- `parse_csproj_files_batch()` — parses XML but only checks "does this reference target X?"
- `derive_namespace()` — extracts RootNamespace/AssemblyName from .csproj
- `find_cs_files_referencing_sproc()` — string-literal sproc detection
- No adjacency list, no graph data structure, no metrics, no persistence layer

### What needs to be built

A `DependencyGraph` with nodes (projects), typed edges (reference/usage/db), query methods, cycle detection, clustering, metrics, persistence, and reporters. Built in phases so each phase delivers testable value.

---

## Phase Breakdown

| Phase | Deliverable | Files | Depends on |
|-------|-------------|-------|------------|
| **Phase 1** | Graph model + bulk builder | `core/graph.py`, `analyzers/graph_builder.py` | Nothing |
| **Phase 2** | Metrics + cycle detection | `analyzers/coupling_analyzer.py` | Phase 1 |
| **Phase 3** | Persistence + CLI integration | `store/graph_cache.py`, `__main__.py` changes | Phase 1 |
| **Phase 4** | Database dependency mapping | `scanners/db_scanner.py` | Phase 1 |
| **Phase 5** | Domain boundary detection | `analyzers/domain_analyzer.py` | Phase 2 |
| **Phase 6** | Graph reporters + health dashboard | `reports/graph_reporter.py` | Phases 2, 5 |

**Parallelism note:** Phases 2, 3, and 4 all depend only on Phase 1 and are independent of each other. They can be developed in any order or in parallel after Phase 1 is complete.

---

## Phase 1: Graph Model + Bulk Builder

### Goal

Define the core data structures and build the graph from a codebase in a single pass.

### 1.1 Data models — `scatter/core/graph.py`

**Design principle: DependencyGraph is a pure data structure.** It owns mutation, query, traversal, serialization, and properties. All analysis algorithms (cycle detection, metrics, clustering, Mermaid generation, diffing) are standalone functions that accept a graph as input. This avoids circular imports and keeps the class focused (SRP).

```python
MAX_EVIDENCE_ENTRIES = 10  # cap evidence lists to prevent unbounded growth

@dataclass
class ProjectNode:
    """A .csproj project in the dependency graph."""
    path: Path                              # absolute path to .csproj
    name: str                               # stem of .csproj (e.g. "GalaxyWorks.Data")
    namespace: Optional[str]                # derived via derive_namespace()
    framework: Optional[str]                # e.g. "net8.0", "v4.7.2"
    project_style: str                      # "sdk" or "framework" (SDK-style vs legacy)
    output_type: Optional[str]              # "Library", "Exe", etc.
    file_count: int                         # number of .cs files (not stored: paths reconstructed on load)
    type_declarations: List[str]            # class/struct/interface/enum names
    sproc_references: List[str]             # stored procedure names found in source

@dataclass
class DependencyEdge:
    """A directed dependency between two projects."""
    source: str                             # project name (the dependent)
    target: str                             # project name (the dependency)
    edge_type: str                          # "project_reference", "namespace_usage",
                                            # "type_usage", "sproc_shared"
    weight: float = 1.0                     # strength (number of usages, etc.)
    evidence: Optional[List[str]] = None    # files/lines that prove this edge (max 10)
    evidence_total: int = 0                 # total evidence count when > MAX_EVIDENCE_ENTRIES

class DependencyGraph:
    """Directed dependency graph of .NET projects.

    Pure data structure — mutation, query, traversal, serialization only.
    Analysis algorithms (cycles, metrics, clustering) are standalone functions
    in their respective analyzer modules.
    """

    def __init__(self):
        self._nodes: Dict[str, ProjectNode] = {}
        # Per-node edge indexes for O(degree) lookups
        self._outgoing: Dict[str, List[DependencyEdge]] = defaultdict(list)  # source -> edges
        self._incoming: Dict[str, List[DependencyEdge]] = defaultdict(list)  # target -> edges
        # Adjacency sets for O(1) neighbor checks
        self._forward: Dict[str, Set[str]] = defaultdict(set)   # project -> its dependencies
        self._reverse: Dict[str, Set[str]] = defaultdict(set)   # project -> its consumers

    # --- Mutation ---
    def add_node(self, node: ProjectNode) -> None
    def add_edge(self, edge: DependencyEdge) -> None
        # Validates source/target exist, caps evidence to MAX_EVIDENCE_ENTRIES

    # --- Query ---
    def get_node(self, name: str) -> Optional[ProjectNode]
    def get_all_nodes(self) -> List[ProjectNode]
    def get_dependencies(self, name: str) -> List[ProjectNode]      # what does this project depend on?
    def get_consumers(self, name: str) -> List[ProjectNode]          # what depends on this project?
    def get_edges_from(self, name: str) -> List[DependencyEdge]      # outgoing edges — O(degree)
    def get_edges_to(self, name: str) -> List[DependencyEdge]        # incoming edges — O(degree)
    def get_edges_for(self, name: str) -> List[DependencyEdge]       # all edges involving this project — O(degree)
    def get_edges_between(self, a: str, b: str) -> List[DependencyEdge]  # O(degree of a)

    # --- Traversal ---
    def get_transitive_consumers(self, name: str, max_depth: int = 3) -> List[Tuple[ProjectNode, int]]
    def get_transitive_dependencies(self, name: str, max_depth: int = 3) -> List[Tuple[ProjectNode, int]]

    # --- Export ---
    def to_dict(self) -> Dict[str, Any]                     # JSON-serializable
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DependencyGraph"

    # --- Properties ---
    @property
    def node_count(self) -> int
    @property
    def edge_count(self) -> int
    @property
    def all_edges(self) -> List[DependencyEdge]             # flat list for serialization
    @property
    def connected_components(self) -> List[List[str]]
```

**Design decisions:**

- **String-keyed nodes** — project name is the canonical key. Paths can collide on case-insensitive filesystems; names are the user-facing identifier.
- **Per-node edge indexes** — `_outgoing[source]` and `_incoming[target]` give O(degree) lookups for `get_edges_for()`, `get_edges_from()`, `get_edges_to()`, and `get_edges_between()`. This is critical because `compute_all_metrics()` calls these for every node — indexed lookups give O(N+E) total vs O(N*E) with a flat list. Adjacency sets (`_forward`, `_reverse`) provide O(1) neighbor membership checks. All four structures are maintained in sync by `add_edge()`.
- **Immutable-ish** — `add_node`/`add_edge` are the only mutators. No `remove_*` needed for v1 (graph is built fresh or loaded from cache, never incrementally modified).
- **No analysis methods on graph** — `detect_cycles()`, `compute_all_metrics()`, `find_clusters()`, `generate_mermaid()`, and `diff()` are all free functions in their respective modules. This eliminates circular imports (`graph.py` ← `coupling_analyzer.py` ← `graph.py`) and follows the standard pattern in scientific computing (algorithms operate on data structures, they don't live on them).
- **Evidence capping** — `add_edge()` truncates `evidence` lists to `MAX_EVIDENCE_ENTRIES` (default 10) and sets `evidence_total` to the original count. For a type used in 500 files, storing all 500 paths is wasteful; 10 representative examples plus a count is sufficient for reporting.
- **`file_count` instead of `files: List[Path]`** — `ProjectNode` stores the count of .cs files, not the full path list. For large projects with hundreds of files, serializing all paths to the cache is wasteful. The file list is used transiently during graph building but not persisted. If a consumer needs the actual files, they can re-scan the project directory.

### 1.2 Graph builder — `scatter/analyzers/graph_builder.py`

```python
def build_dependency_graph(
    search_scope: Path,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    exclude_patterns: Optional[List[str]] = None,
) -> DependencyGraph:
    """Build a complete dependency graph from a codebase directory.

    Single-pass construction:
    1. Discover all .csproj files (reuses find_files_with_pattern_parallel)
    2. Parse each .csproj to extract:
       - ProjectReferences (-> project_reference edges)
       - RootNamespace / AssemblyName
       - TargetFramework
       - OutputType
       - Project style (SDK vs Framework)
    3. Discover .cs files and map to parent projects via reverse index
    4. For each project's .cs files:
       - Extract type declarations (reuses extract_type_names_from_content)
       - Detect stored procedure references (reuses sproc detection regex)
       - Detect namespace usages (-> namespace_usage edges)
    5. For each namespace_usage edge, check if the consuming file also uses
       specific types (-> type_usage edges with weight = usage count)
    6. Build DependencyGraph with all nodes and edges
    """
```

**Key architectural choice: single-pass vs reuse `find_consumers()`**

`find_consumers()` is designed for one target — calling it N times for N projects would parse all .csproj files N times. Instead, `build_dependency_graph()` does a *single pass*:

1. Parse all `.csproj` files once → extract ALL `<ProjectReference>` entries → build complete adjacency list
2. Scan all `.cs` files once → extract type declarations, namespace usages, and sproc references
3. Cross-reference the results to construct typed edges

This gives O(P + F) complexity instead of O(P * P) where P = projects, F = files.

**Reuse of existing functions:**

| Existing function | Reused for |
|-------------------|-----------|
| `find_files_with_pattern_parallel("*.csproj")` | Step 1: discover .csproj files |
| `find_files_with_pattern_parallel("*.cs")` | Step 3: discover .cs files |
| `derive_namespace(csproj_path)` | Step 2: namespace extraction |
| `extract_type_names_from_content(content)` | Step 4: type declarations |
| `parse_csproj_files_batch(paths, target)` | **NOT reused** — needs new function that extracts ALL references |

**NOT reused: `find_project_file_on_disk()`** — this function walks up directory trees per file, which is O(F * depth). Instead, the builder constructs a **reverse index** during Step 2: for each `.csproj`, compute its project directory. In Step 3, assign each `.cs` file to the project whose directory is its closest ancestor via sorted prefix matching. This is O(F * log(P)) with a sorted project list — much faster for large codebases.

```python
def _build_project_directory_index(
    csproj_paths: List[Path],
) -> Dict[Path, str]:
    """Build reverse index: project_directory -> project_name.

    Sorted by path depth (deepest first) so nested projects
    match before parent projects.
    """

def _map_cs_to_project(
    cs_path: Path,
    project_dirs: List[Tuple[Path, str]],  # sorted deepest-first
) -> Optional[str]:
    """Find the closest ancestor project for a .cs file.

    Walks up cs_path parents, checks against sorted project dirs.
    Returns project name or None if no parent project found.
    """
```

**New parsing function needed:**

```python
def parse_csproj_all_references(csproj_path: Path) -> Dict[str, Any]:
    """Parse a .csproj file and extract all metadata.

    Returns dict with keys:
    - 'project_references': List[str]  — relative paths from <ProjectReference>
    - 'root_namespace': Optional[str]
    - 'target_framework': Optional[str]
    - 'output_type': Optional[str]
    - 'project_style': str  — "sdk" or "framework"
    """
```

This function lives in `scatter/scanners/project_scanner.py` alongside `derive_namespace()`.

### 1.3 Parallelization strategy

The builder reuses the existing multiprocessing infrastructure:

| Step | Parallelized via | Chunk size |
|------|-----------------|------------|
| .csproj discovery | `find_files_with_pattern_parallel` | `chunk_size` (default 75 dirs) |
| .csproj XML parsing | `ProcessPoolExecutor` with batch function | `csproj_analysis_chunk_size` (25) |
| .cs file discovery | `find_files_with_pattern_parallel` | `chunk_size` |
| .cs-to-.csproj mapping | Reverse index lookup (no parallelization needed — O(F * log(P))) | N/A |
| .cs content analysis | `ProcessPoolExecutor` with batch function | `cs_analysis_chunk_size` (50) |

### 1.4 Tests — `test_graph.py`

**TestProjectNode** (~3 tests):
- `test_node_construction` — all fields populated
- `test_node_defaults` — optional fields default to None/empty
- `test_node_from_sample_project` — build node from real GalaxyWorks.Data .csproj

**TestDependencyEdge** (~3 tests):
- `test_edge_construction` — all fields
- `test_edge_defaults` — weight=1.0, evidence=None, evidence_total=0
- `test_evidence_capping` — evidence list truncated to MAX_EVIDENCE_ENTRIES, evidence_total set

**TestDependencyGraph** (~17 tests):
- `test_empty_graph` — node_count=0, edge_count=0
- `test_add_node` — node retrievable by name
- `test_add_edge` — edge retrievable, adjacency updated, edge indexes populated
- `test_get_dependencies` — returns correct dependency list
- `test_get_consumers` — returns correct consumer list (reverse lookup)
- `test_get_edges_from` — returns outgoing edges for a node — O(degree)
- `test_get_edges_to` — returns incoming edges for a node — O(degree)
- `test_get_edges_for` — returns all edges (incoming + outgoing) for a node
- `test_get_edges_between` — returns edges between two specific nodes
- `test_transitive_consumers_depth_1` — one hop
- `test_transitive_consumers_depth_2` — two hops (BatchProcessor → WebPortal → Data)
- `test_transitive_consumers_cycle_safe` — doesn't infinite loop on cycles
- `test_connected_components` — identifies GalaxyWorks and MyDotNetApp clusters
- `test_to_dict_roundtrip` — serialize → deserialize → equal
- `test_duplicate_node_rejected` — adding same name twice raises or warns
- `test_edge_to_unknown_node` — adding edge with unknown source/target raises
- `test_all_edges_property` — returns flat list of all edges

**TestGraphBuilder** (~8 tests, integration):
- `test_build_from_sample_projects` — builds graph from repo's sample .NET projects
- `test_node_count` — 8 projects found (all .csproj in repo, excluding temp_test_data)
- `test_edge_count` — correct number of project_reference edges
- `test_galaxyworks_data_consumers` — 4 consumers (WebPortal, BatchProcessor, 2x ConsumerApp)
- `test_mydotnetapp_consumers` — 1 consumer (MyDotNetApp.Consumer)
- `test_exclude_has_zero_edges` — MyDotNetApp2.Exclude is isolated
- `test_framework_detection` — WebPortal detected as "framework", Data as "sdk"
- `test_namespace_extraction` — namespaces correctly derived for all projects

**TestParseCsprojAllReferences** (~5 tests):
- `test_sdk_style_project` — extracts references, namespace, framework from SDK .csproj
- `test_framework_style_project` — handles MSBuild namespace, HintPath references
- `test_no_references` — project with zero ProjectReferences
- `test_multiple_references` — project with 2+ references (BatchProcessor)
- `test_missing_file` — returns None or raises for nonexistent path

**TestProjectDirectoryIndex** (~3 tests):
- `test_build_index` — correct directory-to-project mapping
- `test_map_cs_to_project` — .cs file assigned to correct parent project
- `test_nested_projects` — deeper project directory wins over parent

### 1.5 Files to create/modify

| File | Action |
|------|--------|
| `scatter/core/graph.py` | **Create** — `ProjectNode`, `DependencyEdge`, `DependencyGraph` |
| `scatter/analyzers/graph_builder.py` | **Create** — `build_dependency_graph()`, `_build_project_directory_index()`, `_map_cs_to_project()` |
| `scatter/scanners/project_scanner.py` | **Modify** — add `parse_csproj_all_references()` |
| `test_graph.py` | **Create** — ~39 tests |

---

## Phase 2: Metrics + Cycle Detection

### Goal

Compute coupling metrics for every project and detect circular dependency groups.

### 2.1 Coupling metrics — `scatter/analyzers/coupling_analyzer.py`

All functions are **standalone free functions** that accept a `DependencyGraph` as input.

```python
# --- Configurable weights ---
# Rationale: project references are "hard" coupling (compile-time dependency),
# sproc_shared is nearly as hard (shared mutable state), namespace usage is "soft"
# (may or may not indicate real coupling), type usage is softest (could be a single enum ref).
DEFAULT_COUPLING_WEIGHTS: Dict[str, float] = {
    "project_reference": 1.0,
    "namespace_usage": 0.5,
    "type_usage": 0.3,
    "sproc_shared": 0.8,
}

@dataclass
class ProjectMetrics:
    """Coupling and structural metrics for a single project."""
    fan_in: int                         # number of projects that depend on this one
    fan_out: int                        # number of projects this one depends on
    instability: float                  # fan_out / (fan_in + fan_out), 0.0-1.0
    coupling_score: float               # weighted interconnectedness measure
    afferent_coupling: int              # number of incoming edges (all types)
    efferent_coupling: int              # number of outgoing edges (all types)
    shared_db_density: float            # fraction of sprocs shared with other projects
    type_export_count: int              # number of type declarations
    consumer_count: int                 # total direct consumers (fan_in alias for clarity)

def compute_all_metrics(
    graph: DependencyGraph,
    coupling_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, ProjectMetrics]:
    """Compute metrics for every node in the graph.

    Uses graph._outgoing and graph._incoming edge indexes for
    O(N + E) total traversal instead of O(N * E) flat-list scan.

    Args:
        graph: The dependency graph to analyze.
        coupling_weights: Optional override for edge type weights.
            Defaults to DEFAULT_COUPLING_WEIGHTS.
    """

def rank_by_coupling(metrics: Dict[str, ProjectMetrics], top_n: int = 10) -> List[Tuple[str, ProjectMetrics]]:
    """Return the top-N most coupled projects by coupling_score."""
```

**Metric definitions:**

| Metric | Formula | Interpretation |
|--------|---------|---------------|
| fan_in | count of project_reference edges pointing TO this project | How many projects depend on me |
| fan_out | count of project_reference edges pointing FROM this project | How many projects I depend on |
| instability | fan_out / (fan_in + fan_out), 0.0 if both are 0 | 0.0 = maximally stable, 1.0 = maximally unstable |
| coupling_score | weighted sum using configurable weights (default: `1.0 * project_ref + 0.5 * namespace + 0.3 * type + 0.8 * sproc_shared`) | Overall interconnectedness |
| shared_db_density | sprocs_shared_with_other_projects / total_sprocs_in_project, 0.0 if no sprocs | Database coupling intensity |

**coupling_score weight rationale:**
- `project_reference = 1.0` — hard compile-time dependency, breaking changes propagate directly
- `sproc_shared = 0.8` — shared mutable database state, nearly as tight as direct reference
- `namespace_usage = 0.5` — indicates awareness of another project but may not use any types
- `type_usage = 0.3` — softest signal, could be a single enum reference or utility class

Weights are configurable via the `coupling_weights` parameter and can be overridden in `.scatter.yaml`:

```yaml
graph:
  coupling_weights:
    project_reference: 1.0
    namespace_usage: 0.5
    type_usage: 0.3
    sproc_shared: 0.8
```

**Instability index edge case:** When both fan_in and fan_out are 0 (orphan project like MyDotNetApp2.Exclude), instability is defined as 0.0 (stable by default — it's not going to break anything because nothing depends on it and it depends on nothing).

### 2.2 Cycle detection — `scatter/analyzers/coupling_analyzer.py`

Cycle detection is a **standalone free function**, not a method on `DependencyGraph`.

```python
@dataclass
class CycleGroup:
    """A strongly connected component with size > 1 — a circular dependency tangle."""
    projects: List[str]                 # project names in the SCC, sorted alphabetically
    size: int                           # number of projects
    shortest_cycle: List[str]           # one representative shortest cycle within the SCC
    edge_count: int                     # number of edges within the SCC

def detect_cycles(graph: DependencyGraph) -> List[CycleGroup]:
    """Find all circular dependency groups using Tarjan's SCC algorithm.

    Returns list of CycleGroups (SCCs with size > 1), sorted by size
    (smallest first — often the easiest to break).

    For each SCC, a representative shortest cycle is extracted via BFS
    to give users a concrete example of the circularity.

    Why Tarjan's SCC instead of enumerating all simple cycles:
    - A graph with N nodes can have exponentially many simple cycles.
      Enumerating all of them is O(2^N) in the worst case.
    - DFS back-edge detection finds *a* cycle, not *all* cycles, and
      can miss cycles in complex graphs.
    - Tarjan's SCC runs in O(N + E), identifies all groups of mutually
      reachable nodes, and gives users actionable information: "these
      projects form a circular dependency tangle."
    - Within each SCC, we extract one shortest cycle via BFS as a
      concrete illustration. This is what users actually need for
      remediation.
    """
```

**Implementation detail — Tarjan's algorithm:**

```python
def _tarjans_scc(graph: DependencyGraph) -> List[List[str]]:
    """Tarjan's strongly connected components algorithm.

    O(N + E) time, O(N) space.
    Returns all SCCs (including singletons). Caller filters to size > 1.
    """

def _shortest_cycle_in_scc(
    graph: DependencyGraph,
    scc: List[str],
) -> List[str]:
    """Find shortest cycle within an SCC via BFS from each node.

    For small SCCs (typical in real codebases), this is fast.
    For large SCCs (>50 nodes), BFS from first node only — O(N + E) per SCC.
    """
```

### 2.3 Tests — `test_coupling.py`

**TestProjectMetrics** (~3 tests):
- `test_metrics_construction` — all fields populated
- `test_instability_calculation` — verify formula
- `test_orphan_instability` — fan_in=0, fan_out=0 → instability=0.0

**TestComputeAllMetrics** (~9 tests, using sample projects):
- `test_galaxyworks_data_metrics` — fan_in=4, fan_out=0, instability=0.0
- `test_batch_processor_metrics` — fan_in=0, fan_out=2, instability=1.0
- `test_webportal_metrics` — fan_in=1, fan_out=1, instability=0.5
- `test_exclude_metrics` — fan_in=0, fan_out=0, instability=0.0
- `test_all_projects_have_metrics` — 8 projects, 8 metric entries
- `test_coupling_score_ordering` — Data has highest coupling score (most edges)
- `test_rank_by_coupling` — top-3 returns correct ordering
- `test_shared_db_density` — GalaxyWorks.Data has sproc references, others may share them
- `test_custom_coupling_weights` — override weights, verify coupling_score changes

**TestCycleDetection** (~8 tests):
- `test_no_cycles` — sample projects return empty list
- `test_simple_cycle` — A→B→A detected as one CycleGroup with shortest_cycle=["A","B"]
- `test_triangle_cycle` — A→B→C→A detected as CycleGroup with size=3
- `test_multiple_independent_sccs` — graph with 2 separate SCCs finds both CycleGroups
- `test_self_loop` — A→A detected as CycleGroup with size=1, shortest_cycle=["A"]
- `test_large_scc_with_shortest_cycle` — 5-node SCC, verify shortest_cycle is correct
- `test_scc_sorted_by_size` — smallest CycleGroup first
- `test_tarjans_linear_time` — verify O(N+E) by checking all nodes/edges visited once

### 2.4 Files to create/modify

| File | Action |
|------|--------|
| `scatter/analyzers/coupling_analyzer.py` | **Create** — `ProjectMetrics`, `CycleGroup`, `compute_all_metrics()`, `detect_cycles()`, `rank_by_coupling()`, `_tarjans_scc()`, `_shortest_cycle_in_scc()` |
| `test_coupling.py` | **Create** — ~20 tests |

---

## Phase 3: Persistence + CLI Integration

### Goal

Cache the dependency graph to disk so subsequent runs are instant, and add CLI commands to build/query it.

### 3.1 Graph cache — `scatter/store/graph_cache.py`

```python
def save_graph(graph: DependencyGraph, cache_path: Path) -> None:
    """Serialize graph to JSON file."""

def load_graph(cache_path: Path) -> Optional[DependencyGraph]:
    """Load graph from cache. Returns None if cache missing or corrupt."""

def is_cache_valid(cache_path: Path, search_scope: Path) -> bool:
    """Check if the cached graph is still valid.

    Invalidation strategies:
    1. Git-based (preferred): use `git diff --name-only <cached_hash> HEAD -- '*.csproj' '*.cs'`
       to check if any code files actually changed. If only non-code files changed
       (README, .yaml, docs), the cache remains valid. Falls back to full rebuild
       if git command fails.
    2. Mtime-based (fallback for non-git dirs): compare newest .csproj/.cs
       mtime against cache file mtime.
    """

def get_default_cache_path(search_scope: Path) -> Path:
    """Return default cache location: {search_scope}/.scatter/graph_cache.json"""
```

**Cache invalidation — smart git-based strategy:**

The naive approach (compare HEAD hash) invalidates on *any* commit, even documentation-only changes. Instead, we check whether `.csproj` or `.cs` files actually changed:

```python
def _git_has_code_changes(cached_hash: str, search_scope: Path) -> bool:
    """Check if any .csproj or .cs files changed since cached_hash.

    Runs: git diff --name-only <cached_hash> HEAD -- '*.csproj' '*.cs'
    Returns True if any code files changed (cache is stale).
    Returns True if git command fails (conservative fallback).
    """
```

This dramatically improves cache hit rates in repos with frequent non-code commits.

**Cache file format:**

```json
{
  "version": 1,
  "created_at": "2026-03-07T14:30:00Z",
  "search_scope": "/path/to/repo",
  "git_head": "abc123def",
  "node_count": 8,
  "edge_count": 6,
  "graph": { ... }
}
```

### 3.2 CLI integration — `scatter/__main__.py`

Add a new mode:

```
python -m scatter --graph --search-scope .                    # build + print summary
python -m scatter --graph --search-scope . --rebuild-graph    # force rebuild
python -m scatter --graph --search-scope . --output-format json --output-file graph.json
```

New arguments:

| Flag | Description |
|------|-------------|
| `--graph` | MODE: Dependency graph analysis |
| `--rebuild-graph` | Force graph rebuild (ignore cache) |

The `--graph` flag goes into the existing mutually exclusive mode group.

When `--graph` is selected:
1. Check for cached graph (unless `--rebuild-graph`)
2. If cache miss or stale, call `build_dependency_graph()`
3. Save to cache
4. Compute metrics via `compute_all_metrics(graph)`
5. Detect cycles via `detect_cycles(graph)`
6. Output via appropriate reporter

### 3.3 Config additions — `scatter/config.py`

```python
@dataclass
class GraphConfig:
    cache_dir: Optional[str] = None       # override default cache location
    rebuild: bool = False                  # force rebuild
    invalidation: str = "git"             # "git" or "mtime"
    coupling_weights: Optional[Dict[str, float]] = None  # override DEFAULT_COUPLING_WEIGHTS
```

Add to `ScatterConfig`:

```python
@dataclass
class ScatterConfig:
    ai: AIConfig = ...
    graph: GraphConfig = field(default_factory=GraphConfig)
    ...
```

YAML schema:

```yaml
graph:
  cache_dir: .scatter
  invalidation: git     # "git" or "mtime"
  coupling_weights:     # optional — override default edge type weights
    project_reference: 1.0
    namespace_usage: 0.5
    type_usage: 0.3
    sproc_shared: 0.8
```

### 3.4 Tests — `test_graph_cache.py`

**TestGraphCache** (~10 tests):
- `test_save_load_roundtrip` — save graph, load it, verify equality
- `test_load_missing_file` — returns None
- `test_load_corrupt_file` — returns None, logs warning
- `test_cache_valid_git_no_code_changes` — non-code commit → cache still valid
- `test_cache_invalid_git_csproj_changed` — .csproj changed → cache invalid
- `test_cache_invalid_git_cs_changed` — .cs file changed → cache invalid
- `test_cache_valid_mtime` — no .csproj/.cs newer than cache → valid
- `test_cache_invalid_mtime` — .csproj newer than cache → invalid
- `test_default_cache_path` — returns {scope}/.scatter/graph_cache.json
- `test_git_command_failure_fallback` — git fails → conservative rebuild

### 3.5 Files to create/modify

| File | Action |
|------|--------|
| `scatter/store/__init__.py` | **Create** — empty |
| `scatter/store/graph_cache.py` | **Create** — save/load/validate |
| `scatter/__main__.py` | **Modify** — add `--graph` mode |
| `scatter/config.py` | **Modify** — add `GraphConfig` |
| `test_graph_cache.py` | **Create** — ~10 tests |

---

## Phase 4: Database Dependency Mapping

### Goal

Go beyond stored procedure string matching. Detect EF models, direct SQL, and connection strings. Build `sproc_shared` edges in the dependency graph.

### 4.1 Enhanced DB scanner — `scatter/scanners/db_scanner.py`

```python
# Configurable sproc prefixes — default covers common conventions,
# users can extend via .scatter.yaml for custom naming (e.g. "proc_", "fn_")
DEFAULT_SPROC_PREFIXES: List[str] = ["sp_", "usp_"]

@dataclass
class DbDependency:
    """A database dependency found in source code."""
    db_object_name: str                 # sproc name, table name, etc.
    db_object_type: str                 # "sproc", "table", "view", "ef_model", "connection_string"
    source_file: Path                   # .cs file where found
    source_project: str                 # parent .csproj name
    containing_class: Optional[str]     # enclosing class name
    detection_method: str               # "string_literal", "ef_dbset", "ef_dbcontext", "sql_text"
    line_number: Optional[int]          # for evidence

def scan_db_dependencies(
    search_scope: Path,
    max_workers: int = DEFAULT_MAX_WORKERS,
    disable_multiprocessing: bool = False,
    sproc_prefixes: Optional[List[str]] = None,
) -> List[DbDependency]:
    """Scan all .cs files for database dependencies.

    Preprocessing: Before applying detection regexes, strip C# comments
    (single-line // and multi-line /* */) from file content to prevent
    false positives from commented-out code or documentation.

    Detection methods:
    1. Stored procedure names in string literals (configurable prefixes)
    2. DbContext subclasses → extract DbSet<T> → T is the EF model/table
    3. Direct SQL: regex for SELECT/INSERT/UPDATE/DELETE inside string literals
    4. Connection strings: regex for "Data Source=", "Server=", "Database="
    """

def build_db_dependency_matrix(
    dependencies: List[DbDependency]
) -> Dict[str, List[str]]:
    """Build a cross-project DB object matrix.

    Returns: {db_object_name: [project_names_that_reference_it]}
    Objects referenced by 2+ projects are shared dependencies.
    """

def add_db_edges_to_graph(
    graph: DependencyGraph,
    dependencies: List[DbDependency]
) -> None:
    """Add sproc_shared edges for DB objects shared between projects."""
```

**Comment stripping preprocessor:**

```python
def _strip_cs_comments(content: str) -> str:
    """Remove C# single-line and multi-line comments from source.

    Handles:
    - // single-line comments (to end of line)
    - /* multi-line comments */ (including nested)
    - String literals preserved (comments inside strings are NOT stripped)

    ~10 lines using a simple state machine or regex.
    Applied before all detection patterns to eliminate false positives.
    """
```

**Detection patterns:**

| What | Regex / Pattern | Example match | False positive mitigation |
|------|----------------|---------------|--------------------------|
| Stored procs | `["'](?:\w+\.)?(?:{prefixes})\w+["']` | `"dbo.sp_Insert..."` | Comment stripping + string literal context + configurable prefixes |
| EF DbSet | `DbSet<(\w+)>` | `public DbSet<PortalConfiguration> ...` | Very reliable pattern, minimal false positives |
| EF DbContext | `class\s+(\w+)\s*:\s*DbContext` | `class AppDbContext : DbContext` | Very reliable pattern |
| Direct SQL | `["'](?:SELECT\|INSERT\|UPDATE\|DELETE)\s+.*?(?:FROM\|INTO)\s+[\["]?(\w+)[\]"]?` | `"SELECT * FROM Users"` | Requires opening quote — only matches SQL inside string literals |
| Connection string | `["'].*?(?:Data Source\|Server\|Database)\s*=\s*([^;'"]+)` | `"Server=myserver;Database=mydb"` | Requires string literal context |

**Configurable sproc prefixes via `.scatter.yaml`:**

```yaml
db:
  sproc_prefixes:
    - "sp_"
    - "usp_"
    - "proc_"    # custom prefix for this codebase
```

### 4.2 Integration with graph builder

`build_dependency_graph()` (from Phase 1) gets an optional step 6:

```python
# Step 6 (optional): DB dependency scan
if include_db_dependencies:
    db_deps = scan_db_dependencies(search_scope, ...)
    add_db_edges_to_graph(graph, db_deps)
```

### 4.3 Tests — `test_db_scanner.py`

**TestCommentStripping** (~3 tests):
- `test_strip_single_line_comments` — `// sp_Foo` removed, sproc in code preserved
- `test_strip_multi_line_comments` — `/* sp_Foo */` removed
- `test_preserve_strings` — `"// not a comment"` preserved

**TestDbDependencyDetection** (~12 tests):
- `test_detect_sproc_string_literal` — finds `"dbo.sp_InsertPortalConfiguration"` in sample projects
- `test_detect_sproc_without_schema` — finds `"sp_GetPortalConfigurationDetails"`
- `test_detect_sproc_custom_prefix` — finds `"proc_MyCustom"` with custom prefix list
- `test_detect_dbset_pattern` — synthetic .cs file with `DbSet<User>`
- `test_detect_dbcontext_subclass` — synthetic .cs file with `class AppDb : DbContext`
- `test_detect_direct_sql_in_string` — synthetic .cs file with `"SELECT * FROM Users"` in string literal
- `test_no_match_bare_sql_keyword` — bare `SELECT` outside string literal not matched
- `test_detect_connection_string` — synthetic .cs file with connection string pattern
- `test_no_false_positives_on_comments` — sproc name in `// comment` or `/* block */` not matched
- `test_scan_sample_projects` — integration test against real GalaxyWorks files
- `test_build_db_matrix` — shared sprocs appear in matrix with 2+ projects
- `test_add_db_edges` — sproc_shared edges added to graph

### 4.4 Files to create/modify

| File | Action |
|------|--------|
| `scatter/scanners/db_scanner.py` | **Create** — `DbDependency`, `_strip_cs_comments()`, detection functions |
| `scatter/analyzers/graph_builder.py` | **Modify** — optional DB dependency step |
| `scatter/config.py` | **Modify** — add `DbConfig` with `sproc_prefixes` |
| `test_db_scanner.py` | **Create** — ~15 tests |

---

## Phase 5: Domain Boundary Detection

### Goal

Identify natural service boundaries by clustering tightly-connected project groups, and assess extraction feasibility.

### 5.1 Domain analyzer — `scatter/analyzers/domain_analyzer.py`

All functions are **standalone free functions** that accept a `DependencyGraph`.

```python
@dataclass
class Cluster:
    """A group of tightly-connected projects — a candidate domain/service boundary."""
    name: str                                       # auto-generated or derived from common namespace prefix
    projects: List[str]                             # project names in this cluster
    internal_edges: int                             # edges between projects within the cluster
    external_edges: int                             # edges crossing the cluster boundary
    cohesion: float                                 # internal_edges / total_possible_internal_edges
    coupling_to_outside: float                      # external_edges / total_edges
    cross_boundary_dependencies: List[DependencyEdge]   # edges that cross the boundary
    extraction_feasibility: Optional[str]           # "easy", "moderate", "hard", "very_hard"

def find_clusters(
    graph: DependencyGraph,
    min_cluster_size: int = 2,
) -> List[Cluster]:
    """Detect natural service boundaries via two-level clustering.

    Strategy — connected components first, then label propagation for refinement:

    Level 1: Connected components (treating edges as undirected).
    This is deterministic, O(N + E), and gives the coarse grouping.
    For well-structured codebases (like the sample projects), this alone
    produces the right clusters.

    Level 2: For large connected components (> threshold, e.g. 20 nodes),
    apply label propagation to find sub-communities within the component.

    Label propagation determinism:
    - Nodes iterated in sorted order (alphabetical by name)
    - Ties broken by lowest label (alphabetical)
    - Max iterations capped at 100 to guarantee termination
    - These constraints make results fully reproducible

    For the sample projects, expected clusters:
    - GalaxyWorks cluster: Data, WebPortal, BatchProcessor, ConsumerApp, ConsumerApp2
    - MyDotNetApp cluster: MyDotNetApp, MyDotNetApp.Consumer
    - MyDotNetApp2.Exclude: isolated, filtered out (size < 2 if min_cluster_size=2)
    """

def score_extraction_feasibility(cluster: Cluster, graph: DependencyGraph) -> str:
    """Score how easy it would be to extract this cluster as a service.

    Factors:
    - Few cross-boundary edges → easier
    - No shared DB objects → easier
    - No circular dependencies with external projects → easier
    - Small API surface (few types used externally) → easier

    Returns: "easy", "moderate", "hard", "very_hard"
    """
```

**Why connected components + label propagation over pure label propagation?**

- Pure label propagation is non-deterministic — iteration order affects results. Running twice can produce different clusters.
- Connected components is deterministic, O(N+E), and handles the common case perfectly (separate project groups like GalaxyWorks vs MyDotNetApp).
- Label propagation is only needed as a refinement for large, monolithic connected components where sub-communities exist.
- This two-level approach gives deterministic results for simple graphs and reasonable results for complex ones.

### 5.2 AI boundary assessment (optional, LOW priority)

```python
def assess_boundary_with_ai(
    cluster: Cluster,
    graph: DependencyGraph,
    ai_provider: Optional[AIProvider],
) -> Optional[str]:
    """AI-generated assessment of extraction complexity for a cluster.

    Sends cluster composition, cross-boundary edges, and shared DB objects
    to AI for natural language analysis.
    """
```

This uses the existing `AIProvider` protocol and `AIRouter`. New task type: `AITaskType.BOUNDARY_ASSESSMENT`.

### 5.3 Tests — `test_domain.py`

**TestFindClusters** (~8 tests):
- `test_two_clusters_in_sample_projects` — GalaxyWorks cluster and MyDotNetApp cluster
- `test_isolated_node_excluded` — MyDotNetApp2.Exclude not in any cluster
- `test_cluster_cohesion` — GalaxyWorks cluster has correct internal/external edge counts
- `test_min_cluster_size` — min_cluster_size=3 excludes MyDotNetApp cluster
- `test_single_component_graph` — all nodes in one cluster (no label prop refinement for small)
- `test_empty_graph` — returns empty list
- `test_deterministic_results` — same input → same output on repeated calls
- `test_large_component_uses_label_propagation` — component > threshold triggers sub-clustering

**TestExtractionFeasibility** (~4 tests):
- `test_easy_extraction` — cluster with few external edges
- `test_hard_extraction` — cluster with many cross-boundary edges + shared DB
- `test_isolated_cluster` — zero external edges → "easy"
- `test_scoring_deterministic` — same input → same output

### 5.4 Files to create/modify

| File | Action |
|------|--------|
| `scatter/analyzers/domain_analyzer.py` | **Create** — `Cluster`, `find_clusters()`, `score_extraction_feasibility()` |
| `scatter/ai/base.py` | **Modify** — add `BOUNDARY_ASSESSMENT` to `AITaskType` |
| `test_domain.py` | **Create** — ~12 tests |

---

## Phase 6: Graph Reporters + Health Dashboard

### Goal

Output the graph analysis in multiple formats: console summary, JSON, Mermaid diagrams, and a health dashboard.

### 6.1 Graph reporter — `scatter/reports/graph_reporter.py`

All functions are **standalone free functions**.

```python
def print_graph_summary(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    cycles: List[CycleGroup],
    clusters: List[Cluster],
) -> None:
    """Print a console summary of the dependency graph analysis.

    Output sections:
    - Overview: N projects, M edges, K components
    - Top-10 most coupled projects (by coupling_score)
    - Circular dependency groups (SCCs with representative cycles)
    - Domain clusters with extraction feasibility
    - Orphan projects (zero fan-in, zero fan-out)
    """

def write_graph_json(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    cycles: List[CycleGroup],
    clusters: List[Cluster],
    output_path: Path,
) -> None:
    """Write full graph analysis to JSON file."""

def generate_mermaid(graph: DependencyGraph) -> str:
    """Generate a Mermaid flowchart diagram of the dependency graph.

    Standalone free function — not a method on DependencyGraph.

    Output:
    ```mermaid
    flowchart LR
      GalaxyWorks.Data
      GalaxyWorks.WebPortal --> GalaxyWorks.Data
      GalaxyWorks.BatchProcessor --> GalaxyWorks.Data
      GalaxyWorks.BatchProcessor --> GalaxyWorks.WebPortal
      MyDotNetApp.Consumer --> MyDotNetApp
      MyDotNetApp2.Exclude
    ```
    """
```

### 6.2 Health dashboard data — `scatter/analyzers/health_analyzer.py`

```python
@dataclass
class HealthDashboard:
    """Aggregate health metrics for a codebase."""
    total_projects: int
    total_files: int
    total_edges: int
    connected_components: int
    orphan_projects: List[str]              # zero fan-in AND zero fan-out
    circular_dependency_groups: List[CycleGroup]
    top_coupled: List[Tuple[str, float]]    # (project_name, coupling_score)
    shared_db_hotspots: List[Tuple[str, int]]   # (db_object, project_count)
    cluster_summary: List[Dict[str, Any]]   # cluster name, size, feasibility
    framework_distribution: Dict[str, int]  # framework → project count

def compute_health_dashboard(
    graph: DependencyGraph,
    metrics: Dict[str, ProjectMetrics],
    cycles: List[CycleGroup],
    clusters: List[Cluster],
    db_matrix: Optional[Dict[str, List[str]]] = None,
) -> HealthDashboard:
    """Compute aggregate health metrics from graph analysis results."""
```

### 6.3 Tests — `test_reporters.py`

**TestGraphReporter** (~5 tests):
- `test_print_summary_no_crash` — runs without error on sample data
- `test_json_output_valid` — parses as valid JSON with expected keys
- `test_mermaid_output_valid` — contains expected project names and arrows
- `test_empty_graph_summary` — handles empty graph gracefully
- `test_mermaid_with_cycles` — cycle edges rendered correctly

**TestHealthDashboard** (~4 tests):
- `test_dashboard_from_sample_projects` — correct totals
- `test_orphan_detection` — MyDotNetApp2.Exclude identified
- `test_framework_distribution` — sdk and framework counts correct
- `test_empty_codebase` — all zeros, no crash

### 6.4 Files to create/modify

| File | Action |
|------|--------|
| `scatter/reports/graph_reporter.py` | **Create** — console, JSON, Mermaid output |
| `scatter/analyzers/health_analyzer.py` | **Create** — `HealthDashboard`, `compute_health_dashboard()` |
| `test_reporters.py` | **Create** — ~9 tests |

---

## Cross-Cutting Concerns

### Exports

Update `scatter/__init__.py` to export:
- `DependencyGraph`, `ProjectNode`, `DependencyEdge` (from `core/graph.py`)
- `ProjectMetrics`, `CycleGroup`, `compute_all_metrics`, `detect_cycles` (from `analyzers/coupling_analyzer.py`)
- `build_dependency_graph` (from `analyzers/graph_builder.py`)
- `Cluster`, `find_clusters` (from `analyzers/domain_analyzer.py`)
- `HealthDashboard` (from `analyzers/health_analyzer.py`)
- `generate_mermaid` (from `reports/graph_reporter.py`)

### Backward compatibility

All existing functionality is untouched. The `--graph` mode is purely additive. Existing modes (`--branch-name`, `--target-project`, `--stored-procedure`, `--sow`) continue to work exactly as before. The graph builder reuses existing scanner functions but does not modify them.

### Performance expectations

- **Small codebases** (8 projects, like sample): Graph builds in <1 second. No caching benefit.
- **Medium codebases** (100-500 projects): Graph builds in 5-30 seconds. Caching saves time on repeated runs.
- **Large codebases** (1000+ projects): Graph builds in 1-5 minutes. Caching essential. Parallelization provides significant speedup.

### No external dependencies

All algorithms (Tarjan's SCC, connected components, label propagation clustering, metric computation) are implemented from scratch using only Python stdlib. No networkx, no python-louvain, no igraph. This keeps the dependency footprint minimal and avoids version conflicts.

### Deferred features

The following features are explicitly **deferred** to a future initiative:

- **`diff(baseline, current) -> GraphDiff`** — comparing two graphs to show added/removed nodes, edges, and metric deltas. Requires a clear use case (CI integration? branch comparison?) and a fully specified `GraphDiff` data model. Not needed for v1.
- **Graph query DSL** — a query language for ad-hoc graph traversal (e.g., "show all paths from A to B"). Useful for large codebases but premature before the basic graph is proven.
- **Incremental graph updates** — modifying an existing graph instead of rebuilding from scratch. The smart cache invalidation (checking actual .csproj/.cs changes) reduces rebuild frequency enough that full rebuilds are acceptable for v1.

---

## Verification Plan

After each phase:

```bash
# All existing tests still pass
python -m pytest --tb=short

# New tests pass
python -m pytest test_graph.py -v          # Phase 1
python -m pytest test_coupling.py -v       # Phase 2
python -m pytest test_graph_cache.py -v    # Phase 3
python -m pytest test_db_scanner.py -v     # Phase 4
python -m pytest test_domain.py -v         # Phase 5
python -m pytest test_reporters.py -v      # Phase 6

# Manual integration test (after Phase 3)
python -m scatter --graph --search-scope . -v
python -m scatter --graph --search-scope . --output-format json --output-file /tmp/graph.json
```

After all phases:

```bash
# Full suite
python -m pytest -v

# Verify graph against known dependency structure
python -m scatter --graph --search-scope . 2>&1 | grep "GalaxyWorks.Data"
# Should show: fan_in=4, fan_out=0, instability=0.0

# Verify cycle detection
python -m scatter --graph --search-scope . 2>&1 | grep -i "cycle"
# Should show: 0 circular dependency groups

# Verify clustering
python -m scatter --graph --search-scope . 2>&1 | grep -i "cluster"
# Should show: 2 clusters (GalaxyWorks, MyDotNetApp)
```

---

## File Summary

| Phase | File | Action | Lines (est.) |
|-------|------|--------|-------------|
| 1 | `scatter/core/graph.py` | Create | ~250 |
| 1 | `scatter/analyzers/graph_builder.py` | Create | ~250 |
| 1 | `scatter/scanners/project_scanner.py` | Modify | +60 |
| 1 | `test_graph.py` | Create | ~450 |
| 2 | `scatter/analyzers/coupling_analyzer.py` | Create | ~180 |
| 2 | `test_coupling.py` | Create | ~300 |
| 3 | `scatter/store/__init__.py` | Create | 1 |
| 3 | `scatter/store/graph_cache.py` | Create | ~140 |
| 3 | `scatter/__main__.py` | Modify | +50 |
| 3 | `scatter/config.py` | Modify | +40 |
| 3 | `test_graph_cache.py` | Create | ~180 |
| 4 | `scatter/scanners/db_scanner.py` | Create | ~250 |
| 4 | `scatter/analyzers/graph_builder.py` | Modify | +20 |
| 4 | `scatter/config.py` | Modify | +15 |
| 4 | `test_db_scanner.py` | Create | ~250 |
| 5 | `scatter/analyzers/domain_analyzer.py` | Create | ~180 |
| 5 | `scatter/ai/base.py` | Modify | +1 |
| 5 | `test_domain.py` | Create | ~180 |
| 6 | `scatter/reports/graph_reporter.py` | Create | ~200 |
| 6 | `scatter/analyzers/health_analyzer.py` | Create | ~100 |
| 6 | `test_reporters.py` | Create | ~120 |
| All | `scatter/__init__.py` | Modify | +15 |

**Total estimated: ~2,700 lines of production code + tests across 6 phases.**

---

## Review Findings Applied

This plan incorporates all findings from the principal engineer review:

| # | Finding | Resolution |
|---|---------|------------|
| 1 | **Edge indexing gap** — flat `List[DependencyEdge]` causes O(E) lookups | Replaced with per-node edge indexes: `_outgoing[source]` and `_incoming[target]` for O(degree) lookups |
| 2 | **Cycle detection algorithm wrong** — DFS back-edge can't find all cycles | Switched to Tarjan's SCC (O(N+E)) + BFS shortest-cycle extraction per SCC. Introduced `CycleGroup` dataclass |
| 3 | **Label propagation non-determinism** | Two-level strategy: connected components first (deterministic), label propagation only for large components with fixed iteration order + tie-breaking |
| 4 | **DB scanner false positives** | Added `_strip_cs_comments()` preprocessor, required string-literal context for SQL patterns, made sproc prefixes configurable |
| 5 | **DependencyGraph god object (SRP)** | Removed all analysis methods from graph class. `detect_cycles()`, `compute_all_metrics()`, `find_clusters()`, `generate_mermaid()` are all free functions |
| 6 | **coupling_score magic numbers** | Documented weight rationale, made weights configurable via `coupling_weights` parameter and `.scatter.yaml` |
| 7 | **`diff()` unspecified** | Deferred to future initiative. Explicitly listed in "Deferred features" section |
| 8 | **Cache invalidation too coarse** | Smart git-based: `git diff --name-only` checks actual .csproj/.cs changes, not just HEAD hash |
| 9 | **`find_project_file_on_disk` is O(N*M)** | Replaced with reverse index: build project-directory map in Step 2, assign .cs files via sorted prefix match in Step 3 |
| 10 | **Minor issues** — evidence capping, file serialization, phase parallelism | Evidence capped to 10 entries with `evidence_total` count. `ProjectNode` stores `file_count` not `files`. Phase parallelism noted in breakdown table |

---

## Recommended Execution Order

Start with **Phase 1** — the graph model and builder are the foundation everything else builds on. Phase 2 (metrics + cycles) follows immediately because it validates the graph structure. Phase 3 (persistence + CLI) makes it usable. Phases 4-6 can proceed in any order after that.

Phases 1+2 are **HIGH priority**. Phase 3 is **HIGH** for usability. Phases 4-6 are **MEDIUM**.
