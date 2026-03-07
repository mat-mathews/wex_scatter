"""Scatter CLI entry point — argument parsing and mode dispatch."""
import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from scatter.core.models import DEFAULT_MAX_WORKERS, DEFAULT_CHUNK_SIZE
from scatter.core.parallel import find_files_with_pattern_parallel
from scatter.scanners.type_scanner import extract_type_names_from_content
from scatter.scanners.project_scanner import derive_namespace
from scatter.scanners.sproc_scanner import find_cs_files_referencing_sproc
from scatter.analyzers.consumer_analyzer import find_consumers
from scatter.analyzers.git_analyzer import (
    analyze_branch_changes,
    get_diff_for_file,
)
from scatter.compat.v1_bridge import (
    _process_consumer_summaries_and_append_results,
    map_batch_jobs_from_config_repo,
)
from scatter.reports.console_reporter import print_console_report
from scatter.reports.json_reporter import prepare_detailed_results, write_json_report
from scatter.reports.csv_reporter import write_csv_report

from scatter.config import load_config
from scatter.ai.router import AIRouter


def _build_cli_overrides(args) -> Dict[str, Any]:
    """Extract CLI args that override config values.

    Only includes keys the user explicitly passed on the command line.
    Argparse defaults are None for optional args so we can distinguish
    "not passed" from "passed the default value".
    """
    overrides: Dict[str, Any] = {}
    if args.google_api_key is not None:
        overrides["ai.credentials.gemini.api_key"] = args.google_api_key
    if args.gemini_model is not None:
        overrides["ai.gemini_model"] = args.gemini_model
    if args.disable_multiprocessing:
        overrides["multiprocessing.disabled"] = True
    if args.max_depth is not None:
        overrides["search.max_depth"] = args.max_depth
    return overrides


