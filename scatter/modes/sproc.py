"""Stored procedure analysis mode handler."""

from scatter.cli import ModeContext, dispatch_legacy_output, run_sproc_analysis


def run_sproc_mode(args, ctx: ModeContext, start_time: float) -> None:
    """Stored procedure analysis. Reads: args.stored_procedure, args.sproc_regex_pattern"""
    result = run_sproc_analysis(ctx, args.stored_procedure, args.sproc_regex_pattern)

    dispatch_legacy_output(
        result.all_results,
        result.filter_pipeline,
        args,
        ctx.search_scope,
        start_time,
        result.graph_enriched,
        pipeline_map=ctx.pipeline_map,
    )
