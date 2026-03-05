"""Legacy functions not yet modularized into dedicated submodules.

This module holds functions that will be extracted into scanners/, analyzers/,
ai/, reports/, and compat/ modules in later phases. It exists to resolve the
package-vs-file naming conflict: with scatter/ as a package, scatter.py cannot
be imported as a module, so all importable functions must live in the package.
"""
import google.generativeai as genai
import textwrap
import logging
import re
import sys
import os
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Dict, Set, Union
from collections import defaultdict

try:
    import git
except ImportError:
    print("Error: GitPython library not found.")
    print("Please install it using: pip install GitPython")
    sys.exit(1)

from scatter.core.models import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_CHUNK_SIZE,
    TYPE_DECLARATION_PATTERN,
)
from scatter.core.parallel import (
    find_files_with_pattern_parallel,
    parse_csproj_files_parallel,
    analyze_cs_files_parallel,
    map_cs_to_projects_parallel,
)


# global variable to hold the configured gemini model
gemini_model = None


# --- helper for type extraction ---
def extract_type_names_from_content(content: str) -> Set[str]:
    """
    extracts declared type names (class, struct, interface, enum) from c# file content.
    """
    found_types = set()
    try:
        matches = TYPE_DECLARATION_PATTERN.finditer(content)
        for match in matches:
            type_name_full = match.group(1).strip()
            type_name_base = re.sub(r'<.*', '', type_name_full).strip()
            type_name_base = type_name_base.split(',')[0].strip()
            if type_name_base:
                found_types.add(type_name_base)
    except Exception as e:
        logging.warning(f"Regex error during type extraction: {e}")
    return found_types


# --- find_project_file  ---
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


# --- find_project_file_on_disk ---
def find_project_file_on_disk(cs_file_abs_path: Path) -> Optional[Path]:
    """
    Finds the .csproj file corresponding to a given C# file by searching upwards
    in the directory tree from the C# file's location.
    Returns the absolute path to the first .csproj found, or None.
    """
    logging.debug(f"Attempting to find project on disk for: {cs_file_abs_path}")
    current_path = cs_file_abs_path.parent
    while True:
        try:
            csproj_files = list(current_path.glob('*.csproj'))
            if csproj_files:
                project_file = csproj_files[0].resolve()
                logging.debug(f"Found project file '{project_file.name}' in '{current_path}' for C# file '{cs_file_abs_path.name}'")
                return project_file
        except Exception as e:
            logging.warning(f"Error searching for .csproj in '{current_path}' for '{cs_file_abs_path.name}': {e}")
            return None

        if current_path == current_path.parent:
            logging.debug(f"Reached filesystem root without finding .csproj for '{cs_file_abs_path.name}'")
            break
        current_path = current_path.parent

    logging.warning(f"No .csproj file found upwards from C# file '{cs_file_abs_path.name}' in its directory tree.")
    return None


# --- analyze_branch_changes ---
def analyze_branch_changes(repo_path: str, feature_branch_name: str, base_branch_name: str = 'main') -> Dict[str, List[str]]:
    """ Analyzes git changes, returns {proj_rel_path_str: [cs_rel_path_str,...]} using POSIX paths"""
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


# --- derive_namespace ---
def derive_namespace(csproj_path: Path) -> Optional[str]:
    """
    Attempts to derive the primary namespace from a .csproj file.
    checks <RootNamespace>, then <AssemblyName> or falls back to filename stem.
    """
    if not csproj_path.is_file():
        logging.error(f"Target project file not found for namespace derivation: {csproj_path}")
        return None
    try:
        namespaces = {'msb': 'http://schemas.microsoft.com/developer/msbuild/2003'}
        tree = ET.parse(csproj_path)
        root = tree.getroot()

        tags_to_check = ['RootNamespace', 'AssemblyName']

        for tag in tags_to_check:
            xpath_query = f'.//msb:{tag}'
            elem = root.find(xpath_query, namespaces)
            if elem is None:
                elem = root.find(f'.//{tag}')

            if elem is not None and elem.text:
                namespace_value = elem.text.strip()
                if namespace_value:
                    logging.debug(f"Derived namespace '{namespace_value}' from <{tag}> in {csproj_path.name}")
                    return namespace_value

        logging.warning(f"<{'> or <'.join(tags_to_check)}> tags not found or empty in {csproj_path.name}. Falling back to filename stem '{csproj_path.stem}' as namespace.")
        return csproj_path.stem

    except ET.ParseError as e:
        logging.error(f"Failed to parse XML for namespace derivation in {csproj_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error deriving namespace from {csproj_path}: {e}")
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


