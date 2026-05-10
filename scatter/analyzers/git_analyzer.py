"""Git branch analysis — compare branches, find project files, extract diffs."""

import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple, cast

try:
    import git
except ImportError:
    logging.error("GitPython library not found. Install it using: pip install GitPython")
    sys.exit(1)

from scatter.core.models import ChangeKind, ChangedType, TypeKind
from scatter.scanners.type_scanner import extract_type_declarations_with_kind


@dataclass
class ConfigFileChange:
    """A .props/.targets file changed in a git diff."""

    path: str  # POSIX-normalized relative path
    change_type: str  # "A", "M", "D", "R" from git diff


@dataclass
class BranchChanges:
    """Result of analyze_branch_changes."""

    project_changes: Dict[str, List[str]] = field(default_factory=dict)
    changed_config_files: List[ConfigFileChange] = field(default_factory=list)


class BranchSHAs(NamedTuple):
    head_sha: Optional[str]
    base_sha: Optional[str]
    repo_id: str


def resolve_branch_shas(repo_path: str, feature_branch: str, base_branch: str) -> BranchSHAs:
    """Resolve head/base SHAs and repo identity. Best-effort, never raises.

    Shallow-clone safe: the broad except catches partial/corrupt repos where
    repo.heads may raise unexpectedly. This is intentional — prediction logging
    must not break the main flow.
    """
    head_sha = base_sha = None
    repo_id = repo_path
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
        try:
            head_sha = repo.commit(feature_branch).hexsha
            logging.debug(f"Resolved feature ref '{feature_branch}' → {head_sha[:7]}")
        except Exception:
            logging.debug(f"Could not resolve feature ref '{feature_branch}' for prediction log")
        try:
            base_sha = repo.commit(base_branch).hexsha
            logging.debug(f"Resolved base ref '{base_branch}' → {base_sha[:7]}")
        except Exception:
            logging.debug(f"Could not resolve base ref '{base_branch}' for prediction log")
        try:
            repo_id = repo.remotes.origin.url
        except (AttributeError, ValueError):
            repo_id = str(Path(repo_path).resolve())
    except Exception:
        logging.debug("Could not resolve branch SHAs", exc_info=True)
    return BranchSHAs(head_sha=head_sha, base_sha=base_sha, repo_id=repo_id)


