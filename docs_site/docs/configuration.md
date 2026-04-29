# Configuration

Scatter uses a layered configuration system. You can configure nothing and it works. You can configure everything and it still works. The layers merge top-down, so a CLI flag always wins.

## Precedence

| Priority | Source | Path / Mechanism |
|----------|--------|------------------|
| 1 (highest) | CLI flags | `--max-depth 3`, `--google-api-key ...`, etc. |
| 2 | Repo config | `.scatter.yaml` in the repo root |
| 3 | User config | `~/.scatter/config.yaml` |
| 4 | Environment variables | `GOOGLE_API_KEY`, `WEX_AI_API_KEY`, `SCATTER_DEFAULT_PROVIDER` |
| 5 (lowest) | Built-in defaults | Hardcoded in `scatter/config.py` |

Missing config files are silently ignored. You do not need `.scatter.yaml` in your repo. You do not need `~/.scatter/config.yaml` at home. Scatter checks for them, shrugs if they are absent, and moves on. No warnings, no errors.

## Typical Setup

Most teams land on a two-file setup: one user-level config that holds your API key, one repo-level config that holds repo-specific defaults. CLI flags for one-off experiments.

### User-level config (`~/.scatter/config.yaml`)

Set your API key once. Every Scatter run in every repo picks it up.

```yaml
ai:
  credentials:
    gemini:
      api_key: AIzaSy...your-key-here
```

### Repo-level config (`.scatter.yaml`)

Repo-specific defaults. Committed to source control so the whole team shares them.

```yaml
search:
  max_depth: 3
  exclude_patterns:
    - "*/bin/*"
    - "*/obj/*"
    - "*/test-fixtures/*"

graph:
  invalidation: git

db:
  sproc_prefixes:
    - "sp_"
    - "usp_"
    - "proc_"
```

### CLI overrides

For one-off runs, just pass flags. They override everything.

```bash
scatter --target-project ./MyLib/MyLib.csproj --search-scope . --max-depth 4
```

## Environment Variables

| Variable | What it does |
|----------|-------------|
| `GOOGLE_API_KEY` | Google API key for the Gemini provider. Used when no key is provided via CLI flag or config file. |
| `WEX_AI_API_KEY` | API key for the WEX AI Platform provider. |
| `WEX_AI_ENDPOINT` | WEX AI Platform endpoint URL (default: `https://ai.wexinc.com`). |
| `SCATTER_DEFAULT_PROVIDER` | Override the default AI provider (`gemini` or `wex`). |

## AI Provider Setup

You only need an API key for AI features: `--summarize-consumers`, `--enable-hybrid-git`, `--sow`, and `--sow-file`. All other Scatter functionality works without one.

### Google Gemini (Current Default)

Three ways to provide the API key (simplest first, highest-precedence last):

1. **Environment variable**: `export GOOGLE_API_KEY=YOUR_KEY` -- set once, works everywhere
2. **Config file**: Set in `~/.scatter/config.yaml` or `.scatter.yaml` under `ai.credentials.gemini.api_key`
3. **CLI flag**: `--google-api-key YOUR_KEY` -- highest priority, useful for CI/CD or one-off runs

### WEX AI Platform (Coming Soon)

The WEX AI Platform provider is stubbed and ready for integration. Once the API contract is finalized, it will become the default provider. Configure it the same way:

1. **Environment variable**: `export WEX_AI_API_KEY=YOUR_KEY`
2. **Config file**: `ai.credentials.wex.api_key` in config YAML
3. **CLI flag**: `--wex-api-key YOUR_KEY`

To switch providers: set `ai.default_provider: wex` in your config or `export SCATTER_DEFAULT_PROVIDER=wex`.

## Full .scatter.yaml Schema

```yaml
# AI provider settings
ai:
  default_provider: gemini              # "gemini" (current) or "wex" (coming soon)
  gemini_model: gemini-2.0-flash        # Gemini model name
  wex_model: default                    # WEX AI Platform model name
  task_overrides:                       # Route specific AI tasks to different providers
    risk_assessment: gemini             # e.g., keep risk assessment on Gemini
  credentials:
    gemini:
      api_key: your-key-here            # Or use env var / CLI flag instead
    wex:
      api_key: your-wex-key-here        # Or use WEX_AI_API_KEY env var

# Search behavior
search:
  max_depth: 2                          # Transitive tracing depth for impact analysis
  exclude_patterns:                     # Glob patterns to skip during file discovery
    - "*/bin/*"                         # NOTE: this REPLACES the defaults entirely.
    - "*/obj/*"                         # If you add custom patterns, re-list bin/obj
    - "*/node_modules/*"               # or they will no longer be excluded

# Parallel processing
multiprocessing:
  disabled: false                       # Set true to force sequential execution
  max_workers: 14                       # Upper bound on worker processes
  chunk_size: 75                        # Directories per worker batch

# Dependency graph
graph:
  cache_dir: null                       # Override default .scatter/ cache location
  rebuild: false                        # Force full rebuild (ignore cache)
  invalidation: git                     # "git" (default) or "mtime" fallback
  coupling_weights:                     # Override edge type weights for coupling score
    project_reference: 1.0
    namespace_usage: 0.5
    type_usage: 0.3
    sproc_shared: 0.8

# Analysis behavior
analysis:
  parser_mode: regex                    # "regex" (default) or "hybrid"
                                        # hybrid uses tree-sitter AST to filter
                                        # false positives in comments/strings
  exclude_test_projects: true           # Filter test projects from blast radius (default: true)
  test_project_patterns:                # Glob patterns for test project names (fnmatchcase)
    - "*.Tests"                         # These are the defaults — only set this if you need
    - "*.Tests.*"                       # to override them. Setting this REPLACES the defaults.
    - "*.UnitTests"
    - "*.IntegrationTests"
    - "*.TestUtils"
    - "*.TestHelpers"
    - "*.Benchmarks"
    - "*.Specs"
    - "*PostDeployTests"

# Database dependency scanning
db:
  sproc_prefixes:                       # Prefixes that identify stored procedures
    - "sp_"
    - "usp_"
  include_db_edges: true                # Add sproc_shared edges to the graph
```

