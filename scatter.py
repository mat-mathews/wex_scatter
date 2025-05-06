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
from typing import List, Optional, Tuple, Dict, Set, Union # Added Union
from collections import defaultdict
import json


# attempt to import gitpython
try:
    import git
except ImportError:
    print("Error: GitPython library not found.")
    print("Please install it using: pip install GitPython")
    sys.exit(1)


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
    Extracts declared type names (class, struct, interface, enum) from C# file content.
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


# --- find_project_file Function ---
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
                                logging.debug(f"       Found matching item via case-insensitive search: '{item.name}', type is '{item.type}'")
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


# --- analyze_branch_changes Function ---
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


# global variable to hold the configured gemini model, will update this later with correct
# use, this can be sort of anti-pattern
gemini_model = None

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


def summarize_csharp_file_with_gemini(csharp_code: str, file_path_for_log: str) -> Optional[str]:
    """
    Uses the configured Gemini API to summarize a C# file's content.

    Args:
        csharp_code: A string containing the C# code from the file.
        file_path_for_log: The path of the file being summarized (for logging).

    Returns:
        A string containing the summary from the Gemini API, or None if an error occurs
        or Gemini is not configured.
    """
    global gemini_model #yuck
    if not gemini_model:
        logging.error("Gemini model not configured. Cannot summarize.")
        return None

    if not csharp_code.strip():
        logging.warning(f"Skipping summarization for empty or whitespace-only file: {file_path_for_log}")
        return "[File is empty or contains only whitespace]"

    try:
        # construct the prompt for the gemini api
        # this should all be a factory for LLMs, just shoving this here for the POC

        prompt = f"""
        Analyze the following C# code from the file '{Path(file_path_for_log).name}':

        ```csharp
        {csharp_code[:20000]} // Limit code length to avoid excessive token usage
        ```

        Please provide a concise summary (2-3 sentences) explaining the primary purpose of the C# code in this file. Focus on what the main classes/structs/interfaces/enums declared within this specific file *do*. Do not list methods or properties unless essential for the summary.
        """

        logging.info(f"Requesting summary for {file_path_for_log} from Gemini API...")
        # dont know if this makes a big difference when dealing with code, but still
        safety_settings = [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
        ]
        response = gemini_model.generate_content(prompt, safety_settings=safety_settings)
        logging.debug(f"Received Gemini response for {file_path_for_log}.")

        if not response.parts:
             logging.warning(f"Gemini response for {file_path_for_log} was empty or blocked. Safety ratings: {response.prompt_feedback}")
             return "[Summary generation blocked or failed]"

        # return the text part of the response
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

    Args:
        # ... (Args documentation) ...

    Returns:
        A list of dictionaries, where each dictionary represents a consumer and
        contains:
        - 'consumer_path': Absolute Path to the consumer .csproj file. <--- NOW INCLUDED
        - 'consumer_name': The consumer project's name stem.
        - 'relevant_files': List of absolute Paths to .cs files within the consumer
                           that satisfied the deepest applied filter level.
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

