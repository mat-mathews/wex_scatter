"""CLI argument parser definition for Scatter."""

import argparse
from typing import Any, Dict

from scatter.core.models import DEFAULT_MAX_WORKERS, DEFAULT_CHUNK_SIZE


_REDACTED_CLI_KEYS = frozenset({"google_api_key", "wex_api_key"})


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
    if getattr(args, "wex_api_key", None) is not None:
        overrides["ai.credentials.wex.api_key"] = args.wex_api_key
    if getattr(args, "wex_model", None) is not None:
        overrides["ai.wex_model"] = args.wex_model
    if args.disable_multiprocessing:
        overrides["multiprocessing.disabled"] = True
    if args.max_depth is not None:
        overrides["search.max_depth"] = args.max_depth
    if getattr(args, "max_ai_calls", None) is not None:
        overrides["ai.max_ai_calls"] = args.max_ai_calls
    if getattr(args, "parser_mode", None) is not None:
        overrides["analysis.parser_mode"] = args.parser_mode
    if hasattr(args, "rebuild_graph") and args.rebuild_graph:
        overrides["graph.rebuild"] = True
    if hasattr(args, "include_db") and args.include_db:
        overrides["db.include_db_edges"] = True
    if getattr(args, "include_test_projects", False):
        overrides["analysis.exclude_test_projects"] = False
    return overrides


