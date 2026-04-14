# GitHub Actions — PR Impact & Risk Comments

Scatter ships two workflow templates that comment on pull requests automatically. Copy one (or both) into your .NET repo and every PR gets analysis — zero effort from engineers.

No marketplace action to install. No org approvals. One YAML file each.

## Available Workflows

| Template | What it posts | Comment tag |
|----------|-------------|-------------|
| `scatter-impact.yml` | Consumer impact analysis (blast radius tree, affected projects) | `<!-- scatter-impact -->` |
| `scatter-pr-risk.yml` | PR risk scoring (risk level, dimensions, changed types, consumers) | `<!-- scatter-pr-risk -->` |

Both can run side-by-side. They use separate comment tags so they don't overwrite each other. Teams can adopt one or both, migrating at their own pace.

---

## PR Risk Scoring

### Setup

```bash
cp tools/github-action/scatter-pr-risk.yml \
   /path/to/your-dotnet-repo/.github/workflows/
```

Push, open a PR that touches `.cs` or `.csproj` files. Scatter posts a risk comment.

### How It Works

```
PR opened/updated
  → GitHub Actions triggers on .cs/.csproj/.sln changes
  → Restores graph cache (if available)
  → Clones scatter, installs via uv (~30s)
  → Runs: scatter --pr-risk --graph-metrics --collapsible --output-format markdown
  → Posts risk report as PR comment (or fallback on failure)
  → On subsequent pushes, updates the same comment
```

### What the Risk Comment Shows

- **Risk level** — GREEN / YELLOW / RED with composite score (0.00–1.00)
- **Risk dimensions** — change surface, blast radius, coupling, cycle entanglement, instability (each scored independently)
- **Changed types** — collapsible table of added/modified/deleted C# types
- **Consumer impact** — direct and transitive consumer counts
- **Risk factors** — top contributors to the score

When a PR has no C# type changes (e.g., only method body edits), the workflow exits cleanly without posting a comment. Check workflow logs for "No C# type changes detected."

### Graph Caching

The PR risk workflow includes graph caching out of the box:

- **Cache key:** `scatter-graph-${{ hashFiles('**/*.csproj') }}` — invalidates when project structure changes
- **Restore key:** `scatter-graph-` — falls back to any previous cache for incremental rebuild
- **`continue-on-error: true`** — cache misses don't fail the workflow

First run builds the dependency graph (~30-60s for large repos). Subsequent runs hit cache. For small repos (<20 projects), the graph builds in <5s.

### Failure Handling

If scatter crashes, the workflow posts a fallback comment: "Analysis failed — does not block merge" with a link to the workflow logs. Failures are visible but don't block merges.

---

## PR Impact Analysis

### Setup

```bash
cp tools/github-action/scatter-impact.yml \
   /path/to/your-dotnet-repo/.github/workflows/
```

Push, open a PR, and scatter comments with the impact report.

### How It Works

```
PR opened/updated
  → GitHub Actions triggers on .cs/.csproj/.sln changes
  → Clones scatter, installs via uv (~30s)
  → Runs: scatter --branch-name <pr-branch> --output-format markdown
  → Posts markdown report as PR comment
  → On subsequent pushes, updates the same comment
```

### What the Impact Comment Shows

- **Summary** with risk, complexity, consumer count
- **Blast Radius** tree view showing affected projects
- **Affected Projects** table with confidence, depth, risk
- **Next Steps** based on risk level

If a `GOOGLE_API_KEY` secret is configured, the report also includes
AI-enriched risk ratings, coupling narratives, and an executive summary.
Without an API key, you still get the full blast radius tree.

To add graph caching to the impact workflow, insert before "Run impact analysis":

```yaml
- name: Cache scatter graph
  uses: actions/cache@v4
  continue-on-error: true
  with:
    path: .scatter/
    key: scatter-graph-${{ hashFiles('**/*.csproj') }}
    restore-keys: scatter-graph-
```

---

## Common Configuration

### AI Enrichment (Optional)

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

## Permissions

Both workflows use only built-in GitHub permissions:

| Permission | Why |
|-----------|-----|
| `contents: read` | Checkout the repo |
| `pull-requests: write` | Post/update the PR comment |

No marketplace actions, no Docker, no additional tokens.

## Troubleshooting

**Comment not appearing** — Verify `pull-requests: write` is in the workflow permissions. Check if your org restricts `GITHUB_TOKEN` permissions (Settings > Actions > General > Workflow permissions).

**Slow runs** — First run clones and installs scatter (~30s). First graph build adds ~30-60s for large repos. Enable graph caching to avoid rebuilding.

**GitHub Enterprise Server** — The fallback error comment uses `github.server_url` for log links. This works for github.com but may need adjustment for GHES instances.

## Template Reference

- [`tools/github-action/scatter-pr-risk.yml`](https://github.com/mat-mathews/wex_scatter/blob/main/tools/github-action/scatter-pr-risk.yml) — PR risk scoring
- [`tools/github-action/scatter-impact.yml`](https://github.com/mat-mathews/wex_scatter/blob/main/tools/github-action/scatter-impact.yml) — PR impact analysis
- [`tools/github-action/README.md`](https://github.com/mat-mathews/wex_scatter/blob/main/tools/github-action/README.md) — detailed troubleshooting and advanced configuration
