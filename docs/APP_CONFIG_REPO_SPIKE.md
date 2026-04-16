# Spike Plan: APP_CONFIG Repo Crawler — Evidence Pass

Companion to [APP_CONFIG_REPO.md](APP_CONFIG_REPO.md). Before committing to the full `--app-config-path` pipeline resolution plan, run a read-only spike that produces auditable evidence about the real repo.

**Goal:** Answer *"is the full plan worth building as written, or does the data favor a different shape?"* — without committing to any runtime matcher, data model, or scatter integration.

**Anti-goal:** This spike does NOT ship production code. Nothing it produces gets imported by scatter. The output is data for humans to read.

---

## 1. Purpose

The full plan depends on assumptions that can only be validated against the real config repo:

1. The pattern taxonomy (A/B/C/D) is accurate and complete
2. `wexhealth.host.json` is present in enough pipelines to be the primary signal
3. The matcher cascade (L1→L2→L3) is needed — i.e., L1 exact-match alone isn't sufficient
4. Org prefixes are limited to `wexhealth.`/`wex.`/`lighthouse1.`/`lh1.`
5. The Jaccard threshold of 0.5 at L2 fires on useful cases without producing false positives
6. Nav fan-out groups are correctly identifiable by the `-navN-az-cd` suffix pattern

The spike produces ground-truth data for each assumption. Based on the results, Phase 1 of the full plan is either green-lit, re-scoped to CSV enrichment, or revised.

---

## 2. Scope

### In scope

- Read-only crawl of the entire APP_CONFIG repo `production/` environment
- Extraction of: `AppName` from host.json, `.dll` arg from web.config, `.exe.config` filename stem, pipeline dir name
- Comparison of crawled data against the existing hand-maintained `examples/pipeline_to_app_mapping.csv`
- Quantitative reports: pattern counts, signal availability, agreement/disagreement with CSV, ambiguity frequency
- Edge-case audit: `//` comments in JSON, `{AppName}` placeholder occurrences, case variations, unknown org prefixes

### Out of scope

- Runtime matcher code
- Scatter integration (no changes to `scatter/` package)
- Any matching of project names → pipelines (the spike stops at producing the raw data; matching happens in analysis, by human)
- `qa`/`staging`/`uat` environments — `production` only
- Dependency graph updates, test suite, CLI flags

### Deliberate constraints

- **Read-only.** No writes to the config repo. Enforced by the script never opening a file with write mode.
- **Idempotent.** Running twice produces identical output. No timestamps in filenames, no append-only behavior.
- **Self-contained.** Single Python file, no imports from `scatter/`. Must be deletable when the spike is done without touching the project.
- **No new dependencies.** Stdlib only (`re`, `json`, `csv`, `pathlib`, `collections`, `argparse`).

---

## 3. Deliverables

The spike produces five artifacts, all written to `spike_output/` (gitignored):

| Artifact | Format | Purpose |
|---|---|---|
| `01_raw_crawl.csv` | CSV | Every pipeline dir → extracted signals (one row per pipeline, one row per batch job) |
| `02_pattern_taxonomy.md` | Markdown | Counts per pattern (A/B/C/D) with pipeline name samples |
| `03_csv_diff.md` | Markdown | Side-by-side: hand CSV vs crawled data. New mappings, disagreements, missing |
| `04_ambiguity_report.md` | Markdown | Cases where matcher cascade would produce multiple candidates or low confidence |
| `05_edge_cases.md` | Markdown | Observed occurrences of `//` comments, `{AppName}` placeholders, new prefixes, unusual structures |

All artifacts are plain text — reviewable in a PR, grep-able, diffable across spike runs.

---

## 4. Script Layout

**Location:** `tools/spike/config_repo_crawl.py`

**Why `tools/spike/`:** existing `tools/` directory holds dev scripts (`check.sh`, `setup.sh`). The `spike/` subdirectory is a clear signal that contents are throwaway. `.gitignore` keeps `spike_output/` out of commits; the script itself is committed so the work is reproducible.

**Invocation:**

```bash
python tools/spike/config_repo_crawl.py \
    --app-config-path /path/to/health-benefits-app-config \
    --hand-csv examples/pipeline_to_app_mapping.csv \
    --output-dir spike_output/
```

**Single file, ~250 LOC target.** If it grows past 400 LOC, that's a sign the spike is becoming the real thing and should be redirected.

**Structure (top-to-bottom):**

