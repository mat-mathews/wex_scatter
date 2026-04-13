"""Output routing and metadata helpers for Scatter CLI.

Handles format dispatch (console, JSON, CSV, markdown, pipelines) and
report metadata construction.  These are CLI concerns — no analysis logic.
"""

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from scatter.__version__ import __version__
from scatter.cli_parser import _REDACTED_CLI_KEYS
from scatter.core.models import ConsumerResult, FilterPipeline
from scatter.reports.console_reporter import print_console_report
from scatter.reports.json_reporter import prepare_detailed_results, write_json_report
from scatter.reports.csv_reporter import write_csv_report


def _build_metadata(
    args,
    search_scope: Optional[Path],
    start_time: float,
    *,
    graph_enriched: bool = False,
) -> Dict:
    """Build metadata dict for JSON report output."""
    cli_args = {k: v for k, v in vars(args).items() if k not in _REDACTED_CLI_KEYS}
    return {
        "scatter_version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cli_args": cli_args,
        "search_scope": str(search_scope) if search_scope else None,
        "duration_seconds": round(time.monotonic() - start_time, 2),
        "graph_enriched": graph_enriched,
    }


def _require_output_file(args, format_name: str) -> Path:
    """Validate --output-file is provided for file-based formats. Exit if missing."""
    if not args.output_file:
        logging.error(f"{format_name} output format requires the --output-file argument.")
        sys.exit(1)
    return Path(args.output_file)


def dispatch_legacy_output(
    all_results: List[ConsumerResult],
    filter_pipeline: Optional[FilterPipeline],
    args,
    search_scope: Optional[Path],
    start_time: float,
    graph_enriched: bool,
    pipeline_map: Optional[Dict[str, str]] = None,
) -> None:
    """Route legacy mode results (git/target/sproc) to the chosen reporter.

    Handles sorting, metadata building, and format-specific dispatch.

    ``args`` attributes read: output_format, output_file, and all attributes
    forwarded to ``_build_metadata`` (everything except ``_REDACTED_CLI_KEYS``).
    """
    logging.info("\n--- Consolidating and reporting results ---")

    # Apply pipeline mapping to results when provided
    if pipeline_map:
        for r in all_results:
            if r.pipeline_name is None:
                r.pipeline_name = pipeline_map.get(r.consumer_project_name, "") or None
    if not all_results:
        logging.info(
            "Overall analysis complete. No consuming relationships matching the criteria were found."
        )
    else:
        logging.info(
            f"Overall analysis complete. Found {len(all_results)} consuming relationship(s) matching the criteria."
        )
        all_results.sort(
            key=lambda x: (
                x.target_project_name,
                x.triggering_type,
                x.consumer_project_name,
            )
        )

    # Handle JSON Output
    if args.output_format == "json":
        output_path = _require_output_file(args, "JSON")
        detailed = prepare_detailed_results(all_results, graph_metrics_requested=graph_enriched)
        write_json_report(
            detailed,
            output_path,
            metadata=_build_metadata(args, search_scope, start_time, graph_enriched=graph_enriched),
            pipeline=filter_pipeline,
        )

    # Handle CSV Output
    elif args.output_format == "csv":
        output_path = _require_output_file(args, "CSV")
        detailed = prepare_detailed_results(all_results, graph_metrics_requested=graph_enriched)
        write_csv_report(
            detailed,
            output_path,
            pipeline=filter_pipeline,
            graph_metrics_requested=graph_enriched,
        )

    # Handle Markdown Output
    elif args.output_format == "markdown":
        from scatter.reports.markdown_reporter import build_markdown, write_markdown_report

        detailed = prepare_detailed_results(all_results, graph_metrics_requested=graph_enriched)
        md_metadata = _build_metadata(args, search_scope, start_time, graph_enriched=graph_enriched)
        if args.output_file:
            write_markdown_report(
                detailed,
                Path(args.output_file),
                metadata=md_metadata,
                pipeline=filter_pipeline,
                graph_metrics_requested=graph_enriched,
            )
        else:
            print(
                build_markdown(
                    detailed,
                    metadata=md_metadata,
                    pipeline=filter_pipeline,
                    graph_metrics_requested=graph_enriched,
                )
            )

    # Handle Pipelines Output
    elif args.output_format == "pipelines":
        from scatter.reports.pipeline_reporter import (
            extract_pipeline_names,
            format_pipeline_output,
            write_pipeline_report,
        )

        names = extract_pipeline_names(all_results)
        if args.output_file:
            write_pipeline_report(names, Path(args.output_file))
        else:
            output = format_pipeline_output(names)
            if output:
                print(output)

    # Handle Console Output (Default)
    else:
        print_console_report(
            all_results,
            pipeline=filter_pipeline,
            graph_metrics_requested=graph_enriched,
        )

    # Summary line is printed by each reporter; no duplicate needed here.
