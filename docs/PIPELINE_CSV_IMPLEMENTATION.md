# Implementation Plan: Pipeline CSV Generator

Supersedes §3-5 of [APP_CONFIG_REPO.md](APP_CONFIG_REPO.md) (the runtime matcher sections). The spike ([SPIKE_RESULTS.md](SPIKE_RESULTS.md), [SPIKE_RESULTS_2.md](SPIKE_RESULTS_2.md), [SPIKE_RESULTS_3.md](SPIKE_RESULTS_3.md)) showed that:

- L1 exact-match has perfect precision — zero false positives across 33 matches
- L2/L3 cascade adds noise, not signal (10 matches, all ambiguous)
- The naming gap between source projects and config-repo AppNames can't be bridged programmatically — it requires human curation
- The right approach is Path 2: crawl the config repo, emit an enriched CSV, commit it, maintain it

**Scatter's interface does not change.** `--pipeline-csv` works exactly as it does today. The crawler is a dev tool that produces a better CSV than the one humans were maintaining by hand.

---

## 1. Deliverables

| # | What | Where | New / Modified |
|---|---|---|---|
| 1 | Pipeline CSV generator | `tools/generate_pipeline_csv.py` | New (promoted from spike) |
| 2 | Enriched pipeline CSV | `examples/pipeline_to_app_mapping.csv` | Modified (replaces 5-row demo) |
| 3 | Manual overrides CSV | `examples/pipeline_manual_overrides.csv` | New |
| 4 | "Pipeline not found" warning | `scatter/compat/v1_bridge.py` | Modified |
| 5 | `load_pipeline_csv()` update | `scatter/modes/setup.py` | Modified (reads both CSVs, new column names) |
| 6 | CSV schema + generator tests | `tests/integration/test_pipeline_csv.py` | New |
| 7 | Regeneration runbook | `tools/README.md` or section in this doc | New |

## 2. What does NOT get built

Explicitly dropped based on spike evidence:

- ~~`scatter/scanners/config_repo_scanner.py`~~ — no runtime scanner
- ~~`scatter/scanners/config_repo_matcher.py`~~ — no runtime matcher (L1/L2/L3 cascade)
- ~~`ModeContext.config_repo_crawl` field~~ — scatter core unchanged
- ~~`load_from_config_repo()` in `modes/setup.py`~~ — no replacement for `load_batch_jobs()`
- ~~Nav fan-out collapsing in the CSV~~ — emit every real pipeline name, no wildcards
- ~~Merge logic in the generator~~ — generator always writes a clean file; manual overrides live separately

---

## 3. Deliverable details

### 3.1 `tools/generate_pipeline_csv.py` (~200 LOC target)

Promoted from `tools/spike/config_repo_crawl.py`. **Strip aggressively** — the spike had 7 reports, 3 populations, temporal diffs, HMAC redaction, ambiguity simulation. The production tool needs:

**Keep:**
- `crawl()` — walk the config repo, classify patterns, extract signals
- `_make_row()` / signal extractors (`extract_app_name`, `extract_assembly_from_webconfig`, `extract_assembly_from_execonfig`)
- `CrawlRow` dataclass (slimmed — drop `has_comments_in_host_json`, `has_appname_placeholder_near`, `raw_host_json_size_bytes`, `notes`)
- `KNOWN_PREFIXES`, `SKIP_DIRS`, `ENV_SKIP` constants
- `{AppName}` placeholder rejection in `extract_app_name()`

**Drop:**
- All 7 report writers
- `detect_nav_groups()` — no longer needed (nav rows emitted individually)
- `normalize()`, `tokens()`, `jaccard()` — matcher utilities
- `find_within_repo_ambiguities()`, `simulate_source_match()` — cascade simulation
- `diff_against_hand_csv()`, `audit_edge_cases()` — analysis functions
- `load_prev_snapshot()`, `temporal_diff()` — temporal comparison
- `redactor()` — HMAC redaction
- `--source-stems`, `--prev-snapshot`, `--redact`, `--l2-threshold` flags

**Output CSV columns:**

```
pipeline_name,app_name,assembly_name,source
```

- `pipeline_name` — the real CI pipeline directory name (no wildcards, no collapsing)
- `app_name` — from `wexhealth.host.json` AppName
- `assembly_name` — from `web.config` DLL or `exe.config` filename (may differ from app_name; empty if not available)
- `source` — `host_json`, `web_config`, `exe_config`, `heuristic`

Nav fan-out pipelines emit one row per pipeline (all 25 `cdh-exportscheduler-navN-az-cd` rows appear individually). `-az-cd`/`-cd` pairs emit as separate rows. Pattern-B batch jobs emit one row per job. No collapsing, no wildcards — every row is a real pipeline name that scatter's lookup can match exactly.

Columns deliberately excluded (per team review): `pipeline_count` (derivable from data), `pattern` (crawler implementation detail), `alt_pipeline` (unnecessary when pairs are separate rows).

**Invocation:**

