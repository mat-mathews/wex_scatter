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

# C# using statements
USING_PATTERN = re.compile(
    r"^\s*using\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;",
    re.MULTILINE,
)
