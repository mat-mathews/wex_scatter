"""Impact analysis mode handler."""

import logging
import sys
from pathlib import Path

from scatter.cli import (
    ModeContext,
    apply_impact_graph_enrichment,
    _build_metadata,
    _require_output_file,
)


def run_impact_mode(args, ctx: ModeContext, start_time: float) -> None:
    """Impact analysis. Reads: args.sow, args.sow_file, args.sow_min_confidence, args.output_format, args.output_file"""
    logging.info("\n--- Running Impact Analysis Mode ---")

    # Resolve SOW text
    if args.sow_file:
        try:
            sow_file_path = Path(args.sow_file).resolve(strict=True)
            sow_text = sow_file_path.read_text(encoding="utf-8")
            logging.info(f"Loaded work request from file: {sow_file_path}")
        except FileNotFoundError:
            logging.error(f"SOW file not found: {args.sow_file}")
            sys.exit(1)
        except Exception as e:
            logging.error(f"Error reading SOW file: {e}")
            sys.exit(1)
    else:
        sow_text = args.sow

    logging.info(f"Work request: {sow_text[:200]}{'...' if len(sow_text) > 200 else ''}")

    from scatter.analyzers.impact_analyzer import run_impact_analysis
    from scatter.reports.console_reporter import print_impact_report
    from scatter.reports.json_reporter import write_impact_json_report
    from scatter.reports.csv_reporter import write_impact_csv_report

    impact_report = run_impact_analysis(
        sow_text=sow_text,
        search_scope=ctx.search_scope,
        ai_provider=ctx.ai_provider,
        max_depth=ctx.config.max_depth,
        pipeline_map=ctx.pipeline_map,
        solution_file_cache=ctx.solution_file_cache,
        max_workers=ctx.max_workers,
        chunk_size=ctx.chunk_size,
        disable_multiprocessing=ctx.disable_multiprocessing,
        cs_analysis_chunk_size=ctx.cs_analysis_chunk_size,
        csproj_analysis_chunk_size=ctx.csproj_analysis_chunk_size,
        graph=ctx.graph_ctx.graph if ctx.graph_ctx else None,
        min_confidence=args.sow_min_confidence,
        solution_index=ctx.solution_index,
        analysis_config=ctx.config.analysis,
    )

    # Enrich consumers with graph metrics if available
    apply_impact_graph_enrichment(impact_report, ctx)
    graph_enriched = ctx.graph_enriched

    # Output impact report
    if args.output_format == "json":
        output_path = _require_output_file(args, "JSON")
        write_impact_json_report(
            impact_report,
            output_path,
            metadata=_build_metadata(
                args, ctx.search_scope, start_time, graph_enriched=graph_enriched
            ),
        )
    elif args.output_format == "csv":
        output_path = _require_output_file(args, "CSV")
        write_impact_csv_report(impact_report, output_path, graph_metrics_requested=graph_enriched)
    elif args.output_format == "markdown":
        from scatter.reports.markdown_reporter import (
            build_impact_markdown,
            write_impact_markdown_report,
        )

        md_metadata = _build_metadata(
            args, ctx.search_scope, start_time, graph_enriched=graph_enriched
        )
        if args.output_file:
            write_impact_markdown_report(
                impact_report,
                Path(args.output_file),
                metadata=md_metadata,
                graph_metrics_requested=graph_enriched,
            )
        else:
            print(
                build_impact_markdown(
                    impact_report, metadata=md_metadata, graph_metrics_requested=graph_enriched
                )
            )
    elif args.output_format == "pipelines":
        from scatter.reports.pipeline_reporter import (
            extract_impact_pipeline_names,
            format_pipeline_output,
            write_pipeline_report,
        )

        names = extract_impact_pipeline_names(impact_report)
        if args.output_file:
            write_pipeline_report(names, Path(args.output_file))
        else:
            output = format_pipeline_output(names)
            if output:
                print(output)
    else:
        print_impact_report(impact_report)

    consumer_count = sum(len(ti.consumers) for ti in impact_report.targets)
    target_count = len(impact_report.targets)
    if args.output_format != "pipelines":
        print(
            f"\nAnalysis complete. {consumer_count} consumer(s) found across {target_count} target(s).\n"
        )
