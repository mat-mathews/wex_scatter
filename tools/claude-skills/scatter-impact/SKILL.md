---
name: scatter-impact
description: >
  Analyze the blast radius of a proposed change described in natural language.
  Accepts a Statement of Work (SOW), change request, or plain description of
  what's being modified. Use when asked "what's the blast radius of X?",
  "what would be affected if we change X?", "scope this work request",
  "analyze this SOW/CSE", "what's the impact of changing X?", or "how
  many projects does this touch?"
argument-hint: [description-or-path-to-sow-file]
---

Run scatter in impact analysis mode to assess the blast radius of a proposed change.

## Steps

1. Determine input type:
   - If the argument looks like a file path (ends in .txt, .md, or exists on disk), use `--sow-file`
   - Otherwise, write the description to a temp file and use `--sow-file` to avoid shell escaping issues:
     ```bash
     echo 'DESCRIPTION TEXT HERE' > /tmp/scatter_sow_input.txt
     ```
2. A search scope is required. Ask the user if not obvious from context.
3. Run the analysis (JSON output requires a file):
   ```bash
   python -m scatter --sow-file "$SOW_FILE" --search-scope "$SEARCH_SCOPE" --output-format json --output-file /tmp/scatter_impact_$$.json
   ```
   Optional flags:
   - `--google-api-key KEY` or set `GOOGLE_API_KEY` env var — enables AI enrichment (risk assessment, coupling narrative, complexity estimate)
   - `--sow-min-confidence 0.3` — filter out low-confidence targets (default: 0.3)
   - `--pipeline-csv path/to/mapping.csv` — map consumers to CI/CD pipelines
4. Read the output file, then clean up
5. Summarize for the user:
   - **Targets identified**: what code artifacts the SOW maps to, with confidence scores and match evidence
   - **Target quality**: clear/moderate/vague assessment with avg confidence
   - **Blast radius**: direct and transitive consumers shown as a tree
   - **Risk assessment**: overall risk rating with justification (if AI enrichment enabled)
   - **Complexity estimate**: effort estimate and complexity rating (if AI enrichment enabled)
   - **Pipelines affected**: which CI/CD pipelines need testing

## Output guidance

- Lead with target quality — if it's "vague", warn that results may be incomplete
- Show the blast radius tree (targets -> direct consumers -> transitive consumers)
- Highlight high-risk consumers and explain why they're high risk
- If AI enrichment is not enabled (no API key), note that risk/complexity ratings are unavailable
- Suggest `--dump-index` if the user wants to see what artifacts scatter knows about

## If targets are wrong or missing

- The user can refine by being more specific in the description
- Use `python -m scatter --dump-index --search-scope .` to see the codebase index
- Adjust `--sow-min-confidence` to include/exclude borderline targets

## If the command fails

- If the search scope path does not exist, ask the user for the correct path
- If the Gemini API key is missing or expired, scatter still runs but without AI enrichment — inform the user
- If scatter is not installed, suggest: `pip install -r requirements.txt` or `uv sync`
- If the graph cache is corrupted, suggest `--rebuild-graph` with a separate `--graph` run first
