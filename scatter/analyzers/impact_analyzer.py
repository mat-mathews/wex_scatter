"""Impact analysis orchestrator — SOW text to ImpactReport pipeline."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from scatter.config import AnalysisConfig
    from scatter.analyzers.graph_enrichment import GraphContext

from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    RawConsumerDict,
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
from scatter.analyzers.risk_engine import aggregate_risk, compute_risk_profile
from scatter.core.risk_models import RiskLevel, SOW_RISK_CONTEXT
from scatter.scanners.project_scanner import derive_namespace
from scatter.compat.v1_bridge import find_solutions_for_project

# Risk level ordering for AI escalation logic (Decision #16).
# Graph-derived risk tops out at "High"; only AI can escalate to "Critical".
RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


def _risk_level_to_label(level: RiskLevel) -> str:
    """Map graph-derived RiskLevel to existing AI-compatible label.

    Decision #15: No "Critical" mapping. Graph tops out at "High".
    Only AI enrichment can escalate to "Critical".
    """
    return {
        RiskLevel.RED: "High",
        RiskLevel.YELLOW: "Medium",
        RiskLevel.GREEN: "Low",
    }[level]


def _derive_overall_risk_from_consumers(report: ImpactReport) -> str:
    """Derive overall risk from max consumer risk_rating (AI-only fallback)."""
    max_risk = "Low"
    for ti in report.targets:
        for c in ti.consumers:
            if c.risk_rating and RISK_ORDER.get(c.risk_rating, 0) > RISK_ORDER.get(max_risk, 0):
                max_risk = c.risk_rating
    return max_risk


def _compute_ambiguity_label(targets: List[AnalysisTarget]) -> str:
    """Classify target parse quality as clear/moderate/vague.

    clear: <=5 targets, avg confidence >= 0.7
    moderate: 6-10 targets, or avg confidence 0.4-0.7
    vague: >10 targets, or avg confidence < 0.4
    """
    if not targets:
        return "vague"

    avg_conf = sum(t.confidence for t in targets) / len(targets)
    count = len(targets)

    if count > 10 or avg_conf < 0.4:
        return "vague"
    if count > 5 or avg_conf < 0.7:
        return "moderate"
    return "clear"


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
    graph_ctx: Optional["GraphContext"] = None,
    min_confidence: float = 0.3,
    solution_index=None,
    analysis_config: Optional["AnalysisConfig"] = None,
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

    # Extract raw graph for consumer tracing and codebase index (Decision #12).
    # Risk scoring uses graph_ctx directly (metrics, cycles); consumer tracing
    # and codebase index only need the raw DependencyGraph.
    graph = graph_ctx.graph if graph_ctx else None

    report = ImpactReport(sow_text=sow_text)

    # Build codebase index from graph if available
    codebase_index = None
    if graph is not None:
        from scatter.ai.codebase_index import build_codebase_index

        codebase_index = build_codebase_index(graph, search_scope)
        logging.info(
            f"Built codebase index: {codebase_index.project_count} projects, "
            f"{codebase_index.type_count} types, {codebase_index.sproc_count} sprocs, "
            f"{codebase_index.size_bytes:,} bytes"
        )

    # Step 1: Parse work request into targets
    logging.info("Step 1: Parsing work request into analysis targets...")
    from scatter.ai.tasks.parse_work_request import parse_work_request

    # Note: parse_work_request is currently the only AI call that receives the
    # full codebase index. If other tasks start sending it, move this catch to
    # a shared wrapper closer to the AI call boundary.
    try:
        targets = parse_work_request(
            sow_text,
            ai_provider,
            search_scope,
            codebase_index=codebase_index,
        )
    except Exception as exc:
        # Gemini raises google.api_core.exceptions.InvalidArgument for oversized requests.
        # Match by class name to avoid importing google.api_core when AI is unused.
        if type(exc).__name__ == "InvalidArgument":
            index_tokens = codebase_index.size_bytes // 4 if codebase_index else 0
            raise RuntimeError(
                f"Codebase index is ~{index_tokens:,} tokens (estimated), which exceeds "
                f"the model's context window. Try narrowing --search-scope or using a "
                f"model with a larger context window."
            ) from exc
        raise

    if not targets:
        logging.warning("No analysis targets could be extracted from the work request.")
        return report

    logging.info(f"Extracted {len(targets)} analysis target(s) from work request.")

    # Compute ambiguity from full list (before filtering)
    report.ambiguity_level = _compute_ambiguity_label(targets)
    report.avg_target_confidence = sum(t.confidence for t in targets) / len(targets)
    logging.info(
        f"Target quality: {report.ambiguity_level} "
        f"({len(targets)} targets, avg confidence {report.avg_target_confidence:.2f})"
    )

    # Filter low-confidence targets
    filtered_targets = []
    for target in targets:
        if target.confidence < min_confidence:
            logging.info(
                f"Excluded target '{target.name}' "
                f"(confidence {target.confidence:.2f}, threshold {min_confidence:.2f})"
            )
        else:
            filtered_targets.append(target)

    if not filtered_targets:
        logging.warning(
            f"All {len(targets)} targets excluded by confidence threshold {min_confidence:.2f}."
        )
        return report

    targets = filtered_targets

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
            graph=graph,  # raw graph for consumer tracing
            solution_index=solution_index,
            analysis_config=analysis_config,
        )
        report.targets.append(target_impact)

    # Step 3: Risk assessment per target (Decision #11 — per-target, not per-consumer)
    # Graph-derived risk fills first when graph_ctx is available. AI enrichment
    # can escalate but never downgrade (Decision #16).
    logging.info("\nStep 3: Assessing risk per target...")
    from scatter.ai.tasks.risk_assess import assess_risk

    risk_profiles = []

    for target_impact in report.targets:
        if not target_impact.consumers:
            continue

        consumers = target_impact.consumers

        # Graph-derived risk (deterministic, no AI needed)
        if graph_ctx is not None:
            profile = compute_risk_profile(
                target=target_impact.target.name,
                graph=graph_ctx.graph,
                metrics=graph_ctx.metrics,
                consumers=[c.consumer_name for c in consumers],
                cycles=graph_ctx.cycles,
                context=SOW_RISK_CONTEXT,  # Phase 3 replaces with mode-aware context selection
                direct_consumer_count=target_impact.total_direct,
                transitive_consumer_count=target_impact.total_transitive,
            )
            risk_profiles.append(profile)
            risk_label = _risk_level_to_label(profile.risk_level)
            logging.debug(
                "risk_engine: %s → %s (composite %.3f)",
                target_impact.target.name,
                risk_label,
                profile.composite_score,
            )
            for consumer in consumers:
                consumer.risk_rating = risk_label
                consumer.risk_justification = "; ".join(profile.risk_factors[:3])

        # AI enrichment (can escalate, never downgrade — Decision #16)
        risk_result = assess_risk(target_impact.target, consumers, ai_provider)
        if risk_result:
            ai_rating = risk_result.get("rating")
            for consumer in consumers:
                if consumer.risk_rating is None:
                    # No graph data — AI is primary
                    consumer.risk_rating = ai_rating
                    consumer.risk_justification = risk_result.get("justification")
                elif ai_rating and RISK_ORDER.get(ai_rating, 0) > RISK_ORDER.get(
                    consumer.risk_rating, 0
                ):
                    # AI escalates graph-derived risk (e.g. "High" → "Critical")
                    logging.debug(
                        "risk_ai_escalation: %s consumer=%s %s→%s",
                        target_impact.target.name,
                        consumer.consumer_name,
                        consumer.risk_rating,
                        ai_rating,
                    )
                    consumer.risk_rating = ai_rating
                if consumer.risk_justification is None:
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

    # Derive overall risk (Decision #13): graph aggregate when available,
    # AI-derived max otherwise.
    if risk_profiles:
        agg = aggregate_risk(risk_profiles, SOW_RISK_CONTEXT)
        report.overall_risk = _risk_level_to_label(agg.risk_level)
        report.risk_profiles = risk_profiles  # Decision #10
        report.aggregate_risk = agg  # Decision #10
    else:
        report.overall_risk = _derive_overall_risk_from_consumers(report)

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
    graph=None,
    solution_index=None,
    analysis_config: Optional["AnalysisConfig"] = None,
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
    direct_consumers_data, _pipeline = find_consumers(
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
        graph=graph,
        analysis_config=analysis_config,
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
        graph=graph,
        solution_index=solution_index,
        analysis_config=analysis_config,
    )

    impact.consumers = all_consumers
    impact.total_direct = sum(1 for c in all_consumers if c.depth == 0)
    impact.total_transitive = sum(1 for c in all_consumers if c.depth > 0)
    impact.max_depth_reached = max((c.depth for c in all_consumers), default=0)

    return impact


def trace_transitive_impact(
    direct_consumers: List[RawConsumerDict],
    search_scope: Path,
    max_depth: int = DEFAULT_MAX_DEPTH,
    pipeline_map: Optional[Dict[str, str]] = None,
    solution_file_cache: Optional[List[Path]] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
    csproj_analysis_chunk_size: int = 25,
    graph=None,
    solution_index=None,
    analysis_config: Optional["AnalysisConfig"] = None,
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
    parent_map: Dict[Path, str] = {}  # maps consumer_path → parent consumer_name
    all_enriched: List[EnrichedConsumer] = []

    # Convert direct consumers to EnrichedConsumer at depth 0
    current_level: List[RawConsumerDict] = direct_consumers
    depth = 0

    while depth <= max_depth and current_level:
        conf = confidence_by_depth.get(depth, CONFIDENCE_LOW)
        next_level_raw: List[RawConsumerDict] = []

        for consumer_data in current_level:
            consumer_path = consumer_data["consumer_path"]
            if consumer_path in visited:
                continue
            visited.add(consumer_path)

            consumer_name = str(consumer_data["consumer_name"])

            # Resolve solutions
            solutions = []
            if solution_index is not None or solution_file_cache:
                sol_paths = find_solutions_for_project(
                    consumer_path, solution_file_cache, solution_index=solution_index
                )
                solutions = [s.stem for s in sol_paths]

            # Resolve pipeline
            pipeline_name = pipeline_map.get(consumer_name, "")

            enriched = EnrichedConsumer(
                consumer_path=consumer_path,
                consumer_name=consumer_name,
                relevant_files=list(consumer_data.get("relevant_files", [])),
                solutions=solutions,
                pipeline_name=pipeline_name,
                depth=depth,
                confidence=conf,
                confidence_label=_confidence_label(conf),
                # Direct consumers (depth 0) have no parent — they are roots.
                # Only transitive consumers get a propagation parent.
                propagation_parent=parent_map.get(consumer_path) if depth > 0 else None,
            )
            all_enriched.append(enriched)

            # For next depth: find consumers of this consumer (project-reference only)
            if depth < max_depth and consumer_path.is_file():
                ns = derive_namespace(consumer_path)
                if ns:
                    transitive_data, _t_pipeline = find_consumers(
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
                        graph=graph,
                        analysis_config=analysis_config,
                    )
                    for td in transitive_data:
                        td_path = td["consumer_path"]
                        if td_path not in visited and td_path not in parent_map:
                            parent_map[td_path] = consumer_name
                    next_level_raw.extend(transitive_data)

        depth += 1
        current_level = next_level_raw

    return all_enriched
