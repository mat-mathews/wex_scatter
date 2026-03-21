"""Per-target risk assessment using AI."""

import json
import logging
from typing import Any, Dict, List, Optional

from scatter.core.models import AnalysisTarget, EnrichedConsumer


def assess_risk(
    target: AnalysisTarget,
    consumers: List[EnrichedConsumer],
    ai_provider,
) -> Optional[Dict[str, Any]]:
    """Assess risk for a target given its consumers.

    Returns {rating, justification, concerns, mitigations} or None on failure.
    """
    if not ai_provider:
        return None

    if not consumers:
        return {
            "rating": "Low",
            "justification": "No consumers detected.",
            "concerns": [],
            "mitigations": [],
        }

    return assess_risk_with_model(ai_provider.model, target, consumers)


def assess_risk_with_model(
    model_instance,
    target: AnalysisTarget,
    consumers: List[EnrichedConsumer],
) -> Optional[Dict[str, Any]]:
    """Module-level function accepting any model with generate_content()."""
    direct = [c for c in consumers if c.depth == 0]
    transitive = [c for c in consumers if c.depth > 0]

    consumer_summary = []
    for c in consumers:
        entry = f"- {c.consumer_name} (depth: {c.depth}, pipeline: {c.pipeline_name or 'unknown'})"
        consumer_summary.append(entry)

    prompt = f"""Assess the risk of modifying the following .NET component.

Target: {target.name} (type: {target.target_type})
{f"Class: {target.class_name}" if target.class_name else ""}
{f"Method: {target.method_name}" if target.method_name else ""}

Direct consumers: {len(direct)}
Transitive consumers: {len(transitive)}

Consumer list:
{chr(10).join(consumer_summary)}

Based on this information, provide a risk assessment. Return ONLY a JSON object with:
- "rating": one of "Low", "Medium", "High", "Critical"
- "justification": a 1-2 sentence explanation of the rating
- "concerns": a list of specific concerns (strings)
- "mitigations": a list of suggested mitigations (strings)

Risk criteria:
- Low: 1-2 direct consumers, no transitive, not in critical pipelines
- Medium: 3-5 direct consumers OR some transitive consumers
- High: 6+ direct consumers OR deep transitive chains OR critical pipelines
- Critical: widely used core library with many transitive consumers

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
            logging.warning(f"Risk assessment returned non-dict: {response_text}")
            return None

        logging.info(f"Risk assessment for {target.name}: {result.get('rating', 'Unknown')}")
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse risk assessment JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI risk assessment failed: {e}")
        return None
