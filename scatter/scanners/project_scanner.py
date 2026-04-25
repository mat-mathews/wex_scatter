"""Project file discovery and namespace derivation from .csproj files."""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_project_file_on_disk(cs_file_abs_path: Path) -> Optional[Path]:
    """
    Finds the .csproj file corresponding to a given C# file by searching upwards
    in the directory tree from the C# file's location.
    Returns the absolute path to the first .csproj found, or None.
    """
    logging.debug(f"Attempting to find project on disk for: {cs_file_abs_path}")
    current_path = cs_file_abs_path.parent
    while True:
        try:
            csproj_files = list(current_path.glob("*.csproj"))
            if csproj_files:
                project_file = csproj_files[0].resolve()
                logging.debug(
                    f"Found project file '{project_file.name}' in '{current_path}' for C# file '{cs_file_abs_path.name}'"
                )
                return project_file
        except Exception as e:
            logging.warning(
                f"Error searching for .csproj in '{current_path}' for '{cs_file_abs_path.name}': {e}"
            )
            return None

        if current_path == current_path.parent:
            logging.debug(
                f"Reached filesystem root without finding .csproj for '{cs_file_abs_path.name}'"
            )
            break
        current_path = current_path.parent

    logging.warning(
        f"No .csproj file found upwards from C# file '{cs_file_abs_path.name}' in its directory tree."
    )
    return None


def derive_namespace(csproj_path: Path) -> Optional[str]:
    """
    Attempts to derive the primary namespace from a .csproj file.
    checks <RootNamespace>, then <AssemblyName> or falls back to filename stem.
    """
    if not csproj_path.is_file():
        logging.error(f"Target project file not found for namespace derivation: {csproj_path}")
        return None
    try:
        namespaces = {"msb": "http://schemas.microsoft.com/developer/msbuild/2003"}
        tree = ET.parse(csproj_path)
        root = tree.getroot()

        tags_to_check = ["RootNamespace", "AssemblyName"]

        for tag in tags_to_check:
            xpath_query = f".//msb:{tag}"
            elem = root.find(xpath_query, namespaces)
            if elem is None:
                elem = root.find(f".//{tag}")

            if elem is not None and elem.text:
                namespace_value = elem.text.strip()
                if namespace_value:
                    logging.debug(
                        f"Derived namespace '{namespace_value}' from <{tag}> in {csproj_path.name}"
                    )
                    return namespace_value

        logging.warning(
            f"<{'> or <'.join(tags_to_check)}> tags not found or empty in {csproj_path.name}. Falling back to filename stem '{csproj_path.stem}' as namespace."
        )
        return csproj_path.stem

    except ET.ParseError as e:
        logging.error(f"Failed to parse XML for namespace derivation in {csproj_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error deriving namespace from {csproj_path}: {e}")
        return None


def parse_csproj(
    csproj_path: Path, search_scope: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Parse a .csproj file and extract all metadata in a single XML pass.

    Returns dict with keys:
    - 'project_references': List[str]  — Include attribute values from <ProjectReference>
    - 'explicit_imports': List[Path]   — resolved local .props/.targets from <Import>
    - 'root_namespace': Optional[str]
    - 'assembly_name': Optional[str]
    - 'target_framework': Optional[str]
    - 'output_type': Optional[str]
    - 'project_style': str  — "sdk" or "framework"

    Returns None if file doesn't exist or can't be parsed.
    """
    if not csproj_path.is_file():
        logging.warning(f"Csproj file not found: {csproj_path}")
        return None

    try:
        tree = ET.parse(csproj_path)
        root = tree.getroot()
    except (ET.ParseError, OSError) as e:
        logging.warning(f"Could not parse {csproj_path}: {e}")
        return None

    msb_ns = {"msb": "http://schemas.microsoft.com/developer/msbuild/2003"}
    msb_ns_uri = "{http://schemas.microsoft.com/developer/msbuild/2003}"

    # Detect project style: SDK-style has Sdk attribute on <Project> element
    project_style = "sdk" if root.get("Sdk") else "framework"

    def _find_text(tag: str) -> Optional[str]:
        """Find element text, trying without and with MSBuild namespace."""
        elem = root.find(f".//{tag}")
        if elem is None:
            elem = root.find(f".//msb:{tag}", msb_ns)
        if elem is not None and elem.text:
            return elem.text.strip()
        return None

    # Extract ProjectReferences
    refs: List[str] = []
    for ref in root.findall(".//ProjectReference"):
        include = ref.get("Include")
        if include:
            refs.append(include.replace("\\", "/"))
    if not refs:
        for ref in root.findall(".//msb:ProjectReference", msb_ns):
            include = ref.get("Include")
            if include:
                refs.append(include.replace("\\", "/"))

    # Extract explicit <Import> elements (same XML tree, no re-parse)
    explicit_imports: List[Path] = []
    if search_scope is not None:
        try:
            explicit_imports = _extract_explicit_imports(
                root, msb_ns_uri, csproj_path, search_scope
            )
        except Exception as e:
            logging.warning(
                f"Import extraction failed for {csproj_path}, continuing without imports: {e}"
            )

    return {
        "project_references": refs,
        "explicit_imports": explicit_imports,
        "root_namespace": _find_text("RootNamespace"),
        "assembly_name": _find_text("AssemblyName"),
        "target_framework": _find_text("TargetFramework") or _find_text("TargetFrameworkVersion"),
        "output_type": _find_text("OutputType"),
        "project_style": project_style,
    }


# Keep old name as alias for backward compatibility with external callers
parse_csproj_all_references = parse_csproj


_SYSTEM_IMPORT_MARKERS = frozenset(
    {
        "$(MSBuildExtensionsPath)",
        "$(MSBuildToolsPath)",
        "$(MSBuildBinPath)",
        "$(VSToolsPath)",
        "$(NuGetPackageRoot)",
        "Microsoft.Common.props",
        "Microsoft.CSharp.targets",
        "Microsoft.WebApplication.targets",
    }
)

_DIRECTORY_BUILD_NAMES = frozenset({"Directory.Build.props", "Directory.Build.targets"})


def _extract_explicit_imports(
    root: ET.Element, msb_ns_uri: str, csproj_path: Path, search_scope: Path
) -> List[Path]:
    """Extract <Import Project="..."> elements from an already-parsed XML tree."""
    imports: List[Path] = []

    for import_elem in list(root.findall(".//Import")) + list(
        root.findall(f".//{msb_ns_uri}Import")
    ):
        project_attr = import_elem.get("Project", "")
        if not project_attr or any(m in project_attr for m in _SYSTEM_IMPORT_MARKERS):
            continue

        resolved = project_attr.replace("\\", "/")
        resolved = resolved.replace("$(MSBuildThisFileDirectory)", str(csproj_path.parent) + "/")
        if "$(" in resolved:
            continue

        try:
            abs_path = (csproj_path.parent / resolved).resolve()
            if not abs_path.is_file():
                continue
            abs_path.relative_to(search_scope.resolve())
            if abs_path.name not in _DIRECTORY_BUILD_NAMES:
                imports.append(abs_path)
        except (ValueError, OSError):
            continue

    return imports
