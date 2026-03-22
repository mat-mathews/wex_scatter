# Scatter GitHub Action — PR Impact Comments

Drop a single workflow file into your .NET repo and every PR gets an automatic
impact analysis comment showing which projects are affected by the change.

## Quick Setup

1. Copy `scatter-impact.yml` into your repo:

```bash
mkdir -p .github/workflows
cp scatter-impact.yml .github/workflows/
```

2. Push. Open a PR that touches `.cs` or `.csproj` files. Scatter will comment
   with the impact report.

That's it. No marketplace action, no org installation, no Docker.

## What It Does

On every PR to `main` that touches `.cs`, `.csproj`, or `.sln` files:

1. Clones scatter and installs it via uv (~30s)
2. Runs `scatter --branch-name <pr-branch>` against your repo
3. Posts the markdown impact report as a PR comment
4. On subsequent pushes to the same PR, updates the existing comment

## What You See

The PR comment contains:

- **Summary** — risk level, complexity, consumer count
- **Targets** — which projects/types changed, with confidence
- **Blast Radius** — tree view of affected consumers
- **Affected Projects** — table with depth, risk, pipelines
- **Next Steps** — template-driven guidance based on risk level

## Configuration

### AI-Enriched Reports (Optional)

Set a `GOOGLE_API_KEY` repository secret to enable AI-powered features:
- Risk ratings and justifications per target
- Coupling narratives explaining how consumers depend on the target
- Complexity estimates with effort ranges
- Executive summary narrative

Without an API key, you still get the full blast radius tree and consumer
tracing — just without AI enrichment.

### Pin Scatter Version (Optional)

By default the workflow clones `main`. To pin a specific version:

1. Go to your repo Settings > Variables > Actions
2. Add a variable `SCATTER_REF` with a branch, tag, or commit SHA

### Project Configuration (Optional)

Add a `.scatter.yaml` to your repo root for project-specific settings:

```yaml
ai:
  provider: gemini
  model: gemini-2.0-flash

search:
  exclude_patterns:
    - "**/test/**"
    - "**/obj/**"
    - "**/bin/**"

graph:
  auto_build: true
```

See [Configuration docs](../../documentation/docs/configuration.md) for all options.

### Path Filters

The workflow only runs when `.cs`, `.csproj`, or `.sln` files change. Edit the
`paths:` filter in the workflow to match your repo structure:

```yaml
paths:
  - 'src/**/*.cs'
  - 'src/**/*.csproj'
```

### Skip Draft PRs

Draft PRs are skipped by default (`if: github.event.pull_request.draft == false`).
Remove this condition to analyze drafts too.

## Permissions

The workflow uses only built-in GitHub permissions:

| Permission | Why |
|-----------|-----|
| `contents: read` | Checkout the repo |
| `pull-requests: write` | Post/update the PR comment |

No additional tokens, apps, or marketplace actions required. The default
`GITHUB_TOKEN` handles everything.

## Troubleshooting

**"Scatter did not produce an impact report"**

- The PR may not touch any `.cs` files that affect dependency relationships
- Check the workflow logs for the stderr output
- Verify the repo has `.csproj` files discoverable from the root

**Comment not appearing**

- Verify `pull-requests: write` is in the workflow permissions
- Check if your org restricts `GITHUB_TOKEN` permissions (Settings > Actions > General > Workflow permissions)

**Slow runs**

- First run clones and installs scatter (~30s). Subsequent runs benefit from uv caching.
- Graph cache is not persisted between runs. For large repos, consider caching `.scatter/` via `actions/cache`.

## Caching the Graph (Advanced)

For large .NET repos where graph build takes >30 seconds, cache the scatter
graph between runs:

```yaml
      - name: Cache scatter graph
        uses: actions/cache@v4
        with:
          path: .scatter/
          key: scatter-graph-${{ hashFiles('**/*.csproj') }}
```

Add this step before "Run impact analysis" in the workflow.
