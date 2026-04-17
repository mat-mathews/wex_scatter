# APP_CONFIG Repo Spike — Run 1 Results & Analysis

Companion to [APP_CONFIG_REPO_SPIKE.md](APP_CONFIG_REPO_SPIKE.md) (the plan) and [APP_CONFIG_REPO.md](APP_CONFIG_REPO.md) (the full design this spike is gating).

Captures the first evidence pass: what was run, what the five artifacts in `spike_output/` say, where they leave the decision, and what has to happen before a Path 1 / Path 2 / Path 3 call can be made.

---

## 1. Run context

**Script:** `tools/spike/config_repo_crawl.py`
**Date of run:** 2026-04-16
**Invocation (via Docker from Git Bash on Windows):**

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd)":/workspace \
  -v /c/_/health-benefits-app-config:/config:ro \
  python:3.12-slim \
  python /workspace/tools/spike/config_repo_crawl.py \
    --app-config-path /config \
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv \
    --output-dir /workspace/spike_output
```

Note on `MSYS_NO_PATHCONV=1`: without it, Git Bash rewrote `/workspace/...` to `//C:/Program Files/Git/workspace/...` inside the container, producing `can't open file` errors. Documented here for the next runner.

**Inputs supplied:**

- `--app-config-path` → local clone of `health-benefits-app-config`
- `--hand-csv` → `examples/pipeline_to_app_mapping.csv` (demo-only; see §4.3)

**Inputs *not* supplied (opt-in per plan §4):**

