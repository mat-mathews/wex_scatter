# Configuration

Scatter uses a layered configuration system. Settings are resolved in order of precedence:

**CLI flags > repo config > user config > environment variables > defaults**

## Config Files

| Location | Scope |
|----------|-------|
| `.scatter.yaml` | Repository-level (checked into source) |
| `.scatter/config.yaml` | User-level (local to machine) |

## Configuration Reference

### Top-Level

```yaml
max_depth: 3              # Maximum transitive dependency depth
multiprocessing: true      # Enable parallel processing
exclude_patterns:          # Glob patterns to exclude from scanning
  - "**/bin/**"
  - "**/obj/**"
  - "**/test/**"
```

### Graph Settings

```yaml
graph:
  cache_dir: .scatter       # Cache directory for graph data
  rebuild: false            # Force full graph rebuild (ignore cache)
  invalidation: mtime       # Cache invalidation strategy
  coupling_weights:          # Weights for coupling score calculation
    direct: 1.0
    transitive: 0.5
```

### AI Settings

```yaml
ai:
  default_provider: gemini
  gemini_model: gemini-pro
  credentials:
    google_api_key: ${GOOGLE_API_KEY}   # Supports env var interpolation
  task_overrides:
    summarization:
      provider: gemini
```

### Database Scanning

```yaml
db:
  sproc_prefixes:            # Stored procedure prefixes to detect
    - "dbo.sp_"
    - "dbo.usp_"
  include_db_edges: true     # Add DB dependencies to the graph
```

## Environment Variables

| Variable | Maps To |
|----------|---------|
| `GOOGLE_API_KEY` | `ai.credentials.google_api_key` |
| `SCATTER_MAX_WORKERS` | `max_workers` CLI flag |
| `SCATTER_CACHE_DIR` | `graph.cache_dir` |
