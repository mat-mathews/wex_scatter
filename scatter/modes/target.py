"""Target project analysis mode handler."""

import logging
import sys
from pathlib import Path

from scatter.analysis import ModeContext, run_target_analysis
from scatter.output import dispatch_legacy_output


def run_target_mode(args, ctx: ModeContext, start_time: float) -> None:
    """Target project analysis. Reads: args.target_project"""
    target_path_input = Path(args.target_project).resolve()
    if target_path_input.is_dir():
        try:
            target_csproj = next(target_path_input.glob("*.csproj"))
        except StopIteration:
            logging.error(f"No .csproj file found in directory: {target_path_input}")
            sys.exit(1)
    else:
        target_csproj = target_path_input

    try:
        result = run_target_analysis(ctx, target_csproj)
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    dispatch_legacy_output(
        result.all_results,
        result.filter_pipeline,
        args,
        ctx.search_scope,
        start_time,
        result.graph_enriched,
        pipeline_map=ctx.pipeline_map,
        ai_provider=ctx.ai_provider,
        graph_ctx=ctx.graph_ctx,
    )
