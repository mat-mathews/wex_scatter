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
| 3 | Nav/pair collapsing | Built into the generator | New |
| 4 | "Pipeline not found" warning | `scatter/compat/v1_bridge.py` | Modified |
| 5 | CSV schema smoke test | `tests/integration/test_pipeline_csv.py` | New |
| 6 | Regeneration runbook | `tools/README.md` or section in this doc | New |

## 2. What does NOT get built

Explicitly dropped based on spike evidence:

- ~~`scatter/scanners/config_repo_scanner.py`~~ — no runtime scanner
- ~~`scatter/scanners/config_repo_matcher.py`~~ — no runtime matcher (L1/L2/L3 cascade)
- ~~`ModeContext.config_repo_crawl` field~~ — scatter core unchanged
- ~~`load_from_config_repo()` in `modes/setup.py`~~ — no replacement for `load_batch_jobs()`
- ~~Nav fan-out collapsing in reporters~~ — handled in CSV generation, not at runtime

---

## 3. Deliverable details

### 3.1 `tools/generate_pipeline_csv.py` (~200 LOC target)

Promoted from `tools/spike/config_repo_crawl.py`. **Strip aggressively** — the spike had 7 reports, 3 populations, temporal diffs, HMAC redaction, ambiguity simulation. The production tool needs:

**Keep:**
- `crawl()` — walk the config repo, classify patterns, extract signals
- `_make_row()` / signal extractors (`extract_app_name`, `extract_assembly_from_webconfig`, `extract_assembly_from_execonfig`)
- `detect_nav_groups()` — needed for collapsing
- `CrawlRow` dataclass (can slim down — drop `has_comments_in_host_json`, `has_appname_placeholder_near`, `raw_host_json_size_bytes`, `notes`)
- `KNOWN_PREFIXES`, `SKIP_DIRS`, `ENV_SKIP` constants
- `{AppName}` placeholder rejection in `extract_app_name()`

**Drop:**
- All 7 report writers
- `normalize()`, `tokens()`, `jaccard()` — matcher utilities
- `find_within_repo_ambiguities()`, `simulate_source_match()` — cascade simulation
- `diff_against_hand_csv()`, `audit_edge_cases()` — analysis functions
- `load_prev_snapshot()`, `temporal_diff()` — temporal comparison
- `redactor()` — HMAC redaction
- `--source-stems`, `--prev-snapshot`, `--redact`, `--l2-threshold` flags

**Add:**
- **Canonical pipeline group collapsing:**
  - Nav fan-out: `cdh-exportscheduler-nav{1..25}-az-cd` → single row with `pipeline_name = cdh-exportscheduler-nav*-az-cd` and `pipeline_count = 25`
  - `-az-cd`/`-cd` pairs: `cdh-authservice-az-cd` + `cdh-authservice-cd` → single row with `pipeline_name = cdh-authservice-az-cd` (prefer `-az-cd` variant) and `alt_pipeline = cdh-authservice-cd`
  - Pattern-B batch jobs: emit one row per job (keep current behavior — each job is a distinct deployable)
- **`source` column:** `host_json`, `web_config`, `exe_config`, `heuristic`, `manual`
  - `manual` is never emitted by the generator — it's for human-added rows that the crawler can't derive

**Output CSV columns:**

```
pipeline_name, app_name, assembly_name, alt_pipeline, pipeline_count, source, pattern
```

- `pipeline_name` — canonical pipeline (or `*`-collapsed for nav groups)
- `app_name` — from `wexhealth.host.json` AppName
- `assembly_name` — from `web.config` DLL or `exe.config` filename (may differ from app_name)
- `alt_pipeline` — secondary pipeline if `-az-cd`/`-cd` pair exists, empty otherwise
- `pipeline_count` — 1 for single pipelines, N for nav groups
- `source` — which signal resolved this row
- `pattern` — A, B, C, D_PARTIAL (for traceability)

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
- If `--output` file already exists, **merge** with existing rows: crawler output overwrites rows with `source != manual`, preserves `manual` rows untouched. This is the mechanism that protects human-curated entries across regeneration.
- Print a summary to stdout: `N rows crawled, M nav groups collapsed, P pairs collapsed, Q manual rows preserved`

### 3.2 Enriched `examples/pipeline_to_app_mapping.csv`

Replace the current 5-row demo file with the real output from the generator. This is a one-time action during implementation:

1. Run the generator against the real config repo
2. Human-review the output (check for obviously wrong rows, add known manual mappings for deployed apps the crawler missed)
3. Commit the reviewed CSV

