"""Scatter CLI entry point — argument parsing and mode dispatch."""

import logging
import time

from scatter.cli_parser import build_parser
from scatter.modes.setup import (
    setup_logging,
    validate_mode_and_format,
    resolve_paths,
    load_config_from_args,
    setup_ai_provider,
    scan_solutions_data,
    load_batch_jobs,
    load_pipeline_csv,
    build_graph_context_if_needed,
    build_mode_context,
)
from scatter.modes import (
    run_dump_index_mode,
    run_git_mode,
    run_graph_mode,
    run_impact_mode,
    run_pr_risk_mode,
    run_sproc_mode,
    run_target_mode,
)


def main():
    start_time = time.monotonic()
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args)

    # Standalone mode — no shared setup needed
    if getattr(args, "dump_index", False):
        run_dump_index_mode(args)
        return

    # Validate mode + format selection
    validate_mode_and_format(args, parser)

    # Shared setup
    paths = resolve_paths(args, parser)
    config = load_config_from_args(args, paths)
    ai_provider, ai_budget = setup_ai_provider(args, config)
    solutions = scan_solutions_data(paths.search_scope)
    batch_jobs = load_batch_jobs(args)
    pipeline_map = load_pipeline_csv(paths.pipeline_csv)
    graph_ctx, graph_enriched = build_graph_context_if_needed(
        args, config, paths.search_scope, solutions.index
    )
    ctx = build_mode_context(
        args,
        paths,
        config,
        ai_provider,
        solutions,
        batch_jobs,
        pipeline_map,
        graph_ctx,
        graph_enriched,
    )

    # Mode dispatch
    if args.branch_name is not None:
        if getattr(args, "pr_risk", False):
            run_pr_risk_mode(args, ctx, start_time)
        else:
            run_git_mode(args, ctx, start_time)
    elif args.target_project is not None:
        run_target_mode(args, ctx, start_time)
    elif args.stored_procedure is not None:
        run_sproc_mode(args, ctx, start_time)
    elif args.sow is not None or args.sow_file is not None:
        run_impact_mode(args, ctx, start_time)
    elif args.graph:
        run_graph_mode(args, ctx, start_time)

    # Log AI budget summary if any calls were made
    if ai_budget and ai_budget.calls_made > 0:
        logging.info(f"AI usage: {ai_budget.summary()}")


if __name__ == "__main__":
    main()
