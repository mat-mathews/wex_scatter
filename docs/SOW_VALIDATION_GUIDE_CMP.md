# SOW Prediction Validation Guide

How to measure scatter's `--sow-file` prediction accuracy against real branch implementations. Written for the CDH monolith on a Windows PC running Docker via Git Bash.

---

## Prerequisites

- Docker image rebuilt from latest `main` (`docker build -t scatter .`)
- Monolith repo at `C:\_\health-cdh-ondemand` with target branch(es) fetched
- Output directory at `C:\_\scatter-output`
- WEX AI Gateway API key in environment (`WEX_AI_API_KEY`, `WEX_AI_ENDPOINT`)
- SOW text file accessible inside a mounted volume (e.g., `examples/TEST_FID_2728_PROJECT_REQUIREMENTS.txt`)

---

## Step 1: Run SOW prediction (3 runs minimum)

AI output is nondeterministic (±15% on root count, ±1 tier on risk labels). Always run at least 3 times and report the median.

```bash
# Run 1
MSYS_NO_PATHCONV=1 docker run --rm \
  -e WEX_AI_API_KEY -e WEX_AI_ENDPOINT -e SCATTER_DEFAULT_PROVIDER=wex \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/wex_scatter/examples:/sow:ro" \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --sow-file /sow/TEST_FID_2728_PROJECT_REQUIREMENTS.txt \
    --search-scope /workspace \
    --output-format json --output-file /output/fid2728_run1.json -v

# Run 2
MSYS_NO_PATHCONV=1 docker run --rm \
  -e WEX_AI_API_KEY -e WEX_AI_ENDPOINT -e SCATTER_DEFAULT_PROVIDER=wex \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/wex_scatter/examples:/sow:ro" \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --sow-file /sow/TEST_FID_2728_PROJECT_REQUIREMENTS.txt \
    --search-scope /workspace \
    --output-format json --output-file /output/fid2728_run2.json -v

# Run 3
MSYS_NO_PATHCONV=1 docker run --rm \
  -e WEX_AI_API_KEY -e WEX_AI_ENDPOINT -e SCATTER_DEFAULT_PROVIDER=wex \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/wex_scatter/examples:/sow:ro" \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --sow-file /sow/TEST_FID_2728_PROJECT_REQUIREMENTS.txt \
    --search-scope /workspace \
    --output-format json --output-file /output/fid2728_run3.json -v
```

---

## Step 2: Validate key consumers surfaced

The key consumers feature promotes depth-0 consumers appearing under multiple roots or at High/Critical risk to a top-level section. This is the primary validation target — these should be stable across runs because they come from the dependency graph, not the AI.

```bash
python -c "
import json

for i in range(1, 4):
    f = f'c:/_/scatter-output/fid2728_run{i}.json'
    d = json.load(open(f))
    kc = d.get('key_consumers', [])
    names = [c['consumer_name'] for c in kc]
    print(f'Run {i}: {len(kc)} key consumer(s)')
    for c in kc:
        print(f'  {c[\"consumer_name\"]} — {c[\"appearances\"]} root(s), {c[\"max_risk\"]} risk')
    presenter_hit = 'Lighthouse1.Presenters.Web.Admin' in names
    print(f'  Presenters.Web.Admin surfaced: {presenter_hit}')
    print()
"
```

**Expected results for FID-2728:**

| Check | Expected |
|---|---|
| `key_consumers` array present | Yes, all 3 runs |
| `Lighthouse1.Presenters.Web.Admin` in array | Yes, all 3 runs (stable — graph-derived) |
| Appearances for Presenters.Web.Admin | 2-5 (varies with AI root count) |
| Risk for Presenters.Web.Admin | High or Critical |
| Key consumers stable across runs | Yes — graph output is deterministic |

---

## Step 3: Run branch comparison (ground truth)

Run the actual branch to get ground truth of what the developer changed:

```bash
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --branch-name origin/Athena/FID-2728-response-header \
    --base-branch origin/main \
    --repo-path /workspace --search-scope /workspace \
    --output-format json --output-file /output/fid2728_actual.json
```

---

## Step 4: Compare prediction vs actual

Use the v3 comparison script (git-diff based, test-filtered):

```bash
python scratch/compare_v3.py \
  --predicted //c/_/scatter-output/fid2728_run1.json \
  --repo //c/_/health-cdh-ondemand \
  --branch origin/Athena/FID-2728-response-header \
  --base origin/main \
  --output-dir //c/_/scatter-output/runs/analysis4_run1
```

Repeat for runs 2 and 3. Report median values.

---

## Step 5: Compute metrics

### Definitions

| Metric | Formula |
|---|---|
| **Root recall** | (predicted roots ∩ actually changed) / actually changed |
| **Root precision** | (predicted roots ∩ actually changed) / predicted roots |
| **Functional recall** | (actually changed ∩ predicted at depth ≤ 1, confidence ≥ 0.9) / actually changed |
| **Key consumer hit rate** | (actually changed ∩ key_consumers) / actually changed |

### Reporting template

```
SOW: [filename]
Branch: [branch name]
Runs: N

Predicted roots (median): X
Actually changed (excl. tests): Y

Root recall: median A% (range B%-C%)
Root precision: median D% (range E%-F%)
Functional recall: G% (expected 100%)
Key consumer hit rate: H%

Key consumers stable across runs: [Yes/No]
Key consumers that matched actual changes: [list]
```

---

## Known patterns (established in ANALYSIS_2 and ANALYSIS_3)

**Systematic AI bias:** The AI consistently extracts business-domain projects (services, data layers, sprocs) and consistently misses UI hosts (.aspx projects) and presenter-layer helpers. This is a prompt-level artifact, not a bug — the graph compensates by catching these at depth-0.

**Nondeterminism bounds:** ±15% on root count, ±1 tier on risk labels across runs with identical inputs. Always use N≥3 runs.

**Precision is bounded by SOW breadth:** A SOW describing a full feature will over-predict when compared against a single branch implementing one slice. Precision improves when measured against the union of all branches for the same FID.

**Key consumers are more stable than roots:** Because they derive from the deterministic dependency graph, not the nondeterministic AI root selection. A consumer that's depth-0 under 3 AI roots in Run 1 will still be depth-0 under 2 different AI roots in Run 2 — the appearances count may shift but the consumer still qualifies.

---

## Artifacts produced

| File pattern | Contents |
|---|---|
| `fid2728_runN.json` | SOW prediction output (per run) |
| `fid2728_actual.json` | Branch ground truth (consumer-centric, leaf-blind) |
| `runs/analysis4_runN/v3_*.txt` | Per-run comparison breakdown |

---

## See also

- `perf_runs/ANALYSIS_2.md` — original FID-2728 validation (methodology v3)
- `perf_runs/ANALYSIS_3.md` — stability analysis (3 runs, 2 branches, nondeterminism quantified)
- `docs/MONOLITH_RUNBOOK.md` Step 5 — general SOW mode usage
