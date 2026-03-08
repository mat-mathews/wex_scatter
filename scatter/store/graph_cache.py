"""Dependency graph persistence with smart cache invalidation.

Saves/loads graphs to JSON with metadata for cache validation.
Uses git-based invalidation (preferred) with mtime fallback.
"""
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from scatter.core.graph import DependencyGraph

CACHE_VERSION = 1


def get_default_cache_path(search_scope: Path) -> Path:
    """Return default cache location: {search_scope}/.scatter/graph_cache.json"""
    return search_scope / ".scatter" / "graph_cache.json"


def save_graph(graph: DependencyGraph, cache_path: Path, search_scope: Path) -> None:
    """Serialize graph to JSON file with metadata."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    git_head = _get_git_head(search_scope)

    envelope: Dict[str, Any] = {
        "version": CACHE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "search_scope": str(search_scope),
        "git_head": git_head,
        "node_count": graph.node_count,
        "edge_count": graph.edge_count,
        "graph": graph.to_dict(),
    }

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)

    logging.info(
        f"Graph cache saved: {graph.node_count} nodes, {graph.edge_count} edges → {cache_path}"
    )


def load_graph(cache_path: Path) -> Optional[DependencyGraph]:
    """Load graph from cache. Returns None if missing or corrupt."""
    if not cache_path.is_file():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            envelope = json.load(f)

        if not isinstance(envelope, dict):
            logging.warning(f"Graph cache corrupt (not a dict): {cache_path}")
            return None

        version = envelope.get("version")
        if version != CACHE_VERSION:
            logging.info(
                f"Graph cache version mismatch (got {version}, want {CACHE_VERSION}). Rebuilding."
            )
            return None

        graph_data = envelope.get("graph")
        if not isinstance(graph_data, dict):
            logging.warning(f"Graph cache missing 'graph' key: {cache_path}")
            return None

        graph = DependencyGraph.from_dict(graph_data)
        logging.info(
            f"Graph loaded from cache: {graph.node_count} nodes, {graph.edge_count} edges"
        )
        return graph

    except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError) as e:
        logging.warning(f"Could not load graph cache {cache_path}: {e}")
        return None


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
    """
    if not cache_path.is_file():
        return False

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            envelope = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    if envelope.get("version") != CACHE_VERSION:
        return False

    if invalidation == "git":
        cached_hash = envelope.get("git_head")
        if cached_hash is None:
            # Cache was created in a non-git directory; fall back to mtime
            return _is_cache_valid_mtime(cache_path, search_scope)
        return not _git_has_code_changes(cached_hash, search_scope)

    # mtime strategy
    return _is_cache_valid_mtime(cache_path, search_scope)


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
    """Mtime-based fallback: cache valid if no .csproj/.cs newer than cache."""
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
