"""Impact analysis mode handler."""

import logging
import sys
from pathlib import Path

from scatter.analysis import ModeContext, apply_impact_graph_enrichment
from scatter.output import _build_metadata, _require_output_file


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
        graph_ctx=ctx.graph_ctx,
        min_confidence=args.sow_min_confidence,
        solution_index=ctx.solution_index,
        analysis_config=ctx.config.analysis,
    )

    # Enrich consumers with graph metrics if available
    apply_impact_graph_enrichment(impact_report, ctx)
    graph_enriched = ctx.graph_enriched

    # Scoping analysis (Decision #8 — extends --sow mode, not a new mode)
    if getattr(args, "scope_estimate", False):
        try:
            from scatter.analyzers.scoping_analyzer import run_scoping_analysis

            scoping_report = run_scoping_analysis(impact_report, ctx.graph_ctx, ctx.ai_provider)
            _dispatch_scoping_output(scoping_report, args, ctx, start_time, graph_enriched)
            return
        except Exception:
            # Fatima #13: scoping failure falls back to impact report
            logging.warning("Scoping analysis failed, falling back to impact report", exc_info=True)

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


def _dispatch_scoping_output(scoping_report, args, ctx, start_time, graph_enriched):
    """Route scoping report to the appropriate output format."""
    metadata = _build_metadata(args, ctx.search_scope, start_time, graph_enriched=graph_enriched)

    if args.output_format == "json":
        from scatter.reports.json_reporter import write_scoping_json_report

        output_path = _require_output_file(args, "JSON")
        write_scoping_json_report(scoping_report, output_path, metadata=metadata)
    elif args.output_format == "csv":
        from scatter.reports.csv_reporter import write_scoping_csv_report

        output_path = _require_output_file(args, "CSV")
        write_scoping_csv_report(scoping_report, output_path)
    elif args.output_format == "markdown":
        from scatter.reports.markdown_reporter import (
            build_scoping_markdown,
            write_scoping_markdown_report,
        )

        if args.output_file:
            write_scoping_markdown_report(scoping_report, Path(args.output_file), metadata=metadata)
        else:
            print(build_scoping_markdown(scoping_report, metadata=metadata))
    else:
        from scatter.reports.console_reporter import print_scoping_report

        print_scoping_report(scoping_report)

    consumer_count = sum(len(ti.consumers) for ti in scoping_report.impact_report.targets)
    target_count = len(scoping_report.impact_report.targets)
    print(
        f"\nScoping complete. {consumer_count} consumer(s) across {target_count} target(s). "
        f"Estimated {scoping_report.effort.total_min_days:.1f}-{scoping_report.effort.total_max_days:.1f} dev-days.\n"
    )
