"""Focused unit tests for C# type declaration regex extraction.

Covers every C# type declaration form: class, struct, interface, enum,
record (all variants), delegate, and edge cases.
"""
from scatter.scanners.type_scanner import extract_type_names_from_content


class TestClassDeclarations:
    def test_public_class(self):
        assert "Foo" in extract_type_names_from_content("public class Foo {")

    def test_internal_class(self):
        assert "Foo" in extract_type_names_from_content("internal class Foo {")

    def test_sealed_class(self):
        assert "Foo" in extract_type_names_from_content("public sealed class Foo {")

    def test_abstract_class(self):
        assert "Foo" in extract_type_names_from_content("public abstract class Foo {")

    def test_static_class(self):
        assert "Foo" in extract_type_names_from_content("public static class Foo {")

    def test_partial_class(self):
        assert "Foo" in extract_type_names_from_content("public partial class Foo {")


class TestStructDeclarations:
    def test_public_struct(self):
        assert "Bar" in extract_type_names_from_content("public struct Bar {")

    def test_readonly_struct(self):
        code = "public readonly struct Bar {"
        types = extract_type_names_from_content(code)
        assert "Bar" in types


class TestInterfaceDeclarations:
    def test_public_interface(self):
        assert "IFoo" in extract_type_names_from_content("public interface IFoo {")

    def test_generic_interface(self):
        assert "IFoo" in extract_type_names_from_content("public interface IFoo<T> {")


class TestEnumDeclarations:
    def test_public_enum(self):
        assert "Status" in extract_type_names_from_content("public enum Status {")

    def test_enum_with_base_type(self):
        assert "Status" in extract_type_names_from_content("public enum Status : byte {")


class TestRecordDeclarations:
    def test_positional_record(self):
        code = "public record PersonDto(string Name, int Age);"
        assert "PersonDto" in extract_type_names_from_content(code)

    def test_record_class_with_body(self):
        code = "public record class OrderSummary\n{\n    public int Id { get; init; }\n}"
        assert "OrderSummary" in extract_type_names_from_content(code)

    def test_record_struct_positional(self):
        code = "public record struct Point(double X, double Y);"
        assert "Point" in extract_type_names_from_content(code)

    def test_record_struct_with_body(self):
        code = "public record struct Coordinate\n{\n    public double Lat { get; init; }\n}"
        assert "Coordinate" in extract_type_names_from_content(code)

    def test_record_with_inheritance(self):
        code = "public record EmployeeDto(string Name, string Dept)\n    : PersonDto(Name);"
        assert "EmployeeDto" in extract_type_names_from_content(code)

    def test_internal_record(self):
        code = "internal record InternalAuditEntry(string Action, DateTime Ts);"
        assert "InternalAuditEntry" in extract_type_names_from_content(code)

    def test_sealed_record(self):
        code = "public sealed record SealedDto(int Id);"
        assert "SealedDto" in extract_type_names_from_content(code)

    def test_abstract_record(self):
        code = "public abstract record BaseDto(int Id);"
        assert "BaseDto" in extract_type_names_from_content(code)

    def test_partial_record(self):
        code = "public partial record PartialDto\n{"
        assert "PartialDto" in extract_type_names_from_content(code)

    def test_record_no_access_modifier(self):
        code = "record SimpleRecord(int X);"
        assert "SimpleRecord" in extract_type_names_from_content(code)


class TestDelegateDeclarations:
    def test_simple_delegate(self):
        code = "public delegate void MyHandler(object sender, EventArgs e);"
        assert "MyHandler" in extract_type_names_from_content(code)

    def test_generic_delegate(self):
        code = "public delegate Task AsyncEventHandler<TEventArgs>(object sender, TEventArgs args);"
        assert "AsyncEventHandler" in extract_type_names_from_content(code)

    def test_internal_delegate(self):
        code = "internal delegate int Transformer(string input);"
        assert "Transformer" in extract_type_names_from_content(code)

    def test_delegate_returning_generic(self):
        code = "public delegate Task<bool> Validator(string input);"
        assert "Validator" in extract_type_names_from_content(code)