```bash
# Local (with Python + uv)
uv run python tools/generate_pipeline_csv.py \
    --app-config-path /path/to/health-benefits-app-config \
    --output examples/pipeline_to_app_mapping.csv

# Docker (no Python install)
docker run --rm \
    -v "$(pwd)":/workspace \
    -v /path/to/config-repo:/config:ro \
    python:3.12-slim \
    python /workspace/tools/generate_pipeline_csv.py \
        --app-config-path /config \
        --output /workspace/examples/pipeline_to_app_mapping.csv
```

**Behavior:**
- Always writes a **clean, complete** output. No merge logic. If `--output` file already exists, it is overwritten entirely.
- Manual overrides live in a separate file (§3.3) and are never touched by the generator.
- Prints summary to stdout: `N pipeline dirs scanned, M rows written (K via host_json, J via web_config, ...)`

### 3.2 Enriched `examples/pipeline_to_app_mapping.csv`

Replace the current 5-row demo file with the real output from the generator. This is a one-time action during implementation:

1. Run the generator against the real config repo
2. Human-review the output (spot-check for obviously wrong extractions)
3. Commit the reviewed CSV

The committed CSV is the crawled source of truth. Scatter reads it via `--pipeline-csv` at runtime — no change to scatter's behavior.

### 3.3 Manual overrides: `examples/pipeline_manual_overrides.csv`

A separate, human-maintained CSV for mappings the crawler can't derive:

```
pipeline_name,app_name,assembly_name,source
```

Same schema as the crawled CSV. The `source` column is always `manual`.