def _process_consumer_summaries_and_append_results(
    target_project_name: str,
    target_project_rel_path_str: str,
    triggering_info: str,
    final_consumers_data: List[Dict[str, Union[Path, str, List[Path]]]],
    all_results_list: List[Dict[str, Union[str, Dict, List[str]]]],
    pipeline_map_dict: Dict[str, str],
    solution_file_cache: List[Path],
    batch_job_map: Dict[str, List[str]],
    search_scope_path_abs: Path,
    summarize_flag: bool,
    gemini_is_configured: bool,
    gemini_model_instance,
    current_gemini_model_name: str) -> None:
    """
    Helper to process summaries for consumer files and append to the main results list.
    Generates a row for EACH unique pipeline found for a consumer.
    """
    if not final_consumers_data:
        logging.info(f"   No consumers found for target '{target_project_name}' triggered by '{triggering_info}'.")
        return

    logging.info(f"   Found {len(final_consumers_data)} consumer(s) for target '{target_project_name}' triggered by '{triggering_info}'.")
    summaries_for_this_target: Dict[str, Dict[str, str]] = defaultdict(dict)

    for consumer_info in final_consumers_data:
        consumer_abs_path = consumer_info['consumer_path']
        consumer_name_stem = consumer_info['consumer_name']
        try:
            consumer_rel_path_str = consumer_abs_path.relative_to(search_scope_path_abs).as_posix()
        except ValueError:
            consumer_rel_path_str = consumer_abs_path.as_posix()

        solutions_for_consumer_paths = find_solutions_for_project(consumer_abs_path, solution_file_cache)
        solutions_for_consumer_names = [p.name for p in solutions_for_consumer_paths]
        logging.debug(f"   Found {len(solutions_for_consumer_names)} solutions for consumer '{consumer_name_stem}': {solutions_for_consumer_names}")

        consumer_summaries_dict = summaries_for_this_target.get(consumer_rel_path_str, {})

        found_pipelines: Dict[str, str] = {}
        if solutions_for_consumer_names:
            for solution_name in solutions_for_consumer_names:
                solution_stem = Path(solution_name).stem
                if solution_stem in pipeline_map_dict:
                    pipeline_name = pipeline_map_dict[solution_stem]
                    if pipeline_name not in found_pipelines:
                        found_pipelines[pipeline_name] = solution_stem
                        logging.debug(f"   Found mapping: Solution '{solution_stem}' -> Pipeline '{pipeline_name}'")

        if found_pipelines:
            for pipeline_name, source_solution in found_pipelines.items():
                batch_job_verification = ""
                if pipeline_name == "cdh-batchprocesses-az-cd":
                    all_known_jobs = batch_job_map.get(pipeline_name, [])
                    if consumer_name_stem in all_known_jobs:
                        batch_job_verification = "Verified"
                    else:
                        batch_job_verification = "Unverified"

                all_results_list.append({
                    'TargetProjectName': target_project_name,
                    'TargetProjectPath': target_project_rel_path_str,
                    'TriggeringType': triggering_info,
                    'ConsumerProjectName': consumer_name_stem,
                    'ConsumerProjectPath': consumer_rel_path_str,
                    'ConsumingSolutions': solutions_for_consumer_names,
                    'PipelineName': pipeline_name,
                    'BatchJobVerification': batch_job_verification,
                    'ConsumerFileSummaries': consumer_summaries_dict
                })
        else:
            logging.debug(f"   No pipeline mapping found for consumer '{consumer_name_stem}' via its solutions.")
            all_results_list.append({
                'TargetProjectName': target_project_name,
                'TargetProjectPath': target_project_rel_path_str,
                'TriggeringType': triggering_info,
                'ConsumerProjectName': consumer_name_stem,
                'ConsumerProjectPath': consumer_rel_path_str,
                'ConsumingSolutions': solutions_for_consumer_names,
                'PipelineName': '',
                'BatchJobVerification': '',
                'ConsumerFileSummaries': consumer_summaries_dict
            })


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


