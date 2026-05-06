"""RDL scanner — detects stored procedure references in SSRS report files.

Scans .rdl/.rdlc/.rds files for sproc names in <CommandText> elements.
When a referenced sproc maps to a project in the graph, emits an rdl_sproc
edge linking the report-owning project to the sproc-owning project.

Covers the CDH gap: Find-RdlFilesReferencingStoredProcs.
"""

import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from scatter.core.graph import DependencyEdge, DependencyGraph
from scatter.scanners._helpers import find_owning_project

_MAX_FILE_SIZE = 1_048_576  # 1 MB


@dataclass
class RdlSprocReference:
    """A stored procedure reference found in an RDL report file."""

    sproc_name: str  # "dbo.sp_GetPortalConfigurationDetails"
    rdl_file: Path
    containing_project: str  # nearest project owning this .rdl file
    dataset_name: str  # SSRS DataSet name for evidence


def scan_rdl_files(
    rdl_files: List[Path],
    project_dir_index: Dict[Path, str],
    search_scope: Path,
) -> List[RdlSprocReference]:
    """Parse RDL/RDLC/RDS files for stored procedure references.

    Extracts sproc names from <CommandText> elements inside <Query> blocks.
    Handles all SSRS XML namespace versions by stripping namespace prefixes
    from element tags.

    Skips files larger than 1 MB, malformed XML, and encoding errors.

    Returns:
        List of RdlSprocReference for each sproc found.
    """
    if not rdl_files:
        return []

    references: List[RdlSprocReference] = []

    for rdl_path in rdl_files:
        try:
            file_size = rdl_path.stat().st_size
        except OSError:
            continue

        if file_size > _MAX_FILE_SIZE:
            logging.warning(f"Skipping oversized RDL file ({file_size:,} bytes): {rdl_path}")
            continue

        owning_project = find_owning_project(rdl_path, project_dir_index)
        if owning_project is None:
            continue

        try:
            tree = ET.parse(rdl_path)  # noqa: S314
        except ET.ParseError as e:
            logging.warning(f"Malformed XML in {rdl_path}: {e}")
            continue
        except (OSError, UnicodeDecodeError) as e:
            logging.warning(f"Could not read {rdl_path}: {e}")
            continue

        refs = _extract_sproc_references(tree, rdl_path, owning_project)
        references.extend(refs)

    if references:
        logging.info(
            f"RDL scanner: found {len(references)} sproc reference(s) "
            f"across {len(rdl_files)} RDL file(s)"
        )

    return references


def add_rdl_sproc_edges(
    graph: DependencyGraph,
    references: List[RdlSprocReference],
    sproc_to_projects: Dict[str, Set[str]],
) -> int:
    """Add rdl_sproc edges for sproc references that resolve to graph projects.

    For each sproc found in an RDL file, checks if the sproc name exists in
    any graph project's sproc_references. If so, creates a directed edge from
    the report-owning project to the sproc-owning project.

    Accumulates evidence per project pair. Logs a summary for unmatched sprocs.

    Returns the number of edges added.
    """
    if not references:
        return 0

    pair_evidence: Dict[tuple, List[str]] = defaultdict(list)
    matched = 0
    unmatched = 0

    for ref in references:
        targets = sproc_to_projects.get(ref.sproc_name, set())
        if not targets:
            unmatched += 1
            continue

        for target_project in targets:
            if target_project == ref.containing_project:
                continue

            if graph.get_node(ref.containing_project) is None:
                continue
            if graph.get_node(target_project) is None:
                continue

            pair = (ref.containing_project, target_project)
            pair_evidence[pair].append(f"{ref.rdl_file.name}:{ref.sproc_name}")
            matched += 1

    edges_added = 0
    for (source, target), evidence in pair_evidence.items():
        graph.add_edge(
            DependencyEdge(
                source=source,
                target=target,
                edge_type="rdl_sproc",
                weight=float(len(evidence)),
                evidence=sorted(evidence),
            )
        )
        edges_added += 1

    if edges_added or unmatched:
        logging.info(
            f"RDL scanner: {matched} sproc(s) matched, {unmatched} unmatched (outside search scope)"
        )
    if edges_added:
        logging.info(f"Added {edges_added} rdl_sproc edge(s) to graph")

    return edges_added


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix from a tag: '{ns}localname' → 'localname'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _extract_sproc_references(
    tree: Any,
    rdl_path: Path,
    owning_project: str,
) -> List[RdlSprocReference]:
    """Extract sproc names from DataSet/Query/CommandText elements."""
    references: List[RdlSprocReference] = []
    seen_sprocs: Set[str] = set()

    # Walk all elements, match by local name (namespace-agnostic)
    for elem in tree.iter():
        if _strip_ns(elem.tag) != "DataSet":
            continue

        dataset_name = elem.get("Name", "unknown")
        command_text: Optional[str] = None

        for child in elem.iter():
            local = _strip_ns(child.tag)
            if local == "CommandText" and child.text:
                command_text = child.text.strip()
                break

        if command_text and command_text not in seen_sprocs:
            seen_sprocs.add(command_text)
            references.append(
                RdlSprocReference(
                    sproc_name=command_text,
                    rdl_file=rdl_path,
                    containing_project=owning_project,
                    dataset_name=dataset_name,
                )
            )

    return references