This file is:
- **Never written by the generator.** Only humans edit it.
- **Read by `load_pipeline_csv()`** alongside the crawled CSV. Manual entries win on conflicts (same `app_name` appearing in both files → manual's `pipeline_name` takes precedence).
- **Small.** Expected to contain ~10-30 rows for deployed apps the crawler can't resolve.

Separating manual from crawled entries eliminates merge logic entirely: the generator always writes a clean file, manual entries are never at risk of being overwritten, and the source of every mapping is unambiguous.

### 3.4 `load_pipeline_csv()` update

`scatter/modes/setup.py:load_pipeline_csv()` changes:

1. **Accept new column names:** read `app_name` / `pipeline_name` in addition to the existing `Application Name` / `Pipeline Name`. Old-schema CSVs continue to work — this is backward compatible, not a migration. The old column names are supported indefinitely (no deprecation planned; removing them costs more than keeping them).

2. **Read the manual overrides file:** if `--pipeline-csv` points to `examples/pipeline_to_app_mapping.csv`, also look for `examples/pipeline_manual_overrides.csv` in the same directory. Load both, manual wins on conflict. If the overrides file doesn't exist, proceed silently with only the crawled CSV.

Metadata columns (`assembly_name`, `source`) are not consumed by scatter at runtime — they exist for human reviewers and for the regeneration workflow. `load_pipeline_csv()` reads only `pipeline_name` and `app_name`.

### 3.5 "Pipeline not found" warning

In `scatter/compat/v1_bridge.py`, when a consumer project resolves to no pipeline in the CSV, log:

```
WARNING: Pipeline not found for 'ProjectName' — consider adding to pipeline_manual_overrides.csv
```

This surfaces CSV drift without failing the analysis. Implementation is a single `logging.warning()` call in `_build_consumer_results()` where the pipeline lookup returns empty.

Log once per project, not once per consumer — avoids noise when the same unresolved project appears across multiple consumers.

### 3.6 CSV schema + generator tests

`tests/integration/test_pipeline_csv.py`:

**Schema test (runs against committed CSV):**

```python
REQUIRED_COLUMNS = {"pipeline_name", "app_name", "source"}
VALID_SOURCES = {"host_json", "web_config", "exe_config", "heuristic", "manual"}

def test_pipeline_csv_schema():
    """Assert the committed CSV has the expected structure."""
    csv_path = Path("examples/pipeline_to_app_mapping.csv")
    assert csv_path.is_file()
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Required columns present
    assert REQUIRED_COLUMNS.issubset(set(reader.fieldnames))
    # No empty pipeline_name or app_name
    assert all(r["pipeline_name"].strip() for r in rows)
    assert all(r["app_name"].strip() for r in rows)
    # Source values are from the known set
    assert all(r["source"].strip() in VALID_SOURCES for r in rows)
    # No duplicate (app_name, pipeline_name) pairs
    pairs = [(r["app_name"], r["pipeline_name"]) for r in rows]
    assert len(pairs) == len(set(pairs))

def test_manual_overrides_schema():
    """If manual overrides exist, validate their schema too."""
    csv_path = Path("examples/pipeline_manual_overrides.csv")
    if not csv_path.is_file():
        pytest.skip("no manual overrides file")
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert REQUIRED_COLUMNS.issubset(set(reader.fieldnames))
    assert all(r["source"].strip() == "manual" for r in rows)
```

**Generator fixture test (runs against `tests/fixtures/config_repo_mini/`):**

```python
def test_generator_against_fixture(tmp_path):
    """Run the generator against config_repo_mini and verify output."""
    # Invoke generator against fixture, write to tmp_path
    output = tmp_path / "output.csv"
    # ... run generate_pipeline_csv against tests/fixtures/config_repo_mini/ ...
    with output.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Fixture has 7 pipelines (8 crawl rows — 2 Pattern B jobs)
    #   Pattern A: cdh-pattern-a-az-cd → host_json
    #   Pattern B: cdh-batchprocesses-az-cd/JobAlpha → host_json
    #   Pattern B: cdh-batchprocesses-az-cd/JobBeta → host_json
    #   Pattern C (nav): cdh-navpipe-nav1-az-cd → host_json
    #   Pattern C (nav): cdh-navpipe-nav2-az-cd → host_json
    #   Pattern D_PARTIAL: pts-partial-az-cd → web_config
    #   Pattern D_EMPTY: pts-empty-az-cd → heuristic
    #   MISSING_ENV: no-env-pipeline → heuristic
    assert len(rows) == 8
    sources = [r["source"] for r in rows]
    assert sources.count("host_json") == 5
    assert sources.count("web_config") == 1
    assert sources.count("heuristic") == 2
    # Pattern A has both app_name and assembly_name
    pattern_a = [r for r in rows if r["pipeline_name"] == "cdh-pattern-a-az-cd"]
    assert len(pattern_a) == 1
    assert pattern_a[0]["app_name"] == "WexHealth.Apps.Web.EmployerPortal"
    assert pattern_a[0]["assembly_name"] == "WexHealth.Apps.Web.Employer.Portal"

def test_load_merges_crawled_and_manual(tmp_path):
    """Manual overrides win on conflict when load_pipeline_csv reads both."""
    # Create crawled CSV: app Foo → pipeline-a
    # Create manual CSV: app Foo → pipeline-b (override)
    # Also: app Bar → pipeline-c (manual-only, no conflict)
    # Assert: Foo → pipeline-b (manual wins), Bar → pipeline-c (added)
    ...
```

### 3.7 Regeneration runbook

```markdown
## Regenerating the pipeline CSV

When: when new pipelines are added or modified in the config repo,
or when the "Pipeline not found" warning starts appearing for
projects you know are deployed.

1. Clone or pull `health-benefits-app-config`
2. Run the generator:
   docker run --rm \
       -v "$(pwd)":/workspace \
       -v /path/to/config-repo:/config:ro \
       python:3.12-slim \
       python /workspace/tools/generate_pipeline_csv.py \
           --app-config-path /config \
           --output /workspace/examples/pipeline_to_app_mapping.csv
3. Diff the output: git diff examples/pipeline_to_app_mapping.csv
4. Review new/changed rows.
5. Commit and push.

Manual overrides in pipeline_manual_overrides.csv are unaffected
by regeneration — they live in a separate file.

To add a manual mapping for a deployed app the crawler can't resolve,
add a row to examples/pipeline_manual_overrides.csv with source=manual.
```

---

## 4. File layout

```
tools/
  generate_pipeline_csv.py          NEW  — the production CSV generator (~200 LOC)
  spike/
    config_repo_crawl.py            DEL  — remove from tree (preserved in git history)

examples/
  pipeline_to_app_mapping.csv       MOD  — real crawled CSV replaces 5-row demo
  pipeline_manual_overrides.csv     NEW  — human-curated overrides (empty initially)

scatter/
  compat/v1_bridge.py               MOD  — add "pipeline not found" warning log
  modes/setup.py                    MOD  — load_pipeline_csv() reads both CSVs, new column names

tests/
  integration/
    test_pipeline_csv.py            NEW  — schema tests + generator fixture test + merge test
  fixtures/
    config_repo_mini/               KEEP — synthetic fixture for generator tests
```

**Minimal changes to `scatter/` core.** Only `v1_bridge.py` (warning log) and `modes/setup.py` (CSV loading) are touched. No new modules, no `ModeContext` changes. Scatter's runtime behavior is identical before and after — only the CSV it reads improves.

---

## 5. Migration: existing `--pipeline-csv` consumers

The current CSV schema is:

```
"Pipeline Name","Application Artifact","Application Name"
```

The new schema is:

```
pipeline_name,app_name,assembly_name,source
```

**Backward compatibility:** `load_pipeline_csv()` accepts both old and new column names. Old-schema CSVs continue to work indefinitely. No deprecation planned — removing old-name support costs more than keeping it. The `Application Artifact` column from the old schema is ignored (it was display-only).

---

## 6. Implementation order

1. **`tools/generate_pipeline_csv.py`** — build and test against the synthetic fixture
2. **`load_pipeline_csv()` update** — read both CSVs, accept new column names, manual wins on conflict
3. **"Pipeline not found" warning** — single addition to `v1_bridge.py`
4. **`tests/integration/test_pipeline_csv.py`** — schema test, generator fixture test, merge test
5. **Delete `tools/spike/`** — preserved in git history
6. **Generate the real CSV** — run against the config repo on the PC, human-review, commit
7. **Create `examples/pipeline_manual_overrides.csv`** — header-only initially, populated during step 6 review

Steps 1-5 can be built and tested on this machine against the synthetic fixture. Steps 6-7 require the PC with the config repo.
