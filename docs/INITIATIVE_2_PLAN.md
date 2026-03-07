# Initiative 2: Hybrid Git Analysis — Implementation Plan

## Context

Current git branch analysis (`--branch-name` mode) extracts **all** type declarations from changed files using regex (`extract_type_names_from_content()`), then traces consumers for every one. This produces false positives — if a file has 5 classes but only 1 was actually modified, all 5 get traced. Comment-only or import-only changes also trigger full analysis.

Hybrid Git Analysis uses the existing Gemini integration to read the actual git diff and identify which symbols were **meaningfully changed**, reducing noise in the blast radius report.

## Approach

Minimal changes to scatter.py. No new files (besides tests), no new dependencies. Reuse existing Gemini infrastructure.

### 1. Add `get_diff_for_file()` helper (~15 lines)

**Where:** After `analyze_branch_changes()` (line ~877 in scatter.py)

Fetches the unified diff text for a single file between merge base and feature branch. Uses the GitPython `repo` object already available.

```python
def get_diff_for_file(repo_path: str, file_path: str,
                      feature_branch: str, base_branch: str = 'main') -> Optional[str]:
```

Returns the diff text string, or None on error.

### 2. Add `get_affected_symbols_from_diff()` function (~60 lines)

**Where:** After `get_diff_for_file()`

Core function. Takes file content + diff text, calls Gemini to identify affected symbols.

```python
def get_affected_symbols_from_diff(file_content: str, diff_text: str,
                                    file_path: str,
                                    model_instance) -> Optional[Set[str]]:
```

- Constructs a prompt asking Gemini to analyze the diff and return a JSON array of affected C# type names (class/struct/interface/enum)
- Parses the JSON response
- Returns `Set[str]` of affected symbols, or `None` on failure (triggers fallback)

**Prompt design:** Ask for only the type declarations whose body/signature/members were changed — not types that merely appear in the same file. Instruct to return `[]` for comment-only or import-only changes.

**Error handling:** Try/except around the entire Gemini call. On any failure (API error, JSON parse error, empty response), return `None` to trigger fallback to regex extraction.

### 3. Add CLI flags (~10 lines)

**Where:** In argument parser (line ~1637, git_group)

```
--enable-hybrid-git    Enable LLM-enhanced diff analysis for more precise symbol extraction (requires Gemini API key)
```

No other new flags needed — reuses existing `--google-api-key` and `--gemini-model`.

### 4. Modify git mode in `main()` (~30 lines changed)

**Where:** Lines 1888-1914 (Step 2: type extraction loop)

Current flow:
```
for each changed file:
    content = read file
    types = extract_type_names_from_content(content)  # regex — gets ALL types
```

New flow (when `--enable-hybrid-git` and Gemini configured):
```
for each changed file:
    content = read file
    diff_text = get_diff_for_file(repo, file, branch, base)
    if diff_text and gemini_model:
        types = get_affected_symbols_from_diff(content, diff_text, file, gemini_model)
        if types is None:  # LLM failed — fallback
            types = extract_type_names_from_content(content)
            log warning about fallback
    else:
        types = extract_type_names_from_content(content)  # original behavior
```

When `--enable-hybrid-git` is not set, behavior is identical to current.

### 5. Configure Gemini earlier for hybrid mode (~5 lines)

**Where:** Lines 1734-1741 in scatter.py

Currently Gemini is only configured when `--summarize-consumers` is set. Add: also configure when `--enable-hybrid-git` is set.

### 6. Tests (~4 test cases)

**File:** New test file `test_hybrid_git.py`

- **AC-01:** Mock Gemini returning `["ModifiedClass"]` for a file with 3 classes — verify only `ModifiedClass` is in extracted types
- **AC-02:** Mock Gemini returning `[]` for comment/import-only change — verify no types extracted
- **AC-03:** Mock Gemini raising exception — verify fallback to regex extraction returns all types
- **AC-04:** Test `get_diff_for_file()` returns valid diff text using the test repo

## Files Modified

| File | Change |
|------|--------|
| `scatter.py` | Add `get_diff_for_file()`, `get_affected_symbols_from_diff()`, CLI flag, modify Step 2 loop, extend Gemini config trigger |
| `test_hybrid_git.py` (new) | 4 acceptance tests |
| `tasks.txt` | Update Initiative 2 status |

## Verification

1. `python -m pytest` — all 63 existing tests still pass (no behavior change without `--enable-hybrid-git`)
2. `python -m pytest test_hybrid_git.py` — new tests pass
3. Manual test: `python scatter.py --branch-name feat/finish-multiprocessing-v1 --repo-path . --base-branch main --enable-hybrid-git --google-api-key $GOOGLE_API_KEY`
4. Compare output with and without `--enable-hybrid-git` to confirm reduced type set
