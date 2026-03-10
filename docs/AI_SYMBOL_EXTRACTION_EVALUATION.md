# Evaluation: AI vs Regex for C# Symbol Extraction

## Context

Scatter's `TYPE_DECLARATION_PATTERN` regex misses ALL C# record variants (even `record class` / `record struct`), delegates, and other modern type forms. `test_new_samples.py` documents these gaps with 54 tests. The question: should we use AI (Gemini) for type extraction, fix the regex, or both? This evaluation covers architecture, cost, LOE, and a recommended phased approach.

## The Gap — What Regex Misses

Verified against our sample projects:

| Pattern | Regex finds? | Why it fails |
|---------|-------------|--------------|
| `public record PersonDto(string Name, int Age);` | No | No `class/struct/interface/enum` keyword |
| `public record class OrderSummary { }` | No | `record` not in modifier list |
| `public record struct Point(double X, double Y);` | No | `record` not in modifier list + `(` not in lookahead |
| `public record struct Coordinate { }` | No | `record` not in modifier list |
| `public delegate Task AsyncEventHandler<T>(...);` | No | `delegate` not a recognized type keyword |
| `internal record InternalAuditEntry(...)` | No | Both `record` gap AND `internal` + no keyword |

**Impact**: In a .NET 6+ codebase, records are used heavily for DTOs, API contracts, events, and value objects. Scatter silently misses them all.

---

## Options Evaluated

### Option D: Fix the Regex — $0, ~120 LOC, 1-2 hours

Two changes to `TYPE_DECLARATION_PATTERN` in `scatter/core/models.py`:
1. Add `record\s+` to the optional modifiers (handles `record class`, `record struct`)
2. Add `record` as a standalone type keyword (handles positional `record Foo(...)`)
3. Add `\(` to the lookahead (handles positional syntax ending with `(`)
4. Add a separate `DELEGATE_DECLARATION_PATTERN` for delegates

Closes 100% of known gaps. Zero runtime cost. Deterministic.

| File | Change | Lines |
|------|--------|-------|
| `scatter/core/models.py` | Update TYPE_DECLARATION_PATTERN, add DELEGATE pattern | ~18 |
| `scatter/scanners/type_scanner.py` | Use both patterns in `extract_type_names_from_content()` | ~10 |
| `scatter/scanners/type_scanner.py` | Update `find_enclosing_type_name()` inline regex | ~5 |
| `test_new_samples.py` | Flip assertions from "not in" to "in" (gap → fixed) | ~20 |
| `test_graph.py` | Update type_declarations counts (Common now has records) | ~10 |
| New `test_type_extraction.py` | Focused unit tests for all record/delegate forms | ~60 |
| **Total** | | **~123** |

### Option E: Hybrid — Fix Regex AND Add AI Enrichment — ~$0.03-0.15/run, ~350 additional LOC, 4-6 hours

After the regex fix, add AI as an opt-in enrichment layer for future-proofing.

**Architecture**: Regex always runs (fast, free). When `--ai-type-extraction` is enabled, batch files to Gemini, merge AI results with regex results (union).

**Batching**: Concatenate 50-80 .cs files per prompt with `===FILE: path===` delimiters. ~13-20 API calls for 1000 files instead of 1000 individual calls.

**Caching**: Extend existing graph cache envelope (`scatter/store/graph_cache.py`) with `ai_type_extraction` key. Same git-based invalidation — only re-extract for files changed since cached commit hash. First run pays full cost; incremental runs nearly free.

**API cost** (Gemini 1.5 Flash @ $0.075/1M input, $0.30/1M output):

| Codebase size | Files | Cost (first run) | Cost (incremental, 50 changed) |
|---|---|---|---|
| Small (this repo, 40 files) | 40 | $0.002 | $0.001 |
| Medium enterprise | 500 | $0.03 | $0.003 |
| Large enterprise | 2000 | $0.15 | $0.003 |

| File | Change | Lines |
|------|--------|-------|
| New `scatter/ai/tasks/type_extraction.py` | Batched AI extraction, prompt, JSON parse | ~120 |
| `scatter/analyzers/graph_builder.py` | Accept strategy param, merge AI results post-regex | ~40 |
| `scatter/__main__.py` | New `--ai-type-extraction` flag, wire to graph_builder | ~25 |
| `scatter/config.py` | `ai.type_extraction: bool` config field | ~10 |
| `scatter/store/graph_cache.py` | Cache AI extraction results in envelope | ~40 |
| `scatter/ai/providers/gemini_provider.py` | Add `extract_types()` method | ~20 |
| New `test_ai_type_extraction.py` | Mocked tests + live-gated integration tests | ~100 |
| **Total (Phase 2 only)** | | **~355** |

### Option A: AI Replaces Regex for ALL Files — Not Recommended

