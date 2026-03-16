"""Consumer detection pipeline — finds projects that consume a target project."""
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Union

from scatter.core.models import (
    DEFAULT_MAX_WORKERS, DEFAULT_CHUNK_SIZE,
    FilterStage, FilterPipeline,
    STAGE_DISCOVERY, STAGE_PROJECT_REFERENCE, STAGE_NAMESPACE,
    STAGE_CLASS, STAGE_METHOD,
)
from scatter.core.parallel import (
    find_files_with_pattern_parallel,
    parse_csproj_files_parallel,
    analyze_cs_files_parallel,
)

if TYPE_CHECKING:
    from scatter.core.graph import DependencyGraph


def _lookup_consumers_from_graph(
    graph: "DependencyGraph",
    target_csproj_path: Path,
) -> Optional[Dict[Path, Dict[str, Union[str, List[Path]]]]]:
    """Stages 1-2 via graph reverse lookup. Returns None if target not in graph.

    Filters to project_reference edges only — the graph has 4 edge types
    (project_reference, namespace_usage, type_usage, sproc_shared) but
    stage 2 semantics only check <ProjectReference> in .csproj XML.
    Using all edge types would widen the consumer set beyond what the
    filesystem path finds, causing correctness divergence.
    """
    target_name = target_csproj_path.stem

    # Target not in graph → caller should fall back to filesystem.
    # This handles stale cache, scope mismatch, or new projects.
    if graph.get_node(target_name) is None:
        logging.debug(f"Target '{target_name}' not found in graph, falling back to filesystem.")
        return None

    direct_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    for edge in graph.get_edges_to(target_name):
        if edge.edge_type == "project_reference":
            node = graph.get_node(edge.source)
            if node:
                direct_consumers[node.path.resolve()] = {
                    'consumer_name': edge.source,
                    'relevant_files': []
                }
    return direct_consumers


def _discover_consumers_from_filesystem(
    target_csproj_path: Path,
    search_scope_path: Path,
    max_workers: int,
    chunk_size: int,
    disable_multiprocessing: bool,
    csproj_analysis_chunk_size: int,
) -> Tuple[Dict[Path, Dict[str, Union[str, List[Path]]]], int, List[Path]]:
    """Stages 1-2 via filesystem scan + XML parsing.

    Returns (direct_consumers, total_scanned, potential_consumers).
    Raises OSError if the search scope cannot be scanned.
    """
    all_csproj_files = find_files_with_pattern_parallel(
        search_scope_path, '*.csproj',
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing
    )
    logging.debug(f'Found {len(all_csproj_files)} total .csproj files in scope.')
    potential_consumers = [
        p.resolve() for p in all_csproj_files if p.resolve() != target_csproj_path
    ]
    logging.debug(f"Found {len(potential_consumers)} potential consumer project(s) to check.")

    # --- step 2: identify direct consumers (parallel csproj parsing) ---
    logging.debug("Checking for direct project references to target...")
    csproj_parse_results = parse_csproj_files_parallel(
        potential_consumers,
        target_csproj_path,
        max_workers=max_workers,
        csproj_analysis_chunk_size=csproj_analysis_chunk_size,
        disable_multiprocessing=disable_multiprocessing
    )

    direct_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    for consumer_csproj_abs in potential_consumers:
        result = csproj_parse_results.get(str(consumer_csproj_abs))
        if result and result['is_consumer']:
            direct_consumers[consumer_csproj_abs] = {
                'consumer_name': result['consumer_name'],
                'relevant_files': []
            }

    logging.debug(f"Found {len(direct_consumers)} direct consumer(s) via ProjectReference.")
    return direct_consumers, len(all_csproj_files), potential_consumers


