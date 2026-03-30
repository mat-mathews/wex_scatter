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
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Set, Tuple

if TYPE_CHECKING:
    from scatter.config import AnalysisConfig

from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.core.models import DEFAULT_CHUNK_SIZE, DEFAULT_MAX_WORKERS
from scatter.core.parallel import find_files_with_pattern_parallel
from scatter.scanners.project_scanner import (
    derive_namespace,
    parse_csproj_all_references,
)
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


def _extract_file_data(cs_path: Path, use_ast: bool = False) -> Optional[_FileExtraction]:
    """Read a .cs file and extract all relevant data. Pure function, safe for threads.

    When use_ast=True, applies tree-sitter validation to filter identifiers
    in comments/strings and confirm type declarations against the AST.
    """
    try:
        content = cs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    identifiers: Set[str]
    types: Set[str]

    if use_ast:
        from scatter.parsers.ast_validator import identifiers_in_code, validate_type_declarations

        # Capture byte positions for each identifier match
        ident_positions: Dict[str, List[int]] = {}
        for m in _IDENT_PATTERN.finditer(content):
            ident_positions.setdefault(m.group(), []).append(m.start())
        identifiers = identifiers_in_code(content, ident_positions)
        types = validate_type_declarations(content, extract_type_names_from_content(content))
    else:
        identifiers = {m.group() for m in _IDENT_PATTERN.finditer(content)}
        types = extract_type_names_from_content(content)

    return _FileExtraction(
        cs_path=cs_path,
        identifiers=identifiers,
        types=types,
        sprocs={m.group().strip("\"'") for m in _SPROC_PATTERN.finditer(content)},
        namespaces={m.group(1) for m in _USING_PATTERN.finditer(content)},
        content_hash=compute_content_hash(content),
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
):
    """Build a complete dependency graph from a codebase directory.

    If capture_facts=True, returns (graph, file_facts, project_facts) tuple
    for v2 cache persistence. Otherwise returns just the graph.

    Args:
        analysis_config: Optional AnalysisConfig. When parser_mode="hybrid",
            enables tree-sitter AST validation to filter regex false positives.
    """
    if exclude_patterns is None:
        exclude_patterns = ["*/bin/*", "*/obj/*", "*/temp_test_data/*"]

    # Resolve AST mode
    use_ast = False
    requested_mode = analysis_config.parser_mode if analysis_config else "regex"
    if requested_mode == "hybrid":
        from scatter.parsers.ast_validator import is_hybrid_available

        if is_hybrid_available():
            use_ast = True
            logging.info("Hybrid parser mode: tree-sitter AST validation enabled")
        else:
            logging.warning(
                "Hybrid parser mode requested but tree-sitter is not installed. "
                "Install with: uv sync --extra ast. Falling back to regex-only."
            )

    graph = DependencyGraph()

    # Step 1: Discover all .csproj files
    all_csproj = find_files_with_pattern_parallel(
        search_scope,
        "*.csproj",
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing,
    )

    # Filter excluded paths
    csproj_files = _filter_excluded(all_csproj, exclude_patterns)
    logging.info(f"Found {len(csproj_files)} .csproj files")

    # Step 2: Parse each .csproj → extract metadata
    project_metadata: Dict[str, Dict[str, Any]] = {}
    project_refs: Dict[str, List[str]] = {}  # project_name -> list of ref include paths

    for csproj_path in csproj_files:
        parsed = parse_csproj_all_references(csproj_path)
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

    # Step 3: Discover .cs files and map to parent projects via reverse index
    all_cs = find_files_with_pattern_parallel(
        search_scope,
        "*.cs",
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing,
    )
    cs_files = _filter_excluded(all_cs, exclude_patterns)
    logging.info(f"Found {len(cs_files)} .cs files")

    project_dir_index = _build_project_directory_index(csproj_files)
    project_cs_files: Dict[str, List[Path]] = defaultdict(list)

    for cs_path in cs_files:
        mapped_name = _map_cs_to_project(cs_path, project_dir_index)
        if mapped_name:
            project_cs_files[mapped_name].append(cs_path)

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

    # Flatten project→files for dispatch
    all_file_tasks: List[Tuple[str, Path]] = [
        (pname, cspath) for pname, cs_paths in project_cs_files.items() for cspath in cs_paths
    ]

    extract_fn = partial(_extract_file_data, use_ast=use_ast)

    if disable_multiprocessing or len(all_file_tasks) < 100:
        file_extractions = [
            (pname, result)
            for pname, cspath in all_file_tasks
            if (result := extract_fn(cspath)) is not None
        ]
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(
                executor.map(
                    extract_fn,
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
        )
        graph.add_node(node)

    # Step 5: Build edges

    # 5a: project_reference edges (from .csproj ProjectReference entries)
    _build_project_reference_edges(graph, project_refs, csproj_files, project_metadata)

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
            for type_name in matched_types:
                for owner_project in type_to_projects[type_name]:
                    if (
                        owner_project != source_project
                        and owner_project in graph._nodes
                        and (
                            full_type_scan
                            or owner_project in reachable_targets.get(source_project, set())
                        )
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

    del file_identifier_cache

    # Step 6 (optional): DB dependency scan → sproc_shared edges
    if include_db_dependencies:
        from scatter.scanners.db_scanner import add_db_edges_to_graph, scan_db_dependencies

        db_deps = scan_db_dependencies(
            search_scope,
            project_cs_map=dict(project_cs_files),
            max_workers=max_workers,
            chunk_size=chunk_size,
            disable_multiprocessing=disable_multiprocessing,
            exclude_patterns=exclude_patterns,
            sproc_prefixes=sproc_prefixes,
        )
        add_db_edges_to_graph(graph, db_deps)

    logging.info(f"Built dependency graph: {graph.node_count} nodes, {graph.edge_count} edges")

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
    """Resolve ProjectReference Include paths and add edges."""
    # Build a lookup from resolved path to project name
    path_to_name: Dict[Path, str] = {}
    for csproj_path in csproj_files:
        name = csproj_path.stem
        if name in project_metadata:
            try:
                path_to_name[csproj_path.resolve()] = name
            except OSError:
                path_to_name[csproj_path] = name

    for source_name, ref_includes in project_refs.items():
        if source_name not in graph._nodes:
            continue
        source_path = project_metadata[source_name]["path"]

        for include in ref_includes:
            # Skip MSBuild property references
            if "$(" in include:
                continue
            try:
                ref_abs = (source_path.parent / include).resolve(strict=False)
                target_name = path_to_name.get(ref_abs)
                if target_name and target_name in graph._nodes:
                    graph.add_edge(
                        DependencyEdge(
                            source=source_name,
                            target=target_name,
                            edge_type="project_reference",
                            weight=1.0,
                            evidence=[include],
                        )
                    )
            except OSError as e:
                logging.debug(f"Could not resolve reference {include}: {e}")


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
