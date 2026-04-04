# Scatter GitHub Actions — PR Impact & Risk Comments

Drop a single workflow file into your .NET repo and every PR gets an automatic
analysis comment — either impact analysis, risk scoring, or both.

## Workflows

| File | What it does | Comment tag |
|------|-------------|-------------|
| `scatter-impact.yml` | Consumer impact analysis (blast radius tree) | `<!-- scatter-impact -->` |
| `scatter-pr-risk.yml` | PR risk scoring (risk level, dimensions, changed types) | `<!-- scatter-pr-risk -->` |

Both workflows can run side-by-side on the same repo. They use separate comment
tags so they don't overwrite each other.

## PR Risk Scoring — Quick Setup

1. Copy `scatter-pr-risk.yml` into your repo:

```bash
mkdir -p .github/workflows
cp scatter-pr-risk.yml .github/workflows/
```

2. Push. Open a PR that touches `.cs` or `.csproj` files. Scatter will comment
   with the risk score.

That's it. No marketplace action, no org installation, no Docker.

### What the Risk Comment Shows

- **Risk level** — GREEN / YELLOW / RED with composite score
- **Risk dimensions** — change surface, blast radius, coupling, cycle entanglement, instability
- **Changed types** — collapsible table of added/modified/deleted C# types
- **Consumer impact** — direct and transitive consumer counts
- **Risk factors** — top contributors to the score

When a PR has no C# type changes (e.g., only method body edits), the workflow
exits cleanly without posting a comment. Check the workflow logs for a
"No C# type changes detected" notice. If neither a comment nor a log notice
appears, something broke.

## PR Impact Analysis — Quick Setup

1. Copy `scatter-impact.yml` into your repo:

```bash
mkdir -p .github/workflows
cp scatter-impact.yml .github/workflows/
```

2. Push. Open a PR that touches `.cs` or `.csproj` files. Scatter will comment
   with the impact report.

### What the Impact Comment Shows

- **Summary** — risk level, complexity, consumer count
- **Targets** — which projects/types changed, with confidence
- **Blast Radius** — tree view of affected consumers
- **Affected Projects** — table with depth, risk, pipelines
- **Next Steps** — template-driven guidance based on risk level

## Graph Caching

The PR risk workflow includes graph caching out of the box. The impact workflow
can add it manually.

**How it works:**
- Cache key: `scatter-graph-${{ hashFiles('**/*.csproj') }}` — invalidates when project structure changes
- Restore key: `scatter-graph-` — falls back to any previous graph cache for incremental rebuild
- The cache step uses `continue-on-error: true` so cache misses don't fail the workflow

**Cold-start cost:** First run builds the dependency graph (~30-60s for large
repos). Subsequent runs hit cache and skip the build. For small repos (<20
projects), the graph builds in <5s so caching is less important.

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

Both workflows only run when `.cs`, `.csproj`, or `.sln` files change. Edit the
`paths:` filter to match your repo structure:

```yaml
paths:
  - 'src/**/*.cs'
  - 'src/**/*.csproj'
```

### Skip Draft PRs

Draft PRs are skipped by default (`if: github.event.pull_request.draft == false`).
Remove this condition to analyze drafts too.

## Permissions

Both workflows use only built-in GitHub permissions:

| Permission | Why |
|-----------|-----|
| `contents: read` | Checkout the repo |
| `pull-requests: write` | Post/update the PR comment |

No additional tokens, apps, or marketplace actions required. The default
`GITHUB_TOKEN` handles everything.

## Troubleshooting

### PR Risk

**"Analysis failed — does not block merge"**

- The fallback comment means scatter crashed. Check the workflow logs for the
  stderr output.
- The fallback comment links to the workflow run — click through for details.

**No comment posted (silent)**

- If scatter exits cleanly with no C# type changes, it logs a notice but does
  not post a comment. Check workflow logs for "No C# type changes detected".

**Stale graph cache**

- If you've renamed or moved .csproj files, the cache key changes automatically
  (it hashes all .csproj paths). If you suspect a corrupt cache, delete it via
  GitHub Actions > Caches.

### PR Impact

**"Scatter did not produce an impact report"**

- The PR may not touch any `.cs` files that affect dependency relationships
- Check the workflow logs for the stderr output
- Verify the repo has `.csproj` files discoverable from the root

### Common

**Comment not appearing**

- Verify `pull-requests: write` is in the workflow permissions
- Check if your org restricts `GITHUB_TOKEN` permissions (Settings > Actions > General > Workflow permissions)

**Slow runs**

- First run clones and installs scatter (~30s). Subsequent runs benefit from uv caching.
- First graph build takes ~30-60s for large repos. Enable graph caching to avoid
  rebuilding on every push.

### GitHub Enterprise Server

The fallback error comment includes a link to the workflow logs using
`github.server_url`. This works for github.com but may need adjustment for
GitHub Enterprise Server instances with custom URLs.
