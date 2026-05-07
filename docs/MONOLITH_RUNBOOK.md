# Running Scatter Against the Monolith

Step-by-step instructions for running Scatter via Docker on a Windows PC with Git Bash against the CDH monolith. Written for someone who hasn't touched the tool before.

All commands use **Git Bash** (not PowerShell, not cmd.exe). If you're in the wrong shell, things will break in confusing ways.

---

## Git Bash + Docker: Things That Will Bite You

Read this before running anything. Git Bash on Windows has path-rewriting behavior that silently breaks Docker volume mounts and container paths.

**The `MSYS_NO_PATHCONV=1` prefix is mandatory.** Without it, Git Bash rewrites `/workspace` to `C:/Program Files/Git/workspace` before Docker sees it. Every `docker run` command in this doc includes it. Don't remove it.

**Path rules:**
- Host paths use forward slashes: `//c/Users/you/repos/monolith` (not `C:\Users\...`)
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

You should see six analysis modes listed.

### Set up volume mounts

You'll mount two things into the container:
- **The monolith repo** at `/workspace` — so Scatter can read the code
- **A cache volume** at `/workspace/.scatter` — so the graph cache persists between runs

The monolith path in all examples below is `//c/repos/monolith`. Replace it with your actual path.

### Set up an output directory

```bash
mkdir -p //c/scatter-output
```

Reports will be written here so they survive after the container exits.

---

## Step 1: Full dependency graph (start here)

This is the foundation. Every other mode benefits from the cached graph.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
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
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/scatter-output:/output" \
  scatter --graph --search-scope /workspace \
    --output-format json --output-file /output/graph_report.json
```

The report lands at `C:\scatter-output\graph_report.json` on your host.

---

## Step 2: Target project analysis

Pick a project you know well and check who consumes it. Replace `src/SomeProject/SomeProject.csproj` with the actual relative path inside the monolith.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --target-project /workspace/src/SomeProject/SomeProject.csproj \
    --search-scope /workspace
```

**What to look for:**
- Consumer count — does it match your mental model?
- The filter line: `N → M project refs → K test-excluded → J namespace` — shows how the funnel narrows
- Coupling scores — highest-score consumers are the ones most tightly coupled

**Narrow to a specific class:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --target-project /workspace/src/SomeProject/SomeProject.csproj \
    --search-scope /workspace \
    --class-name SomeImportantService
```

**Get an AI-generated analysis report:**

Add `--ai-summary` to any consumer analysis command. It makes one Gemini API call and appends a structured markdown report — executive summary, technical risk analysis, and recommendations. Useful for pasting into a ticket or sharing with your manager.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e GOOGLE_API_KEY="your-gemini-api-key" \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --target-project /workspace/src/SomeProject/SomeProject.csproj \
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
  -e GOOGLE_API_KEY="your-gemini-api-key" \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/scatter-output:/output" \
  scatter \
    --target-project /workspace/src/SomeProject/SomeProject.csproj \
    --search-scope /workspace \
    --ai-summary \
    --output-format markdown --output-file /output/analysis_report.md
```

The report lands at `C:\scatter-output\analysis_report.md` — ready to paste into Confluence, a PR description, or a Slack message.

> **What gets sent to the AI:** Project names, coupling scores, fan-in/fan-out metrics, instability indices, and solution membership. No source code or file contents leave the network.

---

## Step 3: Stored procedure tracing

Pick a sproc the DBA team has been asking about.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --stored-procedure "dbo.sp_YourStoredProcedure" \
    --search-scope /workspace
```

**What to look for:**
- Which C# classes reference this sproc (and in which projects)
- The consumer chain: sproc → class → project → consumers of that project
- If SSRS reports (`.rdl` files) reference this sproc, the graph has `rdl_sproc` edges — visible in graph mode output but not yet in sproc mode (follow-up enhancement tracked)

**With pipeline mapping:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --stored-procedure "dbo.sp_YourStoredProcedure" \
    --search-scope /workspace \
    --pipeline-csv /workspace/path/to/pipeline_to_app_mapping.csv
```

The pipeline CSV must be inside the mounted volume — Docker can't see files outside `/workspace`.

---

## Step 4: PR risk scoring

Score the risk of a feature branch before merge. The branch must exist in the mounted repo.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --branch-name feature/your-branch \
    --pr-risk \
    --repo-path /workspace \
    --search-scope /workspace
