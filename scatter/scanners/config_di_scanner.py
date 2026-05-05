"""Config-based DI scanner — detects type registrations in .config XML files.

Scans .config files for assembly-qualified type names used in dependency
injection containers (Unity, Autofac, Windsor, generic patterns). When a
referenced type maps to a project in the graph, emits a config_di edge.

Covers the CDH gap: Find-ConfigFilesReferencingTypesWithNamespaces.
"""

import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from scatter.core.graph import DependencyEdge, DependencyGraph

_MAX_FILE_SIZE = 1_048_576  # 1 MB — skip oversized config files

# Matches assembly-qualified type names: "Namespace.Type, AssemblyName"
# Captures the type portion (before the comma).
_AQTN_PATTERN = re.compile(r"([A-Z][A-Za-z0-9]+(?:\.[A-Z][A-Za-z0-9]+)+)\s*,\s*[A-Za-z]")


@dataclass
class ConfigDIReference:
    """A DI type registration found in a .config file."""

    type_fqtn: str  # "GalaxyWorks.Data.PortalDataService"
    config_file: Path
    containing_project: str  # nearest project owning this .config file
    element_tag: str  # XML element where found (e.g. "register", "component")


def scan_config_files(
    config_files: List[Path],
    project_dir_index: Dict[Path, str],
    search_scope: Path,
) -> List[ConfigDIReference]:
    """Parse .config XML files for DI type registrations.

    Scans XML attributes for assembly-qualified type names (AQTN) —
    the common pattern across Unity, Autofac, Windsor, and custom DI configs.
    Skips files larger than 1 MB and malformed XML.

    Args:
        config_files: .config file paths from walk_and_collect.
        project_dir_index: directory (Path) → project name mapping from graph builder.
        search_scope: root search directory for relative path computation.

    Returns:
        List of ConfigDIReference for each type registration found.
    """
    if not config_files:
        return []

    references: List[ConfigDIReference] = []

    for config_path in config_files:
        try:
            file_size = config_path.stat().st_size
        except OSError:
            continue

        if file_size > _MAX_FILE_SIZE:
            logging.warning(f"Skipping oversized .config file ({file_size:,} bytes): {config_path}")
            continue

        owning_project = _find_owning_project(config_path, project_dir_index)
        if owning_project is None:
            continue

        try:
            tree = ET.parse(config_path)  # noqa: S314
        except ET.ParseError as e:
            logging.warning(f"Malformed XML in {config_path}: {e}")
            continue
        except OSError as e:
            logging.warning(f"Could not read {config_path}: {e}")
            continue

        refs = _extract_type_references(tree, config_path, owning_project)
        references.extend(refs)

    if references:
        logging.info(
            f"Config DI scanner: found {len(references)} type reference(s) "
            f"across {len(config_files)} .config file(s)"
        )

    return references


def add_config_di_edges(
    graph: DependencyGraph,
    references: List[ConfigDIReference],
    type_to_projects: Dict[str, Set[str]],
) -> int:
    """Add config_di edges for type references that resolve to graph projects.

    For each FQTN found in a .config file, checks if the short type name
    (last segment of the dotted path) matches a declared type in any
    graph project. If so, creates a directed edge from the config-owning
    project to the type-declaring project.

    Returns the number of edges added.
    """
    if not references:
        return 0

    # Accumulate evidence per project pair (like add_db_edges_to_graph)
    pair_evidence: Dict[tuple, List[str]] = defaultdict(list)

    for ref in references:
        short_name = ref.type_fqtn.rsplit(".", 1)[-1]

        if short_name not in type_to_projects:
            continue

        for target_project in type_to_projects[short_name]:
            if target_project == ref.containing_project:
                continue

            if graph.get_node(ref.containing_project) is None:
                continue
            if graph.get_node(target_project) is None:
                continue

            pair = (ref.containing_project, target_project)
            pair_evidence[pair].append(f"{ref.config_file.name}:{ref.type_fqtn}")

    edges_added = 0
    for (source, target), evidence in pair_evidence.items():
        graph.add_edge(
            DependencyEdge(
                source=source,
                target=target,
                edge_type="config_di",
                weight=float(len(evidence)),
                evidence=sorted(evidence),
            )
        )
        edges_added += 1

    if edges_added:
        logging.info(f"Added {edges_added} config_di edge(s) to graph")

    return edges_added


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_owning_project(
    file_path: Path,
    project_dir_index: Dict[Path, str],
) -> Optional[str]:
    """Walk up from a file to find the nearest project directory."""
    current = file_path.parent
    while True:
        if current in project_dir_index:
            return project_dir_index[current]
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _extract_type_references(
    tree: Any,
    config_path: Path,
    owning_project: str,
) -> List[ConfigDIReference]:
    """Extract assembly-qualified type names from XML attributes and text."""
    references: List[ConfigDIReference] = []
    seen_types: Set[str] = set()

    def _collect_from(text: str, elem: ET.Element) -> None:
        for match in _AQTN_PATTERN.finditer(text):
            type_fqtn = match.group(1)
            if type_fqtn not in seen_types:
                seen_types.add(type_fqtn)
                tag = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
                references.append(
                    ConfigDIReference(
                        type_fqtn=type_fqtn,
                        config_file=config_path,
                        containing_project=owning_project,
                        element_tag=tag,
                    )
                )

    for elem in tree.iter():
        for attr_value in elem.attrib.values():
            _collect_from(attr_value, elem)
        if elem.text:
            _collect_from(elem.text, elem)

    return references
