"""CSV output formatting for analysis results."""
import csv
import logging
from pathlib import Path
from typing import Dict, List

from scatter.core.models import ImpactReport


def write_csv_report(detailed_results: List[Dict], output_file_path: Path) -> None:
    """Write analysis results as CSV to file."""
    logging.info(f"Writing {len(detailed_results)} results to CSV: {output_file_path}")
    report_fieldnames = [
        'TargetProjectName', 'TargetProjectPath', 'TriggeringType',
        'ConsumerProjectName', 'ConsumerProjectPath', 'ConsumingSolutions',
        'PipelineName', 'BatchJobVerification', 'ConsumerFileSummaries'
    ]
    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=report_fieldnames)
            writer.writeheader()
            if detailed_results:
                writer.writerows(detailed_results)
        logging.info(f"Successfully wrote CSV report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write output CSV file: {e}")


def write_impact_csv_report(report: ImpactReport, output_file_path: Path) -> None:
    """Write impact analysis report as CSV to file. One row per consumer."""
    logging.info(f"Writing impact report to CSV: {output_file_path}")
    fieldnames = [
        'Target', 'TargetType', 'Consumer', 'ConsumerPath',
        'Depth', 'Confidence', 'ConfidenceLabel',
        'RiskRating', 'RiskJustification', 'Pipeline',
        'Solutions', 'CouplingVectors',
    ]
    rows = []
    for ti in report.targets:
        for c in ti.consumers:
            rows.append({
                'Target': ti.target.name,
                'TargetType': ti.target.target_type,
                'Consumer': c.consumer_name,
                'ConsumerPath': str(c.consumer_path),
                'Depth': c.depth,
                'Confidence': c.confidence,
                'ConfidenceLabel': c.confidence_label,
                'RiskRating': c.risk_rating or '',
                'RiskJustification': c.risk_justification or '',
                'Pipeline': c.pipeline_name,
                'Solutions': ', '.join(c.solutions),
                'CouplingVectors': ', '.join(c.coupling_vectors) if c.coupling_vectors else '',
            })
    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logging.info(f"Successfully wrote impact CSV report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write impact CSV report: {e}")
