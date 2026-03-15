"""Dependency graph persistence with smart cache invalidation.

Saves/loads graphs to JSON with metadata for cache validation.
Uses git-based invalidation (preferred) with mtime fallback.

Cache format v2 adds per-file and per-project facts for incremental updates.
"""
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scatter.core.graph import DependencyGraph

CACHE_VERSION = 2


@dataclass
class FileFacts:
    """Per-.cs-file parsed facts for incremental invalidation."""

    path: str  # relative to search_scope
    project: str  # owning project name
    types_declared: List[str] = field(default_factory=list)
    namespaces_used: List[str] = field(default_factory=list)
    sprocs_referenced: List[str] = field(default_factory=list)
    content_hash: str = ""  # sha256 of file contents


@dataclass
class ProjectFacts:
    """Per-project parsed facts for incremental invalidation."""

    namespace: Optional[str] = None
    project_references: List[str] = field(default_factory=list)
    csproj_content_hash: str = ""  # sha256 of .csproj contents


def compute_content_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    try:
        content = file_path.read_bytes()
        return hashlib.sha256(content).hexdigest()
    except OSError:
        return ""


def compute_project_set_hash(csproj_paths: List[str]) -> str:
    """Hash of sorted .csproj relative paths to detect structural changes."""
    joined = "\n".join(sorted(csproj_paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def get_default_cache_path(search_scope: Path) -> Path:
    """Return default cache location: {search_scope}/.scatter/graph_cache.json"""
    return search_scope / ".scatter" / "graph_cache.json"


def cache_exists(search_scope: Path, config_cache_dir: Optional[str] = None) -> bool:
    """Check if a graph cache file exists for the given scope."""
    if config_cache_dir:
        path = Path(config_cache_dir) / "graph_cache.json"
    else:
        path = get_default_cache_path(search_scope)
    return path.is_file()


def save_graph(
    graph: DependencyGraph,
    cache_path: Path,
    search_scope: Path,
    file_facts: Optional[Dict[str, "FileFacts"]] = None,
    project_facts: Optional[Dict[str, "ProjectFacts"]] = None,
) -> None:
    """Serialize graph to JSON file with metadata.

    Uses atomic write (temp file + os.replace) to prevent corrupt cache
    from partial writes or crashes.

    v2: optionally includes file_facts and project_facts for incremental updates.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    git_head = _get_git_head(search_scope)

    envelope: Dict[str, Any] = {
        "version": CACHE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "search_scope": str(search_scope.resolve()),
        "git_head": git_head,
        "node_count": graph.node_count,
        "edge_count": graph.edge_count,
        "graph": graph.to_dict(),
    }

    if file_facts is not None:
        envelope["file_facts"] = {k: asdict(v) for k, v in file_facts.items()}
    if project_facts is not None:
        envelope["project_facts"] = {k: asdict(v) for k, v in project_facts.items()}
    if file_facts is not None and project_facts is not None:
        csproj_paths = list(project_facts.keys())
        envelope["project_set_hash"] = compute_project_set_hash(csproj_paths)

    # Atomic write: write to temp file, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(cache_path.parent), suffix=".tmp", prefix="graph_cache_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2)
        os.replace(tmp_path, str(cache_path))
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logging.info(
        f"Graph cache saved: {graph.node_count} nodes, {graph.edge_count} edges → {cache_path}"
    )


def load_graph(cache_path: Path) -> Optional[DependencyGraph]:
    """Load graph from cache. Returns None if missing or corrupt."""
    envelope = _read_envelope(cache_path)
    if envelope is None:
        return None

    graph_data = envelope.get("graph")
    if not isinstance(graph_data, dict):
        logging.warning(f"Graph cache missing 'graph' key: {cache_path}")
        return None

    try:
        graph = DependencyGraph.from_dict(graph_data)
    except (KeyError, ValueError, TypeError) as e:
        logging.warning(f"Could not deserialize graph from cache {cache_path}: {e}")
        return None

    logging.info(
        f"Graph loaded from cache: {graph.node_count} nodes, {graph.edge_count} edges"
    )
    return graph


def load_and_validate(
    cache_path: Path,
    search_scope: Path,
    invalidation: str = "git",
) -> Optional[
    Tuple[DependencyGraph, Optional[Dict[str, "FileFacts"]],
          Optional[Dict[str, "ProjectFacts"]], Optional[str], Optional[str]]
]:
    """Single-pass load: read cache once, validate, and return graph if valid.

    Returns None if cache is missing, corrupt, stale, or for a different scope.
    Avoids the double-read of is_cache_valid() + load_graph().

    v2 return: (graph, file_facts_or_None, project_facts_or_None, git_head_or_None,
                project_set_hash_or_None).
    file_facts/project_facts are None for v1 caches (caller should do full rebuild
    to populate them).
    """
    envelope = _read_envelope(cache_path)
    if envelope is None:
        return None

    # Validate search_scope matches
    cached_scope = envelope.get("search_scope")
    resolved_scope = str(search_scope.resolve())
    if cached_scope and cached_scope != resolved_scope:
        logging.info(
            f"Cache scope mismatch: cached '{cached_scope}' vs current '{resolved_scope}'. Rebuilding."
        )
        return None

    # Validate freshness — for v2 with facts, we skip git freshness check
    # because the patcher will use git diff to do incremental updates.
    has_facts = "file_facts" in envelope and "project_facts" in envelope
    if not has_facts:
        # v1-style: validate freshness the old way
        if invalidation == "git":
            cached_hash = envelope.get("git_head")
            if cached_hash is None:
                if not _is_cache_valid_mtime(cache_path, search_scope):
                    return None
            elif _git_has_code_changes(cached_hash, search_scope):
                return None
        else:
            if not _is_cache_valid_mtime(cache_path, search_scope):
                return None

    # Deserialize graph
    graph_data = envelope.get("graph")
    if not isinstance(graph_data, dict):
        logging.warning(f"Graph cache missing 'graph' key: {cache_path}")
        return None

    try:
        graph = DependencyGraph.from_dict(graph_data)
    except (KeyError, ValueError, TypeError) as e:
        logging.warning(f"Could not deserialize graph from cache {cache_path}: {e}")
        return None

    # Deserialize facts (v2)
    file_facts = None
    project_facts = None
    if has_facts:
        try:
            file_facts = {
                k: FileFacts(**v) for k, v in envelope["file_facts"].items()
            }
            project_facts = {
                k: ProjectFacts(**v) for k, v in envelope["project_facts"].items()
            }
        except (KeyError, TypeError) as e:
            logging.warning(f"Could not deserialize facts from cache: {e}")
            file_facts = None
            project_facts = None

    git_head = envelope.get("git_head")
    project_set_hash = envelope.get("project_set_hash")

    logging.info(
        f"Graph loaded from cache: {graph.node_count} nodes, {graph.edge_count} edges"
        + (" (with facts)" if file_facts is not None else " (no facts, will rebuild)")
    )
    return graph, file_facts, project_facts, git_head, project_set_hash


def is_cache_valid(
    cache_path: Path,
    search_scope: Path,
    invalidation: str = "git",
) -> bool:
    """Check if the cached graph is still valid.

    Args:
        cache_path: Path to the cache file.
        search_scope: Root directory that was scanned.
        invalidation: Strategy — "git" (default) or "mtime".

    Returns True if cache is valid and can be reused.

    Note: For production use, prefer load_and_validate() which reads the
    file once instead of this + load_graph() which reads it twice.
    """
    envelope = _read_envelope(cache_path)
    if envelope is None:
        return False

    # Validate search_scope matches
    cached_scope = envelope.get("search_scope")
    resolved_scope = str(search_scope.resolve())
    if cached_scope and cached_scope != resolved_scope:
        logging.info(
            f"Cache scope mismatch: cached '{cached_scope}' vs current '{resolved_scope}'. Rebuilding."
        )
        return False

    if invalidation == "git":
        cached_hash = envelope.get("git_head")
        if cached_hash is None:
            # Cache was created in a non-git directory; fall back to mtime
            return _is_cache_valid_mtime(cache_path, search_scope)
        return not _git_has_code_changes(cached_hash, search_scope)

    # mtime strategy
    return _is_cache_valid_mtime(cache_path, search_scope)


def _read_envelope(cache_path: Path) -> Optional[Dict[str, Any]]:
    """Read and validate the cache envelope (version check).

    Shared by is_cache_valid, load_graph, and load_and_validate
    to avoid duplicating parse + version logic.
    """
    if not cache_path.is_file():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            envelope = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logging.warning(f"Could not read graph cache {cache_path}: {e}")
        return None

    if not isinstance(envelope, dict):
        logging.warning(f"Graph cache corrupt (not a dict): {cache_path}")
        return None

    version = envelope.get("version")
    if version not in (1, CACHE_VERSION):
        logging.info(
            f"Graph cache version mismatch (got {version}, want {CACHE_VERSION}). Rebuilding."
        )
        return None

    return envelope


def _get_git_head(search_scope: Path) -> Optional[str]:
    """Get current HEAD commit hash, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(search_scope),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _git_has_code_changes(cached_hash: str, search_scope: Path) -> bool:
    """Check if any .csproj or .cs files changed since cached_hash.

    Returns True if code files changed (cache is stale).
    Returns True if git command fails (conservative fallback).
    """
    try:
        result = subprocess.run(
            [
                "git", "diff", "--name-only",
                cached_hash, "HEAD",
                "--", "*.csproj", "*.cs",
            ],
            cwd=str(search_scope),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logging.debug(
                f"git diff failed (rc={result.returncode}): {result.stderr.strip()}"
            )
            return True  # conservative: rebuild

        changed = result.stdout.strip()
        if changed:
            count = len(changed.splitlines())
            logging.debug(f"Cache stale: {count} code file(s) changed since {cached_hash[:8]}")
            return True

        logging.debug(f"Cache valid: no code files changed since {cached_hash[:8]}")
        return False

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logging.debug(f"git diff failed: {e}")
        return True  # conservative: rebuild


def _is_cache_valid_mtime(cache_path: Path, search_scope: Path) -> bool:
    """Mtime-based fallback: cache valid if no .csproj/.cs newer than cache.

    Note: This performs a recursive glob over the search_scope directory tree.
    On very large monorepos this can be slow. It's used only as a fallback
    for non-git directories or when git_head is unavailable. For git repos,
    the git-based strategy is preferred.
    """
    try:
        cache_mtime = cache_path.stat().st_mtime
    except OSError:
        return False

    for pattern in ("**/*.csproj", "**/*.cs"):
        for path in search_scope.glob(pattern):
            try:
                if path.stat().st_mtime > cache_mtime:
                    logging.debug(f"Cache stale: {path} newer than cache")
                    return False
            except OSError:
                continue

    return True
