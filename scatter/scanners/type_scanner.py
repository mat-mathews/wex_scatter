"""Type extraction and enclosing type detection for C# source files."""

import logging
import re
from typing import List, Optional, Set, Tuple

from scatter.core.models import DELEGATE_DECLARATION_PATTERN, TYPE_DECLARATION_PATTERN


def extract_type_declarations_with_kind(content: str) -> List[Tuple[str, str]]:
    """Extract (type_name, kind) pairs from C# content.

    Returns: [("PortalDataService", "class"), ("IDataAccessor", "interface"), ...]
    """
    results: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    try:
        for match in TYPE_DECLARATION_PATTERN.finditer(content):
            kind = match.group("keyword")
            type_name_full = match.group("type_name").strip()
            type_name_base = re.sub(r"<.*", "", type_name_full).strip()
            type_name_base = type_name_base.split(",")[0].strip()
            if type_name_base and type_name_base not in seen:
                seen.add(type_name_base)
                results.append((type_name_base, kind))

        for match in DELEGATE_DECLARATION_PATTERN.finditer(content):
            type_name = match.group(1).strip()
            if type_name and type_name not in seen:
                seen.add(type_name)
                results.append((type_name, "delegate"))
    except Exception as e:
        logging.warning(f"Regex error during type extraction with kind: {e}")
    return results


def extract_type_names_from_content(content: str) -> Set[str]:
    """
    extracts declared type names (class, struct, interface, enum) from c# file content.
    """
    found_types = set()
    try:
        for pattern in (TYPE_DECLARATION_PATTERN, DELEGATE_DECLARATION_PATTERN):
            for match in pattern.finditer(content):
                # Use named group for TYPE_DECLARATION_PATTERN, positional for DELEGATE
                try:
                    type_name_full = match.group("type_name").strip()
                except IndexError:
                    type_name_full = match.group(1).strip()
                type_name_base = re.sub(r"<.*", "", type_name_full).strip()
                type_name_base = type_name_base.split(",")[0].strip()
                if type_name_base:
                    found_types.add(type_name_base)
    except Exception as e:
        logging.warning(f"Regex error during type extraction: {e}")
    return found_types


def find_enclosing_type_name(content: str, match_start_index: int) -> Optional[str]:
    """
    Tries to find the name of the immediately enclosing type (class, struct, interface, enum)
    for a given position within the code content by searching backwards using regex.
    """
    enclosing_type_pattern = re.compile(
        r"^\s*(?:(?:public|internal|private|protected)\s+)?(?:(?:static|abstract|sealed|partial|record|readonly|ref)\s+)*"
        r"(class|struct|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_<>,\s]*)",
        re.MULTILINE,
    )

    last_found_type_name: Optional[str] = None
    last_match_start = -1

    try:
        for match in enclosing_type_pattern.finditer(content, 0, match_start_index):
            if match.start() > last_match_start:
                last_match_start = match.start()
                type_name_full = match.group(2).strip()
                type_name_base = re.sub(r"<.*", "", type_name_full).strip()
                type_name_base = type_name_base.split(",")[0].strip()
                if type_name_base:
                    last_found_type_name = type_name_base
                    logging.debug(
                        f"  Found potential enclosing type '{last_found_type_name}' at index {match.start()} before index {match_start_index}"
                    )

    except Exception as e:
        logging.warning(f"Regex error during enclosing type search: {e}")
        return None

    if last_found_type_name:
        logging.debug(f"  Determined closest enclosing type name: {last_found_type_name}")
        return last_found_type_name
    else:
        logging.warning(f"  Could not determine enclosing type name near index {match_start_index}")
        return None
