"""CSV output formatting for analysis results."""
import csv
import logging
from pathlib import Path
from typing import Dict, List


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
