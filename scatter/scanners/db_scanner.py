"""Enhanced database dependency detection in C# source files.

Detects:
1. Stored procedure references in string literals (configurable prefixes)
2. EF DbSet<T> declarations → table/model dependencies
3. DbContext subclasses
4. Direct SQL (SELECT/INSERT/UPDATE/DELETE) in string literals
5. Connection strings (Data Source, Server, Database patterns)

All detection runs against comment-stripped source to eliminate false positives
from commented-out code and documentation.
"""
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from scatter.core.graph import DependencyEdge, DependencyGraph
from scatter.core.models import DEFAULT_CHUNK_SIZE, DEFAULT_MAX_WORKERS
from scatter.core.parallel import find_files_with_pattern_parallel

DEFAULT_SPROC_PREFIXES: List[str] = ["sp_", "usp_"]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DbDependency:
    """A database dependency found in source code."""

    db_object_name: str  # sproc name, table name, model name, etc.
    db_object_type: str  # "sproc", "ef_model", "ef_context", "sql_table", "connection_string"
    source_file: Path  # .cs file where found
    source_project: str  # parent .csproj name
    detection_method: str  # "string_literal", "ef_dbset", "ef_dbcontext", "sql_text", "connection_string"
    containing_class: Optional[str] = None
    line_number: Optional[int] = None


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------

def _strip_cs_comments(content: str) -> str:
    """Remove C# single-line and multi-line comments, preserving string literals.

    Uses a state machine approach:
    - Inside a string literal (double-quoted), comment markers are ignored.
    - Handles verbatim strings (@"...") where "" is an escaped quote.
    - // strips to end of line.
    - /* ... */ strips the block.

    Limitations:
    - C# interpolated strings ($"...{expr}...") are treated as regular strings.
      Nested quotes inside interpolation expressions (e.g. $"{dict["key"]}")
      may cause early string termination in the parser.
    - C# 11 raw string literals (triple-quote \"\"\") are not handled.
    - These limitations are unlikely to cause false positives in practice since
      DB references rarely appear in such contexts.
    """
    result: List[str] = []
    i = 0
    n = len(content)

    while i < n:
        c = content[i]

        # Verbatim string: @"..."
        if c == '@' and i + 1 < n and content[i + 1] == '"':
            result.append(c)
            result.append(content[i + 1])
            i += 2
            while i < n:
                if content[i] == '"':
                    result.append('"')
                    i += 1
                    # "" is escaped quote inside verbatim string
                    if i < n and content[i] == '"':
                        result.append('"')
                        i += 1
                    else:
                        break
                else:
                    result.append(content[i])
                    i += 1
            continue

        # Regular string literal: "..."
        if c == '"':
            result.append(c)
            i += 1
            while i < n:
                if content[i] == '\\':
                    result.append(content[i])
                    i += 1
                    if i < n:
                        result.append(content[i])
                        i += 1
                elif content[i] == '"':
                    result.append('"')
                    i += 1
                    break
                else:
                    result.append(content[i])
                    i += 1
            continue

        # Character literal: '...'
        if c == "'":
            result.append(c)
            i += 1
            while i < n:
                if content[i] == '\\':
                    result.append(content[i])
                    i += 1
                    if i < n:
                        result.append(content[i])
                        i += 1
                elif content[i] == "'":
                    result.append("'")
                    i += 1
                    break
                else:
                    result.append(content[i])
                    i += 1
            continue

        # Single-line comment: //
        if c == '/' and i + 1 < n and content[i + 1] == '/':
            # Skip to end of line, preserve newline
            i += 2
            while i < n and content[i] != '\n':
                i += 1
            continue

        # Multi-line comment: /* ... */
        if c == '/' and i + 1 < n and content[i + 1] == '*':
            i += 2
            while i < n:
                if content[i] == '*' and i + 1 < n and content[i + 1] == '/':
                    i += 2
                    break
                # Preserve newlines to keep line numbering correct
                if content[i] == '\n':
                    result.append('\n')
                i += 1
            continue

        result.append(c)
        i += 1

    return "".join(result)


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

def _build_sproc_pattern(prefixes: List[str]) -> re.Pattern:
    """Build regex for stored procedure references in string literals."""
    escaped = "|".join(re.escape(p) for p in prefixes)
    # Match sproc names inside quotes, optionally with schema prefix (e.g. dbo.)
    return re.compile(
        rf"""["'](?:[a-zA-Z_][a-zA-Z0-9_]*\.)?(?:{escaped})\w+["']""",
        re.IGNORECASE,
    )


# EF DbSet<ModelName> pattern
_DBSET_PATTERN = re.compile(r"DbSet<(\w+)>")

# DbContext subclass pattern.
# Matches: class Foo : DbContext, class Foo : BaseClass, DbContext
# Does NOT match generic base types before DbContext (e.g. Base<T>, DbContext)
# since \w+ doesn't cover angle brackets. Covers the common case.
_DBCONTEXT_PATTERN = re.compile(r"class\s+(\w+)\s*:\s*(?:\w+\s*,\s*)*DbContext\b")

