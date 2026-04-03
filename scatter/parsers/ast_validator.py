"""AST validation layer using tree-sitter to filter regex false positives.

All public functions gracefully return the regex input on any error,
so hybrid mode never produces *fewer* results than regex-only due to crashes.
"""

import bisect
import logging
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# Module-level cache for the parser instance (created lazily).
# Typed as Any because tree-sitter is an optional dependency —
# the actual types (Language, Parser, Query) are only available at runtime.
_parser: Any = None
_ts_language: Any = None

# Cache compiled Query objects (compilation is the repeated cost;
# QueryCursor is stateful and must be fresh per call).
_query_cache: Dict[str, Any] = {}


def is_hybrid_available() -> bool:
    """Check whether tree-sitter and the C# grammar are importable."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_c_sharp  # noqa: F401

        return True
    except ImportError:
        return False


def _get_parser():
    """Return a cached tree-sitter Parser configured for C#."""
    global _parser, _ts_language
    if _parser is not None:
        return _parser

    try:
        import tree_sitter
        import tree_sitter_c_sharp

        _ts_language = tree_sitter.Language(tree_sitter_c_sharp.language())
        _parser = tree_sitter.Parser(_ts_language)
        return _parser
    except Exception:
        # Reset both globals so next call retries instead of returning stale state
        _parser = None
        _ts_language = None
        raise


def parse_csharp(content: str):
    """Parse C# content and return the tree-sitter Tree."""
    parser = _get_parser()
    return parser.parse(content.encode("utf-8"))


def _run_query(query_string: str, root_node, capture_name: str):
    """Run a tree-sitter query and yield captured nodes."""
    if _ts_language is None:
        _get_parser()  # ensure language initialized
    import tree_sitter

    query = _query_cache.get(query_string)
    if query is None:
        query = tree_sitter.Query(_ts_language, query_string)
        _query_cache[query_string] = query
    cursor = tree_sitter.QueryCursor(query)
    for _, captures in cursor.matches(root_node):
        for node in captures.get(capture_name, []):
            yield node


def _build_non_code_ranges(tree) -> List[Tuple[int, int]]:
    """Extract sorted (start_byte, end_byte) intervals for non-code nodes."""
    from scatter.parsers.ts_queries import NON_CODE_RANGES_QUERY

    ranges = []
    for node in _run_query(NON_CODE_RANGES_QUERY, tree.root_node, "non_code"):
        ranges.append((node.start_byte, node.end_byte))
    ranges.sort()
    return ranges


def _is_in_non_code(position: int, ranges: List[Tuple[int, int]]) -> bool:
    """Binary search to check if a byte position falls inside any non-code range."""
    if not ranges:
        return False
    idx = bisect.bisect_right(ranges, (position, float("inf"))) - 1
    if idx < 0:
        return False
    start, end = ranges[idx]
    return start <= position < end


def identifiers_in_code(content: str, candidates: Dict[str, List[int]]) -> Set[str]:
    """Filter identifier candidates, keeping only those with at least one code occurrence.

    Args:
        content: Full C# file content.
        candidates: Map of identifier -> list of byte positions from regex pass.

    Returns:
        Set of identifiers that appear at least once outside comments/strings.
    """
    if not candidates:
        return set()
    try:
        tree = parse_csharp(content)
        non_code = _build_non_code_ranges(tree)
    except Exception:
        logger.debug(
            "AST parse failed in identifiers_in_code; returning all candidates", exc_info=True
        )
        return set(candidates.keys())

    result = set()
    for identifier, positions in candidates.items():
        for pos in positions:
            if not _is_in_non_code(pos, non_code):
                result.add(identifier)
                break  # one code occurrence is enough
    return result


def validate_type_declarations(content: str, regex_types: Set[str]) -> Set[str]:
    """Intersect regex-detected type names with AST-confirmed declarations.

    Args:
        content: Full C# file content.
        regex_types: Type names found by regex.

    Returns:
        Subset of regex_types that the AST confirms as actual type declarations.
    """
    if not regex_types:
        return set()
    try:
        from scatter.parsers.ts_queries import TYPE_DECLARATIONS_QUERY

        tree = parse_csharp(content)
        ast_types = set()
        for node in _run_query(TYPE_DECLARATIONS_QUERY, tree.root_node, "type_name"):
            ast_types.add(node.text.decode("utf-8"))
        return regex_types & ast_types
    except Exception:
        logger.debug(
            "AST parse failed in validate_type_declarations; returning regex input",
            exc_info=True,
        )
        return regex_types


def validate_type_usage(content: str, type_name: str) -> bool:
    """Confirm at least one occurrence of type_name is in a code position.

    Used by the consumer analyzer (stages 4-5) to filter regex matches
    that only appear in comments or string literals.

    Args:
        content: Full C# file content.
        type_name: The type name to look for.

    Returns:
        True if at least one occurrence is in code (not comment/string).
    """
    try:
        content_bytes = content.encode("utf-8")
        tree = parse_csharp(content)
        non_code = _build_non_code_ranges(tree)

        # Find all occurrences of type_name in the byte string
        encoded_name = type_name.encode("utf-8")
        start = 0
        while True:
            idx = content_bytes.find(encoded_name, start)
            if idx == -1:
                return False
            if not _is_in_non_code(idx, non_code):
                return True
            start = idx + 1
    except Exception:
        logger.debug(
            "AST parse failed in validate_type_usage; returning True (conservative)",
            exc_info=True,
        )
        return True
