"""V1 compatibility helpers — pipeline mapping, solution lookup, result processing."""
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Union


def find_solutions_for_project(csproj_path: Path, solution_cache: List[Path]) -> List[Path]:
    """
    Finds .sln files that reference a given .csproj file by performing a text search.
    """
    found_in_solutions: List[Path] = []
    project_filename = csproj_path.name

    if not solution_cache:
        logging.warning("Solution cache is empty. Cannot search for solutions.")
        return found_in_solutions

    logging.debug(f"Searching {len(solution_cache)} cached solution files for '{project_filename}'...")

    for sln_path in solution_cache:
        try:
            content = sln_path.read_text(encoding='utf-8', errors='ignore')
            if project_filename in content:
                logging.debug(f"  -> Found reference in: {sln_path.name}")
                found_in_solutions.append(sln_path)
        except OSError as e:
            logging.warning(f"Could not read solution file {sln_path.name}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error processing solution file {sln_path.name}: {e}")

    return found_in_solutions


def map_batch_jobs_from_config_repo(app_config_path: Path) -> Dict[str, List[str]]:
    """
    Scans the app-config repo for the specific batch processes directory
    and maps the pipeline name to the actual job (subdirectory) names.
    """
    batch_job_map: Dict[str, List[str]] = {}
    pipeline_name = "cdh-batchprocesses-az-cd"

    if not app_config_path or not app_config_path.is_dir():
        logging.warning("App config path not provided or not a valid directory. Skipping batch job mapping.")
        return batch_job_map

    target_dir = app_config_path / pipeline_name / "production"
    logging.info(f"Searching for batch jobs in: {target_dir}")

    if not target_dir.is_dir():
        logging.warning(f"Batch job directory not found: {target_dir}. Cannot map specific job names.")
        return batch_job_map

    try:
        job_names = sorted([item.name for item in target_dir.iterdir() if item.is_dir()])
        if job_names:
            batch_job_map[pipeline_name] = job_names
            logging.info(f"Found {len(job_names)} specific batch jobs in app-config repo (e.g., {', '.join(job_names[:3])}...).")
        else:
            logging.warning(f"Found batch job directory, but it contains no subdirectories: {target_dir}")
    except OSError as e:
        logging.error(f"Could not read batch job subdirectories from '{target_dir}': {e}")

    return batch_job_map


def _process_consumer_summaries_and_append_results(
    target_project_name: str,
    target_project_rel_path_str: str,
    triggering_info: str,
    final_consumers_data: List[Dict[str, Union[Path, str, List[Path]]]],
    all_results_list: List[Dict[str, Union[str, Dict, List[str]]]],
    pipeline_map_dict: Dict[str, str],
    solution_file_cache: List[Path],
    batch_job_map: Dict[str, List[str]],
    search_scope_path_abs: Path) -> None:
    """
    Helper to process summaries for consumer files and append to the main results list.
    Generates a row for EACH unique pipeline found for a consumer.
    """
    if not final_consumers_data:
        logging.info(f"   No consumers found for target '{target_project_name}' triggered by '{triggering_info}'.")
        return

    logging.info(f"   Found {len(final_consumers_data)} consumer(s) for target '{target_project_name}' triggered by '{triggering_info}'.")
    summaries_for_this_target: Dict[str, Dict[str, str]] = defaultdict(dict)

    for consumer_info in final_consumers_data:
        consumer_abs_path = consumer_info['consumer_path']
        consumer_name_stem = consumer_info['consumer_name']
        try:
            consumer_rel_path_str = consumer_abs_path.relative_to(search_scope_path_abs).as_posix()
        except ValueError:
            consumer_rel_path_str = consumer_abs_path.as_posix()

        solutions_for_consumer_paths = find_solutions_for_project(consumer_abs_path, solution_file_cache)
        solutions_for_consumer_names = [p.name for p in solutions_for_consumer_paths]
        logging.debug(f"   Found {len(solutions_for_consumer_names)} solutions for consumer '{consumer_name_stem}': {solutions_for_consumer_names}")

        consumer_summaries_dict = summaries_for_this_target.get(consumer_rel_path_str, {})

        found_pipelines: Dict[str, str] = {}
        if solutions_for_consumer_names:
            for solution_name in solutions_for_consumer_names:
                solution_stem = Path(solution_name).stem
                if solution_stem in pipeline_map_dict:
                    pipeline_name = pipeline_map_dict[solution_stem]
                    if pipeline_name not in found_pipelines:
                        found_pipelines[pipeline_name] = solution_stem
                        logging.debug(f"   Found mapping: Solution '{solution_stem}' -> Pipeline '{pipeline_name}'")

        if found_pipelines:
            for pipeline_name, source_solution in found_pipelines.items():
                batch_job_verification = None
                if pipeline_name == "cdh-batchprocesses-az-cd":
                    all_known_jobs = batch_job_map.get(pipeline_name, [])
                    if consumer_name_stem in all_known_jobs:
                        batch_job_verification = "Verified"
                    else:
                        batch_job_verification = "Unverified"

                all_results_list.append({
                    'TargetProjectName': target_project_name,
                    'TargetProjectPath': target_project_rel_path_str,
                    'TriggeringType': triggering_info,
                    'ConsumerProjectName': consumer_name_stem,
                    'ConsumerProjectPath': consumer_rel_path_str,
                    'ConsumingSolutions': solutions_for_consumer_names,
                    'PipelineName': pipeline_name,
                    'BatchJobVerification': batch_job_verification,
                    'ConsumerFileSummaries': consumer_summaries_dict
                })
        else:
            logging.debug(f"   No pipeline mapping found for consumer '{consumer_name_stem}' via its solutions.")
            all_results_list.append({
                'TargetProjectName': target_project_name,
                'TargetProjectPath': target_project_rel_path_str,
                'TriggeringType': triggering_info,
                'ConsumerProjectName': consumer_name_stem,
                'ConsumerProjectPath': consumer_rel_path_str,
                'ConsumingSolutions': solutions_for_consumer_names,
                'PipelineName': None,
                'BatchJobVerification': None,
                'ConsumerFileSummaries': consumer_summaries_dict
            })