```

**What to look for:**
- Risk level: GREEN (< 0.4), YELLOW (0.4-0.7), RED (>= 0.7)
- Dimension breakdown: which risk dimensions are driving the score
- Changed types: what types were modified on this branch
- Consumer count: how many projects are affected

**Generate markdown for a PR comment:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/scatter-output:/output" \
  scatter \
    --branch-name feature/your-branch \
    --pr-risk \
    --repo-path /workspace \
    --search-scope /workspace \
    --output-format markdown --collapsible \
    --output-file /output/pr_risk.md
```

Open `C:\scatter-output\pr_risk.md` and paste into the PR description.

---

## Step 5: Impact analysis (requires API key)

Analyze a work request in plain English. Pass the Gemini API key via `-e`.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e GOOGLE_API_KEY="your-gemini-api-key" \
  -v "//c/repos/monolith:/workspace" \
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
  -e GOOGLE_API_KEY="your-gemini-api-key" \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sow-file /workspace/docs/my_sow.md \
    --search-scope /workspace
```

**With effort estimation:**

```bash
MSYS_NO_PATHCONV=1 docker run \
  -e GOOGLE_API_KEY="your-gemini-api-key" \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --sow "Your work request here" \
    --search-scope /workspace \
    --scope-estimate --graph-metrics
```

---

## Step 6: Validate new edge types

Check whether the config DI and RDL scanners found anything in the monolith.

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  -v "//c/scatter-output:/output" \
  scatter --graph --search-scope /workspace \
    --output-format json --output-file /output/graph.json
```

Then on your host:

```bash
# Count config_di edges
grep -c '"config_di"' //c/scatter-output/graph.json

# Count rdl_sproc edges
grep -c '"rdl_sproc"' //c/scatter-output/graph.json
```

**If you see zero for either:**
- Check the build log for "Config DI scanner" and "RDL scanner" lines — they report file counts and match counts
- Add `-v` for verbose: append `-v` before `--search-scope`
- Make sure the monolith root is mounted — `.config` and `.rdl` files in subdirectories are scanned recursively

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

## Interactive session

If you want to poke around inside the container:

```bash
MSYS_NO_PATHCONV=1 docker run -it --entrypoint /bin/bash \
  -v "//c/repos/monolith:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter
```

Inside the container, run Scatter commands directly (no `docker run`, no `MSYS_NO_PATHCONV`):

```bash
scatter --graph --search-scope /workspace
scatter --target-project /workspace/src/SomeProject/SomeProject.csproj --search-scope /workspace
```

---

## Troubleshooting

**"No projects found" or empty output**
- Check that `/workspace` contains `.csproj` files: `docker run -v "//c/repos/monolith:/workspace" scatter ls /workspace`
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
- Docker may create output files as root. Fix: `chmod 644 //c/scatter-output/*`
- Or run the output mount with `:rw` flag (default, but explicit): `-v "//c/scatter-output:/output:rw"`

---

## Quick reference

All commands assume:
- Monolith at `//c/repos/monolith`
- Output at `//c/scatter-output`
- Cache in `scatter-cache` named volume

```bash
# Build image (once)
docker build -t scatter .

# Graph
MSYS_NO_PATHCONV=1 docker run -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter scatter --graph --search-scope /workspace

# Target project
MSYS_NO_PATHCONV=1 docker run -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter scatter --target-project /workspace/src/Project/Project.csproj --search-scope /workspace

# Stored procedure
MSYS_NO_PATHCONV=1 docker run -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter scatter --stored-procedure "dbo.sp_Name" --search-scope /workspace

# PR risk
MSYS_NO_PATHCONV=1 docker run -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter scatter --branch-name feature/x --pr-risk --repo-path /workspace --search-scope /workspace

# Impact analysis
MSYS_NO_PATHCONV=1 docker run -e GOOGLE_API_KEY="key" -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter scatter --sow "description" --search-scope /workspace

# AI analysis report (any consumer mode)
MSYS_NO_PATHCONV=1 docker run -e GOOGLE_API_KEY="key" -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter scatter --target-project /workspace/src/Project/Project.csproj --search-scope /workspace --ai-summary

# Save JSON output
MSYS_NO_PATHCONV=1 docker run -v "//c/repos/monolith:/workspace" -v scatter-cache:/workspace/.scatter -v "//c/scatter-output:/output" scatter --graph --search-scope /workspace --output-format json --output-file /output/report.json
```
