"""Parse .sln solution files and build project-to-solution indexes."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from scatter.core.parallel import find_files_with_pattern_parallel

# C# project type GUIDs — whitelist, not blacklist.
# Only these produce .cs files that scatter can analyze.
_CS_PROJECT_GUIDS = {
    "FAE04EC0-301F-11D3-BF4B-00C04F79EFBC",  # Classic C# project
    "9A19103F-16F7-4668-BE54-9A1E7A4F7556",  # SDK-style C# project
}

# Captures: (type_guid, project_name, relative_path)
_PROJECT_LINE_RE = re.compile(
    r'^Project\("\{([^}]+)\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)",\s*"[^"]+"',
    re.MULTILINE,
)

# Minimum header to distinguish a real .sln from garbage content
_SLN_HEADER = "Microsoft Visual Studio Solution File"


@dataclass
class SolutionInfo:
    """Parsed metadata from a .sln file."""

    path: Path
    name: str
    project_entries: List[str] = field(default_factory=list)
    project_paths: List[Path] = field(default_factory=list)


def parse_solution_file(sln_path: Path) -> SolutionInfo:
    """Parse a .sln file and extract C# project references.

    Reads the file (UTF-8 with BOM tolerance), applies regex to extract
    Project(...) lines, filters to C# type GUIDs only, resolves .csproj
    paths against the .sln parent directory using string-based normpath
    (no filesystem stat calls).

    Distinguishes empty-but-valid solutions (has .sln header, zero projects)
    from unrecognized formats (no header — logs warning).

    Returns SolutionInfo with empty lists on read failure (logs warning).
    Deduplicates project entries by resolved path (logs warning on duplicates).
    """
    import os as _os

    sln_norm = Path(_os.path.normpath(str(sln_path)))
    info = SolutionInfo(path=sln_norm, name=sln_norm.stem)

    try:
        content = sln_norm.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError as e:
        logging.warning(f"Could not read solution file {info.name}: {e}")
        return info

    if _SLN_HEADER not in content:
        logging.warning(
            f"{info.name}: does not appear to be a valid solution file "
            f"(missing '{_SLN_HEADER}' header)"
        )
        return info

    sln_dir = str(sln_norm.parent)
    seen_paths: set = set()

    for match in _PROJECT_LINE_RE.finditer(content):
        type_guid, project_name, raw_path = match.groups()

        if type_guid.upper() not in _CS_PROJECT_GUIDS:
            continue

        # Normalize Windows backslashes, then resolve via string math
        normalized = raw_path.replace("\\", "/")
        resolved_str = _os.path.normpath(_os.path.join(sln_dir, normalized))

        if resolved_str in seen_paths:
            logging.warning(f"{info.name}: duplicate project entry '{project_name}' — skipping")
            continue
        seen_paths.add(resolved_str)

        info.project_entries.append(project_name)
        info.project_paths.append(Path(resolved_str))

    return info


def scan_solutions(
    search_scope: Path,
    sln_files: Optional[List[Path]] = None,
) -> List[SolutionInfo]:
    """Discover and parse all .sln files in the search scope.

    When *sln_files* is provided (pre-discovered by the top-level walk),
    skips its own file discovery pass. Sorted by name for deterministic output.
    """
    if sln_files is None:
        sln_files = find_files_with_pattern_parallel(search_scope, "*.sln")
    solutions = [parse_solution_file(p) for p in sln_files]
    solutions.sort(key=lambda s: s.name)
    return solutions


def build_project_to_solutions(
    solutions: List[SolutionInfo],
) -> Dict[str, List[SolutionInfo]]:
    """Build reverse index: project_name -> list of SolutionInfo objects.

    Keyed by .csproj filename stem (matches ProjectNode.name convention).
    Logs a warning on stem collision (two different .csproj paths with the
    same stem).
    """
    index: Dict[str, List[SolutionInfo]] = {}
    # Track which resolved paths map to each stem for collision detection
    stem_to_paths: Dict[str, set] = {}

    for sol in solutions:
        for resolved_path in sol.project_paths:
            stem = resolved_path.stem
            index.setdefault(stem, []).append(sol)

            paths_for_stem = stem_to_paths.setdefault(stem, set())
            paths_for_stem.add(resolved_path)

    # Log collisions
    for stem, paths in stem_to_paths.items():
        if len(paths) > 1:
            path_strs = ", ".join(str(p) for p in sorted(paths))
            logging.warning(
                f"Solution index stem collision: '{stem}' maps to {len(paths)} "
                f"different .csproj files: {path_strs}"
            )

    return index
