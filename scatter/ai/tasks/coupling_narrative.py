"""AI coupling narrative — explains why a dependency exists."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from scatter.core.models import AnalysisTarget, EnrichedConsumer


def explain_coupling(
    target: AnalysisTarget,
    consumer: EnrichedConsumer,
    ai_provider,
    search_scope: Path,
) -> Optional[Dict[str, Any]]:
    """Explain the coupling between a target and a consumer.

    Reads consumer's relevant .cs files for context, asks AI to explain
    the dependency and suggest decoupling strategies.

    Returns {narrative, vectors} or None on failure.
    """
    if not ai_provider:
        return None

    # Read relevant file contents for context
    file_contexts = []
    for f in consumer.relevant_files[:5]:  # Limit to 5 files
        try:
            if f.is_file():
                content = f.read_text(encoding='utf-8', errors='ignore')
                file_contexts.append(f"// File: {f.name}\n{content[:5000]}")
        except OSError:
            continue

    if not file_contexts:
        return None

    return explain_coupling_with_model(
        ai_provider.model, target, consumer, file_contexts
    )


def explain_coupling_with_model(
    model_instance,
    target: AnalysisTarget,
    consumer: EnrichedConsumer,
    file_contexts: list,
) -> Optional[Dict[str, Any]]:
    """Module-level function accepting any model with generate_content()."""
    combined_context = "\n\n".join(file_contexts)

    prompt = f"""Analyze the coupling between these two .NET components.

Target component: {target.name}
{f"Class: {target.class_name}" if target.class_name else ""}
Consumer: {consumer.consumer_name}

The following C# files in the consumer reference the target:

{combined_context[:15000]}

Return ONLY a JSON object with:
- "narrative": a 2-3 sentence explanation of HOW and WHY the consumer depends on the target
- "vectors": a list of coupling vectors (strings), e.g., ["Direct class instantiation", "Interface implementation", "Extension method usage"]

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
            logging.warning(f"Coupling narrative returned non-dict: {response_text}")
            return None

        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse coupling narrative JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI coupling narrative failed: {e}")
        return None
