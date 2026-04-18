# Development

How the dev environment, tooling, and CI pipeline work together. For adding features and writing code, see [Contributing](contributing.md).

---

## Package Manager: uv

Scatter uses [uv](https://docs.astral.sh/uv/) for dependency management. All dependencies (runtime and dev) are declared in `pyproject.toml` and locked in `uv.lock`.

```bash
# Install all deps (creates .venv automatically)
uv sync

# Run any tool through uv (uses the project's .venv)
uv run pytest
uv run ruff check scatter/
uv run mypy scatter
```

uv replaces `pip`, `pip-tools`, `venv`, and `requirements.txt`. There is no `requirements.txt` — `pyproject.toml` is the single source of truth.

### Optional extras

Scatter has optional dependency groups for features that not everyone needs:

```bash
# AST validation (tree-sitter for --parser-mode hybrid)
uv sync --extra ast

# Pipeline artifact parsing (pandas for parse_pipeline_artifacts.py)
uv sync --extra pipeline-tools

# Both
uv sync --extra ast --extra pipeline-tools
```

The `ast` extra installs `tree-sitter` and `tree-sitter-c-sharp`. Without it, `--parser-mode hybrid` silently falls back to regex. If you're working on anything in `scatter/parsers/`, install this.

### Adding dependencies

```bash
# Runtime dependency
uv add some-package

# Dev-only dependency
uv add --group dev some-dev-tool
```

---

## Developer Scripts

All developer tooling lives in `tools/`. The scripts are bash — on Windows, run them from Git Bash (included with Git for Windows).

| Script | Purpose | When to use |
|--------|---------|-------------|
| `tools/setup.sh` | One-time environment bootstrap | After cloning, or when onboarding someone new |
| `tools/check.sh` | Local CI mirror | Before pushing — catches issues before CI |
| `tools/check.sh --quick` | Lint + format only (~2s) | While iterating on code |
| `tools/generate_pipeline_csv.py` | Generate pipeline CSV from app-config repo | When pipelines are added/removed, or when "pipeline not found" warnings appear |
| `tools/setup-claude-skills.sh` | Link Claude Code skills | Called by `setup.sh` automatically |
| `tools/smoke-test-claude-skills.sh` | Validate skills work | After modifying skill definitions |

### setup.sh

Idempotent bootstrap that:

1. Checks Python >= 3.10
2. Checks uv is installed (prints install command if not)
3. Runs `uv sync`
4. Configures `git blame.ignoreRevsFile`
5. Links Claude Code skills

### check.sh

Runs the exact same checks as GitHub Actions CI:

```bash
bash tools/check.sh          # full: ruff check + ruff format + mypy + pytest
bash tools/check.sh --quick  # fast: ruff check + ruff format only
```

If `check.sh` passes locally, CI will pass. No drift between local and CI.

---

## Documentation Site

The docs site lives in `docs_site/` and is built with [mkdocs](https://www.mkdocs.org/) + the [Material](https://squidfunk.github.io/mkdocs-material/) theme. The dependencies are declared separately from the main project in `docs_site/requirements-docs.txt`.

### Via Docker (no Python install required)

The official `squidfunk/mkdocs-material` image has everything needed:

```bash
# Build the static site into docs_site/site/
docker run --rm -v "$(pwd)":/docs -w /docs squidfunk/mkdocs-material \
    build -f docs_site/mkdocs.yml

# Or serve it live at http://localhost:8000 with auto-reload
docker run --rm -it -p 8000:8000 -v "$(pwd)":/docs -w /docs squidfunk/mkdocs-material \
    serve -f docs_site/mkdocs.yml -a 0.0.0.0:8000
```

Works identically on macOS, Linux, and Windows (Git Bash).

### Via uv

If you already have Python and uv:

```bash
uv run --with-requirements docs_site/requirements-docs.txt \
    mkdocs serve -f docs_site/mkdocs.yml
```

The `--with-requirements` flag installs the docs deps into an ephemeral uv-managed environment — no pollution of your project `.venv`.

The built `site/` directory is gitignored, so rebuilding in-tree is safe.

---

## Pipeline CSV Generator

`tools/generate_pipeline_csv.py` crawls the WEX app-config repo and produces a pipeline-to-application mapping CSV. Stdlib only, no scatter imports.

```bash
# Via Docker (no Python install required)
docker run --rm \
    -v "$(pwd)":/workspace \
    -v /path/to/health-benefits-app-config:/config:ro \
    python:3.12-slim \
    python /workspace/tools/generate_pipeline_csv.py \
        --app-config-path /config \
        --output /workspace/examples/pipeline_to_app_mapping.csv

# Via uv
uv run python tools/generate_pipeline_csv.py \
    --app-config-path /path/to/health-benefits-app-config \
    --output examples/pipeline_to_app_mapping.csv
```

The generator always writes a clean, complete file — it does not merge with existing data. Manual overrides for apps the generator can't resolve belong in `examples/pipeline_manual_overrides.csv` (same schema, `source=manual`). Scatter loads both files at runtime; manual entries take precedence.

### When to regenerate

Regenerate when new pipelines are added to the config repo, or when scatter's "Pipeline not found" warnings start appearing for projects you know are deployed. Review the diff before committing:

```bash
git diff examples/pipeline_to_app_mapping.csv
```

---

## Linting: ruff

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting. Configuration lives in `pyproject.toml` under `[tool.ruff]`.

### Rules

| Rule set | What it catches |
|----------|----------------|
| **E** | pycodestyle errors (syntax, whitespace) |
| **F** | pyflakes (unused imports, undefined names, unused variables) |
| **W** | pycodestyle warnings |

### Ignored rules

| Rule | Why |
|------|-----|
| **E501** | Line too long — ruff format handles code structure; long strings are readable as-is |
| **E741** | Ambiguous variable name (`l`, `O`, `I`) — a font issue, not a code issue |

### Per-file ignores

| File pattern | Rule | Why |
|-------------|------|-----|
| `__init__.py` | **F401** | Barrel re-exports look like unused imports but are the public API |

### Commands

```bash
uv run ruff check scatter/          # lint
uv run ruff check scatter/ --fix    # auto-fix what's possible
uv run ruff format scatter/         # format
uv run ruff format --check scatter/ # check formatting without changing files
```

### Format settings

- **Line length**: 100 (middle ground — fits laptops, less reformatting noise than 88)
- **Quote style**: double
- **Target version**: Python 3.10

---

## Type Checking: mypy

[mypy](https://mypy.readthedocs.io/) is configured in `pyproject.toml` under `[tool.mypy]`.

```bash
uv run mypy scatter --ignore-missing-imports
```

Current baseline: **0 errors**. CI enforces this — any new type error will fail the build.

Settings: `python_version = "3.11"`, `warn_return_any = true`, `warn_unused_configs = true`, `ignore_missing_imports = true`.

---

## CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and every PR. Three jobs run in parallel:

### test

Runs `uv run pytest --cov=scatter --cov-report=term-missing -q` across a Python version matrix (3.10, 3.11). Coverage threshold is 70% (currently ~79%).

### lint

Runs `uv run ruff check scatter/` and `uv run ruff format --check scatter/`. Any lint error or formatting drift fails the build.

### type-check

Runs `uv run mypy scatter --ignore-missing-imports`. Any type error fails the build.

All three jobs use `astral-sh/setup-uv@v4` with `enable-cache: true` for fast installs on repeat runs.

---

## Git Configuration

### .git-blame-ignore-revs

Mass formatting commits destroy `git blame` history. The `.git-blame-ignore-revs` file tells git (and GitHub's web UI) to skip those commits when computing blame.

`tools/setup.sh` configures this automatically:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

### Optional: pre-push hook

To run checks automatically before every push:

```bash
echo 'bash tools/check.sh' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

This is opt-in — `setup.sh` mentions it but doesn't install it.

---

## Tool Versions

| Tool | Version | Managed by |
|------|---------|-----------|
| Python | >= 3.10 | System / pyenv / uv |
| uv | latest | System (`curl` install) |
| ruff | latest | `pyproject.toml` dev deps, pinned by `uv.lock` |
| mypy | latest | `pyproject.toml` dev deps, pinned by `uv.lock` |
| pytest | >= 9, < 10 | `pyproject.toml` dev deps |
| pytest-cov | >= 7, < 8 | `pyproject.toml` dev deps |
