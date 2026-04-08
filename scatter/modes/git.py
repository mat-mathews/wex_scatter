"""Git branch analysis mode handler."""

import logging
import sys

from scatter.cli import ModeContext, dispatch_legacy_output, run_git_analysis


def run_git_mode(args, ctx: ModeContext, start_time: float) -> None:
    """Git branch analysis. Reads: args.branch_name, args.base_branch, args.enable_hybrid_git"""
    assert ctx.repo_path is not None, "repo_path must be set for git mode"
    try:
        result = run_git_analysis(
            ctx,
            ctx.repo_path,
            args.branch_name,
            args.base_branch,
            args.enable_hybrid_git,
        )
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
    )
