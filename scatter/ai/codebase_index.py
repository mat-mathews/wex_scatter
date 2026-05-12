"""Build a compact text index from the dependency graph for LLM context."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from scatter.core.graph import DependencyGraph

logger = logging.getLogger(__name__)

_TYPE_STOPLIST = frozenset(
    {
        "Program",
        "Startup",
        "Constants",
        "Extensions",
        "AssemblyInfo",
        "Resources",
        "Settings",
        "App",
        "GlobalSuppressions",
        "Module",
        "ServiceCollectionExtensions",
        "DependencyInjection",
        "AutofacModule",
        "MappingProfile",
    }
)

_DEFAULT_MAX_TYPES_CAPS = [15, 10, 5]


@dataclass
class CodebaseIndex:
    """Compact text representation of codebase artifacts for LLM prompts."""

    text: str
    project_count: int
    type_count: int
    sproc_count: int
    file_count: int
    size_bytes: int


def _filter_types(
    types: List[str],
    project_name: str,
    stoplist: frozenset = _TYPE_STOPLIST,
) -> List[str]:
    """Remove stoplist entries, single-char names, and project-name duplicates."""
    return [t for t in types if t not in stoplist and len(t) > 1 and t != project_name]


def _apply_type_cap(types: List[str], cap: int) -> List[str]:
    """Keep top N types by name length. Appends '...' sentinel if truncated."""
    if len(types) <= cap:
        return types
    kept = set(sorted(types, key=len, reverse=True)[:cap])
    return [t for t in types if t in kept] + ["..."]


def build_codebase_index(
    graph: DependencyGraph,
    search_scope: Optional[Path] = None,
    max_bytes: Optional[int] = None,
) -> CodebaseIndex:
    """Build compact text index from the dependency graph.

    The index uses a one-line-per-project format optimized for token efficiency.
    When max_bytes is set and the index exceeds the budget, progressive
    reductions are applied to bring it under budget while preserving the
    highest-signal data.
    """
    nodes = graph.get_all_nodes()
    if not nodes:
        return CodebaseIndex(
            text="", project_count=0, type_count=0, sproc_count=0, file_count=0, size_bytes=0
        )

    nodes.sort(key=lambda n: n.name)

    # Count file stems for metrics only (not included in prompt text)
    total_file_count = 0
    if search_scope:
        for node in nodes:
            project_dir = node.path.parent
            if project_dir.is_dir():
                total_file_count += sum(
                    1 for f in project_dir.glob("*.cs") if not f.name.startswith(".")
                )

    # Collect sprocs with owning projects for cross-reference
    sproc_to_projects: dict[str, List[str]] = {}
    for node in nodes:
        for sproc in node.sproc_references:
            sproc_to_projects.setdefault(sproc, []).append(node.name)

    # Build compact index text
    text = _build_index_text(nodes, sproc_to_projects)
    size_bytes = len(text.encode("utf-8"))

    total_type_count = sum(len(n.type_declarations) for n in nodes)
    total_sproc_count = sum(len(n.sproc_references) for n in nodes)
    project_count = len(nodes)

    # Apply budget compression if needed
    if max_bytes is not None and size_bytes > max_bytes:
        logger.info(
            "Index exceeds budget (%s > %s bytes). Applying reductions...",
            f"{size_bytes:,}",
            f"{max_bytes:,}",
        )
        text, size_bytes, project_count, total_type_count = _compress_index(
            nodes,
            sproc_to_projects,
            max_bytes,
            size_bytes,
        )

    return CodebaseIndex(
        text=text,
        project_count=project_count,
        type_count=total_type_count,
        sproc_count=total_sproc_count,
        file_count=total_file_count,
        size_bytes=size_bytes,
    )


def _compress_index(
    nodes,
    sproc_to_projects: dict[str, List[str]],
    max_bytes: int,
    original_size: int,
) -> tuple[str, int, int, int]:
    """Apply progressive reductions to bring index under budget.

    Returns (text, size_bytes, project_count, type_count).
    """
    steps_applied: List[str] = []
    type_overrides: Dict[str, List[str]] = {
        node.name: list(node.type_declarations) for node in nodes
    }
    include_shared_sprocs = True
    active_nodes = list(nodes)

    def _rebuild() -> tuple[str, int]:
        txt = _build_index_text(
            active_nodes,
            sproc_to_projects,
            type_overrides=type_overrides,
            include_shared_sprocs=include_shared_sprocs,
        )
        return txt, len(txt.encode("utf-8"))

    def _count_types() -> int:
        active = {n.name for n in active_nodes}
        return sum(
            sum(1 for t in ts if t != "...")
            for name, ts in type_overrides.items()
            if name in active
        )

    def _finish(text: str, size: int) -> tuple[str, int, int, int]:
        reduction_pct = (original_size - size) * 100 // original_size
        logger.info(
            "Index reduced to %s bytes (%d%% reduction via %s)",
            f"{size:,}",
            reduction_pct,
            " \u2192 ".join(steps_applied),
        )
        return text, size, len(active_nodes), _count_types()

    # Step 1: Drop shared sproc cross-reference section
    include_shared_sprocs = False
    text, size = _rebuild()
    steps_applied.append("drop shared sprocs")
    logger.info("  Step 1 (drop shared sprocs): %s bytes", f"{size:,}")
    if size <= max_bytes:
        return _finish(text, size)

    # Step 2: Filter low-signal type names (stoplist)
    for node in active_nodes:
        type_overrides[node.name] = _filter_types(
            type_overrides[node.name],
            node.name,
        )
    text, size = _rebuild()
    steps_applied.append("stoplist filter")
    logger.info("  Step 2 (stoplist filter): %s bytes", f"{size:,}")
    if size <= max_bytes:
        return _finish(text, size)

    # Step 3: Progressive type caps
    for cap in _DEFAULT_MAX_TYPES_CAPS:
        for node in active_nodes:
            type_overrides[node.name] = _apply_type_cap(
                type_overrides[node.name],
                cap,
            )
        text, size = _rebuild()
        steps_applied.append(f"cap={cap}")
        logger.info("  Step 3 (cap=%d): %s bytes", cap, f"{size:,}")
        if size <= max_bytes:
            return _finish(text, size)

    # Step 4: Drop zero-signal projects (no types and no sprocs after filtering)
    active_nodes = [
        node for node in active_nodes if type_overrides[node.name] or node.sproc_references
    ]
    text, size = _rebuild()
    steps_applied.append("drop zero-signal projects")
    logger.info("  Step 4 (drop zero-signal): %s bytes", f"{size:,}")
    if size <= max_bytes:
        return _finish(text, size)

    # Best effort — still over budget after all reductions
    logger.warning(
        "All reductions applied but index still exceeds budget (%s > %s bytes). Steps: %s",
        f"{size:,}",
        f"{max_bytes:,}",
        ", ".join(steps_applied),
    )
    return text, size, len(active_nodes), _count_types()


def _build_index_text(
    nodes,
    sproc_to_projects: dict[str, List[str]],
    *,
    type_overrides: Optional[Dict[str, List[str]]] = None,
    include_shared_sprocs: bool = True,
) -> str:
    """Build compact one-line-per-project index text.

    Format:
        P=Project NS=Namespace (omitted when = project name) T=Types SP=StoredProcs
        P:Name T:Type1,Type2 SP:sproc1,sproc2
        P:Name NS:DifferentNamespace T:Type1
    """
    lines: List[str] = []
    lines.append(f"=== Codebase Index ({len(nodes)} projects) ===")
    lines.append(
        "P=Project NS=Namespace (omitted when same as project name) T=Types SP=StoredProcs"
    )

    for node in nodes:
        parts = [f"P:{node.name}"]

        # Only include namespace when it differs from project name
        if node.namespace and node.namespace != node.name:
            parts.append(f"NS:{node.namespace}")

        types = (
            type_overrides[node.name]
            if type_overrides is not None and node.name in type_overrides
            else node.type_declarations
        )
        if types:
            parts.append(f"T:{','.join(types)}")

        if node.sproc_references:
            parts.append(f"SP:{','.join(node.sproc_references)}")

        lines.append(" ".join(parts))

    # Shared sproc cross-reference: only if enabled and any sproc appears in 2+ projects
    if include_shared_sprocs:
        shared_sprocs = {
            sproc: projects for sproc, projects in sproc_to_projects.items() if len(projects) >= 2
        }
        if shared_sprocs:
            lines.append("")
            lines.append("=== Shared Stored Procedures ===")
            for sproc, projects in sorted(shared_sprocs.items()):
                lines.append(f"  {sproc}: {', '.join(sorted(projects))}")

    return "\n".join(lines)