def find_consumers(
    target_csproj_path: Path,
    search_scope_path: Path,
    target_namespace: str,
    class_name: Optional[str],
    method_name: Optional[str],
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50,
    csproj_analysis_chunk_size: int = 25
) -> List[Dict[str, Union[Path, str, List[Path]]]]:
    """
    Finds consuming projects based on ProjectReference, namespace usage,
    and optional class/method usage checks. Tracks the specific files causing matches.
    """
    logging.info(f"-- Analyzing consumers for target: {target_csproj_path.name} (Namespace: {target_namespace}) --")
    if class_name: logging.info(f"     Filtering for type/class: {class_name}")
    if method_name: logging.info(f"     Filtering for method: {method_name}")

    potential_consumers: List[Path] = []
    direct_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    namespace_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    class_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    method_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    cs_file_cache: Dict[Path, List[Path]] = {}

    # --- step 1: find potential consumers ---
    try:
        all_csproj_files = find_files_with_pattern_parallel(
            search_scope_path, '*.csproj',
            max_workers=max_workers,
            chunk_size=chunk_size,
            disable_multiprocessing=disable_multiprocessing
        )
        logging.debug(f'Found {len(all_csproj_files)} total .csproj files in scope.')
        potential_consumers = [
            p.resolve() for p in all_csproj_files if p.resolve() != target_csproj_path
        ]
        logging.debug(f"Found {len(potential_consumers)} potential consumer project(s) to check.")
    except OSError as e:
        logging.error(f"Error scanning search scope '{search_scope_path}': {e}")
        return []

    # --- step 2: identify direct consumers (parallel csproj parsing) ---
    logging.debug("Checking for direct project references to target...")
    csproj_parse_results = parse_csproj_files_parallel(
        potential_consumers,
        target_csproj_path,
        max_workers=max_workers,
        csproj_analysis_chunk_size=csproj_analysis_chunk_size,
        disable_multiprocessing=disable_multiprocessing
    )

    for consumer_csproj_abs in potential_consumers:
        result = csproj_parse_results.get(str(consumer_csproj_abs))
        if result and result['is_consumer']:
            direct_consumers[consumer_csproj_abs] = {
                'consumer_name': result['consumer_name'],
                'relevant_files': []
            }

    logging.debug(f"Found {len(direct_consumers)} direct consumer(s) via ProjectReference.")
    if not direct_consumers:
        logging.info("No projects directly referencing the target were found.")
        return []

    # --- step 3: filter consumers by namespace ---
    if not target_namespace or target_namespace.startswith("NAMESPACE_ERROR_"):
        logging.warning(f"Target namespace is unreliable or missing ('{target_namespace}'). Skipping namespace usage check. All direct consumers will be considered.")
        namespace_consumers = direct_consumers
    else:
        logging.debug(f"Checking {len(direct_consumers)} direct consumers for 'using {target_namespace};' statements...")
        using_pattern = re.compile(rf"(?:^|;|\{{)\s*(?:global\s+)?using\s+{re.escape(target_namespace)}(?:\.[A-Za-z0-9_.]+)?\s*;", re.MULTILINE)

        all_cs_files_for_analysis = []
        consumer_to_files_map = {}

        for consumer_path_abs, consumer_data in direct_consumers.items():
            consumer_dir_abs = consumer_path_abs.parent

            if consumer_dir_abs not in cs_file_cache:
                try:
                    cs_file_cache[consumer_dir_abs] = find_files_with_pattern_parallel(
                        consumer_dir_abs, '*.cs',
                        max_workers=max_workers,
                        chunk_size=chunk_size,
                        disable_multiprocessing=disable_multiprocessing
                    )
                    logging.debug(f"Found {len(cs_file_cache[consumer_dir_abs])} C# files in {consumer_dir_abs}")
                except OSError as e:
                    logging.warning(f"Could not list .cs files in {consumer_dir_abs} for project {consumer_data['consumer_name']}: {e}")
                    cs_file_cache[consumer_dir_abs] = []

            consumer_files = cs_file_cache[consumer_dir_abs]
            consumer_to_files_map[consumer_path_abs] = consumer_files
            all_cs_files_for_analysis.extend(consumer_files)

        if all_cs_files_for_analysis:
            analysis_config = {
                'analysis_type': 'namespace',
                'target_namespace': target_namespace,
                'using_pattern': using_pattern
            }

            analysis_results = analyze_cs_files_parallel(
                all_cs_files_for_analysis,
                analysis_config,
                max_workers=max_workers,
                cs_analysis_chunk_size=cs_analysis_chunk_size,
                disable_multiprocessing=disable_multiprocessing
            )

            for consumer_path_abs, consumer_data in direct_consumers.items():
                namespace_match_files = []

                for cs_file_path in consumer_to_files_map.get(consumer_path_abs, []):
                    file_result = analysis_results.get(cs_file_path)
                    if file_result:
                        if file_result.get('error'):
                            logging.warning(f"Could not read {cs_file_path.name} in {consumer_data['consumer_name']} for namespace check: {file_result['error']}")
                        elif file_result.get('has_match'):
                            namespace_match_files.append(cs_file_path)

                if namespace_match_files:
                    consumer_data['relevant_files'] = namespace_match_files
                    namespace_consumers[consumer_path_abs] = consumer_data
                    logging.debug(f"  Namespace used in {consumer_data['consumer_name']} (Files: {[f.name for f in namespace_match_files]})")

        logging.debug(f"Found {len(namespace_consumers)} consumer(s) using namespace '{target_namespace}'.")

    # --- helper to format results ---
    def format_results(consumer_dict: Dict[Path, Dict[str, Union[str, List[Path]]]]) -> List[Dict[str, Union[Path, str, List[Path]]]]:
        results = []
        for path, data in consumer_dict.items():
            results.append({
                'consumer_path': path,
                'consumer_name': data['consumer_name'],
                'relevant_files': data['relevant_files']
            })
        return results

    if not namespace_consumers:
        logging.info("No consuming projects using the target namespace were found (or check skipped).")
        return format_results(direct_consumers) if not class_name else []
    if not class_name:
        return format_results(namespace_consumers)

    # --- step 4: filter by class/type usage ---
    logging.debug(f"Checking {len(namespace_consumers)} namespace consumers for usage of type '{class_name}'...")

    class_pattern = re.compile(rf"\b{re.escape(class_name)}\b")

    all_relevant_files = []
    consumer_to_relevant_files_map = {}

    for consumer_path_abs, consumer_data in namespace_consumers.items():
        files_to_check = consumer_data['relevant_files']
        consumer_to_relevant_files_map[consumer_path_abs] = files_to_check
        all_relevant_files.extend(files_to_check)
        logging.debug(f"  Checking type '{class_name}' in {len(files_to_check)} relevant files for {consumer_data['consumer_name']}...")

    if all_relevant_files:
        analysis_config = {
            'analysis_type': 'class',
            'class_name': class_name,
            'class_pattern': class_pattern
        }

        analysis_results = analyze_cs_files_parallel(
            all_relevant_files,
            analysis_config,
            max_workers=max_workers,
            cs_analysis_chunk_size=cs_analysis_chunk_size,
            disable_multiprocessing=disable_multiprocessing
        )

        for consumer_path_abs, consumer_data in namespace_consumers.items():
            class_match_files = []

            for cs_file_path in consumer_to_relevant_files_map.get(consumer_path_abs, []):
                file_result = analysis_results.get(cs_file_path)
                if file_result:
                    if file_result.get('error'):
                        logging.warning(f"Could not read {cs_file_path.name} in {consumer_data['consumer_name']} for type check: {file_result['error']}")
                    elif file_result.get('has_match'):
                        class_match_files.append(cs_file_path)

            if class_match_files:
                consumer_data['relevant_files'] = class_match_files
                class_consumers[consumer_path_abs] = consumer_data
                logging.debug(f"    Type '{class_name}' used in {consumer_data['consumer_name']} (Files: {[f.name for f in class_match_files]})")

    logging.debug(f"Found {len(class_consumers)} consumer(s) potentially using type '{class_name}'.")
    if not class_consumers:
        logging.info(f"No consuming projects potentially using type '{class_name}' were found.")
        return []
    if not method_name:
        return format_results(class_consumers)

    # --- step 5: filter by method (parallel) ---
    logging.debug(f"Checking {len(class_consumers)} class consumers for potential usage of method '{method_name}'...")

    method_pattern = re.compile(rf"\.\s*{re.escape(method_name)}\s*\(")

    all_method_files = []
    file_to_consumer_map: Dict[Path, Path] = {}
    for consumer_path_abs, consumer_data in class_consumers.items():
        for cs_file_abs in consumer_data['relevant_files']:
            all_method_files.append(cs_file_abs)
            file_to_consumer_map[cs_file_abs] = consumer_path_abs

    logging.debug(f"  Scanning {len(all_method_files)} files across {len(class_consumers)} consumers for method '{method_name}'...")

    method_analysis_config = {
        'analysis_type': 'method',
        'method_pattern': method_pattern
    }

    method_results = analyze_cs_files_parallel(
        all_method_files,
        method_analysis_config,
        max_workers=max_workers,
        cs_analysis_chunk_size=cs_analysis_chunk_size,
        disable_multiprocessing=disable_multiprocessing
    )

    for cs_file_abs, result in method_results.items():
        if result.get('error'):
            consumer_path_abs = file_to_consumer_map[cs_file_abs]
            consumer_name = class_consumers[consumer_path_abs]['consumer_name']
            logging.warning(f"Could not read {cs_file_abs.name} in {consumer_name} for method check: {result['error']}")
            continue
        if result['has_match']:
            consumer_path_abs = file_to_consumer_map[cs_file_abs]
            consumer_data = class_consumers[consumer_path_abs]
            if consumer_path_abs not in method_consumers:
                method_consumers[consumer_path_abs] = {
                    'consumer_name': consumer_data['consumer_name'],
                    'relevant_files': []
                }
            method_consumers[consumer_path_abs]['relevant_files'].append(cs_file_abs)

    for consumer_path_abs, consumer_data in method_consumers.items():
        logging.debug(f"    Method '{method_name}' used in {consumer_data['consumer_name']} (Files: {[f.name for f in consumer_data['relevant_files']]})")

    logging.debug(f"Found {len(method_consumers)} consumer(s) potentially calling method '{method_name}'.")
    if not method_consumers:
        logging.info(f"No consuming projects potentially calling method '{method_name}' were found.")
        return []

    return format_results(method_consumers)


