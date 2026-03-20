---
name: scatter-graph
description: >
  Analyze .NET dependency graph health. Computes coupling metrics, detects
  dependency cycles, identifies domain clusters, and produces a health
  dashboard with observations. Use when asked about project architecture,
  coupling scores, dependency health, cycles, domain boundaries, "what's
  coupled to what?", "are there circular dependencies?", or "how healthy
  is the codebase?"
argument-hint: [search-scope-path]
---

Run scatter in dependency graph mode and interpret the results.

## Steps

1. Determine the search scope path from `$ARGUMENTS` (default: current working directory)
2. Run the analysis (JSON output requires a file):
   ```bash
   python -m scatter --graph --include-db --search-scope "$SEARCH_SCOPE" --output-format json --output-file /tmp/scatter_graph_$$.json
   ```
3. Read the output file, then clean up
4. Summarize for the user:
   - **Health dashboard**: list observations (warnings, info) with severity
   - **Top coupled projects**: show the top 5 by coupling score with fan-in/fan-out
   - **Cycles**: list any circular dependencies found (project names in each cycle)
   - **Domain clusters**: show cluster names, project counts, and extraction feasibility
   - **Summary stats**: total projects, edges, avg coupling score

## Output guidance

- Lead with the health observations — these are the actionable findings
- If the user asked about a specific project, focus on that project's metrics
- If cycles exist, emphasize them — they block independent deployment
- Use the coupling score to identify projects that are most entangled
- Offer to generate a Mermaid diagram if the user wants a visual

## If the command fails

- If scatter is not installed, suggest: `pip install -r requirements.txt` or `uv sync`
- If the search scope path does not exist, ask the user for the correct path
- If the search scope has no .csproj files, the graph will be empty — tell the user
- First run builds the graph cache (~30-60s for large repos); subsequent runs are <2s
- If the graph cache is corrupted, suggest `--rebuild-graph` to force a fresh build