# Direct SQL in string literals — SELECT/INSERT/UPDATE/DELETE with FROM/INTO/SET
_SQL_PATTERN = re.compile(
    r"""["'][ \t]*(?:SELECT\s+.*?FROM|INSERT\s+.*?INTO|UPDATE\s+|DELETE\s+.*?FROM)\s+[\["]?(\w+)[\]"]?""",
    re.IGNORECASE,
)

# Connection string patterns in string literals
_CONN_STRING_PATTERN = re.compile(
    r"""["'][^"']*(?:Data\s+Source|Server|Database)\s*=\s*([^;'"]+)""",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------

class _FileIndex:
    """Precomputed lookup tables for a file's line offsets and class positions.

    Built once per file, then queried O(log N) per match via bisect.
    """

    __slots__ = ("_line_offsets", "_class_positions")

    def __init__(self, content: str) -> None:
        # Build line offset table: _line_offsets[i] = char offset of line i+1
        import bisect
        self._line_offsets: List[int] = [0]
        for i, c in enumerate(content):
            if c == '\n':
                self._line_offsets.append(i + 1)

        # Build class position table: [(char_offset, class_name), ...] sorted
        self._class_positions: List[Tuple[int, str]] = [
            (m.start(), m.group(1))
            for m in re.finditer(r'\b(?:class|struct|interface|enum|record)\s+(\w+)', content)
        ]

    def line_number(self, offset: int) -> int:
        """Convert a character offset to a 1-based line number. O(log N)."""
        import bisect
        return bisect.bisect_right(self._line_offsets, offset)

    def enclosing_class(self, offset: int) -> Optional[str]:
        """Find the nearest class declaration before offset. O(log N)."""
        import bisect
        if not self._class_positions:
            return None
        # Find rightmost class declaration with start <= offset
        idx = bisect.bisect_right(
            self._class_positions, (offset,), key=lambda x: (x[0],)
        ) - 1
        if idx >= 0:
            return self._class_positions[idx][1]
        return None


def scan_db_dependencies(
    search_scope: Path,
    project_cs_map: Optional[Dict[str, List[Path]]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    exclude_patterns: Optional[List[str]] = None,
    sproc_prefixes: Optional[List[str]] = None,
) -> List[DbDependency]:
    """Scan all .cs files for database dependencies.

    If project_cs_map is provided (from graph_builder), uses it directly.
    Otherwise discovers .cs files and maps them to projects.

    Args:
        search_scope: Root directory to scan.
        project_cs_map: Pre-built {project_name: [cs_paths]} map.
        sproc_prefixes: Custom stored procedure prefixes (default: sp_, usp_).
        exclude_patterns: Glob patterns to exclude.

    Returns:
        List of DbDependency objects found.
    """
    if exclude_patterns is None:
        exclude_patterns = ["*/bin/*", "*/obj/*", "*/temp_test_data/*"]
    if sproc_prefixes is None:
        sproc_prefixes = list(DEFAULT_SPROC_PREFIXES)

    sproc_pattern = _build_sproc_pattern(sproc_prefixes)

    # Build project→cs mapping if not provided
    if project_cs_map is None:
        project_cs_map, _ = _discover_project_cs_map(
            search_scope, max_workers, chunk_size,
            disable_multiprocessing, exclude_patterns,
        )

    dependencies: List[DbDependency] = []

    for project_name, cs_paths in project_cs_map.items():
        for cs_path in cs_paths:
            try:
                raw_content = cs_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logging.debug(f"Could not read {cs_path}: {e}")
                continue

            stripped = _strip_cs_comments(raw_content)
            file_deps = _scan_file(
                stripped, cs_path, project_name, sproc_pattern,
            )
            dependencies.extend(file_deps)

    logging.info(
        f"DB scanner found {len(dependencies)} database dependencies "
        f"across {len(project_cs_map)} projects"
    )
    return dependencies


def _scan_file(
    content: str,
    source_file: Path,
    project_name: str,
    sproc_pattern: re.Pattern,
) -> List[DbDependency]:
    """Scan a single file's comment-stripped content for all DB dependency types."""
    deps: List[DbDependency] = []
    idx = _FileIndex(content)

    # 1. Stored procedure references
    for m in sproc_pattern.finditer(content):
        sproc_name = m.group().strip("\"'")
        deps.append(DbDependency(
            db_object_name=sproc_name,
            db_object_type="sproc",
            source_file=source_file,
            source_project=project_name,
            detection_method="string_literal",
            containing_class=idx.enclosing_class(m.start()),
            line_number=idx.line_number(m.start()),
        ))

    # 2. DbSet<T> patterns
    for m in _DBSET_PATTERN.finditer(content):
        model_name = m.group(1)
        deps.append(DbDependency(
            db_object_name=model_name,
            db_object_type="ef_model",
            source_file=source_file,
            source_project=project_name,
            detection_method="ef_dbset",
            containing_class=idx.enclosing_class(m.start()),
            line_number=idx.line_number(m.start()),
        ))

    # 3. DbContext subclasses
    for m in _DBCONTEXT_PATTERN.finditer(content):
        context_name = m.group(1)
        deps.append(DbDependency(
            db_object_name=context_name,
            db_object_type="ef_context",
            source_file=source_file,
            source_project=project_name,
            detection_method="ef_dbcontext",
            line_number=idx.line_number(m.start()),
        ))

    # 4. Direct SQL in string literals
    for m in _SQL_PATTERN.finditer(content):
        table_name = m.group(1)
        # Skip common false positives (SQL keywords that look like table names)
        if table_name.upper() in ("SET", "WHERE", "AND", "OR", "VALUES", "NULL"):
            continue
        deps.append(DbDependency(
            db_object_name=table_name,
            db_object_type="sql_table",
            source_file=source_file,
            source_project=project_name,
            detection_method="sql_text",
            containing_class=idx.enclosing_class(m.start()),
            line_number=idx.line_number(m.start()),
        ))

    # 5. Connection strings
    for m in _CONN_STRING_PATTERN.finditer(content):
        conn_value = m.group(1).strip()
        if conn_value:
            deps.append(DbDependency(
                db_object_name=conn_value,
                db_object_type="connection_string",
                source_file=source_file,
                source_project=project_name,
                detection_method="connection_string",
                containing_class=idx.enclosing_class(m.start()),
                line_number=idx.line_number(m.start()),
            ))

    return deps


# ---------------------------------------------------------------------------
# Cross-project analysis
# ---------------------------------------------------------------------------

def build_db_dependency_matrix(
    dependencies: List[DbDependency],
) -> Dict[str, List[str]]:
    """Build a cross-project DB object matrix.

    Returns: {db_object_name: [project_names_that_reference_it]}
    Objects referenced by 2+ projects are shared dependencies.
    """
    obj_to_projects: Dict[str, Set[str]] = defaultdict(set)

    for dep in dependencies:
        # Only sprocs and tables are meaningful for cross-project sharing
        if dep.db_object_type in ("sproc", "sql_table", "ef_model"):
            obj_to_projects[dep.db_object_name].add(dep.source_project)

    return {
        name: sorted(projects)
        for name, projects in sorted(obj_to_projects.items())
    }


def add_db_edges_to_graph(
    graph: DependencyGraph,
    dependencies: List[DbDependency],
) -> int:
    """Add sproc_shared edges for DB objects shared between projects.

    For each pair of projects that share one or more DB objects, adds a
    single bidirectional edge with all shared objects as evidence and
    weight equal to the number of shared objects. This avoids inflating
    coupling scores with redundant per-object edges.

    Returns the number of edges added.
    """
    matrix = build_db_dependency_matrix(dependencies)

    # Aggregate: collect all shared DB objects per project pair
    pair_evidence: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    for db_object, projects in matrix.items():
        if len(projects) < 2:
            continue
        for i, source in enumerate(projects):
            for target in projects[i + 1:]:
                if graph.get_node(source) is None or graph.get_node(target) is None:
                    continue
                # Use sorted tuple as canonical key so (A,B) and (B,A) merge
                pair_evidence[(source, target)].append(db_object)

    edges_added = 0
    for (source, target), evidence in pair_evidence.items():
        graph.add_edge(DependencyEdge(
            source=source,
            target=target,
            edge_type="sproc_shared",
            weight=float(len(evidence)),
            evidence=sorted(evidence),
        ))
        graph.add_edge(DependencyEdge(
            source=target,
            target=source,
            edge_type="sproc_shared",
            weight=float(len(evidence)),
            evidence=sorted(evidence),
        ))
        edges_added += 2

    logging.info(f"Added {edges_added} sproc_shared edges to graph")
    return edges_added


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _discover_project_cs_map(
    search_scope: Path,
    max_workers: int,
    chunk_size: int,
    disable_multiprocessing: bool,
    exclude_patterns: List[str],
) -> Tuple[Dict[str, List[Path]], List[Tuple[Path, str]]]:
    """Discover .cs files and map them to parent projects.

    Returns (project_cs_map, project_dir_index).
    """
    import fnmatch

    # Find all .csproj files
    all_csproj = find_files_with_pattern_parallel(
        search_scope, "*.csproj",
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing,
    )
    csproj_files = [
        p for p in all_csproj
        if not any(fnmatch.fnmatch(str(p), pat) for pat in exclude_patterns)
    ]

    # Build project directory index (deepest first)
    dir_index: List[Tuple[Path, str]] = []
    for csproj in csproj_files:
        dir_index.append((csproj.parent, csproj.stem))
    dir_index.sort(key=lambda x: -len(x[0].parts))

    # Find all .cs files
    all_cs = find_files_with_pattern_parallel(
        search_scope, "*.cs",
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing,
    )
    cs_files = [
        p for p in all_cs
        if not any(fnmatch.fnmatch(str(p), pat) for pat in exclude_patterns)
    ]

    # Map .cs files to projects
    project_cs_map: Dict[str, List[Path]] = defaultdict(list)
    for cs_path in cs_files:
        cs_parents = set(cs_path.parents)
        for project_dir, project_name in dir_index:
            if project_dir in cs_parents or project_dir == cs_path.parent:
                project_cs_map[project_name].append(cs_path)
                break

    return dict(project_cs_map), dir_index
