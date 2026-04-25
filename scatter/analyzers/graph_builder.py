"""Build a complete dependency graph from a .NET codebase in a single pass.

Single-pass O(P+F) construction:
1. Discover all .csproj files
2. Parse each .csproj → extract ProjectReferences, metadata
3. Discover .cs files → map to parent projects via reverse index
4. For each project's .cs files → extract type declarations, sproc refs, namespace usages
5. Cross-reference namespace usages → build namespace_usage and type_usage edges
6. Construct DependencyGraph with all nodes and edges
"""

import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Set, Tuple

if TYPE_CHECKING:
    from scatter.config import AnalysisConfig

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.core.models import DEFAULT_CHUNK_SIZE, DEFAULT_MAX_WORKERS
from scatter.core.parallel import extract_exclude_dirs, walk_and_collect
from scatter.scanners.msbuild_import_scanner import (
    build_directory_build_index,
    resolve_directory_build_imports,
)
from scatter.scanners.project_scanner import (
    derive_namespace,
    parse_csproj,
)
from scatter.core.patterns import CSHARP_KEYWORDS as _CSHARP_KEYWORDS
from scatter.core.patterns import IDENT_PATTERN as _IDENT_PATTERN
from scatter.core.patterns import SPROC_PATTERN as _SPROC_PATTERN
from scatter.core.patterns import USING_PATTERN as _USING_PATTERN
from scatter.scanners.type_scanner import extract_type_names_from_content
from scatter.store.graph_cache import compute_content_hash


class _FileExtraction(NamedTuple):
    """Per-file extraction results — lightweight, immutable, thread-safe."""

    cs_path: Path
    identifiers: Set[str]
    types: Set[str]
    sprocs: Set[str]
    namespaces: Set[str]
    content_hash: str
    content: str


def _extract_file_data(cs_path: Path) -> Optional[_FileExtraction]:
    """Read a .cs file and extract all relevant data. Pure function, safe for threads."""
    try:
        content = cs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    identifiers = {m.group() for m in _IDENT_PATTERN.finditer(content)} - _CSHARP_KEYWORDS
    types = extract_type_names_from_content(content)

    return _FileExtraction(
        cs_path=cs_path,
        identifiers=identifiers,
        types=types,
        sprocs={m.group().strip("\"'") for m in _SPROC_PATTERN.finditer(content)},
        namespaces={m.group(1) for m in _USING_PATTERN.finditer(content)},
        content_hash=compute_content_hash(content),
        content=content,
    )


