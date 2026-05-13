"""Parse a work request (SOW) into structured AnalysisTarget list using AI."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from scatter.core.models import AnalysisTarget, CONFIDENCE_HIGH
from scatter.core.parallel import find_files_with_pattern_parallel


def parse_work_request(
    sow_text: str,
    ai_provider,
    search_scope: Path,
    codebase_index=None,
) -> List[AnalysisTarget]:
    """Parse SOW text into structured targets, resolving project names to csproj paths on disk."""
    if not ai_provider:
        logging.error("AI provider required for work request parsing.")
        return []

    raw_targets = parse_work_request_with_model(
        ai_provider.model,
        sow_text,
        codebase_index=codebase_index,
    )
    if not raw_targets:
        return []

    # Build set of names present in the index for validation
    index_names: Optional[Set[str]] = None
    if codebase_index and codebase_index.text:
        index_names = _extract_index_names(codebase_index.text)

    # Resolve project names to .csproj paths
    csproj_cache: Optional[List[Path]] = None
    targets: List[AnalysisTarget] = []

    for item in raw_targets:
        target_type = item.get("type", "project")
        name = item.get("name", "")
        class_name = item.get("class_name")
        method_name = item.get("method_name")
        confidence = float(item.get("confidence", CONFIDENCE_HIGH))
        match_evidence = item.get("match_evidence")

        if not name:
            continue

        # Validate name against index — drop targets not found
        if index_names is not None and name not in index_names:
            logging.info(f"Dropping target '{name}' — not found in codebase index")
            continue

        csproj_path = None
        namespace = None

        if target_type in ("project", "class"):
            # Resolve to .csproj on disk
            if csproj_cache is None:
                csproj_cache = find_files_with_pattern_parallel(search_scope, "*.csproj")

            csproj_path = _resolve_project_name(name, csproj_cache)
            if csproj_path:
                namespace = csproj_path.stem

        targets.append(
            AnalysisTarget(
                target_type=target_type,
                name=name,
                csproj_path=csproj_path,
                namespace=namespace,
                class_name=class_name,
                method_name=method_name,
                confidence=confidence,
                match_evidence=match_evidence,
            )
        )

    return targets


MAX_SOW_TEXT_LENGTH = 50_000


def parse_work_request_with_model(
    model_instance,
    sow_text: str,
    codebase_index=None,
) -> Optional[List[Dict]]:
    """Module-level function accepting any model with generate_content().

    Returns raw parsed JSON list of target dicts, or None on failure.

    # SECURITY: sow_text is user-supplied and injected into the prompt below.
    # Mitigations: (1) length cap prevents context-window/cost blowout,
    # (2) triple-backtick fencing isolates user content from instructions,
    # (3) output parsed via json.loads (not eval), (4) downstream codebase
    # index validation halves confidence for names not in the known set.
    """
    if len(sow_text) > MAX_SOW_TEXT_LENGTH:
        logging.error(
            f"SOW text too long ({len(sow_text)} chars, max {MAX_SOW_TEXT_LENGTH}). "
            "Truncate or split the work request."
        )
        return None

    # Build optional index section
    index_section = ""
    if codebase_index and codebase_index.text:
        index_section = f"""
The following codebase index lists all known projects, types, and stored procedures:
===
{codebase_index.text}
===
IMPORTANT: ONLY return names that appear in the codebase index above. Match domain
language in the work request to actual project/class/sproc names from the index.
"""
    else:
        logging.warning("No codebase index available — target identification will be less accurate")

    prompt = f"""Analyze the following work request / statement of work and identify the .NET projects
and stored procedures that will be modified or affected.
{index_section}
Return a JSON array of objects. Each object should have:
- "type": one of "project" or "sproc"
- "name": the project name (e.g., "GalaxyWorks.Data") or stored procedure name (e.g., "dbo.sp_InsertPortalConfiguration")
- "class_name": (optional) specific class being modified, if mentioned
- "method_name": (optional) specific method being modified, if mentioned
- "confidence": a number 0.0 to 1.0 indicating how confident you are this is a real target
- "match_evidence": one sentence explaining why you identified this as a target

Rules:
- Return ONLY targets whose names appear in the codebase index above
- Strongly prefer "project" type targets — if a class belongs to a project, return the PROJECT name with the class in "class_name"
- Do NOT return individual classes, DTOs, interfaces, or validators as standalone targets
- For stored procedures, include the schema prefix (e.g., "dbo.")
- Be conservative with confidence — only use 1.0 when the target is explicitly named
- Focus on the 15-20 most important targets — do not exhaustively list every touched component
- Return ONLY the JSON array, no other text

Work request:
```
{sow_text}
```

Return ONLY the JSON array:"""

    try:
        response = model_instance.generate_content(prompt)
        response_text = response.text.strip()

        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            response_text = "\n".join(lines).strip()

        result = json.loads(response_text)
        if not isinstance(result, list):
            logging.warning(f"Work request parsing returned non-list: {response_text}")
            return None

        logging.info(f"AI extracted {len(result)} target(s) from work request.")
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse AI response as JSON: {e}")
        return None
    except Exception as e:
        logging.warning(f"AI work request parsing failed: {e}")
        return None


def _extract_index_names(index_text: str) -> Set[str]:
    """Extract project names, type names, and sproc names from index text.

    Parses the compact one-line-per-project format:
        P:Name T:Type1,Type2 SP:sproc1,sproc2
    """
    names: Set[str] = set()
    for line in index_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("P:"):
            continue
        # Parse space-separated key:value fields
        for field in stripped.split():
            if ":" not in field:
                continue
            key, _, value = field.partition(":")
            if not value:
                continue
            if key == "P":
                names.add(value)
            elif key == "T":
                # Strip trailing "..." from truncated lists
                if value.endswith("..."):
                    value = value[:-3]
                for t in value.split(","):
                    t = t.strip()
                    if t:
                        names.add(t)
            elif key == "SP":
                for s in value.split(","):
                    s = s.strip()
                    if s:
                        names.add(s)
    return names


def _resolve_project_name(name: str, csproj_files: List[Path]) -> Optional[Path]:
    """Resolve a project name to its .csproj path on disk."""
    name_lower = name.lower()

    # Exact match first
    for p in csproj_files:
        if p.stem.lower() == name_lower:
            return p

    # Partial match (project name contained in filename)
    for p in csproj_files:
        if name_lower in p.stem.lower():
            return p

    logging.warning(f"Could not resolve project name '{name}' to a .csproj file.")
    return None
