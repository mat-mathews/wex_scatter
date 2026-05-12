# Running Scatter Against the Monolith

Step-by-step instructions for running Scatter via Docker on a Windows PC with Git Bash against the CDH monolith. Written for someone who hasn't touched the tool before.

All commands use **Git Bash** (not PowerShell, not cmd.exe). If you're in the wrong shell, things will break in confusing ways.

---

## Git Bash + Docker: Things That Will Bite You

Read this before running anything. Git Bash on Windows has path-rewriting behavior that silently breaks Docker volume mounts and container paths.

**The `MSYS_NO_PATHCONV=1` prefix is mandatory.** Without it, Git Bash rewrites `/workspace` to `C:/Program Files/Git/workspace` before Docker sees it. Every `docker run` command in this doc includes it. Don't remove it.

**Path rules:**
- Host paths use forward slashes: `//c/_/health-cdh-ondemand` (not `C:\_\health-cdh-ondemand`)
- The `//c/` prefix is Git Bash's way of saying `C:\` — the double slash prevents path rewriting
- Container paths always start with `/workspace` — that's the mount point inside the container
- Never use `$(pwd)` with spaces in the path — quote it: `"$(pwd)"`

**Line continuation:** Use backslash `\` at the end of a line (not backtick — that's PowerShell).

---

## Prerequisites

1. **Docker Desktop** — installed and running (whale icon in system tray)
2. **Git Bash** — comes with Git for Windows. Open it from Start menu or right-click a folder.
3. **Access to the monolith repo** — local clone with all `.csproj`, `.cs`, `.sln`, `.config`, and `.rdl` files

### Build the Scatter Docker image

```bash
git clone <scatter-repo-url>
cd scatter
docker build -t scatter .
```

Verify it works:

```bash
docker run scatter --help
```

You should see seven analysis modes listed.

### Set up volume mounts

You'll mount two things into the container:
- **The monolith repo** at `/workspace` — so Scatter can read the code
- **A cache volume** at `/workspace/.scatter` — so the graph cache persists between runs

The monolith path in all examples below is `//c/_/health-cdh-ondemand` (i.e. `C:\_\health-cdh-ondemand` on the host).

### Set up an output directory

```bash
mkdir -p //c/_/scatter-output
```

Reports will be written here so they survive after the container exits.

---

## Step 1: Full dependency graph (start here)

This is the foundation. Every other mode benefits from the cached graph.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter --graph --search-scope /workspace
```

**What to expect:**
- First run builds the graph from scratch. Timing depends on repo size:
  - 250 projects: ~3 seconds
  - 800 projects: ~26 seconds
  - 1,500+ projects: 1-3 minutes (Docker adds ~20% overhead vs native)
- The `scatter-cache` named volume keeps the graph between runs — subsequent runs load in under a second
- Output shows: project count, dependency count, cycles, top coupled projects, domain clusters, observations

**What to look for:**
- `Projects: N` — should match the number of `.csproj`/`.vbproj`/`.fsproj`/`.rptproj` files in the repo
- `Circular dependencies: N` — non-zero means there are cycles to investigate
- `Observations` — warnings about stable cores, high coupling, DB hotspots, Directory.Build.props blast radius
- Look for `config_di` edge count (from `.config` DI registrations) and `rdl_sproc` edge count (from SSRS `.rdl` reports) in the build log

**Save to JSON:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter --graph --search-scope /workspace \
    --output-format json --output-file /output/graph_report.json
```

The report lands at `C:\_\scatter-output\graph_report.json` on your host.

---

## Step 2: Target project analysis

Pick a project you know well and check who consumes it. The example below uses `Lighthouse1.Platform.WCF.Services` — substitute any other `.csproj` path inside the monolith.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj \
    --search-scope /workspace
```

**What to look for:**
- Consumer count — does it match your mental model?
- The filter line: `N → M project refs → K test-excluded → J namespace` — shows how the funnel narrows
- Coupling scores — highest-score consumers are the ones most tightly coupled

**Narrow to a specific class:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj \
    --search-scope /workspace \
    --class-name IClaimService
```

**Get an AI-generated analysis report:**

