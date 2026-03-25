"""Shared setup helpers extracted from __main__.py."""

import csv
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scatter.cli import ModeContext
from scatter.cli_parser import _build_cli_overrides
from scatter.config import ScatterConfig, load_config
from scatter.scanners.solution_scanner import (
    SolutionInfo,
    scan_solutions,
    build_project_to_solutions,
)


@dataclass
class ResolvedPaths:
    search_scope: Path
    repo_path: Optional[Path] = None
    pipeline_csv: Optional[Path] = None


@dataclass
class SolutionData:
    infos: List[SolutionInfo]
    index: Dict
    file_cache: List[Path]


def populate_graph_solutions(graph, solution_index) -> None:
    """Post-process: set node.solutions from the solution reverse index."""
    if not solution_index:
        return
    for node in graph.get_all_nodes():
        matches = solution_index.get(node.name, [])
        node.solutions = sorted(set(si.name for si in matches))


def setup_logging(args) -> None:
    """Configure logging based on --verbose flag."""
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if args.verbose:
        logging.debug("Debug logging enabled.")


def validate_mode_and_format(args, parser) -> None:
    """Validate that a mode was selected, format/mode combinations are valid, and arg constraints hold."""
    is_git_mode = args.branch_name is not None
    is_target_mode = args.target_project is not None
    is_sproc_mode = args.stored_procedure is not None
    is_impact_mode = args.sow is not None or args.sow_file is not None
    is_graph_mode = args.graph

    if not any([is_git_mode, is_target_mode, is_sproc_mode, is_impact_mode, is_graph_mode]):
        parser.error(
            "A mode (--branch-name, --target-project, --stored-procedure, --sow, --sow-file, or --graph) must be selected, or use --dump-index."
        )

    if is_graph_mode and args.output_format == "pipelines":
        parser.error("Pipeline output format is not supported in graph mode.")

    if not is_graph_mode and args.output_format == "mermaid":
        parser.error("Mermaid output format is only supported in graph mode (--graph).")

    if args.output_format == "pipelines" and not args.pipeline_csv:
        logging.warning(
            "--output-format pipelines was requested without --pipeline-csv; output will be empty."
        )

    if args.method_name and not args.class_name:
        logging.warning("Ignoring --method-name because --class-name was not provided.")
        args.method_name = None


def resolve_paths(args, parser) -> ResolvedPaths:
    """Resolve and validate file paths from CLI args.

    Raises SystemExit on invalid paths.
    """
    is_git_mode = args.branch_name is not None
    is_sproc_mode = args.stored_procedure is not None
    is_target_mode = args.target_project is not None
    is_impact_mode = args.sow is not None or args.sow_file is not None
    is_graph_mode = args.graph

    repo_path_abs: Optional[Path] = None
    search_scope_abs: Optional[Path] = None

    try:
        if args.search_scope:
            search_scope_abs = Path(args.search_scope).resolve(strict=True)
            logging.info(f"Using specified search scope: {search_scope_abs}")
        elif is_git_mode:
            repo_path_abs = Path(args.repo_path).resolve(strict=True)
            search_scope_abs = repo_path_abs
            logging.info(f"Using repository path as search scope: {search_scope_abs}")
        elif is_sproc_mode:
            parser.error("--search-scope is required when using --stored-procedure mode.")
        elif is_target_mode:
            parser.error("--search-scope is required when using --target-project mode.")
        elif is_impact_mode:
            parser.error("--search-scope is required when using --sow or --sow-file mode.")
        elif is_graph_mode:
            parser.error("--search-scope is required when using --graph mode.")
        else:
            parser.error(
                "A mode (--branch-name, --target-project, --stored-procedure, --sow, or --sow-file) must be selected."
            )

        if is_sproc_mode:
            if args.repo_path != "." or args.base_branch != "main":
                if (
                    args.repo_path != Path(args.search_scope).resolve(strict=True).as_posix()
                    and args.branch_name is None
                ):
                    logging.warning(
                        "Arguments --repo-path and --base-branch are not applicable in --stored-procedure mode and will be ignored."
                    )

        if is_git_mode:
            if not repo_path_abs:
                repo_path_abs = Path(args.repo_path).resolve(strict=True)

        if is_target_mode:
            target_path_input = Path(args.target_project).resolve()
            if target_path_input.is_dir():
                try:
                    next(target_path_input.glob("*.csproj"))
                    logging.info(f"Found target project in directory: {target_path_input}")
                except StopIteration:
                    raise FileNotFoundError(
                        f"No .csproj file found in the target directory: {target_path_input}"
                    )
            elif target_path_input.is_file() and target_path_input.suffix.lower() == ".csproj":
                logging.info(f"Using target project file: {target_path_input}")
            else:
                raise ValueError(
                    f"Invalid target project path: '{args.target_project}'. Must be a .csproj file or a directory containing one."
                )

        pipeline_csv_path = Path(args.pipeline_csv).resolve() if args.pipeline_csv else None

        if search_scope_abs is None:
            raise ValueError("Search scope could not be determined.")

    except (FileNotFoundError, ValueError) as e:
        logging.error(f"Input validation failed: {e}")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        logging.error(f"Unexpected error during input validation: {e}")
        sys.exit(1)

    return ResolvedPaths(
        search_scope=search_scope_abs,
        repo_path=repo_path_abs,
        pipeline_csv=pipeline_csv_path,
    )


