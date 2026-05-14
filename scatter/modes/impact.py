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

    is_dry_run = getattr(args, "sow_dry_run", False)

    # SOW mode defaults to depth 1 (depth 2 causes massive fan-out on large repos).
    # User can override with --max-depth 2 if they want deeper tracing.
    sow_depth = ctx.config.max_depth
    if getattr(args, "max_depth", None) is None and sow_depth > 1:
        sow_depth = 1
        logging.info("SOW mode: defaulting to --max-depth 1 (use --max-depth 2 for deeper tracing)")

    impact_report = run_impact_analysis(
        sow_text=sow_text,
        search_scope=ctx.search_scope,
        ai_provider=ctx.ai_provider,
        max_depth=sow_depth,
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
        index_max_bytes=ctx.config.ai.index_max_bytes,
        dry_run=is_dry_run,
    )

    if is_dry_run:
        _print_dry_run(impact_report)
        return

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
            # Scoping failure falls back to impact report
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


def _print_dry_run(report) -> None:
    """Print target list for dry-run mode and exit."""
    targets = report.targets
    print(f"\n{'=' * 70}")
    print(f"SOW Dry Run: {len(targets)} target(s) identified")
    print(
        f"Target quality: {report.ambiguity_level} "
        f"(avg confidence {report.avg_target_confidence:.2f})"
    )
    print(f"{'=' * 70}\n")

    if not targets:
        print("No targets identified. Check the SOW text and codebase index.")
        return

    # Header
    print(f"  {'#':<4} {'Name':<50} {'Type':<8} {'Role':<9} {'Conf':<6} {'Resolved'}")
    print(f"  {'─' * 4} {'─' * 50} {'─' * 8} {'─' * 9} {'─' * 6} {'─' * 8}")

    for i, ti in enumerate(targets, 1):
        t = ti.target
        resolved = "yes" if t.csproj_path and t.csproj_path.is_file() else "no"
        name = t.name[:50]
        print(
            f"  {i:<4} {name:<50} {t.target_type:<8} {t.target_role:<9} "
            f"{t.confidence:<6.2f} {resolved}"
        )

    # Evidence section
    print("\n  Evidence:")
    for i, ti in enumerate(targets, 1):
        t = ti.target
        evidence = t.match_evidence or "(none)"
        print(f"  {i:<4} {evidence}")

    print(f"\n{'─' * 70}")
    print("To run full analysis, remove --sow-dry-run.\n")