# --- find_cs_files_referencing_sproc ---
def find_cs_files_referencing_sproc(
    sproc_name_input: str,
    search_path: Path,
    custom_sproc_regex_pattern: Optional[str] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    disable_multiprocessing: bool = False,
    cs_analysis_chunk_size: int = 50
) -> Dict[Path, Dict[str, Set[Path]]]:
    """
    Scans all .cs files within the search_path for the given stored procedure name
    and identifies the containing class.
    """
    projects_classes_sproc_refs: Dict[Path, Dict[str, Set[Path]]] = defaultdict(lambda: defaultdict(set))
    base_sproc_name = sproc_name_input.split('.')[-1]
    escaped_base_sproc_name = re.escape(base_sproc_name)

    if custom_sproc_regex_pattern:
        if "{sproc_name_placeholder}" not in custom_sproc_regex_pattern:
            logging.error("Custom sproc regex pattern must contain '{sproc_name_placeholder}'. Using default pattern.")
            sproc_pattern_str = r'["\'](?:[a-zA-Z0-9_]+\.)?' + escaped_base_sproc_name + r'["\']'
        else:
            sproc_pattern_str = custom_sproc_regex_pattern.replace("{sproc_name_placeholder}", escaped_base_sproc_name)
    else:
        sproc_pattern_str = r'["\'](?:[a-zA-Z_][a-zA-Z0-9_]*\.)?' + escaped_base_sproc_name + r'["\']'

    try:
        sproc_pattern = re.compile(sproc_pattern_str, re.IGNORECASE)
        logging.debug(f"Using sproc search pattern: {sproc_pattern.pattern}")
    except re.error as e:
        logging.error(f"Invalid regex pattern for sproc search ('{sproc_pattern_str}'): {e}. Aborting sproc search.")
        return {}

    try:
        cs_files_to_scan = find_files_with_pattern_parallel(
            search_path, '*.cs',
            max_workers=max_workers,
            chunk_size=chunk_size,
            disable_multiprocessing=disable_multiprocessing
        )
    except OSError as e:
        logging.error(f"Error scanning for .cs files in '{search_path}': {e}")
        return {}

    logging.info(f"Scanning {len(cs_files_to_scan)} C# files in '{search_path}' for references to sproc '{sproc_name_input}'.")
    files_with_ref_count = 0
    projects_found_count = 0
    classes_found_count = 0

    if cs_files_to_scan:
        analysis_config = {
            'analysis_type': 'sproc',
            'sproc_name': sproc_name_input,
            'sproc_pattern': sproc_pattern
        }

        analysis_results = analyze_cs_files_parallel(
            cs_files_to_scan,
            analysis_config,
            max_workers=max_workers,
            cs_analysis_chunk_size=cs_analysis_chunk_size,
            disable_multiprocessing=disable_multiprocessing
        )

        matching_files = []
        for cs_file_abs, file_result in analysis_results.items():
            if file_result.get('error'):
                log_level_detail = logging.DEBUG if logging.getLogger().level == logging.DEBUG else logging.WARNING
                logging.log(log_level_detail, f"Error processing file {cs_file_abs.name} for sproc search: {file_result['error']}")
                continue
            if file_result.get('has_match'):
                matching_files.append(cs_file_abs)

        cs_to_csproj_map = {}
        if matching_files:
            cs_to_csproj_map = map_cs_to_projects_parallel(
                matching_files,
                max_workers=max_workers,
                cs_analysis_chunk_size=cs_analysis_chunk_size,
                disable_multiprocessing=disable_multiprocessing
            )

        for cs_file_abs, file_result in analysis_results.items():
            try:
                if file_result.get('error') or not file_result.get('has_match'):
                    continue

                files_with_ref_count += 1
                logging.debug(f"  Potential reference(s) to sproc '{sproc_name_input}' found in: {cs_file_abs.relative_to(search_path) if search_path in cs_file_abs.parents else cs_file_abs.name}")

                csproj_str = cs_to_csproj_map.get(str(cs_file_abs))
                if not csproj_str:
                    logging.warning(f"  Could not map C# file '{cs_file_abs.name}' (with sproc ref) to a project.")
                    continue

                project_file_abs = Path(csproj_str)
                is_new_project = project_file_abs not in projects_classes_sproc_refs

                matches = file_result.get('matches', [])
                if matches:
                    first_match_index = matches[0][1] if isinstance(matches[0], tuple) else 0

                    content = cs_file_abs.read_text(encoding='utf-8', errors='ignore')
                    enclosing_class = find_enclosing_type_name(content, first_match_index)

                    if enclosing_class:
                        is_new_class_for_project = enclosing_class not in projects_classes_sproc_refs[project_file_abs]
                        projects_classes_sproc_refs[project_file_abs][enclosing_class].add(cs_file_abs)

                        if is_new_project:
                            projects_found_count += 1
                        if is_new_class_for_project:
                            classes_found_count += 1

                        logging.debug(f"    Mapped sproc ref in '{cs_file_abs.name}' to Project '{project_file_abs.name}' and Class '{enclosing_class}'")
                    else:
                        logging.warning(f"    Could not determine enclosing class for sproc ref near index {first_match_index} in '{cs_file_abs.name}' (Project: {project_file_abs.name}). Skipping this reference for class-based consumer analysis.")

            except Exception as e:
                log_level_detail = logging.DEBUG if logging.getLogger().level == logging.DEBUG else logging.WARNING
                logging.log(log_level_detail, f"Unexpected error processing results for file {cs_file_abs.name} for sproc search: {e}", exc_info=(log_level_detail == logging.DEBUG))

    if files_with_ref_count == 0:
        logging.info(f"No C# files found directly referencing sproc '{sproc_name_input}' with the pattern.")
    else:
        log_msg = f"Found {files_with_ref_count} C# file(s) with potential sproc references. "
        log_msg += f"Mapped references to {classes_found_count} unique class(es) across {projects_found_count} project(s)."
        logging.info(log_msg)

    final_result = {proj: dict(classes) for proj, classes in projects_classes_sproc_refs.items()}
    return final_result


