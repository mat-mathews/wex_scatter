# Type Extraction

How Scatter identifies C# type declarations from source files. This is the foundation of every analysis mode -- if Scatter can't figure out what types live in a file, nothing downstream works.

---

## Regex Extraction (Default)

Scatter's workhorse. Two compiled patterns in `scatter/core/models.py` handle the heavy lifting.

### TYPE_DECLARATION_PATTERN

The primary pattern that matches `class`, `struct`, `interface`, `enum`, and `record` declarations:

```python
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"       # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+|"
    r"record\s+|readonly\s+|ref\s+)*"                      # Optional keywords (any combination)
    r"(?:class|struct|interface|enum|record)\s+"            # The type keyword itself
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)"                     # Capture group 1: type name (non-greedy)
    r"\s*(?::|{|where|<|\(|;)",                            # Terminator: inheritance, brace, constraint, etc.
    re.MULTILINE
)
```

Breaking that down group by group:

| Group | What it matches | Examples |
|-------|----------------|----------|
| Access modifier | `public`, `internal`, `private`, `protected` (optional) | `public`, or nothing |
| Keywords | Zero or more of: `static`, `abstract`, `sealed`, `partial`, `record`, `readonly`, `ref` | `public sealed partial` |
| Type keyword | One of: `class`, `struct`, `interface`, `enum`, `record` | `class` |
| Type name (captured) | Identifier with optional generic params | `MyService`, `Repository<T, K>` |
| Terminator | Colon (inheritance), `{`, `where`, `<`, `(`, `;` | `: BaseClass {` |

The captured type name then gets post-processed in `extract_type_names_from_content()`:

1. Strip everything after the first `<` (removes generic parameters)
2. Split on `,` and take the first segment
3. Strip whitespace

So `Repository<T, K>` becomes `Repository`. This is intentional -- consumers reference the type by its base name, not its generic arity.

### DELEGATE_DECLARATION_PATTERN

Handles the oddball syntax of delegate declarations:

```python
DELEGATE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"
    r"delegate\s+"
    r"[A-Za-z_][A-Za-z0-9_<>,\s\[\]\.]*?\s+"   # Return type
    r"([A-Za-z_][A-Za-z0-9_]*)"                  # Delegate name (captured)
    r"\s*[<(]",                                   # Generic params or parameter list
    re.MULTILINE
)
```

Delegates are types too -- and they show up as project dependencies when other projects reference them.

### Key Behavior: All Types, All the Time

Here's the thing that catches people off guard. When Scatter operates in regex mode, it extracts **every type declared in a changed file** -- not just the ones the diff touched. If you change a comment inside `MyService` in a file that also declares `MyHelper` and `IMyRepository`, Scatter reports all three as potentially affected.

This is a deliberate precision trade-off. Regex can't understand scope or diff hunks. It knows what types exist in a file; it does not know which ones changed. This means regex mode over-reports. You get false positives, but never false negatives.

### Where Regex Extraction Is Used

- **Git branch mode** (step 4 of `build_dependency_graph`): Extracts type declarations from all `.cs` files to build the type-to-project index
- **Graph builder** (step 4): Same extraction, used to populate `ProjectNode.type_declarations`
- **Type usage edge construction**: The inverted index (`type_to_projects` dict) is built from regex-extracted type names

### Performance

Extraction is O(L) per file where L is line count. The regex runs on file content in a single `finditer()` pass. For the graph builder, this is part of a larger O(P + F) pipeline where P = projects and F = files. At 500 projects / 15K files, type extraction takes under 2 seconds.

---

## LLM Extraction (`--enable-hybrid-git`)

The precision upgrade. Instead of "every type in this file," the LLM answers: "which types actually changed?"

### How It Works

The function `extract_affected_symbols_from_model()` in `scatter/ai/providers/gemini_provider.py` sends two things to the Gemini API:

1. **Full file content** -- the entire `.cs` file
2. **Git diff** -- the specific diff hunk for that file

The prompt asks the model to identify which top-level type declarations had their body, signature, or members "meaningfully changed" in the diff.

### The Prompt

```
Analyze the following C# file and its git diff. Identify which top-level
type declarations (class, struct, interface, enum) had their body, signature,
or members meaningfully changed in the diff.

Rules:
- Only return type names whose definition/body/members were actually modified
- Do NOT include types that merely appear in the same file but were not changed
- For comment-only or using/import-only changes, return an empty array
- Return ONLY a JSON array of type name strings, nothing else
```

### Response Parsing

The response goes through a hardening pipeline:

1. Strip leading/trailing whitespace
2. If the response starts with `` ``` ``, strip markdown code fences (LLMs love to wrap JSON in fences even when we ask them not to)
3. Parse as JSON
4. Validate it's a list
5. Filter to strings only
6. Return as `Set[str]`

### Comment-Only Changes

This is where hybrid mode earns its keep. If you only changed a comment or added a `using` statement, the LLM returns an empty array `[]`. Scatter then skips the downstream consumer analysis entirely for that file. Regex mode would have flagged every type in the file.

### Fallback Behavior

LLM extraction falls back to regex on:

- API failure (network error, rate limit, timeout)
- Invalid JSON response
- Non-list response type
- Any exception during parsing

The fallback is logged at WARNING level. You never lose analysis coverage -- you just lose precision for that particular file.

### Task Type

LLM extraction uses `AITaskType.SYMBOL_EXTRACTION` from the `AIProvider` protocol. The provider's `supports()` method must return `True` for this task type. Currently only `GeminiProvider` implements it.

---

## Comparison

| Dimension | Regex | LLM (`--enable-hybrid-git`) |
|-----------|-------|-----------------------------|
| **Speed** | Instant (~microseconds/file) | ~1-2 seconds per file (API round-trip) |
| **Precision** | All types in file (over-reports) | Only changed types |
| **Comment-only changes** | Flags all types in file | Returns empty list (no analysis) |
| **API key required** | No | Yes (Gemini) |
| **Failure mode** | N/A | Falls back to regex |
| **Cost** | Free | API token costs per file |
| **Deterministic** | Yes | No (LLM variance) |

For most workflows, regex is fine. Hybrid mode pays off on large feature branches where many files changed but only a few types actually matter -- it narrows the blast radius analysis significantly.

---

## `find_enclosing_type_name()`

A supporting utility in `scatter/scanners/type_scanner.py`. Given a character position in a `.cs` file, it walks backward through the content to find the nearest enclosing type declaration.

```python
def find_enclosing_type_name(content: str, match_start_index: int) -> Optional[str]:
```

The algorithm:

1. Compile a multiline regex for type declarations (similar to `TYPE_DECLARATION_PATTERN` but with `re.MULTILINE`)
2. Run `finditer()` from position 0 up to `match_start_index`
3. Track the last match -- that's the closest enclosing type
4. Extract and clean the type name (strip generics, split on comma)

**Used in**: Stored procedure analysis. When Scatter finds a sproc reference like `"dbo.sp_InsertPortalConfiguration"` at position 1,247 in a file, `find_enclosing_type_name()` determines it's inside `PortalDataService`. That class name becomes the link in the consumer chain.

The walk-backward approach is O(N) where N is the content length up to the match position. It doesn't try to parse brace nesting or understand scope -- it just finds the nearest type declaration above the match. For deeply nested types (type within a type), it returns the innermost one, which is usually what you want.

---

## AST Validation (`--parser-mode hybrid`)

A different kind of "hybrid" from the LLM approach above. This one uses **tree-sitter** (a local parser, no AI, no API calls) to filter false positives in the consumer pipeline's class and method filtering stages.

### What It Does

When you search for consumers of `PortalDataService` with `--class-name`, Scatter's regex (`\bPortalDataService\b`) matches every occurrence in every `.cs` file — including comments, string literals, and documentation templates. These are false positives: the project mentions the type but doesn't actually use it in code.

With `--parser-mode hybrid`, after the regex finds a match, Scatter parses the file with tree-sitter, builds a map of non-code ranges (comments and strings), and checks whether the match falls inside one. If every occurrence is in a non-code position, the file is filtered out.

### Where It Runs

AST validation runs only in the **consumer pipeline** (stages 4 and 5), not during graph construction. The graph builder uses pure regex — AST overhead there adds ~40% build time for zero measured edge delta.

| Stage | What happens |
|-------|-------------|
| Stage 4 (class filter) | `validate_type_usage(content, class_name)` |
| Stage 5 (method filter) | `validate_type_usage(content, f".{method_name}")` — dot anchors to member access, no paren to handle `.Save (data)` |

Regex runs first. AST only fires if regex found a match. Non-matching files pay zero additional cost.

### How It Differs from LLM Hybrid

| | `--parser-mode hybrid` (AST) | `--enable-hybrid-git` (LLM) |
|---|---|---|
| **Technology** | tree-sitter (local C parser) | Gemini API (remote LLM) |
| **API key** | No | Yes |
| **Speed** | ~1ms per file | ~1-2s per file |
| **What it filters** | False positives in consumer detection (comments/strings) | Over-reported types in git branch extraction |
| **Where it runs** | Consumer pipeline stages 4-5 | Git mode type extraction (step 2) |
| **Failure mode** | Returns regex result (conservative) | Falls back to regex |
| **Install** | `uv sync --extra ast` | Included by default |

They solve different problems and can be used together.

### Setup

```bash
# Install tree-sitter dependencies
uv sync --extra ast

# Use hybrid mode
scatter --target-project ./MyLib/MyLib.csproj --search-scope . \
  --class-name MyService --parser-mode hybrid
```

If tree-sitter is not installed, `--parser-mode hybrid` silently falls back to regex.

---

## Adding a New Extraction Strategy

If you want to add a new extraction approach (say, Roslyn-based):

1. Create a function with signature `(content: str) -> Set[str]` in `scatter/scanners/type_scanner.py`
2. Wire it into `graph_builder.py` where `extract_type_names_from_content()` is called
3. For hybrid/AI approaches, add a new `AITaskType` and implement the provider method
4. Add tests in `test_type_extraction.py` -- the existing 48 tests cover edge cases you'll want to match
