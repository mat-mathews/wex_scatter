"""Incremental graph patching — surgical updates instead of full rebuilds.

When scatter runs, it checks git diff for changes since the last graph build.
If only a few files changed, it patches the cached graph in milliseconds
instead of rebuilding from scratch.

Strategy:
  1. Classify changes (.cs vs .csproj, added/modified/deleted)
  2. Safety valves (structural change, threshold exceeded → full rebuild)
  3. Content hash early cutoff (unchanged hash → skip re-extraction)
  4. Declaration early cutoff (types_declared unchanged → cheap path)
  5. Project-level edge attribution (rebuild outgoing edges from affected projects)
"""
import logging
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.core.patterns import IDENT_PATTERN as _IDENT_PATTERN
from scatter.core.patterns import SPROC_PATTERN as _SPROC_PATTERN
from scatter.core.patterns import USING_PATTERN as _USING_PATTERN
from scatter.scanners.db_scanner import _strip_cs_comments
from scatter.scanners.project_scanner import (
    derive_namespace,
    parse_csproj_all_references,
)
from scatter.scanners.type_scanner import extract_type_names_from_content
from scatter.store.graph_cache import (
    FileFacts,
    ProjectFacts,
    compute_content_hash,
    compute_project_set_hash,
)


@dataclass
class PatchResult:
    """Result of an incremental graph patch."""

    graph: DependencyGraph
    file_facts: Dict[str, FileFacts]
    project_facts: Dict[str, ProjectFacts]
    patch_applied: bool  # True if patched, False if fell back to full rebuild
    files_processed: int  # number of files re-extracted
    projects_affected: int  # number of projects with edge rebuilds
    declarations_changed: bool  # whether type_to_projects was rebuilt
    elapsed_ms: float = 0.0


# --- Fact Extraction ---


def extract_file_facts(
    cs_path: Path,
    project_name: str,
    search_scope: Path,
) -> FileFacts:
    """Read a single .cs file and extract types, namespaces, sprocs, content hash."""
    content_hash = compute_content_hash(cs_path)

    try:
        content = cs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        rel = str(cs_path.relative_to(search_scope)) if search_scope else str(cs_path)
        return FileFacts(
            path=rel, project=project_name, content_hash=content_hash,
        )

    types = sorted(extract_type_names_from_content(content))

    namespaces = sorted(set(m.group(1) for m in _USING_PATTERN.finditer(content)))

    sprocs = sorted(
        set(m.group().strip("\"'") for m in _SPROC_PATTERN.finditer(content))
    )

    try:
        rel = str(cs_path.relative_to(search_scope))
    except ValueError:
        rel = str(cs_path)

    return FileFacts(
        path=rel,
        project=project_name,
        types_declared=types,
        namespaces_used=namespaces,
        sprocs_referenced=sprocs,
        content_hash=content_hash,
    )


def extract_project_facts(
    csproj_path: Path,
    all_project_names: Set[str],
) -> ProjectFacts:
    """Parse a single .csproj and extract namespace, references, content hash."""
    content_hash = compute_content_hash(csproj_path)
    namespace = derive_namespace(csproj_path)

    parsed = parse_csproj_all_references(csproj_path)
    if parsed is None:
        return ProjectFacts(
            namespace=namespace,
            csproj_content_hash=content_hash,
        )

    # Resolve reference include paths to project names
    ref_names = []
    for include in parsed["project_references"]:
        if "$(" in include:
            continue
        try:
            ref_abs = (csproj_path.parent / include).resolve(strict=False)
            ref_name = ref_abs.stem
            if ref_name in all_project_names:
                ref_names.append(ref_name)
        except OSError:
            pass

    return ProjectFacts(
        namespace=namespace,
        project_references=sorted(ref_names),
        csproj_content_hash=content_hash,
    )


# --- Git Diff ---


