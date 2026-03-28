"""Build a compact text index from the dependency graph for LLM context."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from scatter.core.graph import DependencyGraph


@dataclass
class CodebaseIndex:
    """Compact text representation of codebase artifacts for LLM prompts."""

    text: str
    project_count: int
    type_count: int
    sproc_count: int
    file_count: int
    size_bytes: int


def build_codebase_index(
    graph: DependencyGraph,
    search_scope: Optional[Path] = None,
) -> CodebaseIndex:
    """Build compact text index from the dependency graph.

    The index uses a one-line-per-project format optimized for token efficiency.
    File stems are only collected for the file_count metric (not included in the
    LLM prompt). All types are always included — if the index exceeds a model's
    context window, the API call will error with an actionable message.
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

    total_type_count = sum(len(n.type_declarations) for n in nodes)
    total_sproc_count = sum(len(n.sproc_references) for n in nodes)

    # Collect sprocs with owning projects for cross-reference
    sproc_to_projects: dict[str, List[str]] = {}
    for node in nodes:
        for sproc in node.sproc_references:
            sproc_to_projects.setdefault(sproc, []).append(node.name)

    # Build compact index text
    text = _build_index_text(nodes, sproc_to_projects)
    size_bytes = len(text.encode("utf-8"))

    return CodebaseIndex(
        text=text,
        project_count=len(nodes),
        type_count=total_type_count,
        sproc_count=total_sproc_count,
        file_count=total_file_count,
        size_bytes=size_bytes,
    )


def _build_index_text(
    nodes,
    sproc_to_projects: dict[str, List[str]],
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

        if node.type_declarations:
            parts.append(f"T:{','.join(node.type_declarations)}")

        if node.sproc_references:
            parts.append(f"SP:{','.join(node.sproc_references)}")

        lines.append(" ".join(parts))

    # Shared sproc cross-reference: only if any sproc appears in 2+ projects
    shared_sprocs = {
        sproc: projects for sproc, projects in sproc_to_projects.items() if len(projects) >= 2
    }
    if shared_sprocs:
        lines.append("")
        lines.append("=== Shared Stored Procedures ===")
        for sproc, projects in sorted(shared_sprocs.items()):
            lines.append(f"  {sproc}: {', '.join(sorted(projects))}")

    return "\n".join(lines)
