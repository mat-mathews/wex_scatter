"""Shared helpers for scanner modules."""

from pathlib import Path
from typing import Dict, Optional


def find_owning_project(
    file_path: Path,
    project_dir_index: Dict[Path, str],
) -> Optional[str]:
    """Walk up from a file to find the nearest project directory."""
    current = file_path.parent
    while True:
        if current in project_dir_index:
            return project_dir_index[current]
        parent = current.parent
        if parent == current:
            return None
        current = parent