The committed CSV is the source of truth for pipeline resolution. Scatter reads it via `--pipeline-csv` at runtime — no change to scatter's behavior.

### 3.3 "Pipeline not found" warning

In `scatter/compat/v1_bridge.py`, when a consumer project resolves to no pipeline in the CSV, log:

```
WARNING: Pipeline not found for 'ProjectName' — consider adding to pipeline_to_app_mapping.csv
```

This is Anya's feedback loop: it surfaces CSV drift without failing the analysis. Implementation is a single `logging.warning()` call in `_build_consumer_results()` where the pipeline lookup returns empty.

### 3.4 CSV schema smoke test

`tests/integration/test_pipeline_csv.py`:

```python
def test_pipeline_csv_schema():
    """Assert the committed CSV has the expected shape."""
    csv_path = Path("examples/pipeline_to_app_mapping.csv")
    assert csv_path.is_file()
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Has required columns
    assert "pipeline_name" in reader.fieldnames
    assert "app_name" in reader.fieldnames
    assert "source" in reader.fieldnames
    # No empty pipeline names
    assert all(r["pipeline_name"].strip() for r in rows)
    # No duplicate app_name→pipeline_name pairs
    pairs = [(r["app_name"], r["pipeline_name"]) for r in rows]
    assert len(pairs) == len(set(pairs))
    # Has at least the count we expect from the config repo crawl
    assert len(rows) >= 40  # Run 3 showed 43 L1 matches; real CSV will be larger
```

Plus the existing synthetic fixture test to verify the generator itself works:

```python
def test_generator_against_fixture():
    """Run the generator against config_repo_mini and verify output shape."""
    # Uses tests/fixtures/config_repo_mini/
    ...
```

### 3.5 Regeneration runbook

Added to `tools/README.md` or as a section here. Short and actionable:

```markdown
## Regenerating the pipeline CSV

When: quarterly, or when new pipelines are added to the config repo.

1. Clone or pull `health-benefits-app-config`
2. Run the generator (Docker or uv — see §3.1 invocation)
3. Diff the output against the current committed CSV:
   `git diff examples/pipeline_to_app_mapping.csv`
4. Review new/changed rows. Check that `source=manual` rows are preserved.
5. Commit and push.

The generator preserves `source=manual` rows across regeneration.
New pipelines appear as new rows with `source=host_json` (or similar).
Removed pipelines disappear from the crawled output but manual rows
for them are kept — delete manually if the pipeline is truly gone.
```

---

## 4. File layout

```
tools/
  generate_pipeline_csv.py          NEW  — the production CSV generator (~200 LOC)
  spike/
    config_repo_crawl.py            KEEP — historical spike, not used in production

examples/
  pipeline_to_app_mapping.csv       MOD  — real enriched CSV replaces 5-row demo

scatter/
  compat/v1_bridge.py               MOD  — add "pipeline not found" warning log

tests/
  integration/
    test_pipeline_csv.py            NEW  — schema test for committed CSV + generator fixture test
  fixtures/
    config_repo_mini/               KEEP — synthetic fixture for generator tests
```

**No changes to `scatter/` core** (no new modules, no `ModeContext` changes, no `modes/setup.py` changes). Scatter's runtime behavior is identical before and after — only the CSV it reads improves.

---

## 5. Migration: existing `--pipeline-csv` consumers

The current CSV schema is:

```
"Pipeline Name","Application Artifact","Application Name"
```

The new schema adds columns:

```
pipeline_name, app_name, assembly_name, alt_pipeline, pipeline_count, source, pattern
```

**Backward compatibility:** `scatter/modes/setup.py:load_pipeline_csv()` currently reads `Application Name` and `Pipeline Name` columns. It needs to also accept the new column names (`app_name`, `pipeline_name`). The function already has fallback logic for column name variants — extend it to handle both old and new schemas.

This is the only runtime code change in scatter (besides the warning log).

---

## 6. Implementation order

1. **`tools/generate_pipeline_csv.py`** — build and test against the synthetic fixture
2. **`load_pipeline_csv()` column-name update** — backward-compat for new CSV schema
3. **"Pipeline not found" warning** — one-line addition to `v1_bridge.py`
4. **`tests/integration/test_pipeline_csv.py`** — schema test + generator fixture test
5. **Generate the real CSV** — run against the config repo on the PC, human-review, commit
6. **Commit `SPIKE_RESULTS_3.md`** — close the spike evidence trail

Steps 1-4 can be built and tested on this machine against the synthetic fixture. Step 5 requires the PC with the config repo. Step 6 is housekeeping.