Add `--ai-summary` to any consumer analysis command. It makes one Gemini API call and appends a structured markdown report — executive summary, technical risk analysis, and recommendations. Useful for pasting into a ticket or sharing with your manager.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj \
    --search-scope /workspace \
    --ai-summary
```

The report includes:
- **Executive Summary** — 1-2 sentences with specific numbers for EM/PO audiences
- **Technical Risk Analysis** — consumers grouped by category (web portals, processors, services), coupling outliers called out by name and score, instability breakdown
- **Recommendations** — 3-4 actionable items (testing strategy, deployment coordination, refactoring priorities)

Works with any mode: `--target-project`, `--stored-procedure`, `--branch-name`. Combine with `--output-format markdown` to save the full report:

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj \
    --search-scope /workspace \
    --ai-summary \
    --output-format markdown --output-file /output/analysis_report.md
```

The report lands at `C:\_\scatter-output\analysis_report.md` — ready to paste into Confluence, a PR description, or a Slack message.

> **What gets sent to the AI:** Project names, coupling scores, fan-in/fan-out metrics, instability indices, and solution membership. No source code or file contents leave the network.

---

## Step 3: Stored procedure tracing

The example below uses `usp_SelectAdministratorByAlias` — a known coupling hotspot in this monolith. A live run on 2026-05-08 (see `perf_run1.txt`) found **10 C# callers across 8 projects**, with downstream consumer counts of 15, 11, and 1 for the top three triggering types. Substitute any sproc the DBA team is asking about.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --stored-procedure "usp_SelectAdministratorByAlias" \
    --search-scope /workspace
```

**What to look for:**
- Which C# classes reference this sproc (and in which projects)
- The consumer chain: sproc → class → project → consumers of that project
- If SSRS reports (`.rdl` files) reference this sproc, the graph has `rdl_sproc` edges — visible in graph mode output but not yet in sproc mode (follow-up enhancement tracked)

> **Reporting-heavy alternative:** `usp_ReportCheck` appears in **328 `.rdl/.rdlc` files** in this monolith (filesystem string match) — the highest-fan-in sproc by SSRS surface. The `rdl_sproc` edge count in graph mode will be slightly lower because the scanner only counts bare-sproc `<CommandText>` blocks (not embedded SELECTs); expect ~300+. Useful for demonstrating the rdl_sproc edge weight.

**With pipeline mapping:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --stored-procedure "usp_SelectAdministratorByAlias" \
    --search-scope /workspace \
    --pipeline-csv /workspace/path/to/pipeline_to_app_mapping.csv
```

The pipeline CSV must be inside the mounted volume — Docker can't see files outside `/workspace`.

---

## Step 4: PR risk scoring

Score the risk of a feature branch before merge. Scatter accepts any git ref — local branch, remote-tracking ref (`origin/...`), tag, or SHA. No need to check out or create a local branch. If `git rev-parse <ref>` resolves it, scatter can diff it.

The example below uses a real CDH branch (`Stingrays/dleal/CDH-27013-fix-assembly-error`). You can pass it as a local branch or as `origin/Stingrays/dleal/CDH-27013-fix-assembly-error` — both work:

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --branch-name Stingrays/dleal/CDH-27013-fix-assembly-error \
    --pr-risk \
    --repo-path /workspace \
    --search-scope /workspace
```

Verified diff size: ~215 changed `.cs` files vs `main`. If your monolith's mainline is not `main`, append `--base-branch <name>` (e.g. `--base-branch master`). On `C:\_\health-cdh-ondemand` the default of `main` is correct.

**What to look for:**
- Risk level: GREEN (< 0.4), YELLOW (0.4-0.7), RED (>= 0.7)
- Dimension breakdown: which risk dimensions are driving the score
- Changed types: what types were modified on this branch
- Consumer count: how many projects are affected

**Generate markdown for a PR comment:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --branch-name Stingrays/dleal/CDH-27013-fix-assembly-error \
    --pr-risk \
    --repo-path /workspace \
    --search-scope /workspace \
    --output-format markdown --collapsible \
    --output-file /output/pr_risk.md
```

Open `C:\_\scatter-output\pr_risk.md` and paste into the PR description.

---

## Step 5: Impact analysis (requires API key)

Analyze a work request in plain English. Pass the WEX AI Gateway API key via `-e`.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sow "Add tenant isolation to the portal configuration system" \
    --search-scope /workspace
