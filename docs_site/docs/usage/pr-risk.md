# PR Risk Scoring

You open a pull request. How risky is it? Not "does the code compile" — that's CI's job. The question is: if this change has a subtle bug, how far does the damage travel?

Scatter's `--pr-risk` mode answers that by scoring your branch diff across 7 risk dimensions, using the same graph-derived engine that powers SOW scoping and impact analysis.

## Basic usage

```bash
scatter --branch-name feature/refactor-data --pr-risk --search-scope .
```

```
============================================================
  PR Risk: RED (0.80)
============================================================
  Branch: feature/refactor-data (vs main)
  Changed: 2 type(s) across 1 project(s)

  Type                           Kind         Change     Project
  ────────────────────────────── ──────────── ────────── ────────────────────
  PortalDataService              class        modified   GalaxyWorks.Data
  PortalConfiguration            class        modified   GalaxyWorks.Data

  Dimension                     Score  Severity
  ───────────────────────────── ─────  ──────────
  Structural coupling            0.65  high
  Instability                    0.00  low
  Cycle entanglement             0.00  low
  Database coupling              0.72  high
  Blast radius                   0.80  critical
  Domain boundary                0.30  medium
  Change surface                 0.70  high

  Risk Factors:
    • 7 direct consumers affected
    • shared sproc sp_InsertPortalConfiguration used by 3 projects
    • stable core project (instability 0.00) — many dependents

  Consumers: 7 direct, 2 transitive (8 unique)

  Completed in 142ms
```

The score is deterministic — same branch against the same dependency graph produces the same number. No AI involved in the scoring, just graph topology. If the graph changes between runs (someone merges a PR that adds a project reference), the score may shift because the inputs changed.

## How it works

1. **Diff extraction** — Scatter diffs your branch against `main` (or `--base-branch`) and identifies changed `.cs` files
2. **Type extraction** — Regex (or hybrid AST) identifies which types were added, modified, or deleted
3. **Consumer detection** — For each changed type's owning project, find all consuming projects via the dependency graph
4. **Risk scoring** — The risk engine scores each changed project across 7 dimensions (see [Risk Engine](risk-engine.md))
5. **Aggregation** — Multiple projects aggregate into a single composite score using weighted-max

The whole pipeline runs in under 200ms on a cached graph.

## For PR comments

The real power is in CI. Add `--output-format markdown --collapsible` and the output is ready to paste (or auto-post) as a PR comment:

```bash
scatter --branch-name $BRANCH --pr-risk --search-scope . \
  --output-format markdown --collapsible
```

This produces markdown with collapsible `<details>` sections — a compact summary at the top, expandable dimension table and consumer list below. Perfect for GitHub PR comments where you want the risk level visible at a glance without overwhelming the reviewer.

## GitHub Action

The repo ships with a workflow template at `tools/github-action/scatter-pr-risk.yml`. Drop it into `.github/workflows/` and every PR gets an automatic risk comment:

```yaml
# .github/workflows/scatter-pr-risk.yml
name: PR Risk Analysis
on:
  pull_request:
    branches: [main]

jobs:
  risk:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # full history for branch comparison

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install scatter
        run: pip install .

      - name: Run risk analysis
        run: |
          scatter \
            --branch-name ${{ github.head_ref }} \
            --base-branch ${{ github.base_ref }} \
            --pr-risk \
            --search-scope . \
            --output-format markdown \
            --collapsible \
            --output-file risk-comment.md

      - name: Post PR comment
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          path: risk-comment.md
```

The sticky comment updates on each push — no comment spam.

!!! tip "Cache the graph for faster CI"
    The first run on a fresh checkout builds the dependency graph from scratch (a few seconds). Cache the `.scatter/` directory between builds to skip this on subsequent runs. The full template at `tools/github-action/scatter-pr-risk.yml` includes cache restore/save steps.

## Prediction logging

Every `--pr-risk` run writes a prediction record to `.scatter/predictions.jsonl` — branch name, composite score, dimension breakdown, timestamp. The purpose: over time, you can compare predictions against actual outcomes. Did the RED PRs actually cause incidents? Did GREEN PRs sail through? That feedback loop is how you calibrate whether the thresholds are right for your codebase.

Nobody reviews these automatically today — it's a dataset for future analysis. The file grows by ~500 bytes per PR. Disable with `--no-prediction-log` in ephemeral CI containers where the file won't persist anyway.

## Output formats

| Format | Flag | Use case |
|--------|------|----------|
| Console | (default) | Quick check from your terminal |
| JSON | `--output-format json --output-file risk.json` | Feed into dashboards, aggregate across repos |
| Markdown | `--output-format markdown` | PR comments, Confluence, Slack |
| Markdown (collapsible) | `--output-format markdown --collapsible` | GitHub PR comments with expandable details |

## Reading the output

**Composite score** — a single number from 0.0 to 1.0. This is the weighted maximum across all dimensions, not an average. A project with 0.9 in one dimension and 0.0 everywhere else scores 0.9.

**Risk level** — GREEN (< 0.4), YELLOW (0.4–0.7), RED (≥ 0.7). See [Risk Engine](risk-engine.md) for the full model.

**Changed types table** — every C# type (class, interface, struct, enum, record) that was added, modified, or deleted in the diff. This is what triggers the analysis.

**Dimension table** — scores and severity for each of the 7 risk dimensions. Dimensions marked "N/A" lack data (e.g., database coupling when `--include-db` wasn't used during graph build).

**Risk factors** — the top 3 human-readable explanations of what's driving the score. These come from the highest-scoring dimensions.

**Consumer summary** — how many projects are affected, split into direct (one hop) and transitive (two+ hops).

---

!!! tip "Combine with hybrid type extraction"
    Add `--enable-hybrid-git` to use LLM-enhanced diff analysis. This filters changed types to only those whose body or signature actually changed — not every type in a modified file. Fewer false positives means more accurate risk scores. Requires a Gemini API key.
