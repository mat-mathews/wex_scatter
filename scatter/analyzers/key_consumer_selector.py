"""Identify key consumers — depth-0 consumers prominent enough to surface at report level."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from scatter.core.models import KeyConsumer, TargetImpact

RISK_SEVERITY: Dict[Optional[str], int] = {
    None: 0,
    "Low": 1,
    "Medium": 2,
    "High": 3,
    "Critical": 4,
}
_SEVERITY_TO_LABEL: Dict[int, Optional[str]] = {v: k for k, v in RISK_SEVERITY.items()}
MAX_KEY_CONSUMERS = 10


def select_key_consumers(
    targets: List[TargetImpact],
    max_results: int = MAX_KEY_CONSUMERS,
) -> List[KeyConsumer]:
    """Select consumers that warrant first-class visibility in the report.

    Criteria (either qualifies):
      - Multi-root: depth-0 consumer appearing under >= 2 distinct root targets
      - High-risk: depth-0 consumer with risk_rating in ("High", "Critical")

    Returns at most max_results entries, sorted by appearances desc,
    risk severity desc, name asc (deterministic).
    """
    root_map: Dict[str, Set[str]] = {}
    risk_map: Dict[str, int] = {}

    for ti in targets:
        target_name = ti.target.name
        for consumer in ti.consumers:
            if consumer.depth != 0:
                continue
            name = consumer.consumer_name
            if name not in root_map:
                root_map[name] = set()
            root_map[name].add(target_name)
            severity = RISK_SEVERITY.get(consumer.risk_rating, 0)
            if severity > risk_map.get(name, 0):
                risk_map[name] = severity

    results: List[KeyConsumer] = []
    for name, root_targets in root_map.items():
        appearances = len(root_targets)
        severity = risk_map.get(name, 0)
        qualifies_multi_root = appearances >= 2
        qualifies_high_risk = severity >= RISK_SEVERITY["High"]
        if not (qualifies_multi_root or qualifies_high_risk):
            continue
        max_risk_label = _SEVERITY_TO_LABEL[severity]
        results.append(
            KeyConsumer(
                consumer_name=name,
                appearances=appearances,
                root_targets=sorted(root_targets),
                max_risk=max_risk_label,
            )
        )

    results.sort(
        key=lambda kc: (-kc.appearances, -risk_map.get(kc.consumer_name, 0), kc.consumer_name)
    )
    return results[:max_results]
