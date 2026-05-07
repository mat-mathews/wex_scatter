"""Report-level AI summary — narrative explanation of consumer analysis results.

Generates a 2-3 paragraph narrative summarizing the full consumer result set:
outlier identification, stable core vs leaf node breakdown, coupling distribution,
and actionable guidance. One AI call with pre-aggregated stats (token-efficient).

Activated by ``--ai-summary`` on target-project, stored-procedure, and git-branch modes.
"""

import json
import logging
import statistics
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from scatter.ai.base import AITaskType
from scatter.core.models import ConsumerResult, FilterPipeline

if TYPE_CHECKING:
    from scatter.analyzers.graph_enrichment import GraphContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure stats function (testable without AI)
# ---------------------------------------------------------------------------


def build_summary_stats(
    all_results: List[ConsumerResult],
    filter_pipeline: Optional[FilterPipeline] = None,
    graph_ctx: Optional["GraphContext"] = None,
) -> Dict[str, Any]:
    """Pre-aggregate consumer results into a token-efficient stats dict.

    Pure function — no AI, no I/O. The dict is designed to fit in ~300 tokens
    when serialized into the LLM prompt.
    """
    targets: Set[str] = set()
    triggering_types: Set[str] = set()
    consumer_names: List[str] = []
    solutions: Set[str] = set()
    pipelines: Set[str] = set()

    coupling_scores: List[float] = []
    fan_ins: List[int] = []
    instabilities: List[float] = []
    cycle_count = 0

    for r in all_results:
        targets.add(r.target_project_name)
        if r.triggering_type:
            triggering_types.add(r.triggering_type)
        consumer_names.append(r.consumer_project_name)
        for s in r.consuming_solutions:
            solutions.add(s)
        if r.pipeline_name:
            pipelines.add(r.pipeline_name)
        if r.coupling_score is not None:
            coupling_scores.append(r.coupling_score)
        if r.fan_in is not None:
            fan_ins.append(r.fan_in)
        if r.instability is not None:
            instabilities.append(r.instability)
        if r.in_cycle:
            cycle_count += 1

    stats: Dict[str, Any] = {
        "targets": sorted(targets),
        "triggering_types": sorted(triggering_types),
        "consumer_count": len(all_results),
        "consumer_names": consumer_names,
        "solutions": sorted(solutions),
        "pipelines": sorted(pipelines),
        "has_graph_metrics": len(coupling_scores) > 0,
    }

    if filter_pipeline:
        stats["projects_scanned"] = filter_pipeline.total_projects_scanned
        stats["files_scanned"] = filter_pipeline.total_files_scanned

    # Full consumer table for the prompt (all consumers with metrics)
    if coupling_scores:
        stats["all_consumers"] = [
            {
                "name": r.consumer_project_name,
                "coupling": round(r.coupling_score, 1) if r.coupling_score is not None else 0,
                "fan_in": r.fan_in or 0,
                "fan_out": r.fan_out or 0,
                "instability": round(r.instability, 2) if r.instability is not None else 0,
                "in_cycle": r.in_cycle or False,
            }
            for r in sorted(all_results, key=lambda x: x.coupling_score or 0, reverse=True)
        ]

    if coupling_scores:
        sorted_scores = sorted(coupling_scores)
        stats["coupling"] = {
            "min": round(min(sorted_scores), 1),
            "max": round(max(sorted_scores), 1),
            "median": round(statistics.median(sorted_scores), 1),
            "mean": round(statistics.mean(sorted_scores), 1),
        }

        median_c = statistics.median(sorted_scores)
        top5 = sorted(
            [
                (r.consumer_project_name, r.coupling_score, r.fan_in, r.instability)
                for r in all_results
                if r.coupling_score is not None
            ],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        stats["top_consumers"] = [
            {
                "name": name,
                "coupling": round(score, 1),
                "fan_in": fi,
                "instability": round(inst, 2) if inst is not None else None,
            }
            for name, score, fi, inst in top5
        ]

        stats["outliers"] = [
            r.consumer_project_name
            for r in all_results
            if r.coupling_score is not None and r.coupling_score > 2 * median_c
        ]
        stats["stable_core"] = [
            r.consumer_project_name
            for r in all_results
            if r.instability is not None
            and r.instability <= 0.3
            and r.fan_in is not None
            and r.fan_in >= 5
        ]
        stats["leaf_nodes"] = [
            r.consumer_project_name
            for r in all_results
            if r.instability is not None and r.instability >= 0.8 and not r.in_cycle
        ]
        stats["cycle_count"] = cycle_count

    if fan_ins:
        stats["fan_in"] = {
            "min": min(fan_ins),
            "max": max(fan_ins),
            "median": round(statistics.median(fan_ins), 1),
        }

    if instabilities:
        stats["instability"] = {
            "min": round(min(instabilities), 2),
            "max": round(max(instabilities), 2),
            "median": round(statistics.median(instabilities), 2),
        }

    return stats


# ---------------------------------------------------------------------------
# AI orchestration
# ---------------------------------------------------------------------------


def generate_report_summary(
    all_results: List[ConsumerResult],
    filter_pipeline: Optional[FilterPipeline],
    graph_ctx: Optional["GraphContext"],
    ai_provider: Any,
) -> Optional[str]:
    """Generate an AI narrative summarizing the full consumer result set.

    Returns the summary string, or None on failure / no provider / empty results.
    """
    if not ai_provider:
        return None
    if not all_results:
        return None

    stats = build_summary_stats(all_results, filter_pipeline, graph_ctx)
    prompt = _build_prompt(stats)

    try:
        result = ai_provider.analyze(
            prompt=prompt,
            context="",
            task_type=AITaskType.REPORT_SUMMARY,
        )
        return _parse_response(result.response)
    except Exception as e:
        logger.warning(f"AI report summary failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_prompt(stats: Dict[str, Any]) -> str:
    """Build the LLM prompt from pre-aggregated stats."""
    if stats["has_graph_metrics"]:
        return _build_prompt_with_metrics(stats)
    return _build_prompt_without_metrics(stats)


def _build_consumer_table(stats: Dict[str, Any]) -> str:
    """Build a markdown table of all consumers for the prompt."""
    rows = []
    for t in stats.get("all_consumers", []):
        rows.append(
            f"| {t['name']} | {t['coupling']} | {t['fan_in']} | {t['fan_out']} | {t['instability']} | {'yes' if t['in_cycle'] else 'no'} |"
        )
    if not rows:
        return ""
    header = "| Consumer | Coupling | Fan-In | Fan-Out | Instability | In Cycle |\n| --- | --- | --- | --- | --- | --- |"
    return header + "\n" + "\n".join(rows)


def _build_prompt_with_metrics(stats: Dict[str, Any]) -> str:
    targets = ", ".join(stats["targets"])
    consumer_table = _build_consumer_table(stats)
    outliers = ", ".join(stats.get("outliers", [])) or "none"
    stable = ", ".join(stats.get("stable_core", [])) or "none"
    leaves = ", ".join(stats.get("leaf_nodes", [])) or "none"
    pipelines = ", ".join(stats.get("pipelines", [])) or "not mapped"
    solutions = ", ".join(stats.get("solutions", [])) or "unknown"

    coupling = stats.get("coupling", {})

    return f"""You are a senior software architecture advisor writing a dependency risk report. Your audience is both engineering managers (who need the business impact) and engineers (who need the technical detail).

TARGET: {targets}
CONSUMERS: {stats["consumer_count"]} (from {stats.get("projects_scanned", "unknown")} projects scanned)
SOLUTIONS AFFECTED: {solutions}
PIPELINES AFFECTED: {pipelines}

COUPLING DISTRIBUTION: min={coupling.get("min")}, median={coupling.get("median")}, max={coupling.get("max")}, mean={coupling.get("mean")}
OUTLIERS (>2x median): {outliers}
STABLE CORE (instability <= 0.3, fan-in >= 5): {stable}
LEAF NODES (instability >= 0.8, not in cycle): {leaves}
CONSUMERS IN CYCLES: {stats.get("cycle_count", 0)} of {stats["consumer_count"]}

FULL CONSUMER TABLE:
{consumer_table}

Write a structured markdown report with these sections:

## Executive Summary
1-2 sentences for an EM or PO. What is this component, how critical is it, what's the blast radius? Cite the specific numbers.

## Technical Risk Analysis
- Identify the coupling distribution shape (is it dominated by outliers or uniform?)
- Group consumers into categories (e.g., web portals, batch processors, services, test projects) and assign risk levels (Critical/High/Medium/Low)
- Call out the highest-coupling consumers by name with their scores
- Explain what the instability scores mean for change safety (stable cores vs leaf nodes)
- Note any positive signals (no cycles, isolated leaf nodes)

## Recommendations
- 3-4 specific, actionable recommendations for the team (testing strategy, deployment coordination, refactoring priorities, architectural improvements)

STYLE GUIDELINES:
- Direct and conversational. No corporate filler.
- Bold key numbers and project names for scannability.
- Use tables where they help (e.g., grouping consumers by category)
- Cite specific coupling scores and fan-in numbers — don't just say "high"
- If there are positive signals (no cycles, many leaf nodes), call them out as silver linings
- Write as if explaining to a smart colleague at a whiteboard

Return ONLY a JSON object with:
- "report": the full markdown report text (with headers, tables, bold, etc.)"""


def _build_prompt_without_metrics(stats: Dict[str, Any]) -> str:
    targets = ", ".join(stats["targets"])
    consumers = ", ".join(stats["consumer_names"])
    solutions = ", ".join(stats["solutions"]) or "unknown"
    pipelines = ", ".join(stats["pipelines"]) or "not mapped"

    return f"""You are a senior software architecture advisor. Write a brief dependency risk summary in markdown.

TARGET: {targets}
CONSUMERS: {stats["consumer_count"]}
SOLUTIONS AFFECTED: {solutions}
PIPELINES AFFECTED: {pipelines}
CONSUMER NAMES: {consumers}

Write a short markdown report with:
## Executive Summary
What is the blast radius? How many teams/solutions need coordination?

## Recommendations
2-3 actionable items (testing, deployment, communication).

Be direct. Cite the numbers. No filler.

Return ONLY a JSON object with:
- "report": the markdown report text"""


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(response_text: str) -> Optional[str]:
    """Parse the LLM JSON response and extract the report markdown."""
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            # Accept either "report" or "summary" key for backward compat
            raw = result.get("report") or result.get("summary")
            if isinstance(raw, str) and raw:
                report: str = raw
                return report
        logger.warning(f"AI report summary missing 'report' key: {text[:200]}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI report summary JSON: {e}")
        return None
