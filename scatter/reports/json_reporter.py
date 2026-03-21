"""JSON output formatting for analysis results."""
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from scatter.core.models import FilterPipeline, ImpactReport
from scatter.core.tree import build_adjacency, CONFIDENCE_LABEL_RANK


def prepare_detailed_results(all_results: list,
                             graph_metrics_requested: bool = False) -> List[Dict]:
    """Convert ConsumerResult objects to PascalCase dicts for JSON output."""
    detailed_results = []
    for r in all_results:
        result = {
            'TargetProjectName': r.target_project_name,
            'TargetProjectPath': r.target_project_path,
            'TriggeringType': r.triggering_type,
            'ConsumerProjectName': r.consumer_project_name,
            'ConsumerProjectPath': r.consumer_project_path,
            'ConsumingSolutions': r.consuming_solutions,
            'PipelineName': r.pipeline_name or None,
            'BatchJobVerification': r.batch_job_verification or None,
            'ConsumerFileSummaries': r.consumer_file_summaries,
        }
        if graph_metrics_requested:
            result['CouplingScore'] = r.coupling_score
            result['FanIn'] = r.fan_in
            result['FanOut'] = r.fan_out
            result['Instability'] = r.instability
            result['InCycle'] = r.in_cycle
        detailed_results.append(result)
    return detailed_results


def write_json_report(detailed_results: List[Dict], output_file_path: Path,
                      metadata: Optional[Dict] = None,
                      pipeline: Optional[FilterPipeline] = None) -> None:
    """Write analysis results as JSON to file."""
    logging.info(f"Writing {len(detailed_results)} detailed results to JSON: {output_file_path}")

    unique_pipelines = sorted([
        p for item in detailed_results
        if (p := item.get('PipelineName')) is not None
    ])

    json_output: Dict[str, Any] = {}
    if metadata is not None:
        json_output['metadata'] = metadata
    if pipeline is not None:
        json_output['filter_pipeline'] = asdict(pipeline)
    json_output['pipeline_summary'] = unique_pipelines
    json_output['all_results'] = detailed_results

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(json_output, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write output JSON file: {e}")


def _path_serializer(obj):
    """JSON serializer for Path objects."""
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


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
            nodes.append({
                "consumer_name": c["consumer_name"],
                "depth": c["depth"],
                "confidence_label": c["confidence_label"],
                "children": _build_nodes(c["consumer_name"]),
            })
        return nodes

    return _build_nodes(None)


def write_impact_json_report(report: ImpactReport, output_file_path: Path,
                             metadata: Optional[Dict] = None) -> None:
    """Write impact analysis report as JSON to file."""
    logging.info(f"Writing impact report to JSON: {output_file_path}")

    report_dict = {}
    if metadata is not None:
        report_dict['metadata'] = metadata
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
        with open(output_file_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(report_dict, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote impact JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write impact JSON report: {e}")
