# Initiative 9 Phase 1: Parse Solutions Properly — Implementation Plan

**Branch:** feature/solution-aware-graph
**Estimated effort:** 0.5 day
**Depends on:** Nothing (all prerequisites shipped)
**Blocks:** Init 9 Phases 2-5, Init 11 (focused SOW index)
**Team review:** 2026-03-20 (Priya, Tomás, Anya, Jake, Sam, Kai, Fatima)

---

## Problem

`v1_bridge.find_solutions_for_project()` finds solutions by substring-matching
the `.csproj` filename against the raw text of every `.sln` file. This has two
problems:

1. **False positives**: A project named `Auth.Core.csproj` matches a solution
   containing only `MyAuth.Core.csproj` (substring hit on `Auth.Core.csproj`).

2. **No structured data**: We get back a list of `.sln` paths, not parsed project
   entries. We can't ask "what projects are in this solution?" or build a reverse
   index without re-reading every file.

## Solution

Replace text search with a proper `.sln` parser that extracts project entries
structurally, and build a reverse index for O(1) lookups.

---

## .sln Format Reference

The `.sln` format has `Project(...)` lines with this structure:

```
Project("{TYPE-GUID}") = "ProjectName", "relative\path\to\Project.csproj", "{PROJECT-GUID}"
EndProject
```

Key observations from the real `GalaxyWorks.sln` and synthetic generator:
- Type GUID `{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}` = C# project
- Type GUID `{9A19103F-16F7-4668-BE54-9A1E7A4F7556}` = SDK-style C# project
- Type GUID `{2150E333-...}` = Solution Folder (skip)
- Various other GUIDs for VB.NET, F#, Docker Compose, etc. (skip — scatter only
  analyzes C# projects)
- Paths use backslashes (Windows convention) but may have forward slashes
- Project name and .csproj filename may differ (e.g., name="MyGalaryConsumerApp"
  but path="MyGalaxyConsumerApp\MyGalaryConsumerApp.csproj")
- Files may start with a UTF-8 BOM (`\xef\xbb\xbf`) when created by Visual Studio

---

## Deliverables

### 1. Create `scatter/scanners/solution_scanner.py`

```python
@dataclass
class SolutionInfo:
    """Parsed metadata from a .sln file."""
    path: Path                    # absolute path to the .sln file
    name: str                     # stem (e.g., "GalaxyWorks" from "GalaxyWorks.sln")
    project_entries: List[str]    # project names from Project(...) lines
    project_paths: List[Path]    # resolved absolute paths to .csproj files
```

`project_paths` are resolved against the `.sln` parent directory during parsing
(Priya). Backslashes normalized to forward slashes before resolution. Downstream
code never reconstructs paths from strings.

**Functions:**

```python
# Whitelist C# project type GUIDs (Jake — positive match, not blacklist):
#   FAE04EC0-301F-11D3-BF4B-00C04F79EFBC  (classic C# project)
#   9A19103F-16F7-4668-BE54-9A1E7A4F7556  (SDK-style C# project)
# All other type GUIDs (Solution Folders, VB.NET, F#, Docker, etc.) are skipped.
# Scatter only analyzes .cs files, so non-C# projects are correctly excluded.
_CS_PROJECT_GUIDS = {"FAE04EC0-301F-11D3-BF4B-00C04F79EFBC",
                     "9A19103F-16F7-4668-BE54-9A1E7A4F7556"}

_PROJECT_LINE_RE = re.compile(
    r'^Project\("\{([^}]+)\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)",\s*"[^"]+"',
    re.MULTILINE,
)

def parse_solution_file(sln_path: Path) -> SolutionInfo:
    """Parse a .sln file and extract C# project references.

    Reads the file (UTF-8 with BOM tolerance), applies regex to extract
    Project(...) lines, filters to C# type GUIDs only, resolves .csproj
    paths against the .sln parent directory.

    Distinguishes empty-but-valid solutions (has .sln header, zero projects)
    from unrecognized formats (no header — logs warning).

    Returns SolutionInfo with empty lists on read failure (logs warning).
    Deduplicates project entries by path (logs warning on duplicates).
    """

def scan_solutions(search_scope: Path) -> List[SolutionInfo]:
    """Discover and parse all .sln files in the search scope.

    Uses find_files_with_pattern_parallel('*.sln') for discovery,
    then parse_solution_file() on each.
    Sorted by name for deterministic output.
    """

def build_project_to_solutions(
    solutions: List[SolutionInfo],
) -> Dict[str, List[SolutionInfo]]:
    """Build reverse index: project_name -> list of SolutionInfo objects.

    Keyed by .csproj filename stem (e.g., "GalaxyWorks.Data" from the
    resolved path). This matches how ProjectNode.name works throughout
    scatter.

    Logs a warning on stem collision (two different .csproj files with
    the same stem in different directories). Both are indexed — the
    collision is informational, not an error (Kai, Priya).

    Returns SolutionInfo objects (not just names) so callers can access
    .path, .name, or any other field without a second lookup (Sam, Tomás).
    """
```

