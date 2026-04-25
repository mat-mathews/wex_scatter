"""Analysis engines, data containers, and shared helpers for Scatter.

This module contains the core analysis logic that mode handlers delegate to.
Each ``run_*_analysis`` function accepts a :class:`ModeContext`, calls into
scanners/analyzers, and returns a :class:`ModeResult`.  They are pure business
logic — no CLI arg parsing, no ``sys.exit()``, no output formatting.

See ``modes/setup.py:build_mode_context()`` for ModeContext construction.
"""

import logging
import types
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set

if TYPE_CHECKING:
    from scatter.analyzers.graph_enrichment import GraphContext

from scatter.ai.base import AIProvider
from scatter.config import ScatterConfig
from scatter.core.models import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_CHUNK_SIZE,
    ConsumerResult,
    FilterPipeline,
    PropsImpact,
    RawConsumerDict,
)


@dataclass
class ModeContext:
    """Resolved, typed fields that mode handlers need — no raw ``args``."""

    search_scope: Path
    config: ScatterConfig
    pipeline_map: Dict[str, str]
    solution_file_cache: List[Path]
    batch_job_map: Dict[str, List[str]]
    ai_provider: Optional[AIProvider]
    repo_path: Optional[Path] = None
    graph_ctx: Optional["GraphContext"] = None  # mutable, updated by _apply_graph_enrichment
    solution_index: Optional[Dict] = None
    graph_enriched: bool = False  # mutable, updated by _apply_graph_enrichment

    # Resolved from args — only fields mode handlers actually read
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    target_namespace: Optional[str] = None
    summarize_consumers: bool = False
    max_workers: int = DEFAULT_MAX_WORKERS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    disable_multiprocessing: bool = False
    cs_analysis_chunk_size: int = 50
    csproj_analysis_chunk_size: int = 25
    no_graph: bool = False
    discovered_files: Optional[Dict] = None


@dataclass
class ModeResult:
    """Return type for legacy mode handlers (git, target, sproc)."""

    all_results: List[ConsumerResult] = field(default_factory=list)
    filter_pipeline: Optional[FilterPipeline] = None
    graph_enriched: bool = False
    props_impacts: List[PropsImpact] = field(default_factory=list)


def _summarize_consumer_files(
    final_consumers_data: List[RawConsumerDict],
    all_results: List[ConsumerResult],
    ai_provider,
    search_scope: Path,
    results_start_index: int,
) -> None:
    """Summarize relevant files for each consumer and inject into result dicts.

    Reads each consumer's relevant_files, sends content to the AI provider
    for summarization, and populates the 'ConsumerFileSummaries' field in
    the corresponding result dicts (which were appended by the bridge call).

    Args:
        final_consumers_data: Consumer dicts from find_consumers(), each with
            'consumer_name', 'consumer_path', and 'relevant_files'.
        all_results: The results list that the bridge already appended to.
        ai_provider: An AIProvider instance that supports SUMMARIZATION.
        search_scope: Absolute path used to compute relative file paths.
        results_start_index: Index into all_results where this batch starts,
            so we can match consumers to their result dicts.
    """
    from scatter.ai.base import AITaskType, MAX_SUMMARIZATION_CHARS, SUMMARIZATION_PROMPT_TEMPLATE

    if not ai_provider or not final_consumers_data:
        return

    if not ai_provider.supports(AITaskType.SUMMARIZATION):
        logging.warning("AI provider does not support summarization. Skipping.")
        return

    # Build a map keyed by consumer_path (absolute) to avoid stem collisions
    consumer_files_map: Dict[Path, List[Path]] = {}
    for consumer_info in final_consumers_data:
        consumer_path = consumer_info["consumer_path"]
        files = consumer_info.get("relevant_files", [])
        if files:
            consumer_files_map[consumer_path] = files

    if not consumer_files_map:
        logging.debug("No relevant files found for any consumer. Skipping summarization.")
        return

    total_files = sum(len(f) for f in consumer_files_map.values())
    logging.info(
        f"Summarizing {total_files} file(s) across {len(consumer_files_map)} consumer(s)..."
    )

    # Summarize each file and build summaries dict per consumer path
    summaries_by_path: Dict[Path, Dict[str, str]] = defaultdict(dict)
    file_counter = 0
    for consumer_path, file_paths in consumer_files_map.items():
        for file_path in file_paths:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logging.warning(f"Could not read {file_path}: {e}")
                continue

            if not content.strip():
                continue

            try:
                rel_path = file_path.relative_to(search_scope).as_posix()
            except ValueError:
                rel_path = file_path.name

            prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
                filename=file_path.name,
                code=content[:MAX_SUMMARIZATION_CHARS],
            )

            try:
                result = ai_provider.analyze(prompt, "", AITaskType.SUMMARIZATION)
                file_counter += 1
                if result and result.response:
                    summaries_by_path[consumer_path][rel_path] = result.response
                    logging.info(f"  Summarized {file_counter}/{total_files}: {rel_path}")
            except Exception as e:
                file_counter += 1
                logging.warning(f"Summarization failed for {rel_path}: {e}")

    # Inject summaries into ConsumerResult objects by matching consumer_project_path
    for result in all_results[results_start_index:]:
        consumer_rel = result.consumer_project_path
        for consumer_abs, summaries in summaries_by_path.items():
            try:
                expected_rel = consumer_abs.relative_to(search_scope).as_posix()
            except ValueError:
                expected_rel = consumer_abs.as_posix()
            if consumer_rel == expected_rel:
                result.consumer_file_summaries = summaries
                break


