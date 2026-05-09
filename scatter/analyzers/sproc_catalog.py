"""Sproc catalog — aggregates stored procedure references from all detection sources.

Cross-references .sql definitions against C# code references to produce a
complete inventory: which sprocs are defined, which are referenced, which are
shared across projects, and which have no .sql definition in the repo.

The catalog is assembled at query time from DbDependency objects — it is not
stored on the graph. This keeps the graph schema flat (team decision D1).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from scatter.scanners.db_scanner import DbDependency
from scatter.scanners.sql_catalog_scanner import normalize_sproc_name

if TYPE_CHECKING:
    from scatter.core.graph import DependencyGraph

logger = logging.getLogger(__name__)

# Detection methods that indicate a sproc *definition* (vs a code reference)
_DEFINITION_METHODS = frozenset({"sql_catalog", "ef_migration"})

# Detection methods that indicate a sproc *reference* from C# code
_REFERENCE_METHODS = frozenset({"string_literal", "commandtype_window"})


@dataclass
class SprocCatalogEntry:
    """A single stored procedure in the catalog."""

    name: str
    defined_in_sql: bool = False
    defined_in_migration: bool = False
    referencing_projects: List[str] = field(default_factory=list)
    defining_projects: List[str] = field(default_factory=list)
    detection_methods: Set[str] = field(default_factory=set)
    reference_count: int = 0
    status: str = ""  # "defined_and_referenced", "referenced_only", "defined_only"


@dataclass
class SprocCatalog:
    """Complete stored procedure inventory for a codebase."""

    entries: List[SprocCatalogEntry] = field(default_factory=list)
    total_sprocs: int = 0
    total_defined: int = 0
    total_referenced: int = 0
    total_undefined: int = 0  # referenced but no .sql definition found in repo
    total_shared: int = 0  # referenced by 2+ projects
    coverage_pct: float = 0.0


def build_sproc_catalog(
    db_dependencies: List[DbDependency],
    graph: Optional["DependencyGraph"] = None,
) -> SprocCatalog:
    """Build a complete sproc inventory from all detection sources.

    Aggregates DbDependency objects from all detection_methods:
    - "string_literal": sproc name in C# string (existing db_scanner)
    - "sql_catalog": CREATE/ALTER PROCEDURE in .sql file
    - "ef_migration": CREATE PROCEDURE in migration file
    - "commandtype_window": CommandType.StoredProcedure window (future PR)

    Also pulls sproc names from graph nodes (ProjectNode.sproc_references)
    which were populated during graph build Step 4 via SPROC_PATTERN.

    Uses normalize_sproc_name() for case/schema deduplication.

    Returns SprocCatalog with entries sorted by reference_count descending.
    """
    # Accumulate data per normalized sproc name
    sproc_data: Dict[str, Dict] = defaultdict(
        lambda: {
            "defined_in_sql": False,
            "defined_in_migration": False,
            "referencing_projects": set(),
            "defining_projects": set(),
            "detection_methods": set(),
            "reference_count": 0,
        }
    )

    # Process DbDependency objects
    for dep in db_dependencies:
        if dep.db_object_type != "sproc":
            continue

        normalized = normalize_sproc_name(dep.db_object_name)
        entry = sproc_data[normalized]
        entry["detection_methods"].add(dep.detection_method)

        if dep.detection_method in _DEFINITION_METHODS:
            entry["defining_projects"].add(dep.source_project)
            if dep.detection_method == "sql_catalog":
                entry["defined_in_sql"] = True
            elif dep.detection_method == "ef_migration":
                entry["defined_in_migration"] = True
        else:
            entry["referencing_projects"].add(dep.source_project)
            entry["reference_count"] += 1

    # Pull additional sproc names from graph nodes (SPROC_PATTERN matches
    # from Step 4 that may not have produced DbDependency objects)
    if graph:
        for node in graph.get_all_nodes():
            for sproc_ref in node.sproc_references:
                normalized = normalize_sproc_name(sproc_ref)
                entry = sproc_data[normalized]
                entry["referencing_projects"].add(node.name)
                if not entry["reference_count"]:
                    entry["reference_count"] = 1
                entry["detection_methods"].add("sproc_pattern")

    # Build catalog entries
    entries: List[SprocCatalogEntry] = []
    for name, data in sproc_data.items():
        is_defined = data["defined_in_sql"] or data["defined_in_migration"]
        is_referenced = len(data["referencing_projects"]) > 0

        if is_defined and is_referenced:
            status = "defined_and_referenced"
        elif is_referenced:
            # D6: label as "no .sql definition found in repo," not "doesn't exist"
            status = "referenced_only"
        else:
            status = "defined_only"

        entries.append(
            SprocCatalogEntry(
                name=name,
                defined_in_sql=data["defined_in_sql"],
                defined_in_migration=data["defined_in_migration"],
                referencing_projects=sorted(data["referencing_projects"]),
                defining_projects=sorted(data["defining_projects"]),
                detection_methods=data["detection_methods"],
                reference_count=data["reference_count"],
                status=status,
            )
        )

    entries.sort(key=lambda e: e.reference_count, reverse=True)

    total_defined = sum(1 for e in entries if e.defined_in_sql or e.defined_in_migration)
    total_referenced = sum(1 for e in entries if e.referencing_projects)
    total_undefined = sum(
        1
        for e in entries
        if e.referencing_projects and not e.defined_in_sql and not e.defined_in_migration
    )
    total_shared = sum(1 for e in entries if len(e.referencing_projects) >= 2)
    coverage_pct = (total_defined / len(entries) * 100) if entries else 0.0

    catalog = SprocCatalog(
        entries=entries,
        total_sprocs=len(entries),
        total_defined=total_defined,
        total_referenced=total_referenced,
        total_undefined=total_undefined,
        total_shared=total_shared,
        coverage_pct=round(coverage_pct, 1),
    )

    logger.info(
        f"Sproc catalog: {catalog.total_sprocs} sprocs, "
        f"{catalog.total_defined} defined, {catalog.total_referenced} referenced, "
        f"{catalog.total_shared} shared, coverage {catalog.coverage_pct}%"
    )
    return catalog
