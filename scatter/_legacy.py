"""Legacy functions not yet modularized into dedicated submodules.

This module holds functions that will be extracted into analyzers/git_analyzer.py
and ai/ modules in later phases (Phase 3 and Phase 4).

Functions already extracted to their permanent homes are re-exported here
for backward compatibility with scatter/__init__.py imports.
"""
import google.generativeai as genai
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Set

try:
    import git
except ImportError:
    print("Error: GitPython library not found.")
    print("Please install it using: pip install GitPython")
    sys.exit(1)

# Re-export functions that have been moved to their permanent modules.
# This keeps `from scatter._legacy import X` working in __init__.py.
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
from scatter.compat.v1_bridge import (
    find_solutions_for_project,
    map_batch_jobs_from_config_repo,
    _process_consumer_summaries_and_append_results,
)


# global variable to hold the configured gemini model
gemini_model = None


# --- find_project_file (git tree traversal — Phase 3) ---
def find_project_file(repo: git.Repo, commit: git.Commit, cs_file_relative_path_str: str) -> Optional[str]:
    cs_file_rel_path = Path(cs_file_relative_path_str)
    current_path = cs_file_rel_path.parent

    logging.debug(f"Attempting to find project for: {cs_file_relative_path_str}")
    logging.debug(f"Starting search directory relative to repo root: {current_path.as_posix()}")
    logging.debug(f"Using Git repository root: {repo.working_tree_dir}")

    while True:
        try:
            dir_path_for_tree = current_path.as_posix() if str(current_path) != '.' else '.'
            logging.debug(f"Searching in directory (relative path): {dir_path_for_tree}")

            current_tree = commit.tree
            logging.debug(f"Commit Tree Root Path: {current_tree.path}")
            try:
                logging.debug(f"Root tree children: {[(item.name, item.type) for item in current_tree]}")
            except Exception as log_e:
                logging.warning(f"Could not log root tree children: {log_e}")

            # walk the tree
            if dir_path_for_tree != '.':
                logging.debug(f"Navigating tree for path parts: {current_path.parts}")
                try:
                    temp_tree = commit.tree
                    for i, part in enumerate(current_path.parts):
                        logging.debug(f"   Navigating part {i+1}/{len(current_path.parts)}: '{part}'")
                        try:
                            current_children = [(item.name, item.type) for item in temp_tree]
                            logging.debug(f"       Children of '{temp_tree.path}' ({len(current_children)} items): {current_children}")
                        except Exception as log_e:
                            logging.warning(f"       Could not log children of '{temp_tree.path}': {log_e}")

                        found_item = None
                        for item in temp_tree:
                            if item.name.lower() == part.lower():
                                found_item = item
                                logging.debug(f"        Found matching item via case-insensitive search: '{item.name}', type is '{item.type}'")
                                break

                        if found_item:
                            if found_item.type == 'tree':
                                temp_tree = found_item
                            elif found_item.type == 'blob':
                                logging.error(f"       Path part '{part}' (matched as '{found_item.name}') is a blob (file), not a tree. Cannot descend.")
                                raise KeyError(f"Path component {part} is not a tree")
                            elif found_item.type == 'commit':
                                logging.warning(f"       Path part '{part}' (matched as '{found_item.name}') is a commit object, likely a SUBMODULE. Standard tree traversal will stop here.")
                                raise KeyError(f"Path component {part} is a submodule commit")
                            else:
                                logging.error(f"       Found '{part}' (matched as '{found_item.name}'), but has unexpected type '{found_item.type}'. Stopping.")
                                raise KeyError(f"Path component {part} has unknown type {found_item.type}")
                        else:
                            logging.error(f"       Path part '{part}' NOT FOUND (case-insensitive) in '{temp_tree.path}'.")
                            current_children_final = [(item.name, item.type) for item in temp_tree]
                            logging.debug(f"       Children of '{temp_tree.path}' before failing: {current_children_final}")
                            raise KeyError(f"Path component {part} not found")

                    current_tree = temp_tree
                    logging.debug(f"   Successfully navigated to tree: {current_tree.path}")

                except KeyError as ke:
                    logging.debug(f"Path '{dir_path_for_tree}' traversal failed in commit {commit.hexsha}: {ke}. Stopping upward search.")
                    break # stop searching upwards

            logging.debug(f"Checking blobs in final directory tree: {current_tree.path}")
            found_in_dir = False
            try:
                dir_blobs = [(item.name, item.path) for item in current_tree.blobs]
                logging.debug(f"   Blobs found: {dir_blobs}")
                for item in current_tree.blobs:
                    if item.name.lower().endswith(".csproj"):
                        project_file_path = current_path / item.name
                        project_file_rel_path_str = project_file_path.as_posix()
                        logging.info(f"Found .csproj '{project_file_rel_path_str}' for '{cs_file_relative_path_str}'")
                        return project_file_rel_path_str
            except Exception as blob_e:
                logging.warning(f"Could not list blobs in '{current_tree.path}': {blob_e}")

            logging.debug(f"No .csproj file found in directory: {current_path.as_posix()}")

            if current_path == Path('.'):
                logging.debug("Reached repo root directory representation. Stopping upward search.")
                break
            parent_path = current_path.parent
            logging.debug(f"Moving up search to parent directory: {parent_path.as_posix()}")
            if parent_path == current_path:
                logging.debug("Parent path is same as current path (at root). Stopping upward search.")
                break
            current_path = parent_path

        except git.exc.GitCommandError as e:
            logging.warning(f"Git command error accessing tree for '{dir_path_for_tree}' in {commit.hexsha}: {e}. Stopping upward search.")
            break
        except KeyError:
            break
        except Exception as e:
            logging.error(f"Unexpected error accessing tree for '{dir_path_for_tree}' in {commit.hexsha}: {e}. Stopping upward search.", exc_info=True)
            break

    logging.debug(f"Finished search. No .csproj found upwards from '{cs_file_relative_path_str}'")
    return None


