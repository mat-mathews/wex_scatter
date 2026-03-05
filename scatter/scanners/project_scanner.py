"""Project file discovery and namespace derivation from .csproj files."""
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


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
            csproj_files = list(current_path.glob('*.csproj'))
            if csproj_files:
                project_file = csproj_files[0].resolve()
                logging.debug(f"Found project file '{project_file.name}' in '{current_path}' for C# file '{cs_file_abs_path.name}'")
                return project_file
        except Exception as e:
            logging.warning(f"Error searching for .csproj in '{current_path}' for '{cs_file_abs_path.name}': {e}")
            return None

        if current_path == current_path.parent:
            logging.debug(f"Reached filesystem root without finding .csproj for '{cs_file_abs_path.name}'")
            break
        current_path = current_path.parent

    logging.warning(f"No .csproj file found upwards from C# file '{cs_file_abs_path.name}' in its directory tree.")
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
        namespaces = {'msb': 'http://schemas.microsoft.com/developer/msbuild/2003'}
        tree = ET.parse(csproj_path)
        root = tree.getroot()

        tags_to_check = ['RootNamespace', 'AssemblyName']

        for tag in tags_to_check:
            xpath_query = f'.//msb:{tag}'
            elem = root.find(xpath_query, namespaces)
            if elem is None:
                elem = root.find(f'.//{tag}')

            if elem is not None and elem.text:
                namespace_value = elem.text.strip()
                if namespace_value:
                    logging.debug(f"Derived namespace '{namespace_value}' from <{tag}> in {csproj_path.name}")
                    return namespace_value

        logging.warning(f"<{'> or <'.join(tags_to_check)}> tags not found or empty in {csproj_path.name}. Falling back to filename stem '{csproj_path.stem}' as namespace.")
        return csproj_path.stem

    except ET.ParseError as e:
        logging.error(f"Failed to parse XML for namespace derivation in {csproj_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error deriving namespace from {csproj_path}: {e}")
        return None
