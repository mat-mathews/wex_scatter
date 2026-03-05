"""Scatter — .NET dependency analyzer package.

Re-exports all public functions for backward compatibility.
Code that does `from scatter import find_consumers` continues to work.
"""
from scatter.core.models import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_CHUNK_SIZE,
    MULTIPROCESSING_ENABLED,
    TYPE_DECLARATION_PATTERN,
)
from scatter.core.parallel import (
    chunk_list,
    find_files_with_pattern_chunk,
    map_cs_to_projects_batch,
    parse_csproj_files_batch,
    parse_csproj_files_parallel,
    map_cs_to_projects_parallel,
    analyze_cs_files_batch,
    analyze_cs_files_parallel,
    estimate_file_count,
    find_files_with_pattern_parallel,
)
from scatter._legacy import (
    extract_type_names_from_content,
    find_project_file,
    find_project_file_on_disk,
    analyze_branch_changes,
    get_diff_for_file,
    get_affected_symbols_from_diff,
    derive_namespace,
    configure_gemini,
    summarize_csharp_file_with_gemini,
    _process_consumer_summaries_and_append_results,
    find_consumers,
    find_cs_files_referencing_sproc,
    find_enclosing_type_name,
    find_solutions_for_project,
    map_batch_jobs_from_config_repo,
    gemini_model,
)

# Re-export stdlib modules that tests access via scatter.X
import argparse
import logging