def _ensure_graph_context(ctx: ModeContext) -> None:
    """Build graph on first run if not already loaded.

    Idempotent: returns immediately if graph_ctx is already set, --no-graph
    is passed, or search_scope is not available. On failure, logs at DEBUG
    and leaves ctx unchanged.

    Mutates ctx.graph_ctx and ctx.graph_enriched in place.
    """
    if ctx.graph_ctx is not None or ctx.no_graph:
        return
    from scatter.analyzers.graph_enrichment import build_graph_context

    # build_graph_context expects an object with a disable_multiprocessing attribute.
    # We use SimpleNamespace instead of passing the full args namespace to avoid
    # pulling CLI concerns into analysis code.
    shim = types.SimpleNamespace(disable_multiprocessing=ctx.disable_multiprocessing)

    try:
        logging.info("Building dependency graph cache for future acceleration...")
        graph_ctx = build_graph_context(ctx.search_scope, ctx.config, shim)
        if graph_ctx:
            ctx.graph_ctx = graph_ctx
            ctx.graph_enriched = True
        else:
            logging.debug("First-run graph build returned no context (no .csproj files in scope?)")
    except Exception as e:
        logging.debug(f"First-run graph build failed (non-fatal): {e}")


def _apply_graph_enrichment(all_results: List[ConsumerResult], ctx: ModeContext) -> None:
    """Build graph context if needed, enrich results in place.

    Mutates ctx.graph_ctx and ctx.graph_enriched.
    """
    _ensure_graph_context(ctx)
    if ctx.graph_ctx and all_results:
        from scatter.analyzers.graph_enrichment import enrich_legacy_results

        enrich_legacy_results(all_results, ctx.graph_ctx)


def _build_import_reverse_index(graph) -> Dict[str, List[str]]:
    """Build {import_path: [project_names]} from graph nodes in a single pass.

    O(nodes) — iterates all nodes once regardless of how many config files
    changed. Normalizes paths as a safety net (PR 1's graph builder already
    stores forward-slash paths, but this guards against cross-platform edge cases).
    """
    index: Dict[str, List[str]] = defaultdict(list)
    for node in graph.get_all_nodes():
        for imp in node.msbuild_imports:
            normalized = imp.replace("\\", "/")
            index[normalized].append(node.name)
    return dict(index)


def apply_impact_graph_enrichment(impact_report, ctx: ModeContext) -> None:
    """Build graph context if needed, enrich impact consumers in place.

    Mutates ctx.graph_ctx and ctx.graph_enriched.
    """
    _ensure_graph_context(ctx)
    if ctx.graph_ctx:
        from scatter.analyzers.graph_enrichment import enrich_consumers

        for ti in impact_report.targets:
            enrich_consumers(ti.consumers, ctx.graph_ctx)


