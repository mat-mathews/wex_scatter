"""Legacy functions not yet modularized into dedicated submodules.

This module holds AI/Gemini functions that will be extracted into
ai/providers/gemini_provider.py in Phase 4.

Functions already extracted to their permanent homes are re-exported here
for backward compatibility with scatter/__init__.py imports.
"""
import google.generativeai as genai
import json
import logging
import os
from pathlib import Path
from typing import Optional, Set

# Re-export functions that have been moved to their permanent modules.
from scatter.scanners.type_scanner import (
    extract_type_names_from_content,
    find_enclosing_type_name,
)
from scatter.scanners.project_scanner import (
    find_project_file_on_disk,
    derive_namespace,
)
from scatter.scanners.sproc_scanner import find_cs_files_referencing_sproc
from scatter.analyzers.consumer_analyzer import find_consumers
from scatter.analyzers.git_analyzer import (
    find_project_file,
    analyze_branch_changes,
    get_diff_for_file,
)
from scatter.compat.v1_bridge import (
    find_solutions_for_project,
    map_batch_jobs_from_config_repo,
    _process_consumer_summaries_and_append_results,
)


# global variable to hold the configured gemini model
gemini_model = None


def get_affected_symbols_from_diff(file_content: str, diff_text: str,
                                    file_path: str,
                                    model_instance) -> Optional[Set[str]]:
    """
    Uses Gemini to analyze a diff and identify which C# type declarations were meaningfully changed.
    Returns a Set of affected type names, or None on failure (triggers fallback to regex).
    """
    prompt = f"""Analyze the following C# file and its git diff. Identify which top-level type declarations
(class, struct, interface, enum) had their body, signature, or members meaningfully changed in the diff.

Rules:
- Only return type names whose definition/body/members were actually modified in the diff
- Do NOT include types that merely appear in the same file but were not changed
- For comment-only or using/import-only changes, return an empty array
- Return ONLY a JSON array of type name strings, nothing else
- Example: ["MyClass", "IMyInterface"]

File path: {file_path}

Full file content:
```csharp
{file_content}
```

Git diff:
```diff
{diff_text}
```

Return ONLY the JSON array:"""

    try:
        response = model_instance.generate_content(prompt)
        response_text = response.text.strip()

        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split('\n')
            lines = [l for l in lines if not l.startswith("```")]
            response_text = '\n'.join(lines).strip()

        affected = json.loads(response_text)
        if not isinstance(affected, list):
            logging.warning(f"Gemini returned non-list for {file_path}: {response_text}")
            return None

        result = {name for name in affected if isinstance(name, str)}
        logging.info(f"Hybrid analysis for {file_path}: {len(result)} affected type(s) identified by LLM: {result if result else '(none - comment/import only change)'}")
        return result

    except json.JSONDecodeError as e:
        logging.warning(f"Failed to parse Gemini JSON response for {file_path}: {e}")
        return None
    except Exception as e:
        logging.warning(f"Gemini call failed for {file_path}: {e}")
        return None


def configure_gemini(api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash") -> bool:
    """Configures the Gemini client. Returns True on success, False on failure."""
    global gemini_model
    if gemini_model:
        return True

    resolved_api_key = api_key
    if not resolved_api_key:
        resolved_api_key = os.getenv("GOOGLE_API_KEY")

    if not resolved_api_key:
        logging.error("Google API Key not found. Set the GOOGLE_API_KEY environment variable or use the --google-api-key argument.")
        return False

    try:
        logging.debug(f"Configuring Gemini with API key (source: {'Argument' if api_key else 'Environment Variable'})...")
        genai.configure(api_key=resolved_api_key)
        gemini_model = genai.GenerativeModel(model_name)
        logging.info(f"Gemini configured successfully using model '{model_name}'.")
        return True

    except (ValueError, Exception) as e:
        logging.error(f"Error configuring Generative AI: {e}")
        logging.error("Ensure the API key is valid and has permissions for the Gemini API.")
        gemini_model = None
        return False


def summarize_csharp_file_with_gemini(model_instance, csharp_code: str, file_path_for_log: str) -> Optional[str]:
    """
    Uses the provided Gemini API model instance to summarize a C# file's content.
    """
    if not model_instance:
        logging.error("Gemini model instance not provided. Cannot summarize.")
        return None

    if not csharp_code.strip():
        logging.warning(f"Skipping summarization for empty or whitespace-only file: {file_path_for_log}")
        return "[File is empty or contains only whitespace]"

    try:
        prompt = f"""
        Analyze the following C# code from the file '{Path(file_path_for_log).name}':

        ```csharp
        {csharp_code[:20000]} // Limit code length to avoid excessive token usage
        ```

        Please provide a concise summary (2-3 sentences) explaining the primary purpose of the C# code in this file. Focus on what the main classes/structs/interfaces/enums declared within this specific file *do*. Do not list methods or properties unless essential for the summary.
        """

        logging.info(f"Requesting summary for {file_path_for_log} from Gemini API...")
        safety_settings = [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
        ]
        response = model_instance.generate_content(prompt, safety_settings=safety_settings)
        logging.debug(f"Received Gemini response for {file_path_for_log}.")

        if not response.parts:
            logging.warning(f"Gemini response for {file_path_for_log} was empty or blocked. Safety ratings: {response.prompt_feedback}")
            return "[Summary generation blocked or failed]"

        summary = response.text.strip()
        return summary if summary else "[No summary generated]"

    except Exception as e:
        logging.error(f"An error occurred while interacting with the Gemini API for {file_path_for_log}: {e}", exc_info=True)
        return "[Error during summarization]"
