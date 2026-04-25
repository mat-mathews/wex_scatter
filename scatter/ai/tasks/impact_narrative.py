"""AI impact narrative — manager-friendly summary of the full impact report."""

import json
import logging
from typing import Any, Dict, Optional

from scatter.core.models import ImpactReport


def generate_impact_narrative(
    report: ImpactReport,
    ai_provider,
) -> Optional[Dict[str, Any]]:
    """Generate a manager-friendly impact narrative for the full report.

    Returns {narrative} or None on failure.
    """
    if not ai_provider:
        return None

    if not report.targets:
        return {
            "narrative": "No impact detected. The work request does not appear to affect any known consumers."
        }

    return generate_narrative_with_model(ai_provider.model, report)


def generate_narrative_with_model(
    model_instance,
    report: ImpactReport,
) -> Optional[Dict[str, Any]]:
    """Module-level function accepting any model with generate_content()."""
    # Build a summary of the report for the AI
    target_summaries = []
    for ti in report.targets:
        direct = sum(1 for c in ti.consumers if c.depth == 0)
        transitive = sum(1 for c in ti.consumers if c.depth > 0)
        pipelines = sorted(set(c.pipeline_name for c in ti.consumers if c.pipeline_name))
        target_summaries.append(
            f"- {ti.target.name} ({ti.target.target_type}): "
            f"{direct} direct, {transitive} transitive consumers. "
            f"Pipelines: {', '.join(pipelines) if pipelines else 'none identified'}"
        )

    prompt = f"""Write a 1-2 paragraph executive summary of the following impact analysis.
This should be suitable for inclusion in a project scoping email or ticket.

Work Request:
```
{report.sow_text[:500]}
```

Complexity: {report.complexity_rating or "Not assessed"}
{f"Effort estimate: {report.effort_estimate}" if report.effort_estimate else ""}

Affected targets:
{chr(10).join(target_summaries)}

Return ONLY a JSON object with:
- "narrative": the 1-2 paragraph summary text

Write in a professional, concise tone. Focus on business impact, risk areas, and deployment considerations.
Return ONLY the JSON object:"""

    try:
        response = model_instance.generate_content(prompt)
        response_text = response.text.strip()

        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            response_text = "\n".join(lines).strip()

        result = json.loads(response_text)
        if not isinstance(result, dict):
            logging.warning(f"Impact narrative returned non-dict: {response_text}")
            return None

        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse impact narrative JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI impact narrative failed: {e}")
        return None
