"""Configuration system with layered precedence.

Loads settings from (highest to lowest priority):
1. CLI flags (passed as cli_overrides dict)
2. Repo-level .scatter.yaml
3. User-level ~/.scatter/config.yaml
4. Environment variables
5. Hardcoded defaults
"""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class AIConfig:
    default_provider: str = "gemini"
    task_overrides: Dict[str, str] = field(default_factory=dict)
    credentials: Dict[str, Dict[str, str]] = field(default_factory=dict)
    gemini_model: str = "gemini-1.5-flash"


@dataclass
class GraphConfig:
    cache_dir: Optional[str] = None  # override default cache location
    rebuild: bool = False  # force rebuild (ignore cache)
    invalidation: str = "git"  # "git" or "mtime"
    coupling_weights: Optional[Dict[str, float]] = None  # override DEFAULT_COUPLING_WEIGHTS


@dataclass
class ScatterConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    max_depth: int = 2
    disable_multiprocessing: bool = False
    max_workers: Optional[int] = None
    chunk_size: Optional[int] = None
    exclude_patterns: List[str] = field(default_factory=lambda: ["*/bin/*", "*/obj/*"])


def _load_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load a YAML file, returning None if missing or malformed."""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
        return None
    except (yaml.YAMLError, OSError) as e:
        logging.warning(f"Could not parse config file {path}: {e}")
        return None


def _merge_ai_config(target: AIConfig, source: Dict[str, Any]) -> None:
    """Merge an 'ai' section dict into an AIConfig instance."""
    if "default_provider" in source:
        target.default_provider = source["default_provider"]
    if "gemini_model" in source:
        target.gemini_model = source["gemini_model"]
    if "task_overrides" in source and isinstance(source["task_overrides"], dict):
        target.task_overrides.update(source["task_overrides"])
    if "credentials" in source and isinstance(source["credentials"], dict):
        for provider_name, creds in source["credentials"].items():
            if isinstance(creds, dict):
                target.credentials.setdefault(provider_name, {}).update(creds)


def _apply_yaml(config: ScatterConfig, data: Dict[str, Any]) -> None:
    """Apply a parsed YAML dict onto a ScatterConfig."""
    if "ai" in data and isinstance(data["ai"], dict):
        _merge_ai_config(config.ai, data["ai"])

    search = data.get("search", {})
    if isinstance(search, dict):
        if "max_depth" in search:
            config.max_depth = int(search["max_depth"])
        if "exclude_patterns" in search and isinstance(search["exclude_patterns"], list):
            # Replaces defaults entirely — user must re-list patterns they
            # want to keep (e.g. */bin/*, */obj/*).  This matches the
            # convention for list-valued config: explicit > implicit.
            config.exclude_patterns = search["exclude_patterns"]

    graph = data.get("graph", {})
    if isinstance(graph, dict):
        if "cache_dir" in graph:
            config.graph.cache_dir = str(graph["cache_dir"]) if graph["cache_dir"] is not None else None
        if "invalidation" in graph:
            config.graph.invalidation = str(graph["invalidation"])
        if "coupling_weights" in graph and isinstance(graph["coupling_weights"], dict):
            config.graph.coupling_weights = {
                str(k): float(v) for k, v in graph["coupling_weights"].items()
            }

    mp = data.get("multiprocessing", {})
    if isinstance(mp, dict):
        if "disabled" in mp:
            config.disable_multiprocessing = bool(mp["disabled"])
        if "max_workers" in mp and mp["max_workers"] is not None:
            config.max_workers = int(mp["max_workers"])
        if "chunk_size" in mp and mp["chunk_size"] is not None:
            config.chunk_size = int(mp["chunk_size"])


def _apply_env_vars(config: ScatterConfig) -> None:
    """Apply environment variables to config."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        config.ai.credentials.setdefault("gemini", {})["api_key"] = api_key

    default_provider = os.environ.get("SCATTER_DEFAULT_PROVIDER")
    if default_provider:
        config.ai.default_provider = default_provider


def _apply_cli_overrides(config: ScatterConfig, overrides: Dict[str, Any]) -> None:
    """Apply CLI overrides using dot-notation keys."""
    for key, value in overrides.items():
        if key == "ai.credentials.gemini.api_key":
            config.ai.credentials.setdefault("gemini", {})["api_key"] = value
        elif key == "ai.gemini_model":
            config.ai.gemini_model = value
        elif key == "ai.default_provider":
            config.ai.default_provider = value
        elif key == "multiprocessing.disabled":
            config.disable_multiprocessing = bool(value)
        elif key == "multiprocessing.max_workers":
            config.max_workers = int(value) if value is not None else None
        elif key == "multiprocessing.chunk_size":
            config.chunk_size = int(value) if value is not None else None
        elif key == "search.max_depth":
            config.max_depth = int(value)
        elif key == "search.exclude_patterns":
            config.exclude_patterns = list(value)
        elif key == "graph.rebuild":
            config.graph.rebuild = bool(value)
        elif key == "graph.cache_dir":
            config.graph.cache_dir = str(value) if value is not None else None
        elif key == "graph.invalidation":
            config.graph.invalidation = str(value)


def load_config(
    repo_root: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> ScatterConfig:
    """Load configuration with layered precedence.

    Precedence (highest wins):
    1. CLI flags (cli_overrides)
    2. Repo-level .scatter.yaml
    3. User-level ~/.scatter/config.yaml
    4. Environment variables
    5. Hardcoded defaults
    """
    config = ScatterConfig()

    # 5. Defaults already set by dataclass

    # 4. Environment variables
    _apply_env_vars(config)

    # 3. User-level config
    user_config_path = Path.home() / ".scatter" / "config.yaml"
    user_data = _load_yaml_file(user_config_path)
    if user_data:
        _apply_yaml(config, user_data)

    # 2. Repo-level config
    repo_dir = repo_root or Path.cwd()
    repo_config_path = repo_dir / ".scatter.yaml"
    repo_data = _load_yaml_file(repo_config_path)
    if repo_data:
        _apply_yaml(config, repo_data)

    # 1. CLI overrides
    if cli_overrides:
        _apply_cli_overrides(config, cli_overrides)

    return config