# --- helper function: find enclosing type name ---
def find_enclosing_type_name(content: str, match_start_index: int) -> Optional[str]:
    """
    Tries to find the name of the immediately enclosing type (class, struct, interface, enum)
    for a given position within the code content by searching backwards using regex.
    """
    enclosing_type_pattern = re.compile(
        r"^\s*(?:(?:public|internal|private|protected)\s+)?(?:(?:static|abstract|sealed|partial)\s+)*"
        r"(class|struct|interface|enum)\s+([A-Za-z_][A-Za-z0-9_<>,\s]*)",
        re.MULTILINE
    )

    last_found_type_name: Optional[str] = None
    last_match_start = -1

    try:
        for match in enclosing_type_pattern.finditer(content, 0, match_start_index):
            if match.start() > last_match_start:
                last_match_start = match.start()
                type_name_full = match.group(2).strip()
                type_name_base = re.sub(r'<.*', '', type_name_full).strip()
                type_name_base = type_name_base.split(',')[0].strip()
                if type_name_base:
                    last_found_type_name = type_name_base
                    logging.debug(f"  Found potential enclosing type '{last_found_type_name}' at index {match.start()} before index {match_start_index}")

    except Exception as e:
        logging.warning(f"Regex error during enclosing type search: {e}")
        return None

    if last_found_type_name:
        logging.debug(f"  Determined closest enclosing type name: {last_found_type_name}")
        return last_found_type_name
    else:
        logging.warning(f"  Could not determine enclosing type name near index {match_start_index}")
        return None