def load_config_from_args(args, paths: ResolvedPaths) -> ScatterConfig:
    """Load config using resolved paths and CLI overrides."""
    cli_overrides = _build_cli_overrides(args)
    return load_config(repo_root=paths.search_scope, cli_overrides=cli_overrides)


def setup_ai_provider(args, config):
    """Configure AI provider if needed by the selected mode. Returns provider or None.

    Note: AIRouter is only instantiated when AI features are requested.
    Its __init__ has no side effects (just stores config), so this is safe.
    """
    from scatter.ai.router import AIRouter

    is_impact_mode = args.sow is not None or args.sow_file is not None

    ai_provider = None
    if args.summarize_consumers or args.enable_hybrid_git or is_impact_mode:
        reason = []
        if args.summarize_consumers:
            reason.append("summarization")
        if args.enable_hybrid_git:
            reason.append("hybrid git analysis")
        if is_impact_mode:
            reason.append("impact analysis")
        logging.info(f"{', '.join(reason).capitalize()} enabled. Configuring AI provider...")
        router = AIRouter(config)
        ai_provider = router.get_provider()
        if ai_provider is None:
            logging.error("AI provider configuration failed.")
            if args.summarize_consumers:
                logging.error("Summarization will be disabled.")
                args.summarize_consumers = False
            if args.enable_hybrid_git:
                logging.warning("Hybrid git analysis will fall back to regex extraction.")
                args.enable_hybrid_git = False
            if is_impact_mode:
                print(
                    "\nImpact analysis (--sow) requires a Google API key for work request parsing.\n"
                    "\n"
                    "  Set the GOOGLE_API_KEY environment variable:\n"
                    "    export GOOGLE_API_KEY=your-key-here\n"
                    "\n"
                    "  Or use a mode that doesn't require AI:\n"
                    "    scatter --target-project ./MyApp/MyApp.csproj --search-scope .\n"
                    "    scatter --branch-name feature/my-branch --search-scope .\n"
                    "    scatter --graph --search-scope .\n",
                    file=sys.stderr,
                )
                sys.exit(1)

    return ai_provider


def scan_solutions_data(search_scope: Path) -> SolutionData:
    """Scan for .sln files and build solution index."""
    logging.info("\n--- Caching solution files ---")
    solution_infos: List[SolutionInfo] = []
    solution_index: Dict = {}
    solution_file_cache: List[Path] = []

    logging.info(f"Scanning for .sln files within '{search_scope}'...")
    try:
        solution_infos = scan_solutions(search_scope)
        solution_index = build_project_to_solutions(solution_infos)
        solution_file_cache = [si.path for si in solution_infos]
        logging.info(f"Found {len(solution_infos)} solution files")
    except Exception as e:
        logging.error(f"An error occurred while scanning for solution files: {e}")

    return SolutionData(infos=solution_infos, index=solution_index, file_cache=solution_file_cache)


