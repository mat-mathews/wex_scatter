# Technical Debt

Tracked risks, known limitations, and deferred optimizations from the graph performance work. Each item includes context on why it was deferred and what would trigger revisiting it.

*Last reviewed: 2026-05-03. Items dated from initial graph performance work (2026-03) unless noted.*

---

## Performance

### P1: DB scanner comment-stripping cost (~30-50s estimated)

`_strip_cs_comments()` in `db_scanner.py:52-160` is a char-by-char Python state machine run on every .cs file. Even after eliminating redundant file I/O (by passing cached content), the stripping itself is ~20-30% of the DB scanner's time.

**Why deferred:** The file I/O is the bigger win. Comment stripping is CPU-bound and won't benefit from the WSL2 bridge optimization. Diminishing returns for the complexity.

**When to revisit:** If step 6 is still >60s after the content cache optimization. Options: C extension, pre-stripped content cache, or skip stripping for patterns that don't need it (sproc refs in quoted strings are unaffected by comments).

### P2: Step 5a Path.resolve() on non-WSL2 environments

The string-based path resolution (`os.path.normpath`) replaces `Path.resolve()` to avoid WSL2 filesystem overhead. This works because project stems are unique and the stem-based fallback catches edge cases.

**Risk:** If the monolith uses symlinks in project directories, `normpath` won't follow them and the primary path match will fail. The stem-based fallback covers this, but if two projects share a stem AND symlinks are involved, the wrong project could match.

**When to revisit:** If project_reference edge counts differ between `normpath` and `resolve()` approaches on the real monolith. Compare edge counts from the old and new runs.

### ~~P3: Solution scanning still does its own filesystem walk~~ — RESOLVED

Fixed. `__main__.py` now does a single `walk_and_collect` for `.sln`, `.csproj`, and `.cs`, feeding results into both solution scanning and graph building. `Path.resolve()` replaced with `os.path.normpath()` in .sln parsing. See [ADR_DOCKER_PERFORMANCE.md](ADR_DOCKER_PERFORMANCE.md).

### P4: Duplicate sproc extraction in step 4 and step 6

Step 4 (`_extract_file_data` in graph_builder.py:61) extracts sproc references via `SPROC_PATTERN`. Step 6 (DB scanner, db_scanner.py:322) extracts them again from the same files. The results are used for different purposes (graph node metadata vs. cross-project DB edges) but the extraction is identical.

**Why deferred:** The regex scan is fast — the redundant work is maybe 1-2 seconds. Not worth the coupling to pipe `project_sprocs` into the DB scanner's edge builder.

**When to revisit:** Only if we're micro-optimizing below 5-minute total builds. Low priority.

### P5: Parallelization of type_usage edge loop

The type_usage edge construction loop (graph_builder.py:311-360) is sequential over source projects. After the scope gate optimization it runs in 0.9 seconds, so parallelization was deferred.

**Why deferred:** The GIL limits real speedup for CPU-bound set operations. The scope gate reduced the workload enough that it's no longer a bottleneck.

**When to revisit:** If the monolith grows significantly (e.g., 3x more projects) and step 5c exceeds 10 seconds. Consider `ProcessPoolExecutor` with shared-memory type name set, or a C extension for the set intersection.

---

## Correctness

### C1: Scope gate misses fully-qualified type usage

The per-file scope gate (graph_builder.py:305-330) only checks types from projects whose namespaces the file imports via `using` statements. Fully-qualified type usage without a `using` (e.g., `new GalaxyWorks.Data.Foo()`) is not detected.

**Mitigation:** `full_type_scan=True` bypasses the scope gate entirely. Project-level fallback fires when a file has no namespace-matched usings.

**When to revisit:** If users report missing type_usage edges. Could add a regex scan for fully-qualified names as a secondary check.

### C2: Step 5b namespace_usage edges are zero on the monolith

The monolith run shows 0.0s for namespace_usage edges, meaning no matches. This could mean `namespace_to_project` mapping doesn't match any project namespaces (e.g., projects use `RootNamespace` values that don't match `derive_namespace()` output, or namespaces don't align with project names).

**Impact:** The scope gate fallback fires more often (falls back to project-level reachable_targets). This is correct behavior but means the scope gate provides less narrowing than ideal.

**When to revisit:** Worth investigating the namespace mapping to understand why zero edges. May reveal a bug in `derive_namespace()` or a convention mismatch in the monolith.

### C3: USING_PATTERN alias capture is a no-op, not an error

`using M = System.Math;` is correctly excluded by the USING_PATTERN regex (the `=` breaks the match). This is documented in `tests/unit/test_graph.py::TestUsingPattern::test_using_alias_excluded`.

**No action needed** — just documenting for future reference. If someone changes the regex and aliases start matching, they'll be harmless (alias names like `M` won't match any project namespace).

---

## Architecture

### A1: `find_files_with_pattern_parallel` has overlapping rglob walks

The current `find_files_with_pattern_parallel` (parallel.py:581-695) enumerates all directories with `rglob("*")`, then hands chunks to workers that each call `rglob(pattern)` recursively — causing massive overlap. Graph building no longer uses it (replaced by `walk_and_collect`), but other callers still do: `consumer_analyzer.py`, `db_scanner.py` (when called standalone), `sproc_scanner.py`, `solution_scanner.py`.

**When to revisit:** When any of these callers becomes a measured bottleneck. The fix is to either use `walk_and_collect` or replace the rglob approach with a single `os.walk` pass.

### A2: File content read three times during graph build

Even after the content cache optimization, file content flows through:
1. Step 4: `_extract_file_data()` reads and returns content
2. Step 6: DB scanner uses cached content but still strips comments (second pass over the string)

In theory, a single-pass architecture could extract everything (identifiers, types, sprocs, DB deps) in one file read with one comment strip. But this couples graph_builder and db_scanner tightly.

**When to revisit:** If total build time needs to drop below 3 minutes. Would require a unified file analysis pipeline.