def main():
    parser = argparse.ArgumentParser(
        description="Analyzes .NET project consumers based on Git branch changes OR a specific target project. Can optionally summarize consumer files using Gemini API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- mode selection ---
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--target-project",
        help="MODE: Target Project Analysis. Path to the .csproj file or directory of the specific project to analyze."
    )
    mode_group.add_argument(
        "--branch-name",
        help="MODE: Git Branch Analysis. Name of the feature branch to analyze changes on."
    )

    mode_group.add_argument(
        "--stored-procedure",
        metavar="SPROC_NAME",
        help="MODE: Stored Procedure Analysis. Name of the stored procedure to find references to (e.g., 'usp_MyProcedure' or 'dbo.usp_MyProcedure'). Requires --search-scope."
    )
    mode_group.add_argument(
        "--sow",
        metavar="DESCRIPTION",
        help="MODE: Impact Analysis. Inline work request text describing the change."
    )
    mode_group.add_argument(
        "--sow-file",
        metavar="FILE",
        help="MODE: Impact Analysis. Path to file containing the work request text."
    )

    #--- sproc group ---
    sproc_group = parser.add_argument_group('Stored Procedure Analysis Options (Requires --stored-procedure)')
    sproc_group.add_argument(
        "--sproc-regex-pattern",
        default=None,
        help="(Optional) Custom Python regex pattern to find stored procedure names in C# files. If not provided, a default pattern is used. Example: \"MyCustomPatternFor_(?P<sproc>{sproc_name_placeholder})\" where {sproc_name_placeholder} will be replaced by the escaped sproc name."
    )

    # --- git mode specific arguments ---
    git_group = parser.add_argument_group('Git Branch Analysis Options (Requires --branch-name)')
    git_group.add_argument(
        "-r", "--repo-path", default=".",
        help="Path to the Git repository (default: current directory)."
    )
    git_group.add_argument(
        "-b", "--base-branch", default="main",
        help="Base branch to compare against (default: main)."
    )
    git_group.add_argument(
        "--enable-hybrid-git", action="store_true",
        help="Enable LLM-enhanced diff analysis for more precise symbol extraction (requires Gemini API key)."
    )

    common_group = parser.add_argument_group('Common Options')
    common_group.add_argument(
        "--search-scope",
        help="Root directory to search for consuming projects (defaults to --repo-path if Git mode is used and this is omitted, otherwise REQUIRED)."
    )
    common_group.add_argument(
        "--max-depth", type=int, default=None,
        help="Maximum transitive tracing depth for impact analysis (default: 2)."
    )
    common_group.add_argument(
        "--app-config-path",
        help="(Optional) Path to the 'health-benefits-app-config' repository to resolve specific batch job names."
    )
    common_group.add_argument(
        "--class-name", default=None,
        help="(Optional) Filter: In Git mode, analyze only this type if found in changes. In Target Project mode, check for usage of this specific type."
    )
    common_group.add_argument(
        "--method-name", default=None,
        help="(Optional) Filter: Check for usage of this specific method name. Requires --class-name to be specified."
    )
    common_group.add_argument(
        "--target-namespace", default=None,
        help="(Optional) Explicitly specify the target project's namespace. Overrides automatic derivation (mainly useful in Target Project mode)."
    )
    common_group.add_argument(
        "--pipeline-csv", default=None,
        help="(Optional) Path to CSV mapping 'Project Name' to 'Pipeline Name'."
    )
    common_group.add_argument(
        "--output-file", default=None,
        help="(Optional) Path to write results to a file. The format is determined by --output-format."
    )
    common_group.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable detailed DEBUG level logging."
    )
    summarize_group = parser.add_argument_group('Summarization Options (using Google Gemini)')
    summarize_group.add_argument(
        "--summarize-consumers", action="store_true",
        help="Enable summarization of relevant C# files in consuming projects using the Gemini API."
    )
    summarize_group.add_argument(
        "--google-api-key", default=None,
        help="Google API Key for Gemini. If not provided, uses the GOOGLE_API_KEY environment variable."
    )
    summarize_group.add_argument(
        "--gemini-model", default=None,
        help="The Gemini model to use for summarization (default: gemini-1.5-flash)."
    )
    common_group.add_argument(
        "--output-format", default="console",
        choices=['console', 'csv', 'json'],
        help="Format for the output. 'console' prints to screen. 'csv' or 'json' requires --output-file."
    )

    # Multiprocessing options
    multiprocessing_group = parser.add_argument_group('Multiprocessing Options')
    multiprocessing_group.add_argument(
        "--disable-multiprocessing", action="store_true",
        help="Disable parallel processing and use sequential file discovery."
    )
    multiprocessing_group.add_argument(
        "--max-workers", type=int, default=DEFAULT_MAX_WORKERS,
        help=f"Maximum number of worker processes for parallel operations (default: {DEFAULT_MAX_WORKERS})."
    )
    multiprocessing_group.add_argument(
        "--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
        help=f"Number of directories to process per worker chunk (default: {DEFAULT_CHUNK_SIZE})."
    )
    multiprocessing_group.add_argument(
        "--cs-analysis-chunk-size", type=int, default=50,
        help="Number of .cs files per worker batch for content analysis (default: 50)."
    )
    multiprocessing_group.add_argument(
        "--csproj-analysis-chunk-size", type=int, default=25,
        help="Number of .csproj files per worker batch for XML parsing (default: 25)."
    )

    args = parser.parse_args()

    # --- setup logging ---
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if args.verbose:
        logging.debug("Debug logging enabled.")

    is_git_mode = args.branch_name is not None
    is_target_mode = args.target_project is not None
    is_sproc_mode = args.stored_procedure is not None
    is_impact_mode = args.sow is not None or args.sow_file is not None

    # --- load config and configure AI provider ---
    cli_overrides = _build_cli_overrides(args)
    # Resolve without strict=True — config loading tolerates missing dirs.
    # The real path validation with strict=True happens below.
    config_root = Path(args.search_scope).resolve() if args.search_scope else Path(args.repo_path).resolve()
    config = load_config(repo_root=config_root, cli_overrides=cli_overrides)
    router = AIRouter(config)

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
                logging.error("Impact analysis requires a working AI provider. Exiting.")
                sys.exit(1)

    repo_path_abs: Optional[Path] = None
    search_scope_abs: Optional[Path] = None
    target_csproj_abs_path: Optional[Path] = None

    try:
        # validate search scope
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
        else:
            parser.error("A mode (--branch-name, --target-project, --stored-procedure, --sow, or --sow-file) must be selected.")

        if is_sproc_mode:
            if args.repo_path != "." or args.base_branch != "main":
                if args.repo_path != Path(args.search_scope).resolve(strict=True).as_posix() and args.branch_name is None:
                    logging.warning("Arguments --repo-path and --base-branch are not applicable in --stored-procedure mode and will be ignored.")

        if is_git_mode:
            if not repo_path_abs:
                repo_path_abs = Path(args.repo_path).resolve(strict=True)

        if is_target_mode:
            target_path_input = Path(args.target_project).resolve()
            if target_path_input.is_dir():
                try:
                    target_csproj_abs_path = next(target_path_input.glob('*.csproj'))
                    logging.info(f"Found target project file: {target_csproj_abs_path}")
                except StopIteration:
                    raise FileNotFoundError(f"No .csproj file found in the target directory: {target_path_input}")
            elif target_path_input.is_file() and target_path_input.suffix.lower() == '.csproj':
                target_csproj_abs_path = target_path_input
                logging.info(f"Using target project file: {target_csproj_abs_path}")
            else:
                raise ValueError(f"Invalid target project path: '{args.target_project}'. Must be a .csproj file or a directory containing one.")

        output_file_path = Path(args.output_file).resolve() if args.output_file else None
        pipeline_csv_path = Path(args.pipeline_csv).resolve() if args.pipeline_csv else None

        if args.method_name and not args.class_name:
            logging.warning("Ignoring --method-name because --class-name was not provided.")
            args.method_name = None

        if search_scope_abs is None:
            raise ValueError("Search scope could not be determined.")

    except (FileNotFoundError, ValueError) as e:
        logging.error(f"Input validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during input validation: {e}")
        sys.exit(1)

    # --- Step 1: Cache all solution files ---
    logging.info(f"\n--- Caching solution files ---")
    solution_file_cache: List[Path] = []
    if search_scope_abs:
        logging.info(f"Scanning for .sln files within '{search_scope_abs}'...")
        try:
            solution_file_cache = find_files_with_pattern_parallel(
                search_scope_abs, '*.sln',
                max_workers=args.max_workers,
                chunk_size=args.chunk_size,
                disable_multiprocessing=args.disable_multiprocessing
            )
            logging.info(f"Found {len(solution_file_cache)} solution files")
        except Exception as e:
            logging.error(f"An error occurred while scanning for solution files: {e}")
    else:
        logging.warning("Search scope not defined, cannot cache solution files.")

    # --- Load batch job mapping if app-config-path is provided ---
    batch_job_map: Dict[str, List[str]] = {}
    if args.app_config_path:
        logging.info(f"\n--- Loading batch job data from app-config repo ---")
        try:
            app_config_repo_path = Path(args.app_config_path).resolve(strict=True)
            batch_job_map = map_batch_jobs_from_config_repo(app_config_repo_path)
        except FileNotFoundError:
            logging.error(f"The provided --app-config-path does not exist: {args.app_config_path}")
        except Exception as e:
            logging.error(f"An error occurred processing the --app-config-path: {e}")

    # --- load pipeline data ---
    logging.info(f"\n--- Loading pipeline data ---")
    pipeline_map: Dict[str, str] = {}
    if pipeline_csv_path:
        if not pipeline_csv_path.is_file():
            logging.warning(f"Pipeline CSV file not found: {pipeline_csv_path}. Proceeding without pipeline data.")
        else:
            try:
                with open(pipeline_csv_path, mode='r', newline='', encoding='utf-8-sig') as csvfile:
                    reader = csv.DictReader(csvfile)
                    required_headers = {'Application Name', 'Pipeline Name'}
                    if not required_headers.issubset(reader.fieldnames or set()):
                        missing = required_headers - set(reader.fieldnames or [])
                        logging.error(f"Pipeline CSV missing required columns: {', '.join(missing)}. Proceeding without pipeline data.")
                    else:
                        loaded_count = 0
                        duplicate_count = 0
                        for row in reader:
                            app_name = row.get('Application Name','').strip()
                            pipe_name = row.get('Pipeline Name','').strip()
                            if app_name and pipe_name:
                                if app_name in pipeline_map:
                                    duplicate_count += 1
                                    logging.debug(f"Duplicate application '{app_name}' in pipeline CSV. Overwriting.")
                                pipeline_map[app_name] = pipe_name
                                loaded_count += 1
                        log_msg = f"Loaded {loaded_count} pipeline mappings."
                        if duplicate_count > 0: log_msg += f" ({duplicate_count} duplicate application names found, last entry used)."
                        logging.info(log_msg)

            except Exception as e:
                logging.error(f"Error loading pipeline CSV '{pipeline_csv_path}': {e}. Proceeding without pipeline data.")
    else:
        logging.info("No pipeline CSV provided.")


    # --- main logic ---
    all_results: List[Dict[str, Union[str, Dict, List[str]]]] = []

    # == GIT BRANCH ANALYSIS MODE ==
    if is_git_mode:
        assert repo_path_abs is not None and search_scope_abs is not None
        logging.info(f"\n--- Running Git Branch Analysis Mode ---")
        logging.info(f"Comparing branch '{args.branch_name}' against base '{args.base_branch}' in repo '{repo_path_abs}'")

        logging.info(f"Step 1: Analyzing Git changes...")
        changed_projects_dict = analyze_branch_changes(str(repo_path_abs), args.branch_name, args.base_branch)

        if not changed_projects_dict:
            logging.info("No projects with changed C# files found. Exiting.")
        else:
            logging.info("\nStep 2: Extracting type declarations from changed C# files...")
            types_by_project: Dict[str, Set[str]] = defaultdict(set)
            files_processed_count = 0
            types_extracted_count = 0

            for proj_rel_path_str, cs_rel_paths_str in changed_projects_dict.items():
                logging.debug(f"Processing project for type extraction: {proj_rel_path_str}")
                project_types = set()
                for cs_rel_path_str in cs_rel_paths_str:
                    cs_abs_path = (repo_path_abs / cs_rel_path_str).resolve()
                    files_processed_count += 1
                    logging.debug(f"   Reading file: {cs_abs_path}")
                    if cs_abs_path.is_file():
                        try:
                            content = cs_abs_path.read_text(encoding='utf-8', errors='ignore')
                            extracted = None

                            if args.enable_hybrid_git and ai_provider:
                                diff_text = get_diff_for_file(
                                    str(repo_path_abs), cs_rel_path_str,
                                    args.branch_name, args.base_branch)
                                if diff_text:
                                    extracted = ai_provider.extract_affected_symbols(
                                        content, diff_text, cs_rel_path_str)
                                    if extracted is None:
                                        logging.warning(f"LLM analysis failed for {cs_rel_path_str}, falling back to regex extraction.")
                                        extracted = extract_type_names_from_content(content)
                                else:
                                    logging.debug(f"No diff found for {cs_rel_path_str}, using regex extraction.")
                                    extracted = extract_type_names_from_content(content)
                            else:
                                extracted = extract_type_names_from_content(content)

                            if extracted:
                                logging.debug(f"     Found types in {cs_rel_path_str}: {', '.join(extracted)}")
                                project_types.update(extracted)
                        except OSError as e:
                            logging.warning(f"Could not read C# file {cs_abs_path}: {e}")
                    else:
                        logging.warning(f"Changed C# file not found on disk (might be deleted/moved): {cs_abs_path}")

                if project_types:
                    types_by_project[proj_rel_path_str] = project_types
                    types_extracted_count += len(project_types)

            logging.info(f"Processed {files_processed_count} changed C# files.")
            if not types_by_project:
                logging.info("No type declarations found in the changed files. Cannot perform type-based consumer analysis.")
            else:
                logging.info(f"Found {types_extracted_count} unique type declaration(s) across {len(types_by_project)} project(s).")

                logging.info(f"\nStep 3: Analyzing consumers...")
                processed_targets_count = 0
                for target_project_rel_path_str, extracted_types in types_by_project.items():
                    processed_targets_count += 1
                    target_csproj_abs_git_mode = (repo_path_abs / target_project_rel_path_str).resolve()
                    target_project_name_git_mode = target_csproj_abs_git_mode.stem

                    logging.info(f"\n--- Analyzing Target Project {processed_targets_count}/{len(types_by_project)}: {target_project_name_git_mode} ({target_project_rel_path_str}) ---")

                    if not target_csproj_abs_git_mode.is_file():
                        logging.warning(f"Target project file '{target_csproj_abs_git_mode}' not found on disk. Skipping.")
                        continue

                    target_namespace_str_git_mode = derive_namespace(target_csproj_abs_git_mode)
                    if not target_namespace_str_git_mode:
                        logging.warning(f"Could not derive namespace for {target_project_name_git_mode}. Consumer analysis may be incomplete.")
                        target_namespace_str_git_mode = f"NAMESPACE_ERROR_{target_project_name_git_mode}"

                    types_to_analyze: Set[str]
                    if args.class_name:
                        if args.class_name in extracted_types:
                            types_to_analyze = {args.class_name}
                            logging.info(f"Filtering analysis to explicitly provided type (found in changes): '{args.class_name}'")
                        else:
                            logging.info(f"Explicitly provided type '{args.class_name}' was NOT found in changed files. Skipping.")
                            types_to_analyze = set()
                    else:
                        types_to_analyze = extracted_types
                        logging.info(f"Analyzing consumers for {len(types_to_analyze)} types detected in changed files: {', '.join(sorted(types_to_analyze))}")

                    if not types_to_analyze:
                        continue

                    for type_name_to_check in sorted(list(types_to_analyze)):
                        logging.info(f"   Checking for consumers of type: '{type_name_to_check}'...")

                        method_filter = args.method_name if args.class_name == type_name_to_check else None
                        if method_filter:
                            logging.info(f"     (Including method filter: '{method_filter}')")

                        final_consumers_data = find_consumers(
                            target_csproj_abs_git_mode,
                            search_scope_abs,
                            target_namespace_str_git_mode,
                            type_name_to_check,
                            method_filter,
                            max_workers=args.max_workers,
                            chunk_size=args.chunk_size,
                            disable_multiprocessing=args.disable_multiprocessing,
                            cs_analysis_chunk_size=args.cs_analysis_chunk_size,
                            csproj_analysis_chunk_size=args.csproj_analysis_chunk_size
                        )

                        if final_consumers_data:
                            try:
                                target_proj_rel_for_git_report = target_csproj_abs_git_mode.relative_to(repo_path_abs).as_posix()
                            except ValueError:
                                target_proj_rel_for_git_report = target_csproj_abs_git_mode.as_posix()

                            _process_consumer_summaries_and_append_results(
                                target_project_name=target_project_name_git_mode,
                                target_project_rel_path_str=target_proj_rel_for_git_report,
                                triggering_info=type_name_to_check,
                                final_consumers_data=final_consumers_data,
                                all_results_list=all_results,
                                pipeline_map_dict=pipeline_map,
                                solution_file_cache=solution_file_cache,
                                batch_job_map=batch_job_map,
                                search_scope_path_abs=search_scope_abs,
                                ai_provider=ai_provider)

                        else:
                            logging.info(f"     No consumers found for type '{type_name_to_check}' in project '{target_project_name_git_mode}'.")

    # == TARGET PROJECT ANALYSIS MODE ==
    elif is_target_mode:
        assert target_csproj_abs_path is not None and search_scope_abs is not None
        logging.info(f"\n--- Running Target Project Analysis Mode ---")
        target_project_name = target_csproj_abs_path.stem
        logging.info(f"Analyzing target project: {target_project_name} ({target_csproj_abs_path})")

        logging.info("Step 1: Determining target namespace...")
        target_namespace_str = args.target_namespace
        if not target_namespace_str:
            target_namespace_str = derive_namespace(target_csproj_abs_path)

        if not target_namespace_str:
            logging.error("Could not derive target namespace. Please specify it using --target-namespace.")
            sys.exit(1)
        logging.info(f"Using target namespace: '{target_namespace_str}'")

        logging.info("\nStep 2: Analyzing consumers...")
        final_consumers_data = find_consumers(
            target_csproj_abs_path,
            search_scope_abs,
            target_namespace_str,
            args.class_name,
            args.method_name,
            max_workers=args.max_workers,
            chunk_size=args.chunk_size,
            disable_multiprocessing=args.disable_multiprocessing,
            cs_analysis_chunk_size=args.cs_analysis_chunk_size,
            csproj_analysis_chunk_size=args.csproj_analysis_chunk_size
        )

        if final_consumers_data:
            logging.info(f"Found {len(final_consumers_data)} consumer(s) matching criteria for target '{target_project_name}'.")
            trigger_level = 'N/A (Project Reference)'
            if args.method_name and args.class_name: trigger_level = f"{args.class_name}.{args.method_name}"
            elif args.class_name: trigger_level = args.class_name

            try:
                target_rel_path_for_report = target_csproj_abs_path.relative_to(search_scope_abs).as_posix()
            except ValueError:
                target_rel_path_for_report = target_csproj_abs_path.as_posix()

            _process_consumer_summaries_and_append_results(
                target_project_name=target_project_name,
                target_project_rel_path_str=target_rel_path_for_report,
                triggering_info=trigger_level,
                final_consumers_data=final_consumers_data,
                all_results_list=all_results,
                pipeline_map_dict=pipeline_map,
                solution_file_cache=solution_file_cache,
                batch_job_map=batch_job_map,
                search_scope_path_abs=search_scope_abs,
                ai_provider=ai_provider
            )
        else:
            logging.info(f"No consuming projects matching the criteria were found for target '{target_project_name}'.")

    # == STORED PROCEDURE ANALYSIS MODE ==
    elif is_sproc_mode:
        assert search_scope_abs is not None
        logging.info(f"\n--- Running Stored Procedure Analysis Mode ---")
        sproc_name_arg = args.stored_procedure
        logging.info(f"Identifying projects/classes referencing stored procedure: '{sproc_name_arg}' within scope '{search_scope_abs}'")

        project_class_sproc_map = find_cs_files_referencing_sproc(
            sproc_name_arg,
            search_scope_abs,
            args.sproc_regex_pattern,
            max_workers=args.max_workers,
            chunk_size=args.chunk_size,
            disable_multiprocessing=args.disable_multiprocessing,
            cs_analysis_chunk_size=args.cs_analysis_chunk_size
        )

        if not project_class_sproc_map:
            logging.info(f"No projects/classes found referencing stored procedure '{sproc_name_arg}'. Exiting.")
            sys.exit(0)

        total_classes_found = sum(len(classes) for classes in project_class_sproc_map.values())
        logging.info(f"Found {total_classes_found} class(es) across {len(project_class_sproc_map)} project(s) referencing sproc '{sproc_name_arg}'.")

        processed_targets_count = 0

        for target_csproj_abs, classes_dict in project_class_sproc_map.items():
            target_project_name_sproc_mode = target_csproj_abs.stem
            try:
                target_project_rel_path_str = target_csproj_abs.relative_to(search_scope_abs).as_posix()
            except ValueError:
                target_project_rel_path_str = target_csproj_abs.as_posix()

            target_namespace_str_sproc_mode = args.target_namespace or derive_namespace(target_csproj_abs)
            if not target_namespace_str_sproc_mode:
                logging.warning(f"Could not derive namespace for {target_project_name_sproc_mode}. Consumer analysis may be incomplete.")
                target_namespace_str_sproc_mode = f"NAMESPACE_ERROR_{target_project_name_sproc_mode}"

            for class_containing_sproc, cs_files_with_sproc_call in classes_dict.items():
                processed_targets_count += 1

                class_filter_user = args.class_name
                if class_filter_user and class_filter_user != class_containing_sproc:
                    logging.debug(f"Skipping analysis for class '{class_containing_sproc}' because it doesn't match --class-name '{class_filter_user}'.")
                    continue

                method_filter_sproc = args.method_name if class_filter_user and class_filter_user == class_containing_sproc else None

                logging.info(f"\n--- Analyzing Consumers for Class {processed_targets_count}/{total_classes_found}: '{class_containing_sproc}' in Project: {target_project_name_sproc_mode} ---")

                report_trigger_info = f"{class_containing_sproc} (via Sproc: {sproc_name_arg})"
                if method_filter_sproc:
                    report_trigger_info = f"{class_containing_sproc}.{method_filter_sproc} (via Sproc: {sproc_name_arg})"

                final_consumers_data = find_consumers(
                    target_csproj_path=target_csproj_abs,
                    search_scope_path=search_scope_abs,
                    target_namespace=target_namespace_str_sproc_mode,
                    class_name=class_containing_sproc,
                    method_name=method_filter_sproc,
                    max_workers=args.max_workers,
                    chunk_size=args.chunk_size,
                    disable_multiprocessing=args.disable_multiprocessing,
                    cs_analysis_chunk_size=args.cs_analysis_chunk_size,
                    csproj_analysis_chunk_size=args.csproj_analysis_chunk_size
                )

                _process_consumer_summaries_and_append_results(
                    target_project_name=target_project_name_sproc_mode,
                    target_project_rel_path_str=target_project_rel_path_str,
                    triggering_info=report_trigger_info,
                    final_consumers_data=final_consumers_data,
                    all_results_list=all_results,
                    pipeline_map_dict=pipeline_map,
                    solution_file_cache=solution_file_cache,
                    batch_job_map=batch_job_map,
                    search_scope_path_abs=search_scope_abs,
                    ai_provider=ai_provider)

    # == IMPACT ANALYSIS MODE ==
    elif is_impact_mode:
        assert search_scope_abs is not None
        logging.info(f"\n--- Running Impact Analysis Mode ---")

        # Resolve SOW text
        if args.sow_file:
            try:
                sow_file_path = Path(args.sow_file).resolve(strict=True)
                sow_text = sow_file_path.read_text(encoding='utf-8')
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
            search_scope=search_scope_abs,
            ai_provider=ai_provider,
            max_depth=config.max_depth,
            pipeline_map=pipeline_map,
            solution_file_cache=solution_file_cache,
            max_workers=args.max_workers,
            chunk_size=args.chunk_size,
            disable_multiprocessing=args.disable_multiprocessing,
            cs_analysis_chunk_size=args.cs_analysis_chunk_size,
            csproj_analysis_chunk_size=args.csproj_analysis_chunk_size,
        )

        # Output impact report (separate from legacy all_results path)
        if args.output_format == 'json':
            if not args.output_file:
                logging.error("JSON output format requires the --output-file argument.")
                sys.exit(1)
            write_impact_json_report(impact_report, Path(args.output_file))
        elif args.output_format == 'csv':
            if not args.output_file:
                logging.error("CSV output format requires the --output-file argument.")
                sys.exit(1)
            write_impact_csv_report(impact_report, Path(args.output_file))
        else:
            print_impact_report(impact_report)

        print("\ndone.\n")
        return

    # --- step: output combined results ---
    logging.info(f"\n\n\n################################################################\n\n")
    logging.info(f"\n--- Consolidating and reporting results ---")
    if not all_results:
        logging.info("Overall analysis complete. No consuming relationships matching the criteria were found.")
    else:
        logging.info(f"Overall analysis complete. Found {len(all_results)} consuming relationship(s) matching the criteria.")
        all_results.sort(key=lambda x: (x.get('TargetProjectName',''), x.get('TriggeringType',''), x.get('ConsumerProjectName','')))

    # Handle JSON Output
    if args.output_format == 'json':
        if not args.output_file:
            logging.error("JSON output format requires the --output-file argument.")
            sys.exit(1)
        detailed = prepare_detailed_results(all_results)
        write_json_report(detailed, Path(args.output_file))

    # Handle CSV Output
    elif args.output_format == 'csv':
        if not args.output_file:
            logging.error("CSV output format requires the --output-file argument.")
            sys.exit(1)
        detailed = prepare_detailed_results(all_results)
        write_csv_report(detailed, Path(args.output_file))

    # Handle Console Output (Default)
    else:
        print_console_report(all_results)

    print("\ndone.\n")


if __name__ == "__main__":
    main()
