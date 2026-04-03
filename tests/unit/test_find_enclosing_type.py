"""Unit tests for find_enclosing_type_name() in type_scanner."""

from scatter.scanners.type_scanner import find_enclosing_type_name


class TestBasicEnclosingTypes:
    def test_class_enclosure(self):
        code = "public class MyService {\n    var x = DoSomething();\n}"
        # match_start_index points inside the class body
        idx = code.index("DoSomething")
        assert find_enclosing_type_name(code, idx) == "MyService"

    def test_struct_enclosure(self):
        code = "public struct Point {\n    public int X;\n}"
        idx = code.index("public int")
        assert find_enclosing_type_name(code, idx) == "Point"

    def test_interface_enclosure(self):
        code = "public interface IRepository {\n    void Save();\n}"
        idx = code.index("void Save")
        assert find_enclosing_type_name(code, idx) == "IRepository"

    def test_enum_enclosure(self):
        code = "public enum Status {\n    Active,\n    Inactive\n}"
        idx = code.index("Active")
        assert find_enclosing_type_name(code, idx) == "Status"

    def test_record_enclosure(self):
        code = "public record PersonDto {\n    public string Name { get; init; }\n}"
        idx = code.index("public string")
        assert find_enclosing_type_name(code, idx) == "PersonDto"


class TestNestedTypes:
    def test_inner_class_returned_for_inner_match(self):
        code = "public class Outer {\n    public class Inner {\n        var x = 1;\n    }\n}\n"
        idx = code.index("var x")
        assert find_enclosing_type_name(code, idx) == "Inner"

    def test_outer_class_returned_for_outer_match(self):
        code = (
            "public class Outer {\n"
            "    int y = 2;\n"
            "    public class Inner {\n"
            "        var x = 1;\n"
            "    }\n"
            "}\n"
        )
        idx = code.index("int y")
        assert find_enclosing_type_name(code, idx) == "Outer"

    def test_deeply_indented_nested_type(self):
        code = (
            "namespace Foo {\n"
            "    public class Level1 {\n"
            "        private class Level2 {\n"
            "            internal struct Level3 {\n"
            "                int val = 42;\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        idx = code.index("int val")
        assert find_enclosing_type_name(code, idx) == "Level3"


class TestGenericTypes:
    def test_generic_class_with_constraint(self):
        code = "public class Repository<T> where T : class {\n    void Save(T item);\n}"
        idx = code.index("void Save")
        assert find_enclosing_type_name(code, idx) == "Repository"


class TestEdgeCases:
    def test_match_before_any_declaration_returns_none(self):
        code = "using System;\nnamespace Foo {\n    // no type yet\n    public class Bar { }\n}"
        idx = code.index("// no type")
        assert find_enclosing_type_name(code, idx) is None

    def test_multiple_types_returns_second_for_later_match(self):
        code = "public class First {\n    int a = 1;\n}\npublic class Second {\n    int b = 2;\n}\n"
        idx = code.index("int b")
        assert find_enclosing_type_name(code, idx) == "Second"

    def test_readonly_struct_enclosure(self):
        code = "public readonly struct Span {\n    int length;\n}"
        idx = code.index("int length")
        assert find_enclosing_type_name(code, idx) == "Span"

    def test_ref_struct_enclosure(self):
        code = "public ref struct SpanRef {\n    int data;\n}"
        idx = code.index("int data")
        assert find_enclosing_type_name(code, idx) == "SpanRef"

    def test_empty_content_returns_none(self):
        assert find_enclosing_type_name("", 0) is None
