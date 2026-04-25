"""Dependency graph data structures for .NET project analysis.

DependencyGraph is a pure data structure — mutation, query, traversal,
serialization only. All analysis algorithms (cycles, metrics, clustering)
are standalone functions in their respective analyzer modules.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

MAX_EVIDENCE_ENTRIES = 10


@dataclass
class ProjectNode:
    """A .csproj project in the dependency graph."""

    path: Path
    name: str
    namespace: Optional[str] = None
    framework: Optional[str] = None
    project_style: str = "sdk"
    output_type: Optional[str] = None
    file_count: int = 0
    type_declarations: List[str] = field(default_factory=list)
    sproc_references: List[str] = field(default_factory=list)
    solutions: List[str] = field(default_factory=list)
    msbuild_imports: List[str] = field(default_factory=list)


@dataclass
class DependencyEdge:
    """A directed dependency between two projects."""

    source: str
    target: str
    edge_type: str  # "project_reference", "namespace_usage", "type_usage", "sproc_shared"
    weight: float = 1.0
    evidence: Optional[List[str]] = None
    evidence_total: int = 0


class DependencyGraph:
    """Directed dependency graph of .NET projects.

    Pure data structure — mutation, query, traversal, serialization only.
    Analysis algorithms (cycles, metrics, clustering) are standalone functions
    in their respective analyzer modules.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, ProjectNode] = {}
        self._outgoing: Dict[str, List[DependencyEdge]] = defaultdict(list)
        self._incoming: Dict[str, List[DependencyEdge]] = defaultdict(list)
        self._forward: Dict[str, Set[str]] = defaultdict(set)
        self._reverse: Dict[str, Set[str]] = defaultdict(set)

    # --- Mutation ---

    def add_node(self, node: ProjectNode) -> None:
        """Add a project node. Raises ValueError if name already exists."""
        if node.name in self._nodes:
            raise ValueError(f"Node '{node.name}' already exists in the graph")
        self._nodes[node.name] = node

    def add_edge(self, edge: DependencyEdge) -> None:
        """Add a dependency edge. Validates nodes exist, caps evidence."""
        if edge.source not in self._nodes:
            raise ValueError(f"Edge source '{edge.source}' not found in graph")
        if edge.target not in self._nodes:
            raise ValueError(f"Edge target '{edge.target}' not found in graph")

        if edge.evidence is not None:
            total = len(edge.evidence)
            if total > MAX_EVIDENCE_ENTRIES:
                edge.evidence = edge.evidence[:MAX_EVIDENCE_ENTRIES]
                edge.evidence_total = total
            else:
                edge.evidence_total = total

        self._outgoing[edge.source].append(edge)
        self._incoming[edge.target].append(edge)
        self._forward[edge.source].add(edge.target)
        self._reverse[edge.target].add(edge.source)

    def remove_edges_from(self, source: str, edge_types: Optional[Set[str]] = None) -> int:
        """Remove outgoing edges from source, optionally filtered by edge_type.

        Updates _outgoing, _incoming, _forward, _reverse consistently.
        Returns count of edges removed. O(degree) single-pass.
        """
        if source not in self._outgoing:
            return 0

        edges = self._outgoing[source]

        # Single-pass partition into keep vs remove
        if edge_types is None:
            to_remove = edges[:]
            self._outgoing[source] = []
        else:
            to_remove_ids: Set[int] = set()
            to_remove = []
            keep = []
            for e in edges:
                if e.edge_type in edge_types:
                    to_remove.append(e)
                    to_remove_ids.add(id(e))
                else:
                    keep.append(e)
            if not to_remove:
                return 0
            self._outgoing[source] = keep

        # Remove from _incoming in one pass per affected target
        removed_targets: Set[str] = set()
        to_remove_ids = {id(e) for e in to_remove}
        for edge in to_remove:
            removed_targets.add(edge.target)

        for target in removed_targets:
            if target in self._incoming:
                self._incoming[target] = [
                    e for e in self._incoming[target] if id(e) not in to_remove_ids
                ]

        # Update _forward and _reverse — check if any edges to target remain
        remaining_targets = {e.target for e in self._outgoing.get(source, [])}
        for target in removed_targets:
            if target not in remaining_targets:
                self._forward.get(source, set()).discard(target)
                self._reverse.get(target, set()).discard(source)

        return len(to_remove)

    def remove_edges_to(self, target: str, edge_types: Optional[Set[str]] = None) -> int:
        """Remove incoming edges to target, optionally filtered by edge_type.

        Updates _outgoing, _incoming, _forward, _reverse consistently.
        Returns count of edges removed. O(degree) single-pass.
        """
        if target not in self._incoming:
            return 0

        edges = self._incoming[target]

        # Single-pass partition
        if edge_types is None:
            to_remove = edges[:]
            self._incoming[target] = []
        else:
            to_remove = []
            keep = []
            for e in edges:
                if e.edge_type in edge_types:
                    to_remove.append(e)
                else:
                    keep.append(e)
            if not to_remove:
                return 0
            self._incoming[target] = keep

        # Remove from _outgoing in one pass per affected source
        removed_sources: Set[str] = set()
        to_remove_ids = {id(e) for e in to_remove}
        for edge in to_remove:
            removed_sources.add(edge.source)

        for source in removed_sources:
            if source in self._outgoing:
                self._outgoing[source] = [
                    e for e in self._outgoing[source] if id(e) not in to_remove_ids
                ]

        # Update _forward and _reverse
        for source in removed_sources:
            still_has_edge = any(e.target == target for e in self._outgoing.get(source, []))
            if not still_has_edge:
                self._forward.get(source, set()).discard(target)
                self._reverse.get(target, set()).discard(source)

        return len(to_remove)

    # --- Query ---

    def get_node(self, name: str) -> Optional[ProjectNode]:
        return self._nodes.get(name)

    def get_all_nodes(self) -> List[ProjectNode]:
        return list(self._nodes.values())

    def get_dependencies(self, name: str) -> List[ProjectNode]:
        """What does this project depend on?"""
        return [self._nodes[dep] for dep in self._forward.get(name, set()) if dep in self._nodes]

    def get_consumers(self, name: str) -> List[ProjectNode]:
        """What depends on this project?"""
        return [self._nodes[con] for con in self._reverse.get(name, set()) if con in self._nodes]

    def get_dependency_names(self, name: str) -> Set[str]:
        """Names of projects this one depends on — O(1) set copy."""
        return set(self._forward.get(name, set()))

    def get_consumer_names(self, name: str) -> Set[str]:
        """Names of projects that depend on this one — O(1) set copy."""
        return set(self._reverse.get(name, set()))

    def get_edges_from(self, name: str) -> List[DependencyEdge]:
        """Outgoing edges from a node — O(degree)."""
        return list(self._outgoing.get(name, []))

    def get_edges_to(self, name: str) -> List[DependencyEdge]:
        """Incoming edges to a node — O(degree)."""
        return list(self._incoming.get(name, []))

    def get_edges_for(self, name: str) -> List[DependencyEdge]:
        """All edges involving this project (incoming + outgoing)."""
        edges = list(self._outgoing.get(name, []))
        edges.extend(self._incoming.get(name, []))
        return edges

    def get_projects_importing(self, import_path: str) -> List[ProjectNode]:
        """Projects whose msbuild_imports contain import_path."""
        normalized = import_path.replace("\\", "/")
        return [
            node
            for node in self._nodes.values()
            if normalized in node.msbuild_imports
        ]

    def get_edges_between(self, a: str, b: str) -> List[DependencyEdge]:
        """Edges between two specific nodes (either direction)."""
        result = []
        for edge in self._outgoing.get(a, []):
            if edge.target == b:
                result.append(edge)
        for edge in self._outgoing.get(b, []):
            if edge.target == a:
                result.append(edge)
        return result

    # --- Traversal ---

    def get_transitive_consumers(
        self, name: str, max_depth: int = 3
    ) -> List[Tuple[ProjectNode, int]]:
        """BFS traversal of consumers up to max_depth hops."""
        if name not in self._nodes:
            return []
        result: List[Tuple[ProjectNode, int]] = []
        visited: Set[str] = {name}
        queue: deque[Tuple[str, int]] = deque()

        for consumer_name in self._reverse.get(name, set()):
            if consumer_name not in visited:
                queue.append((consumer_name, 1))
                visited.add(consumer_name)

        while queue:
            current, depth = queue.popleft()
            node = self._nodes.get(current)
            if node:
                result.append((node, depth))
            if depth < max_depth:
                for next_name in self._reverse.get(current, set()):
                    if next_name not in visited:
                        visited.add(next_name)
                        queue.append((next_name, depth + 1))

        return result

    def get_transitive_dependencies(
        self, name: str, max_depth: int = 3
    ) -> List[Tuple[ProjectNode, int]]:
        """BFS traversal of dependencies up to max_depth hops."""
        if name not in self._nodes:
            return []
        result: List[Tuple[ProjectNode, int]] = []
        visited: Set[str] = {name}
        queue: deque[Tuple[str, int]] = deque()

        for dep_name in self._forward.get(name, set()):
            if dep_name not in visited:
                queue.append((dep_name, 1))
                visited.add(dep_name)

        while queue:
            current, depth = queue.popleft()
            node = self._nodes.get(current)
            if node:
                result.append((node, depth))
            if depth < max_depth:
                for next_name in self._forward.get(current, set()):
                    if next_name not in visited:
                        visited.add(next_name)
                        queue.append((next_name, depth + 1))

        return result

    # --- Export ---

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the graph to a JSON-compatible dict."""
        nodes = {}
        for name, node in self._nodes.items():
            nodes[name] = {
                "path": str(node.path),
                "name": node.name,
                "namespace": node.namespace,
                "framework": node.framework,
                "project_style": node.project_style,
                "output_type": node.output_type,
                "file_count": node.file_count,
                "type_declarations": node.type_declarations,
                "sproc_references": node.sproc_references,
                "solutions": node.solutions,
                "msbuild_imports": node.msbuild_imports,
            }

        edges = []
        for edge in self.all_edges:
            edges.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "edge_type": edge.edge_type,
                    "weight": edge.weight,
                    "evidence": edge.evidence,
                    "evidence_total": edge.evidence_total,
                }
            )

        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DependencyGraph":
        """Deserialize a graph from a dict."""
        graph = cls()

        for name, node_data in data.get("nodes", {}).items():
            node = ProjectNode(
                path=Path(node_data["path"]),
                name=node_data["name"],
                namespace=node_data.get("namespace"),
                framework=node_data.get("framework"),
                project_style=node_data.get("project_style", "sdk"),
                output_type=node_data.get("output_type"),
                file_count=node_data.get("file_count", 0),
                type_declarations=node_data.get("type_declarations", []),
                sproc_references=node_data.get("sproc_references", []),
                solutions=node_data.get("solutions", []),
                msbuild_imports=node_data.get("msbuild_imports", []),
            )
            graph.add_node(node)

        for edge_data in data.get("edges", []):
            edge = DependencyEdge(
                source=edge_data["source"],
                target=edge_data["target"],
                edge_type=edge_data["edge_type"],
                weight=edge_data.get("weight", 1.0),
                evidence=edge_data.get("evidence"),
                evidence_total=edge_data.get("evidence_total", 0),
            )
            graph.add_edge(edge)

        return graph

    # --- Properties ---

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self._outgoing.values())

    @property
    def all_edges(self) -> List[DependencyEdge]:
        """Flat list of all edges (for serialization)."""
        result = []
        for edges in self._outgoing.values():
            result.extend(edges)
        return result

    @property
    def connected_components(self) -> List[List[str]]:
        """Find connected components treating edges as undirected."""
        visited: Set[str] = set()
        components: List[List[str]] = []

        for node_name in self._nodes:
            if node_name in visited:
                continue
            component: List[str] = []
            queue: deque[str] = deque([node_name])
            visited.add(node_name)

            while queue:
                current = queue.popleft()
                component.append(current)
                neighbors = self._forward.get(current, set()) | self._reverse.get(current, set())
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            component.sort()
            components.append(component)

        components.sort(key=lambda c: (-len(c), c[0] if c else ""))
        return components
