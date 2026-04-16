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

When the optional inputs below are supplied, two additional artifacts are produced:

| Artifact | Triggered by | Purpose |
|---|---|---|
| `06_temporal_diff.md` | `--prev-snapshot <path>` | Diff of today's crawl vs. a prior crawl — stability signal for Path 2 |
| `07_source_project_match.md` | `--source-stems <path>` | Cascade simulation against real `.csproj` stems from the WEX source tree |

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
    --output-dir spike_output/ \
    [--source-stems source_project_stems.txt] \
    [--prev-snapshot spike_output_previous/01_raw_crawl.csv] \
    [--redact]
```

Optional flags:
- `--source-stems`: newline-delimited list of `.csproj` stem names from WEX source repos (the real inputs a runtime matcher would receive). Enables the P-intersect cascade simulation — the numbers that actually bear on the Path 1 vs Path 2 decision.
- `--prev-snapshot`: path to an earlier `01_raw_crawl.csv` from a prior run. Enables the temporal stability diff required for Path 2 viability.
- `--redact`: enable HMAC redaction of names for external sharing (see §8.3). Default off — outputs are internal only.

**Single file, ~300 LOC target.** If it grows past 450 LOC, that's a sign the spike is becoming the real thing and should be redirected.

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

# 3. Analysis (130 lines)
#    - detect_nav_groups(rows) -> list[NavGroup]
#    - cluster_pipeline_prefixes(rows) -> dict[str, list[str]]
#    - diff_against_hand_csv(rows, csv_path) -> DiffReport
#    - find_ambiguities(rows) -> list[Ambiguity]
#    - audit_edge_cases(rows, raw_content_cache) -> EdgeCaseReport
#    - simulate_against_source_stems(rows, stems) -> SourceMatchReport  # optional
#    - temporal_diff(rows, prev_rows) -> TemporalDiffReport             # optional

# 4. Report writers (60 lines)
#    - write_raw_csv(rows, path)
#    - write_pattern_taxonomy_md(rows, path)
#    - write_csv_diff_md(diff, path)
#    - write_ambiguity_md(ambig, path)
#    - write_edge_cases_md(audit, path)
#    - write_temporal_diff_md(diff, path)              # optional
#    - write_source_match_md(match_report, path)       # optional

# 5. main() + argparse (30 lines)
```

---

## 5. Algorithm Detail

### 5.0 Population and denominators — stated explicitly

Every rate and count in the reports is anchored to one of three populations. Reports must label which is in use:

| Population | Definition | Typical use |
|---|---|---|
| **P-all** | All pipeline directories crawled (expected ~370) | Pattern distribution, edge-case rates |
| **P-resolvable** | Pipelines that produced at least one signal (host.json, web.config DLL, or exe.config) | Collision analysis among deployed pipelines |
| **P-intersect** | Subset of P-resolvable whose AppName/assembly appears in `--source-stems` (when provided) | Runtime matcher decision — the only population whose numbers actually bear on whether scatter will resolve real source projects correctly |

Without `--source-stems`, matcher quality measures are reported against **P-resolvable** with an explicit caveat in the report header: *"collision analysis, not match-quality analysis."* A Path 1 vs Path 2 decision made without P-intersect data is being made on a proxy — acceptable as a tentative call but flagged as such.

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
- **Pipeline name family clustering**: strip known CI suffixes (`-az-cd`, `-az-cicd`, `-cicd`, `-cd`, `-mws`) and tokenize the remaining prefix. Cluster pipelines by their leading token family (`cdh-`, `pts-`, `direct-`, `wexhealth.card-`, etc.). Report the distribution with a sample pipeline per family. On future runs, the appearance of a new or single-member prefix family is the signal that the repo grew a pattern the crawler may not yet handle — a guardrail against silently returning empty for deployments in unfamiliar territory

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

**This within-repo simulation answers one question:** are there collisions *among deployed pipelines* that L3 cannot disambiguate?

**It does NOT answer the runtime question:** does L3 correctly resolve a real `.csproj` stem from a WEX source repo to exactly one pipeline? That requires source-side inputs.

