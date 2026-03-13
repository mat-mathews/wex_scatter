"""Shared tree-building utilities for blast radius rendering."""
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")

# Sort rank derived from the pre-computed confidence_label field.
# No threshold logic here — labels are already assigned in models._confidence_label.
CONFIDENCE_LABEL_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def build_adjacency(
    items: List[T],
    get_name: Callable[[T], str],
    get_parent: Callable[[T], Optional[str]],
    sort_key: Optional[Callable[[T], Any]] = None,
) -> Dict[Optional[str], List[T]]:
    """Group items into a parent -> [children] adjacency dict.

    Direct items (parent is None) are children of the root (keyed by None).
    Orphans whose parent name isn't found among item names are re-parented to root.

    Note: parent matching uses consumer_name which is assumed unique within a
    single analysis scope.  Duplicate names from different paths would cause
    ambiguous parent resolution — a known limitation when the same project
    name appears at multiple paths.
    """
    names = {get_name(item) for item in items}
    tree: Dict[Optional[str], List[T]] = defaultdict(list)
    for item in items:
        parent = get_parent(item)
        if parent is not None and parent not in names:
            parent = None
        tree[parent].append(item)
    if sort_key:
        for children in tree.values():
            children.sort(key=sort_key)
    return dict(tree)
