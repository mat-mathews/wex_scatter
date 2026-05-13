"""Per-target change surface analysis using AI.

Identifies which specific types and sprocs in a project would need
modification to implement a given work request. Uses index data only
(no file I/O) — types and sprocs come from the dependency graph.

# SECURITY: sow_text is user-supplied and injected into the prompt.
# Mitigations: (1) triple-backtick fencing isolates user content,
# (2) output parsed via json.loads (not eval), (3) upstream length
# cap on SOW text (MAX_SOW_TEXT_LENGTH in parse_work_request.py).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from scatter.core.models import AnalysisTarget


def assess_change_surface_with_model(
    model_instance,
    target: AnalysisTarget,
    types: List[str],
    sprocs: List[str],
    sow_text: str,
    consumer_count: int,
) -> Optional[Dict[str, Any]]:
    """Identify which components in a project would need changes for a work request.

    Returns {changes: [{component, change, complexity}], notes: [...]} or None on failure.
    """
    types_str = ", ".join(types[:30]) if types else "(none)"
    sprocs_str = ", ".join(sprocs[:20]) if sprocs else "(none)"
    evidence = target.match_evidence or "(not specified)"

    prompt = f"""Given the following work request and .NET project, identify the specific
components that would need to change to implement the work.

Work request:
```
{sow_text[:3000]}
```

Project: {target.name}
Types in this project: {types_str}
Stored procedures: {sprocs_str}
Why this project was identified: {evidence}
Number of downstream consumers: {consumer_count}

Return ONLY a JSON object with:
- "changes": a list of objects, each with:
  - "component": the type or sproc name that needs modification
  - "change": one sentence describing the specific change needed
  - "complexity": one of "low", "medium", "high"
- "notes": (optional) a list of implementation considerations or risks

Focus on the most important changes. Do not list components that would not need modification.

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
            logging.warning(f"Change surface returned non-dict: {response_text}")
            return None

        change_count = len(result.get("changes", []))
        logging.info(f"Change surface for {target.name}: {change_count} component(s)")
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse change surface JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI change surface assessment failed: {e}")
        return None