```python
# 1. Constants / regexes (30 lines)
_APP_NAME_RE = re.compile(r'"AppName"\s*:\s*"([^"]+)"')
_DLL_ARG_RE  = re.compile(r'arguments="[^"]*?([A-Za-z][A-Za-z0-9.]+)\.dll"')
_NAV_RE      = re.compile(r'^(.+?)-nav\d+(-az-cd|$)')
_PIPELINE_SUFFIX_RE = re.compile(r'-(az-cd|az-cicd|cicd|cd|mws)$')
SKIP_DIRS = {"GeneratedIisSettingsFiles", "MachineConfigurationsSummarizer", ".git", ".github"}
ENV_SKIP = {"App_Data", "PostDeployTests"}
KNOWN_PREFIXES = ("wexhealth.", "wex.", "lighthouse1.", "lh1.")

# 2. Data extraction (90 lines)
#    - walk_repo(repo_path) -> list[PipelineDir]
#    - classify_pattern(pipeline_dir) -> "A" | "B" | "C" | "D"
#    - extract_app_name(host_json_path) -> str | None
#    - extract_assembly_from_webconfig(web_config_path) -> str | None
#    - extract_assembly_from_execonfig(env_dir) -> str | None
#    - collect_pipeline_signals(pipeline_dir) -> list[CrawlRow]

# 3. Analysis (80 lines)
#    - detect_nav_groups(rows) -> list[NavGroup]
#    - diff_against_hand_csv(rows, csv_path) -> DiffReport
#    - find_ambiguities(rows) -> list[Ambiguity]
#    - audit_edge_cases(rows, raw_content_cache) -> EdgeCaseReport

# 4. Report writers (40 lines)
#    - write_raw_csv(rows, path)
#    - write_pattern_taxonomy_md(rows, path)
#    - write_csv_diff_md(diff, path)
#    - write_ambiguity_md(ambig, path)
#    - write_edge_cases_md(audit, path)

# 5. main() + argparse (20 lines)
```

---

## 5. Algorithm Detail

### 5.1 Walk and classify

```
for child in repo_path.iterdir():
    if not child.is_dir(): continue
    if child.name.startswith("."): continue
    if child.name in SKIP_DIRS: continue

    env_dir = child / "production"
    if not env_dir.is_dir():
        record(pattern="MISSING_ENV", pipeline=child.name)
        continue

    # Pattern classification
    subdirs = [d for d in env_dir.iterdir()
               if d.is_dir() and d.name not in ENV_SKIP]

    host_json = env_dir / "wexhealth.host.json"

    if subdirs and all((d / "wexhealth.host.json").exists() for d in subdirs):
        pattern = "B"  # Batch fan-out
    elif host_json.exists():
        pattern = "A" or "C"  # nav detection happens later
    elif any(env_dir.glob("*.config")):
        pattern = "D_PARTIAL"  # has config but no host.json
    else:
        pattern = "D_EMPTY"
```

### 5.2 Signal extraction (per pipeline)

Each pipeline produces one or more `CrawlRow` records:

```python
@dataclass
class CrawlRow:
    pipeline_name: str
    job_name: str | None          # None for A/C/D; job dir name for B
    pattern: str                  # "A", "B", "C", "D_PARTIAL", "D_EMPTY", "MISSING_ENV"
    host_app_name: str | None
    web_config_dll: str | None
    exe_config_stem: str | None
    heuristic_name: str | None    # from pipeline dir name
    resolution_source: str        # "host_json" | "web_config" | "exe_config" | "heuristic" | "none"
    has_comments_in_host_json: bool
    has_appname_placeholder_near: bool  # true if `{AppName}` appears anywhere in the host_json content
    raw_host_json_size_bytes: int
```

**Critical:** populate ALL available signals per row, not just the "winning" one. The report reader needs to see agreement/disagreement between host_json and web_config on the same pipeline.

### 5.3 Edge-case instrumentation

The script tracks but does not act on:

- `//` comment count per host.json (regex: `^\s*//`)
- Occurrences of `{AppName}` substring in any host.json body (tracks the plan's §7.6 collision risk)
- Org prefix seen in any extracted name that is NOT in `KNOWN_PREFIXES` — emit to `05_edge_cases.md`
- host.json files that fail the `_APP_NAME_RE` regex entirely (surface these as "malformed" — we need to see why)
- Case variations: if any pipeline has both `web.config` and `Web.Config`, or host.json with both `AppName` and `appName`

### 5.4 Nav group detection

Post-crawl pass:

```python
groups = defaultdict(list)
for row in rows:
    m = _NAV_RE.match(row.pipeline_name)
    if m:
        groups[m.group(1)].append(row)

# Report groups where len > 1
# Also report "would-be groups" where pattern matches but only 1 exists
```

The "would-be groups" case catches typos or incomplete fan-out families — useful signal about repo hygiene.

### 5.5 CSV diff

Read the hand CSV (`examples/pipeline_to_app_mapping.csv`):
- Format: `Application Name, Pipeline Name`
- Build `hand_map: dict[str_normalized, str]` (app → pipeline)

Build crawled map from rows:
- For each row, try `host_app_name`, then `web_config_dll`, then `exe_config_stem` → pipeline (+ job if batch)
- Normalize the same way (lowercase, dots/dashes/underscores unified, known prefixes stripped)

Produce three buckets:

| Bucket | Meaning |
|---|---|
| **Agree** | Both sources have the app; pipelines match (ignoring nav-fan-out multiplicity) |
| **Disagree** | Both sources have the app; pipelines differ → HIGH priority for human review |
| **Crawled-only** | Crawler found it, hand CSV missed it → the "free wins" count |
| **CSV-only** | Hand CSV has it, crawler didn't resolve → explains what the crawler misses |

### 5.6 Ambiguity analysis

For each row, simulate what the plan's L1/L2/L3 matcher WOULD return:

- L1 exact against `host_app_name` and `assembly_name` — count hits with normalized equality
- L2 Jaccard ≥ 0.5 against all other rows' app names — count candidates
- L3 tail-2-tokens match against all other rows — count candidates

**Key question answered:** for how many pipelines does L3 produce ≥2 candidates? Those are the silent-wrong-answer cases.

Report format (abbreviated):

```
## L3 tail-match ambiguities (20 rows)

- project tail: `.scheduler` → candidates:
    - cdh-exportscheduler-nav1-az-cd   AppName=Lighthouse1.Exports.Scheduler
    - cdh-batchscheduler-az-cd          AppName=WexHealth.Batch.Scheduler
    - pts-cdb-scheduler-az-cd           AppName=WexHealth.PTS.Scheduler
  → THREE candidates; L3 cannot disambiguate
```

---

## 6. Reports — Specific Contents

### 6.1 `01_raw_crawl.csv`

Columns: `pipeline_name, job_name, pattern, host_app_name, web_config_dll, exe_config_stem, heuristic_name, resolution_source, has_comments, has_placeholder, host_json_bytes, notes`

One row per pipeline (Pattern A/C/D). One row per batch job (Pattern B). Sort by `pipeline_name, job_name`.

### 6.2 `02_pattern_taxonomy.md`

```markdown
# Pattern Counts

| Pattern | Count | % | Description |
|---|---|---|---|
| A | ___ | __%  | Single-app pipeline with host.json |
| B | ___ | __%  | Batch fan-out with per-job host.json |
| C | ___ | __%  | Nav fan-out (subset of A, flagged by nav detection) |
| D_PARTIAL | ___ | __% | No host.json, has web.config or other |
| D_EMPTY | ___ | __% | No resolvable signals |
| MISSING_ENV | ___ | __% | No `production/` subdirectory |

# Nav Groups Detected
<list: canonical name, pipeline count, shared AppName or "MIXED">

# Would-be Nav Groups (1-member patterns)
<list — could indicate typos or partial fan-out>

# Batch Pipelines
<list with job count per pipeline>
```

### 6.3 `03_csv_diff.md`

```markdown
# Hand CSV vs Crawler

**Hand CSV total entries:** ___
**Crawler resolved entries:** ___

## Agreement (___ entries)
<collapsed count — sample 10>

## Disagreement — HUMAN REVIEW REQUIRED (___ entries)
<full list: app_name | hand_pipeline | crawled_pipeline>

## Crawler found, hand CSV missed (___ entries)
<full list: app_name | crawled_pipeline | resolution_source>

## Hand CSV has, crawler missed (___ entries)
<full list: app_name | hand_pipeline | why_unresolved>
```

### 6.4 `04_ambiguity_report.md`

```markdown
# Matcher Cascade Simulation

Given the plan's L1 (exact) → L2 (Jaccard 0.5) → L3 (tail-2) cascade,
how many pipelines fall through to each level on realistic input?

## L1 exact match rate: ___ / ___ (__%)
## L2-only match rate: ___ / ___ (__%)
## L3-only match rate: ___ / ___ (__%)
## Cascade failure rate: ___ / ___ (__%)

## L2 Jaccard firings — threshold 0.5 analysis
<table: matched pair | token intersection | union | ratio>

## L3 ambiguities (multiple candidates)
<sectioned by tail — each with all candidates>

## L3 potential silent-wrongs
<cases where L3 returns a SINGLE candidate that might be wrong>
```

### 6.5 `05_edge_cases.md`

```markdown
# Edge Cases Observed

## `//` comments in host.json: ___ of ___ files (__%)
<samples of comment patterns>

## `{AppName}` placeholder occurrences: ___ of ___ files
<context for each — confirms plan §7.6 assumption>

## Unknown org prefixes
<any prefix not in KNOWN_PREFIXES — with count of occurrences>

## Malformed host.json (regex failed)
<full list + reason if diagnosable>

## Case anomalies
- host.json with `appName` (lowercase): ___
- `Web.Config` (capitalized): ___
- Other observed casings: <list>

## Structural surprises
<anything that doesn't fit A/B/C/D/MISSING — e.g., pipelines with
 nested pipeline dirs, pipelines with only `staging/`, etc.>
```

---

## 7. Decision Criteria

After the reports are generated and reviewed, one of three paths:

### Path 1 — Build full plan as written

**Triggers (all must hold):**
- L1 exact-match rate < 85%
- L2+L3 cascade usefully resolves ≥50% of non-L1 cases with ≤5% ambiguous/wrong
- Pattern taxonomy A/B/C/D covers ≥95% of pipelines
- ≥20 crawler-only mappings (CSV misses) — proves the crawler delivers value
- Edge cases (comments, placeholders) behave as the plan predicts

### Path 2 — Enriched-CSV approach

**Triggers:**
- L1 exact-match rate ≥ 90%
- L2/L3 cascade adds < 10% coverage OR has unacceptable ambiguity
- Crawled data is stable enough that a committed CSV would stay correct for ≥ 6 months between regenerations

**Action:** commit the crawler as `tools/generate_pipeline_csv.py`, commit its output to `examples/pipeline_to_app_mapping.csv`, skip the runtime matcher entirely. Full plan §3-§5 never gets built.

### Path 3 — Re-scope

**Triggers:**
- Pattern taxonomy misses significant structures (>5% of pipelines don't fit A/B/C/D)
- Edge cases are worse than the plan anticipates (e.g., host.json corruption rate >1%, many unknown org prefixes)
- The CSV diff shows the hand CSV is systematically *more* correct than the crawler in ways the plan doesn't address

**Action:** revise the plan before any Phase 1 work. The spike becomes input to v2 of `APP_CONFIG_REPO.md`.

**Falsifiability:** Path 1 requires the fewest assumptions to change. Paths 2 and 3 are real possibilities — don't walk into the spike assuming Path 1.

---

## 8. Operational Notes

### 8.1 Prerequisites

- Local clone of `health-benefits-app-config`
- Python 3.10+ (same as scatter)
- No other setup — stdlib only

### 8.2 Running it

```bash
# From repo root
mkdir -p spike_output
python tools/spike/config_repo_crawl.py \
    --app-config-path /path/to/health-benefits-app-config \
    --hand-csv examples/pipeline_to_app_mapping.csv \
    --output-dir spike_output/

# Artifacts land in spike_output/
ls spike_output/
# 01_raw_crawl.csv
# 02_pattern_taxonomy.md
# 03_csv_diff.md
# 04_ambiguity_report.md
# 05_edge_cases.md
```

### 8.3 Sharing the output

The config repo contains WEX internal app and pipeline names. Before sharing the spike output:

- `01_raw_crawl.csv` is the only file that contains raw internal names. The `.md` reports reference names but may be redactable.
- If the output needs review from anyone outside the team: provide a `--redact` flag that replaces identifiers with hashes while preserving structural signal (pattern counts, agreement rates, ambiguity counts). Implementation: `hashlib.sha1(name.encode()).hexdigest()[:8]`.

### 8.4 `.gitignore` additions

```
# Spike artifacts — never committed
spike_output/
```

The script itself (`tools/spike/config_repo_crawl.py`) IS committed so future devs can reproduce or re-run.

---

## 9. What This Spike Will NOT Tell Us

Stating limits prevents over-reading the results:

- **Temporal stability.** A one-time crawl tells us today's state. It doesn't tell us how often the repo changes or whether the crawler's output would be stable week-to-week. If Path 2 (enriched CSV) is selected, a follow-up decision is how often to regenerate — the spike doesn't answer that.

- **Runtime performance.** The crawl happens once, offline, in this spike. If we build the runtime matcher (Path 1), performance on every invocation needs separate measurement.

- **Matching quality against real source projects.** The spike simulates the matcher cascade against crawled data alone. It doesn't cross-match against the actual `.csproj` files in WEX source repos. That's a second-order question; we need to know the crawled data is good before it's worth asking whether our source projects find matches in it.

- **How users feel about the output.** Whether "Unmapped" in a pipeline column is an acceptable UX is not a data question. If the spike shows 150 unresolvable pipelines, the user-experience decision is separate from the technical question.

---

## 10. Follow-on After Spike

Whichever path is selected, the spike leaves artifacts that feed it:

- **Path 1:** `01_raw_crawl.csv` becomes the golden fixture for `tests/integration/test_config_repo_scanner_integration.py` — real data, redacted, committed.
- **Path 2:** The crawler gets promoted from `tools/spike/` to `tools/generate_pipeline_csv.py`, reports become CI outputs.
- **Path 3:** Reports are attached as appendix to revised `APP_CONFIG_REPO.md v2`.

In all three cases, nothing the spike produces is wasted.
