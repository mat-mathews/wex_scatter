"""Shared constants and compiled patterns for Scatter."""
import re
import multiprocessing

# multiprocessing configuration
DEFAULT_MAX_WORKERS = min(32, (multiprocessing.cpu_count() or 1) + 4)
DEFAULT_CHUNK_SIZE = 75
MULTIPROCESSING_ENABLED = True

# --- regex for type extraction ---
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"  # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*"  # Optional keywords
    r"(?:class|struct|interface|enum)\s+"  # Type keyword
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)"  # Capture type name (non-greedy) - handles generics roughly
    r"\s*(?::|{|where|<)",  # Look for inheritance colon, opening brace, where clause, or start of generics
    re.MULTILINE
)
