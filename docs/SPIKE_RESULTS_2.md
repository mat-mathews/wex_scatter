# APP_CONFIG Repo Spike — Run 2 Results: Threshold Sweep & Prefix Expansion

Companion to:
- [APP_CONFIG_REPO_SPIKE.md](APP_CONFIG_REPO_SPIKE.md) — the plan
- [APP_CONFIG_REPO.md](APP_CONFIG_REPO.md) — the full design this spike is gating
- [APP_CONFIG_REPO_SPIKE_RESULTS.md](APP_CONFIG_REPO_SPIKE_RESULTS.md) — Run 1 results

This run executes the cheap follow-ups from Run 1 §9.1: expand `KNOWN_PREFIXES`, add a `--l2-threshold` flag, and sweep the threshold to confirm or refute the partial falsification of plan assumption 5.

---

## 1. Run context

**Script:** `tools/spike/config_repo_crawl.py` (modified since Run 1)
**Date of run:** 2026-04-17
**Two runs executed:**

```bash
# Run 2a: threshold 0.5 (default; kept for direct comparison with Run 1)
docker run --rm \
  -v "$(pwd)":/workspace \
  -v /c/_/health-benefits-app-config:/config:ro \
  python:3.12-slim \
  python /workspace/tools/spike/config_repo_crawl.py \
    --app-config-path /config \
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv \
    --output-dir /workspace/spike_output_50

# Run 2b: threshold 0.7 (the candidate replacement value)
docker run --rm \
  -v "$(pwd)":/workspace \
  -v /c/_/health-benefits-app-config:/config:ro \
  python:3.12-slim \
  python /workspace/tools/spike/config_repo_crawl.py \
    --app-config-path /config \
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv \
    --output-dir /workspace/spike_output_70 \
    --l2-threshold 0.7
```

(Both prefixed with `MSYS_NO_PATHCONV=1` on Git Bash; see Run 1 §1.)

**Inputs supplied / withheld:** unchanged from Run 1. `--source-stems` and `--prev-snapshot` still not provided, so P-intersect data and temporal stability data are still missing. Hand CSV is still the demo file.

---

## 2. Script changes since Run 1

Two changes, both motivated by Run 1 §9.1 cheap follow-ups:

### 2.1 `KNOWN_PREFIXES` expanded (commit-time change)

The 5 unknown-prefix families with ≥3 occurrences from Run 1's `05_edge_cases.md` were added to the normalizer:

```python
KNOWN_PREFIXES = (
    "wexhealth.", "wex.", "lighthouse1.", "lh1.",
    # Added after Run 1 — covers top 5 families (33+ pipelines)
    "taskhost.", "rdcpoint.", "smartcommute.", "dbi.", "lh1ondemand.",
)
```

This affects `normalize()`, which is called from every cascade-level matcher. Names that previously normalized as `taskhost.eventintegration` (prefix unknown, kept as-is) now normalize as `eventintegration` (prefix stripped). Smaller token sets → fewer Jaccard matches above any threshold → lower L2 collision counts even at the unchanged 0.5 default.

### 2.2 `--l2-threshold` flag plumbed end-to-end

- New constant `DEFAULT_L2_THRESHOLD = 0.5`
- New CLI flag `--l2-threshold` (defaults to the constant)
- `find_within_repo_ambiguities()` and `simulate_source_match()` accept `l2_threshold` keyword
- `write_ambiguity_report()` accepts `l2_threshold` and prints it in the report header (visible in the diff as `**L2 Jaccard threshold:** 0.7`)

**Known bug (not yet fixed):** `write_source_match()` (writer for `07_source_project_match.md`, only fires with `--source-stems`) hardcodes `≥0.5` in its level-summary label even when a different threshold is in use. Doesn't affect Run 2 because `--source-stems` was not supplied, but will silently mislabel future runs that combine the two flags. Tracked as a follow-up.

---

## 3. Headline numbers

| Metric | Run 1 (0.5, old prefixes) | Run 2a (0.5, expanded prefixes) | Run 2b (0.7, expanded prefixes) |
|---|---|---|---|
| Total rows | 364 | 364 | 364 |
| Total within-repo ambiguities | 204 | **203** | **175** |
| L1 exact-normalize collisions | 174 | 174 | 174 |
| L2 Jaccard collisions | 30 | **29** | **1** |
| L3 tail-2-token collisions | 0 | 0 | 0 |

The 364-row crawl, the 174 L1 collisions, and the 0 L3 collisions are all unchanged across runs. Every difference is concentrated in L2.

---

## 4. Effect attribution — separating the two changes

