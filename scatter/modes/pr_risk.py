"""PR risk analysis mode handler."""

import logging
import sys
from pathlib import Path

from scatter.cli import ModeContext, _build_metadata, _require_output_file

_SUPPORTED_FORMATS = {"console", "json", "markdown"}


def run_pr_risk_mode(args, ctx: ModeContext, start_time: float) -> None:
    """PR risk analysis. Reads: args.branch_name, args.base_branch, args.output_format, args.output_file"""
    from scatter.analyzers.pr_risk_analyzer import analyze_pr_risk

    assert ctx.repo_path is not None, "repo_path must be set for pr-risk mode"

    if args.output_format not in _SUPPORTED_FORMATS:
        logging.error(
            f"--pr-risk does not support --output-format {args.output_format}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_FORMATS))}."
        )
        sys.exit(1)

    try:
        report = analyze_pr_risk(
            repo_path=ctx.repo_path,
            branch_name=args.branch_name,
            base_branch=args.base_branch,
            graph_ctx=ctx.graph_ctx,
        )
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    # Output dispatch
    if args.output_format == "json":
        from scatter.reports.json_reporter import write_pr_risk_json_report

        output_path = _require_output_file(args, "JSON")
        metadata = _build_metadata(
            args, ctx.search_scope, start_time, graph_enriched=ctx.graph_enriched
        )
        write_pr_risk_json_report(report, output_path, metadata=metadata)

    elif args.output_format == "markdown":
        from scatter.reports.pr_comment_reporter import build_pr_risk_markdown

        md = build_pr_risk_markdown(report, collapsible=getattr(args, "collapsible", False))
        if args.output_file:
            output_path = Path(args.output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(md, encoding="utf-8")
            logging.info(f"Wrote PR risk markdown to: {output_path}")
        else:
            print(md)

    else:
        from scatter.reports.console_reporter import print_pr_risk_report

        print_pr_risk_report(report)
