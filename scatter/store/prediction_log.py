"""Prediction logging — append JSONL record per --pr-risk run."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from scatter.core.models import PRRiskReport

from scatter.__version__ import __version__

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_SIZE_WARNING_BYTES = 10 * 1024 * 1024  # 10 MB


def build_prediction_record(
    report: "PRRiskReport",
    head_sha: Optional[str],
    base_sha: Optional[str],
    repo_id: str,
) -> Dict[str, Any]:
    """Build a prediction record dict from a PRRiskReport."""
    import os

    agg = report.aggregate
    pr_number_str = os.environ.get("SCATTER_PR_NUMBER")
    try:
        pr_number = int(pr_number_str) if pr_number_str else None
    except (ValueError, TypeError):
        pr_number = None
    return {
        "schema_version": _SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo": repo_id,
        "pr_number": pr_number,
        "branch": report.branch_name,
        "base_branch": report.base_branch,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "scatter_version": __version__,
        "composite_score": round(agg.composite_score, 4),
        "risk_level": report.risk_level.value,
        "dimensions": {d.name: round(d.score, 4) for d in agg.dimensions},
        "dimension_data_available": {d.name: d.data_available for d in agg.dimensions},
        "changed_type_count": len(report.changed_types),
        "direct_consumers": report.total_direct_consumers,
        "transitive_consumers": report.total_transitive_consumers,
        "graph_available": report.graph_available,
        "risk_factors": report.risk_factors[:3],
        "duration_ms": report.duration_ms,
        "outcome": None,
        "outcome_signals": None,
        "merge_sha": None,
    }


def append_prediction(record: Dict[str, Any], repo_path: Path) -> None:
    """Append a JSONL record to .scatter/predictions.jsonl. Never raises."""
    try:
        log_path = repo_path / ".scatter" / "predictions.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            size = log_path.stat().st_size
            if size > _SIZE_WARNING_BYTES:
                logger.warning(
                    "Prediction log is %.1f MB (%s). Consider archiving.",
                    size / (1024 * 1024),
                    log_path,
                )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        logger.debug("Prediction logged to %s", log_path)
    except Exception:
        logger.warning("Failed to write prediction log", exc_info=True)
