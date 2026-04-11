# Hybrid AST Spike: Tree-Sitter Validation Layer

## Context

Scatter's dependency graph is built with regex pattern matching. This works well for broad scanning but produces false positives — identifiers in comments/strings create phantom `type_usage` edges, and `\bClassName\b` in consumer analysis can't distinguish real usage from mentions in comments. The spike introduces an **optional tree-sitter validation layer** that filters regex matches against the actual syntax tree, reducing false positives without replacing the regex engine.

The feature is **off by default** (`parser_mode: regex`). Devs opt in via `.scatter.yaml` or `--parser-mode hybrid`.

**Spike scope**: Config + CLI + parsers module + graph_builder wiring only. Consumer analyzer wiring is Phase 2 — the graph builder's broad scan (set intersection on line 275) is where phantom edges are born, and cleaner graph edges automatically improve downstream consumer analysis.

## Team Design Decisions

These decisions emerged from team review and override the naive approach:

1. **Thread `AnalysisConfig`, not `parser_mode: str`** — `build_dependency_graph()` accepts `analysis_config: Optional[AnalysisConfig] = None` instead of a bare string. One object, zero signature churn when we add future options (Priya).
2. **Capture identifier match positions during regex pass** — `_extract_file_data` captures `{identifier: [byte_positions]}` when AST mode is on, avoiding a second file scan during validation. Binary search against AST non-code ranges (Devon).
3. **Cache key includes parser mode** — `parser_mode` stored in cache metadata; mismatch triggers rebuild. Same pattern as `invalidation` strategy (Kai/Priya).
4. **Clear naming** — `identifiers_in_code()` not `filter_code_identifiers()`. Comments above each S-expression query showing the C# pattern it matches (Sam).
5. **Regression test invariant** — hybrid mode must produce `<=` edges compared to regex mode on same input. Test the graceful fallback with mocked imports (Anya).
6. **Benchmark** — run `tools/benchmark_graph_build.py` in both modes, report delta (Marcus).

## Implementation Steps

### 1. Dependencies — `pyproject.toml`

Add optional extra:
```toml
[project.optional-dependencies]
ast = ["tree-sitter>=0.23,<1", "tree-sitter-c-sharp>=0.23,<1"]
```

Add both to existing `dev` dependency group so CI always tests hybrid mode.

### 2. Config — `scatter/config.py`

New dataclass:
```python
@dataclass
class AnalysisConfig:
    parser_mode: str = "regex"  # "regex" | "hybrid"
```

Add `analysis: AnalysisConfig` field to `ScatterConfig`.

Wire into `_apply_yaml()` (new `analysis` section) and `_apply_cli_overrides()` (key `"analysis.parser_mode"`).

### 3. CLI flag — `scatter/cli_parser.py`

Add `--parser-mode` to `common_group` (choices: `regex`, `hybrid`, default: `None`).

Add to `_build_cli_overrides()`: `overrides["analysis.parser_mode"] = args.parser_mode`.

### 4. Parser module — `scatter/parsers/` (3 new files)

**`scatter/parsers/__init__.py`** — Barrel exports.

**`scatter/parsers/ts_queries.py`** — S-expression query strings with C# pattern comments:
- `TYPE_DECLARATIONS_QUERY` — captures names from `class_declaration`, `struct_declaration`, `interface_declaration`, `enum_declaration`, `record_declaration`, `delegate_declaration`
- `NON_CODE_RANGES_QUERY` — captures `comment`, `string_literal`, `verbatim_string_literal`, `interpolated_string_expression` nodes for exclusion ranges

**`scatter/parsers/ast_validator.py`** — Core module:
- Lazy import of `tree_sitter` + `tree_sitter_c_sharp` (no import-time cost when off)
- `is_hybrid_available() -> bool`
- `parse_csharp(content: str) -> Tree` (module-level cached parser)
- `identifiers_in_code(content: str, candidates: Dict[str, List[int]]) -> Set[str]` — takes identifier→byte positions map, builds non-code interval set from AST, binary-searches each position, keeps identifiers with at least one code occurrence
- `validate_type_declarations(content: str, regex_types: Set[str]) -> Set[str]` — intersects regex types with AST-confirmed declarations
- `validate_type_usage(content: str, type_name: str) -> bool` — confirms at least one occurrence is in a code position (not comment/string). Reserved for Phase 2 consumer analyzer wiring.

All functions gracefully return the regex input on any error (logged at DEBUG).

### 5. Wire into graph builder — `scatter/analyzers/graph_builder.py`

