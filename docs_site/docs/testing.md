# Testing

Is this thing well-tested? Yes. Can you verify that yourself in under a minute? Also yes.

## Running the tests

The fastest way to check everything before pushing:

```bash
bash tools/check.sh
```

This mirrors CI exactly — ruff lint, ruff format, mypy, then pytest. If `check.sh` passes locally, CI will pass.

For a lint-only check (~2 seconds):

```bash
bash tools/check.sh --quick
```

Or run just the test suite:

```bash
uv run pytest
```

```
~1,490 passed, 1 xfailed (run `uv run pytest --co -q` for the current count)
```

~1,490 tests across 35+ files. The single xfail tracks a known limitation: `TargetFrameworks` (plural) in `.csproj` files isn't parsed yet — only `TargetFramework` (singular). The test marks it so we don't forget.

## What the tests cover

The short version, without the file-by-file inventory:

- **All six analysis modes** -- target project, git branch, stored procedure, impact analysis, dependency graph, and PR risk scoring. Each mode has its own test file plus integration tests that run the full pipeline.
- **Graph construction and caching** -- build, serialize, deserialize, roundtrip. Smart git-based cache invalidation with mtime fallback.
- **Incremental updates** -- the patch algorithm is property-tested: for 6 mutation types (usage edits, declaration changes, new files, deleted files, csproj changes), incremental patching produces identical results to a full rebuild.
- **Coupling metrics** -- fan-in, fan-out, instability index, coupling score, shared database density. Cycle detection across project-reference edges.
- **Domain clustering** -- connected components, label propagation, cluster naming, extraction feasibility scoring.
- **Every output format** -- console, JSON, CSV, markdown, mermaid, pipelines. Column validation, escaping edge cases, empty report handling.
- **AI integration** -- all mocked. No real API calls, ever. Mocks cover valid responses, empty responses, invalid JSON, markdown fence stripping, API exceptions, and graceful fallback when no provider is configured.
- **Parallel vs sequential consistency** -- every parallel operation is verified to produce identical results when run with `--disable-multiprocessing`.

No flaky tests. No sleeps. No network calls.

## Smoke-testing against sample projects

The repo ships with 13 sample .NET projects. Use them to verify Scatter works end-to-end on your machine.

### GalaxyWorks.Data should have 7 consumers

```bash
scatter --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

Look for: `7 consumer(s)` in the output. Test projects are excluded by default — GalaxyWorks.Data.Tests won't appear in the list.

### MyDotNetApp should have 1 consumer

```bash
scatter --target-project ./samples/MyDotNetApp/MyDotNetApp.csproj --search-scope .
```

Look for: `1 consumer(s)`.

### MyDotNetApp2.Exclude should have 0 consumers

```bash
scatter --target-project ./samples/MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .
```

Look for: `0 consumer(s)`. This one is intentionally isolated -- it validates that Scatter doesn't report false positives.

### Stored procedure tracing works

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```

Should find the sproc in `PortalDataService` and `PortalCacheService`, tracing 7 consumers across 2 targets.

### Graph mode works

```bash
scatter --graph --search-scope .
```

Should produce a health dashboard with project counts, edge counts, coupling metrics, and domain clusters. No errors, no warnings.

## Testing AI features

These require a `$GOOGLE_API_KEY` environment variable. If you don't have one, the smoke tests above cover everything that matters for day-to-day use.

### Summarization

```bash
scatter --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY
```

### Hybrid git analysis

```bash
scatter --branch-name feature/your-branch --repo-path . --search-scope . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY -v
```

### Impact analysis

```bash
scatter --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter" \
  --search-scope . --google-api-key $GOOGLE_API_KEY
```

## Want to go deeper?

See [Test Architecture](reference/test-architecture.md) for the full 33-file test inventory, fixture design, mock patterns, and how to add new tests.