```

**What to look for:**
- Target quality: clear/moderate/vague — tells you how specific the SOW was
- Blast radius tree: direct and transitive consumers with risk ratings
- Complexity estimate and impact summary — paste directly into a ticket

**From a file (for longer SOWs):**

Put the SOW file inside the monolith repo (or another mounted volume) so Docker can see it:

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sow-file /workspace/docs/my_sow.md \
    --search-scope /workspace
```

**With effort estimation:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sow "Your work request here" \
    --search-scope /workspace \
    --scope-estimate --graph-metrics
```

---

## Step 6: Validate new edge types

Check whether the config DI and RDL scanners found anything in the monolith.

> **Important:** the JSON exporter omits the raw `nodes`/`edges` arrays by default to reduce file size. To grep for edge types you **must** add `--include-graph-topology`. Without it, `graph.json` will contain `summary`, `top_coupled`, `metrics`, and `cycles` only — and `grep -c '"config_di"'` will return 0 even when the scanners found thousands of edges.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter --graph --search-scope /workspace \
    --include-graph-topology \
    --output-format json --output-file /output/graph.json
```

Then on your host:

```bash
# Count config_di edges
grep -c '"config_di"' //c/_/scatter-output/graph.json

# Count rdl_sproc edges
grep -c '"rdl_sproc"' //c/_/scatter-output/graph.json
```

**Expected order of magnitude on this monolith (verified 2026-04):**
- 1,180 `.rdl/.rdlc` files exist in the tree; ~990 carry `<CommandText>` sproc references
- `rdl_sproc` edge count should be in the **thousands** (one per RDL → sproc → owning-project link)
- Top RDL-referenced sprocs (filesystem string match): `usp_ReportCheck` (328 files), `usp_ReportPtpCheck` (~135), `usp_ReportHSACheck` (~114). The `rdl_sproc` edge count is bounded above by these numbers. A concrete RDL example: `Dev/Source/Code/Database.NavSuite Operational/Execution Logs - Administrator Stats.rdl` binds to `dbo.usp_GetExecutionLogs_AdministratorStats`.

**Independent verification from the build log** (works even without `--include-graph-topology`): both scanners emit summary log lines during the graph build. Look for:
- `Config DI scanner: found N type reference(s) across M .config file(s)` followed by `Added K config_di edge(s) to graph`
- `RDL scanner: found N sproc reference(s) across M RDL file(s)` followed by `Added K rdl_sproc edge(s) to graph`

If those log lines show non-zero counts, the scanners worked. If `grep -c '"config_di"'` returns 0 anyway, you forgot `--include-graph-topology`.

**If the log lines themselves show zero:**
- Add `-v` for verbose: append `-v` before `--search-scope`
- Make sure the monolith root is mounted — `.config` and `.rdl` files in subdirectories are scanned recursively
- Force a fresh build to re-run the scanners: `docker volume rm scatter-cache` then re-run Step 1

---

## Step 7: Calibrate coupling weights

Compare coupling rankings with the new edge types. Save the full graph JSON (Step 6 above), then check:

- Top 10 coupled projects — do the rankings make sense with `config_di` (0.7) and `rdl_sproc` (0.6) edges?
- Are any projects jumping unexpectedly high?
- If rankings look wrong, the weights need adjustment

Record:
- Number of `config_di` and `rdl_sproc` edges found
- Top 10 before (from any prior run without new scanners) and after
- Any ranking changes that seem wrong

---

## Step 8: Stored procedure inventory

Build a complete catalog of every sproc defined in `.sql` files and referenced in C# code. Shows which sprocs have definitions, which are referenced but undefined, and coverage metrics.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sproc-inventory \
    --search-scope /workspace
```

**What to look for:**
- Coverage percentage — what fraction of referenced sprocs have a `.sql` definition in the repo?
- "no .sql definition in repo" entries — these are sprocs called from C# but with no `.sql` source file. They may be defined directly in the database or in a separate repo.
- Shared sprocs — referenced by 2+ projects. These are the hidden coupling hotspots (e.g. `usp_SelectAdministratorByAlias` shows up across 4 projects in this monolith).

**Save to JSON:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter --sproc-inventory --search-scope /workspace \
    --output-format json --output-file /output/sproc_inventory.json
```

