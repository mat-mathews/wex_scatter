"""Tests for Hybrid Git Analysis (Initiative 2) — LLM-enhanced diff analysis."""

import pytest
from unittest.mock import MagicMock, patch
from scatter import (
    get_affected_symbols_from_diff,
    get_diff_for_file,
    extract_type_names_from_content,
)


SAMPLE_CS_CONTENT = """
using System;

namespace MyApp
{
    public class UnchangedClassA { }

    public class ModifiedClass
    {
        public void DoWork() { }
    }

    public interface IUnchangedInterface { }
}
"""

SAMPLE_DIFF = """
@@ -8,7 +8,7 @@ namespace MyApp
     public class ModifiedClass
     {
-        public void DoWork() { }
+        public void DoWork(int param) { return; }
     }
"""


class TestGetAffectedSymbolsFromDiff:
    """AC-01, AC-02, AC-03: Tests for LLM-based symbol extraction."""

    def test_ac01_only_modified_symbols_returned(self):
        """AC-01: When Gemini returns only the modified class, only that class is extracted."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '["ModifiedClass"]'
        mock_model.generate_content.return_value = mock_response

        result = get_affected_symbols_from_diff(
            SAMPLE_CS_CONTENT, SAMPLE_DIFF, "MyApp/MyFile.cs", mock_model
        )

        assert result == {"ModifiedClass"}
        # Regex would return all 3 types; LLM correctly returns only 1
        regex_result = extract_type_names_from_content(SAMPLE_CS_CONTENT)
        assert len(regex_result) == 3
        assert "UnchangedClassA" not in result
        assert "IUnchangedInterface" not in result

    def test_ac02_comment_only_change_returns_empty(self):
        """AC-02: When diff is comment/import only, Gemini returns [] and no types are extracted."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "[]"
        mock_model.generate_content.return_value = mock_response

        comment_diff = """
@@ -1,3 +1,3 @@
-// Old comment
+// New comment
 using System;
"""
        result = get_affected_symbols_from_diff(
            SAMPLE_CS_CONTENT, comment_diff, "MyApp/MyFile.cs", mock_model
        )

        assert result == set()

    def test_ac03_gemini_exception_returns_none_for_fallback(self):
        """AC-03: When Gemini raises an exception, returns None to trigger regex fallback."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API rate limit exceeded")

        result = get_affected_symbols_from_diff(
            SAMPLE_CS_CONTENT, SAMPLE_DIFF, "MyApp/MyFile.cs", mock_model
        )

        assert result is None

    def test_gemini_returns_invalid_json_returns_none(self):
        """When Gemini returns unparseable text, returns None for fallback."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "The affected types are ModifiedClass"
        mock_model.generate_content.return_value = mock_response

        result = get_affected_symbols_from_diff(
            SAMPLE_CS_CONTENT, SAMPLE_DIFF, "MyApp/MyFile.cs", mock_model
        )

        assert result is None

    def test_gemini_returns_markdown_fenced_json(self):
        """When Gemini wraps JSON in markdown code fences, it is still parsed correctly."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '```json\n["ModifiedClass"]\n```'
        mock_model.generate_content.return_value = mock_response

        result = get_affected_symbols_from_diff(
            SAMPLE_CS_CONTENT, SAMPLE_DIFF, "MyApp/MyFile.cs", mock_model
        )

        assert result == {"ModifiedClass"}


class TestGetDiffForFile:
    """AC-04: Tests for get_diff_for_file()."""

    def test_same_branch_diff_returns_none(self):
        """Comparing a branch to itself produces no diff (None)."""
        result = get_diff_for_file(".", "scatter.py", "main", "main")
        assert result is None

    def test_returns_none_on_invalid_repo(self):
        """Returns None when repo path is invalid."""
        result = get_diff_for_file("/nonexistent/path", "file.cs", "main", "main")
        assert result is None