The drop from 204 → 175 has two independent contributors:

### 4.1 KNOWN_PREFIXES expansion alone (Run 1 → Run 2a, both at 0.5): −1

One L2 case fell out of the ambiguity report between Run 1 and Run 2a even though the threshold did not change. Mechanism: names previously containing a leading `taskhost.` / `rdcpoint.` / `smartcommute.` / `dbi.` / `lh1ondemand.` token now have it stripped. Their token sets shrink, which lowers their Jaccard similarity against other names. One previously-borderline L2 hit at 0.5 fell below threshold and disappeared from the ambiguity list.

The effect is small at threshold 0.5 because the dropped prefix tokens were noise tokens shared by few other names. The same change at threshold 0.7 would have a smaller effect still (high-overlap pairs stay high-overlap) — but the prefix change does shift several individual Jaccard scores. The honest reading: the prefix expansion is a normalization correctness fix more than a noise-reduction lever; its main value is in `05_edge_cases.md` (the unknown-prefix tail should now drop from 27 families to ~22 — recommend confirming on the next run).

### 4.2 Threshold tightening alone (Run 2a → Run 2b, both with expanded prefixes): −28

At threshold 0.7, **only one L2 case survives**:

```
cdh-employerportal-az-cd  probe=WexHealth.Apps.Web.EmployerPortal
    → cdh-authservice-az-cd, cdh-authservice-cd
```

The other 28 L2 cases that existed at 0.5 disappeared. They are exactly the false-positive clusters Run 1 §4.3 called out:

| Cluster (Run 1 example) | Behavior at 0.5 | Behavior at 0.7 |
|---|---|---|
| `cdh-*-api` (audit-tracking, benefit-analytics, branding, cwsrest, dataapi, employeruser) | 5 cross-firings, all sharing `wex/health/cdh/apps/web/api` tokens | gone |
| `ps-ipwhitelist-az-cd` matching all 8 `ps-configuration-service-*` | matches 8 candidates | gone |
| `pts-cdb-*` web cluster (carriernotificationservice ↔ cobraadminapi ↔ cobrapoint ↔ cobrapointwebapi ↔ employerapi ↔ letterservice ↔ memberapi) | bidirectional clique | gone |
| `pts-cdb-*` batch cluster (capitationreport, exportserver, cobracarriernotificationbounceprocessor, jobqueuejq1-14, sandboxservice1-8) | bidirectional clique | gone |
| `cdh-taskhost-*` family (queuelistener, taskhost-cd, debitcardevent) over-firing | 3 cases | gone |
| `cdh-claimslink-portal` ↔ `cdh-newemployersetup` ↔ `cdh-consumerinvestment-portal` | bidirectional | gone |
| `cdh-cardtransactionservice-api` ↔ `cdh-debitcard-mailtracing-api` ↔ `cdh-hsa-strangler-api` ↔ `cdh-investment-api` ↔ `cdh-smartcommute-webapi` | bidirectional | gone |
| `cdh-demo-api`, `direct-cdh-api` matching by short shared token | gone | gone |

The remaining `cdh-employerportal-az-cd ↔ cdh-authservice-*` is plausibly a **real** ambiguity — the auth service is the auth half of the employer portal. A matcher returning both as candidates and asking the human to pick is reasonable. Tightening further to 0.8 would likely lose this signal too.



---

## 5. Diff against Run 1 — what changed in `04_ambiguity_report.md`

Direct `diff spike_output_50/04_ambiguity_report.md spike_output_70/04_ambiguity_report.md` (Run 2a vs Run 2b, both with expanded prefixes):

```
4c4
< **L2 Jaccard threshold:** 0.5
---
> **L2 Jaccard threshold:** 0.7
7c7
< Total probes with ambiguity: **203**
---
> Total probes with ambiguity: **175**
37,63c37,38
< ### L2 (29)  [27 lines of L2 ambiguity entries]
---
> ### L2 (1)
> - cdh-employerportal-az-cd probe=WexHealth.Apps.Web.EmployerPortal
>   → cdh-authservice-az-cd, cdh-authservice-cd
```

L1 section is byte-identical between the two runs — confirming the threshold flag is doing exactly what it claims and not affecting any other cascade level.

---

## 6. Bearing on the plan's assumptions

### 6.1 Assumption 4 (KNOWN_PREFIXES limited to wexhealth/wex/lighthouse1/lh1) — partially repaired

Run 1 falsified this. Run 2 partially repairs it by adding the top 5 unknown families into the constant. Remaining tail (22 families with 1-2 occurrences each, plus the 16 single-pipeline families) is small enough that the runtime matcher could either:

1. Add a prefix-discovery pass that auto-detects org prefixes from the corpus rather than requiring a hand-maintained list, or
2. Accept that ~25 pipelines normalize without prefix stripping and rely on token-overlap matchers to handle them anyway

Decision can defer until P-intersect data is available — the repair is good enough to move on for now.

### 6.2 Assumption 5 (Jaccard 0.5 fires on useful cases without false positives) — falsified, with concrete replacement

Run 1 marked this "partially falsified." Run 2 makes it **fully falsified at 0.5** and shows that **0.7 is a defensible default**:

- 0.5 fires 29× (28 of which are clearly false positives by inspection)
- 0.7 fires 1× (the one survivor is borderline-genuine)

Recommended action: change `DEFAULT_L2_THRESHOLD` from 0.5 to 0.7 in the script. The runtime matcher in the full plan should adopt the same value as its starting point and re-tune only after P-intersect data is available.

**Caveat:** L3 still shows 0 collisions in both runs. That is not yet evidence L3 is unneeded. The within-repo collision space is small at threshold 0.7; whether L3 helps real source-project matching against this index will only be answered when `--source-stems` runs against actual `.csproj` inputs from the WEX source tree.

### 6.3 No effect on other assumptions

Assumptions 1, 2, 3, and 6 are unchanged from Run 1 — the script changes were scoped to normalization and L2 only. Pattern taxonomy, host.json primacy, cascade-need, and nav-detection findings stand as documented in Run 1 §4.1, 4.2, 4.3, and 4.6 respectively.

---

## 7. Updated decision-criteria status

Compared with the Run 1 §8 table, only one cell moves:

| Trigger | Run 1 status | Run 2 status |
|---|---|---|
| Path 1: edge cases behave as plan predicted | partial (KNOWN_PREFIXES falsified, JSONC higher than implied) | **partial — KNOWN_PREFIXES repaired, JSONC issue unchanged** |
| All other Path 1 / Path 2 / Path 3 triggers | unchanged | unchanged (still blocked on `--source-stems` and `--prev-snapshot`) |

**The Path 1 / Path 2 / Path 3 decision is still blocked on the same two missing inputs.** Run 2's value is in tightening the matcher's default behavior so that whichever path is chosen, it starts from a saner threshold and a more complete prefix list.

---

## 8. Outstanding follow-ups

From Run 1 §9, status update:

### 8.1 Cheap (minutes) — partially done

- ✅ Expand `KNOWN_PREFIXES` (this run)
- ✅ Add `--l2-threshold` flag (this run)
- ⬜ Add `{AppName}` placeholder rejection in `extract_app_name()` — still pending; 115 occurrences in Run 1 / Run 2 confirm the risk is real
- ⬜ Fix the hardcoded `≥0.5` label bug in `write_source_match()` — see §2.2 above

### 8.2 Medium (hours) — unchanged

- ⬜ Produce a real `--source-stems` file from the WEX source tree
- ⬜ Produce `expected_matches.csv` by human review of `07_source_project_match.md`
- ⬜ Capture a `--prev-snapshot` against a prior config-repo revision

### 8.3 Requires design decision first — unchanged

- ⬜ "Canonical pipeline group" concept (collapsing `-az-cd`/`-cd` pairs, nav families, Pattern-B fan-out) — still the right next architectural conversation
- ⬜ Prefix handling: stick with the expanded list, or replace with prefix discovery

### 8.4 New — surfaced by Run 2

- ⬜ Decide whether to flip `DEFAULT_L2_THRESHOLD` from 0.5 to 0.7 in the script. Run 2 evidence supports it; only reason to defer is if a future `--source-stems` run shows 0.7 is too tight against real source stems.
- ⬜ Re-confirm `05_edge_cases.md` numbers after the prefix expansion — the unknown-prefix tail should drop from 27 families to ~22 (the removed ones being `taskhost.`, `rdcpoint.`, `smartcommute.`, `dbi.`, `lh1ondemand.`).

---

## 9. Pointers to raw artifacts

Run 2 generated two output directories:

| Directory | L2 threshold | Ambiguity total |
|---|---|---|
| `spike_output_50/` | 0.5 | 203 |
| `spike_output_70/` | 0.7 | 175 |

Both contain the full five-artifact set (`01_raw_crawl.csv` through `05_edge_cases.md`). `06_temporal_diff.md` and `07_source_project_match.md` were not produced (no `--prev-snapshot`, no `--source-stems`).

The single-line diff between the two `04_ambiguity_report.md` files captures the entire L2 difference; the other four artifacts in each pair are byte-identical (modulo the threshold value itself).