def load_batch_jobs(args) -> Dict[str, List[str]]:
    """Load batch job mapping from app-config repo if --app-config-path provided."""
    from scatter.compat.v1_bridge import map_batch_jobs_from_config_repo

    batch_job_map: Dict[str, List[str]] = {}
    if args.app_config_path:
        logging.info("\n--- Loading batch job data from app-config repo ---")
        try:
            app_config_repo_path = Path(args.app_config_path).resolve(strict=True)
            batch_job_map = map_batch_jobs_from_config_repo(app_config_repo_path)
        except FileNotFoundError:
            logging.error(f"The provided --app-config-path does not exist: {args.app_config_path}")
        except Exception as e:
            logging.error(f"An error occurred processing the --app-config-path: {e}")
    return batch_job_map


def load_pipeline_csv(csv_path: Optional[Path]) -> Dict[str, str]:
    """Load pipeline-to-application mapping from CSV file."""
    logging.info("\n--- Loading pipeline data ---")
    pipeline_map: Dict[str, str] = {}
    if csv_path:
        if not csv_path.is_file():
            logging.warning(
                f"Pipeline CSV file not found: {csv_path}. Proceeding without pipeline data."
            )
        else:
            try:
                with open(csv_path, mode="r", newline="", encoding="utf-8-sig") as csvfile:
                    reader = csv.DictReader(csvfile)
                    required_headers = {"Application Name", "Pipeline Name"}
                    if not required_headers.issubset(reader.fieldnames or set()):
                        missing = required_headers - set(reader.fieldnames or [])
                        logging.error(
                            f"Pipeline CSV missing required columns: {', '.join(missing)}. Proceeding without pipeline data."
                        )
                    else:
                        loaded_count = 0
                        duplicate_count = 0
                        for row in reader:
                            app_name = row.get("Application Name", "").strip()
                            pipe_name = row.get("Pipeline Name", "").strip()
                            if app_name and pipe_name:
                                if app_name in pipeline_map:
                                    duplicate_count += 1
                                    logging.debug(
                                        f"Duplicate application '{app_name}' in pipeline CSV. Overwriting."
                                    )
                                pipeline_map[app_name] = pipe_name
                                loaded_count += 1
                        log_msg = f"Loaded {loaded_count} pipeline mappings."
                        if duplicate_count > 0:
                            log_msg += f" ({duplicate_count} duplicate application names found, last entry used)."
                        logging.info(log_msg)

            except Exception as e:
                logging.error(
                    f"Error loading pipeline CSV '{csv_path}': {e}. Proceeding without pipeline data."
                )
    else:
        logging.info("No pipeline CSV provided.")
    return pipeline_map


def build_graph_context_if_needed(args, config, search_scope, solution_index) -> Tuple:
    """Build graph context from cache or on demand. Returns (graph_ctx, graph_enriched)."""
    graph_ctx = None
    graph_enriched = False
    if not args.no_graph and search_scope and not args.graph:
        from scatter.store.graph_cache import cache_exists
        from scatter.analyzers.graph_enrichment import build_graph_context

        if args.graph_metrics or cache_exists(search_scope, config.graph.cache_dir):
            graph_ctx = build_graph_context(
                search_scope, config, args, solution_index=solution_index
            )
            if graph_ctx:
                graph_enriched = True
            elif args.graph_metrics:
                logging.warning("Graph context unavailable. Proceeding without graph metrics.")

    return graph_ctx, graph_enriched


def build_mode_context(
    args,
    paths,
    config,
    ai_provider,
    solutions,
    batch_jobs,
    pipeline_map,
    graph_ctx,
    graph_enriched,
) -> ModeContext:
    """Assemble ModeContext from resolved components."""
    return ModeContext(
        search_scope=paths.search_scope,
        config=config,
        pipeline_map=pipeline_map,
        solution_file_cache=solutions.file_cache,
        batch_job_map=batch_jobs,
        ai_provider=ai_provider,
        repo_path=paths.repo_path,
        graph_ctx=graph_ctx,
        solution_index=solutions.index,
        graph_enriched=graph_enriched,
        class_name=args.class_name,
        method_name=args.method_name,
        target_namespace=args.target_namespace,
        summarize_consumers=args.summarize_consumers,
        max_workers=args.max_workers,
        chunk_size=args.chunk_size,
        disable_multiprocessing=args.disable_multiprocessing,
        cs_analysis_chunk_size=args.cs_analysis_chunk_size,
        csproj_analysis_chunk_size=args.csproj_analysis_chunk_size,
        no_graph=args.no_graph,
    )