### 2. Migrate `v1_bridge.find_solutions_for_project()`

Add an optional `solution_index` parameter:

```python
def find_solutions_for_project(
    csproj_path: Path,
    solution_cache: List[Path],                              # old API (backward compat)
    solution_index: Optional[Dict[str, List[SolutionInfo]]] = None,  # new API
) -> List[Path]:
```

- When `solution_index` is provided: O(1) dict lookup by project stem,
  return `[si.path for si in matches]`
- When only `solution_cache` is provided: existing text-search fallback
- Return type stays `List[Path]` for backward compatibility in this phase
  (Phase 2 will add richer return types)

### 3. Tests: `test_solution_scanner.py`

Structural tests use fixture strings, not the real `GalaxyWorks.sln` file (Anya).
One integration test uses the real file.

| Test | What it validates |
|------|-------------------|
| **Parsing** | |
| `test_parse_csharp_projects` | Fixture with 3 C# projects, all extracted correctly |
| `test_parse_sdk_style_guid` | SDK-style GUID `{9A19103F-...}` projects included |
| `test_parse_skips_solution_folders` | Solution Folder GUID `{2150E333-...}` excluded |
| `test_parse_skips_non_csharp` | VB.NET, F#, Docker GUIDs excluded |
| `test_parse_backslash_paths_resolved` | Backslash paths normalized and resolved to absolute |
| `test_parse_forward_slash_paths_resolved` | Forward slash paths resolved to absolute |
| `test_parse_with_bom` | UTF-8 BOM prefix doesn't break parsing |
| `test_parse_deduplicates` | Duplicate project entries collapsed, warning logged |
| `test_parse_empty_valid_sln` | Has .sln header but zero projects — empty lists, no warning |
| `test_parse_unrecognized_format` | No .sln header — empty lists, warning logged |
| `test_parse_malformed_sln` | Garbage content — no crash, warning logged |
| `test_parse_unreadable_file` | OSError on read — empty SolutionInfo, warning logged |
| **Scanning** | |
| `test_scan_real_repo` | scan_solutions() finds GalaxyWorks.sln, 10 C# projects |
| `test_scan_sorted` | Results sorted by name |
| `test_scan_empty_dir` | Empty directory returns empty list |
| **Reverse index** | |
| `test_reverse_index_basic` | Correct project -> SolutionInfo mapping |
| `test_reverse_index_multi_solution` | Project in 2+ solutions listed in both |
| `test_reverse_index_stem_collision` | Two .csproj with same stem — both indexed, warning logged |
| **Migration** | |
| `test_migration_with_index` | find_solutions_for_project() uses index, returns List[Path] |
| `test_migration_fallback` | find_solutions_for_project() falls back to text search |
| `test_no_false_positive_substring` | "Auth.Core" does NOT match "MyAuth.Core" solution entry |

---

## Files Changed

| File | Change |
|------|--------|
| **NEW** `scatter/scanners/solution_scanner.py` | SolutionInfo, parser, scanner, reverse index |
| `scatter/compat/v1_bridge.py` | Add `solution_index` param to `find_solutions_for_project()` |
| `scatter/__init__.py` | Export new module |
| **NEW** `test_solution_scanner.py` | ~21 tests |

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| Whitelist C# GUIDs, not blacklist non-project GUIDs | Safer — new non-C# type GUIDs won't false-match. Scatter only analyzes .cs files. | Jake |
| `project_paths` stores resolved `Path` objects, not raw strings | Downstream code shouldn't reconstruct paths. Normalize once at parse time. | Priya, Tomás |
| Reverse index maps to `List[SolutionInfo]`, not `List[str]` | Callers need `.path` for v1_bridge compat and `.name` for display. One lookup, not two. | Sam, Tomás |
| Reverse index keyed by csproj stem (matches `ProjectNode.name`) | Consistent with existing conventions. Log warning on stem collision. | Kai, Priya |
| Deduplicate project entries in parse | Bad `.sln` merges can produce duplicates. Dedupe by path, log warning. | Anya |
| Distinguish empty-valid vs unrecognized format | Zero projects with .sln header = valid. Zero projects without header = suspect. | Fatima |
| Fixture strings for structural tests | Decouples tests from repo state. One integration test uses real file. | Anya |

---

## What This Does NOT Change (yet)

- `__main__.py` / `cli.py` still use the old `solution_file_cache: List[Path]` flow.
  Phase 2 will wire `scan_solutions()` into startup and populate `ProjectNode.solutions`.
- `ProjectNode` has no `solutions` field yet. That's Phase 2.
- No new CLI flags. The parser is internal plumbing.
- The graph builder does not call `scan_solutions()` yet. Phase 2.

---

## Risk

**Minimal.** This is additive — new module, new tests, one backward-compatible
parameter addition. The old text-search path continues to work unchanged until
callers are migrated in Phase 2.

The GUID whitelist approach means we'll miss non-C# projects, which is correct
behavior since scatter only analyzes `.cs` files. If this changes in the future,
add the relevant GUIDs to `_CS_PROJECT_GUIDS`.
