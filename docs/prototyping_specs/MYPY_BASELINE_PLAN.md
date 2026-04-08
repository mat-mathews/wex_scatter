# Mypy Baseline — Implementation Plan

**Branch:** feature/mypy-baseline
**Estimated effort:** 0.5-1 day
**Depends on:** ConsumerResult dataclass (shipped)
**Blocks:** Init 8 Phase 3 (CI pipeline — mypy must pass clean)
**Team review:** 2026-03-21 (Priya, Marcus, Tomás, Devon, Anya, Jake, Fatima, Sam, Kai)

---

## Current State

`uv run mypy scatter --ignore-missing-imports` produces **77 errors across 17 files**.
No mypy config exists in pyproject.toml yet.

---

## Error Inventory by Category

### Category 1: Stale ConsumerResult type annotations (23 errors) — `console_reporter.py`

All 23 errors are the same root cause: `print_console_report` signature still
says `List[Dict[str, Union[str, Dict, List[str]]]]` but the code accesses
`.target_project_name` (attribute access on ConsumerResult objects).

This is leftover from the ConsumerResult migration that updated the code but
didn't fix all type annotations (Anya). Other stale signatures exist in
`cli.py` (`all_results: List[Dict]`, `_summarize_consumer_files: List[Dict]`).

**Fix:** Update all stale type annotations to `List[ConsumerResult]`.

### Category 2: Untyped raw consumer dicts (20 errors) — `v1_bridge.py`, `impact_analyzer.py`, `cli.py`

The raw consumer dicts from `find_consumers()` have type
`Dict[str, Union[Path, str, List[Path]]]`. When code accesses
`consumer_info['consumer_path']`, mypy infers `Path | str | List[Path]`
and complains when it's passed to functions expecting `Path`.

**Fix:** Define `RawConsumerDict` TypedDict (Marcus, Tomás). 4 lines, fixes 20
errors, documents the contract, no runtime overhead:

```python
class RawConsumerDict(TypedDict):
    consumer_path: Path
    consumer_name: str
    relevant_files: List[Path]
```

Update `find_consumers()` return type to `List[RawConsumerDict]`.

### Category 3: `all_results` type annotations in `cli.py` (5 errors)

Three callsites pass `list[dict[Any, Any]]` to v1_bridge which expects
`list[ConsumerResult]`. Two more access `.consumer_project_path` on
`dict[Any, Any]`.

**Fix:** Part of Category 1 — update `all_results` annotations throughout
`cli.py` mode handlers.

### Category 4: `parallel.py` lowercase `any` (3 errors)

Lines 295, 382, 385 use `any` (the builtin function) as a type hint
instead of `typing.Any`. Flagged in leadership review.

**Fix:** `any` → `Any`.

### Category 5: Missing type annotations (5 errors) — `var-annotated`

Variables need explicit types:

```python
namespace_match_files: List[Path] = []
all_relevant_files: List[Path] = []
class_match_files: List[Path] = []
matching_files: List[Path] = []
dir_to_csproj: Dict[Path, Path] = {}
```

### Category 6: Optional not narrowed (5 errors) — `union-attr`

Code calls methods on `Optional[X]` without checking for `None`:

| File | Line | Fix |
|------|------|-----|
| `graph_reporter.py:271` | `node.solutions` where node is `Optional` | Add `if node:` guard |
| `gemini_provider.py:199` | `self.model.generate_content()` where model is `Optional` | Add `if self.model is None:` guard |
| `graph_patcher.py:339` | `graph.get_node()` returns `Optional` | Add None check |
| `health_analyzer.py:205` | Same pattern | Add None check |

### Category 7: Dict/assignment type mismatches (8 errors) — reporters

`build_graph_json()` and `json_reporter` build dicts incrementally. Mypy
infers the type from the first assignment. Later assignments conflict.

**Fix:** Annotate report dicts as `Dict[str, Any]`.

### Category 8: Miscellaneous (8 errors)

| File | Error | Fix |
|------|-------|-----|
| `config.py:16` | yaml stubs not installed | Add `types-PyYAML` to dev deps |
| `coupling_analyzer.py:171-176` | `frozenset` vs `set \| None` | Fix narrowing |
| `graph_builder.py:99` | `str \| None` assigned to `str` | Add `or ""` fallback |
| `markdown_reporter.py:132` | List type mismatch in append | Fix annotation |
| `consumer_analyzer.py:320` | `str \| Path` assigned to `Path` | Use `Path()` |
| `graph_patcher.py:563` | `walk_up` kwarg (Python 3.12 only) | **Investigate compat bug** — add 3.10 fallback (Fatima, Devon) |
| `cli.py:458` | `AIProvider` missing `extract_affected_symbols` | Add to protocol (Sam, Marcus) |

---

## Implementation Phases

### Phase 1: Configuration (~5 min)

Add mypy config to `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true
```

No `--strict` or `--check-untyped-defs` yet — clean baseline first,
tighten incrementally (Kai, Priya).

Add `types-pyyaml` to dev deps. Keep `ignore_missing_imports` for all
other third-party libraries (Jake, Marcus).

### Phase 2: Finish ConsumerResult type annotations (~30 min)