def run_target_analysis(ctx: ModeContext, target_csproj: Path) -> ModeResult:
    """Run target-project analysis mode.

    Finds consumers of a specific .csproj project within the search scope.
    """
    from scatter.scanners.project_scanner import derive_namespace
    from scatter.analyzers.consumer_analyzer import find_consumers
    from scatter.compat.v1_bridge import _build_consumer_results

    logging.info("\n--- Running Target Project Analysis Mode ---")
    target_project_name = target_csproj.stem
    logging.info(f"Analyzing target project: {target_project_name} ({target_csproj})")

    logging.info("Step 1: Determining target namespace...")
    target_namespace_str = ctx.target_namespace
    if not target_namespace_str:
        target_namespace_str = derive_namespace(target_csproj)

    if not target_namespace_str:
        raise ValueError(
            "Could not derive target namespace. Please specify it using --target-namespace."
        )
    logging.info(f"Using target namespace: '{target_namespace_str}'")

    logging.info("\nStep 2: Analyzing consumers...")
    final_consumers_data, filter_pipeline = find_consumers(
        target_csproj,
        ctx.search_scope,
        target_namespace_str,
        ctx.class_name,
        ctx.method_name,
        max_workers=ctx.max_workers,
        chunk_size=ctx.chunk_size,
        disable_multiprocessing=ctx.disable_multiprocessing,
        cs_analysis_chunk_size=ctx.cs_analysis_chunk_size,
        csproj_analysis_chunk_size=ctx.csproj_analysis_chunk_size,
        graph=ctx.graph_ctx.graph if ctx.graph_ctx else None,
        analysis_config=ctx.config.analysis,
    )

    all_results: List[ConsumerResult] = []

    if final_consumers_data:
        logging.info(
            f"Found {len(final_consumers_data)} consumer(s) matching criteria for target '{target_project_name}'."
        )
        trigger_level = "N/A (Project Reference)"
        if ctx.method_name and ctx.class_name:
            trigger_level = f"{ctx.class_name}.{ctx.method_name}"
        elif ctx.class_name:
            trigger_level = ctx.class_name

        try:
            target_rel_path_for_report = target_csproj.relative_to(ctx.search_scope).as_posix()
        except ValueError:
            target_rel_path_for_report = target_csproj.as_posix()

        results_before = len(all_results)
        _build_consumer_results(
            target_project_name=target_project_name,
            target_project_rel_path_str=target_rel_path_for_report,
            triggering_info=trigger_level,
            final_consumers_data=final_consumers_data,
            all_results_list=all_results,
            pipeline_map_dict=ctx.pipeline_map,
            solution_file_cache=ctx.solution_file_cache,
            batch_job_map=ctx.batch_job_map,
            search_scope_path_abs=ctx.search_scope,
            solution_index=ctx.solution_index,
        )

        if ctx.summarize_consumers and ctx.ai_provider:
            _summarize_consumer_files(
                final_consumers_data,
                all_results,
                ctx.ai_provider,
                ctx.search_scope,
                results_before,
            )
    else:
        logging.info(
            f"No consuming projects matching the criteria were found for target '{target_project_name}'."
        )

    _apply_graph_enrichment(all_results, ctx)

    return ModeResult(
        all_results=all_results,
        filter_pipeline=filter_pipeline,
        graph_enriched=ctx.graph_enriched,
    )


