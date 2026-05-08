# Why Docker Runs Took 11 Minutes (and How We Got to 5)

**April 2026**

---

## The Problem

Scatter against the OD monolith via Docker on Windows: 11 minutes. The graph build was 307 seconds, which was already optimized from the work in [ADR_GRAPH_PERFORMANCE.md](ADR_GRAPH_PERFORMANCE.md). But solution scanning — the step *before* the graph build — took 375 seconds. Longer than the graph itself. Nobody noticed because it wasn't instrumented.

Two things were going on.

### 1. Two independent walks of the same tree

The solution scanner and the graph builder each did their own file discovery. The solution scanner used `find_files_with_pattern_parallel` (multiple overlapping `rglob` walks). The graph builder used `walk_and_collect` (single-pass `os.walk`). Both traversed 32,156 directories.

On a native filesystem, walking a directory tree twice is mildly wasteful. On Docker for Windows with WSL2, it's catastrophic. Every syscall — `stat`, `readdir`, `open` — crosses a 9P protocol bridge between the Linux VM and the Windows filesystem. The latency per call is small. The count of calls is enormous. Two walks means paying that bridge toll twice for every directory in a 60,000-directory tree.

### 2. Path.resolve() on every .sln project reference

`parse_solution_file` called `Path.resolve()` twice per solution: once on the .sln path itself, once on each project reference inside it. `resolve()` is a filesystem operation — it follows symlinks and calls `os.stat()` to confirm the path exists.

361 .sln files, average ~20 project references each = ~7,500 `resolve()` calls. On native Linux, you wouldn't notice. On 9P over WSL2, each one is a cross-bridge round trip. That added up to roughly 200 seconds of pure path resolution overhead.

---

## What We Did

### Combined discovery into one walk

Added `.sln` to the existing `walk_and_collect` call. `__main__.py` now does a single `os.walk` that collects `.sln`, `.csproj`, and `.cs` files in one pass:

```python
discovered = walk_and_collect(paths.search_scope, {".sln", ".csproj", ".cs"}, exclude_dirs)
```

The result dict feeds into both phases:
- Solution scanner gets `discovered[".sln"]` — skips its own discovery
- Graph builder gets the full dict — skips its own walk

Both components accept pre-discovered files via optional parameters and fall back to their own walks when called standalone (tests, scripts, direct CLI invocation without the shared setup). No existing caller breaks.

### Replaced resolve() with normpath

`Path.resolve()` follows symlinks and stats the filesystem. `os.path.normpath()` cleans up `.` and `..` and duplicate separators with pure string math. Zero syscalls.

The project reference paths from .sln files are used for lookup only — matching stems against the graph's project index. They don't need to be canonicalized through symlinks. `normpath` produces the same stems, so downstream matching is unaffected.

Same approach already used in `_build_project_reference_edges` for .csproj ProjectReference paths. Same risk profile: if symlinks exist in the path, normpath won't follow them. Same mitigation: the data is keyed by stem, not full path.

### Threaded discovered files through all call paths

The shared discovery dict flows through `ModeContext` so every mode handler has access:

```
__main__.py (walk_and_collect)
  → scan_solutions_data(sln_files=...)
  → build_graph_context_if_needed(discovered_files=...)
      → build_graph_context(discovered_files=...)
          → build_dependency_graph(discovered_files=...)
  → ModeContext(discovered_files=...)
      → run_graph_mode → build_dependency_graph(ctx.discovered_files)
```

---

## The Numbers

Estimated timings on the OD monolith via Docker/WSL2:

| Phase | Before | After | Savings |
|-------|--------|-------|---------|
| Solution discovery (file walk) | ~150-200s | 0s (shared walk) | ~150-200s |
| .sln parsing + resolve() | ~175-225s | ~5-10s (normpath) | ~170-215s |
| Graph file discovery | ~151s | 0s (shared walk) | ~151s |
| **Total** | **~682s (~11 min)** | **~311s (~5 min)** | **~370s** |

The graph build steps 2-6 (csproj parsing, cs mapping, file extraction, edge building, DB scanner) are unchanged.

---

## What We Didn't Do

**Parallelize .sln parsing.** After the resolve() removal, parsing 361 .sln files is string work — regex and normpath on a few KB of text each. Probably under 5 seconds. Not worth the complexity of a process pool for that.

**Cache .sln parse results.** Solution data isn't used in hot loops. It's built once at startup and never recomputed. Caching a one-shot operation adds complexity for zero benefit.

**Replace walk_and_collect with a faster walker.** `os.walk` with in-place pruning is already near-optimal for this workload. The bottleneck was never the walk itself — it was doing the walk multiple times and making unnecessary syscalls during parsing.

---

## What We Learned

**Profile the boring parts.** The graph builder was instrumented. The solution scanner wasn't. A 375-second step hiding in an uninstrumented function is worse than a 30-second step you can see in the logs. We found this by adding timing to the entire pipeline, not just the parts we expected to be slow.

**Syscalls have context-dependent costs.** `Path.resolve()` is fine on native Linux. It's a disaster on 9P over WSL2. The function doesn't change — the cost per call does. When your tool runs in Docker on developer machines, "fast on Linux" is not the same as "fast."

**One walk is a design decision, not just an optimization.** Combining file discovery into a single point in `__main__.py` creates a canonical discovery step that all downstream components share. Adding a new file extension to scan is one line in one place. Before this, adding `.sln` collection required understanding two independent discovery paths and keeping them in sync.