## Pipeline Mapping

Map consumer projects to their CI/CD pipelines using `--pipeline-csv`:

```bash
# Try it with the included example CSV
scatter --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv examples/pipeline_to_app_mapping.csv
```

The CSV needs at least two columns: `pipeline_name` and `app_name`. Scatter resolves consumer projects to pipeline names using a layered matching strategy. For each consumer, it builds a probe list (solution stems first, then the project name) and tries four strategies in order:

| Priority | Strategy | Example |
|----------|----------|---------|
| 1 | Exact match | `"GalaxyWorks.Api"` matches key `"GalaxyWorks.Api"` |
| 2 | Case-insensitive | `"galaxyworks.api"` matches key `"GalaxyWorks.Api"` |
| 3 | Suffix-stripped | `"Auth.Service"` strips `.Service`, matches key `"Auth"` |
| 4 | Prefix match | `"MyApp.Data.Migrations"` matches key `"MyApp.Data"` (longest key wins) |

Strippable suffixes include `.Service`, `.Api`, `.Web`, `.Host`, `.Worker`, `.Client`, `.Core`, `.Console`, `.WebApi`, `.IntegrationTests`, `.UnitTests`, `.Shared`, `.Server`, and `.App`. The first match wins, so exact matches are never overridden by fuzzy ones. Pipeline names then appear in every output format.

The full schema produced by `tools/generate_pipeline_csv.py` is:

```
pipeline_name,app_name,assembly_name,source
```

- `assembly_name` — the DLL name from `web.config` or `exe.config` (may differ from `app_name`; metadata, not used by scatter at runtime)
- `source` — how the mapping was derived: `host_json`, `web_config`, `exe_config`, `heuristic`, or `manual`

For backward compatibility, scatter also accepts the old column names (`Application Name` and `Pipeline Name`).

### Manual overrides

If `examples/pipeline_manual_overrides.csv` exists in the same directory as the pipeline CSV, scatter loads it automatically. Manual entries use the same schema with `source=manual` and take precedence over crawled entries on conflict. Use this for deployed apps the generator can't resolve from the config repo.

The repo includes a working example at `examples/pipeline_to_app_mapping.csv` that maps the sample projects. For real codebases, generate the CSV from your app-config repo using `tools/generate_pipeline_csv.py` (see [Development](reference/development.md) for details).

## Multiprocessing Tuning

| Flag | Default | What it does |
|------|---------|-------------|
| `--disable-multiprocessing` | `false` | Force sequential processing. Useful for debugging or environments where fork is problematic. |
| `--max-workers` | `14` | Upper bound on worker processes. Actual count may be lower (see adaptive scaling below). |
| `--chunk-size` | `75` | Number of directories processed per worker batch during file discovery. |
| `--cs-analysis-chunk-size` | `50` | Number of `.cs` files per worker batch for content analysis. |
| `--csproj-analysis-chunk-size` | `25` | Number of `.csproj` files per worker batch for XML parsing. |

### Adaptive Worker Scaling

Scatter does not blindly spin up `--max-workers` processes. It scales based on workload:

- Less than 200 files: 4 workers
- 200 to 999 files: 8 workers
- 1000+ files: up to `--max-workers`

This prevents the overhead of process creation from exceeding the work being parallelized. For the sample projects (dozens of files), you will see 4 workers. For a 500-project monolith, you will see the full pool.

## Graph Behavior

| Flag | Effect |
|------|--------|
| *(default)* | Auto-build graph on first run, auto-load from cache on subsequent runs, incremental patching via git diff |
| `--no-graph` | Skip all graph operations -- no build, no load, no enrichment. Pure filesystem analysis. |
| `--rebuild-graph` | Force a full graph rebuild, ignoring the existing cache. Useful after major refactors. |
| `--graph` | Dedicated graph analysis mode. Builds graph, computes coupling metrics, detects cycles, identifies domain clusters. |
| `--graph-metrics` | Explicitly request graph enrichment. Redundant now -- enrichment happens automatically when a cache exists. |

> **How this works:** Configuration merging, adaptive scaling, and graph caching are handled by the config and graph engine subsystems. See [Architecture Overview](reference/architecture.md) for details.