When `--source-stems <file>` is provided, a second simulation runs the full cascade against each source stem and reports:

- Stems resolved at L1 (exact): count and listing
- Stems resolved at L2 (Jaccard ≥ 0.5): count, candidates, and the Jaccard score
- Stems resolved at L3 (tail match): count, candidates
- Stems producing multiple candidates at any level: **the silent-wrong-answer risk set**
- Stems with zero matches: the unresolvable set

This second simulation runs against the **P-intersect** population. Its numbers are the ones that drive the Path 1 vs Path 2 decision. The within-repo collision report is background context; the source-stem report is the call.

Report format for the within-repo collision analysis (abbreviated):

```
## L3 tail-match ambiguities (20 rows)

- project tail: `.scheduler` → candidates:
    - cdh-exportscheduler-nav1-az-cd   AppName=Lighthouse1.Exports.Scheduler
    - cdh-batchscheduler-az-cd          AppName=WexHealth.Batch.Scheduler
    - pts-cdb-scheduler-az-cd           AppName=WexHealth.PTS.Scheduler
  → THREE candidates; L3 cannot disambiguate
```

### 5.7 Temporal diff (optional)

When `--prev-snapshot <path>` is provided, load the earlier run's `01_raw_crawl.csv` and compute a change report:

- Pipelines added (new pipeline dirs)
- Pipelines removed (deleted pipeline dirs)
- Pipelines whose extracted AppName changed
- Pipelines whose extracted assembly name changed
- Pipelines whose pattern classification changed (e.g., Pattern D → Pattern A because someone added a host.json)
- Batch pipelines whose job list changed (additions, removals, renames)

**Why this matters:** Path 2 (enriched CSV) depends on the crawler's output being stable enough that a committed CSV remains correct for months. A temporal diff across two snapshots — HEAD now and HEAD 30 days ago, or two environment branches — quantifies that assumption. Large churn in either the AppName column or the pattern column invalidates Path 2 without a regeneration cadence commitment.

If `--prev-snapshot` is not provided, the report is not generated. This is an opt-in because producing two snapshots requires either waiting between runs or checking out two revs of the config repo.

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

### 6.6 `06_temporal_diff.md` (optional — triggered by `--prev-snapshot`)

```markdown
# Temporal Stability Diff

**Previous snapshot:** <path, timestamp if derivable>
**Current snapshot:** <timestamp>

## Summary
- Pipelines added: ___
- Pipelines removed: ___
- AppName changes: ___
- Assembly changes: ___
- Pattern re-classifications: ___
- Batch job list changes: ___ (affecting ___ pipelines)

## Detailed churn
<per-pipeline diff, grouped by change type>

## Path 2 viability signal
<verdict:
  - Total churn <5% → Path 2 viable, annual regeneration cadence
  - 5-15% → Path 2 viable, quarterly regeneration cadence
  - >15% → Path 2 not viable on stability grounds; runtime matcher required>
```

### 6.7 `07_source_project_match.md` (optional — triggered by `--source-stems`)

```markdown
# Source Project → Pipeline Match Simulation (P-intersect)

**Source stems supplied:** ___
**Successfully resolved (any level):** ___ (__%)
**Unresolved:** ___ (__%)

## L1 exact matches (___ of ___)
<sample, full list linked>

## L2 Jaccard matches (___ of ___)
<table: stem | matched_app | jaccard_score | candidate_count>

## L3 tail matches (___ of ___)
<table: stem | tail_token | matched_app | candidate_count>

## Ambiguous resolutions — SILENT WRONG-ANSWER RISK (___ of ___)
<full list: stem | levels_attempted | all_candidates | why_ambiguous>

## Unresolved stems (___ of ___)
<full list: stem | best_partial_match_if_any>
```

---

## 7. Decision Criteria

After the reports are generated and reviewed, one of three paths.

### Thresholds below are initial proposals, not absolutes

Revise them once the spike output shows the actual distribution. If an observed rate falls within a few points of any threshold, review adjacent path triggers before deciding — the numbers exist to structure the conversation, not to automate the decision.

