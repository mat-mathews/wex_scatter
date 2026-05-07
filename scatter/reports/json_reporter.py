"""JSON output formatting for analysis results."""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from scatter.core.models import FilterPipeline, ImpactReport, PRRiskReport, PropsImpact
from scatter.core.tree import build_adjacency, CONFIDENCE_LABEL_RANK

# Major bump = breaking field removal/rename; minor bump = additive fields.
# Absence of schema_version in old reports should be treated as "0.0".
REPORT_SCHEMA_VERSION = "1.1"


def prepare_detailed_results(
    all_results: list, graph_metrics_requested: bool = False
) -> List[Dict]:
    """Convert ConsumerResult objects to PascalCase dicts for JSON output."""
    detailed_results = []
    for r in all_results:
        result = {
            "TargetProjectName": r.target_project_name,
            "TargetProjectPath": r.target_project_path,
            "TriggeringType": r.triggering_type,
            "ConsumerProjectName": r.consumer_project_name,
            "ConsumerProjectPath": r.consumer_project_path,
            "ConsumingSolutions": r.consuming_solutions,
            "PipelineName": r.pipeline_name or None,
            "BatchJobVerification": r.batch_job_verification or None,
            "ConsumerFileSummaries": r.consumer_file_summaries,
        }
        if graph_metrics_requested:
            result["CouplingScore"] = r.coupling_score
            result["FanIn"] = r.fan_in
            result["FanOut"] = r.fan_out
            result["Instability"] = r.instability
            result["InCycle"] = r.in_cycle
        detailed_results.append(result)
    return detailed_results