def run_git_analysis(
    ctx: ModeContext,
    repo_path: Path,
    branch_name: str,
    base_branch: str,
    enable_hybrid: bool,
) -> ModeResult:
    """Run git-branch analysis mode.

    Compares *branch_name* against *base_branch*, extracts type declarations
    from changed C# files, and finds consumers of those types.
    """
    from scatter.analyzers.git_analyzer import analyze_branch_changes, get_diff_for_file
    from scatter.scanners.type_scanner import extract_type_names_from_content
    from scatter.scanners.project_scanner import derive_namespace
    from scatter.analyzers.consumer_analyzer import find_consumers
    from scatter.compat.v1_bridge import _build_consumer_results

    logging.info("\n--- Running Git Branch Analysis Mode ---")
    logging.info(
        f"Comparing branch '{branch_name}' against base '{base_branch}' in repo '{repo_path}'"
    )

    logging.info("Step 1: Analyzing Git changes...")
    branch_changes = analyze_branch_changes(str(repo_path), branch_name, base_branch)
    changed_projects_dict = branch_changes.project_changes

    all_results: List[ConsumerResult] = []
    filter_pipeline: Optional[FilterPipeline] = None

    if not changed_projects_dict:
        logging.info("No projects with changed C# files found. Exiting.")
    else:
        logging.info("\nStep 2: Extracting type declarations from changed C# files...")
        types_by_project: Dict[str, Set[str]] = defaultdict(set)
        files_processed_count = 0
        types_extracted_count = 0

        for proj_rel_path_str, cs_rel_paths_str in changed_projects_dict.items():
            logging.debug(f"Processing project for type extraction: {proj_rel_path_str}")
            project_types: Set[str] = set()
            for cs_rel_path_str in cs_rel_paths_str:
                cs_abs_path = (repo_path / cs_rel_path_str).resolve()
                files_processed_count += 1
                logging.debug(f"   Reading file: {cs_abs_path}")
                if cs_abs_path.is_file():
                    try:
                        content = cs_abs_path.read_text(encoding="utf-8", errors="ignore")
                        extracted = None

                        if enable_hybrid and ctx.ai_provider:
                            diff_text = get_diff_for_file(
                                str(repo_path),
                                cs_rel_path_str,
                                branch_name,
                                base_branch,
                            )
                            if diff_text:
                                extracted = ctx.ai_provider.extract_affected_symbols(
                                    content,
                                    diff_text,
                                    cs_rel_path_str,
                                )
                                if extracted is None:
                                    logging.warning(
                                        f"LLM analysis failed for {cs_rel_path_str}, "
                                        f"falling back to regex extraction."
                                    )
                                    extracted = extract_type_names_from_content(content)
                            else:
                                logging.debug(
                                    f"No diff found for {cs_rel_path_str}, using regex extraction."
                                )
                                extracted = extract_type_names_from_content(content)
                        else:
                            extracted = extract_type_names_from_content(content)

                        if extracted:
                            logging.debug(
                                f"     Found types in {cs_rel_path_str}: {', '.join(extracted)}"
                            )
                            project_types.update(extracted)
                    except OSError as e:
                        logging.warning(f"Could not read C# file {cs_abs_path}: {e}")
                else:
                    logging.warning(
                        f"Changed C# file not found on disk (might be deleted/moved): {cs_abs_path}"
                    )

            if project_types:
                types_by_project[proj_rel_path_str] = project_types
                types_extracted_count += len(project_types)

        logging.info(f"Processed {files_processed_count} changed C# files.")
        if not types_by_project:
            logging.info(
                "No type declarations found in the changed files. "
                "Cannot perform type-based consumer analysis."
            )
        else:
            logging.info(
                f"Found {types_extracted_count} unique type declaration(s) "
                f"across {len(types_by_project)} project(s)."
            )

            logging.info("\nStep 3: Analyzing consumers...")
            processed_targets_count = 0
            for target_project_rel_path_str, extracted_types in types_by_project.items():
                processed_targets_count += 1
                target_csproj_abs = (repo_path / target_project_rel_path_str).resolve()
                target_project_name = target_csproj_abs.stem

                logging.info(
                    f"\n--- Analyzing Target Project "
                    f"{processed_targets_count}/{len(types_by_project)}: "
                    f"{target_project_name} ({target_project_rel_path_str}) ---"
                )

                if not target_csproj_abs.is_file():
                    logging.warning(
                        f"Target project file '{target_csproj_abs}' not found on disk. Skipping."
                    )
                    continue

                target_namespace_str = derive_namespace(target_csproj_abs)
                if not target_namespace_str:
                    logging.warning(
                        f"Could not derive namespace for {target_project_name}. "
                        f"Consumer analysis may be incomplete."
                    )
                    target_namespace_str = f"NAMESPACE_ERROR_{target_project_name}"

                types_to_analyze: Set[str]
                if ctx.class_name:
                    if ctx.class_name in extracted_types:
                        types_to_analyze = {ctx.class_name}
                        logging.info(
                            f"Filtering analysis to explicitly provided type "
                            f"(found in changes): '{ctx.class_name}'"
                        )
                    else:
                        logging.info(
                            f"Explicitly provided type '{ctx.class_name}' "
                            f"was NOT found in changed files. Skipping."
                        )
                        types_to_analyze = set()
                else:
                    types_to_analyze = extracted_types
                    logging.info(
                        f"Analyzing consumers for {len(types_to_analyze)} types "
                        f"detected in changed files: "
                        f"{', '.join(sorted(types_to_analyze))}"
                    )

                if not types_to_analyze:
                    continue

                for type_name_to_check in sorted(list(types_to_analyze)):
                    logging.info(f"   Checking for consumers of type: '{type_name_to_check}'...")

                    method_filter = (
                        ctx.method_name if ctx.class_name == type_name_to_check else None
                    )
                    if method_filter:
                        logging.info(f"     (Including method filter: '{method_filter}')")

                    final_consumers_data, _pipeline = find_consumers(
                        target_csproj_abs,
                        ctx.search_scope,
                        target_namespace_str,
                        type_name_to_check,
                        method_filter,
                        max_workers=ctx.max_workers,
                        chunk_size=ctx.chunk_size,
                        disable_multiprocessing=ctx.disable_multiprocessing,
                        cs_analysis_chunk_size=ctx.cs_analysis_chunk_size,
                        csproj_analysis_chunk_size=ctx.csproj_analysis_chunk_size,
                        graph=ctx.graph_ctx.graph if ctx.graph_ctx else None,
                        analysis_config=ctx.config.analysis,
                    )

                    # Keep the first pipeline that produced results; fall back to last
                    if filter_pipeline is None or final_consumers_data:
                        filter_pipeline = _pipeline

                    if final_consumers_data:
                        try:
                            target_proj_rel = target_csproj_abs.relative_to(repo_path).as_posix()
                        except ValueError:
                            target_proj_rel = target_csproj_abs.as_posix()

                        results_before = len(all_results)
                        _build_consumer_results(
                            target_project_name=target_project_name,
                            target_project_rel_path_str=target_proj_rel,
                            triggering_info=type_name_to_check,
                            final_consumers_data=final_consumers_data,
                            all_results_list=all_results,
                            pipeline_map_dict=ctx.pipeline_map,
                            solution_file_cache=ctx.solution_file_cache,
                            batch_job_map=ctx.batch_job_map,
                            search_scope_path_abs=ctx.search_scope,
                        )

                        if ctx.summarize_consumers and ctx.ai_provider:
                            _summarize_consumer_files(
                                final_consumers_data,
                                all_results,
                                ctx.ai_provider,
                                ctx.search_scope,
                                results_before,
                            )

                    else:
                        logging.info(
                            f"     No consumers found for type "
                            f"'{type_name_to_check}' in project "
                            f"'{target_project_name}'."
                        )

    _apply_graph_enrichment(all_results, ctx)

    # --- Props/targets expansion ---
    props_impacts: List[PropsImpact] = []
    if branch_changes.changed_config_files:
        if ctx.graph_ctx is not None:
            import_index = _build_import_reverse_index(ctx.graph_ctx.graph)
            for cfg in branch_changes.changed_config_files:
                importing_projects = import_index.get(cfg.path, [])
                props_impacts.append(
                    PropsImpact(
                        import_path=cfg.path,
                        change_type=cfg.change_type,
                        importing_projects=sorted(importing_projects),
                    )
                )
                if importing_projects:
                    logging.info(
                        f"Config change {cfg.path} ({cfg.change_type}): "
                        f"affects {len(importing_projects)} project(s)"
                    )
                else:
                    logging.info(
                        f"Config change {cfg.path} ({cfg.change_type}): "
                        f"not imported by any project in graph"
                    )
        else:
            logging.warning(
                "Graph context unavailable — skipping .props/.targets expansion. "
                "Run without --no-graph to enable config change detection."
            )

    return ModeResult(
        all_results=all_results,
        filter_pipeline=filter_pipeline,
        graph_enriched=ctx.graph_enriched,
        props_impacts=props_impacts,
    )


