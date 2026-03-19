# Incremental Graph Updates

Full graph rebuilds take 1-60 seconds depending on codebase size. A typical PR changes 5-10 files. Rebuilding the entire graph because someone renamed a variable is wasteful. The patch algorithm fixes this.

---

## The Problem

Every time Scatter runs, it needs an up-to-date dependency graph. The naive approach is: detect staleness, rebuild from scratch. But "from scratch" means re-reading thousands of .cs files, re-parsing hundreds of .csproj files, and re-building all edges. For a 500-project codebase, that is 42 seconds of work to handle a one-line change.

## The Solution

`git diff` tells us exactly which files changed. We use that to surgically patch the cached graph -- update only the projects affected by the change, leave everything else untouched.

The algorithm lives in `store/graph_patcher.py`.

---

## The Patch Flow

```
get_changed_files()
  --> classify changes (.cs vs .csproj)
  --> detect structural changes (new/deleted .csproj -> full rebuild)
  --> map changed .cs files to parent projects
  --> check thresholds (too many changes -> full rebuild)
  --> content hash early cutoff (unchanged hash -> skip)
  --> declaration early cutoff (same types -> cheap path)
  --> edge rebuild scoped to affected projects
  --> global type_usage rebuild only if declarations changed
```

### Step 1: Get Changed Files

```python
def get_changed_files(cached_git_head: str, search_scope: Path) -> Optional[List[str]]:
    # git diff --name-only <cached_head> HEAD -- *.csproj *.cs
```

Returns a list of relative paths. Returns `None` if git is unavailable or the cached commit is unreachable (e.g., after a force push), which signals the caller to fall back to a full rebuild.

### Step 2: Classify Changes

Changed files are split into two buckets:

- `.cs` files: may affect type declarations, namespace usages, sproc references
- `.csproj` files: may affect project references, namespace, framework metadata

### Step 3: Detect Structural Changes

If a `.csproj` file was **added** (exists on disk but not in graph) or **deleted** (in graph but not on disk), we bail out to a full rebuild. Structural changes can cascade in ways that incremental patching cannot safely handle -- new projects need nodes, deleted projects need edge cleanup across the entire graph.

### Step 4: Map to Affected Projects

Changed .cs files are mapped to their parent projects using the same deepest-first directory index as the full builder. Changed .csproj files directly identify their project by stem name.

### Step 5: Check Thresholds (Safety Valves)

Three conditions trigger a full rebuild instead of patching:

| Condition | Threshold | Rationale |
|-----------|-----------|-----------|
| Too many affected projects | > 50 | Patching cost approaches rebuild cost |
| Too many changed files | > 30% of total | Same -- diminishing returns on surgical updates |
| Project set hash mismatch | any | External tool (IDE, manual edit) added/removed a .csproj |

The project set hash is a SHA-256 of sorted project names, computed at save time and verified at patch time. If it does not match, something changed outside of git's view.

### Step 6: Content Hash Early Cutoff

Inspired by Bazel's content-addressable caching. Before re-extracting facts from a changed file, we compute its SHA-256 hash and compare it to the cached hash:

```python
old = file_facts.get(cs_rel)
new_facts = extract_file_facts(cs_abs, project_name, search_scope)

if old and old.content_hash and old.content_hash == new_facts.content_hash:
    # Content unchanged despite git reporting a change (whitespace, permissions)
    continue
```

Git can report a file as "changed" for reasons that do not affect analysis (file mode changes, whitespace normalization). The content hash catches these false positives.

### Step 7: Declaration Early Cutoff

Inspired by Salsa's (Rust-analyzer) incremental computation model. If a file's type declarations are unchanged, the `type_to_projects` index does not need a global rebuild:

```python
if old is None or sorted(old.types_declared) != sorted(new_facts.types_declared):
    declarations_changed = True
```

The `declarations_changed` flag controls whether we do a global type_usage edge rebuild (expensive) or a project-scoped edge rebuild (cheap). This is the single biggest performance lever in the patcher -- changing a method body triggers only project-scoped work, while adding a new class triggers a global pass.

### Step 8: Edge Rebuild

For each affected project, we:

1. Remove analysis edges (`namespace_usage`, `type_usage`, `sproc_shared`) from the project
2. Rebuild those edges from current file facts
3. If a `.csproj` changed, also remove and rebuild `project_reference` edges

```python
for project_name in affected_projects:
    graph.remove_edges_from(project_name, {"namespace_usage", "type_usage", "sproc_shared"})
    _rebuild_namespace_edges(graph, project_name, file_facts, namespace_to_project, ...)
    _rebuild_type_usage_edges(graph, project_name, file_facts, type_to_projects, ...)
    _rebuild_sproc_edges(graph, project_name, file_facts, ...)
```

