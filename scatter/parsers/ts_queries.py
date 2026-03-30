"""Tree-sitter S-expression queries for C# syntax analysis.

Each query string is annotated with the C# pattern it matches.
"""

# Captures type declaration names:
#   class Foo { }
#   struct Bar { }
#   interface IFoo { }
#   enum Status { }
#   record Point(int X, int Y);
#   delegate void Handler(object sender, EventArgs e);
TYPE_DECLARATIONS_QUERY = """
(class_declaration name: (identifier) @type_name)
(struct_declaration name: (identifier) @type_name)
(interface_declaration name: (identifier) @type_name)
(enum_declaration name: (identifier) @type_name)
(record_declaration name: (identifier) @type_name)
(delegate_declaration name: (identifier) @type_name)
"""

# Captures non-code ranges (comments, string literals) for exclusion.
# Any identifier whose byte position falls inside one of these ranges
# is considered a false positive.
#
#   // single-line comment
#   /* block comment */
#   "regular string"
#   @"verbatim string"
#   $"interpolated {expr} string"
NON_CODE_RANGES_QUERY = """
(comment) @non_code
(string_literal) @non_code
(verbatim_string_literal) @non_code
(interpolated_string_expression) @non_code
"""
