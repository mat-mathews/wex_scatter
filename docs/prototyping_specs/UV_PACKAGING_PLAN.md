# Python Packaging with uv — Implementation Plan

**Branch:** feature/uv-packaging
**Initiative:** 8 Phase 2 (Production Readiness)
**Estimated effort:** 0.5 day
**Depends on:** Nothing
**Blocks:** Init 8 Phase 3 (CI pipeline with GitHub Actions)
**Team review:** 2026-03-21 (Priya, Marcus, Tomás, Jake, Kai, Anya, Devon, Fatima, Sam)

---

## Goal

Replace manual venv management with uv. After this:
- `uv sync` installs everything (deps + dev tools)
- `uv run scatter` runs the tool
- `uv run pytest` runs tests
- `uv.lock` ensures reproducible installs across machines
- `requirements.txt` is deleted (pyproject.toml is the single source of truth)
- `pip install .` works as fallback for non-uv users

---

## Current State

- `pyproject.toml` exists but only has `[tool.pytest]` and `[tool.coverage]` config
- `requirements.txt` has 6 deps with version ranges
- `scatter/__version__.py` has `__version__ = "2.1.0"`
- `scatter.py` is a thin entry point (runpy to `scatter.__main__`)
- `scatter/__main__.py:main()` is the real entry point
- uv 0.5.21 is installed locally
- Python 3.11.12 in use, no `.python-version` file

---

## Deliverables

### 1. Expand `pyproject.toml` with full project metadata

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "wex-scatter"
version = "2.1.0"  # keep in sync with scatter/__version__.py
description = ".NET dependency graph engine — trace blast radius before you ship"
requires-python = ">=3.10"
dependencies = [
    "gitpython>=3.1,<4",
    "google-generativeai>=0.8,<1",
    "pyyaml>=6,<7",
]

[project.optional-dependencies]
pipeline-tools = ["pandas>=1.5,<3"]

[project.scripts]
scatter = "scatter.__main__:main"

[dependency-groups]
dev = [
    "pytest>=9,<10",
    "pytest-cov>=7,<8",
    "ruff",
    "mypy",
]
```

Key decisions:
- **`[build-system]` with hatchling** (Jake, Kai) — uv's recommended default.
  Lightweight, fast, enables `pip install .` fallback for non-uv users.
- **`requires-python = ">=3.10"`** — oldest supported CPython. WEX uses 3.11+
  for new projects, but 3.10 is still in some legacy services (Marcus).
- **`[project.scripts]`** — `scatter` command maps to `scatter.__main__:main`
  so `uv run scatter --help` works.
- **pandas moved to optional deps** (Fatima, Tomás, Devon) — only used by
  `parse_pipeline_artifacts.py` utility, not core scatter. 30MB+ dependency
  most users never need. Install with `uv sync --extra pipeline-tools`.
- **Dev deps in `[dependency-groups]`** — uv's preferred pattern. `uv sync`
  installs dev deps by default; `uv sync --no-group dev` for production.
- **Version in both files** (Priya) — `pyproject.toml` and `__version__.py`
  kept in sync manually. Comment in pyproject.toml, version consistency test
  catches drift. Dynamic version over-engineers a twice-a-quarter operation.

### 2. Generate `uv.lock`

```bash
uv lock
```

Resolves all dependencies, creates `uv.lock` with exact pinned versions.
Committed to git for reproducible installs.

### 3. Add `.python-version`

```
3.11
```

uv uses this to auto-detect which Python to use. `3.11` is the development
default (Marcus). `requires-python >= 3.10` allows older runtimes.

### 4. Delete `requirements.txt`

Replaced by `pyproject.toml` + `uv.lock`. Non-uv users do `pip install .`
which reads pyproject.toml directly (Jake, Kai — requires `[build-system]`).

### 5. Verify everything works

```bash
# Clean slate
rm -rf .venv

# Install everything
uv sync

