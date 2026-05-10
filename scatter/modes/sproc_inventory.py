"""Sproc inventory mode — builds complete stored procedure catalog."""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def run_sproc_inventory_mode(args, ctx) -> None:
    """Build sproc inventory: scan .sql files, cross-reference C# code, output catalog.

    Requires a dependency graph (built or loaded from cache) with db dependencies
    enabled. Scans .sql files for CREATE/ALTER PROCEDURE definitions, then
    cross-references against C# sproc references from the graph.
    """
    from scatter.analysis import _ensure_graph_context
    from scatter.analyzers.sproc_catalog import build_sproc_catalog
    from scatter.scanners.sql_catalog_scanner import scan_sql_catalog

    t0 = time.monotonic()

    # Build graph on first run if no cache exists (same as other modes)
    _ensure_graph_context(ctx)

    if not ctx.graph_ctx or not ctx.graph_ctx.graph:
        logging.error("Sproc inventory requires a dependency graph. Run without --no-graph.")
        return

    graph = ctx.graph_ctx.graph

    # Collect .sql files
    sql_files: List[Path] = []
    if ctx.discovered_files:
        sql_files = ctx.discovered_files.get(".sql", [])

    # Build project directory index for find_owning_project
    project_dir_index: Dict[Path, str] = {}
    for node in graph.get_all_nodes():
        if node.path and node.path.parent:
            project_dir_index[node.path.parent] = node.name

    # Scan .sql catalog for definition metadata (detection_method="sql_catalog").
    # C# references come from the graph's ProjectNode.sproc_references, which were
    # populated during graph build Steps 4+6. No need to re-run scan_db_dependencies
    # — the graph already has the data. (Marcus review: avoids 30-60s double scan.)
    sql_deps = scan_sql_catalog(sql_files, project_dir_index, ctx.search_scope)

    # Build catalog from .sql definitions + graph node sproc references
    catalog = build_sproc_catalog(sql_deps, graph)

    elapsed = time.monotonic() - t0
    logging.info(f"Sproc inventory completed in {elapsed:.1f}s")

    # Output
    output_format = getattr(args, "output_format", "console")
    output_file = getattr(args, "output_file", None)

    if output_format == "json":
        _write_json(catalog, output_file)
    else:
        _print_console(catalog)


def _print_console(catalog) -> None:
    """Print sproc inventory to console."""
    print()
    print("=" * 60)
    print("  Stored Procedure Inventory")
    print("=" * 60)
    print(
        f"  Total: {catalog.total_sprocs} sprocs "
        f"({catalog.total_defined} defined, "
        f"{catalog.total_referenced} referenced, "
        f"{catalog.total_shared} shared)"
    )
    print(f"  SQL definition coverage: {catalog.coverage_pct}%")
    print()

    if not catalog.entries:
        print("  No stored procedures found.")
        return

    # Header
    print(f"  {'Sproc':<50} {'Status':<30} {'Projects':>8} {'Methods'}")
    print(f"  {'-' * 50} {'-' * 30} {'-' * 8} {'-' * 20}")

    for entry in catalog.entries:
        if entry.status == "referenced_only":
            status_label = "no .sql definition in repo"
        elif entry.status == "defined_only":
            status_label = "defined, not referenced"
        else:
            status_label = "defined + referenced"

        projects = ", ".join(entry.referencing_projects[:3])
        if len(entry.referencing_projects) > 3:
            projects += f" +{len(entry.referencing_projects) - 3} more"

        methods = ", ".join(sorted(entry.detection_methods))

        print(
            f"  {entry.name:<50} {status_label:<30} {len(entry.referencing_projects):>8} {methods}"
        )

    print()
    print(
        f"  {catalog.total_undefined} sproc(s) referenced in C# "
        f"with no .sql definition found in repo."
    )
    print()


def _write_json(catalog, output_file: Optional[str]) -> None:
    """Write sproc inventory as JSON."""
    data = {
        "total_sprocs": catalog.total_sprocs,
        "total_defined": catalog.total_defined,
        "total_referenced": catalog.total_referenced,
        "total_undefined": catalog.total_undefined,
        "total_shared": catalog.total_shared,
        "coverage_pct": catalog.coverage_pct,
        "entries": [
            {
                "name": e.name,
                "status": e.status,
                "defined_in_sql": e.defined_in_sql,
                "defined_in_migration": e.defined_in_migration,
                "referencing_projects": e.referencing_projects,
                "defining_projects": e.defining_projects,
                "detection_methods": sorted(e.detection_methods),
                "reference_count": e.reference_count,
            }
            for e in catalog.entries
        ],
    }

    json_str = json.dumps(data, indent=2)
    if output_file:
        Path(output_file).write_text(json_str, encoding="utf-8")
        logging.info(f"Sproc inventory written to {output_file}")
    else:
        print(json_str)