> **Note:** `--sproc-inventory` always scans `.sql` files fresh; it does not depend on the cached graph from Step 1. First run on this monolith reads ~all `.sql` files under `/workspace` plus all C# string-literal sproc references (the same ~45,000 `.cs` files Step 1 walked).

---

## Step 9: Index compression validation

The codebase index is embedded in `--sow` prompts so the AI can match domain language to project/type/sproc names. On this monolith the full index is ~1.64 MB — over the gateway's ~1 MB request limit. Index compression applies progressive reductions (drop shared sproc section, filter stoplist types, cap types per project, drop empty projects) to bring it under budget.

This step validates that the compression works and that compressed output still produces usable `--sow` results.

### Baseline: measure the uncompressed index

Before testing compression, know your starting point.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter --dump-index --search-scope /workspace
```

**What to record:**
- Total projects, types, sprocs, files (shown at the bottom)
- Index size in bytes — if this is under 800,000, compression won't activate and there's nothing to test
- Approximate token count (~size / 4)

Save the full index for diff later:

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter --dump-index --search-scope /workspace \
  > //c/_/scatter-output/index_full.txt
```

The diagnostics tool gives richer detail (type coverage, empty-project count):

```bash
python tools/dump_index_check.py //c/_/health-cdh-ondemand -o //c/_/scatter-output/index_full.txt
```

**Expected on this monolith (measured 2026-05):**
- ~1,591 projects, ~54,811 types, ~5,978 sprocs
- ~1,716,923 bytes (1.64 MB) — well over the 800 KB budget

### Run `--sow` and check the compression logs

With compression wired in, `--sow` mode logs each reduction step. Add `-v` for verbose output:

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sow "Add tenant isolation to the portal configuration system" \
    --search-scope /workspace \
    -v
```

**What to look for in the logs:**

| Log line | Meaning |
|----------|---------|
| `Index exceeds budget (X > Y bytes)` | Compression triggered |
| `Step 1 (drop shared sprocs): N bytes` | Shared sproc cross-reference removed |
| `Step 2 (stoplist filter): N bytes` | Low-signal types (Program, Startup, Constants, etc.) removed |
| `Step 3 (cap=15): N bytes` | Types per project capped at 15 |
| `Step 3 (cap=10): N bytes` | Cap tightened to 10 (only if cap=15 wasn't enough) |
| `Step 3 (cap=5): N bytes` | Cap tightened to 5 (only if cap=10 wasn't enough) |
| `Step 4 (drop zero-signal): N bytes` | Projects with no types and no sprocs after filtering removed |
| `Index reduced to N bytes (X% reduction via ...)` | Final result and summary of steps applied |

If you see the warning `still exceeds budget` after all steps, the budget is tighter than the compression can handle. This shouldn't happen on the monolith at the default 800 KB budget, but would on a significantly larger repo.

### Unit tests

Run the compression-specific tests locally (no Docker, no API key needed):

```bash
uv run python -m pytest tests/unit/test_codebase_index.py -v -k "Budget or FilterTypes or ApplyTypeCap"
```

These cover:
- **TestFilterTypes** — stoplist entries, single-char names, project-name duplicates removed; order preserved
- **TestApplyTypeCap** — longest names kept, `...` sentinel appended, no truncation when under cap
- **TestBudgetAwareIndex** — each compression step fires in order, shared sprocs dropped before types, type cap produces `...`, zero-signal projects dropped last, logs emitted at each step, best-effort return when all steps exhausted, `_extract_index_names` round-trips on compressed output, compressed metrics match the actual output

### Spot-check: does the compressed index still find the right targets?

The point of compression is to not break anything. Run the same SOW with and without a budget and compare:

```bash
# Full index (no compression)
MSYS_NO_PATHCONV=1 docker run \
  -e WEX_AI_API_KEY="your-api-key" \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/_/scatter-output:/output" \
  scatter \
    --sow "Add tenant isolation to the portal configuration system" \
    --search-scope /workspace \
    --output-format json --output-file /output/sow_full.json

