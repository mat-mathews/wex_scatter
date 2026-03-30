"""Tests for scatter.parsers.ast_validator."""

import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from scatter.parsers.ast_validator import (
    identifiers_in_code,
    is_hybrid_available,
    validate_type_declarations,
    validate_type_usage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _byte_positions(content: str, identifier: str):
    """Find all byte-offset positions of identifier in content."""
    encoded = content.encode("utf-8")
    target = identifier.encode("utf-8")
    positions = []
    start = 0
    while True:
        idx = encoded.find(target, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


# ---------------------------------------------------------------------------
# TestIdentifiersInCode
# ---------------------------------------------------------------------------


class TestIdentifiersInCode:
    def test_identifier_only_in_comment_excluded(self):
        content = "// Foo is mentioned here\nclass Bar { }"
        candidates = {"Foo": _byte_positions(content, "Foo")}
        result = identifiers_in_code(content, candidates)
        assert "Foo" not in result

    def test_identifier_in_code_kept(self):
        content = "class Foo { }\nvar x = new Foo();"
        candidates = {"Foo": _byte_positions(content, "Foo")}
        result = identifiers_in_code(content, candidates)
        assert "Foo" in result

    def test_identifier_in_both_code_and_comment_kept(self):
        content = "// Foo is used\nclass Foo { }"
        candidates = {"Foo": _byte_positions(content, "Foo")}
        result = identifiers_in_code(content, candidates)
        assert "Foo" in result

    def test_empty_input(self):
        result = identifiers_in_code("", {})
        assert result == set()

    def test_identifier_in_string_excluded(self):
        content = 'var x = "Foo";\nclass Bar { }'
        candidates = {"Foo": _byte_positions(content, "Foo")}
        result = identifiers_in_code(content, candidates)
        assert "Foo" not in result


# ---------------------------------------------------------------------------
# TestValidateTypeDeclarations
# ---------------------------------------------------------------------------


class TestValidateTypeDeclarations:
    def test_real_class_confirmed(self):
        content = "namespace X {\n    public class MyService { }\n}"
        result = validate_type_declarations(content, {"MyService"})
        assert "MyService" in result

    def test_regex_false_positive_filtered(self):
        # "record" as a variable name, not a record declaration
        content = "var record = new Save();\nrecord.Save();"
        result = validate_type_declarations(content, {"record"})
        assert "record" not in result

    def test_multiple_types_subset_confirmed(self):
        content = "class Foo { }\nstruct Bar { }\n// Baz is not a type"
        result = validate_type_declarations(content, {"Foo", "Bar", "Baz"})
        assert result == {"Foo", "Bar"}

    def test_interface_and_enum(self):
        content = "interface IFoo { }\nenum Status { Active, Inactive }"
        result = validate_type_declarations(content, {"IFoo", "Status"})
        assert result == {"IFoo", "Status"}

    def test_empty_regex_types(self):
        result = validate_type_declarations("class Foo { }", set())
        assert result == set()


# ---------------------------------------------------------------------------
# TestValidateTypeUsage
# ---------------------------------------------------------------------------


class TestValidateTypeUsage:
    def test_usage_in_new_confirmed(self):
        content = "var x = new Foo();"
        assert validate_type_usage(content, "Foo") is True

    def test_mention_in_comment_rejected(self):
        content = "// Creates a Foo instance\nclass Bar { }"
        assert validate_type_usage(content, "Foo") is False

    def test_mention_in_string_rejected(self):
        content = 'var name = "Foo";\nclass Bar { }'
        assert validate_type_usage(content, "Foo") is False

    def test_not_present_at_all(self):
        content = "class Bar { }"
        assert validate_type_usage(content, "Foo") is False


# ---------------------------------------------------------------------------
# TestGracefulFallback
# ---------------------------------------------------------------------------


class TestGracefulFallback:
    def test_import_failure_identifiers_in_code(self):
        with patch("scatter.parsers.ast_validator.parse_csharp", side_effect=Exception("boom")):
            candidates = {"Foo": [0], "Bar": [10]}
            result = identifiers_in_code("anything", candidates)
        # Should return all candidates on failure
        assert result == {"Foo", "Bar"}

    def test_import_failure_validate_type_declarations(self):
        with patch("scatter.parsers.ast_validator.parse_csharp", side_effect=Exception("boom")):
            result = validate_type_declarations("anything", {"Foo", "Bar"})
        assert result == {"Foo", "Bar"}

    def test_import_failure_validate_type_usage(self):
        with patch("scatter.parsers.ast_validator.parse_csharp", side_effect=Exception("boom")):
            result = validate_type_usage("anything", "Foo")
        assert result is True  # conservative fallback

    def test_fallback_logs_debug(self, caplog):
        with caplog.at_level(logging.DEBUG):
            with patch("scatter.parsers.ast_validator.parse_csharp", side_effect=Exception("boom")):
                identifiers_in_code("content", {"Foo": [0]})
        assert any("AST parse failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# TestHybridAvailable
# ---------------------------------------------------------------------------


class TestHybridAvailable:
    def test_available_when_installed(self):
        assert is_hybrid_available() is True

    def test_unavailable_when_missing(self):
        with patch.dict("sys.modules", {"tree_sitter": None, "tree_sitter_c_sharp": None}):
            # Force re-import check
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                assert is_hybrid_available() is False


# ---------------------------------------------------------------------------
# TestThreadSafety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_parse(self):
        content = "namespace X { class Foo { } struct Bar { } }"

        def parse_and_validate(_):
            return validate_type_declarations(content, {"Foo", "Bar"})

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(parse_and_validate, range(4)))

        for r in results:
            assert r == {"Foo", "Bar"}

    def test_concurrent_varied_content(self):
        """Different C# snippets per thread — exercises query cache concurrency."""
        snippets = [
            ("class Alpha { }", {"Alpha"}),
            ("struct Beta { }\nenum Gamma { A }", {"Beta", "Gamma"}),
            ("interface IDelta { }", {"IDelta"}),
            ("class Epsilon { }\nclass Zeta { }", {"Epsilon", "Zeta"}),
        ]

        def validate(idx):
            content, expected = snippets[idx % len(snippets)]
            return validate_type_declarations(content, expected)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(validate, range(8)))

        for i, r in enumerate(results):
            _, expected = snippets[i % len(snippets)]
            assert r == expected


# ---------------------------------------------------------------------------
# TestNonASCIIContent
# ---------------------------------------------------------------------------


class TestNonASCIIContent:
    """Validate correct handling of non-ASCII (multi-byte) content."""

    def test_type_usage_after_unicode(self):
        """Type name after multi-byte chars is correctly found in code."""
        content = "// \u00e9\u00e8\u00ea comment\nvar x = new Foo();"
        assert validate_type_usage(content, "Foo") is True

    def test_type_usage_in_unicode_string_rejected(self):
        """Type name inside a unicode string is correctly rejected."""
        content = 'var x = "\u00fc\u00f6 Foo";\nclass Bar { }'
        assert validate_type_usage(content, "Foo") is False

    def test_identifiers_with_unicode_prefix(self):
        """Identifiers after unicode are correctly byte-offset mapped."""
        content = "// \u00c3\u00a9 unicode\nclass Foo { }\nvar x = new Foo();"
        candidates = {"Foo": _byte_positions(content, "Foo")}
        result = identifiers_in_code(content, candidates)
        assert "Foo" in result
