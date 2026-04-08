# Hybrid AST Spike — Phase 2: Consumer Analyzer Wiring + Tech Debt

## Context

Phase 1 shipped the tree-sitter validation layer for the graph builder (`6d28602`). It filters false-positive `type_usage` edges caused by identifiers in comments/strings. But the consumer analyzer — the thing users actually see output from — still relies on raw regex matching. Stages 4 (class filter) and 5 (method filter) in `find_consumers()` use `\bClassName\b` and `.method_name(` patterns that can't distinguish real code from comments/strings. Phase 2 wires the existing `validate_type_usage()` into those stages, plus addresses all tech debt the team flagged during review.

## Design Decisions

1. **Add `"use_ast": bool` to the existing worker config dicts** — the dict already flows through `ProcessPoolExecutor` serialization. No new parameter on `analyze_cs_files_parallel/batch`. Resolve `use_ast` once at the top of `find_consumers()`, inject into the dict.

2. **Reuse `validate_type_usage()` for both class and method stages** — the function does byte-level substring search + non-code range check. For methods, pass `".MethodName"` (no paren) to avoid false negatives when C# has whitespace before `(`. The dot anchors it to member access (Fatima).

3. **Fix the string-index vs UTF-8 byte-offset bug at capture time** in `graph_builder.py` — but guard with `content.isascii()` so the 99% ASCII case pays zero cost. Only build the char→byte offset array for non-ASCII files (Devon).

4. **Cache compiled `Query` objects** at module level in `ast_validator.py` — `QueryCursor` stays fresh per call (it's stateful). Query compilation is the repeated cost.

5. **Rename local `analysis_config` dicts to `stage_config`** in `consumer_analyzer.py` to avoid collision with the new `analysis_config: AnalysisConfig` parameter (Priya).

## Implementation Steps

### Step 1: Tech debt in `scatter/parsers/ast_validator.py`

**a) Cache compiled Query objects + guard `_ts_language`**

```python
_query_cache: Dict[str, object] = {}

def _run_query(query_string, root_node, capture_name):
    if _ts_language is None:
        _get_parser()  # Kai's guard: ensure language initialized
    import tree_sitter
    query = _query_cache.get(query_string)
    if query is None:
        query = tree_sitter.Query(_ts_language, query_string)
        _query_cache[query_string] = query
    cursor = tree_sitter.QueryCursor(query)
    for _, captures in cursor.matches(root_node):
        for node in captures.get(capture_name, []):
            yield node
```

**b) Reset `_parser`/`_ts_language` on init failure**

Wrap `_get_parser()` body in try/except, reset both globals on failure so next call retries.

### Step 2: Fix byte-offset bug in `scatter/analyzers/graph_builder.py:60-67`

