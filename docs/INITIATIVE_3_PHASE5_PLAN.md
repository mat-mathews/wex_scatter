# Initiative 3 Phase 5: Configuration System + AI Task Router

## Context

Initiative 3 modularized scatter into a package with pluggable AI providers. Phases 1-4 established the `AIProvider` protocol, `GeminiProvider`, and AI task modules. However, configuration is entirely CLI-driven — no config files, no way to set repo-level defaults, and provider selection is hardcoded to Gemini in `__main__.py`. Phase 5 adds a YAML config system with layered precedence and an AI task router for provider selection/fallback.

## Scope

- `scatter/config.py` — load config from `.scatter.yaml`, `~/.scatter/config.yaml`, env vars, CLI overrides
- `scatter/ai/router.py` — select AI provider per task type, with fallback logic
- Update `scatter/__main__.py` — use config + router instead of inline GeminiProvider creation
- Tests for both new modules
- NOT in scope: caching (`ai/cache.py`), token budgeting (`ai/budget.py`), new providers

## 1. `scatter/config.py`

### Data model

```python
@dataclass
class AIConfig:
    default_provider: str = "gemini"               # provider name
    task_overrides: Dict[str, str] = field(...)     # AITaskType value → provider name
    credentials: Dict[str, str] = field(...)        # provider_name.key → value (e.g. gemini.api_key)
    gemini_model: str = "gemini-1.5-flash"

@dataclass
class ScatterConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    max_depth: int = 2
    disable_multiprocessing: bool = False
    max_workers: Optional[int] = None
    chunk_size: Optional[int] = None
    exclude_patterns: List[str] = field(...)        # glob patterns to skip
```

### Loading logic

```python
def load_config(
    repo_root: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> ScatterConfig:
```

**Precedence** (highest wins):
1. CLI flags (passed as `cli_overrides` dict)
2. Repo-level `.scatter.yaml` (in `repo_root` or cwd)
3. User-level `~/.scatter/config.yaml`
4. Environment variables (`GOOGLE_API_KEY`, `SCATTER_DEFAULT_PROVIDER`, etc.)
5. Hardcoded defaults

**Mechanics:**
- Use `yaml.safe_load()` for YAML parsing (PyYAML already in requirements)
- Build base config from defaults → merge user config → merge repo config → merge CLI overrides
- Env vars map: `GOOGLE_API_KEY` → `ai.credentials.gemini.api_key`, `SCATTER_DEFAULT_PROVIDER` → `ai.default_provider`
- Missing config files silently ignored (not errors)

### Config file schema

```yaml
# .scatter.yaml (repo-level)
ai:
  default_provider: gemini
  gemini_model: gemini-1.5-flash
  task_overrides:
    work_request_parsing: gemini
    risk_assessment: gemini
  credentials:
    gemini:
      api_key: ""  # prefer env var or user config
search:
  max_depth: 2
  exclude_patterns:
    - "*/bin/*"
    - "*/obj/*"
multiprocessing:
  disabled: false
  max_workers: null
  chunk_size: null
```

## 2. `scatter/ai/router.py`

### Design

```python
class AIRouter:
    def __init__(self, config: ScatterConfig):
        self._config = config
        self._providers: Dict[str, AIProvider] = {}  # lazy cache

    def get_provider(self, task_type: Optional[AITaskType] = None) -> Optional[AIProvider]:
        """Get the best provider for a task type.

        Resolution order:
        1. task_overrides[task_type] if specified
        2. default_provider
        Returns None if provider can't be created (missing credentials).
        """

    def _create_provider(self, provider_name: str) -> Optional[AIProvider]:
        """Lazy-create a provider by name. Cache for reuse."""
        # Currently only "gemini" is supported.
        # Future providers plug in here.
```

**Key behaviors:**
- Lazy initialization — providers created on first `get_provider()` call, not at startup
- Cached — same provider instance reused across calls with same name
- Graceful failure — returns `None` if credentials missing, logs warning
- The `supports()` check is done: if provider doesn't support the task type, return `None`