def build_parser() -> argparse.ArgumentParser:
    """Build and return the Scatter CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Analyzes .NET project consumers based on Git branch changes OR a specific target project. Can optionally summarize consumer files using AI (WEX AI Platform or Google Gemini).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- mode selection ---
    # required=False to allow --dump-index standalone; validated in __main__.py
    mode_group = parser.add_mutually_exclusive_group(required=False)
    mode_group.add_argument(
        "--target-project",
        help="MODE: Target Project Analysis. Path to the .csproj file or directory of the specific project to analyze.",
    )
    mode_group.add_argument(
        "--branch-name",
        help="MODE: Git Branch Analysis. Name of the feature branch to analyze changes on.",
    )

    mode_group.add_argument(
        "--stored-procedure",
        metavar="SPROC_NAME",
        help="MODE: Stored Procedure Analysis. Name of the stored procedure to find references to (e.g., 'usp_MyProcedure' or 'dbo.usp_MyProcedure'). Requires --search-scope.",
    )
    mode_group.add_argument(
        "--sow",
        metavar="DESCRIPTION",
        help="MODE: Impact Analysis. Inline work request text describing the change.",
    )
    mode_group.add_argument(
        "--sow-file",
        metavar="FILE",
        help="MODE: Impact Analysis. Path to file containing the work request text.",
    )
    mode_group.add_argument(
        "--graph",
        action="store_true",
        default=False,
        help="MODE: Dependency Graph Analysis. Build graph, compute coupling metrics, detect cycles.",
    )

    # --- sproc group ---
    sproc_group = parser.add_argument_group(
        "Stored Procedure Analysis Options (Requires --stored-procedure)"
    )
    sproc_group.add_argument(
        "--sproc-regex-pattern",
        default=None,
        help='(Optional) Custom Python regex pattern to find stored procedure names in C# files. If not provided, a default pattern is used. Example: "MyCustomPatternFor_(?P<sproc>{sproc_name_placeholder})" where {sproc_name_placeholder} will be replaced by the escaped sproc name.',
    )

    # --- git mode specific arguments ---
    git_group = parser.add_argument_group("Git Branch Analysis Options (Requires --branch-name)")
    git_group.add_argument(
        "-r",
        "--repo-path",
        default=".",
        help="Path to the Git repository (default: current directory).",
    )
    git_group.add_argument(
        "-b",
        "--base-branch",
        default="main",
        help="Base branch to compare against (default: main).",
    )
    git_group.add_argument(
        "--enable-hybrid-git",
        action="store_true",
        help="Enable LLM-enhanced diff analysis for more precise symbol extraction (requires Gemini API key).",
    )
    git_group.add_argument(
        "--pr-risk",
        action="store_true",
        default=False,
        help="Output PR risk analysis instead of consumer table. Requires --branch-name.",
    )
    git_group.add_argument(
        "--collapsible",
        action="store_true",
        default=False,
        help="Wrap detail sections in collapsible <details> tags. Only affects --pr-risk --output-format markdown.",
    )
    git_group.add_argument(
        "--no-prediction-log",
        action="store_true",
        default=False,
        help="Disable writing prediction records to .scatter/predictions.jsonl after --pr-risk analysis.",
    )

    common_group = parser.add_argument_group("Common Options")
    common_group.add_argument(
        "--search-scope",
        help="Root directory to search for consuming projects (defaults to --repo-path if Git mode is used and this is omitted, otherwise REQUIRED).",
    )
    common_group.add_argument(
        "--parser-mode",
        choices=["regex", "hybrid"],
        default=None,
        help="Parser mode: 'regex' (default) uses regex only; 'hybrid' adds tree-sitter AST validation to reduce false positives.",
    )
    common_group.add_argument(
        "--graph-metrics",
        action="store_true",
        help="Build dependency graph and enrich results with graph metrics (coupling, fan-in/out, instability, cycles). "
        "When a graph cache already exists, enrichment happens automatically without this flag.",
    )
    common_group.add_argument(
        "--no-graph",
        action="store_true",
        help="Skip automatic graph loading and enrichment, even when a cache exists.",
    )
    common_group.add_argument(
        "--rebuild-graph",
        action="store_true",
        help="Force graph rebuild, ignoring cached data (only used with --graph).",
    )
    common_group.add_argument(
        "--full-type-scan",
        action="store_true",
        help="Compute type_usage edges between all project pairs, not just those "
        "connected by project_reference or namespace_usage edges.",
    )
    common_group.add_argument(
        "--include-db",
        action="store_true",
        help="Include database dependency scanning (sprocs, EF models, direct SQL) in --graph mode.",
    )
    common_group.add_argument(
        "--include-graph-topology",
        action="store_true",
        help="Include raw graph topology (nodes/edges) in JSON output. Omitted by default to reduce file size.",
    )
    common_group.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Maximum transitive tracing depth for impact analysis (default: 2).",
    )
    common_group.add_argument(
        "--sow-min-confidence",
        type=float,
        default=0.3,
        help="Minimum confidence threshold for SOW-extracted targets (default: 0.3).",
    )
    common_group.add_argument(
        "--scope-estimate",
        action="store_true",
        default=False,
        help="Generate structured effort estimate with confidence bands. Requires --sow or --sow-file.",
    )
    common_group.add_argument(
        "--dump-index",
        action="store_true",
        help="Build dependency graph, print codebase index to stdout, and exit. Requires --search-scope.",
    )
    common_group.add_argument(
        "--app-config-path",
        help="(Optional) Path to the 'health-benefits-app-config' repository to resolve specific batch job names.",
    )
    common_group.add_argument(
        "--class-name",
        default=None,
        help="(Optional) Filter: In Git mode, analyze only this type if found in changes. In Target Project mode, check for usage of this specific type.",
    )
    common_group.add_argument(
        "--method-name",
        default=None,
        help="(Optional) Filter: Check for usage of this specific method name. Requires --class-name to be specified.",
    )
    common_group.add_argument(
        "--target-namespace",
        default=None,
        help="(Optional) Explicitly specify the target project's namespace. Overrides automatic derivation (mainly useful in Target Project mode).",
    )
    common_group.add_argument(
        "--include-test-projects",
        action="store_true",
        help="Include test projects (e.g. *.Tests) in blast radius analysis. By default they are excluded.",
    )
    common_group.add_argument(
        "--pipeline-csv",
        default=None,
        help="(Optional) Path to CSV mapping 'Project Name' to 'Pipeline Name'.",
    )
    common_group.add_argument(
        "--output-file",
        default=None,
        help="(Optional) Path to write results to a file. The format is determined by --output-format.",
    )
    common_group.add_argument(
        "-v", "--verbose", action="store_true", help="Enable detailed DEBUG level logging."
    )
    ai_group = parser.add_argument_group("AI Provider Options")
    ai_group.add_argument(
        "--summarize-consumers",
        action="store_true",
        help="Enable summarization of relevant C# files in consuming projects using the configured AI provider.",
    )
    ai_group.add_argument(
        "--ai-summary",
        action="store_true",
        help="Generate an AI narrative summarizing the consumer analysis results. "
        "Sends project names and coupling metrics to the configured AI provider.",
    )
    ai_group.add_argument(
        "--google-api-key",
        default=None,
        help="Google API Key for Gemini provider. If not provided, uses the GOOGLE_API_KEY environment variable.",
    )
    ai_group.add_argument(
        "--gemini-model",
        default=None,
        help="The Gemini model to use (default: gemini-2.0-flash).",
    )
    ai_group.add_argument(
        "--wex-api-key",
        default=None,
        help="WEX AI Platform API key. If not provided, uses the WEX_AI_API_KEY environment variable.",
    )
    ai_group.add_argument(
        "--wex-model",
        default=None,
        help="The WEX AI Platform model to use (default: default).",
    )
    ai_group.add_argument(
        "--max-ai-calls",
        type=int,
        default=None,
        help="Maximum number of AI API calls per run. When exhausted, AI enrichment is skipped gracefully.",
    )
    common_group.add_argument(
        "--output-format",
        default="console",
        choices=["console", "csv", "json", "markdown", "mermaid", "pipelines"],
        help="Format for the output. 'console' prints to screen. 'csv', 'json', or 'markdown' writes to --output-file (markdown also prints to stdout if no file given). 'mermaid' outputs a Mermaid dependency diagram (graph mode only). 'pipelines' prints sorted unique pipeline names, one per line.",
    )

    # Multiprocessing options
    multiprocessing_group = parser.add_argument_group("Multiprocessing Options")
    multiprocessing_group.add_argument(
        "--disable-multiprocessing",
        action="store_true",
        help="Disable parallel processing and use sequential file discovery.",
    )
    multiprocessing_group.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Maximum number of worker processes for parallel operations (default: {DEFAULT_MAX_WORKERS}).",
    )
    multiprocessing_group.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Number of directories to process per worker chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )
    multiprocessing_group.add_argument(
        "--cs-analysis-chunk-size",
        type=int,
        default=50,
        help="Number of .cs files per worker batch for content analysis (default: 50).",
    )
    multiprocessing_group.add_argument(
        "--csproj-analysis-chunk-size",
        type=int,
        default=25,
        help="Number of .csproj files per worker batch for XML parsing (default: 25).",
    )

    return parser
