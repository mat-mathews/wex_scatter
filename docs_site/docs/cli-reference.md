# CLI Reference

Everything Scatter does starts with a mode flag and a search scope. One mode is required. Everything else is optional.

Run `scatter --help` for the full list with defaults.

## Mode Selection

These are mutually exclusive. Pick exactly one.

| Flag | Mode | What it does |
|------|------|-------------|
| `--branch-name NAME` | Git Branch Analysis | Extract type declarations from changed files on a feature branch, find consuming projects |
| `--target-project PATH` | Target Project Analysis | Find all projects that reference and use a specific `.csproj` |
| `--stored-procedure NAME` | Stored Procedure Analysis | Find C# projects referencing a sproc, then trace their consumers |
| `--sow DESCRIPTION` | Impact Analysis | Natural language work request -- AI parses it, traces transitive blast radius, rates risk |
| `--sow-file FILE` | Impact Analysis (from file) | Same as `--sow` but reads the work request from a file |
| `--graph` | Dependency Graph Analysis | Build full graph, compute coupling metrics, detect cycles, identify domain clusters |

## Common Options

These work with any mode (unless noted).

| Flag | Default | Description |
|------|---------|-------------|
| `--search-scope DIR` | Repo path (git mode) or required | Root directory to search for consuming projects |
| `--output-format FORMAT` | `console` | One of: `console`, `csv`, `json`, `markdown`, `mermaid`, `pipelines` |
| `--output-file PATH` | None | Path to write output file. Required for `csv` and `json`. `markdown` and `pipelines` print to stdout if omitted. `mermaid` is only valid in `--graph` mode. |
| `--class-name NAME` | None | Filter: only include consumers that use this specific type |
| `--method-name NAME` | None | Filter: only include consumers that call this method. Requires `--class-name`. |
| `--parser-mode MODE` | `regex` | Parser mode: `regex` (default) or `hybrid`. Hybrid uses tree-sitter AST to filter false positives in comments and string literals during class/method filtering (stages 4-5). Requires `tree-sitter` and `tree-sitter-c-sharp` (`uv sync --extra ast`). Falls back to regex if not installed. |
| `--max-depth N` | 2 | Maximum transitive tracing depth for impact analysis |
| `--sow-min-confidence N` | 0.3 | Minimum confidence threshold for SOW-extracted targets. Targets below this are excluded with a log message. |
| `--scope-estimate` | false | Generate structured effort estimate with confidence bands. Requires `--sow` or `--sow-file`. Adds an effort breakdown table (investigation, implementation, testing, integration risk, database migration) with min/max ranges. See [SOW Scoping](usage/scoping.md). |
| `--dump-index` | false | Build the dependency graph, print the codebase index to stdout, and exit. Requires `--search-scope`. Useful for inspecting what the LLM sees during `--sow` mode. |
| `--no-graph` | false | Skip all graph operations (build, load, enrichment) |
| `--rebuild-graph` | false | Force full graph rebuild, ignoring cache |
| `--include-graph-topology` | false | Include raw graph nodes/edges in JSON output. Omitted by default to keep file size down. |
| `--include-db` | false | Include database dependency scanning (sprocs, EF models, direct SQL) in `--graph` mode |
| `--pipeline-csv PATH` | None | Path to CSV mapping app names to pipeline names. Accepts both new schema (`pipeline_name`, `app_name`) and old (`Pipeline Name`, `Application Name`). If a `pipeline_manual_overrides.csv` exists in the same directory, it is loaded automatically and takes precedence. See `examples/pipeline_to_app_mapping.csv`. |
| `--app-config-path PATH` | None | Path to app-config repo for batch job name resolution |
| `--target-namespace NS` | Auto-derived | Override namespace detection for the target project |
| `-v`, `--verbose` | false | Enable DEBUG-level logging. Shows every step of the analysis pipeline. |

## Git Branch Analysis Options

Only relevant with `--branch-name`.

| Flag | Default | Description |
|------|---------|-------------|
| `-r`, `--repo-path PATH` | `.` (current directory) | Path to the Git repository |
| `-b`, `--base-branch NAME` | `main` | Base branch to compare against for diff extraction |
| `--enable-hybrid-git` | false | Use AI-enhanced diff analysis for more precise symbol extraction. Only flags types whose body/signature actually changed, not every type in the file. Requires a Gemini API key. |
| `--pr-risk` | false | Output PR risk analysis instead of consumer table. Scores changes across 6 dimensions, outputs GREEN/YELLOW/RED with composite score. Supports `console`, `json`, and `markdown` output formats. |
| `--collapsible` | false | Wrap detail sections in collapsible `<details>` tags. Only affects `--pr-risk --output-format markdown`. Ideal for PR comments where you want a compact summary with expandable details. |
| `--no-prediction-log` | false | Disable writing prediction records to `.scatter/predictions.jsonl` after `--pr-risk` analysis. |

## Stored Procedure Options

Only relevant with `--stored-procedure`.

| Flag | Default | Description |
|------|---------|-------------|
| `--sproc-regex-pattern PATTERN` | Built-in default | Custom Python regex to find sproc names in C# files. Use `{sproc_name_placeholder}` where the escaped sproc name should be inserted. |

## AI / Summarization Options

These require a Google API key (via `--google-api-key`, config file, or `GOOGLE_API_KEY` env var).

| Flag | Default | Description |
|------|---------|-------------|
| `--summarize-consumers` | false | Send each relevant consumer `.cs` file to Gemini for a 2-3 sentence summary |
| `--google-api-key KEY` | None / env var | Google API key for Gemini |
| `--gemini-model MODEL` | `gemini-2.0-flash` | Which Gemini model to use |

## Multiprocessing Options

| Flag | Default | Description |
|------|---------|-------------|
| `--disable-multiprocessing` | false | Force sequential execution |
| `--max-workers N` | 14 | Upper bound on worker processes (actual count adapts to workload) |
| `--chunk-size N` | 75 | Directories per worker batch during file discovery |
| `--cs-analysis-chunk-size N` | 50 | `.cs` files per worker batch for content analysis |
| `--csproj-analysis-chunk-size N` | 25 | `.csproj` files per worker batch for XML parsing |

## Output Format Notes

- **`csv`** and **`json`** require `--output-file`. Scatter will error without it.
- **`markdown`** writes to `--output-file` if given, otherwise prints to stdout. Handy for piping into a PR comment.
- **`pipelines`** prints sorted unique pipeline names, one per line. Writes to stdout if `--output-file` is omitted.
- **`mermaid`** outputs a Mermaid dependency diagram. Only valid in `--graph` mode.
- **`console`** is the default. Human-readable, printed to stdout, not designed for parsing.
