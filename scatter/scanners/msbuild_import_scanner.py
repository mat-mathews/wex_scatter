"""MSBuild implicit import resolution for Directory.Build.props/.targets files.

Resolves which .props/.targets files affect each project via:
1. Implicit Directory.Build.props/targets (nearest-ancestor walk)
2. Parent chaining (GetPathOfFileAbove)
3. Explicit <Import Project="..."> in csproj files
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set

_DIRECTORY_BUILD_PROPS = "Directory.Build.props"
_DIRECTORY_BUILD_TARGETS = "Directory.Build.targets"
_DIRECTORY_BUILD_NAMES = frozenset({_DIRECTORY_BUILD_PROPS, _DIRECTORY_BUILD_TARGETS})

_SYSTEM_IMPORT_MARKERS = frozenset(
    {
        "$(MSBuildExtensionsPath)",
        "$(MSBuildToolsPath)",
        "$(MSBuildBinPath)",
        "$(VSToolsPath)",
        "$(NuGetPackageRoot)",
        "Microsoft.Common.props",
        "Microsoft.CSharp.targets",
        "Microsoft.WebApplication.targets",
    }
)

_MAX_ANCESTOR_DEPTH = 64
_MAX_CHAIN_DEPTH = 10


def build_directory_build_index(
    props_files: List[Path],
    targets_files: List[Path],
) -> tuple[Dict[Path, Path], Dict[Path, Path]]:
    """Build lookup indexes for Directory.Build.props and .targets files.

    Returns two dicts mapping directory -> file path. Only indexes files
    named exactly Directory.Build.props or Directory.Build.targets.
    Custom .props files (e.g. wex.common.props) are handled separately
    via parse_explicit_imports.
    """
    props_index = {f.parent.resolve(): f for f in props_files if f.name == _DIRECTORY_BUILD_PROPS}
    targets_index = {
        f.parent.resolve(): f for f in targets_files if f.name == _DIRECTORY_BUILD_TARGETS
    }
    return props_index, targets_index


def resolve_directory_build_imports(
    project_dir: Path,
    props_index: Dict[Path, Path],
    targets_index: Dict[Path, Path],
    search_root: Path,
) -> List[Path]:
    """Return all Directory.Build.props/.targets files that affect a project.

    Handles nearest-ancestor resolution and parent chaining.
    A file that chains (contains GetPathOfFileAbove) causes the walk to
    continue upward to find the next ancestor. A file without chaining
    terminates the walk.

    Note: the ancestor walk is bounded by search_root, not the filesystem
    root. A Directory.Build.props above search_root will not be found.
    This is deliberate — scatter only indexes within its configured scope.
    """
    result = _resolve_chain(project_dir, props_index, search_root)
    result.extend(_resolve_chain(project_dir, targets_index, search_root))
    return result


def parse_explicit_imports(csproj_path: Path, search_scope: Path) -> List[Path]:
    """Parse <Import Project="..."> elements from a csproj and resolve to local paths.

    Filters out system MSBuild imports. Resolves $(MSBuildThisFileDirectory)
    to the csproj's parent directory. Only returns paths that exist on disk
    and fall within search_scope.
    """
    try:
        tree = ET.parse(csproj_path)
        root = tree.getroot()
    except (ET.ParseError, OSError) as e:
        logging.debug(f"Could not parse {csproj_path} for imports: {e}")
        return []

    msb_ns = "{http://schemas.microsoft.com/developer/msbuild/2003}"
    imports: List[Path] = []

    for import_elem in list(root.findall(".//Import")) + list(
        root.findall(f".//{msb_ns}Import")
    ):
        project_attr = import_elem.get("Project", "")
        if not project_attr or _is_system_import(project_attr):
            continue

        resolved = project_attr.replace("\\", "/")
        resolved = resolved.replace("$(MSBuildThisFileDirectory)", str(csproj_path.parent) + "/")
        if "$(" in resolved:
            continue

        try:
            abs_path = (csproj_path.parent / resolved).resolve()
            if not abs_path.is_file():
                continue
            abs_path.relative_to(search_scope.resolve())
            if abs_path.name not in _DIRECTORY_BUILD_NAMES:
                imports.append(abs_path)
        except (ValueError, OSError):
            continue

    return imports


# --- Internal helpers ---


def _find_nearest(
    start_dir: Path,
    index: Dict[Path, Path],
    search_root: Path,
) -> Optional[Path]:
    """Walk up from start_dir to find the nearest Directory.Build file."""
    search_root_resolved = search_root.resolve()
    current = start_dir.resolve()
    for _ in range(_MAX_ANCESTOR_DEPTH):
        if current in index:
            return index[current]
        if current == search_root_resolved or current == current.parent:
            return None
        current = current.parent
    return None


def _chains_to_parent(props_path: Path) -> bool:
    """Check if a Directory.Build file chains to its parent via GetPathOfFileAbove."""
    try:
        content = props_path.read_text(encoding="utf-8", errors="ignore")
        return "GetPathOfFileAbove" in content
    except OSError:
        return False


def _resolve_chain(
    project_dir: Path,
    index: Dict[Path, Path],
    search_root: Path,
) -> List[Path]:
    """Resolve the full chain of Directory.Build files for a project directory."""
    nearest = _find_nearest(project_dir, index, search_root)
    if nearest is None:
        return []

    chain: List[Path] = []
    visited: Set[Path] = set()
    current = nearest

    for _ in range(_MAX_CHAIN_DEPTH):
        resolved = current.resolve()
        if resolved in visited:
            break
        visited.add(resolved)
        chain.append(current)

        if not _chains_to_parent(current):
            break

        parent_start = current.parent.parent
        if parent_start == current.parent:
            break
        next_file = _find_nearest(parent_start, index, search_root)
        if next_file is None:
            break
        current = next_file

    return chain


def _is_system_import(project_attr: str) -> bool:
    """Check if an <Import Project="..."> is a system/SDK import to ignore."""
    return any(marker in project_attr for marker in _SYSTEM_IMPORT_MARKERS)
