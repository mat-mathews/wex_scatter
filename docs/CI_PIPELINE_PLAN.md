# CI Pipeline — Implementation Plan

**Branch:** feature/ci-pipeline
**Initiative:** 8 Phase 3 (Production Readiness)
**Estimated effort:** 0.5-1 day
**Depends on:** uv packaging (shipped), mypy baseline (shipped)
**Team review:** 2026-03-21 (Priya, Marcus, Tomás, Anya, Jake, Devon, Fatima, Sam, Kai)

---

## Current State

- Existing `.github/workflows/ci.yml` uses pip + requirements.txt (deleted)
- `uv run mypy scatter --ignore-missing-imports` → 0 errors
- `uv run ruff check scatter/` → **145 errors** (113 unused imports, 20 f-string, 6 ambiguous names, 3 unused vars, 3 multi-statement)
- `uv run ruff format --check scatter/` → **44 files** need reformatting
- `uv run pytest` → 789 passed

---

## Approach: Fix Ruff First, Then Wire CI

CI won't pass with 145 lint errors and 44 unformatted files. Two-step:

1. **Fix ruff errors + format** — one commit, mostly auto-fixable
2. **Update ci.yml** — replace pip with uv, add lint + mypy stages

---

## Phase 1: Ruff Cleanup

### 1a: Configure ruff in pyproject.toml

```toml
[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = [
    "E741",  # ambiguous variable name (l, O, I) — font problem, not code problem
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]  # re-exports are intentional barrel imports

[tool.ruff.format]
quote-style = "double"
```

Key decisions:
- **Line length 100** (Marcus, Priya, Sam) — middle ground between 88 (too
  aggressive, more reformatting noise) and 120 (too generous). Fits laptops,
  matches Google's Python style guide.
- **`E741` ignored globally** (Devon, Tomás) — ambiguous variable names like
  `l` are a font problem, not a code problem. Rename individually if confusing.
- **`__init__.py` F401 ignored** (Fatima, Priya) — barrel re-exports look like
  unused imports to ruff (analyzes one file at a time). Standard pattern for
  packages with `from scatter import find_consumers` API.

### 1b: Auto-fix what we can

```bash
uv run ruff check scatter/ --fix        # fixes F401 (unused imports), F841 (unused vars)
uv run ruff format scatter/             # formats all files to line-length=100
```

### 1c: Manual fixes

- **F541** (20 f-strings without placeholders) — remove the `f` prefix.
  Quick fix, 1-character edit each (Tomás, Sam — don't ignore, they're
  genuinely wrong).
- **E701** (3 multiple statements on one line) — split to two lines.
- Any remaining after auto-fix.

### 1d: Verify

```bash
uv run ruff check scatter/              # 0 errors
uv run ruff format --check scatter/     # 0 files would be reformatted
uv run pytest                           # 789 tests still pass
```

### 1e: Add `.git-blame-ignore-revs` (Priya, Anya)

Mass formatting commits destroy `git blame` history. Mitigate:

```
# .git-blame-ignore-revs
# Ruff formatting pass — 2026-03-21
<commit-hash>
```

Then configure the repo:
```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

GitHub also respects this file automatically in the web UI.

---

## Phase 2: Update CI Workflow

Replace the existing `ci.yml` with a uv-based workflow:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
          enable-cache: true
      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}
      - name: Install dependencies
        run: uv sync --python ${{ matrix.python-version }}
      - name: Run tests
        run: uv run pytest --cov=scatter --cov-report=term-missing -q

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
          enable-cache: true
      - name: Install dependencies
        run: uv sync
      - name: Ruff check
        run: uv run ruff check scatter/
      - name: Ruff format
        run: uv run ruff format --check scatter/

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
          enable-cache: true
      - name: Install dependencies
        run: uv sync
      - name: Mypy
        run: uv run mypy scatter --ignore-missing-imports
```

Key decisions:
- **Python 3.10 + 3.11 matrix** for tests (matches `requires-python >= 3.10`)
- **Lint and type-check on single version** (default 3.11) — no need to matrix
- **Three separate jobs** — fail independently, run in parallel
- **`enable-cache: true`** on setup-uv (Jake) — caches uv downloads, saves
  10-20s per job on repeat runs
- **`astral-sh/setup-uv@v4`** — official uv action

### Pre-push verification (Fatima, Priya)

Before pushing, verify tests pass on 3.10 locally:

```bash
uv run --python 3.10 pytest
```

If 3.10 fails, fix in this branch. Don't let CI go red on first run.

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| `.git-blame-ignore-revs` for formatting commit | Mass reformat destroys git blame. This file tells git and GitHub to skip it. | Priya, Anya |
| `__init__.py` F401 per-file ignore | Barrel re-exports are intentional. Ruff would delete the public API. | Fatima, Priya |
| Line length 100 | Middle ground. Less reformatting noise than 88, fits laptops unlike 120. | Marcus, Priya, Sam |
| E741 global ignore | Ambiguous variable names are a font issue. Rename individually if confusing. | Devon, Tomás |
| Fix F541, don't ignore | f-strings without placeholders are wrong. 20 one-char edits. | Tomás, Sam |
| `enable-cache: true` on uv action | Saves 10-20s per CI job on repeat runs. | Jake |
| Verify 3.10 locally before push | Catch compat issues before red CI. | Fatima, Priya |

---

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Add `[tool.ruff]` config |
| `.github/workflows/ci.yml` | Replace pip with uv, add lint + mypy jobs |
| **NEW** `.git-blame-ignore-revs` | Ignore formatting commit in git blame |
| `scatter/**/*.py` | Ruff auto-fixes (unused imports, formatting) |

---

## Risk

**Low.** Ruff auto-fix removes unused imports and reformats — no behavioral
changes. The CI workflow is standard GitHub Actions with uv.

The only risk is a formatting change that breaks a test assertion on exact
output. Run full test suite after formatting to verify. The `.git-blame-ignore-revs`
file mitigates the git blame pollution from mass formatting.

The 3.10 verification step (Fatima) catches any latent compat issues before
they show up as a red CI on the first run.