All rates are measured against **P-intersect** when `--source-stems` is provided, otherwise against **P-resolvable** with an explicit caveat that the decision is being made on proxy data.

### Path 1 — Build full plan as written

**Triggers (all must hold):**
- L1 exact-match rate **< 90%**
- L2+L3 cascade usefully resolves ≥50% of non-L1 cases with ≤5% ambiguous/wrong
- Pattern taxonomy A/B/C/D covers ≥95% of pipelines
- ≥20 crawler-only mappings (CSV misses) — proves the crawler delivers value
- Edge cases (comments, placeholders) behave as the plan predicts

### Path 2 — Enriched-CSV approach

**Triggers:**
- L1 exact-match rate **≥ 90%**
- L2/L3 cascade adds < 10% coverage OR has unacceptable ambiguity
- Temporal diff run (`--prev-snapshot`) shows churn < 15% with a matching regeneration cadence committed to. If `--prev-snapshot` was NOT run, Path 2 selection is conditional on running the temporal diff before shipping.

**Single threshold at 90%** — no decision gap between Path 1 and Path 2. If L1 is exactly 90%, read the next triggers (cascade quality and temporal churn) to break the tie; they point to the same answer in the vast majority of cases.

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

The config repo contains WEX internal app and pipeline names.

**First decide whether redaction is necessary at all.** If the spike output stays inside WEX walls and reviewers already have repo access, the names are not secret and redaction is theater. In that case, skip the redaction feature entirely and mark output files "internal only" in their headers. **This is the default.**

If redaction is genuinely needed (external consulting discussion, reviewers without repo access, attachment to a public issue tracker):

- Do NOT use plain `sha1(name)[:8]` — at 32 bits of entropy drawn from ~500 names in predictable corporate namespaces (`WexHealth.*`, `Lighthouse1.*`, `cdh-*-az-cd`), a dictionary attack recovers most real names trivially. Deterministic hashing also preserves the relationship graph across leaks, so two separate leaks can be correlated even when neither one exposes raw names.
- Use HMAC with a run-specific secret: `hmac.new(secret, name.encode(), 'sha256').hexdigest()[:8]`. The secret lives in `SPIKE_REDACT_SECRET` env var and rotates per run. Never commit the secret.
- This breaks both dictionary attacks and cross-run correlation.
- Redaction must be applied to ALL output files, not just `01_raw_crawl.csv` — the `.md` reports embed sample names from the data.
- Document which secret was used where (separately, outside the redacted output) so reviewers can ask "what's this hash?" if needed and the answer is retrievable.

**Default: no redaction, outputs marked "internal only."** Opt in with `--redact` only when genuinely needed.

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

Whichever path is selected, the spike leaves artifacts that feed it.

### Path 1 — fixture readiness is a triple, not a single file

The runtime matcher needs real test fixtures. The spike does not produce a complete fixture by itself — `01_raw_crawl.csv` is only the right-hand side of the match. A Path 1 fixture is the triple:

1. `01_raw_crawl.csv` — crawled config-repo data (the match targets)
2. The `--source-stems` file used by the spike — the inputs
3. `expected_matches.csv` — a human-reviewed pairing of each stem to its correct pipeline(s)

Only the complete triple is a fixture. Plan for a half-day of manual review to produce `expected_matches.csv` from the spike's `07_source_project_match.md` output.

### Path 2 — cadence follows churn

The crawler gets promoted from `tools/spike/` to `tools/generate_pipeline_csv.py`. Reports become CI outputs. The `06_temporal_diff.md` verdict directly sets the regeneration cadence:

- Churn < 5% → regenerate annually
- Churn 5-15% → regenerate quarterly
- Churn ≥ 15% → stability disqualifies Path 2; reopen the Path 1 decision

### Path 3 — feeds plan v2

Reports are attached as appendix to a revised `APP_CONFIG_REPO.md v2`. The revision should specifically address which plan assumptions the spike falsified and what structural changes the matcher needs.

In all three cases, nothing the spike produces is wasted.