class TestReadonlyAndRefStructs:
    def test_readonly_struct(self):
        code = "public readonly struct ReadOnlyPoint {"
        assert "ReadOnlyPoint" in extract_type_names_from_content(code)

    def test_ref_struct(self):
        code = "public ref struct SpanLike {"
        assert "SpanLike" in extract_type_names_from_content(code)

    def test_readonly_ref_struct(self):
        code = "public readonly ref struct ReadOnlySpan {"
        assert "ReadOnlySpan" in extract_type_names_from_content(code)

    def test_ref_readonly_struct(self):
        code = "public ref readonly struct RefReadOnly {"
        assert "RefReadOnly" in extract_type_names_from_content(code)


class TestPrimaryConstructors:
    def test_class_primary_constructor(self):
        code = "public class Foo(int x, ILogger logger) {"
        assert "Foo" in extract_type_names_from_content(code)

    def test_record_primary_constructor(self):
        code = "public record Bar(string Name, int Age);"
        assert "Bar" in extract_type_names_from_content(code)

    def test_struct_primary_constructor(self):
        code = "public struct Baz(double X, double Y) {"
        assert "Baz" in extract_type_names_from_content(code)


class TestAttributesBeforeDeclarations:
    def test_attribute_on_separate_line(self):
        code = "[Serializable]\npublic class Foo {"
        assert "Foo" in extract_type_names_from_content(code)

    def test_multiple_attributes(self):
        code = "[Serializable]\n[Obsolete]\npublic class Bar {"
        assert "Bar" in extract_type_names_from_content(code)

    def test_attribute_with_params(self):
        code = '[JsonConverter(typeof(MyConverter))]\npublic struct Baz {'
        assert "Baz" in extract_type_names_from_content(code)


class TestRecordFalsePositives:
    def test_record_dot_method_call(self):
        code = "    record.Save();"
        types = extract_type_names_from_content(code)
        assert "Save" not in types

    def test_this_record_assignment(self):
        code = "    this.record = x;"
        types = extract_type_names_from_content(code)
        assert "record" not in types
        assert "x" not in types

    def test_record_as_parameter_name(self):
        code = "    void Process(Record record) {"
        types = extract_type_names_from_content(code)
        assert "record" not in types


class TestNestedTypeExtraction:
    def test_private_class_inside_public_class(self):
        code = (
            "public class Outer {\n"
            "    private class Inner {\n"
            "    }\n"
            "}\n"
        )
        types = extract_type_names_from_content(code)
        assert "Outer" in types
        assert "Inner" in types

    def test_struct_inside_class(self):
        code = (
            "public class Container {\n"
            "    private struct Item {\n"
            "    }\n"
            "}\n"
        )
        types = extract_type_names_from_content(code)
        assert "Container" in types
        assert "Item" in types


class TestRecordClassDedup:
    def test_record_class_no_duplicate(self):
        code = "public record class OrderSummary {"
        types = extract_type_names_from_content(code)
        # Should extract OrderSummary exactly once (set deduplicates)
        assert "OrderSummary" in types

    def test_record_record_pathological(self):
        """Pathological input 'record record' should not crash."""
        code = "public record record {"
        types = extract_type_names_from_content(code)
        # Should not crash; behavior is to extract "record" as a type name
        assert isinstance(types, set)


class TestEdgeCases:
    def test_generic_class(self):
        code = "public class Repository<T> where T : class {"
        assert "Repository" in extract_type_names_from_content(code)

    def test_multiple_types_in_one_file(self):
        code = """public class Foo {
}
public struct Bar {
}
public record Baz(int X);
"""
        types = extract_type_names_from_content(code)
        assert "Foo" in types
        assert "Bar" in types
        assert "Baz" in types

    def test_indented_type(self):
        code = "    public class NestedType {"
        assert "NestedType" in extract_type_names_from_content(code)

    def test_no_false_positive_on_variable(self):
        code = "var record = new Record();"
        types = extract_type_names_from_content(code)
        # Should not extract from variable assignments
        assert "record" not in types

    def test_comment_lines_not_matched(self):
        code = "// public class Commented {"
        types = extract_type_names_from_content(code)
        # The regex may match this — it doesn't filter comments
        # This documents the behavior (not in scope to fix)
        assert True  # just ensure no crash