# Run the tool (both paths — Fatima)
uv run scatter --help
uv run scatter --graph --search-scope .
uv run python scatter.py --help    # backward compat thin entry point

# Run tests
uv run pytest
uv run pytest --cov

# Verify pip fallback
pip install .
scatter --help
```

### 6. Version consistency test (Anya)

```python
def test_version_consistency():
    """pyproject.toml and __version__.py must agree."""
    import tomllib
    from scatter.__version__ import __version__
    with open("pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
    assert pyproject["project"]["version"] == __version__
```

Catches drift automatically in CI.

### 7. Update all docs that mention pip install (Sam)

Every place that says `pip install -r requirements.txt` gets updated.
uv is primary, `pip install .` is fallback:

**CLAUDE.md:**
```markdown
### Python Environment Setup
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (creates .venv automatically)
uv sync

# Or without uv:
pip install .
```

**documentation/docs/getting-started.md:**
- uv install instructions as primary
- pip fallback noted

**tools/claude-skills/README.md:**
- Update prerequisites from `pip install -r requirements.txt` to `uv sync`

**docs/CLAUDE_SKILLS.md:**
- Same update

---

## Design Decisions (from team review)

| Decision | Rationale | Who |
|----------|-----------|-----|
| Hatchling build backend | uv's recommended default. Lightweight, enables pip fallback. | Jake, Kai |
| pandas to optional deps | 30MB, used only by one utility script. Don't penalize core users. | Fatima, Tomás, Devon |
| Version in both files (no dynamic) | Dynamic version adds import-time complexity for a twice-a-quarter operation. Test catches drift. | Priya, Anya |
| `requires-python >= 3.10` | Oldest supported CPython. WEX has some 3.10 services. | Marcus, Tomás |
| `.python-version = 3.11` | Development default. Different purpose from requires-python. | Marcus |
| Delete requirements.txt | pyproject.toml + uv.lock replaces it. `pip install .` is the non-uv fallback. | Tomás, Jake |

---

## Tests

| Test | What it validates |
|------|-------------------|
| `test_version_consistency` | pyproject.toml version matches `__version__.py` (Anya) |
| Manual: `uv sync` | Clean install works |
| Manual: `uv run scatter --help` | Entry point works |
| Manual: `uv run python scatter.py --help` | Backward compat thin entry point (Fatima) |
| Manual: `uv run pytest` | All 788 tests pass |
| Manual: `pip install .` | Non-uv fallback works (Jake) |

---

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Expand with [build-system], [project], deps, scripts, dev group |
| **NEW** `uv.lock` | Generated by `uv lock`, committed |
| **NEW** `.python-version` | `3.11` |
| **DELETE** `requirements.txt` | Replaced by pyproject.toml |
| `CLAUDE.md` | Update setup instructions to uv |
| `documentation/docs/getting-started.md` | uv install instructions |
| `tools/claude-skills/README.md` | Update prerequisites |
| `docs/CLAUDE_SKILLS.md` | Update prerequisites |
| Test file | Add `test_version_consistency` |

---

## What This Does NOT Change

- `scatter.py` thin entry point — still works via `python scatter.py`
- `python -m scatter` — still works
- `scatter/__main__.py` — unchanged
- Test files — unchanged (uv runs pytest the same way)
- No code changes to scatter package (except version test)
- `parse_pipeline_artifacts.py` still works — just needs `uv sync --extra pipeline-tools`

---

## Risk

**Low.** Packaging and tooling only — zero code changes to the scatter package.
The `[build-system]` with hatchling is standard PEP 517. `uv.lock` pins exact
versions for reproducibility. Both `uv run scatter` and `python scatter.py`
invoke the same `main()` function.

The only migration risk is the pandas removal from required deps — if someone
runs `parse_pipeline_artifacts.py` after a fresh install without `--extra
pipeline-tools`, they'll get an ImportError. The script should catch that and
print a helpful message. That's a one-line fix if needed, not a blocker.
