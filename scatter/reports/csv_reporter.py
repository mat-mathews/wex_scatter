"""CSV output formatting for analysis results."""

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional

from scatter.core.models import FilterPipeline, ImpactReport


def _build_filter_comment_header(pipeline: FilterPipeline) -> str:
    """Build comment header lines for CSV from a FilterPipeline."""
    projects = f"{pipeline.total_projects_scanned:,}"
    files = f"{pipeline.total_files_scanned:,}"
    lines = [f"# Search scope: {pipeline.search_scope} ({projects} projects, {files} files)"]

    if pipeline.stages:
        lines.append(f"# Filter: {pipeline.format_arrow_chain()}")

    return "\n".join(lines) + "\n"


def write_csv_report(
    detailed_results: List[Dict],
    output_file_path: Path,
    pipeline: Optional[FilterPipeline] = None,
    graph_metrics_requested: bool = False,
) -> None:
    """Write analysis results as CSV to file."""
    logging.info(f"Writing {len(detailed_results)} results to CSV: {output_file_path}")
    report_fieldnames = [
        "TargetProjectName",
        "TargetProjectPath",
        "TriggeringType",
        "ConsumerProjectName",
        "ConsumerProjectPath",
        "ConsumingSolutions",
        "PipelineName",
        "BatchJobVerification",
    ]
    if graph_metrics_requested:
        report_fieldnames.extend(["CouplingScore", "FanIn", "FanOut", "Instability", "InCycle"])
    # Stringify native types for CSV compatibility
    csv_rows = []
    for item in detailed_results:
        row = dict(item)
        solutions = row.get("ConsumingSolutions", [])
        row["ConsumingSolutions"] = (
            "; ".join(solutions) if isinstance(solutions, list) else (solutions or "")
        )
        row["PipelineName"] = row.get("PipelineName") or ""
        row["BatchJobVerification"] = row.get("BatchJobVerification") or ""
        if graph_metrics_requested:
            row.setdefault("CouplingScore", "")
            row.setdefault("FanIn", "")
            row.setdefault("FanOut", "")
            row.setdefault("Instability", "")
            row["InCycle"] = str(row.get("InCycle", "")) if row.get("InCycle") is not None else ""
        csv_rows.append(row)
    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", newline="", encoding="utf-8") as csvfile:
            if pipeline is not None:
                csvfile.write(_build_filter_comment_header(pipeline))
            writer = csv.DictWriter(csvfile, fieldnames=report_fieldnames, extrasaction="ignore")
            writer.writeheader()
            if csv_rows:
                writer.writerows(csv_rows)
        logging.info(f"Successfully wrote CSV report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write output CSV file: {e}")


def write_scoping_csv_report(report, output_file_path: Path) -> None:
    """Write scoping effort estimate as CSV. Columns match finance budget lines (Decision #2)."""
    logging.info(f"Writing scoping report to CSV: {output_file_path}")
    fieldnames = ["Category", "Base Days", "Multiplier", "Min Days", "Max Days", "Factors"]

    rows = []
    for cat in report.effort.categories:
        rows.append(
            {
                "Category": cat.name,
                "Base Days": f"{cat.base_days:.2f}",
                "Multiplier": f"{cat.multiplier:.2f}",
                "Min Days": f"{cat.min_days:.2f}",
                "Max Days": f"{cat.max_days:.2f}",
                "Factors": "; ".join(cat.factors),
            }
        )
    # TOTAL row
    rows.append(
        {
            "Category": "TOTAL",
            "Base Days": f"{report.effort.total_base_days:.2f}",
            "Multiplier": "",
            "Min Days": f"{report.effort.total_min_days:.2f}",
            "Max Days": f"{report.effort.total_max_days:.2f}",
            "Factors": "",
        }
    )

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", newline="", encoding="utf-8") as csvfile:
            # Header comment with confidence info
            conf = report.confidence
            csvfile.write(
                f"# Confidence: {conf.level.value} (+-{conf.band_pct:.0%}), "
                f"composite score: {conf.composite_score:.2f}\n"
            )
            if report.database_impact.total_shared_sprocs > 0:
                csvfile.write(
                    f"# Database: {report.database_impact.total_shared_sprocs} shared sproc(s), "
                    f"migration complexity: {report.database_impact.migration_complexity}\n"
                )
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logging.info(f"Successfully wrote scoping CSV report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write scoping CSV report: {e}")


def write_impact_csv_report(
    report: ImpactReport, output_file_path: Path, graph_metrics_requested: bool = False
) -> None:
    """Write impact analysis report as CSV to file. One row per consumer."""
    logging.info(f"Writing impact report to CSV: {output_file_path}")
    fieldnames = [
        "Target",
        "TargetType",
        "Consumer",
        "ConsumerPath",
        "Depth",
        "PropagationParent",
        "Confidence",
        "ConfidenceLabel",
        "RiskRating",
        "RiskJustification",
        "Pipeline",
        "Solutions",
        "CouplingVectors",
    ]
    if graph_metrics_requested:
        fieldnames.extend(["CouplingScore", "FanIn", "FanOut", "Instability", "InCycle"])
    rows = []
    for ti in report.targets:
        for c in ti.consumers:
            row = {
                "Target": ti.target.name,
                "TargetType": ti.target.target_type,
                "Consumer": c.consumer_name,
                "ConsumerPath": str(c.consumer_path),
                "Depth": c.depth,
                "PropagationParent": c.propagation_parent or "",
                "Confidence": c.confidence,
                "ConfidenceLabel": c.confidence_label,
                "RiskRating": c.risk_rating or "",
                "RiskJustification": c.risk_justification or "",
                "Pipeline": c.pipeline_name,
                "Solutions": "; ".join(c.solutions),
                "CouplingVectors": "; ".join(c.coupling_vectors) if c.coupling_vectors else "",
            }
            if graph_metrics_requested:
                row["CouplingScore"] = c.coupling_score if c.coupling_score is not None else ""
                row["FanIn"] = c.fan_in if c.fan_in is not None else ""
                row["FanOut"] = c.fan_out if c.fan_out is not None else ""
                row["Instability"] = c.instability if c.instability is not None else ""
                row["InCycle"] = str(c.in_cycle) if c.in_cycle is not None else ""
            rows.append(row)
    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logging.info(f"Successfully wrote impact CSV report to: {output_file_path}")
    except Exception as e:
        logging.error(f"Failed to write impact CSV report: {e}")