# --- analyze_branch_changes (git — Phase 3) ---
def analyze_branch_changes(repo_path: str, feature_branch_name: str, base_branch_name: str = 'main'):
    """ Analyzes git changes, returns {proj_rel_path_str: [cs_rel_path_str,...]} using POSIX paths"""
    from collections import defaultdict
    project_changes = defaultdict(list)
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
        logging.info(f"Opened repository: {repo.working_tree_dir}")

        if base_branch_name not in repo.heads:
            raise ValueError(f"Base branch '{base_branch_name}' not found in repository.")
        if feature_branch_name not in repo.heads:
            raise ValueError(f"Feature branch '{feature_branch_name}' not found in repository.")

        base_commit = repo.heads[base_branch_name].commit
        logging.info(f"Base branch ({base_branch_name}) commit: {base_commit.hexsha[:7]}")
        feature_commit = repo.heads[feature_branch_name].commit
        logging.info(f"Feature branch ({feature_branch_name}) commit: {feature_commit.hexsha[:7]}")

        merge_bases = repo.merge_base(base_commit, feature_commit)
        if not merge_bases:
            logging.warning(f"No common merge base found between '{base_branch_name}' and '{feature_branch_name}'. Comparing '{feature_branch_name}' against its parent(s). This might not be the intended diff.")
            if feature_commit.parents:
                merge_base_commit = feature_commit.parents[0]
            else:
                raise ValueError(f"Feature branch '{feature_branch_name}' has no parents and no merge base with '{base_branch_name}'. Cannot diff.")
        else:
            merge_base_commit = merge_bases[0]

        logging.info(f"Using commit '{merge_base_commit.hexsha[:7]}' as comparison base.")

        diff_index = merge_base_commit.diff(feature_commit)
        logging.info(f"Found {len(diff_index)} changes between base and {feature_branch_name}.")

        changed_cs_files_count = 0
        project_not_found_count = 0
        logging.info("Analyzing changed C# files to identify projects...")
        for diff_item in diff_index:
            logging.debug(f"diff_item: {diff_item} - {diff_item.change_type}")
            if diff_item.change_type != 'D' and diff_item.b_path and diff_item.b_path.lower().endswith(".cs"):
                changed_cs_files_count += 1
                cs_file_rel_path_str = Path(diff_item.b_path).as_posix()
                logging.debug('Searching for project file...')
                project_file_rel_path_str = find_project_file(repo, feature_commit, cs_file_rel_path_str)
                logging.debug(f"Found project: {project_file_rel_path_str}")
                if project_file_rel_path_str:
                    project_changes[project_file_rel_path_str].append(cs_file_rel_path_str)
                else:
                    project_not_found_count += 1
                    logging.debug(f"Could not find .csproj for changed file: {cs_file_rel_path_str}")

        if changed_cs_files_count == 0:
            logging.info("No changed C# (.cs) files found in the diff.")
        else:
            log_msg = f"Processed {changed_cs_files_count} changed C# file(s). "
            log_msg += f"Identified {len(project_changes)} project(s) with changes."
            if project_not_found_count > 0:
                log_msg += f" ({project_not_found_count} file(s) could not be mapped to a .csproj)."
            logging.info(log_msg)

        return dict(project_changes)

    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logging.error(f"Git repository error: {e}. Is '{repo_path}' a valid Git repository?")
        sys.exit(1)
    except git.GitCommandError as e:
        logging.error(f"Git command failed: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"Git analysis error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during Git analysis: {e}", exc_info=True)
        sys.exit(1)


# --- get_diff_for_file (git — Phase 3) ---
def get_diff_for_file(repo_path: str, file_path: str,
                      feature_branch: str, base_branch: str = 'main') -> Optional[str]:
    """Fetches the unified diff text for a single file between merge base and feature branch."""
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
        merge_base = repo.merge_base(base_branch, feature_branch)
        if not merge_base:
            logging.warning(f"Could not find merge base between '{base_branch}' and '{feature_branch}'.")
            return None
        diff_text = repo.git.diff(merge_base[0].hexsha, feature_branch, '--', file_path)
        return diff_text if diff_text else None
    except Exception as e:
        logging.warning(f"Could not get diff for {file_path}: {e}")
        return None


# --- get_affected_symbols_from_diff (AI — Phase 4) ---
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


# --- configure_gemini (AI — Phase 4) ---
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


# --- summarize_csharp_file_with_gemini (AI — Phase 4) ---
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