def find_consumers(
    target_csproj_path: Path,
    search_scope_path: Path,
    target_namespace: str,
    class_name: Optional[str],
    method_name: Optional[str],
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
    csproj_analysis_chunk_size: int = 25,
    graph: Optional["DependencyGraph"] = None,
) -> Tuple[List[Dict[str, Union[Path, str, List[Path]]]], FilterPipeline]:
    """
    Finds consuming projects based on ProjectReference, namespace usage,
    and optional class/method usage checks. Tracks the specific files causing matches.

    When ``graph`` is provided, stages 1-2 (discovery + project reference) use
    O(1) graph reverse lookup instead of filesystem scanning. Stages 3-5
    (namespace, class, method) still run on the candidate set.

    Returns a tuple of (consumer_results, filter_pipeline).
    """
    logging.info(f"-- Analyzing consumers for target: {target_csproj_path.name} (Namespace: {target_namespace}) --")
    if class_name: logging.info(f"     Filtering for type/class: {class_name}")
    if method_name: logging.info(f"     Filtering for method: {method_name}")

    pipeline = FilterPipeline(
        search_scope=str(search_scope_path),
        total_projects_scanned=0,
        total_files_scanned=0,
        target_project=target_csproj_path.stem,
        target_namespace=target_namespace,
        class_filter=class_name,
        method_filter=method_name,
    )

    direct_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    namespace_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    class_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    method_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    cs_file_cache: Dict[Path, List[Path]] = {}

    # --- stages 1-2: discover consumers via graph or filesystem ---
    used_graph = False
    if graph is not None:
        graph_result = _lookup_consumers_from_graph(graph, target_csproj_path)
        if graph_result is not None:
            direct_consumers = graph_result
            used_graph = True
            logging.info(f"Using graph-accelerated consumer lookup ({len(direct_consumers)} direct consumer(s)).")
            pipeline.total_projects_scanned = graph.node_count
            pipeline.stages.append(FilterStage(
                name=STAGE_DISCOVERY,
                input_count=graph.node_count,
                output_count=graph.node_count - 1,
                source="graph",
            ))
            pipeline.stages.append(FilterStage(
                name=STAGE_PROJECT_REFERENCE,
                input_count=graph.node_count - 1,
                output_count=len(direct_consumers),
                source="graph",
            ))

    if not used_graph:
        # Filesystem path: stages 1-2 as before
        try:
            direct_consumers, total_scanned, potential_consumers = _discover_consumers_from_filesystem(
                target_csproj_path, search_scope_path,
                max_workers, chunk_size, disable_multiprocessing,
                csproj_analysis_chunk_size,
            )
            pipeline.total_projects_scanned = total_scanned
            pipeline.stages.append(FilterStage(
                name=STAGE_DISCOVERY,
                input_count=total_scanned,
                output_count=len(potential_consumers),
            ))
            pipeline.stages.append(FilterStage(
                name=STAGE_PROJECT_REFERENCE,
                input_count=len(potential_consumers),
                output_count=len(direct_consumers),
            ))
        except OSError as e:
            logging.error(f"Error scanning search scope '{search_scope_path}': {e}")
            return [], pipeline

    if not direct_consumers:
        logging.info("No projects directly referencing the target were found.")
        return [], pipeline

    # --- step 3: filter consumers by namespace ---
    if not target_namespace or target_namespace.startswith("NAMESPACE_ERROR_"):
        logging.warning(f"Target namespace is unreliable or missing ('{target_namespace}'). Skipping namespace usage check. All direct consumers will be considered.")
        namespace_consumers = direct_consumers
    else:
        logging.debug(f"Checking {len(direct_consumers)} direct consumers for 'using {target_namespace};' statements...")
        using_pattern = re.compile(rf"(?:^|;|\{{)\s*(?:global\s+)?using\s+{re.escape(target_namespace)}(?:\.[A-Za-z0-9_.]+)?\s*;", re.MULTILINE)

        all_cs_files_for_analysis = []
        consumer_to_files_map = {}

        for consumer_path_abs, consumer_data in direct_consumers.items():
            consumer_dir_abs = consumer_path_abs.parent

            if consumer_dir_abs not in cs_file_cache:
                try:
                    cs_file_cache[consumer_dir_abs] = find_files_with_pattern_parallel(
                        consumer_dir_abs, '*.cs',
                        max_workers=max_workers,
                        chunk_size=chunk_size,
                        disable_multiprocessing=disable_multiprocessing
                    )
                    logging.debug(f"Found {len(cs_file_cache[consumer_dir_abs])} C# files in {consumer_dir_abs}")
                except OSError as e:
                    logging.warning(f"Could not list .cs files in {consumer_dir_abs} for project {consumer_data['consumer_name']}: {e}")
                    cs_file_cache[consumer_dir_abs] = []

            consumer_files = cs_file_cache[consumer_dir_abs]
            consumer_to_files_map[consumer_path_abs] = consumer_files
            all_cs_files_for_analysis.extend(consumer_files)

        pipeline.total_files_scanned += len(all_cs_files_for_analysis)

        if all_cs_files_for_analysis:
            analysis_config = {
                'analysis_type': 'namespace',
                'target_namespace': target_namespace,
                'using_pattern': using_pattern
            }

            analysis_results = analyze_cs_files_parallel(
                all_cs_files_for_analysis,
                analysis_config,
                max_workers=max_workers,
                cs_analysis_chunk_size=cs_analysis_chunk_size,
                disable_multiprocessing=disable_multiprocessing
            )

            for consumer_path_abs, consumer_data in direct_consumers.items():
                namespace_match_files = []

                for cs_file_path in consumer_to_files_map.get(consumer_path_abs, []):
                    file_result = analysis_results.get(cs_file_path)
                    if file_result:
                        if file_result.get('error'):
                            logging.warning(f"Could not read {cs_file_path.name} in {consumer_data['consumer_name']} for namespace check: {file_result['error']}")
                        elif file_result.get('has_match'):
                            namespace_match_files.append(cs_file_path)

                if namespace_match_files:
                    consumer_data['relevant_files'] = namespace_match_files
                    namespace_consumers[consumer_path_abs] = consumer_data
                    logging.debug(f"  Namespace used in {consumer_data['consumer_name']} (Files: {[f.name for f in namespace_match_files]})")

        logging.debug(f"Found {len(namespace_consumers)} consumer(s) using namespace '{target_namespace}'.")

    pipeline.stages.append(FilterStage(
        name=STAGE_NAMESPACE,
        input_count=len(direct_consumers),
        output_count=len(namespace_consumers),
    ))

    # --- helper to format results ---
    def format_results(consumer_dict: Dict[Path, Dict[str, Union[str, List[Path]]]]) -> List[Dict[str, Union[Path, str, List[Path]]]]:
        results = []
        for path, data in consumer_dict.items():
            results.append({
                'consumer_path': path,
                'consumer_name': data['consumer_name'],
                'relevant_files': data['relevant_files']
            })
        return results

    if not namespace_consumers:
        logging.info("No consuming projects using the target namespace were found (or check skipped).")
        if not class_name:
            return format_results(direct_consumers), pipeline
        return [], pipeline
    if not class_name:
        return format_results(namespace_consumers), pipeline

    # --- step 4: filter by class/type usage ---
    logging.debug(f"Checking {len(namespace_consumers)} namespace consumers for usage of type '{class_name}'...")

    class_pattern = re.compile(rf"\b{re.escape(class_name)}\b")

    all_relevant_files = []
    consumer_to_relevant_files_map = {}

    for consumer_path_abs, consumer_data in namespace_consumers.items():
        files_to_check = consumer_data['relevant_files']
        consumer_to_relevant_files_map[consumer_path_abs] = files_to_check
        all_relevant_files.extend(files_to_check)
        logging.debug(f"  Checking type '{class_name}' in {len(files_to_check)} relevant files for {consumer_data['consumer_name']}...")

    pipeline.total_files_scanned += len(all_relevant_files)

    if all_relevant_files:
        analysis_config = {
            'analysis_type': 'class',
            'class_name': class_name,
            'class_pattern': class_pattern
        }

        analysis_results = analyze_cs_files_parallel(
            all_relevant_files,
            analysis_config,
            max_workers=max_workers,
            cs_analysis_chunk_size=cs_analysis_chunk_size,
            disable_multiprocessing=disable_multiprocessing
        )

        for consumer_path_abs, consumer_data in namespace_consumers.items():
            class_match_files = []

            for cs_file_path in consumer_to_relevant_files_map.get(consumer_path_abs, []):
                file_result = analysis_results.get(cs_file_path)
                if file_result:
                    if file_result.get('error'):
                        logging.warning(f"Could not read {cs_file_path.name} in {consumer_data['consumer_name']} for type check: {file_result['error']}")
                    elif file_result.get('has_match'):
                        class_match_files.append(cs_file_path)

            if class_match_files:
                consumer_data['relevant_files'] = class_match_files
                class_consumers[consumer_path_abs] = consumer_data
                logging.debug(f"    Type '{class_name}' used in {consumer_data['consumer_name']} (Files: {[f.name for f in class_match_files]})")

    logging.debug(f"Found {len(class_consumers)} consumer(s) potentially using type '{class_name}'.")

    pipeline.stages.append(FilterStage(
        name=STAGE_CLASS,
        input_count=len(namespace_consumers),
        output_count=len(class_consumers),
    ))

    if not class_consumers:
        logging.info(f"No consuming projects potentially using type '{class_name}' were found.")
        return [], pipeline
    if not method_name:
        return format_results(class_consumers), pipeline

    # --- step 5: filter by method (parallel) ---
    logging.debug(f"Checking {len(class_consumers)} class consumers for potential usage of method '{method_name}'...")

    method_pattern = re.compile(rf"\.\s*{re.escape(method_name)}\s*\(")

    all_method_files = []
    file_to_consumer_map: Dict[Path, Path] = {}
    for consumer_path_abs, consumer_data in class_consumers.items():
        for cs_file_abs in consumer_data['relevant_files']:
            all_method_files.append(cs_file_abs)
            file_to_consumer_map[cs_file_abs] = consumer_path_abs

    logging.debug(f"  Scanning {len(all_method_files)} files across {len(class_consumers)} consumers for method '{method_name}'...")

    pipeline.total_files_scanned += len(all_method_files)

    method_analysis_config = {
        'analysis_type': 'method',
        'method_pattern': method_pattern
    }

    method_results = analyze_cs_files_parallel(
        all_method_files,
        method_analysis_config,
        max_workers=max_workers,
        cs_analysis_chunk_size=cs_analysis_chunk_size,
        disable_multiprocessing=disable_multiprocessing
    )

    for cs_file_abs, result in method_results.items():
        if result.get('error'):
            consumer_path_abs = file_to_consumer_map[cs_file_abs]
            consumer_name = class_consumers[consumer_path_abs]['consumer_name']
            logging.warning(f"Could not read {cs_file_abs.name} in {consumer_name} for method check: {result['error']}")
            continue
        if result['has_match']:
            consumer_path_abs = file_to_consumer_map[cs_file_abs]
            consumer_data = class_consumers[consumer_path_abs]
            if consumer_path_abs not in method_consumers:
                method_consumers[consumer_path_abs] = {
                    'consumer_name': consumer_data['consumer_name'],
                    'relevant_files': []
                }
            method_consumers[consumer_path_abs]['relevant_files'].append(cs_file_abs)

    for consumer_path_abs, consumer_data in method_consumers.items():
        logging.debug(f"    Method '{method_name}' used in {consumer_data['consumer_name']} (Files: {[f.name for f in consumer_data['relevant_files']]})")

    logging.debug(f"Found {len(method_consumers)} consumer(s) potentially calling method '{method_name}'.")

    pipeline.stages.append(FilterStage(
        name=STAGE_METHOD,
        input_count=len(class_consumers),
        output_count=len(method_consumers),
    ))

    if not method_consumers:
        logging.info(f"No consuming projects potentially calling method '{method_name}' were found.")
        return [], pipeline

    return format_results(method_consumers), pipeline
