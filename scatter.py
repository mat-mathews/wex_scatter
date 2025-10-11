import google.generativeai as genai
import textwrap
import argparse
import csv
import logging
import re
import sys
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Set, Union
from collections import defaultdict
import json


# attempt to import gitpython
try:
    import git
except ImportError:
    print("Error: GitPython library not found.")
    print("Please install it using: pip install GitPython")
    sys.exit(1)


# global variable to hold the configured gemini model, will update this later with correct
# use, this can be sort of anti-pattern
gemini_model = None


# --- regex for type extraction ---
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*" # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*" # Optional keywords
    r"(?:class|struct|interface|enum)\s+" # Type keyword
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)" # Capture type name (non-greedy) - handles generics roughly
    r"\s*(?::|{|where|<)", # Look for inheritance colon, opening brace, where clause, or start of generics
    re.MULTILINE
)


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
            # This might occur due to permission issues or other OS errors during glob
            logging.warning(f"Error searching for .csproj in '{current_path}' for '{cs_file_abs_path.name}': {e}")
            return None # Stop on error in a directory for safety

        if current_path == current_path.parent: # Reached filesystem root
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

    # (Summarization logic can be placed here if you want to run it once per consumer)
    # ...

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
        
        # Instead of finding just one pipeline, find all of them.
        # We use a dictionary to store {pipeline_name: source_solution} to avoid duplicates.
        found_pipelines: Dict[str, str] = {}
        if solutions_for_consumer_names:
            for solution_name in solutions_for_consumer_names:
                solution_stem = Path(solution_name).stem
                if solution_stem in pipeline_map_dict:
                    pipeline_name = pipeline_map_dict[solution_stem]
                    if pipeline_name not in found_pipelines:
                        found_pipelines[pipeline_name] = solution_stem
                        logging.debug(f"   Found mapping: Solution '{solution_stem}' -> Pipeline '{pipeline_name}'")

        # If we found any pipelines, create a result row for each one.
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
                    'ConsumingSolutions': solutions_for_consumer_names, # List all solutions for context
                    'PipelineName': pipeline_name,
                    'BatchJobVerification': batch_job_verification,
                    'ConsumerFileSummaries': consumer_summaries_dict
                })
        else:
            # If no pipelines were found for this consumer, still add a row to show the dependency exists.
            logging.debug(f"   No pipeline mapping found for consumer '{consumer_name_stem}' via its solutions.")
            all_results_list.append({
                'TargetProjectName': target_project_name,
                'TargetProjectPath': target_project_rel_path_str,
                'TriggeringType': triggering_info,
                'ConsumerProjectName': consumer_name_stem,
                'ConsumerProjectPath': consumer_rel_path_str,
                'ConsumingSolutions': solutions_for_consumer_names,
                'PipelineName': '', # No pipeline found
                'BatchJobVerification': '',
                'ConsumerFileSummaries': consumer_summaries_dict
            })