- Add `analysis_config: Optional[AnalysisConfig] = None` parameter to `build_dependency_graph()`
- Resolve `use_ast` bool at top of function; warn + fallback if hybrid requested but tree-sitter not installed
- Modify `_extract_file_data()`:
  - When `use_ast=True`, capture identifier positions: `{m.group(): m.start() for m in IDENT_PATTERN.finditer(content)}` → build `Dict[str, List[int]]`
  - After regex extraction, call `identifiers_in_code(content, ident_positions)` to filter
  - Call `validate_type_declarations(content, regex_types)` to validate
  - Content is already read at line 45; pass to AST functions directly — no double read
- When `use_ast=False` (default), zero code path changes — existing behavior preserved exactly

### 6. Cache key update — `scatter/store/graph_cache.py`

- Add `parser_mode: str` field to cache metadata
- On load, compare stored `parser_mode` with current config; mismatch → stale cache → rebuild
- Default to `"regex"` for caches that predate this field (backwards compatible)

### 7. Thread config through call sites (spike scope only — graph builder callers)

| Call site | Change |
|-----------|--------|
| `scatter/modes/graph.py:50` | Pass `analysis_config=config.analysis` |
| `scatter/modes/dump_index.py:47` | Pass `analysis_config=config.analysis` |
| `scatter/analyzers/graph_enrichment.py:128` | Pass `analysis_config=config.analysis` |

Consumer analyzer call sites (`cli.py`, `impact_analyzer.py`) are **not touched** in this spike.

### 8. Tests

**New: `tests/unit/test_ast_validator.py`**
- `TestIdentifiersInCode`: identifier only in comment excluded, in code kept, in both kept, empty input
- `TestValidateTypeDeclarations`: real class confirmed, regex false positive (e.g. `record.Save()`) filtered, multiple types with subset confirmed
- `TestValidateTypeUsage`: usage in `new Foo()` confirmed, mention in comment rejected, in string literal rejected
- `TestGracefulFallback`: mock import failure → functions return regex input + warning logged
- `TestThreadSafety`: 4 threads parse same content concurrently, no crashes

**New: `tests/integration/test_hybrid_regression.py`**
- Build graph on sample projects in regex mode, build in hybrid mode
- Assert: hybrid edge count `<=` regex edge count for every edge type
- Assert: `project_reference` edges identical (AST doesn't affect XML parsing)
- Assert: `namespace_usage` edges identical (not validated by AST in spike)

**Extend: `tests/unit/test_config.py`**
- Default `parser_mode` is `"regex"`
- YAML `analysis.parser_mode: hybrid` loads correctly
- CLI override wins

**Extend: `tests/unit/test_cli_parser.py`**
- `--parser-mode hybrid` parses and produces correct override

### 9. Verify

```bash
uv sync --extra ast
ruff check && ruff format --check
pytest tests/unit/ tests/integration/test_hybrid_regression.py
# Regex-only (default):
python -m scatter --graph --search-scope . --output-format json --output-file /tmp/regex.json
# Hybrid mode:
python -m scatter --graph --search-scope . --parser-mode hybrid --output-format json --output-file /tmp/hybrid.json
# Compare edge counts
python tools/benchmark_graph_build.py --mode full --search-scope .  # regex baseline
python tools/benchmark_graph_build.py --mode full --search-scope . --parser-mode hybrid  # hybrid
```

## Files Summary

| File | Action |
|------|--------|
| `pyproject.toml` | Modify — add `[ast]` optional extra, add to dev deps |
| `scatter/config.py` | Modify — add `AnalysisConfig`, wire into `ScatterConfig` |
| `scatter/cli_parser.py` | Modify — add `--parser-mode` flag and override |
| `scatter/parsers/__init__.py` | Create |
| `scatter/parsers/ts_queries.py` | Create — query strings with C# pattern comments |
| `scatter/parsers/ast_validator.py` | Create — core validation functions |
| `scatter/analyzers/graph_builder.py` | Modify — wire AST into `_extract_file_data` |
| `scatter/store/graph_cache.py` | Modify — add `parser_mode` to cache key |
| `scatter/modes/graph.py` | Modify — pass `analysis_config` |
| `scatter/modes/dump_index.py` | Modify — pass `analysis_config` |
| `scatter/analyzers/graph_enrichment.py` | Modify — pass `analysis_config` |
| `tests/unit/test_ast_validator.py` | Create |
| `tests/integration/test_hybrid_regression.py` | Create |
| `tests/unit/test_config.py` | Modify — add AnalysisConfig tests |
| `tests/unit/test_cli_parser.py` | Modify — add `--parser-mode` test |

## Phase 2 (not in spike)

- Wire `validate_type_usage()` into `consumer_analyzer.py` stages 4-5 via `parallel.py`
- Thread `analysis_config` through `find_consumers()` and its call sites
- Extend `validate_type_usage` to distinguish type references from other identifier positions using AST node types (object_creation, variable_declaration, base_list, etc.)
