"""AI effort adjustment — optional overlay on graph-derived estimates.

Follows existing AI task pattern (see complexity_estimate.py).
Graph baseline is authoritative; AI adjustment is labeled overlay (Decision #5).
"""

import json
import logging
from typing import Any, Dict, Optional

from scatter.core.models import ImpactReport
from scatter.core.scoping_models import ConfidenceBand, DatabaseImpact, EffortBreakdown


def adjust_effort(
    impact_report: ImpactReport,
    effort: EffortBreakdown,
    confidence: ConfidenceBand,
    db_impact: DatabaseImpact,
    ai_provider,
) -> Optional[Dict[str, Any]]:
    """Ask AI to adjust graph-derived effort estimate.

    Returns {min_days, max_days, adjustment_narrative} or None on failure.
    """
    if not ai_provider:
        return None

    return _adjust_effort_with_model(
        ai_provider.model, impact_report, effort, confidence, db_impact
    )


def _adjust_effort_with_model(
    model_instance,
    impact_report: ImpactReport,
    effort: EffortBreakdown,
    confidence: ConfidenceBand,
    db_impact: DatabaseImpact,
) -> Optional[Dict[str, Any]]:
    """Module-level function accepting any model with generate_content()."""
    # Build effort table for prompt
    effort_lines = []
    for cat in effort.categories:
        effort_lines.append(
            f"  {cat.name}: {cat.base_days:.1f} days (min {cat.min_days:.1f}, max {cat.max_days:.1f})"
        )
    effort_table = "\n".join(effort_lines)

    # DB impact summary
    db_summary = f"{db_impact.total_shared_sprocs} shared sprocs, complexity: {db_impact.migration_complexity}"

    # Risk composite
    risk_score = confidence.composite_score

    # Target and consumer context for grounding (Marcus review)
    target_lines = []
    for ti in impact_report.targets or []:
        consumer_names = [c.consumer_name for c in ti.consumers[:10]]
        suffix = f" (+{len(ti.consumers) - 10} more)" if len(ti.consumers) > 10 else ""
        target_lines.append(
            f"  {ti.target.name} ({ti.target.target_type}): "
            f"{ti.total_direct} direct, {ti.total_transitive} transitive — "
            f"{', '.join(consumer_names)}{suffix}"
        )
    target_detail = "\n".join(target_lines) if target_lines else "  (none)"

    prompt = f"""Review and adjust the following graph-derived effort estimate for a work request.

Work Request: {impact_report.sow_text[:500]}

Targets and consumers:
{target_detail}

Graph-derived effort breakdown:
{effort_table}
Total: {effort.total_base_days:.1f} days (range: {effort.total_min_days:.1f}-{effort.total_max_days:.1f})

Confidence: {confidence.level.value} (+-{confidence.band_pct:.0%})
Database impact: {db_summary}
Risk composite score: {risk_score:.2f}
Ambiguity: {confidence.ambiguity_level}
Overall risk: {impact_report.overall_risk or "Not assessed"}

Based on the work request, targets, consumers, and metrics above,
provide an adjusted estimate if the graph baseline seems off. Consider:
- Are there hidden complexities the graph can't capture?
- Does the work request imply coordination/communication overhead?
- Are there testing scenarios beyond what consumer count suggests?
- Do the specific consumers listed suggest cross-team coordination?

Return ONLY a JSON object with:
- "min_days": adjusted minimum days (float)
- "max_days": adjusted maximum days (float)
- "adjustment_narrative": 1-2 sentence explanation of your adjustment

Return ONLY the JSON object:"""

    try:
        response = model_instance.generate_content(prompt)
        response_text = response.text.strip()

        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            response_text = "\n".join(lines).strip()

        result = json.loads(response_text)
        if not isinstance(result, dict):
            logging.warning(f"Effort adjustment returned non-dict: {response_text}")
            return None

        logging.info(
            "AI effort adjustment: %.1f-%.1f days — %s",
            result.get("min_days", 0),
            result.get("max_days", 0),
            result.get("adjustment_narrative", "no narrative"),
        )
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse effort adjustment JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI effort adjustment failed: {e}")
        return None
