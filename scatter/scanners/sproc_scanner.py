"""Stored procedure reference detection in C# source files."""

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Set

from scatter.core.models import DEFAULT_MAX_WORKERS, DEFAULT_CHUNK_SIZE
from scatter.core.parallel import (
    find_files_with_pattern_parallel,
    analyze_cs_files_parallel,
    map_cs_to_projects_parallel,
)
from scatter.scanners.type_scanner import find_enclosing_type_name


def find_cs_files_referencing_sproc(
    sproc_name_input: str,
    search_path: Path,
    custom_sproc_regex_pattern: Optional[str] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
) -> Dict[Path, Dict[str, Set[Path]]]:
    """
    Scans all .cs files within the search_path for the given stored procedure name
    and identifies the containing class.
    """
    projects_classes_sproc_refs: Dict[Path, Dict[str, Set[Path]]] = defaultdict(
        lambda: defaultdict(set)
    )
    base_sproc_name = sproc_name_input.split(".")[-1]
    escaped_base_sproc_name = re.escape(base_sproc_name)

    if custom_sproc_regex_pattern:
        if "{sproc_name_placeholder}" not in custom_sproc_regex_pattern:
            logging.error(
                "Custom sproc regex pattern must contain '{sproc_name_placeholder}'. Using default pattern."
            )
            sproc_pattern_str = r'["\'](?:[a-zA-Z0-9_]+\.)?' + escaped_base_sproc_name + r'["\']'
        else:
            sproc_pattern_str = custom_sproc_regex_pattern.replace(
                "{sproc_name_placeholder}", escaped_base_sproc_name
            )
    else:
        sproc_pattern_str = (
            r'["\'](?:[a-zA-Z_][a-zA-Z0-9_]*\.)?' + escaped_base_sproc_name + r'["\']'
        )

    try:
        sproc_pattern = re.compile(sproc_pattern_str, re.IGNORECASE)
        logging.debug(f"Using sproc search pattern: {sproc_pattern.pattern}")
    except re.error as e:
        logging.error(
            f"Invalid regex pattern for sproc search ('{sproc_pattern_str}'): {e}. Aborting sproc search."
        )
        return {}

    try:
        cs_files_to_scan = find_files_with_pattern_parallel(
            search_path,
            "*.cs",
            max_workers=max_workers,
            chunk_size=chunk_size,
            disable_multiprocessing=disable_multiprocessing,
        )
    except OSError as e:
        logging.error(f"Error scanning for .cs files in '{search_path}': {e}")
        return {}

    logging.info(
        f"Scanning {len(cs_files_to_scan)} C# files in '{search_path}' for references to sproc '{sproc_name_input}'."
    )
    files_with_ref_count = 0
    projects_found_count = 0
    classes_found_count = 0

    if cs_files_to_scan:
        analysis_config = {
            "analysis_type": "sproc",
            "sproc_name": sproc_name_input,
            "sproc_pattern": sproc_pattern,
        }

        analysis_results = analyze_cs_files_parallel(
            cs_files_to_scan,
            analysis_config,
            max_workers=max_workers,
            cs_analysis_chunk_size=cs_analysis_chunk_size,
            disable_multiprocessing=disable_multiprocessing,
        )

        matching_files = []
        for cs_file_abs, file_result in analysis_results.items():
            if file_result.get("error"):
                log_level_detail = (
                    logging.DEBUG if logging.getLogger().level == logging.DEBUG else logging.WARNING
                )
                logging.log(
                    log_level_detail,
                    f"Error processing file {cs_file_abs.name} for sproc search: {file_result['error']}",
                )
                continue
            if file_result.get("has_match"):
                matching_files.append(cs_file_abs)

        cs_to_csproj_map = {}
        if matching_files:
            cs_to_csproj_map = map_cs_to_projects_parallel(
                matching_files,
                max_workers=max_workers,
                cs_analysis_chunk_size=cs_analysis_chunk_size,
                disable_multiprocessing=disable_multiprocessing,
            )

        for cs_file_abs, file_result in analysis_results.items():
            try:
                if file_result.get("error") or not file_result.get("has_match"):
                    continue

                files_with_ref_count += 1
                logging.debug(
                    f"  Potential reference(s) to sproc '{sproc_name_input}' found in: {cs_file_abs.relative_to(search_path) if search_path in cs_file_abs.parents else cs_file_abs.name}"
                )

                csproj_str = cs_to_csproj_map.get(str(cs_file_abs))
                if not csproj_str:
                    logging.warning(
                        f"  Could not map C# file '{cs_file_abs.name}' (with sproc ref) to a project."
                    )
                    continue

                project_file_abs = Path(csproj_str)
                is_new_project = project_file_abs not in projects_classes_sproc_refs

                matches = file_result.get("matches", [])
                if matches:
                    first_match_index = matches[0][1] if isinstance(matches[0], tuple) else 0

                    content = cs_file_abs.read_text(encoding="utf-8", errors="ignore")
                    enclosing_class = find_enclosing_type_name(content, first_match_index)

                    if enclosing_class:
                        is_new_class_for_project = (
                            enclosing_class not in projects_classes_sproc_refs[project_file_abs]
                        )
                        projects_classes_sproc_refs[project_file_abs][enclosing_class].add(
                            cs_file_abs
                        )

                        if is_new_project:
                            projects_found_count += 1
                        if is_new_class_for_project:
                            classes_found_count += 1

                        logging.debug(
                            f"    Mapped sproc ref in '{cs_file_abs.name}' to Project '{project_file_abs.name}' and Class '{enclosing_class}'"
                        )
                    else:
                        logging.warning(
                            f"    Could not determine enclosing class for sproc ref near index {first_match_index} in '{cs_file_abs.name}' (Project: {project_file_abs.name}). Skipping this reference for class-based consumer analysis."
                        )

            except Exception as e:
                log_level_detail = (
                    logging.DEBUG if logging.getLogger().level == logging.DEBUG else logging.WARNING
                )
                logging.log(
                    log_level_detail,
                    f"Unexpected error processing results for file {cs_file_abs.name} for sproc search: {e}",
                    exc_info=(log_level_detail == logging.DEBUG),
                )

    if files_with_ref_count == 0:
        logging.info(
            f"No C# files found directly referencing sproc '{sproc_name_input}' with the pattern."
        )
    else:
        log_msg = f"Found {files_with_ref_count} C# file(s) with potential sproc references. "
        log_msg += f"Mapped references to {classes_found_count} unique class(es) across {projects_found_count} project(s)."
        logging.info(log_msg)

    final_result = {proj: dict(classes) for proj, classes in projects_classes_sproc_refs.items()}
    return final_result
