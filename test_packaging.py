"""Tests for packaging and version consistency."""
from pathlib import Path

import pytest


class TestVersionConsistency:
    def test_pyproject_matches_version_py(self):
        """pyproject.toml version must match scatter/__version__.py."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # Python 3.10 fallback

        from scatter.__version__ import __version__

        pyproject_path = Path(__file__).parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)

        assert pyproject["project"]["version"] == __version__, (
            f"Version mismatch: pyproject.toml has {pyproject['project']['version']!r}, "
            f"scatter/__version__.py has {__version__!r}"
        )