def find_project_file(
    repo: git.Repo, commit: git.Commit, cs_file_relative_path_str: str
) -> Optional[str]:
    cs_file_rel_path = Path(cs_file_relative_path_str)
    current_path = cs_file_rel_path.parent

    logging.debug(f"Attempting to find project for: {cs_file_relative_path_str}")
    logging.debug(f"Starting search directory relative to repo root: {current_path.as_posix()}")
    logging.debug(f"Using Git repository root: {repo.working_tree_dir}")

    while True:
        try:
            dir_path_for_tree = current_path.as_posix() if str(current_path) != "." else "."
            logging.debug(f"Searching in directory (relative path): {dir_path_for_tree}")

            current_tree = commit.tree
            logging.debug(f"Commit Tree Root Path: {current_tree.path}")
            try:
                logging.debug(
                    f"Root tree children: {[(item.name, item.type) for item in current_tree]}"
                )
            except Exception as log_e:
                logging.warning(f"Could not log root tree children: {log_e}")

            # walk the tree
            if dir_path_for_tree != ".":
                logging.debug(f"Navigating tree for path parts: {current_path.parts}")
                try:
                    temp_tree = commit.tree
                    for i, part in enumerate(current_path.parts):
                        logging.debug(
                            f"   Navigating part {i + 1}/{len(current_path.parts)}: '{part}'"
                        )
                        try:
                            current_children = [(item.name, item.type) for item in temp_tree]
                            logging.debug(
                                f"       Children of '{temp_tree.path}' ({len(current_children)} items): {current_children}"
                            )
                        except Exception as log_e:
                            logging.warning(
                                f"       Could not log children of '{temp_tree.path}': {log_e}"
                            )

                        found_item = None
                        for item in temp_tree:
                            if item.name.lower() == part.lower():
                                found_item = item
                                logging.debug(
                                    f"        Found matching item via case-insensitive search: '{item.name}', type is '{item.type}'"
                                )
                                break

                        if found_item:
                            if found_item.type == "tree":
                                temp_tree = found_item
                            elif found_item.type == "blob":
                                logging.error(
                                    f"       Path part '{part}' (matched as '{found_item.name}') is a blob (file), not a tree. Cannot descend."
                                )
                                raise KeyError(f"Path component {part} is not a tree")
                            elif found_item.type == "commit":
                                logging.warning(
                                    f"       Path part '{part}' (matched as '{found_item.name}') is a commit object, likely a SUBMODULE. Standard tree traversal will stop here."
                                )
                                raise KeyError(f"Path component {part} is a submodule commit")
                            else:
                                logging.error(
                                    f"       Found '{part}' (matched as '{found_item.name}'), but has unexpected type '{found_item.type}'. Stopping."
                                )
                                raise KeyError(
                                    f"Path component {part} has unknown type {found_item.type}"
                                )
                        else:
                            logging.error(
                                f"       Path part '{part}' NOT FOUND (case-insensitive) in '{temp_tree.path}'."
                            )
                            current_children_final = [(item.name, item.type) for item in temp_tree]
                            logging.debug(
                                f"       Children of '{temp_tree.path}' before failing: {current_children_final}"
                            )
                            raise KeyError(f"Path component {part} not found")

                    current_tree = temp_tree
                    logging.debug(f"   Successfully navigated to tree: {current_tree.path}")

                except KeyError as ke:
                    logging.debug(
                        f"Path '{dir_path_for_tree}' traversal failed in commit {commit.hexsha}: {ke}. Stopping upward search."
                    )
                    break  # stop searching upwards

            logging.debug(f"Checking blobs in final directory tree: {current_tree.path}")
            try:
                dir_blobs = [(item.name, item.path) for item in current_tree.blobs]
                logging.debug(f"   Blobs found: {dir_blobs}")
                for item in current_tree.blobs:
                    if item.name.lower().endswith(".csproj"):
                        project_file_path = current_path / item.name
                        project_file_rel_path_str = project_file_path.as_posix()
                        logging.info(
                            f"Found .csproj '{project_file_rel_path_str}' for '{cs_file_relative_path_str}'"
                        )
                        return project_file_rel_path_str
            except Exception as blob_e:
                logging.warning(f"Could not list blobs in '{current_tree.path}': {blob_e}")

            logging.debug(f"No .csproj file found in directory: {current_path.as_posix()}")

            if current_path == Path("."):
                logging.debug("Reached repo root directory representation. Stopping upward search.")
                break
            parent_path = current_path.parent
            logging.debug(f"Moving up search to parent directory: {parent_path.as_posix()}")
            if parent_path == current_path:
                logging.debug(
                    "Parent path is same as current path (at root). Stopping upward search."
                )
                break
            current_path = parent_path

        except git.exc.GitCommandError as e:
            logging.warning(
                f"Git command error accessing tree for '{dir_path_for_tree}' in {commit.hexsha}: {e}. Stopping upward search."
            )
            break
        except KeyError:
            break
        except Exception as e:
            logging.error(
                f"Unexpected error accessing tree for '{dir_path_for_tree}' in {commit.hexsha}: {e}. Stopping upward search.",
                exc_info=True,
            )
            break

    logging.debug(f"Finished search. No .csproj found upwards from '{cs_file_relative_path_str}'")
    return None