Requires API key for basic `--graph` operation. Breaks the 332 offline tests. Makes a fast deterministic operation dependent on external API. Would need to refactor ~50 existing tests to mock AI. No upside over Option E since regex-first is always faster.

### Option B: AI Only for "Interesting" Files — Not Recommended

The heuristic "AI only for files with no regex types" misses mixed files (a file with both `class` and `record`). Superseded by Option E.

---

## Recommended Approach: Phase 1 (D) then Phase 2 (E)

### Phase 1: Fix the Regex

**Files to modify**:
- `scatter/core/models.py` — Update `TYPE_DECLARATION_PATTERN`, add `DELEGATE_DECLARATION_PATTERN`
- `scatter/scanners/type_scanner.py` — Update `extract_type_names_from_content()` and `find_enclosing_type_name()`
- `test_new_samples.py` — Flip gap-documenting assertions to pass-assertions
- `test_graph.py` — Update type count assertions
- New `test_type_extraction.py` — Focused tests for every C# type form

**Key regex change** (conceptual):
```python
# Current (misses records and delegates):
r"(?:class|struct|interface|enum)\s+"

# Fixed:
r"(?:class|struct|interface|enum|record)\s+"
# Plus: record added to modifier list, ( added to lookahead
# Plus: separate delegate pattern
```

### Phase 2: AI Enrichment (future PR)

**New CLI flag**: `--ai-type-extraction` (boolean, like `--enable-hybrid-git`)

**Config**: `ai.type_extraction: true` in `.scatter.yaml`

**New file**: `scatter/ai/tasks/type_extraction.py`

**Interaction with `--enable-hybrid-git`**: Orthogonal — hybrid-git narrows (which types changed in diff), AI type extraction broadens (what types exist). No conflict.

```
File content --> [extract types] --> {all types in file}
                 |                      |
                 |-- regex (always)     |-- feeds types_by_project / ProjectNode
                 |-- AI (if enabled)    |
                                        |
Git diff    --> [affected symbols] --> {types actually changed}
                 |                      |-- narrows types_by_project
                 |-- AI (hybrid git)
```

**Test architecture**: Follow `test_hybrid_git.py` pattern — MagicMock on `generate_content()` for offline tests. Live API tests gated behind `@pytest.mark.skipif(not os.environ.get("GOOGLE_API_KEY"))`.

### Phase 3: Live AI Comparison Tests (future PR)

**New file**: `test_ai_live_comparison.py`
- Sends actual sample .cs files (Records.cs, DomainEvents.cs, CommonNames.cs) to live Gemini
- Compares regex output vs AI output
- Asserts AI finds everything regex finds plus previously-missed types
- Gated behind `GOOGLE_API_KEY` env var — never runs in CI without credentials
- Validates prompt accuracy against known ground truth

---

## Verification

### Phase 1
- `python -m pytest test_type_extraction.py -v` — all record/delegate forms detected
- `python -m pytest test_new_samples.py -v` — gap assertions flip from "not in" to "in"
- `python -m pytest --tb=short` — full suite passes (332+ tests)

### Phase 2
- `python -m pytest test_ai_type_extraction.py -v` — mocked AI tests pass offline
- `GOOGLE_API_KEY=... python -m pytest test_ai_type_extraction.py -v -m live_ai` — live tests pass
- `python scatter --graph --search-scope . --ai-type-extraction` — graph includes AI-enriched types

---

## Total LOE

| Phase | Lines | Time | Cost |
|-------|-------|------|------|
| Phase 1: Fix regex | ~123 | 1-2 hours | $0 |
| Phase 2: AI enrichment | ~355 | 4-6 hours | $0.003-0.15/run |
| Phase 3: Live comparison tests | ~80 | 1-2 hours | ~$0.01/run |
| **Total** | **~558** | **6-10 hours** | |

---

## Critical Code Paths Reference

| Purpose | File | Key Line(s) |
|---------|------|-------------|
| Type regex definition | `scatter/core/models.py` | 14-21 |
| Type extraction function | `scatter/scanners/type_scanner.py` | 9-24 |
| Enclosing type finder | `scatter/scanners/type_scanner.py` | 27-61 |
| Graph builder type loop | `scatter/analyzers/graph_builder.py` | 116-136 |
| Graph type_usage edge builder | `scatter/analyzers/graph_builder.py` | 183-215 |
| Git branch extraction (regex + hybrid) | `scatter/__main__.py` | 416-430 |
| Consumer class-level filter | `scatter/analyzers/consumer_analyzer.py` | 163-213 |
| Existing AI symbol extraction (diff) | `scatter/ai/providers/gemini_provider.py` | 22-81 |
| AI provider protocol | `scatter/ai/base.py` | 7-39 |
| Graph cache (for AI result caching) | `scatter/store/graph_cache.py` | entire file |
| Test pattern for AI mocking | `test_hybrid_git.py` | MagicMock pattern |
