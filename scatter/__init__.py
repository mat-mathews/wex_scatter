"""Scatter — .NET dependency analyzer package.

Re-exports all public functions for backward compatibility.
Code that does `from scatter import find_consumers` continues to work.
"""
from scatter.__version__ import __version__
from scatter.core.models import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_CHUNK_SIZE,
    MULTIPROCESSING_ENABLED,
    TYPE_DECLARATION_PATTERN,
    AnalysisTarget,
    EnrichedConsumer,
    TargetImpact,
    ImpactReport,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_LABELS,
    DEFAULT_MAX_DEPTH,
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
from scatter.scanners.type_scanner import (
    extract_type_names_from_content,
    find_enclosing_type_name,
)
from scatter.scanners.project_scanner import (
    find_project_file_on_disk,
    derive_namespace,
)
from scatter.scanners.sproc_scanner import find_cs_files_referencing_sproc
from scatter.analyzers.consumer_analyzer import find_consumers
from scatter.analyzers.git_analyzer import (
    find_project_file,
    analyze_branch_changes,
    get_diff_for_file,
)
from scatter.compat.v1_bridge import (
    find_solutions_for_project,
    map_batch_jobs_from_config_repo,
    _process_consumer_summaries_and_append_results,
)
# AI — backward-compatible wrappers in _legacy, canonical code in ai/providers/
from scatter._legacy import (
    get_affected_symbols_from_diff,
    configure_gemini,
    summarize_csharp_file_with_gemini,
    gemini_model,
)
from scatter.ai.base import AITaskType, AnalysisResult, AIProvider
from scatter.ai.providers.gemini_provider import GeminiProvider
from scatter.ai.router import AIRouter
from scatter.config import ScatterConfig, AIConfig, GraphConfig, DbConfig, load_config
from scatter.scanners.db_scanner import (
    DbDependency,
    DEFAULT_SPROC_PREFIXES,
    scan_db_dependencies,
    build_db_dependency_matrix,
    add_db_edges_to_graph,
)
from scatter.store.graph_cache import (
    save_graph,
    load_graph,
    load_and_validate,
    is_cache_valid,
    get_default_cache_path,
)
from scatter.core.graph import DependencyGraph, ProjectNode, DependencyEdge
from scatter.scanners.project_scanner import parse_csproj_all_references
from scatter.analyzers.graph_builder import build_dependency_graph
from scatter.analyzers.coupling_analyzer import (
    ProjectMetrics,
    CycleGroup,
    compute_all_metrics,
    detect_cycles,
    rank_by_coupling,
    DEFAULT_COUPLING_WEIGHTS,
    DEFAULT_CYCLE_EDGE_TYPES,
)
from scatter.analyzers.domain_analyzer import (
    Cluster,
    find_clusters,
    score_extraction_feasibility,
)
from scatter.analyzers.health_analyzer import (
    HealthDashboard,
    Observation,
    compute_health_dashboard,
)
from scatter.reports.graph_reporter import generate_mermaid, write_graph_csv_report

# Re-export stdlib modules that tests access via scatter.X
import argparse
import logging