#
#
#
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
        help="(Optional) Path to write combined results to a CSV file. If omitted, prints to console."
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
        else:
            parser.error("--search-scope is required when using --target-project mode.")

        # validate git mode paths
        if is_git_mode:
            if not repo_path_abs:
                repo_path_abs = Path(args.repo_path).resolve(strict=True)

        # validate target mode path
        if is_target_mode:
            target_path_input = Path(args.target_project).resolve()
            if target_path_input.is_dir():
                try:
                    # Use generator and next() to find the first .csproj
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
                    required_headers = {'Project Name', 'Pipeline Name'}
                    if not required_headers.issubset(reader.fieldnames or set()):
                        missing = required_headers - set(reader.fieldnames or [])
                        logging.error(f"Pipeline CSV missing required columns: {', '.join(missing)}. Proceeding without pipeline data.")
                    else:
                        loaded_count = 0
                        duplicate_count = 0
                        for row in reader:
                            proj_name = row.get('Project Name','').strip()
                            pipe_name = row.get('Pipeline Name','').strip()
                            if proj_name and pipe_name:
                                if proj_name in pipeline_map:
                                    duplicate_count += 1
                                    logging.debug(f"Duplicate project '{proj_name}' in pipeline CSV. Overwriting.")
                                pipeline_map[proj_name] = pipe_name
                                loaded_count += 1
                        log_msg = f"Loaded {loaded_count} pipeline mappings."
                        if duplicate_count > 0: log_msg += f" ({duplicate_count} duplicate project names found, last entry used)."
                        logging.info(log_msg)

            except Exception as e:
                logging.error(f"Error loading pipeline CSV '{pipeline_csv_path}': {e}. Proceeding without pipeline data.")
    else:
        logging.info("No pipeline CSV provided.")


    # --- main logic ---
    all_results: List[Dict[str, Union[str, Dict]]] = [] # stores final report data, may include summary dict

    # == GIT BRANCH ANALYSIS MODE ==
    if is_git_mode:
        assert repo_path_abs is not None
        logging.info(f"\n--- Running Git Branch Analysis Mode ---")
        logging.info(f"Comparing branch '{args.branch_name}' against base '{args.base_branch}' in repo '{repo_path_abs}'")

        # step 1: analyze git branch changes
        logging.info(f"Step 1: Analyzing Git changes...")
        changed_projects_dict = analyze_branch_changes(str(repo_path_abs), args.branch_name, args.base_branch)

        if not changed_projects_dict:
            logging.info("No projects with changed C# files found. Exiting.")
        else:
            # step 2: extract declared type names 
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
                        except Exception as e:
                            logging.error(f"Unexpected error processing file {cs_abs_path}: {e}")
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

                # step 3: analyze consumers for each changed project/type
                logging.info(f"\nStep 3: Analyzing consumers...")
                processed_targets_count = 0 # Counter for logging progress
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

                        # find_consumers returns List[Dict[str, Union[Path, str, List[Path]]]]
                        # example item: {'consumer_path': path(...), 'consumer_name': '...', 'relevant_files': [path(...), ...]}
                        final_consumers_data = find_consumers(
                            target_csproj_abs_git_mode,
                            search_scope_abs, # Assumed not None here
                            target_namespace_str_git_mode,
                            type_name_to_check,
                            method_filter
                        )

                        if final_consumers_data:
                            logging.info(f"     Found {len(final_consumers_data)} consumer(s) for type '{type_name_to_check}'.")
                            summaries_for_this_target_type: Dict[str, Dict[str, str]] = defaultdict(dict) # consumer_rel_path -> {file_rel_path: summary}
                            if args.summarize_consumers and gemini_configured_successfully:
                                logging.info(f"       Attempting to summarize relevant files for {len(final_consumers_data)} consumer(s)...")
                                consumer_index = 0
                                for consumer_info in final_consumers_data:
                                    consumer_index+=1
                                    consumer_abs_path = consumer_info['consumer_path']
                                    consumer_rel_path_str = consumer_abs_path.relative_to(search_scope_abs).as_posix() if search_scope_abs else consumer_abs_path.as_posix()
                                    relevant_files_abs = consumer_info['relevant_files']
                                    logging.debug(f"         Summarizing files for consumer {consumer_index}/{len(final_consumers_data)}: {consumer_info['consumer_name']} ({len(relevant_files_abs)} relevant files)")

                                    file_index = 0
                                    for file_abs_path in relevant_files_abs:
                                        file_index+=1
                                        file_rel_path_str = file_abs_path.relative_to(search_scope_abs).as_posix() if search_scope_abs else file_abs_path.as_posix()
                                        logging.debug(f"           Summarizing file {file_index}/{len(relevant_files_abs)}: {file_rel_path_str}")
                                        try:
                                            content = file_abs_path.read_text(encoding='utf-8', errors='ignore')
                                            summary = summarize_csharp_file_with_gemini(content, str(file_abs_path))
                                            if summary:
                                                summaries_for_this_target_type[consumer_rel_path_str][file_rel_path_str] = summary
                                            else:
                                                 summaries_for_this_target_type[consumer_rel_path_str][file_rel_path_str] = "[Summarization Failed or Disabled]"
                                        except OSError as e:
                                            logging.warning(f"Could not read file {file_abs_path} for summarization: {e}")
                                            summaries_for_this_target_type[consumer_rel_path_str][file_rel_path_str] = "[Error Reading File]"
                                        except Exception as e:
                                             logging.error(f"Unexpected error summarizing {file_abs_path}: {e}")
                                             summaries_for_this_target_type[consumer_rel_path_str][file_rel_path_str] = "[Unexpected Summarization Error]"

                            for consumer_info in final_consumers_data:
                                consumer_abs_path = consumer_info['consumer_path']
                                consumer_name_stem = consumer_info['consumer_name']
                                consumer_rel_path_str = "N/A"
                                try:
                                    consumer_rel_path = consumer_abs_path.relative_to(search_scope_abs) # search_scope_abs validated non-None
                                    consumer_rel_path_str = consumer_rel_path.as_posix()
                                except ValueError:
                                    consumer_rel_path_str = consumer_abs_path.as_posix() # Fallback

                                pipeline_name = pipeline_map.get(consumer_name_stem, '')

                                consumer_summaries = summaries_for_this_target_type.get(consumer_rel_path_str, {})

                                all_results.append({
                                    'TargetProjectName': target_project_name_git_mode,
                                    'TargetProjectPath': target_project_rel_path_str, # keep repo-relative path for target
                                    'TriggeringType': type_name_to_check,
                                    'ConsumerProjectName': consumer_name_stem,
                                    'ConsumerProjectPath': consumer_rel_path_str,
                                    'PipelineName': pipeline_name,
                                    'ConsumerFileSummaries': consumer_summaries # add summaries dict
                                })
                        else:
                            logging.info(f"     No consumers found for type '{type_name_to_check}'.")


    # == TARGET PROJECT ANALYSIS MODE ==
    elif is_target_mode:
        assert target_csproj_abs_path is not None
        assert search_scope_abs is not None

        logging.info(f"\n--- Running Target Project Analysis Mode ---")
        target_project_name = target_csproj_abs_path.stem
        logging.info(f"Analyzing target project: {target_project_name} ({target_csproj_abs_path})")

        logging.info("Step 1: Determining target namespace...")
        target_namespace_str = args.target_namespace
        if target_namespace_str:
            logging.info(f"Using explicitly provided target namespace: '{target_namespace_str}'")
        else:
            logging.info("Attempting to derive target namespace...")
            target_namespace_str = derive_namespace(target_csproj_abs_path)
            if not target_namespace_str:
                logging.error("Could not derive target namespace. Please specify it using --target-namespace.")
                sys.exit(1)

        logging.info("\nStep 2: Analyzing consumers...")
        final_consumers_data = find_consumers(
            target_csproj_abs_path,
            search_scope_abs,
            target_namespace_str,
            args.class_name,
            args.method_name
        )

        if final_consumers_data:
            logging.info(f"Found {len(final_consumers_data)} consumer(s) matching criteria.")

            summaries_for_this_target: Dict[str, Dict[str, str]] = defaultdict(dict) # consumer_rel_path -> {file_rel_path: summary}
            if args.summarize_consumers and gemini_configured_successfully:
                logging.info(f"   Attempting to summarize relevant files for {len(final_consumers_data)} consumer(s)...")
                consumer_index = 0
                for consumer_info in final_consumers_data:
                    consumer_index+=1
                    consumer_abs_path = consumer_info['consumer_path']
                    consumer_rel_path_str = consumer_abs_path.relative_to(search_scope_abs).as_posix() if search_scope_abs else consumer_abs_path.as_posix()
                    relevant_files_abs = consumer_info['relevant_files']
                    logging.debug(f"     Summarizing files for consumer {consumer_index}/{len(final_consumers_data)}: {consumer_info['consumer_name']} ({len(relevant_files_abs)} relevant files)")

                    file_index = 0
                    for file_abs_path in relevant_files_abs:
                        file_index+=1
                        file_rel_path_str = file_abs_path.relative_to(search_scope_abs).as_posix() if search_scope_abs else file_abs_path.as_posix()
                        logging.debug(f"       Summarizing file {file_index}/{len(relevant_files_abs)}: {file_rel_path_str}")
                        try:
                            content = file_abs_path.read_text(encoding='utf-8', errors='ignore')
                            summary = summarize_csharp_file_with_gemini(content, str(file_abs_path))
                            if summary:
                                summaries_for_this_target[consumer_rel_path_str][file_rel_path_str] = summary
                            else:
                                summaries_for_this_target[consumer_rel_path_str][file_rel_path_str] = "[Summarization Failed or Disabled]"
                        except OSError as e:
                            logging.warning(f"Could not read file {file_abs_path} for summarization: {e}")
                            summaries_for_this_target[consumer_rel_path_str][file_rel_path_str] = "[Error Reading File]"
                        except Exception as e:
                             logging.error(f"Unexpected error summarizing {file_abs_path}: {e}")
                             summaries_for_this_target[consumer_rel_path_str][file_rel_path_str] = "[Unexpected Summarization Error]"

            for consumer_info in final_consumers_data:
                consumer_abs_path = consumer_info['consumer_path']
                consumer_name_stem = consumer_info['consumer_name']

                try:
                    target_rel_path = target_csproj_abs_path.relative_to(search_scope_abs)
                    target_rel_path_str = target_rel_path.as_posix()
                except ValueError:
                    target_rel_path_str = target_csproj_abs_path.as_posix()

                try:
                    consumer_rel_path = consumer_abs_path.relative_to(search_scope_abs)
                    consumer_rel_path_str = consumer_rel_path.as_posix()
                except ValueError:
                    consumer_rel_path_str = consumer_abs_path.as_posix()

                pipeline_name = pipeline_map.get(consumer_name_stem, '')
                trigger_level = 'N/A (Project Reference)'
                if args.method_name and args.class_name: trigger_level = f"{args.class_name}.{args.method_name}"
                elif args.class_name: trigger_level = args.class_name

                consumer_summaries = summaries_for_this_target.get(consumer_rel_path_str, {})

                all_results.append({
                    'TargetProjectName': target_project_name,
                    'TargetProjectPath': target_rel_path_str,
                    'TriggeringType': trigger_level, # More descriptive for target mode
                    'ConsumerProjectName': consumer_name_stem,
                    'ConsumerProjectPath': consumer_rel_path_str,
                    'PipelineName': pipeline_name,
                    'ConsumerFileSummaries': consumer_summaries # Add summaries dict
                })
        else:
            logging.info("No consuming projects matching the criteria were found.")


    # --- step: output combined results ---
    logging.info(f"\n--- Consolidating and reporting results ---")
    if not all_results:
        logging.info("Overall analysis complete. No consuming relationships matching the criteria were found.")
    else:
        logging.info(f"Overall analysis complete. Found {len(all_results)} consuming relationship(s) matching the criteria.")
        all_results.sort(key=lambda x: (x['TargetProjectName'], x['TriggeringType'], x['ConsumerProjectName']))

    # --- updated reporting ---
    # define headers for the report
    # adding 'consumerfilesummaries' - note this will be a json string in csv
    report_fieldnames = ['TargetProjectName', 'TargetProjectPath', 'TriggeringType', 'ConsumerProjectName', 'ConsumerProjectPath', 'PipelineName', 'ConsumerFileSummaries']

    # Prepare results for CSV (convert summaries dict to JSON string)
    results_for_csv = []
    if all_results:
        results_for_csv = [
            {**item, 'ConsumerFileSummaries': json.dumps(item.get('ConsumerFileSummaries', {}))}
            for item in all_results
        ]


    # write to csv or print to console
    if output_file_path:
        logging.info(f"Writing {len(results_for_csv)} results to CSV: {output_file_path}")
        try:
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=report_fieldnames)
                writer.writeheader()
                if results_for_csv:
                    writer.writerows(results_for_csv)
            logging.info(f"Successfully wrote results to: {output_file_path}")
        except Exception as e:
            logging.error(f"Failed to write output CSV file: {e}")
    else:
        # print to console
        print("\n--- Combined Consumer Analysis Report ---")

        if is_git_mode:
            assert repo_path_abs is not None
            print(f"Mode: Git Branch Analysis")
            print(f"Branch: '{args.branch_name}' vs '{args.base_branch}' in Repo: {repo_path_abs}")
        elif is_target_mode:
            assert target_csproj_abs_path is not None
            print(f"Mode: Target Project Analysis")
            print(f"Target Project: {target_csproj_abs_path.name} ({target_csproj_abs_path})")
        assert search_scope_abs is not None
        print(f"Search Scope: {search_scope_abs}")

        filter_desc = []
        if args.class_name: filter_desc.append(f"Class Filter: '{args.class_name}'")
        if args.method_name: filter_desc.append(f"Method Filter: '{args.method_name}'")
        if filter_desc: print(f"Filters Applied: {', '.join(filter_desc)}")
        else: print("Filters Applied: None (or only ProjectReference/Namespace level)")

        if pipeline_map: print("Including Pipeline Information (matched by Consumer Project Name)")

        if args.summarize_consumers:
             print(f"Consumer File Summarization: ENABLED (Model: {args.gemini_model})")


        print("\n--- Consuming Relationships Found ---")
        if not all_results:
            print("(None)")
        else:
            last_target_type = None
            for item in all_results:
                current_target_type = (item['TargetProjectName'], item['TriggeringType'])
                if current_target_type != last_target_type:
                    print(f"\nTarget: {item['TargetProjectName']} ({item['TargetProjectPath']})")
                    print(f"   Type/Level: {item['TriggeringType']}")
                    last_target_type = current_target_type

                pipeline_info = f" [Pipeline: {item['PipelineName']}]" if item['PipelineName'] else ""
                print(f"       -> Consumed by: {item['ConsumerProjectName']} ({item['ConsumerProjectPath']}){pipeline_info}")

                # Print Summaries if available
                summaries = item.get('ConsumerFileSummaries', {})
                if summaries:
                    print("          Summaries:")
                    for file_rel_path, summary in summaries.items():
                        # Indent summary for readability
                        indented_summary = textwrap.indent(summary, ' ' * 14)
                        print(f"            File: {file_rel_path}\n{indented_summary}")


        print(f"\n--- Total Consuming Relationships Found: {len(all_results)} ---")

    sys.exit(0)