# Compressed index (default budget)
# (same command — compression activates automatically when index > budget)
```

Compare the JSON reports:
1. Are the same top-confidence targets identified?
2. Is target quality (clear/moderate/vague) the same or worse?
3. Did any high-signal project disappear from the compressed results?

If a previously clear SOW becomes vague after compression, the stoplist may be too aggressive or the budget too tight. Check whether the missing project's types were all stoplist entries.

---

## Interactive session

If you want to poke around inside the container:

```bash
MSYS_NO_PATHCONV=1 docker run -it --entrypoint /bin/bash \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter
```

Inside the container, run Scatter commands directly (no `docker run`, no `MSYS_NO_PATHCONV`):

```bash
scatter --graph --search-scope /workspace
scatter --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj --search-scope /workspace
```

---

## Troubleshooting

**"No projects found" or empty output**
- Check that `/workspace` contains `.csproj` files: `docker run -v "//c/_/health-cdh-ondemand:/workspace" scatter ls /workspace`
- If the repo is nested (e.g., `monolith/src/`), adjust `--search-scope /workspace/src`

**"Error: repository not found" on branch analysis**
- The mounted directory must be a git repo. If you cloned to a different location, mount that path
- Check the branch exists: `git branch -a` in Git Bash (not inside Docker)

**Graph cache not persisting**
- Make sure you're using the named volume: `-v scatter-cache:/workspace/.scatter`
- Without it, the cache lives inside the ephemeral container and dies when it exits
- To force a fresh rebuild: `docker volume rm scatter-cache` then re-run

**Slow first run**
- Expected for large repos — the graph caches after first build
- Docker adds ~20% overhead vs native Python (filesystem bridge). The cache volume eliminates this on subsequent runs
- If it's extremely slow (>10 minutes), check if your antivirus is scanning the mounted volume

**Path rewriting errors (paths look like `C:/Program Files/Git/...`)**
- You forgot `MSYS_NO_PATHCONV=1` at the start of the command
- Every `docker run` command must start with it in Git Bash

**Config DI scanner found 0 references**
- The scanner matches `Namespace.Type, AssemblyName` patterns in `.config` XML attributes and text
- If your DI configs use a different format, file an issue with an example `.config` file

**RDL scanner found 0 references**
- The scanner looks for `<CommandText>` elements inside `<DataSet>` blocks in `.rdl` files
- If your reports use a non-standard RDL XML structure, file an issue with an example `.rdl` file

**"Permission denied" on output files**
- Docker may create output files as root. Fix: `chmod 644 //c/_/scatter-output/*`
- Or run the output mount with `:rw` flag (default, but explicit): `-v "//c/_/scatter-output:/output:rw"`

---

## Quick reference

All commands assume:
- Monolith at `//c/_/health-cdh-ondemand` (i.e. `C:\_\health-cdh-ondemand`)
- Output at `//c/_/scatter-output` (i.e. `C:\_\scatter-output`)
- Cache in `scatter-cache` named volume

```bash
# Build image (once)
docker build -t scatter .

# Graph
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --graph --search-scope /workspace

# Target project
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj --search-scope /workspace

# Stored procedure
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --stored-procedure "usp_SelectAdministratorByAlias" --search-scope /workspace

# Sproc inventory
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --sproc-inventory --search-scope /workspace

# PR risk (branch must exist as a LOCAL branch — see Step 4 for git branch one-liner if you've only fetched)
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --branch-name Stingrays/dleal/CDH-27013-fix-assembly-error --pr-risk --repo-path /workspace --search-scope /workspace

# Impact analysis (compression activates automatically when index > budget)
MSYS_NO_PATHCONV=1 docker run -e WEX_AI_API_KEY="key" -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --sow "description" --search-scope /workspace

# Dump index (measure baseline size — add -v for verbose)
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --dump-index --search-scope /workspace

# AI analysis report (any consumer mode)
MSYS_NO_PATHCONV=1 docker run -e WEX_AI_API_KEY="key" -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter scatter --target-project /workspace/Dev/src/Lighthouse1/Platform/WCF/Services/Lighthouse1.Platform.WCF.Services.csproj --search-scope /workspace --ai-summary

# Save JSON output
MSYS_NO_PATHCONV=1 docker run -v "//c/_/health-cdh-ondemand:/workspace" -v scatter-cache:/workspace/.scatter -v "//c/_/scatter-output:/output" scatter --graph --search-scope /workspace --output-format json --output-file /output/report.json
```