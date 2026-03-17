# Usage Guide

## CLI Reference

```bash
python scatter.py [MODE] [OPTIONS]
```

## Analysis Modes

### Git Branch Analysis

```bash
python scatter.py --branch-name <branch> --repo-path <path> [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--branch-name` | Feature branch to analyze |
| `--repo-path` | Path to the Git repository |
| `--base-branch` | Base branch for comparison (default: auto-detected) |

### Target Project Analysis

```bash
python scatter.py --target-project <csproj> --search-scope <path> [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--target-project` | Path to the `.csproj` file to analyze |
| `--search-scope` | Root directory to search for consumers |

### Stored Procedure Analysis

```bash
python scatter.py --stored-procedure <name> --search-scope <path> [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--stored-procedure` | Stored procedure name (e.g., `dbo.sp_GetUsers`) |
| `--search-scope` | Root directory to search for consumers |

## Output Options

| Flag | Description |
|------|-------------|
| `--output-format` | `console` (default), `json`, `csv`, `markdown` |
| `--output-file` | Write output to a file instead of stdout |
| `--graph-metrics` | Enrich output with dependency graph metrics |

## AI Summarization

Add AI-powered summaries of consuming code:

```bash
python scatter.py \
  --target-project ./MyLib/MyLib.csproj \
  --search-scope . \
  --summarize-consumers \
  --google-api-key YOUR_API_KEY \
  --output-format json \
  --output-file results.json
```

| Flag | Description |
|------|-------------|
| `--summarize-consumers` | Enable AI summarization of consumer files |
| `--google-api-key` | Google Gemini API key |

## Graph Commands

Build and inspect the full dependency graph:

```bash
# Build graph and show metrics
python scatter.py --search-scope . --graph-metrics

# Export graph as Mermaid diagram
python scatter.py --search-scope . --output-format markdown --graph-metrics
```

## Pipeline Mapping

Map consumer projects to CI/CD pipelines:

```bash
python scatter.py \
  --target-project ./MyLib/MyLib.csproj \
  --search-scope . \
  --pipeline-csv pipeline_to_app_mapping.csv
```

| Flag | Description |
|------|-------------|
| `--pipeline-csv` | CSV file mapping projects to pipelines |
| `--batch-config-repo` | Path to batch job config repository for verification |

## Filtering

```bash
python scatter.py \
  --target-project ./MyLib/MyLib.csproj \
  --search-scope . \
  --filter-usage-pattern "DataService" \
  --exclude-pattern "**/test/**"
```

| Flag | Description |
|------|-------------|
| `--filter-usage-pattern` | Only include consumers matching this pattern |
| `--exclude-pattern` | Exclude paths matching this glob |

## Performance Tuning

| Flag | Description |
|------|-------------|
| `--max-workers` | Number of parallel workers (default: CPU count) |
| `--chunk-size` | Files per parallel chunk (default: 50) |
| `--no-cache` | Disable graph caching |