def build_dependency_graph(
    search_scope: Path,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    exclude_patterns: Optional[List[str]] = None,
    include_db_dependencies: bool = False,
    sproc_prefixes: Optional[List[str]] = None,
    capture_facts: bool = False,
    full_type_scan: bool = False,
    analysis_config: Optional["AnalysisConfig"] = None,
    discovered_files: Optional[Dict[str, List[Path]]] = None,
):
    """Build a complete dependency graph from a codebase directory.

    If capture_facts=True, returns (graph, file_facts, project_facts) tuple
    for v2 cache persistence. Otherwise returns just the graph.

    Args:
        analysis_config: Optional AnalysisConfig. Reserved for future analysis
            configuration. parser_mode is not used during graph construction —
            AST validation runs at query time in the consumer pipeline.
    """
    if exclude_patterns is None:
        exclude_patterns = ["*/bin/*", "*/obj/*", "*/temp_test_data/*"]

    graph = DependencyGraph()
    t0 = time.monotonic()

    # Step 1: Discover all .csproj and .cs files.
    # When called from __main__, files are pre-discovered in a single walk
    # shared with solution scanning. Standalone/test callers fall back to
    # walking here.
    if discovered_files is not None:
        csproj_files = discovered_files[".csproj"]
        cs_files = discovered_files[".cs"]
        props_files = discovered_files.get(".props", [])
        targets_files = discovered_files.get(".targets", [])
        logging.info(
            f"Using pre-discovered files: {len(csproj_files)} .csproj, {len(cs_files)} .cs"
        )
    else:
        exclude_dirs = extract_exclude_dirs(exclude_patterns)
        discovered = walk_and_collect(
            search_scope, {".csproj", ".cs", ".props", ".targets"}, exclude_dirs
        )
        csproj_files = discovered[".csproj"]
        cs_files = discovered[".cs"]
        props_files = discovered.get(".props", [])
        targets_files = discovered.get(".targets", [])

    t0a = time.monotonic()
    logging.info(
        f"Graph build step 1 (file discovery): {t0a - t0:.1f}s "
        f"— {len(csproj_files)} .csproj, {len(cs_files)} .cs"
    )

    # Step 2: Parse each .csproj → extract metadata + explicit imports (single XML pass)
    project_metadata: Dict[str, Dict[str, Any]] = {}
    project_refs: Dict[str, List[str]] = {}  # project_name -> list of ref include paths
    project_explicit_imports: Dict[str, List[Path]] = {}

    for csproj_path in csproj_files:
        parsed = parse_csproj(csproj_path, search_scope=search_scope)
        if parsed is None:
            continue

        project_name = csproj_path.stem
        namespace = derive_namespace(csproj_path)

        project_metadata[project_name] = {
            "path": csproj_path,
            "namespace": namespace,
            "framework": parsed["target_framework"],
            "project_style": parsed["project_style"],
            "output_type": parsed["output_type"],
        }
        project_refs[project_name] = parsed["project_references"]
        if parsed["explicit_imports"]:
            project_explicit_imports[project_name] = parsed["explicit_imports"]

    t0b = time.monotonic()
    logging.info(f"Graph build step 2 (csproj parsing): {t0b - t0a:.1f}s")

    # Step 2b: Resolve MSBuild imports (Directory.Build.props/targets + explicit <Import>)
    props_index, targets_index = build_directory_build_index(props_files, targets_files)
    project_msbuild_imports: Dict[str, List[str]] = {}

    for project_name, meta in project_metadata.items():
        csproj_path = meta["path"]
        imports: List[Path] = resolve_directory_build_imports(
            csproj_path.parent, props_index, targets_index, search_scope
        )
        imports.extend(project_explicit_imports.get(project_name, []))

        if imports:
            rel_paths = []
            resolved_scope = search_scope.resolve()
            for p in imports:
                try:
                    rel_paths.append(str(p.resolve().relative_to(resolved_scope)))
                except ValueError:
                    logging.warning(
                        f"MSBuild import outside search scope, skipping: {p} "
                        f"(project: {project_name})"
                    )
            if rel_paths:
                project_msbuild_imports[project_name] = sorted(rel_paths)

    logging.info(
        f"Graph build step 2b (MSBuild imports): "
        f"{len(props_index)} Directory.Build.props, "
        f"{len(targets_index)} Directory.Build.targets, "
        f"{sum(len(v) for v in project_msbuild_imports.values())} total import edges"
    )

    # Step 3: Map .cs files to parent projects via reverse index
    project_dir_index = _build_project_directory_index(csproj_files)
    project_cs_files: Dict[str, List[Path]] = defaultdict(list)

    for cs_path in cs_files:
        mapped_name = _map_cs_to_project(cs_path, project_dir_index)
        if mapped_name:
            project_cs_files[mapped_name].append(cs_path)

    t1 = time.monotonic()
    logging.info(f"Graph build step 3 (cs-to-project mapping): {t1 - t0b:.1f}s")

    # Step 4: For each project's .cs files, extract type declarations, sproc refs, namespace usages
    # Uses ThreadPoolExecutor for I/O-bound file reads (GIL released during I/O).
    project_types: Dict[str, Set[str]] = defaultdict(set)
    project_sprocs: Dict[str, Set[str]] = defaultdict(set)
    project_using_namespaces: Dict[str, Set[str]] = defaultdict(set)
    project_namespace_evidence: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    captured_file_facts: Optional[Dict] = {} if capture_facts else None
    file_identifier_cache: Dict[Path, Set[str]] = {}
    file_namespace_cache: Dict[Path, Set[str]] = {}
    content_by_path: Dict[Path, str] = {} if include_db_dependencies else {}

    # Flatten project→files for dispatch
    all_file_tasks: List[Tuple[str, Path]] = [
        (pname, cspath) for pname, cs_paths in project_cs_files.items() for cspath in cs_paths
    ]

    if disable_multiprocessing or len(all_file_tasks) < 100:
        file_extractions = [
            (pname, result)
            for pname, cspath in all_file_tasks
            if (result := _extract_file_data(cspath)) is not None
        ]
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(
                executor.map(
                    _extract_file_data,
                    [cspath for _, cspath in all_file_tasks],
                )
            )
        file_extractions = [
            (pname, result)
            for (pname, _), result in zip(all_file_tasks, results)
            if result is not None
        ]

    # Aggregate results (main thread)
    for project_name, ext in file_extractions:
        file_identifier_cache[ext.cs_path] = ext.identifiers
        file_namespace_cache[ext.cs_path] = ext.namespaces
        if include_db_dependencies:
            content_by_path[ext.cs_path] = ext.content
        project_types[project_name].update(ext.types)
        project_sprocs[project_name].update(ext.sprocs)
        for ns in ext.namespaces:
            project_using_namespaces[project_name].add(ns)
            project_namespace_evidence[project_name][ns].append(str(ext.cs_path))

        if captured_file_facts is not None:
            from scatter.store.graph_cache import FileFacts

            try:
                rel = str(ext.cs_path.relative_to(search_scope))
            except ValueError:
                rel = str(ext.cs_path)
            captured_file_facts[rel] = FileFacts(
                path=rel,
                project=project_name,
                types_declared=sorted(ext.types),
                namespaces_used=sorted(ext.namespaces),
                sprocs_referenced=sorted(ext.sprocs),
                content_hash=ext.content_hash,
            )

    logging.debug(
        f"Identifier cache: {len(file_identifier_cache)} files, "
        f"{sum(len(v) for v in file_identifier_cache.values())} total identifiers"
    )

    t2 = time.monotonic()
    logging.info(f"Graph build step 4 (file extraction): {t2 - t1:.1f}s")

    # Build nodes
    for project_name, meta in project_metadata.items():
        node = ProjectNode(
            path=meta["path"],
            name=project_name,
            namespace=meta["namespace"],
            framework=meta["framework"],
            project_style=meta["project_style"],
            output_type=meta["output_type"],
            file_count=len(project_cs_files.get(project_name, [])),
            type_declarations=sorted(project_types.get(project_name, set())),
            sproc_references=sorted(project_sprocs.get(project_name, set())),
            msbuild_imports=project_msbuild_imports.get(project_name, []),
        )
        graph.add_node(node)

    # Step 5: Build edges

    # 5a: project_reference edges (from .csproj ProjectReference entries)
    _build_project_reference_edges(graph, project_refs, csproj_files, project_metadata)

    t3 = time.monotonic()
    logging.info(f"Graph build step 5a (project_reference edges): {t3 - t2:.1f}s")

    # 5b: namespace_usage edges (project A uses a namespace that matches project B's namespace)
    namespace_to_project: Dict[str, str] = {}
    for pname, meta in project_metadata.items():
        proj_ns = meta.get("namespace") or meta.get("assembly_name")
        if proj_ns:
            namespace_to_project[proj_ns] = pname

    for source_project, used_namespaces in project_using_namespaces.items():
        if source_project not in graph._nodes:
            continue
        for ns in used_namespaces:
            target_project = namespace_to_project.get(ns)
            if (
                target_project
                and target_project != source_project
                and target_project in graph._nodes
            ):
                evidence = project_namespace_evidence[source_project].get(ns, [])
                graph.add_edge(
                    DependencyEdge(
                        source=source_project,
                        target=target_project,
                        edge_type="namespace_usage",
                        weight=len(evidence),
                        evidence=evidence,
                    )
                )

    t4 = time.monotonic()
    logging.info(f"Graph build step 5b (namespace_usage edges): {t4 - t3:.1f}s")

    # 5c: type_usage edges (project A references types declared in project B)
    # Build multi-owner map: a type name may exist in multiple projects
    type_to_projects: Dict[str, Set[str]] = defaultdict(set)
    for pname, types in project_types.items():
        for t in types:
            type_to_projects[t].add(pname)

    type_name_set = set(type_to_projects.keys())

    # Build reachable targets from existing edges to scope type_usage checks
    if not full_type_scan:
        reachable_targets: Dict[str, Set[str]] = defaultdict(set)
        for source, edges in graph._outgoing.items():
            for edge in edges:
                if edge.edge_type in ("project_reference", "namespace_usage"):
                    reachable_targets[source].add(edge.target)

    # Pre-compute per-file scope: which projects each file can reach via its
    # using statements. This avoids recomputing inside the hot inner loop.
    # Falls back to project-level reachable_targets when a file has no
    # namespace-matched usings (e.g., files relying on global usings declared
    # elsewhere, or generated code without explicit using statements).
    # Known limitation: misses fully-qualified type usage without a using
    # statement (e.g. new GalaxyWorks.Data.Foo()). Use full_type_scan=True
    # to bypass this scope gate entirely.
    file_scope_cache: Dict[Path, Set[str]] = {}
    if not full_type_scan:
        for cs_path, file_ns in file_namespace_cache.items():
            file_scope_cache[cs_path] = {
                namespace_to_project[ns] for ns in file_ns if ns in namespace_to_project
            }

    for source_project, cs_paths in project_cs_files.items():
        if source_project not in graph._nodes:
            continue
        # Track type usages per target project
        type_usage_evidence: Dict[str, List[str]] = defaultdict(list)
        for cs_path in cs_paths:
            file_identifiers = file_identifier_cache.get(cs_path)
            if file_identifiers is None:
                continue
            matched_types = file_identifiers & type_name_set
            if not matched_types:
                continue

            if full_type_scan:
                # No scope gate — check all projects
                for type_name in matched_types:
                    for owner_project in type_to_projects[type_name]:
                        if owner_project != source_project and owner_project in graph._nodes:
                            type_usage_evidence[owner_project].append(f"{cs_path}:{type_name}")
            else:
                # Per-file scope gate: narrow to projects this file imports
                file_reachable = file_scope_cache.get(cs_path, set())
                scope = (
                    file_reachable
                    if file_reachable
                    else reachable_targets.get(source_project, set())
                )
                if not file_reachable and scope:
                    logging.debug(
                        f"Scope gate fallback for {cs_path} (no file-level usings matched)"
                    )
                for type_name in matched_types:
                    for owner_project in type_to_projects[type_name]:
                        if (
                            owner_project != source_project
                            and owner_project in graph._nodes
                            and owner_project in scope
                        ):
                            type_usage_evidence[owner_project].append(f"{cs_path}:{type_name}")

        for target_project, evidence in type_usage_evidence.items():
            graph.add_edge(
                DependencyEdge(
                    source=source_project,
                    target=target_project,
                    edge_type="type_usage",
                    weight=len(evidence),
                    evidence=evidence,
                )
            )

    del file_identifier_cache, file_namespace_cache, file_scope_cache
    t5 = time.monotonic()
    logging.info(f"Graph build step 5c (type_usage edges): {t5 - t4:.1f}s")

    # Step 6 (optional): DB dependency scan → sproc_shared edges
    if include_db_dependencies:
        from scatter.scanners.db_scanner import add_db_edges_to_graph, scan_db_dependencies

        if content_by_path:
            cache_mb = sum(len(v) for v in content_by_path.values()) / (1024 * 1024)
            logging.info(f"Content cache: {len(content_by_path)} files, {cache_mb:.0f}MB")

        db_deps = scan_db_dependencies(
            search_scope,
            project_cs_map=dict(project_cs_files),
            content_by_path=content_by_path or None,
            max_workers=max_workers,
            chunk_size=chunk_size,
            disable_multiprocessing=disable_multiprocessing,
            exclude_patterns=exclude_patterns,
            sproc_prefixes=sproc_prefixes,
        )
        add_db_edges_to_graph(graph, db_deps)
        del content_by_path

    t6 = time.monotonic()
    if include_db_dependencies:
        logging.info(f"Graph build step 6 (DB scanner): {t6 - t5:.1f}s")
    logging.info(
        f"Built dependency graph: {graph.node_count} nodes, {graph.edge_count} edges "
        f"(total: {t6 - t0:.1f}s)"
    )

    if not capture_facts:
        return graph

    # File facts were captured inline during Step 4 — build project facts now
    from scatter.store.graph_cache import ProjectFacts

    captured_project_facts: Dict[str, "ProjectFacts"] = {}
    all_names = set(project_metadata.keys())
    for project_name, meta in project_metadata.items():
        csproj_path = meta["path"]
        content_hash = compute_content_hash(csproj_path)

        # Resolve references to project names
        ref_names = []
        for include in project_refs.get(project_name, []):
            if "$(" in include:
                continue
            try:
                ref_abs = (csproj_path.parent / include).resolve(strict=False)
                ref_name = ref_abs.stem
                if ref_name in all_names:
                    ref_names.append(ref_name)
            except OSError:
                pass

        captured_project_facts[project_name] = ProjectFacts(
            namespace=meta.get("namespace"),
            project_references=sorted(ref_names),
            csproj_content_hash=content_hash,
        )

    return graph, captured_file_facts, captured_project_facts


