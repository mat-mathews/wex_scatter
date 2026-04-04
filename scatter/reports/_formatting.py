"""Shared formatting helpers for report modules."""

from typing import List


def escape_cell(value: str) -> str:
    """Sanitize a value for use inside a markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def md_table(headers: List[str], rows: List[List[str]], *, escape: bool = True) -> str:
    """Build a markdown table from headers and rows.

    Args:
        headers: Column header strings.
        rows: List of rows, each a list of cell values.
        escape: If True (default), sanitize cell values for markdown.
    """
    _esc = escape_cell if escape else str
    header_line = "| " + " | ".join(_esc(h) for h in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    lines = [header_line, separator]
    for row in rows:
        padded = list(row) + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(_esc(str(v)) for v in padded) + " |")
    return "\n".join(lines)