These are stale signatures from the ConsumerResult migration (Anya):

1. `console_reporter.py` — `all_results` param: `List[ConsumerResult]` (fixes 23)
2. `cli.py` — `dispatch_legacy_output`, `_summarize_consumer_files`, mode
   handler `all_results` variables: `List[ConsumerResult]` (fixes 5)
3. `parallel.py` — `any` → `Any` (fixes 3)
4. `consumer_analyzer.py` / `sproc_scanner.py` — add `List[Path]` annotations (fixes 5)
5. `graph_reporter.py` / `json_reporter.py` — `report: Dict[str, Any]` (fixes 8)
6. `graph_builder.py` — `namespace = namespace or ""` (fixes 1)

**Expected: ~45 errors fixed**

### Phase 3: Type narrowing — Optional guards (~20 min)

Add `None` checks before accessing Optional values:

1. `graph_reporter.py:271` — `if node:` guard
2. `gemini_provider.py:199` — None guard on model
3. `graph_patcher.py:339` — None check
4. `health_analyzer.py:205` — None check
5. `coupling_analyzer.py:171-176` — narrowing fix

**Expected: ~5 errors fixed**

### Phase 4: RawConsumerDict TypedDict (~30 min)

Define `RawConsumerDict` TypedDict (named to make it obvious it's a dict —
Tomás):

```python
class RawConsumerDict(TypedDict):
    consumer_path: Path
    consumer_name: str
    relevant_files: List[Path]
```

Update `find_consumers()` return type and all access sites in `v1_bridge.py`,
`impact_analyzer.py`, `cli.py`.

**Expected: ~20 errors fixed**

### Phase 5: Remaining fixes (~15 min)

- `cli.py:458` — add `extract_affected_symbols` to `AIProvider` protocol (Marcus)
- `graph_patcher.py:563` — investigate `walk_up` (Python 3.12 only). If needed,
  add fallback for 3.10 compatibility. Don't just `# type: ignore` (Fatima, Devon)
- `markdown_reporter.py:132` — fix list type
- `consumer_analyzer.py:320` — `Path()` cast

**Expected: remaining errors fixed, 0 total**

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| `RawConsumerDict` TypedDict, not casts | 4 lines, fixes 20 errors, documents contract, no runtime overhead | Marcus, Tomás |
| Named `RawConsumerDict` not `RawConsumer` | It's a dict — make that obvious | Tomás |
| Phase 2 framed as "finish ConsumerResult migration" | The annotations are stale, not wrong — code is correct, types lag | Anya |
| `types-pyyaml` only, `ignore_missing_imports` for rest | Don't chase stubs for transitive deps | Jake, Marcus |
| No `--strict` or `--check-untyped-defs` | Clean baseline first, tighten incrementally | Kai, Priya |
| Investigate `walk_up` properly | 3.12-only feature, may be a latent compat bug on 3.10 | Fatima, Devon |
| Add `extract_affected_symbols` to AIProvider protocol | Method exists on GeminiProvider but missing from protocol | Sam, Marcus |

---

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Add `[tool.mypy]` config, `types-pyyaml` to dev deps |
| `scatter/core/models.py` | Add `RawConsumerDict` TypedDict |
| `scatter/reports/console_reporter.py` | Fix `all_results` type annotation |
| `scatter/core/parallel.py` | `any` → `Any`, annotate `dir_to_csproj` |
| `scatter/analyzers/consumer_analyzer.py` | Add type annotations, use `RawConsumerDict` return |
| `scatter/reports/graph_reporter.py` | `Dict[str, Any]` annotations, None guard |
| `scatter/reports/json_reporter.py` | `Dict[str, Any]` annotations |
| `scatter/compat/v1_bridge.py` | Use `RawConsumerDict` type |
| `scatter/analyzers/impact_analyzer.py` | Use `RawConsumerDict`, type narrowing |
| `scatter/cli.py` | Fix `all_results` types to `List[ConsumerResult]` |
| `scatter/analyzers/coupling_analyzer.py` | Fix set/frozenset narrowing |
| `scatter/analyzers/graph_builder.py` | Namespace fallback |
| `scatter/analyzers/health_analyzer.py` | None check |
| `scatter/ai/base.py` | Add `extract_affected_symbols` to AIProvider protocol |
| `scatter/ai/providers/gemini_provider.py` | None check on model |
| `scatter/store/graph_patcher.py` | Fix `walk_up` compat for 3.10, None check |
| `scatter/reports/markdown_reporter.py` | Fix list type |
| `scatter/scanners/sproc_scanner.py` | Annotate variable |

---

## Acceptance Criteria

- `uv run mypy scatter --ignore-missing-imports` → **0 errors**
- `uv run pytest` → **789 tests passing, 0 regressions**
- No behavioral changes — all fixes are annotations, None guards, and type narrowing

---

## Risk

**Low.** All changes are type annotations, None guards, and a TypedDict (which is
a type-checking-only construct with zero runtime impact). The 789 existing tests
catch any accidental behavioral change.

The `walk_up` investigation (Fatima) may reveal a latent compat bug — if so, the
fix is a 3.10-compatible fallback, not a type annotation.
