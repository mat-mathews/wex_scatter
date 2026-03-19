# Graph Engine

The dependency graph is Scatter's core data structure. Everything interesting -- coupling metrics, cycle detection, consumer lookup, domain clustering, impact analysis -- runs on top of it. This page covers the three-phase lifecycle: build, accelerate, patch.

---

## Phase 1: Build

**Single-pass O(P+F) construction** where P = number of .csproj files and F = number of .cs files.

The builder lives in `analyzers/graph_builder.py` and follows a 6-step pipeline.

### The 6-Step Pipeline

**Step 1: Discover .csproj files.** Parallel glob for `*.csproj` across the search scope. Filter out excluded paths (`*/bin/*`, `*/obj/*` by default).

**Step 2: Parse each .csproj.** Extract `ProjectReference` includes, `TargetFramework`, `OutputType`, project style (SDK vs legacy). Derive namespace from `<RootNamespace>` element or fall back to the project name.

**Step 3: Discover .cs files and build reverse directory index.** Parallel glob for `*.cs`, then map each file to its parent project. The mapping uses a directory index sorted deepest-first -- nested projects match before parent projects.

```python
# Deepest-first sorting ensures that MyApp/SubModule/SubModule.csproj
# matches files before MyApp/MyApp.csproj does.
index.sort(key=lambda x: -len(x[0].parts))
```

**Step 4: Extract per-file facts.** For each project's .cs files, read the content once and extract:
- Type declarations (via `TYPE_DECLARATION_PATTERN` regex: `class`, `struct`, `interface`, `enum`, `record`, `delegate`)
- Stored procedure references (via `SPROC_PATTERN`)
- Namespace usages (via `USING_PATTERN`)

When `capture_facts=True`, `FileFacts` are captured inline during this step to avoid a second pass over all files. This is critical for cache v2.

**Step 5: Build edges.** Three (optionally four) edge types:

| Edge Type | Weight | How It Is Detected |
|-----------|--------|--------------------|
| `project_reference` | 1.0 | `<ProjectReference>` in .csproj XML, resolved to absolute paths |
| `namespace_usage` | file count | `using TargetNamespace;` in .cs files, matched against project namespaces |
| `type_usage` | evidence count | Inverted index: tokenize .cs files, intersect with known type names |
| `sproc_shared` | shared count | Projects referencing the same stored procedures (optional, `--include-db`) |

**Step 6 (optional): DB dependency scan.** When `include_db_dependencies=True`, scan for stored procedure references across projects and add `sproc_shared` edges.

### The type_usage Optimization Story

The original implementation used a triple loop: for each source file, for each type, for each target project, check if the type name appears. That is O(F * T * S) where T = total types and S = source files. On a 100-project codebase, this took 172 seconds.

The fix was an inverted index:

```python
# Build once: type_name -> set of owning projects
type_to_projects: Dict[str, Set[str]] = defaultdict(set)
for project_name, types in project_types.items():
    for t in types:
        type_to_projects[t].add(project_name)

type_name_set = set(type_to_projects.keys())

# Per source file: tokenize once, intersect with known types
for cs_path in project_cs_files[source_project]:
    content = _strip_cs_comments(content)
    file_identifiers = set(_IDENT_PATTERN.findall(content))
    matched_types = file_identifiers & type_name_set
```

Comment stripping happens before tokenization to eliminate false positives from commented-out code. The intersection operation is O(min(|identifiers|, |type_names|)) per file.

Result: 100 projects went from 172s to 1.7s. That is a 101x improvement.

### SDK vs Framework .csproj Handling

The project scanner detects SDK-style projects (which have `<Project Sdk="Microsoft.NET.Sdk">`) versus legacy .NET Framework projects (which use `<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">`). Legacy projects require namespace-qualified XPath queries for `ProjectReference` lookups:

```python
refs = root.findall('.//msb:ProjectReference', {'msb': 'http://schemas.microsoft.com/developer/msbuild/2003'})
if not refs:
    refs = root.findall('.//ProjectReference')  # SDK-style fallback
```

### Data Structures

#### ProjectNode

```python
@dataclass
class ProjectNode:
    path: Path                           # Absolute path to .csproj
    name: str                            # Stem of .csproj (e.g., "GalaxyWorks.Data")
    namespace: Optional[str] = None      # Derived from RootNamespace or name
    framework: Optional[str] = None      # e.g., "net8.0"
    project_style: str = "sdk"           # "sdk" or "framework"
    output_type: Optional[str] = None    # "Library", "Exe", etc.
    file_count: int = 0                  # Number of .cs files
    type_declarations: List[str] = []    # Types declared in this project
    sproc_references: List[str] = []     # Stored procedures referenced
```

#### DependencyEdge

```python
@dataclass
class DependencyEdge:
    source: str                          # Source project name
    target: str                          # Target project name
    edge_type: str                       # "project_reference" | "namespace_usage" | "type_usage" | "sproc_shared"
    weight: float = 1.0                  # Strength of dependency
    evidence: Optional[List[str]] = None # Capped at 10 entries
    evidence_total: int = 0              # Total before cap
```

Evidence is capped at `MAX_EVIDENCE_ENTRIES = 10` to keep memory bounded. The `evidence_total` field preserves the true count.

#### DependencyGraph

Five internal indexes power O(1) lookups:

```python
class DependencyGraph:
    _nodes: Dict[str, ProjectNode]               # name -> node
    _outgoing: Dict[str, List[DependencyEdge]]    # name -> outgoing edges
    _incoming: Dict[str, List[DependencyEdge]]    # name -> incoming edges
    _forward: Dict[str, Set[str]]                 # name -> set of dependency names
    _reverse: Dict[str, Set[str]]                 # name -> set of consumer names
```

`_forward` and `_reverse` are adjacency sets that mirror the edge lists. They exist so `get_dependency_names()` and `get_consumer_names()` can return in O(1) without scanning edge lists. The trade-off is double bookkeeping on mutation, but edges are written once and read many times.

### Edge Type Weights

| Edge Type | Default Weight | Rationale |
|-----------|---------------|-----------|
| `project_reference` | 1.0 | Hard compile-time dependency. Break this and the build breaks. |
| `sproc_shared` | 0.8 | Shared mutable state in the database. Nearly as hard as a project ref. |
| `namespace_usage` | 0.5 | Soft signal. May indicate real coupling, may just be a convenience import. |
| `type_usage` | 0.3 | Softest. Could be a single enum reference or a deep integration. |

These weights are configurable via `graph.coupling_weights` in `.scatter.yaml`.

---

## Phase 2: Accelerate

Once the graph exists (built or loaded from cache), consumer detection can bypass the filesystem entirely for stages 1-2.

### The Acceleration

The consumer detection pipeline has 5 stages. Stages 1 (discover .csproj files) and 2 (filter by ProjectReference) are the expensive ones on large codebases -- they require globbing and XML parsing across the entire search scope.

With a graph, both stages collapse to a single call:

```python
edges = graph.get_edges_to(target_name)
# Filter to project_reference edges only
direct_consumers = {
    node.path: {'consumer_name': edge.source, 'relevant_files': []}
    for edge in edges if edge.edge_type == "project_reference"
}
```

**Filesystem path:** O(P + F) -- glob for .csproj files, parse XML, resolve paths.

**Graph path:** O(in-degree) -- dictionary lookup plus edge list scan.

For a 250-project codebase, that is the difference between scanning 250 XML files and reading a list in memory.

Stages 3-5 (namespace, class, method filtering) still run on the candidate set regardless of source. They need to read actual .cs file contents, which the graph does not cache.

### Transparency

The consumer pipeline reports where each stage got its data:

```
Filter: 250[graph] -> 12 project refs[graph] -> 8 namespace -> 4 class match
```

The `[graph]` annotation in the arrow chain comes from `FilterStage.source = "graph"`. If the target is not in the graph (stale cache, new project), the pipeline falls back to filesystem transparently. No caller code changes.

---

## Phase 3: Patch

When the graph cache exists and only a few files changed, Scatter patches the graph instead of rebuilding it. Full details are in [Incremental Graph Updates](incremental-updates.md). The short version:

1. `git diff` identifies changed .cs and .csproj files since cached `git_head`
2. Changed files are mapped to affected projects
3. Safety valves check thresholds (>50 projects or >30% files changed triggers full rebuild)
4. Content hash early cutoff skips unchanged files
5. Edges are surgically rebuilt for affected projects only
6. If type declarations changed, global type_usage rebuild is triggered

Typical patch time: 10-315ms for 1-10 files. Full rebuild: 1-60 seconds.

---

## Query API

| Method | Complexity | Description |
|--------|------------|-------------|
| `get_node(name)` | O(1) | Look up a project by name |
| `get_all_nodes()` | O(N) | List all projects |
| `get_consumers(name)` | O(in-degree) | Direct consumers of a project |
| `get_dependencies(name)` | O(out-degree) | Direct dependencies of a project |
| `get_consumer_names(name)` | O(1) set copy | Consumer names as a set |
| `get_dependency_names(name)` | O(1) set copy | Dependency names as a set |
| `get_edges_from(name)` | O(out-degree) | Outgoing edges with full metadata |
| `get_edges_to(name)` | O(in-degree) | Incoming edges with full metadata |
| `get_edges_for(name)` | O(degree) | All edges (both directions) |
| `get_edges_between(a, b)` | O(degree) | Edges between two specific nodes |
| `get_transitive_consumers(name, max_depth)` | O(V+E) | BFS consumers up to N hops |
| `get_transitive_dependencies(name, max_depth)` | O(V+E) | BFS dependencies up to N hops |
| `connected_components` (property) | O(V+E) | Connected components (undirected BFS) |
| `remove_edges_from(source, edge_types)` | O(degree) | Remove outgoing edges, filtered |
| `remove_edges_to(target, edge_types)` | O(degree) | Remove incoming edges, filtered |

All traversal methods (`get_transitive_*`) use BFS with a `max_depth` parameter (default 3) and a visited set to handle cycles.

---

## Serialization

`to_dict()` and `from_dict()` provide lossless roundtrip serialization to JSON-compatible dicts.

```python
# Save
data = graph.to_dict()
json.dump(data, f)

# Load
data = json.load(f)
graph = DependencyGraph.from_dict(data)
```

`Path` objects are serialized as strings and reconstructed on load. All other fields are native JSON types.

The cache envelope (in `graph_cache.py`) wraps the graph dict with metadata:

```json
{
    "version": 2,
    "created_at": "2026-03-15T14:30:00+00:00",
    "search_scope": "/abs/path/to/repo",
    "git_head": "abc123...",
    "node_count": 47,
    "edge_count": 182,
    "graph": { ... },
    "file_facts": { ... },
    "project_facts": { ... },
    "project_set_hash": "sha256..."
}
```

---

## Performance Data

Build times measured on representative .NET codebases (sequential mode, M-series Mac):

| Codebase Size | .csproj Count | .cs File Count | Build Time | Notes |
|---------------|--------------|----------------|------------|-------|
| Small | ~100 | ~2,000 | ~1.1s | Dominated by file I/O |
| Medium | ~250 | ~8,000 | ~9.5s | type_usage edges are the bottleneck |
| Large | ~500 | ~20,000 | ~42.8s | Scales roughly linearly with file count |

With `capture_facts=True`, add roughly 10-15% overhead for inline fact extraction. This cost is paid once -- subsequent runs use incremental patching.