- `--source-stems` → no P-intersect simulation → no `07_source_project_match.md`
- `--prev-snapshot` → no temporal stability data → no `06_temporal_diff.md`
- `--redact` → internal-only output (the plan's default)

---

## 2. Why this spike exists (short form)

The full plan in `APP_CONFIG_REPO.md` depends on six assumptions about the real config repo that can only be tested against it:

1. Pattern taxonomy A/B/C/D is accurate and complete
2. `wexhealth.host.json` is present in enough pipelines to be the primary signal
3. The L1→L2→L3 matcher cascade is needed (L1 alone is insufficient)
4. Org prefixes are limited to `wexhealth.` / `wex.` / `lighthouse1.` / `lh1.`
5. Jaccard threshold 0.5 at L2 fires on useful cases without false positives
6. Nav fan-out groups are correctly identifiable by the `-navN-az-cd` pattern

The spike produces ground-truth evidence for each assumption and funnels the result into one of three decision paths (plan §7):

- **Path 1** — build the full runtime matcher as written
- **Path 2** — enriched-CSV approach; commit the crawler's output instead of a runtime matcher
- **Path 3** — re-scope the plan because the data falsifies its structure

Anti-goal reminder: the spike ships no production code. Its output is data for humans to read.

---

## 3. Headline numbers

| Metric | Value | Source |
|---|---|---|
| Total rows crawled (pipelines + batch jobs) | **364** | `02_pattern_taxonomy.md` |
| Rows with a resolvable config signal | **296 (81.3%)** | A + B + C + D_PARTIAL |
| Rows resolved *only* by heuristic (pipeline dir name) | **100 (27.5%)** | resolution_source distribution |
| Rows with `host_json` AppName extracted | **228 (62.6%)** | resolution_source distribution |
| Nav fan-out groups detected | **2** (15 + 25 pipelines) | `02_pattern_taxonomy.md` |
| `//` comments in host.json (JSONC) | **78 of 364 (21.4%)** | `05_edge_cases.md` |
| `{AppName}` placeholder occurrences | **115** | `05_edge_cases.md` |
| Malformed host.json (AppName regex failed) | **3** | `05_edge_cases.md` |
| Unknown org-prefix families observed | **27** (57+ pipelines) | `05_edge_cases.md` |
| Within-repo ambiguities (collision analysis) | **204** (L1: 174, L2: 30, L3: 0) | `04_ambiguity_report.md` |
| Hand-CSV agreement / disagreement | **0 / 0** (demo CSV only) | `03_csv_diff.md` |

---

## 4. Assumption-by-assumption findings

### 4.1 Assumption 1 — Pattern taxonomy (holds, with caveat)

From `02_pattern_taxonomy.md`:

| Pattern | Count | % | Meaning |
|---|---|---|---|
| A | 173 | 47.5% | Single-app with host.json (non-nav) |
| B | 22 | 6.0% | Batch fan-out (per-job host.json) |
| C | 36 | 9.9% | Nav fan-out (subset of A) |
| D_PARTIAL | 65 | 17.9% | No host.json, has `.config` |
| D_EMPTY | 50 | 13.7% | No resolvable signals |
| MISSING_ENV | 18 | 4.9% | No `production/` dir |

A + B + C + D_PARTIAL = 296/364 (**81.3%**) have a concrete config-file signal. The plan's §7 trigger of "≥95% fit the taxonomy" is trivially met because D_EMPTY and MISSING_ENV are themselves taxonomy buckets — but **68 rows (18.7%) produce only a heuristic or nothing**. That is the population scatter cannot resolve via config-repo data alone.

**Read:** taxonomy structure is right; the D_EMPTY/MISSING_ENV tail is larger than the plan's optimistic framing implied and deserves an explicit UX decision (Unmapped? Best-guess heuristic? Error?).

### 4.2 Assumption 2 — `host.json` primacy (mostly holds)

`host_json` resolves 228/364 (62.6%). Adding `web_config` (10) and `exe_config` (26) brings signal-based resolution to 264/364 (**72.5%**). The remaining 100 resolve only through the pipeline directory name (`heuristic`), which is not independent evidence — it's just the deployment's own filename.

**Read:** host.json is correctly identified as the primary signal but is not sufficient alone. The web.config and exe.config extractors pull their weight (36 additional resolutions) and should stay in the plan.

### 4.3 Assumption 3 — Cascade need (holds, but collision data is structural)

`04_ambiguity_report.md` shows 204 probes with at least one other pipeline colliding:

- **L1 exact-normalize collisions: 174.** Inspection of the raw entries shows these are dominated by three structural classes, not semantic ambiguity:
  - **Nav fan-out** — the 15-member `cdh-cdex-fileloader-navN` family and the 25-member `cdh-exportscheduler-navN` family all share a single AppName (`WexHealth.CDH.FileImport.FileLoaderService` and `Lighthouse1.Exports.Scheduler` respectively). Each member collides with all others → contributes ~40+ L1 collision rows.
  - **`-az-cd` / `-cd` deployment pairs** — same app, two pipeline variants (e.g., `cdh-adminportal-az-cd` vs `cdh-adminportal-cd`, `cdh-authservice-az-cd` vs `cdh-authservice-cd`, `cdh-cdex-importmanager-az-cd` vs `cdh-cdex-importmanager-cd`). These are duplicates, not genuine matcher ambiguities.
  - **Pattern-B batch fan-out** — e.g., `pts-cdb-sandboxservice1-az-cd` through `pts-cdb-sandboxservice8-az-cd` each extract the same AppName from their own host.json.
- **L2 Jaccard ≥0.5 collisions: 30.** These are semantic over-fire. The clearest example: the `cdh-*-api` cluster (`cdh-audit-tracking-az-cd`, `cdh-benefit-analytics-az-cd`, `cdh-branding-api-az-cd`, `cdh-dataapi-az-cd`, `cdh-employeruser-az-cd`) all Jaccard-match each other because their normalized names share `wexhealth`, `cdh`, `apps`, `web`, `api` tokens. Another: `ps-ipwhitelist-az-cd` (`WEXHealth.Enterprise.IPWhitelist.Service`) matches all eight `ps-configuration-service-*` pipelines.
- **L3 tail-2-token collisions: 0.** Every tail collision had already been captured at L2; nothing unique reached L3.

**Read:**
- Assumption 3 (L1 alone insufficient) ✓ — but the L1 collision count is largely a measurement of structural duplication, not matcher weakness. Any runtime matcher must first de-duplicate via a "canonical pipeline group" concept (collapse `-az-cd`/`-cd` pairs, collapse nav families, collapse Pattern-B jobs under their parent pipeline) before counting L1 collisions meaningfully.
- Assumption 5 (Jaccard 0.5 is right) looks **partially false** — 30 L2 firings in a 364-pipeline repo is a lot, and the example clusters above are clearly false positives in any realistic matcher use case. Worth re-running at 0.6 and 0.7 to see how the numbers move.
- L3's zero count is not evidence L3 is unneeded — it's evidence L2 at 0.5 is eating everything L3 would have caught. If L2 is tightened, L3 counts will rise.

### 4.4 Assumption 4 — Known org prefixes (falsified)

`05_edge_cases.md` lists **27 unknown prefix families** covering at least 57 pipelines. Top offenders:

| Prefix | Count |
|---|---|
| `taskhost.` | 14 |
| `rdcpoint.` | 6 |
| `smartcommute.` | 5 |
| `dbi.` | 5 |
| `lh1ondemand.` | 3 |
| `sandboxcontainer.` | 2 |
| `custodianfileimport.` | 2 |
| `itemlookupservice.` | 2 |
| `merchantlocator.` | 2 |
| `skuleveldecisioningapi.` | 2 |
| `bennycentral.` | 2 |
| (16 more, 1 pipeline each) | 16 |

These are not typos or outliers — they are genuine AppNames that do not sit under the assumed `WexHealth.` / `Lighthouse1.` / `wex.` / `lh1.` umbrella. Some look like legacy naming (`lh1ondemand.`, `taskhost.`, `rdcpoint.`), others look like single-word product names (`merchantlocator`, `itemlookupservice`, `imagegetter`).

**Read:** the plan's `KNOWN_PREFIXES` list is wrong. Two options:

1. **Expand** the list to include the families with ≥3 occurrences (`taskhost.`, `rdcpoint.`, `smartcommute.`, `dbi.`, `lh1ondemand.`), and let single-word names through the normalizer untouched.
2. **Remove the prefix-stripping concept entirely** and normalize on tokens without privileging a leading component. Cleaner; forces the matcher to rely on tail-token overlap instead of leading-org agreement.

Either way, the decision changes how `normalize()` works across the whole matcher stack — it is not a cosmetic tweak.

### 4.5 Assumption 5 — Jaccard 0.5 appropriateness (partially falsified)

See §4.3 above. The 30 L2 firings include at least two clear false-positive clusters. The threshold is a tuning parameter, not a law; the spike is saying 0.5 is too loose for this naming style. Suggested follow-up: add a `--l2-threshold` flag to the script (or temporarily hard-code 0.6 and 0.7) and re-run. Expect L2 counts to drop and L3 counts to rise.

### 4.6 Assumption 6 — Nav fan-out detection (holds)

Two nav groups detected, both clean:

- `cdh-cdex-fileloader` — 15 pipelines, shared AppName `WexHealth.CDH.FileImport.FileLoaderService`
- `cdh-exportscheduler` — 25 pipelines, shared AppName `Lighthouse1.Exports.Scheduler`

No "MIXED" groups, no would-be-group warnings. The `_NAV_RE` regex (`^(.+?)-nav\d+(-az-cd|$)`) works.

**Read:** nav detection is fine. Keep it.

---

## 5. Edge cases — required behavior for the runtime matcher

### 5.1 JSONC comments (21.4% of host.json)

78 of 364 host.json files contain `//` comments. A strict `json.load()` would reject one in five files. The spike script dodges this by using a regex extractor, but the full plan's runtime matcher must either:

- Use a JSONC-tolerant parser (`jsonc-parser`, `json5`, or strip `//` lines + trailing commas before parsing), or
- Keep regex extraction (accepting the risk of malformed AppName values sneaking through)

This is not optional. Call it out in the implementation task list.

### 5.2 `{AppName}` placeholders (115 occurrences)

Confirms plan §7.6's collision risk. Some host.json files contain literal `{AppName}` templating that has not been substituted. A naive regex would extract `{AppName}` as a valid name. The matcher must reject any extracted name that matches `^\{[A-Za-z]+\}$`.

### 5.3 Malformed host.json (3 files)

- `cdb-sandboxcontainer-az-cd`
- `pts-cdb-sandboxcontainer-az-cd`
- `wexhealth.card-activation-portal-az-cd / config`

Rate is <1%. Log and skip; don't fail the whole crawl.

### 5.4 Lowercase `appName` (0 occurrences)

A non-issue in this repo. Can drop the case-variation branch from the plan.


## 6. Pipeline family distribution

From `05_edge_cases.md`:

| Family | Pipelines | Sample |
|---|---|---|
| `cdh` | 220 | `cdh-EnrollmentImportService-az-cd` |
| `pts` | 67 | `pts-abp-otcpoint-az-cd` |
| `direct` | 35 | `direct-auth-api-az-cd` |
| `ps` | 18 | `ps-communications-brokerapi-az-cd` |
| `wexhealth.card` | 12 | `wexhealth.card-activation-portal-az-cd` |
| `crs` | 4 | `crs-ssrs-import-server` |
| `cdb` | 3 | `cdb-paymentservices-az-cd` |
| `devops` | 2 | `devops-dotnet-template` |
| `wexhealth` | 1 | `wexhealth-card-app-cardadministrationportal-az-cd` |
| `azdo` | 1 | `azdo-tool-az-cicd` |
| `UploadCDExTemplateExternalTool` | 1 | `UploadCDExTemplateExternalTool` |

**Read:** `cdh` accounts for 60% of pipelines. Matcher tuning that regresses behavior on `cdh-*` pipelines will show up as a large swing in overall success rate; tune against the other families separately rather than averaging.

---

## 7. What the output does NOT tell us

The plan's §5.0 is explicit that every rate must be anchored to one of three populations — **P-all**, **P-resolvable**, or **P-intersect** — and that the Path 1 vs Path 2 vs Path 3 decision is only meaningful against **P-intersect** (matcher cascade applied to real source-project `.csproj` stems).

This run measured against **P-resolvable** only. The specific gaps:

### 7.1 No `--source-stems` supplied → no P-intersect data

All 204 ambiguities in `04_ambiguity_report.md` are within-repo collisions: "if pipeline X's AppName were used as a probe, which other pipelines would also match?" This is collision-floor data, not match-quality data. Before the decision is made, a real source-stem file must be produced and the spike re-run. Per the plan §10.1, that means:

1. Extract `.csproj` filename stems from the WEX source tree
2. Run the spike with `--source-stems <file>` → generates `07_source_project_match.md`
3. Human-review the output to produce `expected_matches.csv` (plan estimates half a day)

### 7.2 No `--prev-snapshot` supplied → no temporal stability data

`06_temporal_diff.md` was not generated. The plan's §7 Path 2 trigger requires churn < 15% between snapshots. Without this, Path 2 is not selectable even if the other triggers fire. A follow-up run against a prior revision of `health-benefits-app-config` (e.g., HEAD~30-days or a sibling environment branch) closes that gap.

### 7.3 Hand CSV comparison is not meaningful

`examples/pipeline_to_app_mapping.csv` contains 5 placeholder rows (all `galaxyworks.*`) — these are sample app names for scatter's own demo, not a real hand-maintained mapping of WEX pipelines. Consequently:

- Agreement = 0 is an artifact of the demo CSV, not signal
- Disagreement = 0 is an artifact of the demo CSV, not signal
- The 228 "Crawler-only" rows in `03_csv_diff.md` are the crawler's raw output, not "free wins against hand knowledge"
- The 5 "CSV-only" rows (the `galaxyworks.*` entries) are expected — they aren't in the config repo at all

To make `03_csv_diff.md` meaningful, the actual WEX hand-maintained pipeline mapping (wherever that lives) needs to be supplied as `--hand-csv` in a follow-up run.

---

## 8. Tentative read against the decision criteria

Against the plan's §7 triggers, without P-intersect data:

| Path 1 trigger | Observed | Status |
|---|---|---|
| L1 exact-match rate < 90% | unknown (no P-intersect) | **blocked** |
| L2+L3 resolves ≥50% of non-L1 with ≤5% ambiguous | unknown (no P-intersect) | **blocked** |
| Taxonomy A/B/C/D covers ≥95% | 95.1% (all rows bucketed); 81.3% on real signals | borderline |
| ≥20 crawler-only mappings in CSV diff | n/a (demo CSV) | **blocked** |
| Edge cases behave as plan predicted | JSONC rate higher than implied; KNOWN_PREFIXES falsified | partial |

Against the Path 2 triggers:

| Path 2 trigger | Observed | Status |
|---|---|---|
| L1 exact-match rate ≥ 90% | unknown | **blocked** |
| Temporal churn < 15% | unknown (no `--prev-snapshot`) | **blocked** |

Against the Path 3 triggers:

| Path 3 trigger | Observed | Status |
|---|---|---|
| Taxonomy misses >5% of pipelines | No — all rows bucket into taxonomy | does not fire |
| Edge cases worse than anticipated | `//` comments at 21% is higher than "occasional"; `KNOWN_PREFIXES` is falsified | **partial fire** |
| Hand CSV systematically more correct than crawler in ways plan ignores | n/a (no real CSV) | **blocked** |

### 8.1 Tentative recommendation

**The spike is not yet complete enough to make the Path 1 / Path 2 / Path 3 call.** Two of the three gating inputs (`--source-stems`, `--prev-snapshot`) were not supplied, and the third (`--hand-csv`) was the demo file.

The Run 1 output is nonetheless useful as a **sanity check and design input**:

- The spike script runs against a real 364-row config repo without crashing
- Pattern taxonomy, nav detection, and basic signal extraction are all working
- Two plan assumptions (4: `KNOWN_PREFIXES`, 5: Jaccard 0.5) are already showing cracks and should be revisited *regardless* of which path is chosen
- One edge case (JSONC comments at 21.4%) is material enough to require explicit handling in the runtime matcher, not a best-effort regex dodge

### 8.2 Preconditions for a real decision

Before a Path call is defensible, the spike must be re-run with:

1. **A real `--source-stems` file** derived from the WEX source tree — non-optional; without it, the cascade numbers are collision-floor not match-quality
2. **A real `--hand-csv`** (or a documented acknowledgement that no hand mapping exists, in which case the CSV-diff artifact is retired)
3. **A `--prev-snapshot`** captured against a prior revision of the config repo — required only if Path 2 is under serious consideration

---

## 9. Concrete follow-up actions

Ordered by effort. None of these are committed work yet — they are the candidate next steps if and when the spike is extended.

### 9.1 Cheap (minutes)

- **Expand `KNOWN_PREFIXES`** in `tools/spike/config_repo_crawl.py` to include `taskhost.`, `rdcpoint.`, `smartcommute.`, `dbi.`, `lh1ondemand.` and re-run. Expect the "unknown prefixes" tail in `05_edge_cases.md` to drop ~33 pipelines.
- **Add a `--l2-threshold` flag** (default 0.5). Re-run at 0.6 and 0.7. Compare L2 / L3 counts in `04_ambiguity_report.md`. Use the lowest threshold at which the `cdh-*-api` cluster stops Jaccard-matching itself.
- **Add a `{AppName}` placeholder rejection** to `extract_app_name()` so the regex does not return template literals as values.

### 9.2 Medium (hours)

- **Produce a real `--source-stems` file.** Grep the WEX source tree for `.csproj` filenames, dedupe, write to `source_stems.txt`, run the spike. Review `07_source_project_match.md`.
- **Produce `expected_matches.csv`** by human-reviewing the above. Per plan §10.1, this is the right-hand side of a real fixture.
- **Capture a `--prev-snapshot`** by re-running against `git log --before=30.days.ago` revision of the config repo, or against a `qa` or `staging` environment directory (different branch of the same repo).

### 9.3 Requires design decision first

- **Canonical pipeline group** concept (§4.3 read). Before counting L1 collisions for real, decide how to collapse `-az-cd`/`-cd` pairs, nav families, and Pattern-B job fan-out into one logical pipeline. This changes the matcher's return type (single pipeline → group of pipelines) and is not a tweak.
- **Prefix handling** — expand `KNOWN_PREFIXES` (cheap) or drop prefix stripping entirely (cleaner, but changes normalization semantics everywhere).

---

## 10. Pointers to the raw artifacts

All artifacts are in `spike_output/` (gitignored — see plan §8.4). Re-generate by re-running the script.

| File | Contents |
|---|---|
| `spike_output/01_raw_crawl.csv` | 364 rows, one per pipeline (or per Pattern-B job); full signal extraction per row |
| `spike_output/02_pattern_taxonomy.md` | Pattern A/B/C/D/D_PARTIAL/D_EMPTY/MISSING_ENV counts; nav group listing; resolution-source distribution |
| `spike_output/03_csv_diff.md` | Hand CSV vs crawler comparison (invalid this run — demo CSV) |
| `spike_output/04_ambiguity_report.md` | Within-repo L1/L2/L3 collisions |
| `spike_output/05_edge_cases.md` | `//` comments, `{AppName}` placeholders, unknown prefixes, malformed host.json, pipeline families |

`06_temporal_diff.md` and `07_source_project_match.md` were not produced this run (see §7).