Guard with `content.isascii()` so the common case (99%+ of C# files) pays zero cost. Only build the offset array for non-ASCII files:

```python
if use_ast:
    is_ascii = content.isascii()
    if not is_ascii:
        # Build char-index → byte-offset lookup for non-ASCII safety
        byte_offsets = []
        byte_pos = 0
        for ch in content:
            byte_offsets.append(byte_pos)
            byte_pos += len(ch.encode("utf-8"))

    ident_positions: Dict[str, List[int]] = {}
    for m in _IDENT_PATTERN.finditer(content):
        pos = m.start() if is_ascii else byte_offsets[m.start()]
        ident_positions.setdefault(m.group(), []).append(pos)
    ...
```

### Step 3: Add `analysis_config` to `find_consumers()` signature

**File: `scatter/analyzers/consumer_analyzer.py:111`**

```python
def find_consumers(
    ...,
    graph: Optional["DependencyGraph"] = None,
    analysis_config: Optional["AnalysisConfig"] = None,  # NEW
) -> Tuple[List[RawConsumerDict], FilterPipeline]:
```

Resolve `use_ast` at top of function body (same pattern as graph_builder):
```python
use_ast = False
if analysis_config and analysis_config.parser_mode == "hybrid":
    from scatter.parsers.ast_validator import is_hybrid_available
    if is_hybrid_available():
        use_ast = True
```

### Step 4: Rename local dicts + inject `use_ast` into stage 4 and 5

Rename all local `analysis_config` dicts in `consumer_analyzer.py` to `stage_config` (Priya's fix — avoids collision with the new `analysis_config` parameter).

**Stage 3 (namespace, ~line 268):** Rename `analysis_config` → `stage_config` (no `use_ast` needed — `using` statements don't produce false positives).

**Stage 4 (class filter, ~line 361):**
```python
stage_config = {
    "analysis_type": "class",
    "class_name": class_name,
    "class_pattern": class_pattern,
    "use_ast": use_ast,  # NEW
}
```

**Stage 5 (method filter, ~line 435):**
```python
stage_config = {
    "analysis_type": "method",
    "method_pattern": method_pattern,
    "method_name": method_name,  # NEW — raw name for AST
    "use_ast": use_ast,           # NEW
}
```

### Step 5: Wire AST confirmation into `analyze_cs_files_batch()`

**File: `scatter/core/parallel.py:385-404`**

After regex match succeeds and `use_ast` is set, call `validate_type_usage()` to confirm the match is in code:

**Class branch (~line 390):**
```python
file_result["has_match"] = len(matches) > 0
# AST confirmation: filter false positives in comments/strings
if file_result["has_match"] and analysis_config.get("use_ast"):
    from scatter.parsers.ast_validator import validate_type_usage
    class_name = analysis_config.get("class_name", "")
    if not validate_type_usage(content, class_name):
        file_result["has_match"] = False
        file_result["matches"] = []
```

**Method branch (~line 404):**
```python
file_result["has_match"] = len(matches) > 0
if file_result["has_match"] and analysis_config.get("use_ast"):
    from scatter.parsers.ast_validator import validate_type_usage
    method_name = analysis_config.get("method_name", "")
    # Use ".MethodName" (no paren) to avoid false negatives on "method (" with whitespace
    if method_name and not validate_type_usage(content, f".{method_name}"):
        file_result["has_match"] = False
        file_result["matches"] = []
```

Notes:
- `from ... import` inside worker is intentional — `ProcessPoolExecutor` workers need their own imports
- `validate_type_usage` returns `True` on error → conservative, never drops valid matches
- Regex runs first; AST only runs if regex found something → zero added cost for non-matching files
- Method search uses `.MethodName` without paren to handle `method (` whitespace variant (Fatima)

### Step 6: Thread `analysis_config` through all call sites

| Call site | File | Change |
|-----------|------|--------|
| Target mode | `scatter/cli.py:374` | Add `analysis_config=ctx.config.analysis` |
| Git mode | `scatter/cli.py:606` | Add `analysis_config=ctx.config.analysis` |
| Sproc mode | `scatter/cli.py:756` | Add `analysis_config=ctx.config.analysis` |
| Impact orchestrator | `scatter/modes/impact.py:41` | Add `analysis_config=ctx.config.analysis` to `run_impact_analysis()` |
| Impact analyzer | `scatter/analyzers/impact_analyzer.py:46` | Add param, thread to `_analyze_single_target()` |
| Single target | `scatter/analyzers/impact_analyzer.py:222` | Add param, thread to `find_consumers()` call at line 250 |
| Transitive | `scatter/analyzers/impact_analyzer.py:294` | Add param, thread to `find_consumers()` at line 369 (harmless — class_name=None skips stages 4-5) |

### Step 7: Tests

**Add fixture: `tests/fixtures/false_positive_usage.cs`**

A .cs file that produces a nonzero hybrid delta — regex matches but AST correctly filters:
```csharp
// PortalDataService is referenced in this documentation comment
public class UnrelatedConsumer {
    public void DoStuff() {
        // var svc = new PortalDataService();  // commented out
        var x = "PortalDataService";  // string literal mention
    }
}
```

**New: `tests/unit/test_consumer_ast_hybrid.py`**
- Class in comment only → regex matches, hybrid doesn't (the delta test using fixture above)
- Class in both comment AND real code → both match (partial match — must not filter valid usage)
- Method in string only → regex matches, hybrid doesn't
- Method with whitespace before paren `.Save (` → both match (Fatima's case)
- Real code usage → both match
- AST error fallback → regex result preserved (`validate_type_usage` patched to raise)
- Non-ASCII byte offset correctness (unicode comment before identifier)

**New: `tests/integration/test_hybrid_consumer_regression.py`**
- Run `find_consumers()` on sample projects in regex and hybrid modes
- Assert hybrid results `<=` regex results

**Extend: `tests/unit/test_ast_validator.py`**
- Add varied-content concurrency test (different C# snippets per thread)
- Add test with non-ASCII content to exercise byte-offset conversion

**Verify:** Run the full existing test suite (`pytest tests/unit/ tests/integration/`) to confirm the optional `analysis_config=None` parameter doesn't break the 35+ existing `find_consumers()` tests.

### Step 8: Verify

```bash
uv sync --extra ast
ruff check && ruff format --check
pytest tests/unit/ tests/integration/test_hybrid_regression.py tests/integration/test_hybrid_consumer_regression.py
# Target mode comparison:
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . --class-name PortalDataService --output-format json --output-file /tmp/regex_consumer.json
python -m scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . --class-name PortalDataService --parser-mode hybrid --output-format json --output-file /tmp/hybrid_consumer.json
```

## Files Summary

| File | Action |
|------|--------|
| `scatter/parsers/ast_validator.py` | Modify — query cache, `_ts_language` guard, `_parser` reset |
| `scatter/analyzers/graph_builder.py` | Modify — byte-offset fix in `_extract_file_data` |
| `scatter/analyzers/consumer_analyzer.py` | Modify — add `analysis_config` param, resolve `use_ast`, inject into dicts |
| `scatter/core/parallel.py` | Modify — AST confirmation in class/method branches |
| `scatter/cli.py` | Modify — thread `analysis_config` at 3 call sites |
| `scatter/modes/impact.py` | Modify — thread `analysis_config` |
| `scatter/analyzers/impact_analyzer.py` | Modify — thread `analysis_config` through 3 functions |
| `tests/unit/test_consumer_ast_hybrid.py` | Create |
| `tests/integration/test_hybrid_consumer_regression.py` | Create |
| `tests/unit/test_ast_validator.py` | Modify — concurrency + non-ASCII tests |

## Commit Sequence

1. **Tech debt**: Steps 1-2 (query cache, `_ts_language` guard, parser reset, byte-offset fix)
2. **Consumer wiring**: Steps 3-5 (signature, dict injection, worker AST)
3. **Call sites**: Step 6 (all callers threaded)
4. **Tests**: Step 7-8 (unit + integration + fixture)