### Step 9: Global Rebuild (Conditional)

If `declarations_changed` is `True`, the `type_to_projects` index has changed and every project's type_usage edges could be stale. We rebuild type_usage edges for all projects not already handled in step 8:

```python
if declarations_changed:
    type_to_projects = _build_type_to_projects(file_facts)
    for node in graph.get_all_nodes():
        if node.name not in affected_projects:
            graph.remove_edges_from(node.name, {"type_usage"})
            _rebuild_type_usage_edges(graph, node.name, file_facts, type_to_projects, ...)
```

Similarly, if a project's namespace changed, namespace_usage edges for all projects are rebuilt.

---

## Cache Format v2

The cache envelope includes two additional sections beyond the graph itself:

### file_facts

A `Dict[str, FileFacts]` keyed by relative path. Each entry captures what the patcher needs to know about a .cs file without re-reading it:

```python
@dataclass
class FileFacts:
    path: str                       # Relative to search_scope
    project: str                    # Owning project name
    types_declared: List[str]       # e.g., ["PortalDataService", "PortalConfig"]
    namespaces_used: List[str]      # e.g., ["System.Data", "GalaxyWorks.Data"]
    sprocs_referenced: List[str]    # e.g., ["sp_InsertPortalConfiguration"]
    content_hash: str               # SHA-256 of file contents
```

### project_facts

A `Dict[str, ProjectFacts]` keyed by project name:

```python
@dataclass
class ProjectFacts:
    namespace: Optional[str]        # Derived namespace
    project_references: List[str]   # Resolved project names (not include paths)
    csproj_content_hash: str        # SHA-256 of .csproj contents
```

### Other Envelope Fields

- `project_set_hash`: SHA-256 of sorted project names. Detects structural changes.
- `git_head`: Commit hash at build time. Used as the baseline for `git diff`.
- `version`: Cache format version. Currently `2`. Version `1` caches (without facts) are accepted but trigger a full rebuild to populate facts.

### v1 to v2 Migration

When a v1 cache is loaded, `file_facts` and `project_facts` will be `None`. The graph is still usable for acceleration (Phase 2), but the patcher cannot run without facts. The next save will write a v2 cache with facts.

---

## Atomic Writes

Cache writes use `tempfile.mkstemp` + `os.replace` to prevent corrupt cache files from partial writes or crashes:

```python
fd, tmp_path = tempfile.mkstemp(dir=str(cache_path.parent), suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)
    os.replace(tmp_path, str(cache_path))
except BaseException:
    os.unlink(tmp_path)
    raise
```

`os.replace` is atomic on POSIX systems. On Windows it is atomic if source and destination are on the same filesystem (which they are, since the temp file is created in the same directory).

---

## Performance

Measured on a 250-project codebase (9.5s full rebuild):

| Change Type | Patch Time | Speedup vs Full Rebuild |
|-------------|-----------|------------------------|
| 1 .cs file (usage change only) | ~10ms | 950x |
| 1 .cs file (new type added) | ~555ms | 17x |
| 10 .cs files (usage changes) | ~70ms | 136x |
| 10 .cs files (mixed) | ~315ms | 30x |
| 1 .csproj file (reference change) | ~9ms | 1,056x |
| 1 .csproj file (namespace change) | ~38ms | 250x |
| 1 declaration change | ~555ms-7,060ms | 1.3-17x |

The wide range on declaration changes reflects codebase size -- a declaration change triggers global type_usage rebuild, which is O(F) where F = total .cs files. For 500-project codebases, this approaches the cost of a full rebuild, which is why the >30% threshold exists as a safety valve.

The content hash cutoff saves the most time in practice, because git frequently reports files as "changed" that have no semantic difference (reformatting, line ending normalization, file permission changes).

---

## PatchResult

The patcher returns a `PatchResult` dataclass that tells the caller what happened:

```python
@dataclass
class PatchResult:
    graph: DependencyGraph              # The patched (or unpatched) graph
    file_facts: Dict[str, FileFacts]    # Updated facts
    project_facts: Dict[str, ProjectFacts]
    patch_applied: bool                 # True = patched, False = needs full rebuild
    files_processed: int                # Files that were re-extracted
    projects_affected: int              # Projects with edge rebuilds
    declarations_changed: bool          # Whether type_to_projects was rebuilt
    elapsed_ms: float                   # Wall clock time
```

When `patch_applied=False`, the caller should do a full rebuild and re-save. The graph in the result is still the original cached graph (not corrupted) -- the patcher shallow-copies input dicts and bails cleanly on threshold violations.
