# Running the APP_CONFIG Spike on the PC

The spike script (`tools/spike/config_repo_crawl.py`) is stdlib-only with no scatter imports. No Docker build needed — mount it into a vanilla Python image.

For the full rationale behind this spike, see [APP_CONFIG_REPO_SPIKE.md](APP_CONFIG_REPO_SPIKE.md).

---

## 1. Pull the branch

```bash
cd /path/to/wex_scatter
git fetch origin
git checkout feature/app-config-repo-spike-impl
```

## 2. Run the basic crawl (5 reports)

```bash
docker run --rm \
  -v "$(pwd)":/workspace \
  -v /c/_/health-benefits-app-config:/config:ro \
  python:3.12-slim \
  python /workspace/tools/spike/config_repo_crawl.py \
    --app-config-path /config \
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv \
    --output-dir /workspace/spike_output
```

No build step. `python:3.12-slim` has everything the script needs. The config repo is mounted read-only (`:ro`).

Reports land in `spike_output/` in your local repo (gitignored):

| Report | What to look at |
|---|---|
| `01_raw_crawl.csv` | Every pipeline + all extracted signals |
| `02_pattern_taxonomy.md` | Pattern A/B/C/D counts — does the taxonomy cover everything? |
| `03_csv_diff.md` | Crawler vs hand CSV — new mappings, disagreements, gaps |
| `04_ambiguity_report.md` | Collision analysis — silent-wrong-answer cases |
| `05_edge_cases.md` | `//` comments, `{AppName}` placeholders, unknown prefixes, structural surprises |

## 3. Generate a source-stems file (for P-intersect numbers)

This step is optional but produces the numbers that actually drive the Path 1 vs Path 2 decision.

In PowerShell, from wherever the WEX source repos live:

```powershell
Get-ChildItem -Path C:\_\source -Recurse -Filter *.csproj |
  ForEach-Object { $_.BaseName } > source_project_stems.txt
```

Or in Git Bash:

```bash
find /c/_/source -name "*.csproj" -exec basename {} .csproj \; > source_project_stems.txt
```

## 4. Rerun with source stems

```bash
docker run --rm \
  -v "$(pwd)":/workspace \
  -v /c/_/health-benefits-app-config:/config:ro \
  python:3.12-slim \
  python /workspace/tools/spike/config_repo_crawl.py \
    --app-config-path /config \
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv \
    --output-dir /workspace/spike_output \
    --source-stems /workspace/source_project_stems.txt
```

This adds `07_source_project_match.md` — the cascade simulation against real `.csproj` stems.

## 5. Optional: temporal diff

Save today's crawl as a baseline, then rerun later (or against an older checkout of the config repo) to measure churn:

```bash
cp spike_output/01_raw_crawl.csv spike_output/baseline.csv

# After time passes or after checking out a different rev of the config repo:
docker run --rm \
  -v "$(pwd)":/workspace \
  -v /c/_/health-benefits-app-config:/config:ro \
  python:3.12-slim \
  python /workspace/tools/spike/config_repo_crawl.py \
    --app-config-path /config \
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv \
    --output-dir /workspace/spike_output \
    --prev-snapshot /workspace/spike_output/baseline.csv
```

This adds `06_temporal_diff.md` with a churn rate and Path 2 viability verdict.

---

## Reading the results

The decision-critical reports, in priority order:

1. **`02_pattern_taxonomy.md`** — does A/B/C/D cover everything, or are there structural surprises?
2. **`07_source_project_match.md`** — L1 exact-match rate against real stems. This is THE number for Path 1 vs Path 2.
3. **`04_ambiguity_report.md`** — how many silent-wrong-answer cases at L2/L3?
4. **`03_csv_diff.md`** — how many pipelines does the crawler find that the hand CSV missed?
5. **`05_edge_cases.md`** — unknown prefixes, malformed json, structural anomalies

Decision thresholds (from the spike plan — initial proposals, not absolutes):

- L1 ≥ 90% on P-intersect → **Path 2** (enriched CSV, skip runtime matcher)
- L1 < 90% and cascade adds value → **Path 1** (build the full plan)
- Edge cases worse than expected → **Path 3** (re-scope the plan)

---

## Git Bash path notes

The mount paths above assume Git Bash on Windows, which translates `C:\_\...` to `/c/_/...`. If running from PowerShell instead, use Windows-native paths:

```powershell
docker run --rm `
  -v "${PWD}:/workspace" `
  -v "C:\_\health-benefits-app-config:/config:ro" `
  python:3.12-slim `
  python /workspace/tools/spike/config_repo_crawl.py `
    --app-config-path /config `
    --hand-csv /workspace/examples/pipeline_to_app_mapping.csv `
    --output-dir /workspace/spike_output
```
