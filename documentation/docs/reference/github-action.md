# GitHub Action — PR Impact Comments

Scatter can automatically comment on pull requests with an impact analysis
report. When a PR touches `.cs` or `.csproj` files, the workflow runs
scatter's branch analysis and posts the blast radius as a PR comment.

No marketplace action to install. No org approvals. One YAML file.

## Setup

Copy the workflow template into your .NET repo:

```bash
# From the scatter repo
cp tools/github-action/scatter-impact.yml \
   /path/to/your-dotnet-repo/.github/workflows/
```

Push, open a PR, and scatter will comment with the impact report.

## How It Works

```
PR opened/updated
  → GitHub Actions triggers on .cs/.csproj/.sln changes
  → Clones scatter, installs via uv (~30s)
  → Runs: scatter --branch-name <pr-branch> --output-format markdown
  → Posts markdown report as PR comment
  → On subsequent pushes, updates the same comment
```

The workflow uses `--branch-name` mode, which:

1. Diffs the PR branch against the base branch
2. Extracts C# type declarations from changed files
3. Finds consuming projects via the filter pipeline
4. Generates a markdown impact report

## What the Comment Contains

- **Summary** with risk, complexity, consumer count
- **Blast Radius** tree view showing affected projects
- **Affected Projects** table with confidence, depth, risk
- **Next Steps** based on risk level

If a `GOOGLE_API_KEY` secret is configured, the report also includes
AI-enriched risk ratings, coupling narratives, and an executive summary.
Without an API key, you still get the full blast radius tree.

## Optional Configuration

### AI Enrichment

Add a `GOOGLE_API_KEY` repository secret (Settings > Secrets > Actions) for:

- Per-target risk ratings with justifications
- Coupling narratives explaining dependency vectors
- Complexity and effort estimates
- Executive summary paragraph

### Pin Scatter Version

Add a `SCATTER_REF` repository variable (Settings > Variables > Actions)
with a branch name, tag, or commit SHA. Defaults to `main`.

### Project Settings

Add a `.scatter.yaml` to your repo root. See [Configuration](../configuration.md)
for all options.

### Graph Caching

For large repos, cache the dependency graph between runs:

```yaml
- name: Cache scatter graph
  uses: actions/cache@v4
  with:
    path: .scatter/
    key: scatter-graph-${{ hashFiles('**/*.csproj') }}
```

## Permissions

Only built-in GitHub permissions:

| Permission | Why |
|-----------|-----|
| `contents: read` | Checkout the repo |
| `pull-requests: write` | Post/update the PR comment |

No marketplace actions, no Docker, no additional tokens.

## Full Template Reference

The complete workflow template with all options is at
[`tools/github-action/scatter-impact.yml`](https://github.com/mat-mathews/wex_scatter/blob/main/tools/github-action/scatter-impact.yml).

See [`tools/github-action/README.md`](https://github.com/mat-mathews/wex_scatter/blob/main/tools/github-action/README.md)
for troubleshooting and advanced configuration.
