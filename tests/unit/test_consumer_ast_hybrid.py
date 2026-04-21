"""Tests for hybrid AST confirmation in the consumer analyzer pipeline.

Validates that the AST layer in analyze_cs_files_batch() correctly filters
false positives (identifiers in comments/strings) while preserving true
positives (identifiers in real code).
"""

from pathlib import Path
from unittest.mock import patch

from scatter.core.parallel import analyze_cs_files_batch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _run_batch(content: str, analysis_config: dict) -> dict:
    """Write content to a temp file and run analyze_cs_files_batch on it."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".cs", mode="w", delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp = Path(f.name)
    try:
        results = analyze_cs_files_batch(([tmp], analysis_config))
        return results[tmp]
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Class stage tests
# ---------------------------------------------------------------------------


class TestClassHybridFiltering:
    """Stage 4 (class) — AST confirmation via use_ast flag."""

    def test_class_in_comment_only_filtered(self):
        """Regex matches PortalDataService, but AST sees it's only in comments."""
        import re

        content = (FIXTURE_DIR / "false_positive_usage.cs").read_text()
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is False

    def test_class_in_comment_only_regex_matches(self):
        """Without AST, regex matches the false positive."""
        import re

        content = (FIXTURE_DIR / "false_positive_usage.cs").read_text()
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": False,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is True

    def test_class_in_both_comment_and_code_kept(self):
        """When class appears in both comment and real code, AST keeps it."""
        import re

        content = "// PortalDataService docs\nvar svc = new PortalDataService();"
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is True

    def test_class_real_code_only(self):
        """Real code usage passes both regex and AST."""
        import re

        content = "var svc = new PortalDataService();\nsvc.Execute();"
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is True


# ---------------------------------------------------------------------------
# Method stage tests
# ---------------------------------------------------------------------------


class TestMethodHybridFiltering:
    """Stage 5 (method) — AST confirmation via use_ast flag."""

    def test_method_name_missing_skips_ast(self):
        """When method_name is absent from config, AST check is skipped even with use_ast=True."""
        import re

        # Method in comment — regex matches, but with no method_name the AST gate is skipped
        content = "// Call svc.Save(data) here\nclass Foo { }"
        config = {
            "analysis_type": "method",
            "method_pattern": re.compile(r"\.\s*Save\s*\("),
            "use_ast": True,
            # method_name intentionally omitted
        }
        result = _run_batch(content, config)
        # Without method_name, the `if method_name` guard in parallel.py is False,
        # so AST confirmation is skipped and regex result stands
        assert result["has_match"] is True

    def test_method_in_string_only_filtered(self):
        """Regex matches .Save( in string, AST filters it."""
        import re

        content = 'var x = "obj.Save(data)";\nclass Bar { }'
        config = {
            "analysis_type": "method",
            "method_pattern": re.compile(r"\.\s*Save\s*\("),
            "method_name": "Save",
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is False

    def test_method_with_whitespace_before_paren(self):
        """`.Save (` with whitespace before paren still passes."""
        import re

        content = "var x = svc.Save (data);"
        config = {
            "analysis_type": "method",
            "method_pattern": re.compile(r"\.\s*Save\s*\("),
            "method_name": "Save",
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is True

    def test_method_real_usage(self):
        """Real method call passes both regex and AST."""
        import re

        content = "svc.Save(record);"
        config = {
            "analysis_type": "method",
            "method_pattern": re.compile(r"\.\s*Save\s*\("),
            "method_name": "Save",
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is True

    def test_method_in_comment_only_filtered(self):
        """Method in comment only — AST filters it."""
        import re

        content = "// Call svc.Save(data) here\nclass Foo { }"
        config = {
            "analysis_type": "method",
            "method_pattern": re.compile(r"\.\s*Save\s*\("),
            "method_name": "Save",
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is False


# ---------------------------------------------------------------------------
# Fallback / error handling
# ---------------------------------------------------------------------------


class TestASTFallback:
    """When AST fails, regex result is preserved (conservative)."""

    def test_ast_error_preserves_regex_match(self):
        """validate_type_usage returns True on error, so match is kept."""
        import re

        content = "// PortalDataService in comment\nvar x = 1;"
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": True,
        }
        with patch(
            "scatter.parsers.ast_validator.validate_type_usage",
            side_effect=Exception("boom"),
        ):
            # validate_type_usage is wrapped in try/except and returns True on error,
            # but if the import itself fails in the worker, we patch at the module level
            # The actual function has its own try/except that returns True
            result = _run_batch(content, config)
        # When validate_type_usage raises, its internal fallback returns True
        # so the regex match is preserved
        assert result["has_match"] is True


# ---------------------------------------------------------------------------
# Non-ASCII byte offset correctness
# ---------------------------------------------------------------------------


class TestNonASCIIByteOffset:
    """Unicode content before identifier should not break AST validation."""

    def test_unicode_comment_before_real_code(self):
        """Class after unicode comment is correctly identified as code."""
        import re

        # Unicode chars before the real code usage
        content = "// \u00e9\u00e8\u00ea unicode comment\nvar svc = new PortalDataService();"
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is True

    def test_unicode_string_containing_class_name_filtered(self):
        """Class name inside a unicode string is filtered by AST."""
        import re

        content = 'var x = "\u00e9\u00e8 PortalDataService";\nclass Foo { }'
        config = {
            "analysis_type": "class",
            "class_name": "PortalDataService",
            "class_pattern": re.compile(r"\bPortalDataService\b"),
            "use_ast": True,
        }
        result = _run_batch(content, config)
        assert result["has_match"] is False
