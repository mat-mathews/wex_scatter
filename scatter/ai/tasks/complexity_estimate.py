"""AI complexity estimate — data-informed complexity rating for CSE scoping."""
import json
import logging
from typing import Any, Dict, Optional

from scatter.core.models import ImpactReport


def estimate_complexity(
    report: ImpactReport,
    ai_provider,
) -> Optional[Dict[str, Any]]:
    """Estimate complexity for the full impact report.

    Returns {rating, justification, effort_estimate, factors} or None on failure.
    """
    if not ai_provider:
        return None

    if not report.targets:
        return {
            "rating": "Low",
            "justification": "No affected targets identified.",
            "effort_estimate": "< 1 developer-day",
            "factors": [],
        }

    return estimate_complexity_with_model(ai_provider.model, report)


def estimate_complexity_with_model(
    model_instance,
    report: ImpactReport,
) -> Optional[Dict[str, Any]]:
    """Module-level function accepting any model with generate_content()."""
    # Collect metrics for AI
    total_consumers = 0
    max_depth = 0
    all_pipelines = set()
    risk_ratings = []

    for ti in report.targets:
        total_consumers += len(ti.consumers)
        max_depth = max(max_depth, ti.max_depth_reached)
        for c in ti.consumers:
            if c.pipeline_name:
                all_pipelines.add(c.pipeline_name)
            if c.risk_rating:
                risk_ratings.append(c.risk_rating)

    prompt = f"""Estimate the implementation complexity for the following work request.

Work Request: {report.sow_text[:500]}

Impact metrics:
- Number of targets: {len(report.targets)}
- Total consumers affected: {total_consumers}
- Maximum transitive depth: {max_depth}
- Unique pipelines affected: {len(all_pipelines)} ({', '.join(sorted(all_pipelines)) if all_pipelines else 'none'})
- Risk ratings across consumers: {', '.join(risk_ratings) if risk_ratings else 'none assessed'}

Return ONLY a JSON object with:
- "rating": one of "Low", "Medium", "High", "Critical"
- "justification": a 1-2 sentence explanation
- "effort_estimate": estimated effort as a range, e.g., "3-5 developer-days"
- "factors": a list of key complexity factors (strings)

Complexity criteria:
- Low: 1 target, few consumers, shallow depth → 1-2 developer-days
- Medium: 2-3 targets OR moderate consumers → 3-5 developer-days
- High: 4+ targets OR many consumers OR deep transitive chains → 5-10 developer-days
- Critical: core library changes with wide blast radius → 10+ developer-days

Return ONLY the JSON object:"""

    try:
        response = model_instance.generate_content(prompt)
        response_text = response.text.strip()

        if response_text.startswith("```"):
            lines = response_text.split('\n')
            lines = [l for l in lines if not l.startswith("```")]
            response_text = '\n'.join(lines).strip()

        result = json.loads(response_text)
        if not isinstance(result, dict):
            logging.warning(f"Complexity estimate returned non-dict: {response_text}")
            return None

        logging.info(f"Complexity estimate: {result.get('rating', 'Unknown')} — {result.get('effort_estimate', 'N/A')}")
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse complexity estimate JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI complexity estimate failed: {e}")
        return None