def analyze_branch_changes(
    repo_path: str, feature_branch_name: str, base_branch_name: str = "main"
) -> BranchChanges:
    """Analyzes git changes between branches.

    Returns BranchChanges with project-level .cs changes and any changed
    .props/.targets config files found in the diff.
    """
    project_changes: Dict[str, List[str]] = defaultdict(list)
    changed_config_files: List[ConfigFileChange] = []
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
        logging.info(f"Opened repository: {repo.working_tree_dir}")

        # Accept any git revspec: local branch, remote-tracking ref (origin/...),
        # tag, SHA, or relative ref (HEAD~3). repo.commit() resolves them all.
        # Catch bad-ref errors specifically; let permissions/corruption propagate.
        try:
            base_commit = repo.commit(base_branch_name)
        except (git.BadName, git.GitCommandError, ValueError) as e:
            raise ValueError(
                f"Cannot resolve base ref '{base_branch_name}' in repository "
                f"at {repo_path}. Accepts local branches, remote-tracking refs "
                f"(origin/...), tags, and SHAs."
            ) from e
        logging.info(f"Base ref ({base_branch_name}) commit: {base_commit.hexsha[:7]}")

        try:
            feature_commit = repo.commit(feature_branch_name)
        except (git.BadName, git.GitCommandError, ValueError) as e:
            raise ValueError(
                f"Cannot resolve feature ref '{feature_branch_name}' in repository at {repo_path}."
            ) from e
        logging.info(f"Feature ref ({feature_branch_name}) commit: {feature_commit.hexsha[:7]}")

        merge_bases = repo.merge_base(base_commit, feature_commit)
        if not merge_bases:
            logging.warning(
                f"No common merge base found between '{base_branch_name}' and '{feature_branch_name}'. Comparing '{feature_branch_name}' against its parent(s). This might not be the intended diff."
            )
            if feature_commit.parents:
                merge_base_commit = feature_commit.parents[0]
            else:
                raise ValueError(
                    f"Feature branch '{feature_branch_name}' has no parents and no merge base with '{base_branch_name}'. Cannot diff."
                )
        else:
            merge_base_commit = merge_bases[0]

        logging.info(f"Using commit '{merge_base_commit.hexsha[:7]}' as comparison base.")

        diff_index = merge_base_commit.diff(feature_commit)
        logging.info(f"Found {len(diff_index)} changes between base and {feature_branch_name}.")

        changed_cs_files_count = 0
        project_not_found_count = 0
        logging.info("Analyzing changed files to identify projects...")
        for diff_item in diff_index:
            logging.debug(f"diff_item: {diff_item} - {diff_item.change_type}")

            # Collect .props/.targets before .cs so a find_project_file
            # failure on a later .cs item doesn't skip config files
            relevant_path = diff_item.a_path if diff_item.change_type == "D" else diff_item.b_path
            if relevant_path and (
                relevant_path.lower().endswith(".props")
                or relevant_path.lower().endswith(".targets")
            ):
                normalized = relevant_path.replace("\\", "/")
                changed_config_files.append(
                    ConfigFileChange(path=normalized, change_type=diff_item.change_type or "M")
                )
                continue

            if (
                diff_item.change_type != "D"
                and diff_item.b_path
                and diff_item.b_path.lower().endswith(".cs")
            ):
                changed_cs_files_count += 1
                cs_file_rel_path_str = Path(diff_item.b_path).as_posix()
                logging.debug("Searching for project file...")
                project_file_rel_path_str = find_project_file(
                    repo, feature_commit, cs_file_rel_path_str
                )
                logging.debug(f"Found project: {project_file_rel_path_str}")
                if project_file_rel_path_str:
                    project_changes[project_file_rel_path_str].append(cs_file_rel_path_str)
                else:
                    project_not_found_count += 1
                    logging.debug(
                        f"Could not find .csproj for changed file: {cs_file_rel_path_str}"
                    )

        if changed_cs_files_count == 0:
            logging.info("No changed C# (.cs) files found in the diff.")
        else:
            log_msg = f"Processed {changed_cs_files_count} changed C# file(s). "
            log_msg += f"Identified {len(project_changes)} project(s) with changes."
            if project_not_found_count > 0:
                log_msg += f" ({project_not_found_count} file(s) could not be mapped to a .csproj)."
            logging.info(log_msg)

        if changed_config_files:
            logging.info(
                f"Found {len(changed_config_files)} changed .props/.targets file(s) in diff."
            )

        return BranchChanges(
            project_changes=dict(project_changes),
            changed_config_files=changed_config_files,
        )

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


def get_diff_for_file(
    repo_path: str, file_path: str, feature_branch: str, base_branch: str = "main"
) -> Optional[str]:
    """Fetches the unified diff text for a single file between merge base and feature branch."""
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
        merge_base = repo.merge_base(base_branch, feature_branch)
        if not merge_base:
            logging.warning(
                f"Could not find merge base between '{base_branch}' and '{feature_branch}'."
            )
            return None
        diff_text = repo.git.diff(merge_base[0].hexsha, feature_branch, "--", file_path)
        return diff_text if diff_text else None
    except Exception as e:
        logging.warning(f"Could not get diff for {file_path}: {e}")
        return None


def _read_blob_content(commit: git.Commit, path: str) -> Optional[str]:
    """Read file content from a git tree object (not disk). Returns None if not found."""
    try:
        blob = commit.tree / path
        raw: bytes = blob.data_stream.read()
        return raw.decode("utf-8", errors="ignore")
    except (KeyError, TypeError):
        return None


def _diff_type_sets(
    base_types: List[Tuple[str, str]],
    feature_types: List[Tuple[str, str]],
) -> List[Tuple[str, str, str]]:
    """Compare two type sets and produce (name, kind, change_kind) triples.

    base_types/feature_types: list of (name, kind) tuples.
    Returns: list of (name, kind, change_kind) where change_kind is added/deleted/modified.

    Known limitation: types present in both sets are marked "modified" even if
    only whitespace or comments changed. We compare type *names*, not bodies.
    A future improvement could hash type bodies to distinguish real modifications
    from no-ops.
    """
    base_map = {name: kind for name, kind in base_types}
    feature_map = {name: kind for name, kind in feature_types}

    results: List[Tuple[str, str, str]] = []

    # Types in feature but not base → added
    for name, kind in feature_types:
        if name not in base_map:
            results.append((name, kind, "added"))

    # Types in base but not feature → deleted
    for name, kind in base_types:
        if name not in feature_map:
            results.append((name, kind, "deleted"))

    # Types in both → modified (body may have changed)
    for name, kind in feature_types:
        if name in base_map:
            # Use feature kind (might have changed from class to record, etc.)
            results.append((name, kind, "modified"))

    return results


