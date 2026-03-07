"""Impact analysis orchestrator — SOW text to ImpactReport pipeline."""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    TargetImpact,
    ImpactReport,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_WORKERS,
    DEFAULT_CHUNK_SIZE,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    _confidence_label,
)
from scatter.analyzers.consumer_analyzer import find_consumers
from scatter.scanners.project_scanner import derive_namespace
from scatter.core.parallel import find_files_with_pattern_parallel
from scatter.compat.v1_bridge import find_solutions_for_project


def run_impact_analysis(
    sow_text: str,
    search_scope: Path,
    ai_provider,
    max_depth: int = DEFAULT_MAX_DEPTH,
    pipeline_map: Optional[Dict[str, str]] = None,
    solution_file_cache: Optional[List[Path]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
    csproj_analysis_chunk_size: int = 25,
) -> ImpactReport:
    """Orchestrate the full impact analysis pipeline.

    Pipeline:
      SOW text → AI parse → [AnalysisTarget, ...] → find_consumers() per target
               → transitive tracing → AI enrichment → ImpactReport
    """
    if pipeline_map is None:
        pipeline_map = {}
    if solution_file_cache is None:
        solution_file_cache = []

    report = ImpactReport(sow_text=sow_text)

    # Step 1: Parse work request into targets
    logging.info("Step 1: Parsing work request into analysis targets...")
    from scatter.ai.tasks.parse_work_request import parse_work_request
    targets = parse_work_request(sow_text, ai_provider, search_scope)

    if not targets:
        logging.warning("No analysis targets could be extracted from the work request.")
        return report

    logging.info(f"Extracted {len(targets)} analysis target(s) from work request.")

    # Step 2: For each target, find consumers and trace transitively
    for target in targets:
        logging.info(f"\n--- Analyzing target: {target.name} (type: {target.target_type}) ---")
        target_impact = _analyze_single_target(
            target=target,
            search_scope=search_scope,
            max_depth=max_depth,
            pipeline_map=pipeline_map,
            solution_file_cache=solution_file_cache,
            max_workers=max_workers,
            chunk_size=chunk_size,
            disable_multiprocessing=disable_multiprocessing,
            cs_analysis_chunk_size=cs_analysis_chunk_size,
            csproj_analysis_chunk_size=csproj_analysis_chunk_size,
        )
        report.targets.append(target_impact)

    # Step 3: AI risk assessment per target
    logging.info("\nStep 3: Assessing risk per target...")
    from scatter.ai.tasks.risk_assess import assess_risk
    for target_impact in report.targets:
        if target_impact.consumers:
            risk_result = assess_risk(target_impact.target, target_impact.consumers, ai_provider)
            if risk_result:
                for consumer in target_impact.consumers:
                    if consumer.risk_rating is None:
                        consumer.risk_rating = risk_result.get("rating")
                        consumer.risk_justification = risk_result.get("justification")

    # Step 4: AI coupling narrative (optional, per consumer)
    logging.info("Step 4: Generating coupling narratives...")
    from scatter.ai.tasks.coupling_narrative import explain_coupling
    for target_impact in report.targets:
        for consumer in target_impact.consumers:
            if consumer.depth == 0 and consumer.relevant_files:
                coupling = explain_coupling(
                    target_impact.target, consumer, ai_provider, search_scope
                )
                if coupling:
                    consumer.coupling_narrative = coupling.get("narrative")
                    consumer.coupling_vectors = coupling.get("vectors")

    # Step 5: AI complexity estimate
    logging.info("Step 5: Estimating complexity...")
    from scatter.ai.tasks.complexity_estimate import estimate_complexity
    complexity = estimate_complexity(report, ai_provider)
    if complexity:
        report.complexity_rating = complexity.get("rating")
        report.complexity_justification = complexity.get("justification")
        report.effort_estimate = complexity.get("effort_estimate")

    # Step 6: AI impact narrative
    logging.info("Step 6: Generating impact narrative...")
    from scatter.ai.tasks.impact_narrative import generate_impact_narrative
    narrative = generate_impact_narrative(report, ai_provider)
    if narrative:
        report.impact_narrative = narrative.get("narrative")

    # Derive overall risk from targets
    risk_levels = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
    max_risk = "Low"
    for ti in report.targets:
        for c in ti.consumers:
            if c.risk_rating and risk_levels.get(c.risk_rating, 0) > risk_levels.get(max_risk, 0):
                max_risk = c.risk_rating
    report.overall_risk = max_risk

    return report


def _analyze_single_target(
    target: AnalysisTarget,
    search_scope: Path,
    max_depth: int,
    pipeline_map: Dict[str, str],
    solution_file_cache: List[Path],
    max_workers: int,
    chunk_size: int,
    disable_multiprocessing: bool,
    cs_analysis_chunk_size: int,
    csproj_analysis_chunk_size: int,
) -> TargetImpact:
    """Analyze a single target: find direct consumers, trace transitively."""
    impact = TargetImpact(target=target)

    if not target.csproj_path or not target.csproj_path.is_file():
        logging.warning(f"Target csproj not found on disk: {target.csproj_path}. Skipping.")
        return impact

    # Derive namespace
    namespace = target.namespace or derive_namespace(target.csproj_path)
    if not namespace:
        logging.warning(f"Could not derive namespace for {target.name}.")
        namespace = f"NAMESPACE_ERROR_{target.name}"

    # Find direct consumers
    direct_consumers_data = find_consumers(
        target_csproj_path=target.csproj_path,
        search_scope_path=search_scope,
        target_namespace=namespace,
        class_name=target.class_name,
        method_name=target.method_name,
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing,
        cs_analysis_chunk_size=cs_analysis_chunk_size,
        csproj_analysis_chunk_size=csproj_analysis_chunk_size,
    )

    if not direct_consumers_data:
        logging.info(f"No direct consumers found for {target.name}.")
        return impact

    logging.info(f"Found {len(direct_consumers_data)} direct consumer(s) for {target.name}.")

    # Trace transitively
    all_consumers = trace_transitive_impact(
        direct_consumers=direct_consumers_data,
        search_scope=search_scope,
        max_depth=max_depth,
        pipeline_map=pipeline_map,
        solution_file_cache=solution_file_cache,
        max_workers=max_workers,
        chunk_size=chunk_size,
        disable_multiprocessing=disable_multiprocessing,
        cs_analysis_chunk_size=cs_analysis_chunk_size,
        csproj_analysis_chunk_size=csproj_analysis_chunk_size,
    )

    impact.consumers = all_consumers
    impact.total_direct = sum(1 for c in all_consumers if c.depth == 0)
    impact.total_transitive = sum(1 for c in all_consumers if c.depth > 0)
    impact.max_depth_reached = max((c.depth for c in all_consumers), default=0)

    return impact


def trace_transitive_impact(
    direct_consumers: List[Dict[str, Union[Path, str, List[Path]]]],
    search_scope: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
    pipeline_map: Optional[Dict[str, str]] = None,
    solution_file_cache: Optional[List[Path]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
    csproj_analysis_chunk_size: int = 25,
) -> List[EnrichedConsumer]:
    """BFS transitive tracing with confidence decay and cycle detection.

    depth 0 = direct consumers (from find_consumers)
    depth 1+ = consumers of consumers (project-reference only)
    """
    if pipeline_map is None:
        pipeline_map = {}
    if solution_file_cache is None:
        solution_file_cache = []

    confidence_by_depth = {0: CONFIDENCE_HIGH, 1: CONFIDENCE_MEDIUM, 2: CONFIDENCE_LOW}
    visited: set = set()
    all_enriched: List[EnrichedConsumer] = []

    # Convert direct consumers to EnrichedConsumer at depth 0
    current_level: List[Dict[str, Union[Path, str, List[Path]]]] = direct_consumers
    depth = 0

    while depth <= max_depth and current_level:
        conf = confidence_by_depth.get(depth, CONFIDENCE_LOW)
        next_level_raw: List[Dict[str, Union[Path, str, List[Path]]]] = []

        for consumer_data in current_level:
            consumer_path = consumer_data['consumer_path']
            if consumer_path in visited:
                continue
            visited.add(consumer_path)

            consumer_name = str(consumer_data['consumer_name'])

            # Resolve solutions
            solutions = []
            if solution_file_cache:
                sol_paths = find_solutions_for_project(consumer_path, solution_file_cache)
                solutions = [s.stem for s in sol_paths]

            # Resolve pipeline
            pipeline_name = pipeline_map.get(consumer_name, "")

            enriched = EnrichedConsumer(
                consumer_path=consumer_path,
                consumer_name=consumer_name,
                relevant_files=list(consumer_data.get('relevant_files', [])),
                solutions=solutions,
                pipeline_name=pipeline_name,
                depth=depth,
                confidence=conf,
                confidence_label=_confidence_label(conf),
            )
            all_enriched.append(enriched)

            # For next depth: find consumers of this consumer (project-reference only)
            if depth < max_depth and consumer_path.is_file():
                ns = derive_namespace(consumer_path)
                if ns:
                    transitive_data = find_consumers(
                        target_csproj_path=consumer_path,
                        search_scope_path=search_scope,
                        target_namespace=ns,
                        class_name=None,
                        method_name=None,
                        max_workers=max_workers,
                        chunk_size=chunk_size,
                        disable_multiprocessing=disable_multiprocessing,
                        cs_analysis_chunk_size=cs_analysis_chunk_size,
                        csproj_analysis_chunk_size=csproj_analysis_chunk_size,
                    )
                    next_level_raw.extend(transitive_data)

        depth += 1
        current_level = next_level_raw

    return all_enriched