# --- find_solutions_for_project ---
def find_solutions_for_project(csproj_path: Path, solution_cache: List[Path]) -> List[Path]:
    """
    Finds .sln files that reference a given .csproj file by performing a text search.
    """
    found_in_solutions: List[Path] = []
    project_filename = csproj_path.name

    if not solution_cache:
        logging.warning("Solution cache is empty. Cannot search for solutions.")
        return found_in_solutions

    logging.debug(f"Searching {len(solution_cache)} cached solution files for '{project_filename}'...")

    for sln_path in solution_cache:
        try:
            content = sln_path.read_text(encoding='utf-8', errors='ignore')
            if project_filename in content:
                logging.debug(f"  -> Found reference in: {sln_path.name}")
                found_in_solutions.append(sln_path)
        except OSError as e:
            logging.warning(f"Could not read solution file {sln_path.name}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error processing solution file {sln_path.name}: {e}")

    return found_in_solutions


# --- map_batch_jobs_from_config_repo ---
def map_batch_jobs_from_config_repo(app_config_path: Path) -> Dict[str, List[str]]:
    """
    Scans the app-config repo for the specific batch processes directory
    and maps the pipeline name to the actual job (subdirectory) names.
    """
    batch_job_map: Dict[str, List[str]] = {}
    pipeline_name = "cdh-batchprocesses-az-cd"

    if not app_config_path or not app_config_path.is_dir():
        logging.warning("App config path not provided or not a valid directory. Skipping batch job mapping.")
        return batch_job_map

    target_dir = app_config_path / pipeline_name / "production"
    logging.info(f"Searching for batch jobs in: {target_dir}")

    if not target_dir.is_dir():
        logging.warning(f"Batch job directory not found: {target_dir}. Cannot map specific job names.")
        return batch_job_map

    try:
        job_names = sorted([item.name for item in target_dir.iterdir() if item.is_dir()])
        if job_names:
            batch_job_map[pipeline_name] = job_names
            logging.info(f"Found {len(job_names)} specific batch jobs in app-config repo (e.g., {', '.join(job_names[:3])}...).")
        else:
            logging.warning(f"Found batch job directory, but it contains no subdirectories: {target_dir}")
    except OSError as e:
        logging.error(f"Could not read batch job subdirectories from '{target_dir}': {e}")

    return batch_job_map