### Provider registry

For now, hardcoded mapping in `_create_provider()`:
```python
if provider_name == "gemini":
    return GeminiProvider(api_key=..., model_name=...)
```

Future providers (wex_platform, anthropic, openai) just add `elif` branches. When there are 5+, refactor to a registry dict.

## 3. `scatter/__main__.py` changes

### Before (current):
```python
ai_provider = None
if args.summarize_consumers or args.enable_hybrid_git or is_impact_mode:
    try:
        ai_provider = GeminiProvider(args.google_api_key, args.gemini_model)
    except (ValueError, Exception) as e:
        ...
```

### After:
```python
from scatter.config import load_config
from scatter.ai.router import AIRouter

# Build CLI overrides dict from args
cli_overrides = _build_cli_overrides(args)
config = load_config(repo_root=search_scope_abs, cli_overrides=cli_overrides)
router = AIRouter(config)

ai_provider = None
if args.summarize_consumers or args.enable_hybrid_git or is_impact_mode:
    ai_provider = router.get_provider()
    if ai_provider is None and is_impact_mode:
        logging.error("Impact analysis requires a working AI provider. Exiting.")
        sys.exit(1)
```

**Helper:**
```python
def _build_cli_overrides(args) -> Dict[str, Any]:
    """Extract CLI args that override config values."""
    overrides = {}
    if args.google_api_key:
        overrides["ai.credentials.gemini.api_key"] = args.google_api_key
    if args.gemini_model:
        overrides["ai.gemini_model"] = args.gemini_model
    if args.disable_multiprocessing:
        overrides["multiprocessing.disabled"] = True
    # etc.
    return overrides
```

## 4. Exports

- `scatter/ai/__init__.py` — export `AIRouter`
- `scatter/__init__.py` — export `ScatterConfig`, `load_config`, `AIRouter`

## 5. Tests — `test_config.py`

~15-20 tests:

**TestScatterConfig:**
- `test_default_config` — defaults are sensible
- `test_load_empty_directory` — no yaml files → defaults
- `test_load_repo_config` — `.scatter.yaml` values applied
- `test_load_user_config` — `~/.scatter/config.yaml` values applied
- `test_repo_overrides_user` — repo config wins over user config
- `test_cli_overrides_all` — CLI overrides win over everything
- `test_env_var_credentials` — `GOOGLE_API_KEY` env var flows to `ai.credentials.gemini.api_key`
- `test_missing_yaml_files_ignored` — no errors for missing files
- `test_malformed_yaml_ignored` — invalid YAML logs warning, uses defaults
- `test_partial_config` — YAML with only `ai.default_provider` merges with defaults for everything else
- `test_exclude_patterns_from_config` — search.exclude_patterns loaded correctly

**TestAIRouter:**
- `test_get_provider_default` — returns GeminiProvider when gemini is default + credentials exist
- `test_get_provider_no_credentials` — returns None, logs warning
- `test_get_provider_task_override` — task_overrides routes specific task to specific provider
- `test_provider_caching` — same provider instance returned on repeated calls
- `test_unsupported_task_type` — provider that doesn't support task returns None
- `test_unknown_provider_name` — returns None, logs warning

## 6. Files to create/modify

| File | Action |
|------|--------|
| `scatter/config.py` | **Create** — config loading + dataclasses |
| `scatter/ai/router.py` | **Create** — AI task router |
| `scatter/__main__.py` | **Modify** — use config + router |
| `scatter/__init__.py` | **Modify** — add exports |
| `scatter/ai/__init__.py` | **Modify** — add exports |
| `test_config.py` | **Create** — tests for config + router |

## Verification

```bash
# All existing tests still pass
python -m pytest --tb=short

# New config/router tests pass
python -m pytest test_config.py -v

# Manual: create a .scatter.yaml and verify it's picked up
echo 'ai:\n  gemini_model: gemini-2.0-flash' > .scatter.yaml
python -m scatter --sow "test" --search-scope . -v 2>&1 | grep "gemini-2.0-flash"
```