def get_changed_files(
    cached_git_head: str,
    search_scope: Path,
) -> Optional[List[str]]:
    """Return list of changed .cs/.csproj files since cached_git_head.

    Returns None if git is unavailable or cached_git_head is unreachable
    (e.g., after a force push). Caller should fall back to full rebuild.
    """
    try:
        result = subprocess.run(
            [
                "git", "diff", "--name-only",
                cached_git_head, "HEAD",
                "--", "*.csproj", "*.cs",
            ],
            cwd=str(search_scope),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logging.debug(f"git diff failed (rc={result.returncode}): {result.stderr.strip()}")
            return None

        output = result.stdout.strip()
        if not output:
            return []
        return output.splitlines()

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logging.debug(f"git diff failed: {e}")
        return None


# --- Patch Algorithm ---


def patch_graph(
    graph: DependencyGraph,
    file_facts: Dict[str, FileFacts],
    project_facts: Dict[str, ProjectFacts],
    changed_files: List[str],
    search_scope: Path,
    rebuild_threshold_projects: int = 50,
    rebuild_threshold_pct: float = 0.30,
    cached_project_set_hash: Optional[str] = None,
) -> PatchResult:
    """Incrementally patch a cached graph based on changed files.

    Returns PatchResult with patch_applied=False if a full rebuild is needed.
    """
    start = time.monotonic()

    # Shallow-copy input dicts so callers aren't affected by partial mutation
    # if we bail out partway through patching.
    file_facts = dict(file_facts)
    project_facts = dict(project_facts)

    # Validate project set hasn't changed structurally (e.g., external tool added a .csproj)
    if cached_project_set_hash is not None:
        current_hash = compute_project_set_hash(list(project_facts.keys()))
        if current_hash != cached_project_set_hash:
            logging.info("Project set hash mismatch. Full rebuild needed.")
            return _no_patch(graph, file_facts, project_facts, start)

    if not changed_files:
        return PatchResult(
            graph=graph,
            file_facts=file_facts,
            project_facts=project_facts,
            patch_applied=True,
            files_processed=0,
            projects_affected=0,
            declarations_changed=False,
            elapsed_ms=0.0,
        )

    # Step 1: Classify changes
    changed_cs: List[str] = []
    changed_csproj: List[str] = []
    for f in changed_files:
        if f.endswith(".cs"):
            changed_cs.append(f)
        elif f.endswith(".csproj"):
            changed_csproj.append(f)

    # Step 2: Detect structural changes (.csproj added or removed)
    existing_csproj_paths = set()
    for node in graph.get_all_nodes():
        try:
            rel = str(node.path.relative_to(search_scope))
        except ValueError:
            rel = str(node.path)
        existing_csproj_paths.add(rel)

    for csproj_rel in changed_csproj:
        csproj_abs = search_scope / csproj_rel
        is_known = csproj_rel in existing_csproj_paths
        exists_on_disk = csproj_abs.is_file()

        if not is_known and exists_on_disk:
            # New .csproj added → structural change
            logging.info(f"Structural change: new project {csproj_rel}. Full rebuild needed.")
            return _no_patch(graph, file_facts, project_facts, start)
        if is_known and not exists_on_disk:
            # .csproj deleted → structural change
            logging.info(f"Structural change: project removed {csproj_rel}. Full rebuild needed.")
            return _no_patch(graph, file_facts, project_facts, start)

    # Step 3: Map changed .cs to affected projects
    # Build project directory index from graph nodes
    project_dir_index = _build_project_dir_index(graph, search_scope)
    affected_projects: Set[str] = set()

    for cs_rel in changed_cs:
        cs_abs = search_scope / cs_rel
        project_name = _map_file_to_project(cs_abs, project_dir_index)
        if project_name:
            affected_projects.add(project_name)

    # Also mark projects with changed .csproj
    for csproj_rel in changed_csproj:
        csproj_abs = search_scope / csproj_rel
        project_name = csproj_abs.stem
        if project_name in {n.name for n in graph.get_all_nodes()}:
            affected_projects.add(project_name)

    # Step 4: Check thresholds
    total_projects = graph.node_count
    if len(affected_projects) > rebuild_threshold_projects:
        logging.info(
            f"Threshold exceeded: {len(affected_projects)} projects affected "
            f"(limit: {rebuild_threshold_projects}). Full rebuild needed."
        )
        return _no_patch(graph, file_facts, project_facts, start)

    total_files = len(file_facts)
    if total_files > 0 and len(changed_cs) / total_files > rebuild_threshold_pct:
        logging.info(
            f"Threshold exceeded: {len(changed_cs)}/{total_files} files changed "
            f"({rebuild_threshold_pct:.0%} limit). Full rebuild needed."
        )
        return _no_patch(graph, file_facts, project_facts, start)

    # Step 5: Re-extract facts for changed .cs files
    files_processed = 0
    declarations_changed = False

    # Handle deleted .cs files
    for cs_rel in changed_cs:
        cs_abs = search_scope / cs_rel
        if not cs_abs.is_file() and cs_rel in file_facts:
            old_facts = file_facts.pop(cs_rel)
            affected_projects.add(old_facts.project)
            if old_facts.types_declared:
                declarations_changed = True

    # Handle new and modified .cs files
    for cs_rel in changed_cs:
        cs_abs = search_scope / cs_rel
        if not cs_abs.is_file():
            continue  # already handled deletion

        project_name = _map_file_to_project(cs_abs, project_dir_index)
        if not project_name:
            continue

        # Content hash early cutoff
        old = file_facts.get(cs_rel)
        new_facts = extract_file_facts(cs_abs, project_name, search_scope)
        files_processed += 1

        if old and old.content_hash and old.content_hash == new_facts.content_hash:
            # Content unchanged despite git reporting a change (e.g., whitespace)
            continue

        # Check if declarations changed
        if old is None or sorted(old.types_declared) != sorted(new_facts.types_declared):
            declarations_changed = True

        file_facts[cs_rel] = new_facts
        affected_projects.add(project_name)

    # Step 6: Handle .csproj changes
    namespace_changed = False
    all_project_names = {n.name for n in graph.get_all_nodes()}

    for csproj_rel in changed_csproj:
        csproj_abs = search_scope / csproj_rel
        if not csproj_abs.is_file():
            continue

        project_name = csproj_abs.stem
        old_pfacts = project_facts.get(project_name)
        new_pfacts = extract_project_facts(csproj_abs, all_project_names)

        # Content hash early cutoff
        if old_pfacts and old_pfacts.csproj_content_hash == new_pfacts.csproj_content_hash:
            continue

        # Check namespace change
        if old_pfacts and old_pfacts.namespace != new_pfacts.namespace:
            namespace_changed = True
            # Update node namespace
            ns_node = graph.get_node(project_name)
            if ns_node:
                ns_node.namespace = new_pfacts.namespace

        project_facts[project_name] = new_pfacts
        affected_projects.add(project_name)

    # Step 7: Rebuild edges from affected projects
    if affected_projects:
        # Build project → files index once (avoids O(all_files) scan per helper)
        project_to_files = _build_project_to_files(file_facts)

        # Rebuild lookup maps
        namespace_to_project = _build_namespace_to_project(graph)
        type_to_projects = _build_type_to_projects(file_facts)

        # Update node type_declarations and sproc_references from current facts
        _update_node_metadata(graph, file_facts, affected_projects, project_to_files)

        for project_name in affected_projects:
            if project_name not in all_project_names:
                continue

            project_files = project_to_files.get(project_name, [])

            # Remove analysis edges (not project_reference yet)
            graph.remove_edges_from(
                project_name,
                {"namespace_usage", "type_usage", "sproc_shared"},
            )

            # Rebuild namespace_usage edges
            _rebuild_namespace_edges(
                graph, project_name, file_facts, namespace_to_project,
                project_files,
            )

            # Rebuild type_usage edges
            _rebuild_type_usage_edges(
                graph, project_name, file_facts, type_to_projects, search_scope,
                project_files,
            )

            # Rebuild sproc_shared edges
            _rebuild_sproc_edges(
                graph, project_name, file_facts, project_files,
            )

        # Rebuild project_reference edges for affected projects with .csproj changes
        for csproj_rel in changed_csproj:
            project_name = (search_scope / csproj_rel).stem
            if project_name in affected_projects:
                graph.remove_edges_from(project_name, {"project_reference"})
                _rebuild_project_reference_edges(
                    graph, project_name, project_facts, search_scope,
                )

        # If namespace changed, rebuild namespace edges for ALL projects
        if namespace_changed:
            namespace_to_project = _build_namespace_to_project(graph)
            for node in graph.get_all_nodes():
                if node.name not in affected_projects:
                    graph.remove_edges_from(node.name, {"namespace_usage"})
                    _rebuild_namespace_edges(
                        graph, node.name, file_facts, namespace_to_project,
                        project_to_files.get(node.name, []),
                    )

        # If declarations changed, rebuild type_usage edges for ALL projects
        if declarations_changed:
            type_to_projects = _build_type_to_projects(file_facts)
            for node in graph.get_all_nodes():
                if node.name not in affected_projects:
                    graph.remove_edges_from(node.name, {"type_usage"})
                    _rebuild_type_usage_edges(
                        graph, node.name, file_facts, type_to_projects, search_scope,
                        project_to_files.get(node.name, []),
                    )

    elapsed = (time.monotonic() - start) * 1000

    return PatchResult(
        graph=graph,
        file_facts=file_facts,
        project_facts=project_facts,
        patch_applied=True,
        files_processed=files_processed,
        projects_affected=len(affected_projects),
        declarations_changed=declarations_changed,
        elapsed_ms=round(elapsed, 1),
    )


# --- Edge Rebuild Helpers ---


def _rebuild_namespace_edges(
    graph: DependencyGraph,
    project: str,
    file_facts: Dict[str, FileFacts],
    namespace_to_project: Dict[str, str],
    project_files: List[str],
) -> None:
    """Rebuild namespace_usage edges from project based on current file facts."""
    # Collect all namespaces used by this project's files
    ns_evidence: Dict[str, List[str]] = defaultdict(list)
    for rel_path in project_files:
        facts = file_facts.get(rel_path)
        if facts is None:
            continue
        for ns in facts.namespaces_used:
            ns_evidence[ns].append(rel_path)

    for ns, evidence in ns_evidence.items():
        target = namespace_to_project.get(ns)
        if target and target != project and graph.get_node(target):
            graph.add_edge(
                DependencyEdge(
                    source=project,
                    target=target,
                    edge_type="namespace_usage",
                    weight=len(evidence),
                    evidence=evidence,
                )
            )


def _rebuild_type_usage_edges(
    graph: DependencyGraph,
    project: str,
    file_facts: Dict[str, FileFacts],
    type_to_projects: Dict[str, Set[str]],
    search_scope: Path,
    project_files: List[str],
) -> None:
    """Rebuild type_usage edges from project by re-tokenizing its .cs files."""
    type_name_set = set(type_to_projects.keys())
    type_usage_evidence: Dict[str, List[str]] = defaultdict(list)

    for rel_path in project_files:
        cs_abs = search_scope / rel_path
        try:
            content = cs_abs.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        content = _strip_cs_comments(content)
        file_identifiers = set(_IDENT_PATTERN.findall(content))
        matched_types = file_identifiers & type_name_set

        for type_name in matched_types:
            for owner in type_to_projects[type_name]:
                if owner != project and graph.get_node(owner):
                    type_usage_evidence[owner].append(f"{rel_path}:{type_name}")

    for target, evidence in type_usage_evidence.items():
        graph.add_edge(
            DependencyEdge(
                source=project,
                target=target,
                edge_type="type_usage",
                weight=len(evidence),
                evidence=evidence,
            )
        )


def _rebuild_sproc_edges(
    graph: DependencyGraph,
    project: str,
    file_facts: Dict[str, FileFacts],
    project_files: List[str],
) -> None:
    """Rebuild sproc_shared edges for project based on current sproc refs."""
    project_sprocs: Set[str] = set()
    for rel_path in project_files:
        facts = file_facts.get(rel_path)
        if facts is not None:
            project_sprocs.update(facts.sprocs_referenced)

    if not project_sprocs:
        return

    # Find other projects that share sprocs — this must scan all facts
    # but only happens when the project actually references sprocs (rare)
    other_sprocs: Dict[str, Set[str]] = defaultdict(set)
    for facts in file_facts.values():
        if facts.project != project and facts.sprocs_referenced:
            other_sprocs[facts.project].update(facts.sprocs_referenced)

    for other_project, their_sprocs in other_sprocs.items():
        shared = project_sprocs & their_sprocs
        if shared and graph.get_node(other_project):
            graph.add_edge(
                DependencyEdge(
                    source=project,
                    target=other_project,
                    edge_type="sproc_shared",
                    weight=len(shared),
                    evidence=sorted(shared),
                )
            )


def _rebuild_project_reference_edges(
    graph: DependencyGraph,
    project: str,
    project_facts: Dict[str, ProjectFacts],
    search_scope: Path,
) -> None:
    """Rebuild project_reference edges from project based on current .csproj refs."""
    pfacts = project_facts.get(project)
    if not pfacts:
        return

    # Reconstruct relative Include path for evidence consistency with full builder
    source_node = graph.get_node(project)
    for ref_name in pfacts.project_references:
        target_node = graph.get_node(ref_name)
        if not target_node:
            continue
        # Build a relative Include path like "../RefProject/RefProject.csproj"
        if source_node:
            try:
                import os
                include = os.path.relpath(
                    str(target_node.path), str(source_node.path.parent)
                )
            except (ValueError, TypeError):
                include = ref_name
        else:
            include = ref_name
        graph.add_edge(
            DependencyEdge(
                source=project,
                target=ref_name,
                edge_type="project_reference",
                weight=1.0,
                evidence=[include],
            )
        )


# --- Internal Helpers ---


def _no_patch(graph, file_facts, project_facts, start) -> PatchResult:
    """Return a PatchResult indicating full rebuild is needed."""
    elapsed = (time.monotonic() - start) * 1000
    return PatchResult(
        graph=graph,
        file_facts=file_facts,
        project_facts=project_facts,
        patch_applied=False,
        files_processed=0,
        projects_affected=0,
        declarations_changed=False,
        elapsed_ms=round(elapsed, 1),
    )


def _build_project_dir_index(
    graph: DependencyGraph, search_scope: Path
) -> List[Tuple[Path, str]]:
    """Build project directory index from graph nodes, sorted deepest first."""
    index = []
    for node in graph.get_all_nodes():
        project_dir = node.path.parent
        index.append((project_dir, node.name))
    index.sort(key=lambda x: -len(x[0].parts))
    return index


def _map_file_to_project(
    file_path: Path, project_dirs: List[Tuple[Path, str]]
) -> Optional[str]:
    """Find the closest ancestor project for a file."""
    parents = set(file_path.parents)
    for project_dir, project_name in project_dirs:
        if project_dir in parents or project_dir == file_path.parent:
            return project_name
    return None


def _build_project_to_files(file_facts: Dict[str, FileFacts]) -> Dict[str, List[str]]:
    """Build project name → list of relative file paths index."""
    p2f: Dict[str, List[str]] = defaultdict(list)
    for rel_path, facts in file_facts.items():
        p2f[facts.project].append(rel_path)
    return dict(p2f)


def _build_namespace_to_project(graph: DependencyGraph) -> Dict[str, str]:
    """Build namespace → project name lookup from graph nodes."""
    ns_map: Dict[str, str] = {}
    for node in graph.get_all_nodes():
        if node.namespace:
            ns_map[node.namespace] = node.name
    return ns_map


def _build_type_to_projects(file_facts: Dict[str, FileFacts]) -> Dict[str, Set[str]]:
    """Build type name → owning projects lookup from file facts."""
    t2p: Dict[str, Set[str]] = defaultdict(set)
    for facts in file_facts.values():
        for t in facts.types_declared:
            t2p[t].add(facts.project)
    return t2p


def _update_node_metadata(
    graph: DependencyGraph,
    file_facts: Dict[str, FileFacts],
    affected_projects: Set[str],
    project_to_files: Dict[str, List[str]],
) -> None:
    """Update type_declarations and sproc_references on affected project nodes."""
    for project_name in affected_projects:
        node = graph.get_node(project_name)
        if not node:
            continue
        types: Set[str] = set()
        sprocs: Set[str] = set()
        file_count = 0
        for rel_path in project_to_files.get(project_name, []):
            facts = file_facts.get(rel_path)
            if facts is not None:
                types.update(facts.types_declared)
                sprocs.update(facts.sprocs_referenced)
                file_count += 1
        node.type_declarations = sorted(types)
        node.sproc_references = sorted(sprocs)
        node.file_count = file_count