def _build_project_reference_edges(
    graph: DependencyGraph,
    project_refs: Dict[str, List[str]],
    csproj_files: List[Path],
    project_metadata: Dict[str, Dict[str, Any]],
) -> None:
    """Resolve ProjectReference Include paths and add edges.

    Uses os.path.normpath for string-based path resolution instead of
    Path.resolve() to avoid filesystem stat calls — critical for Docker/WSL2
    where each resolve() triggers multiple cross-bridge syscalls.
    """
    import os as _os

    # Build lookup: normalized path string -> project name
    path_to_name: Dict[str, str] = {}
    for csproj_path in csproj_files:
        name = csproj_path.stem
        if name in project_metadata:
            path_to_name[_os.path.normpath(str(csproj_path))] = name

    unresolved = []

    for source_name, ref_includes in project_refs.items():
        if source_name not in graph._nodes:
            continue
        source_dir = str(project_metadata[source_name]["path"].parent)

        for include in ref_includes:
            # Skip MSBuild property references
            if "$(" in include:
                continue
            # Normalize Windows backslashes — .csproj files authored on Windows
            # use \ in Include paths, but os.path.normpath on Linux treats \ as
            # a literal character, not a separator.
            include_posix = include.replace("\\", "/")
            ref_norm = _os.path.normpath(_os.path.join(source_dir, include_posix))
            target_name = path_to_name.get(ref_norm)

            if target_name is None:
                unresolved.append((source_name, include))
                continue

            if target_name in graph._nodes:
                graph.add_edge(
                    DependencyEdge(
                        source=source_name,
                        target=target_name,
                        edge_type="project_reference",
                        weight=1.0,
                        evidence=[include],
                    )
                )

    if unresolved:
        logging.warning(
            f"Could not resolve {len(unresolved)} project reference(s) via normpath. "
            f"First 5: {unresolved[:5]}"
        )


def _build_project_directory_index(
    csproj_paths: List[Path],
) -> Dict[Path, str]:
    """Build reverse index: directory → project_name."""
    return {csproj_path.parent: csproj_path.stem for csproj_path in csproj_paths}


_MAX_WALK_DEPTH = 64  # safety cap against symlink loops or degenerate paths


def _map_cs_to_project(
    cs_path: Path,
    project_dirs: Dict[Path, str],
) -> Optional[str]:
    """Find the closest ancestor project for a .cs file."""
    current = cs_path.parent
    for _ in range(_MAX_WALK_DEPTH):
        name = project_dirs.get(current)
        if name is not None:
            return name
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _filter_excluded(paths: List[Path], exclude_patterns: List[str]) -> List[Path]:
    """Filter paths matching any exclude pattern."""
    import fnmatch

    result = []
    for p in paths:
        p_str = str(p)
        if not any(fnmatch.fnmatch(p_str, pat) for pat in exclude_patterns):
            result.append(p)
    return result
