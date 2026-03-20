---
name: scatter-consumers
description: >
  Find all projects that consume a specific .NET project's types, classes,
  or methods. Use when asked "who uses X?", "what depends on X?", "what
  would break if I changed X?", "find consumers of project X", "what
  references this project?", or "show me the dependents of X".
argument-hint: [target-project-path] [search-scope-path]
---

Run scatter in target-project mode to find consumers of a specific .NET project.

## Steps

1. Parse arguments:
   - First argument: path to the target .csproj file (required)
   - Second argument: search scope directory (default: current working directory)
2. Run the analysis (JSON output requires a file):
   ```bash
   python -m scatter --target-project "$TARGET_PROJECT" --search-scope "$SEARCH_SCOPE" --output-format json --output-file /tmp/scatter_consumers_$$.json
   ```
   Optional filters (add if the user specified them):
   - `--class-name ClassName` — narrow to consumers of a specific type
   - `--method-name MethodName` — narrow to consumers of a specific method (requires --class-name)
   - `--pipeline-csv path/to/mapping.csv` — map consumers to CI/CD pipelines
3. Read the output file, then clean up
4. Summarize for the user:
   - **Consumer count**: how many projects consume the target
   - **Filter pipeline**: show what was scanned and how results were narrowed (e.g., "200 projects scanned -> 12 with project refs -> 8 using namespace -> 4 using class")
   - **Consumer list**: project name, path, and pipeline (if mapped)
   - **Solutions**: which .sln files contain each consumer
   - **Graph metrics**: coupling score, fan-in/out if available

## Finding the .csproj path

If the user gives a project name instead of a path, help them find it:
```bash
find . -name "*ProjectName*.csproj" -type f
```

## Output guidance

- The filter pipeline is valuable — show it so the user understands the narrowing
- If zero consumers are found, show the filter pipeline to help debug (where did results drop off?)
- Group consumers by solution if solution data is available
- Mention which pipelines would need testing if pipeline mappings exist

## If the command fails

- If the .csproj path does not exist, help the user find it with `find`
- If the search scope path does not exist, ask the user for the correct path
- If zero consumers are found, check: is the project new? Is the search scope too narrow?
- If scatter is not installed, suggest: `pip install -r requirements.txt` or `uv sync`