def extract_pr_changed_types(
    repo_path: str,
    feature_branch: str,
    base_branch: str = "main",
) -> List[ChangedType]:
    """Extract ChangedType list from git diff between branches.

    Reads file content from git tree objects (not disk). Per changed .cs file:
      D: read base tree → all types "deleted"
      A: read feature tree → all types "added"
      M: read both, diff type sets → "added"/"deleted"/"modified"
      R: read both (using a_path/b_path), diff type sets, use b_path for project
    """
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        raise ValueError(f"Not a valid Git repository: {repo_path}") from e

    # Accept any git revspec: local branch, remote-tracking ref, tag, SHA.
    # Catch bad-ref errors specifically; let permissions/corruption propagate.
    try:
        base_commit = repo.commit(base_branch)
    except (git.BadName, git.GitCommandError, ValueError) as e:
        raise ValueError(
            f"Cannot resolve base ref '{base_branch}' in repository "
            f"at {repo_path}. Accepts local branches, remote-tracking refs "
            f"(origin/...), tags, and SHAs."
        ) from e

    try:
        feature_commit = repo.commit(feature_branch)
    except (git.BadName, git.GitCommandError, ValueError) as e:
        raise ValueError(
            f"Cannot resolve feature ref '{feature_branch}' in repository at {repo_path}."
        ) from e

    # Find merge base
    merge_bases = repo.merge_base(base_commit, feature_commit)
    if not merge_bases:
        raise ValueError(
            f"No common ancestor between '{feature_branch}' and '{base_branch}'. "
            f"Are they in the same repository?"
        )
    merge_base_commit = merge_bases[0]

    diff_index = merge_base_commit.diff(feature_commit)
    changed_types: List[ChangedType] = []

    for diff_item in diff_index:
        # Determine which paths to work with
        a_path = diff_item.a_path  # base side
        b_path = diff_item.b_path  # feature side
        change_type = diff_item.change_type

        # Only process .cs files
        relevant_path = b_path or a_path
        if not relevant_path or not relevant_path.lower().endswith(".cs"):
            continue

        # At this point, at least one path is non-None (guarded by relevant_path check).
        # For D: a_path is set. For A/M/R: b_path is set.
        assert a_path is not None or b_path is not None

        # Determine the path to use for project lookup
        # For renames, use b_path (destination). For deletes, use a_path.
        project_lookup_path: str = (b_path if change_type != "D" else a_path) or relevant_path
        project_lookup_commit = feature_commit if change_type != "D" else merge_base_commit

        # Find owning project
        owning_project_path = find_project_file(repo, project_lookup_commit, project_lookup_path)
        if not owning_project_path:
            logging.debug(f"No .csproj found for {relevant_path}, skipping")
            continue

        owning_project = Path(owning_project_path).stem

        if change_type == "D" and a_path:
            # Deleted file — all types are deleted
            content = _read_blob_content(merge_base_commit, a_path)
            if content:
                for name, kind in extract_type_declarations_with_kind(content):
                    changed_types.append(
                        ChangedType(
                            name=name,
                            kind=cast(TypeKind, kind),
                            change_kind="deleted",
                            owning_project=owning_project,
                            owning_project_path=owning_project_path,
                            file_path=a_path,
                        )
                    )

        elif change_type == "A" and b_path:
            # Added file — all types are added
            content = _read_blob_content(feature_commit, b_path)
            if content:
                for name, kind in extract_type_declarations_with_kind(content):
                    changed_types.append(
                        ChangedType(
                            name=name,
                            kind=cast(TypeKind, kind),
                            change_kind="added",
                            owning_project=owning_project,
                            owning_project_path=owning_project_path,
                            file_path=b_path,
                        )
                    )

        elif change_type in ("M", "R") and a_path and b_path:
            # Modified or renamed — diff type sets
            base_content = _read_blob_content(merge_base_commit, a_path)
            feat_content = _read_blob_content(feature_commit, b_path)

            base_types = extract_type_declarations_with_kind(base_content) if base_content else []
            feat_types = extract_type_declarations_with_kind(feat_content) if feat_content else []

            for name, kind, ck in _diff_type_sets(base_types, feat_types):
                changed_types.append(
                    ChangedType(
                        name=name,
                        kind=cast(TypeKind, kind),
                        change_kind=cast(ChangeKind, ck),
                        owning_project=owning_project,
                        owning_project_path=owning_project_path,
                        file_path=b_path,
                    )
                )

    return changed_types
