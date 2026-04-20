"""Shared regex patterns for C# source analysis.

Used by both graph_builder (full build) and graph_patcher (incremental updates).
Keeping these in one place prevents divergence between the two code paths.
"""

import re

# C# identifiers (for inverted-index type matching)
IDENT_PATTERN = re.compile(r"[A-Za-z_]\w*")

# Stored procedure references in string literals
SPROC_PATTERN = re.compile(
    r"""["'](?:[a-zA-Z_][a-zA-Z0-9_]*\.)?(?:sp_|usp_)\w+["']""",
    re.IGNORECASE,
)

# C# using statements (matches regular and global using; excludes using static)
USING_PATTERN = re.compile(
    r"^\s*(?:global\s+)?using\s+(?!static\s)([A-Za-z_][A-Za-z0-9_.]*)\s*;",
    re.MULTILINE,
)

# C# keywords — cannot be used as unescaped type names.
# Verbatim identifiers like @class are legal but IDENT_PATTERN extracts "class"
# not "@class", so they would not appear as declared type names either.
# Safe to filter from identifier sets before type matching.
CSHARP_KEYWORDS = frozenset({
    # Reserved keywords (79)
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch",
    "char", "checked", "class", "const", "continue", "decimal", "default",
    "delegate", "do", "double", "else", "enum", "event", "explicit",
    "extern", "false", "finally", "fixed", "float", "for", "foreach",
    "goto", "if", "implicit", "in", "int", "interface", "internal", "is",
    "lock", "long", "namespace", "new", "null", "object", "operator",
    "out", "override", "params", "private", "protected", "public",
    "readonly", "ref", "return", "sbyte", "sealed", "short", "sizeof",
    "stackalloc", "static", "string", "struct", "switch", "this", "throw",
    "true", "try", "typeof", "uint", "ulong", "unchecked", "unsafe",
    "ushort", "using", "virtual", "void", "volatile", "while",
    # Contextual keywords (~30)
    "add", "and", "alias", "ascending", "args", "async", "await", "by",
    "descending", "dynamic", "equals", "file", "from", "get", "global",
    "group", "init", "into", "join", "let", "managed", "nameof", "nint",
    "not", "notnull", "nuint", "on", "or", "orderby", "partial", "record",
    "remove", "required", "scoped", "select", "set", "unmanaged", "value",
    "var", "when", "where", "with", "yield",
})
