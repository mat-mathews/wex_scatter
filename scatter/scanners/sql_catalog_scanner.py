"""SQL catalog scanner — discovers stored procedure definitions in .sql files.

Scans .sql files for CREATE/ALTER PROCEDURE statements to build a ground-truth
catalog of sproc definitions in the repo. Also scans C# migration files for
embedded CREATE PROCEDURE statements in migrationBuilder.Sql() calls.

This is the foundation for sproc inventory: cross-referencing these definitions
against the C# references found by db_scanner tells you which sprocs are defined
but unreferenced (dead code) and which are referenced but undefined (external DB
or missing .sql).

SOW signal analysis measured 50-60% blast radius coverage without sproc inventory,
75-85% with it. This scanner is the highest-leverage accuracy improvement.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from scatter.scanners._helpers import find_owning_project
from scatter.scanners.db_scanner import DbDependency

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 1_048_576  # 1 MB — matches rdl_scanner.py

# Matches CREATE PROCEDURE, ALTER PROCEDURE, CREATE OR ALTER PROCEDURE
# with optional schema prefix and bracket syntax.
# Group 1: schema (e.g. "dbo." or "[dbo].") — may be None
# Group 2: procedure name (e.g. "sp_Foo" or "[sp_Foo]")
_CREATE_PROC_PATTERN = re.compile(
    r"(?:CREATE|ALTER)\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+"
    r"(\[?[a-zA-Z_]\w*\]?\s*\.)?\s*(\[?[a-zA-Z_]\w*\]?)",
    re.IGNORECASE,
)


def normalize_sproc_name(raw_name: str) -> str:
    """Normalize a sproc name: strip brackets, lowercase schema, preserve name.

    ``dbo.sp_Foo`` → ``dbo.sp_Foo``
    ``[dbo].[sp_Foo]`` → ``dbo.sp_Foo``
    ``DBO.sp_Foo`` → ``dbo.sp_Foo``
    ``sp_Foo`` → ``sp_Foo`` (no schema)
    ``[dbo].[sp_Foo]`` and ``dbo.sp_Foo`` normalize to the same string.

    Schema is lowercased because SQL Server treats schema names as
    case-insensitive. Procedure name case is preserved because some
    teams use casing as a convention signal.
    """
    name = raw_name.strip().replace("[", "").replace("]", "")
    # Strip whitespace that regex capture may leave around the dot
    name = re.sub(r"\s*\.\s*", ".", name)
    parts = name.split(".", 1)
    if len(parts) == 2:
        schema, proc = parts
        return f"{schema.lower().strip()}.{proc.strip()}"
    return name.strip()


def scan_sql_catalog(
    sql_files: List[Path],
    project_dir_index: Dict[Path, str],
    search_scope: Path,
) -> List[DbDependency]:
    """Scan .sql files for CREATE/ALTER PROCEDURE definitions.

    Builds the ground-truth catalog of sproc definitions in the repo.
    Each definition becomes a DbDependency with detection_method="sql_catalog".

    Skips files larger than 1 MB. Handles encoding errors gracefully.
    Uses find_owning_project to map each .sql file to its parent .csproj.

    Returns:
        List of DbDependency, one per procedure definition found.
    """
    if not sql_files:
        return []

    results: List[DbDependency] = []
    skipped = 0
    matched = 0

    for sql_path in sql_files:
        try:
            file_size = sql_path.stat().st_size
        except OSError:
            continue

        if file_size > _MAX_FILE_SIZE:
            logger.warning(f"Skipping oversized .sql file ({file_size:,} bytes): {sql_path.name}")
            skipped += 1
            continue

        project_name = find_owning_project(sql_path, project_dir_index)
        if not project_name:
            continue

        try:
            content = sql_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Could not read {sql_path.name}: {e}")
            continue

        for match in _CREATE_PROC_PATTERN.finditer(content):
            schema_part = match.group(1) or ""
            name_part = match.group(2)
            if not name_part:
                continue

            raw_name = f"{schema_part}{name_part}".strip()
            normalized = normalize_sproc_name(raw_name)
            line_number = content[: match.start()].count("\n") + 1

            results.append(
                DbDependency(
                    db_object_name=normalized,
                    db_object_type="sproc",
                    source_file=sql_path,
                    source_project=project_name,
                    detection_method="sql_catalog",
                    line_number=line_number,
                )
            )
            matched += 1

    logger.info(
        f"SQL catalog scanner: {matched} procedure definition(s) found "
        f"in {len(sql_files)} .sql file(s) ({skipped} skipped for size)."
    )
    return results


def scan_ef_migrations(
    cs_files: List[Path],
    project_cs_map: Dict[str, List[Path]],
    content_by_path: Optional[Dict[Path, str]] = None,
) -> List[DbDependency]:
    """Scan C# migration files for embedded CREATE/ALTER PROCEDURE definitions.

    Identifies migration files via path heuristic: filename contains "Migration"
    or file lives under a ``Migrations/`` directory. Strips C# comments before
    regex matching to avoid false positives from commented-out migrations.

    Uses content_by_path cache when available (no re-reading from disk).

    Note: C# comment stripping handles ``//`` and ``/* */``. SQL ``--`` comments
    inside string literals are not stripped — they're part of the SQL being
    defined, not C# code structure.

    Returns:
        List of DbDependency with detection_method="ef_migration".
    """
    from scatter.scanners.db_scanner import _strip_cs_comments

    results: List[DbDependency] = []

    # Build reverse map: file path -> project name
    # TODO: if called in a hot loop, consider pre-inverting outside this function.
    file_to_project: Dict[Path, str] = {}
    for proj, files in project_cs_map.items():
        for f in files:
            file_to_project[f] = proj

    for cs_path in cs_files:
        # Filter to migration files only
        path_str = str(cs_path).replace("\\", "/")
        name = cs_path.name
        if "/Migrations/" not in path_str and "/migrations/" not in path_str:
            if "Migration" not in name:
                continue

        project_name = file_to_project.get(cs_path)
        if not project_name:
            logger.debug(f"Migration file {cs_path.name} has no owning project — skipping.")
            continue

        # Read content from cache or disk
        if content_by_path and cs_path in content_by_path:
            content = content_by_path[cs_path]
        else:
            try:
                content = cs_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"Could not read migration file {cs_path.name}: {e}")
                continue

        if not content.strip():
            continue

        # Strip C# comments before scanning for CREATE PROCEDURE in strings
        stripped = _strip_cs_comments(content)

        for match in _CREATE_PROC_PATTERN.finditer(stripped):
            schema_part = match.group(1) or ""
            name_part = match.group(2)
            if not name_part:
                continue

            raw_name = f"{schema_part}{name_part}".strip()
            normalized = normalize_sproc_name(raw_name)
            line_number = stripped[: match.start()].count("\n") + 1

            results.append(
                DbDependency(
                    db_object_name=normalized,
                    db_object_type="sproc",
                    source_file=cs_path,
                    source_project=project_name,
                    detection_method="ef_migration",
                    line_number=line_number,
                )
            )

    if results:
        logger.info(
            f"EF migration scanner: {len(results)} procedure definition(s) "
            f"found in migration files."
        )
    return results
