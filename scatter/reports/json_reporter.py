"""JSON output formatting for analysis results."""
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Union

from scatter.core.models import ImpactReport


def prepare_detailed_results(all_results: List[Dict[str, Union[str, Dict, List[str]]]]) -> List[Dict]:
    """Convert results to serializable format for JSON/CSV output."""
    detailed_results = []
    for item in all_results:
        solutions_str = ", ".join(item.get('ConsumingSolutions', []))
        summaries_json = json.dumps(item.get('ConsumerFileSummaries', {}))
        detailed_results.append({
            **item,
            'ConsumingSolutions': solutions_str,
            'ConsumerFileSummaries': summaries_json
        })
    return detailed_results


def write_json_report(detailed_results: List[Dict], output_file_path: Path) -> None:
    """Write analysis results as JSON to file."""
    logging.info(f"Writing {len(detailed_results)} detailed results to JSON: {output_file_path}")

    unique_pipelines = sorted(list(set(
        item.get('PipelineName') for item in detailed_results if item.get('PipelineName')
    )))

    json_output = {
        'pipeline_summary': unique_pipelines,
        'all_results': detailed_results
    }

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(json_output, jsonfile, indent=4)
        logging.info(f"Successfully wrote JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write output JSON file: {e}")


def _path_serializer(obj):
    """JSON serializer for Path objects."""
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def write_impact_json_report(report: ImpactReport, output_file_path: Path) -> None:
    """Write impact analysis report as JSON to file."""
    logging.info(f"Writing impact report to JSON: {output_file_path}")

    report_dict = asdict(report)

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(report_dict, jsonfile, indent=4, default=_path_serializer)
        logging.info(f"Successfully wrote impact JSON report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write impact JSON report: {e}")