def run_sproc_analysis(
    ctx: ModeContext,
    sproc_name: str,
    sproc_regex: Optional[str],
) -> ModeResult:
    """Run stored-procedure analysis mode.

    Finds C# classes referencing the given sproc, then finds consumers of those
    classes across the search scope.
    """
    from scatter.scanners.project_scanner import derive_namespace
    from scatter.scanners.sproc_scanner import find_cs_files_referencing_sproc
    from scatter.analyzers.consumer_analyzer import find_consumers
    from scatter.compat.v1_bridge import _build_consumer_results

    logging.info("\n--- Running Stored Procedure Analysis Mode ---")
    logging.info(
        f"Identifying projects/classes referencing stored procedure: "
        f"'{sproc_name}' within scope '{ctx.search_scope}'"
    )

    project_class_sproc_map = find_cs_files_referencing_sproc(
        sproc_name,
        ctx.search_scope,
        sproc_regex,
        max_workers=ctx.max_workers,
        chunk_size=ctx.chunk_size,
        disable_multiprocessing=ctx.disable_multiprocessing,
        cs_analysis_chunk_size=ctx.cs_analysis_chunk_size,
    )

    if not project_class_sproc_map:
        logging.info(f"No projects/classes found referencing stored procedure '{sproc_name}'.")
        return ModeResult()

    total_classes_found = sum(len(classes) for classes in project_class_sproc_map.values())
    logging.info(
        f"Found {total_classes_found} class(es) across "
        f"{len(project_class_sproc_map)} project(s) referencing sproc '{sproc_name}'."
    )

    all_results: List[ConsumerResult] = []
    filter_pipeline: Optional[FilterPipeline] = None
    processed_targets_count = 0

    for target_csproj_abs, classes_dict in project_class_sproc_map.items():
        target_project_name = target_csproj_abs.stem
        try:
            target_project_rel_path_str = target_csproj_abs.relative_to(ctx.search_scope).as_posix()
        except ValueError:
            target_project_rel_path_str = target_csproj_abs.as_posix()

        target_namespace_str = ctx.target_namespace or derive_namespace(target_csproj_abs)
        if not target_namespace_str:
            logging.warning(
                f"Could not derive namespace for {target_project_name}. "
                f"Consumer analysis may be incomplete."
            )
            target_namespace_str = f"NAMESPACE_ERROR_{target_project_name}"

        for class_containing_sproc, cs_files_with_sproc_call in classes_dict.items():
            processed_targets_count += 1

            if ctx.class_name and ctx.class_name != class_containing_sproc:
                logging.debug(
                    f"Skipping analysis for class '{class_containing_sproc}' "
                    f"because it doesn't match --class-name '{ctx.class_name}'."
                )
                continue

            method_filter = (
                ctx.method_name
                if ctx.class_name and ctx.class_name == class_containing_sproc
                else None
            )

            logging.info(
                f"\n--- Analyzing Consumers for Class {processed_targets_count}/"
                f"{total_classes_found}: '{class_containing_sproc}' in Project: "
                f"{target_project_name} ---"
            )

            report_trigger_info = f"{class_containing_sproc} (via Sproc: {sproc_name})"
            if method_filter:
                report_trigger_info = (
                    f"{class_containing_sproc}.{method_filter} (via Sproc: {sproc_name})"
                )

            final_consumers_data, _pipeline = find_consumers(
                target_csproj_path=target_csproj_abs,
                search_scope_path=ctx.search_scope,
                target_namespace=target_namespace_str,
                class_name=class_containing_sproc,
                method_name=method_filter,
                max_workers=ctx.max_workers,
                chunk_size=ctx.chunk_size,
                disable_multiprocessing=ctx.disable_multiprocessing,
                cs_analysis_chunk_size=ctx.cs_analysis_chunk_size,
                csproj_analysis_chunk_size=ctx.csproj_analysis_chunk_size,
                graph=ctx.graph_ctx.graph if ctx.graph_ctx else None,
                analysis_config=ctx.config.analysis,
            )

            # Keep the first pipeline that produced results; fall back to last
            if filter_pipeline is None or final_consumers_data:
                filter_pipeline = _pipeline

            results_before = len(all_results)
            _build_consumer_results(
                target_project_name=target_project_name,
                target_project_rel_path_str=target_project_rel_path_str,
                triggering_info=report_trigger_info,
                final_consumers_data=final_consumers_data,
                all_results_list=all_results,
                pipeline_map_dict=ctx.pipeline_map,
                solution_file_cache=ctx.solution_file_cache,
                batch_job_map=ctx.batch_job_map,
                search_scope_path_abs=ctx.search_scope,
            )

            if ctx.summarize_consumers and ctx.ai_provider:
                _summarize_consumer_files(
                    final_consumers_data,
                    all_results,
                    ctx.ai_provider,
                    ctx.search_scope,
                    results_before,
                )

    _apply_graph_enrichment(all_results, ctx)

    return ModeResult(
        all_results=all_results,
        filter_pipeline=filter_pipeline,
        graph_enriched=ctx.graph_enriched,
    )
