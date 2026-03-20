---
name: scatter-sproc
description: >
  Find all .NET projects that reference a specific stored procedure.
  Use when asked "who calls this sproc?", "what uses sp_X?", "find
  references to stored procedure X", or "which projects call this
  database procedure?".
disable-model-invocation: true
argument-hint: [stored-procedure-name] [search-scope-path]
---

Run scatter in stored procedure mode to find all projects referencing a specific sproc.

## Steps

1. Parse arguments:
   - First argument: stored procedure name (required, e.g., `dbo.sp_InsertPortalConfiguration` or `sp_InsertPortalConfiguration`)
   - Second argument: search scope directory (default: current working directory)
2. Run the analysis and capture the JSON output from stdout:
   ```bash
   python -m scatter --stored-procedure "$SPROC_NAME" --search-scope "$SEARCH_SCOPE" --output-format json --output-file /tmp/scatter_sproc_$$.json
   ```
   Optional flags:
   - `--pipeline-csv path/to/mapping.csv` — map consumers to CI/CD pipelines
   - `--sproc-regex-pattern "PATTERN"` — custom regex if the default pattern doesn't match
3. Read the output file, then clean up
4. Summarize for the user:
   - **Consumer count**: how many projects reference this stored procedure
   - **Consumer list**: project name, path, pipeline, and solution membership
   - **Filter pipeline**: show the narrowing from all projects to sproc consumers
   - **Graph metrics**: coupling data if available (loaded automatically from cache)

## Output guidance

- Sproc names can include schema prefix (dbo.) or not — scatter handles both
- If zero consumers found, suggest checking the exact sproc name spelling
- Mention which pipelines need testing if pipeline mappings exist
- If the sproc appears in multiple projects, that's a shared database coupling point — flag it

## If the command fails

- If the search scope path does not exist, ask the user for the correct path
- If zero consumers found, verify sproc name spelling and try with/without schema prefix
- If scatter is not installed, suggest: `pip install -r requirements.txt` or `uv sync`