def summarize_csharp_file_with_gemini(model_instance, csharp_code: str, file_path_for_log: str) -> Optional[str]:
    """
    Uses the provided Gemini API model instance to summarize a C# file's content.
    """
    if not model_instance: # Check the passed instance
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
        response = model_instance.generate_content(prompt, safety_settings=safety_settings) # Use model_instance
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
    method_name: Optional[str]
) -> List[Dict[str, Union[Path, str, List[Path]]]]: 
    """
    Finds consuming projects based on ProjectReference, namespace usage,
    and optional class/method usage checks. Tracks the specific files causing matches.
    """
    logging.info(f"-- Analyzing consumers for target: {target_csproj_path.name} (Namespace: {target_namespace}) --")
    if class_name: logging.info(f"     Filtering for type/class: {class_name}")
    if method_name: logging.info(f"     Filtering for method: {method_name}")

    potential_consumers: List[Path] = []
    # intermediate storage: consumer_abs_path -> {'consumer_name': str, 'relevant_files': List[Path]}
    direct_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    namespace_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    class_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    method_consumers: Dict[Path, Dict[str, Union[str, List[Path]]]] = {}
    cs_file_cache: Dict[Path, List[Path]] = {}

    # --- step 1: find potential consumers ---
    try:
        all_csproj_files = list(search_scope_path.rglob('*.csproj'))
        logging.debug(f'Found {len(all_csproj_files)} total .csproj files in scope.')
        potential_consumers = [
            p.resolve() for p in all_csproj_files if p.resolve() != target_csproj_path
        ]
        logging.debug(f"Found {len(potential_consumers)} potential consumer project(s) to check.")
    except OSError as e:
        logging.error(f"Error scanning search scope '{search_scope_path}': {e}")
        return []

    # --- step 2: identify direct consumers ---
    logging.debug("Checking for direct project references to target...")
    consumer_namespaces = {'msb': 'http://schemas.microsoft.com/developer/msbuild/2003'}
    for consumer_csproj_abs in potential_consumers:
        logging.debug(f'Checking references in: {consumer_csproj_abs.name}')
        try:
            tree = ET.parse(consumer_csproj_abs)
            root = tree.getroot()
            refs = root.findall('.//msb:ProjectReference', consumer_namespaces)
            if not refs:
                refs = root.findall('.//ProjectReference')

            for ref in refs:
                include_ = ref.get('Include')
                if include_:

                    # normalize paths so we can run on windows and *nix
                    include_ = include_.replace('\\', '/')

                    # ignore stuff that might not be built yet
                    if '$(' in include_ and ')' in include_:
                        logging.debug(f"  Skipping ProjectReference with likely MSBuild property: '{include_}'")
                        continue

                    try:
                        ref_path_abs = (consumer_csproj_abs.parent / include_).resolve(strict=False)

                        if ref_path_abs.exists() and target_csproj_path.exists() and ref_path_abs.samefile(target_csproj_path):
                            direct_consumers[consumer_csproj_abs] = {
                                'consumer_name': consumer_csproj_abs.stem,
                                'relevant_files': []
                            }
                            logging.debug(f"  MATCH: Found direct reference from {consumer_csproj_abs.name}")
                            break
                    except OSError as e:
                        logging.warning(f"Could not resolve or compare reference path '{include_}' in {consumer_csproj_abs.name}: {e}. Skipping reference.")
                    except Exception as e:
                        logging.warning(f"Error processing reference path '{include_}' in {consumer_csproj_abs.name}: {e}. Skipping reference.")

        except (ET.ParseError, OSError) as e:
            logging.warning(f"Skipping reference check for {consumer_csproj_abs.name}: {type(e).__name__} - {e}")
        except Exception as e:
            logging.warning(f"Unexpected error checking references in {consumer_csproj_abs.name}: {e}")

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

        for consumer_path_abs, consumer_data in direct_consumers.items():
            consumer_dir_abs = consumer_path_abs.parent
            namespace_match_files = []

            if consumer_dir_abs not in cs_file_cache:
                try:
                    cs_file_cache[consumer_dir_abs] = list(consumer_dir_abs.rglob('*.cs'))
                    logging.debug(f"Found {len(cs_file_cache[consumer_dir_abs])} C# files in {consumer_dir_abs}")
                except OSError as e:
                    logging.warning(f"Could not list .cs files in {consumer_dir_abs} for project {consumer_data['consumer_name']}: {e}")
                    cs_file_cache[consumer_dir_abs] = []

            for cs_file_abs in cs_file_cache[consumer_dir_abs]:
                try:
                    content = cs_file_abs.read_text(encoding='utf-8', errors='ignore')
                    if using_pattern.search(content):
                        namespace_match_files.append(cs_file_abs)
                except (OSError, Exception) as e:
                    logging.warning(f"Could not read {cs_file_abs.name} in {consumer_data['consumer_name']} for namespace check: {e}")

            if namespace_match_files:
                consumer_data['relevant_files'] = namespace_match_files
                namespace_consumers[consumer_path_abs] = consumer_data
                logging.debug(f"  Namespace used in {consumer_data['consumer_name']} (Files: {[f.name for f in namespace_match_files]})")

        logging.debug(f"Found {len(namespace_consumers)} consumer(s) using namespace '{target_namespace}'.")

    # --- helper to format results ---
    def format_results(consumer_dict: Dict[Path, Dict[str, Union[str, List[Path]]]]) -> List[Dict[str, Union[Path, str, List[Path]]]]:
        """Adds the consumer_path key to each dictionary in the list."""
        results = []
        for path, data in consumer_dict.items():
            results.append({
                'consumer_path': path, # Add the path here
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
    for consumer_path_abs, consumer_data in namespace_consumers.items():
        consumer_dir_abs = consumer_path_abs.parent
        class_match_files = []
        files_to_check = consumer_data['relevant_files']
        logging.debug(f"  Checking type '{class_name}' in {len(files_to_check)} relevant files for {consumer_data['consumer_name']}...")

        for cs_file_abs in files_to_check:
            try:
                content = cs_file_abs.read_text(encoding='utf-8', errors='ignore')
                if class_pattern.search(content):
                    class_match_files.append(cs_file_abs)
            except (OSError, Exception) as e:
                logging.warning(f"Could not read {cs_file_abs.name} in {consumer_data['consumer_name']} for type check: {e}")

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

    # --- step 5: filter by method ---
    logging.debug(f"Checking {len(class_consumers)} class consumers for potential usage of method '{method_name}'...")

    method_pattern = re.compile(rf"\.\s*{re.escape(method_name)}\s*\(")
    for consumer_path_abs, consumer_data in class_consumers.items():
        consumer_dir_abs = consumer_path_abs.parent
        method_match_files = []
        files_to_check = consumer_data['relevant_files']
        logging.debug(f"  Checking method '{method_name}' in {len(files_to_check)} relevant files for {consumer_data['consumer_name']}...")

        for cs_file_abs in files_to_check:
            try:
                content = cs_file_abs.read_text(encoding='utf-8', errors='ignore')
                if method_pattern.search(content):
                    method_match_files.append(cs_file_abs)
            except (OSError, Exception) as e:
                logging.warning(f"Could not read {cs_file_abs.name} in {consumer_data['consumer_name']} for method check: {e}")

        if method_match_files:
            consumer_data['relevant_files'] = method_match_files
            method_consumers[consumer_path_abs] = consumer_data
            logging.debug(f"    Method '{method_name}' used in {consumer_data['consumer_name']} (Files: {[f.name for f in method_match_files]})")

    logging.debug(f"Found {len(method_consumers)} consumer(s) potentially calling method '{method_name}'.")
    if not method_consumers:
        logging.info(f"No consuming projects potentially calling method '{method_name}' were found.")
        return []

    return format_results(method_consumers)


# --- find_cs_files_referencing_sproc ---
def find_cs_files_referencing_sproc(
    sproc_name_input: str,
    search_path: Path,
    custom_sproc_regex_pattern: Optional[str] = None
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
        cs_files_to_scan = list(search_path.rglob('*.cs'))
    except OSError as e:
        logging.error(f"Error scanning for .cs files in '{search_path}': {e}")
        return {}

    logging.info(f"Scanning {len(cs_files_to_scan)} C# files in '{search_path}' for references to sproc '{sproc_name_input}'.")
    files_with_ref_count = 0
    projects_found_count = 0
    classes_found_count = 0

    for cs_file_abs in cs_files_to_scan:
        try:
            content = cs_file_abs.read_text(encoding='utf-8', errors='ignore')
            matches = list(sproc_pattern.finditer(content))

            if matches:
                files_with_ref_count += 1
                logging.debug(f"  Potential reference(s) to sproc '{sproc_name_input}' found in: {cs_file_abs.relative_to(search_path) if search_path in cs_file_abs.parents else cs_file_abs.name}")

                project_file_abs = find_project_file_on_disk(cs_file_abs)
                if not project_file_abs:
                    logging.warning(f"  Could not map C# file '{cs_file_abs.name}' (with sproc ref) to a project.")
                    continue

                is_new_project = project_file_abs not in projects_classes_sproc_refs
                first_match_index = matches[0].start()
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

        except OSError as e:
            logging.warning(f"Could not read file {cs_file_abs.name} during sproc search: {e}")
        except Exception as e:
            log_level_detail = logging.DEBUG if logging.getLogger().level == logging.DEBUG else logging.WARNING
            logging.log(log_level_detail, f"Unexpected error processing file {cs_file_abs.name} for sproc search: {e}", exc_info=(log_level_detail == logging.DEBUG))

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
        r"(class|struct|interface|enum)\s+([A-Za-z_][A-Za-z0-9_<>,\s]*)", # Greedy name
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

    Args:
        csproj_path: The absolute Path to the .csproj file to search for.
        solution_cache: A list of absolute Paths to all .sln files to search within.

    Returns:
        A list of absolute Path objects for each solution file that contains a
        reference to the project.
    """
    found_in_solutions: List[Path] = []
    project_filename = csproj_path.name # e.g., "MyProject.csproj"

    if not solution_cache:
        logging.warning("Solution cache is empty. Cannot search for solutions.")
        return found_in_solutions

    logging.debug(f"Searching {len(solution_cache)} cached solution files for '{project_filename}'...")

    for sln_path in solution_cache:
        try:
            # Read the entire solution file content. They are usually small.
            content = sln_path.read_text(encoding='utf-8', errors='ignore')
            
            # Simple, effective text search, just like the PowerShell script.
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

    Args:
        app_config_path: The absolute Path to the health-benefits-app-config repository.

    Returns:
        A dictionary mapping the generic pipeline name to a list of specific job names.
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
        # Get a sorted list of all subdirectory names
        job_names = sorted([item.name for item in target_dir.iterdir() if item.is_dir()])
        if job_names:
            batch_job_map[pipeline_name] = job_names
            # Log a snippet of the found jobs for confirmation
            logging.info(f"Found {len(job_names)} specific batch jobs in app-config repo (e.g., {', '.join(job_names[:3])}...).")
        else:
            logging.warning(f"Found batch job directory, but it contains no subdirectories: {target_dir}")
    except OSError as e:
        logging.error(f"Could not read batch job subdirectories from '{target_dir}': {e}")

    return batch_job_map


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyzes .NET project consumers based on Git branch changes OR a specific target project. Can optionally summarize consumer files using Gemini API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- mode selection ---
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--target-project",
        help="MODE: Target Project Analysis. Path to the .csproj file or directory of the specific project to analyze."
    )
    mode_group.add_argument(
        "--branch-name",
        help="MODE: Git Branch Analysis. Name of the feature branch to analyze changes on."
    )

    mode_group.add_argument(
        "--stored-procedure",
        metavar="SPROC_NAME",
        help="MODE: Stored Procedure Analysis. Name of the stored procedure to find references to (e.g., 'usp_MyProcedure' or 'dbo.usp_MyProcedure'). Requires --search-scope."
    )

    #--- sproc group ---
    sproc_group = parser.add_argument_group('Stored Procedure Analysis Options (Requires --stored-procedure)')
    sproc_group.add_argument(
        "--sproc-regex-pattern",
        default=None,
        help="(Optional) Custom Python regex pattern to find stored procedure names in C# files. If not provided, a default pattern is used. Example: \"MyCustomPatternFor_(?P<sproc>{sproc_name_placeholder})\" where {sproc_name_placeholder} will be replaced by the escaped sproc name."
    )

    # --- git mode specific arguments ---
    git_group = parser.add_argument_group('Git Branch Analysis Options (Requires --branch-name)')
    git_group.add_argument(
        "-r", "--repo-path", default=".",
        help="Path to the Git repository (default: current directory)."
    )
    git_group.add_argument(
        "-b", "--base-branch", default="main",
        help="Base branch to compare against (default: main)."
    )

    common_group = parser.add_argument_group('Common Options')
    common_group.add_argument(
        "--search-scope",
        help="Root directory to search for consuming projects (defaults to --repo-path if Git mode is used and this is omitted, otherwise REQUIRED)."
    )
    common_group.add_argument(
        "--app-config-path",
        help="(Optional) Path to the 'health-benefits-app-config' repository to resolve specific batch job names."
    )
    common_group.add_argument(
        "--class-name", default=None,
        help="(Optional) Filter: In Git mode, analyze only this type if found in changes. In Target Project mode, check for usage of this specific type."
    )
    common_group.add_argument(
        "--method-name", default=None,
        help="(Optional) Filter: Check for usage of this specific method name. Requires --class-name to be specified."
    )
    common_group.add_argument(
        "--target-namespace", default=None,
        help="(Optional) Explicitly specify the target project's namespace. Overrides automatic derivation (mainly useful in Target Project mode)."
    )
    common_group.add_argument(
        "--pipeline-csv", default=None,
        help="(Optional) Path to CSV mapping 'Project Name' to 'Pipeline Name'."
    )
    common_group.add_argument(
        "--output-file", default=None,
        help="(Optional) Path to write results to a file. The format is determined by --output-format."
    )
    common_group.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable detailed DEBUG level logging."
    )
    summarize_group = parser.add_argument_group('Summarization Options (using Google Gemini)')
    summarize_group.add_argument(
        "--summarize-consumers", action="store_true",
        help="Enable summarization of relevant C# files in consuming projects using the Gemini API."
    )
    summarize_group.add_argument(
        "--google-api-key", default=None,
        help="Google API Key for Gemini. If not provided, uses the GOOGLE_API_KEY environment variable."
    )
    summarize_group.add_argument(
        "--gemini-model", default="gemini-1.5-flash",
        help="The Gemini model to use for summarization."
    )
    common_group.add_argument(
        "--output-format", default="console",
        choices=['console', 'csv', 'json'],
        help="Format for the output. 'console' prints to screen. 'csv' or 'json' requires --output-file."
    )

    args = parser.parse_args()

    # --- setup logging ---
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if args.verbose:
        logging.debug("Debug logging enabled.")

    # --- configure gemini we are going to summarize ---
    gemini_configured_successfully = False
    if args.summarize_consumers:
        logging.info("Summarization enabled. Configuring Gemini...")
        gemini_configured_successfully = configure_gemini(args.google_api_key, args.gemini_model)
        if not gemini_configured_successfully:
            logging.error("Gemini configuration failed. Summarization will be disabled.")
            args.summarize_consumers = False

    is_git_mode = args.branch_name is not None
    is_target_mode = args.target_project is not None
    is_sproc_mode = args.stored_procedure is not None # New mode flag

    repo_path_abs: Optional[Path] = None
    search_scope_abs: Optional[Path] = None
    target_csproj_abs_path: Optional[Path] = None

    try:
        # validate search scope
        if args.search_scope:
            search_scope_abs = Path(args.search_scope).resolve(strict=True)
            logging.info(f"Using specified search scope: {search_scope_abs}")
        elif is_git_mode:
            repo_path_abs = Path(args.repo_path).resolve(strict=True)
            search_scope_abs = repo_path_abs
            logging.info(f"Using repository path as search scope: {search_scope_abs}")
        elif is_sproc_mode: # Sproc mode requires search scope
            parser.error("--search-scope is required when using --stored-procedure mode.")
        elif is_target_mode: # Target mode also requires search scope if not defaulting from repo path (which it doesn't here)
            parser.error("--search-scope is required when using --target-project mode.")
        else: # Should not happen if modes are mutually exclusive and one is required
            parser.error("A mode (--branch-name, --target-project, or --stored-procedure) must be selected.")

        if is_sproc_mode:
            if args.repo_path != "." or args.base_branch != "main":
                if args.repo_path != Path(args.search_scope).resolve(strict=True).as_posix() and args.branch_name is None:
                    logging.warning("Arguments --repo-path and --base-branch are not applicable in --stored-procedure mode and will be ignored.")

        if is_git_mode:
            if not repo_path_abs:
                repo_path_abs = Path(args.repo_path).resolve(strict=True)

        if is_target_mode:
            target_path_input = Path(args.target_project).resolve()
            if target_path_input.is_dir():
                try:
                    target_csproj_abs_path = next(target_path_input.glob('*.csproj'))
                    logging.info(f"Found target project file: {target_csproj_abs_path}")
                except StopIteration:
                    raise FileNotFoundError(f"No .csproj file found in the target directory: {target_path_input}")
            elif target_path_input.is_file() and target_path_input.suffix.lower() == '.csproj':
                target_csproj_abs_path = target_path_input
                logging.info(f"Using target project file: {target_csproj_abs_path}")
            else:
                raise ValueError(f"Invalid target project path: '{args.target_project}'. Must be a .csproj file or a directory containing one.")

        output_file_path = Path(args.output_file).resolve() if args.output_file else None
        pipeline_csv_path = Path(args.pipeline_csv).resolve() if args.pipeline_csv else None

        if args.method_name and not args.class_name:
            logging.warning("Ignoring --method-name because --class-name was not provided.")
            args.method_name = None

        if search_scope_abs is None:
            raise ValueError("Search scope could not be determined.")

    except (FileNotFoundError, ValueError, git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logging.error(f"Input validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during input validation: {e}")
        sys.exit(1)

    # --- Step 1: Cache all solution files ---
    logging.info(f"\n--- Caching solution files ---")
    solution_file_cache: List[Path] = []
    if search_scope_abs:
        logging.info(f"Scanning for .sln files within '{search_scope_abs}'...")
        try:
            solution_file_cache = list(search_scope_abs.rglob('*.sln'))
            print(solution_file_cache)
        except Exception as e:
            logging.error(f"An error occurred while scanning for solution files: {e}")
    else:
        logging.warning("Search scope not defined, cannot cache solution files.")

    # --- Load batch job mapping if app-config-path is provided ---
    batch_job_map: Dict[str, List[str]] = {}
    if args.app_config_path:
        logging.info(f"\n--- Loading batch job data from app-config repo ---")
        try:
            app_config_repo_path = Path(args.app_config_path).resolve(strict=True)
            batch_job_map = map_batch_jobs_from_config_repo(app_config_repo_path)
        except FileNotFoundError:
            logging.error(f"The provided --app-config-path does not exist: {args.app_config_path}")
        except Exception as e:
            logging.error(f"An error occurred processing the --app-config-path: {e}")

    # --- load pipeline data ---
    logging.info(f"\n--- Loading pipeline data ---")
    pipeline_map: Dict[str, str] = {}
    if pipeline_csv_path:
        if not pipeline_csv_path.is_file():
            logging.warning(f"Pipeline CSV file not found: {pipeline_csv_path}. Proceeding without pipeline data.")
        else:
            try:
                with open(pipeline_csv_path, mode='r', newline='', encoding='utf-8-sig') as csvfile:
                    reader = csv.DictReader(csvfile)
                    required_headers = {'Application Name', 'Pipeline Name'}
                    if not required_headers.issubset(reader.fieldnames or set()):
                        missing = required_headers - set(reader.fieldnames or [])
                        logging.error(f"Pipeline CSV missing required columns: {', '.join(missing)}. Proceeding without pipeline data.")
                    else:
                        loaded_count = 0
                        duplicate_count = 0
                        for row in reader:
                            app_name = row.get('Application Name','').strip()
                            pipe_name = row.get('Pipeline Name','').strip()
                            if app_name and pipe_name:
                                if app_name in pipeline_map:
                                    duplicate_count += 1
                                    logging.debug(f"Duplicate application '{app_name}' in pipeline CSV. Overwriting.")
                                pipeline_map[app_name] = pipe_name
                                loaded_count += 1
                        log_msg = f"Loaded {loaded_count} pipeline mappings."
                        if duplicate_count > 0: log_msg += f" ({duplicate_count} duplicate application names found, last entry used)."
                        logging.info(log_msg)

            except Exception as e:
                logging.error(f"Error loading pipeline CSV '{pipeline_csv_path}': {e}. Proceeding without pipeline data.")
    else:
        logging.info("No pipeline CSV provided.")


    # --- main logic ---
    all_results: List[Dict[str, Union[str, Dict, List[str]]]] = []

    # == GIT BRANCH ANALYSIS MODE ==
    if is_git_mode:
        assert repo_path_abs is not None and search_scope_abs is not None
        logging.info(f"\n--- Running Git Branch Analysis Mode ---")
        logging.info(f"Comparing branch '{args.branch_name}' against base '{args.base_branch}' in repo '{repo_path_abs}'")

        logging.info(f"Step 1: Analyzing Git changes...")
        changed_projects_dict = analyze_branch_changes(str(repo_path_abs), args.branch_name, args.base_branch)

        if not changed_projects_dict:
            logging.info("No projects with changed C# files found. Exiting.")
        else:
            logging.info("\nStep 2: Extracting type declarations from changed C# files...")
            types_by_project: Dict[str, Set[str]] = defaultdict(set)
            files_processed_count = 0
            types_extracted_count = 0

            for proj_rel_path_str, cs_rel_paths_str in changed_projects_dict.items():
                logging.debug(f"Processing project for type extraction: {proj_rel_path_str}")
                project_types = set()
                for cs_rel_path_str in cs_rel_paths_str:
                    cs_abs_path = (repo_path_abs / cs_rel_path_str).resolve()
                    files_processed_count += 1
                    logging.debug(f"   Reading file: {cs_abs_path}")
                    if cs_abs_path.is_file():
                        try:
                            content = cs_abs_path.read_text(encoding='utf-8', errors='ignore')
                            extracted = extract_type_names_from_content(content)
                            if extracted:
                                logging.debug(f"     Found types in {cs_rel_path_str}: {', '.join(extracted)}")
                                project_types.update(extracted)
                        except OSError as e:
                            logging.warning(f"Could not read C# file {cs_abs_path}: {e}")
                    else:
                        logging.warning(f"Changed C# file not found on disk (might be deleted/moved): {cs_abs_path}")

                if project_types:
                    types_by_project[proj_rel_path_str] = project_types
                    types_extracted_count += len(project_types)

            logging.info(f"Processed {files_processed_count} changed C# files.")
            if not types_by_project:
                logging.info("No type declarations found in the changed files. Cannot perform type-based consumer analysis.")
            else:
                logging.info(f"Found {types_extracted_count} unique type declaration(s) across {len(types_by_project)} project(s).")

                logging.info(f"\nStep 3: Analyzing consumers...")
                processed_targets_count = 0
                for target_project_rel_path_str, extracted_types in types_by_project.items():
                    processed_targets_count += 1
                    target_csproj_abs_git_mode = (repo_path_abs / target_project_rel_path_str).resolve()
                    target_project_name_git_mode = target_csproj_abs_git_mode.stem

                    logging.info(f"\n--- Analyzing Target Project {processed_targets_count}/{len(types_by_project)}: {target_project_name_git_mode} ({target_project_rel_path_str}) ---")

                    if not target_csproj_abs_git_mode.is_file():
                        logging.warning(f"Target project file '{target_csproj_abs_git_mode}' not found on disk. Skipping.")
                        continue

                    target_namespace_str_git_mode = derive_namespace(target_csproj_abs_git_mode)
                    if not target_namespace_str_git_mode:
                        logging.warning(f"Could not derive namespace for {target_project_name_git_mode}. Consumer analysis may be incomplete.")
                        target_namespace_str_git_mode = f"NAMESPACE_ERROR_{target_project_name_git_mode}"

                    types_to_analyze: Set[str]
                    if args.class_name:
                        if args.class_name in extracted_types:
                            types_to_analyze = {args.class_name}
                            logging.info(f"Filtering analysis to explicitly provided type (found in changes): '{args.class_name}'")
                        else:
                            logging.info(f"Explicitly provided type '{args.class_name}' was NOT found in changed files. Skipping.")
                            types_to_analyze = set()
                    else:
                        types_to_analyze = extracted_types
                        logging.info(f"Analyzing consumers for {len(types_to_analyze)} types detected in changed files: {', '.join(sorted(types_to_analyze))}")

                    if not types_to_analyze:
                        continue

                    for type_name_to_check in sorted(list(types_to_analyze)):
                        logging.info(f"   Checking for consumers of type: '{type_name_to_check}'...")

                        method_filter = args.method_name if args.class_name == type_name_to_check else None
                        if method_filter:
                            logging.info(f"     (Including method filter: '{method_filter}')")

                        final_consumers_data = find_consumers(
                            target_csproj_abs_git_mode,
                            search_scope_abs,
                            target_namespace_str_git_mode,
                            type_name_to_check,
                            method_filter
                        )

                        if final_consumers_data:
                            try:
                                target_proj_rel_for_git_report = target_csproj_abs_git_mode.relative_to(repo_path_abs).as_posix()
                            except ValueError:
                                target_proj_rel_for_git_report = target_csproj_abs_git_mode.as_posix()

                            _process_consumer_summaries_and_append_results(
                                target_project_name=target_project_name_git_mode,
                                target_project_rel_path_str=target_proj_rel_for_git_report,
                                triggering_info=type_name_to_check,
                                final_consumers_data=final_consumers_data,
                                all_results_list=all_results,
                                pipeline_map_dict=pipeline_map,
                                solution_file_cache=solution_file_cache,
                                batch_job_map=batch_job_map,
                                search_scope_path_abs=search_scope_abs,
                                summarize_flag=args.summarize_consumers,
                                gemini_is_configured=gemini_configured_successfully,
                                gemini_model_instance=gemini_model,
                                current_gemini_model_name=args.gemini_model)
                            
                        else:
                            logging.info(f"     No consumers found for type '{type_name_to_check}' in project '{target_project_name_git_mode}'.")

    # == TARGET PROJECT ANALYSIS MODE ==
    elif is_target_mode:
        assert target_csproj_abs_path is not None and search_scope_abs is not None
        logging.info(f"\n--- Running Target Project Analysis Mode ---")
        target_project_name = target_csproj_abs_path.stem
        logging.info(f"Analyzing target project: {target_project_name} ({target_csproj_abs_path})")

        logging.info("Step 1: Determining target namespace...")
        target_namespace_str = args.target_namespace
        if not target_namespace_str:
            target_namespace_str = derive_namespace(target_csproj_abs_path)
        
        if not target_namespace_str:
            logging.error("Could not derive target namespace. Please specify it using --target-namespace.")
            sys.exit(1)
        logging.info(f"Using target namespace: '{target_namespace_str}'")

        logging.info("\nStep 2: Analyzing consumers...")
        final_consumers_data = find_consumers(
            target_csproj_abs_path,
            search_scope_abs,
            target_namespace_str,
            args.class_name,
            args.method_name
        )

        if final_consumers_data:
            logging.info(f"Found {len(final_consumers_data)} consumer(s) matching criteria for target '{target_project_name}'.")
            trigger_level = 'N/A (Project Reference)'
            if args.method_name and args.class_name: trigger_level = f"{args.class_name}.{args.method_name}"
            elif args.class_name: trigger_level = args.class_name

            try:
                target_rel_path_for_report = target_csproj_abs_path.relative_to(search_scope_abs).as_posix()
            except ValueError:
                target_rel_path_for_report = target_csproj_abs_path.as_posix()

            _process_consumer_summaries_and_append_results(
                target_project_name=target_project_name,
                target_project_rel_path_str=target_rel_path_for_report,
                triggering_info=trigger_level,
                final_consumers_data=final_consumers_data,
                all_results_list=all_results,
                pipeline_map_dict=pipeline_map,
                solution_file_cache=solution_file_cache,
                batch_job_map=batch_job_map,
                search_scope_path_abs=search_scope_abs,
                summarize_flag=args.summarize_consumers,
                gemini_is_configured=gemini_configured_successfully,
                gemini_model_instance=gemini_model,
                current_gemini_model_name=args.gemini_model
            )
        else:
            logging.info(f"No consuming projects matching the criteria were found for target '{target_project_name}'.")

    # == STORED PROCEDURE ANALYSIS MODE ==
    elif is_sproc_mode:
        assert search_scope_abs is not None
        logging.info(f"\n--- Running Stored Procedure Analysis Mode ---")
        sproc_name_arg = args.stored_procedure
        logging.info(f"Identifying projects/classes referencing stored procedure: '{sproc_name_arg}' within scope '{search_scope_abs}'")

        project_class_sproc_map = find_cs_files_referencing_sproc(
            sproc_name_arg,
            search_scope_abs,
            args.sproc_regex_pattern
        )

        if not project_class_sproc_map:
            logging.info(f"No projects/classes found referencing stored procedure '{sproc_name_arg}'. Exiting.")
            sys.exit(0)

        total_classes_found = sum(len(classes) for classes in project_class_sproc_map.values())
        logging.info(f"Found {total_classes_found} class(es) across {len(project_class_sproc_map)} project(s) referencing sproc '{sproc_name_arg}'.")

        processed_targets_count = 0

        for target_csproj_abs, classes_dict in project_class_sproc_map.items():
            target_project_name_sproc_mode = target_csproj_abs.stem
            try:
                target_project_rel_path_str = target_csproj_abs.relative_to(search_scope_abs).as_posix()
            except ValueError:
                target_project_rel_path_str = target_csproj_abs.as_posix()

            target_namespace_str_sproc_mode = args.target_namespace or derive_namespace(target_csproj_abs)
            if not target_namespace_str_sproc_mode:
                logging.warning(f"Could not derive namespace for {target_project_name_sproc_mode}. Consumer analysis may be incomplete.")
                target_namespace_str_sproc_mode = f"NAMESPACE_ERROR_{target_project_name_sproc_mode}"

            for class_containing_sproc, cs_files_with_sproc_call in classes_dict.items():
                processed_targets_count += 1

                class_filter_user = args.class_name
                if class_filter_user and class_filter_user != class_containing_sproc:
                    logging.debug(f"Skipping analysis for class '{class_containing_sproc}' because it doesn't match --class-name '{class_filter_user}'.")
                    continue

                method_filter_sproc = args.method_name if class_filter_user and class_filter_user == class_containing_sproc else None

                logging.info(f"\n--- Analyzing Consumers for Class {processed_targets_count}/{total_classes_found}: '{class_containing_sproc}' in Project: {target_project_name_sproc_mode} ---")
                
                report_trigger_info = f"{class_containing_sproc} (via Sproc: {sproc_name_arg})"
                if method_filter_sproc:
                    report_trigger_info = f"{class_containing_sproc}.{method_filter_sproc} (via Sproc: {sproc_name_arg})"

                final_consumers_data = find_consumers(
                    target_csproj_path=target_csproj_abs,
                    search_scope_path=search_scope_abs,
                    target_namespace=target_namespace_str_sproc_mode,
                    class_name=class_containing_sproc,
                    method_name=method_filter_sproc
                )

                _process_consumer_summaries_and_append_results(
                    target_project_name=target_project_name_sproc_mode,
                    target_project_rel_path_str=target_project_rel_path_str,
                    triggering_info=report_trigger_info,
                    final_consumers_data=final_consumers_data,
                    all_results_list=all_results,
                    pipeline_map_dict=pipeline_map,
                    solution_file_cache=solution_file_cache,
                    batch_job_map=batch_job_map,
                    search_scope_path_abs=search_scope_abs,
                    summarize_flag=args.summarize_consumers,
                    gemini_is_configured=gemini_configured_successfully,
                    gemini_model_instance=gemini_model,
                    current_gemini_model_name=args.gemini_model)

    # --- step: output combined results ---
    logging.info(f"\n\n\n################################################################\n\n")
    logging.info(f"\n--- Consolidating and reporting results ---")
    if not all_results:
        logging.info("Overall analysis complete. No consuming relationships matching the criteria were found.")
    else:
        logging.info(f"Overall analysis complete. Found {len(all_results)} consuming relationship(s) matching the criteria.")
        all_results.sort(key=lambda x: (x.get('TargetProjectName',''), x.get('TriggeringType',''), x.get('ConsumerProjectName','')))

    # Prepare detailed results for file outputs
    detailed_results = []
    if all_results:
        for item in all_results:
            # Prepare data for serialization (convert lists/dicts to strings)
            solutions_str = ", ".join(item.get('ConsumingSolutions', []))
            summaries_json = json.dumps(item.get('ConsumerFileSummaries', {}))
            detailed_results.append({
                **item,
                'ConsumingSolutions': solutions_str,
                'ConsumerFileSummaries': summaries_json
            })

    # Handle JSON Output
    if args.output_format == 'json':
        if not args.output_file:
            logging.error("JSON output format requires the --output-file argument.")
            sys.exit(1)

        output_file_path = Path(args.output_file)
        logging.info(f"Writing {len(detailed_results)} detailed results to JSON: {output_file_path}")

        # Create the top-level summary of unique pipelines
        unique_pipelines = sorted(list(set(
            item.get('PipelineName') for item in detailed_results if item.get('PipelineName')
        )))

        # Build the final JSON structure
        json_output = {
            'pipeline_summary': unique_pipelines,
            'all_results': detailed_results
        }

        try:
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file_path, 'w', encoding='utf-8') as jsonfile:
                json.dump(json_output, jsonfile, indent=4)
            logging.info(f"Successfully wrote JSON report to: {output_file_path}")
        except Exception as e:
            logging.error(f"Failed to write output JSON file: {e}")

    # Handle CSV Output
    elif args.output_format == 'csv':
        if not args.output_file:
            logging.error("CSV output format requires the --output-file argument.")
            sys.exit(1)

        output_file_path = Path(args.output_file)
        logging.info(f"Writing {len(detailed_results)} results to CSV: {output_file_path}")
        report_fieldnames = [
            'TargetProjectName', 'TargetProjectPath', 'TriggeringType',
            'ConsumerProjectName', 'ConsumerProjectPath', 'ConsumingSolutions',
            'PipelineName', 'BatchJobVerification', 'ConsumerFileSummaries'
        ]
        try:
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=report_fieldnames)
                writer.writeheader()
                if detailed_results:
                    writer.writerows(detailed_results)
            logging.info(f"Successfully wrote CSV report to: {output_file_path}")
        except Exception as e:
            logging.error(f"Failed to write output CSV file: {e}")

    # Handle Console Output (Default)
    else:
        print("\n--- Combined Consumer Analysis Report ---")
        # ... (console printing logic remains the same) ...
        # (This part is omitted for brevity but should be the same as your existing console output)
        if not all_results:
            print("\n--- No Consuming Relationships Found ---")
        else:
            print("\n--- Consuming Relationships Found ---")
            last_target_type = None
            for item in all_results:
                current_target_type = (item['TargetProjectName'], item['TriggeringType'])
                if current_target_type != last_target_type:
                    print(f"\nTarget: {item['TargetProjectName']} ({item['TargetProjectPath']})")
                    print(f"    Type/Level: {item['TriggeringType']}")
                    last_target_type = current_target_type

                pipeline_info = f" [Pipeline: {item.get('PipelineName', 'N/A')}]" if item.get('PipelineName') else ""
                print(f"         -> Consumed by: {item['ConsumerProjectName']} ({item['ConsumerProjectPath']}){pipeline_info}")
                
                solutions = item.get('ConsumingSolutions', [])
                if solutions:
                    print(f"           Solutions: {', '.join(solutions)}")
                
                verification = item.get('BatchJobVerification')
                if verification:
                    print(f"           Batch Job Status: {verification} in app-config")
                
                summaries = item.get('ConsumerFileSummaries', {})
                if summaries:
                    print("           Summaries:")
                    for file_rel_path, summary in summaries.items():
                        indented_summary = textwrap.indent(summary, ' ' * 14)
                        print(f"             File: {file_rel_path}\n{indented_summary}")

            print(f"\n--- Total Consuming Relationships Found: {len(all_results)} ---")
            
    print("\ndone.\n")
    sys.exit(0)