def write_json_report(
    detailed_results: List[Dict],
    output_file_path: Path,
    metadata: Optional[Dict] = None,
    pipeline: Optional[FilterPipeline] = None,
    props_impacts: Optional[List[PropsImpact]] = None,
    ai_summary: Optional[str] = None,
) -> None:
    """Write analysis results as JSON to file."""
    logging.info(f"Writing {len(detailed_results)} detailed results to JSON: {output_file_path}")

    unique_pipelines = sorted(
        [p for item in detailed_results if (p := item.get("PipelineName")) is not None]
    )

    pipeline_groups = _build_pipeline_groups(detailed_results)

    json_output: Dict[str, Any] = {}
    if metadata is not None:
        json_output["metadata"] = metadata
    if pipeline is not None:
        json_output["filter_pipeline"] = asdict(pipeline)
    json_output["pipeline_summary"] = unique_pipelines
    if pipeline_groups:
        json_output["pipeline_groups"] = pipeline_groups
    json_output["all_results"] = detailed_results
    if ai_summary:
        json_output["ai_summary"] = ai_summary
    if props_impacts:
        json_output["props_impacts"] = [
            {
                "import_path": pi.import_path,
                "change_type": pi.change_type,
                "importing_projects": pi.importing_projects,
            }
            for pi in props_impacts
        ]

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", encoding="utf-8") as jsonfile:
            json.dump(json_output, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write output JSON file: {e}")


def _path_serializer(obj):
    """JSON serializer for Path objects."""
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _build_pipeline_groups(detailed_results: List[Dict]) -> List[Dict[str, Any]]:
    """Build grouped pipeline view from PascalCase result dicts."""
    from collections import defaultdict

    buckets: Dict[str, List[str]] = defaultdict(list)
    for item in detailed_results:
        pipeline = item.get("PipelineName")
        consumer = item.get("ConsumerProjectName", "")
        if pipeline and consumer and consumer not in buckets[pipeline]:
            buckets[pipeline].append(consumer)

    return sorted(
        [
            {
                "pipeline_name": p,
                "consumer_count": len(c),
                "consumers": sorted(c),
            }
            for p, c in buckets.items()
        ],
        key=lambda g: g["pipeline_name"],
    )


def _build_propagation_tree(consumers_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert flat consumers list into nested propagation tree.

    Each node: {consumer_name, depth, confidence_label, children: [...]}.
    Sorted by confidence (HIGH first) to match console output ordering.
    """
    adjacency = build_adjacency(
        consumers_list,
        get_name=lambda c: c["consumer_name"],
        get_parent=lambda c: c.get("propagation_parent"),
        sort_key=lambda c: CONFIDENCE_LABEL_RANK.get(c.get("confidence_label", "LOW"), 2),
    )

    def _build_nodes(parent_key: Optional[str]) -> List[Dict[str, Any]]:
        nodes = []
        for c in adjacency.get(parent_key, []):
            nodes.append(
                {
                    "consumer_name": c["consumer_name"],
                    "depth": c["depth"],
                    "confidence_label": c["confidence_label"],
                    "children": _build_nodes(c["consumer_name"]),
                }
            )
        return nodes

    return _build_nodes(None)


def write_impact_json_report(
    report: ImpactReport, output_file_path: Path, metadata: Optional[Dict] = None
) -> None:
    """Write impact analysis report as JSON to file."""
    logging.info(f"Writing impact report to JSON: {output_file_path}")

    report_dict = {}
    if metadata is not None:
        report_dict["metadata"] = metadata
    # Note: asdict(report) must not contain a 'metadata' key or it will
    # overwrite the metadata block above.  ImpactReport currently has no
    # such field; if one is added, nest under a 'report' key instead.
    report_dict.update(asdict(report))

    # Inject propagation_tree into each target (alongside flat consumers array)
    for target_dict in report_dict.get("targets", []):
        consumers_list = target_dict.get("consumers", [])
        target_dict["propagation_tree"] = _build_propagation_tree(consumers_list)

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", encoding="utf-8") as jsonfile:
            json.dump(report_dict, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote impact JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write impact JSON report: {e}")


def write_scoping_json_report(
    report, output_file_path: Path, metadata: Optional[Dict] = None
) -> None:
    """Write scoping report as JSON to file."""
    logging.info(f"Writing scoping report to JSON: {output_file_path}")

    report_dict: Dict[str, Any] = {}
    if metadata is not None:
        report_dict["metadata"] = metadata

    # Scoping section
    report_dict["scoping"] = {
        "effort": {
            "categories": [
                {
                    "name": c.name,
                    "base_days": c.base_days,
                    "multiplier": c.multiplier,
                    "min_days": c.min_days,
                    "max_days": c.max_days,
                    "factors": c.factors,
                }
                for c in report.effort.categories
            ],
            "total_base_days": report.effort.total_base_days,
            "total_min_days": report.effort.total_min_days,
            "total_max_days": report.effort.total_max_days,
        },
        "confidence": {
            "level": report.confidence.level.value,
            "band_pct": report.confidence.band_pct,
            "composite_score": report.confidence.composite_score,
            "ambiguity_level": report.confidence.ambiguity_level,
            "was_widened": report.confidence.was_widened,
        },
        "database_impact": {
            "shared_sprocs": [
                {
                    "sproc_name": sg.sproc_name,
                    "projects": sg.projects,
                    "project_count": sg.project_count,
                }
                for sg in report.database_impact.shared_sprocs
            ],
            "total_shared_sprocs": report.database_impact.total_shared_sprocs,
            "migration_complexity": report.database_impact.migration_complexity,
            "migration_factors": report.database_impact.migration_factors,
            "estimated_migration_days": report.database_impact.estimated_migration_days,
        },
        "warnings": report.warnings,
        "duration_ms": report.duration_ms,
    }

    # AI adjustment (if present)
    if report.ai_effort_adjustment:
        report_dict["scoping"]["ai_adjustment"] = {
            "narrative": report.ai_effort_adjustment,
            "min_days": report.ai_effort_min_days,
            "max_days": report.ai_effort_max_days,
        }

    # Aggregate risk
    if report.aggregate_risk:
        report_dict["scoping"]["aggregate_risk"] = {
            "composite_score": report.aggregate_risk.composite_score,
            "risk_level": report.aggregate_risk.risk_level.value,
            "risk_factors": report.aggregate_risk.risk_factors,
        }

    # Impact report section (reuse existing serialization)
    impact_dict = asdict(report.impact_report)
    # Remove risk_profiles and aggregate_risk from impact section (they're in scoping)
    impact_dict.pop("risk_profiles", None)
    impact_dict.pop("aggregate_risk", None)
    for target_dict in impact_dict.get("targets", []):
        consumers_list = target_dict.get("consumers", [])
        target_dict["propagation_tree"] = _build_propagation_tree(consumers_list)
    report_dict["impact_report"] = impact_dict

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", encoding="utf-8") as jsonfile:
            json.dump(report_dict, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote scoping JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write scoping JSON report: {e}")


def write_pr_risk_json_report(
    report: PRRiskReport, output_file_path: Path, metadata: Optional[Dict] = None
) -> None:
    """Write PR risk report as JSON to file."""
    logging.info(f"Writing PR risk report to JSON: {output_file_path}")

    report_dict: Dict[str, Any] = {}
    if metadata is not None:
        report_dict["metadata"] = metadata

    report_dict["branch_name"] = report.branch_name
    report_dict["base_branch"] = report.base_branch
    report_dict["risk_level"] = report.risk_level.value
    report_dict["composite_score"] = report.aggregate.composite_score
    report_dict["graph_available"] = report.graph_available
    report_dict["duration_ms"] = report.duration_ms

    # Changed types
    report_dict["changed_types"] = [
        {
            "name": ct.name,
            "kind": ct.kind,
            "change_kind": ct.change_kind,
            "owning_project": ct.owning_project,
            "owning_project_path": ct.owning_project_path,
            "file_path": ct.file_path,
        }
        for ct in report.changed_types
    ]

    # Dimensions
    report_dict["dimensions"] = {
        dim.name: {
            "label": dim.label,
            "score": dim.score,
            "severity": dim.severity,
            "data_available": dim.data_available,
            "factors": dim.factors,
            "raw_metrics": dim.raw_metrics,
        }
        for dim in report.aggregate.dimensions
    }

    # Profiles
    report_dict["profiles"] = [
        {
            "target_name": p.target_name,
            "composite_score": p.composite_score,
            "risk_level": p.risk_level.value,
            "consumer_count": p.consumer_count,
            "transitive_consumer_count": p.transitive_consumer_count,
        }
        for p in report.profiles
    ]

    # Consumer summary
    report_dict["total_direct_consumers"] = report.total_direct_consumers
    report_dict["total_transitive_consumers"] = report.total_transitive_consumers
    report_dict["unique_consumers"] = report.unique_consumers

    # Risk factors and warnings
    report_dict["risk_factors"] = report.risk_factors
    report_dict["warnings"] = report.warnings

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", encoding="utf-8") as jsonfile:
            json.dump(report_dict, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote PR risk JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write PR risk JSON report: {e}")
