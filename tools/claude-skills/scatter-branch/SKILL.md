---
name: scatter-branch
description: >
  Analyze what a Git feature branch changed and find all consuming projects
  affected by those changes. Use when asked "what did my branch touch?",
  "what's the impact of my branch?", "who consumes what I changed?",
  or "analyze changes on branch X".
disable-model-invocation: true
argument-hint: [branch-name] [repo-path]
---

Run scatter in git branch analysis mode to find consumers affected by branch changes.

## Steps

1. Parse arguments:
   - First argument: feature branch name (required, e.g., `feature/new-widget`)
   - Second argument: repository path (default: current working directory)
2. Run the analysis and capture the JSON output from stdout:
   ```bash
   python -m scatter --branch-name "$BRANCH_NAME" --repo-path "$REPO_PATH" --output-format json --output-file /tmp/scatter_branch_$$.json
   ```
   Optional flags:
   - `--base-branch main` — base branch to compare against (default: main)
   - `--class-name ClassName` — narrow analysis to a specific changed type
   - `--search-scope path` — search for consumers in a different directory than the repo
   - `--pipeline-csv path/to/mapping.csv` — map consumers to CI/CD pipelines
   - `--enable-hybrid-git` — use LLM-enhanced diff analysis for more precise symbol extraction (requires Gemini API key)
3. Read the output file, then clean up
4. Summarize for the user:
   - **Changed files**: which .cs files were modified on the branch
   - **Types affected**: classes, interfaces, enums extracted from changes
   - **Consumer count**: how many projects consume the changed types
   - **Consumer list**: project name, path, pipeline, and solution
   - **Filter pipeline**: how results were narrowed at each stage

## Output guidance

- Lead with what changed (files and types), then who's affected
- If the branch has many changed files, focus on the types with the most consumers
- Mention which pipelines need testing if pipeline mappings exist
- If zero consumers found, it may mean the changes are internal to the project (no external impact)
- The branch must exist in the local repo — remind the user to fetch if needed

## If the command fails

- If the branch does not exist locally, suggest: `git fetch origin && git branch -a | grep BRANCH`
- If the repo path is not a git repository, ask the user for the correct path
- If the base branch doesn't exist, suggest specifying `--base-branch`
- If scatter is not installed, suggest: `pip install -r requirements.txt` or `uv sync`
