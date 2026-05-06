# Running Scatter Against the Monolith

Step-by-step instructions for running Scatter on a Windows PC against the CDH monolith codebase. Written for someone who hasn't touched the tool before.

---

## Prerequisites

### On your PC

1. **Python 3.10+** — check with `python --version`
2. **Git** — check with `git --version`
3. **uv** — Scatter's package manager. Install if missing:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
4. **Access to the monolith repo** — you need a local clone (or a network path) of the CDH codebase with all `.csproj`, `.cs`, `.sln`, `.config`, and `.rdl` files accessible.

### Clone and set up Scatter

```powershell
git clone <scatter-repo-url>
cd scatter
pwsh tools/setup.ps1
```

The setup script installs dependencies and configures git. Run it once. It's safe to re-run.

Verify it works:

```powershell
uv run scatter --help
```

You should see six analysis modes listed.

---

## Step 1: Full dependency graph (start here)

This is the foundation. Every other mode uses the cached graph, so build it first.

```powershell
uv run scatter --graph --search-scope "C:\path\to\monolith\repo"
```

**What to expect:**
- First run builds the graph from scratch. Timing depends on repo size:
  - 250 projects: ~3 seconds
  - 800 projects: ~26 seconds
  - 1,500+ projects: 1-3 minutes
- Output shows: project count, dependency count, cycles, top coupled projects, domain clusters, observations
- Graph is cached to `<search-scope>/.scatter/graph_cache.json` — subsequent runs load from cache in under a second

**What to look for:**
- `Projects: N` — should match the number of `.csproj`/`.vbproj`/`.fsproj`/`.rptproj` files in the repo
- `Circular dependencies: N` — non-zero means there are cycles to investigate
- `Observations` — warnings about stable cores, high coupling, DB hotspots, Directory.Build.props blast radius
- New edge types: `config_di` edges (from `.config` DI registrations) and `rdl_sproc` edges (from SSRS `.rdl` reports) will appear if those files exist in the repo

**Save to JSON for later analysis:**

```powershell
uv run scatter --graph `
  --search-scope "C:\path\to\monolith\repo" `
  --output-format json --output-file graph_report.json
```

---

## Step 2: Target project analysis

Pick a project you know well and check who consumes it.

```powershell
uv run scatter `
  --target-project "C:\path\to\monolith\repo\src\SomeProject\SomeProject.csproj" `
  --search-scope "C:\path\to\monolith\repo"
```

**What to look for:**
- Consumer count — does it match your mental model?
- The filter line: `N → M project refs → K test-excluded → J namespace` — shows how the funnel narrows
- Coupling scores — highest-score consumers are the ones most tightly coupled

**Narrow to a specific class:**

```powershell
uv run scatter `
  --target-project "C:\path\to\monolith\repo\src\SomeProject\SomeProject.csproj" `
  --search-scope "C:\path\to\monolith\repo" `
  --class-name SomeImportantService
```

---

## Step 3: Stored procedure tracing

Pick a sproc the DBA team has been asking about.

```powershell
uv run scatter `
  --stored-procedure "dbo.sp_YourStoredProcedure" `
  --search-scope "C:\path\to\monolith\repo"
```

**What to look for:**
- Which C# classes reference this sproc (and in which projects)
- The consumer chain: sproc → class → project → consumers of that project
- If SSRS reports (`.rdl` files) reference this sproc, the graph will have `rdl_sproc` edges — visible in graph mode but not yet in sproc mode (follow-up enhancement tracked)

**With pipeline mapping:**

```powershell
uv run scatter `
  --stored-procedure "dbo.sp_YourStoredProcedure" `
  --search-scope "C:\path\to\monolith\repo" `
  --pipeline-csv path\to\pipeline_to_app_mapping.csv
```

---

## Step 4: PR risk scoring

Score the risk of a feature branch before merge.

```powershell
uv run scatter `
  --branch-name feature/your-branch `
  --pr-risk `
  --repo-path "C:\path\to\monolith\repo" `
  --search-scope "C:\path\to\monolith\repo"
```

**What to look for:**
- Risk level: GREEN (< 0.4), YELLOW (0.4-0.7), RED (>= 0.7)
- Dimension breakdown: which risk dimensions are driving the score
- Changed types: what types were modified on this branch
- Consumer count: how many projects are affected

**For a PR comment (markdown):**

```powershell
uv run scatter `
  --branch-name feature/your-branch `
  --pr-risk `
  --repo-path "C:\path\to\monolith\repo" `
  --search-scope "C:\path\to\monolith\repo" `
  --output-format markdown --collapsible
```

---

## Step 5: Impact analysis (requires API key)

Analyze a work request in plain English.

```powershell
$env:GOOGLE_API_KEY = "your-gemini-api-key"

uv run scatter `
  --sow "Add tenant isolation to the portal configuration system" `
  --search-scope "C:\path\to\monolith\repo"
```

**What to look for:**
- Target quality: clear/moderate/vague — tells you how specific the SOW was
- Blast radius tree: direct and transitive consumers with risk ratings
- Complexity estimate and impact summary — paste directly into a ticket

**From a file (for longer SOWs):**

```powershell
uv run scatter `
  --sow-file "C:\path\to\your\sow.md" `
  --search-scope "C:\path\to\monolith\repo"
```

**With effort estimation:**

```powershell
uv run scatter `
  --sow "Your work request here" `
  --search-scope "C:\path\to\monolith\repo" `
  --scope-estimate --graph-metrics
```

---

## Step 6: Validate new edge types

After the graph builds, check whether the new scanners found anything in the monolith.

**Config DI edges:**

```powershell
# Check the graph JSON for config_di edges
uv run scatter --graph `
  --search-scope "C:\path\to\monolith\repo" `
  --output-format json --output-file graph.json
```

Search `graph.json` for `"config_di"` — if the monolith has Unity/Autofac `.config` files with assembly-qualified type names, you'll see edges linking the config-owning project to the type-declaring project.

**RDL sproc edges:**

Search `graph.json` for `"rdl_sproc"` — if the monolith has SSRS `.rdl` reports referencing stored procedures, you'll see edges linking report projects to sproc-owning projects.

**If you see zero config_di or rdl_sproc edges:**
- Check the build log for "Config DI scanner" and "RDL scanner" lines — they report how many files were scanned and how many matches found
- Run with `-v` for verbose output: `uv run scatter --graph --search-scope ... -v`
- The scanners only match files within the `--search-scope` — make sure it covers the full repo

---

## Step 7: Calibrate coupling weights

This is the data Marcus asked for. Compare coupling rankings before and after the new edge types.

```powershell
# Run with current weights (config_di: 0.7, rdl_sproc: 0.6)
uv run scatter --graph `
  --search-scope "C:\path\to\monolith\repo" `
  --output-format json --output-file graph_with_new_edges.json

# Check top coupled projects — do the rankings make sense?
# Are any projects jumping unexpectedly high because of config_di/rdl_sproc edges?
# If so, the weights need adjustment.
```

Record:
- Top 10 coupled projects before (from any prior run) and after
- Number of `config_di` and `rdl_sproc` edges found
- Whether any rankings changed in a way that seems wrong

---

## Troubleshooting

**"No projects found"**
- Check `--search-scope` points to a directory containing `.csproj` files
- Scatter walks subdirectories recursively — you don't need to point at each project individually

**Graph cache stale after pulling new code**
- Scatter detects changes via `git diff` and patches automatically
- If the cache seems wrong, force a rebuild: `--rebuild-graph`

**Slow first run**
- Expected for large repos. The graph caches after first build.
- Subsequent runs patch incrementally — typically under 1 second for small changes

**Config DI scanner found 0 references**
- The scanner looks for assembly-qualified type names (`Namespace.Type, AssemblyName` pattern)
- If your `.config` files use a different DI format, the regex may not match — file an issue with an example

**RDL scanner found 0 references**
- Check that `.rdl` files exist in the search scope
- The scanner matches `<CommandText>` elements — if your reports use a different XML structure, file an issue

**PowerShell path issues**
- Use full paths, not relative: `C:\path\to\repo` not `.\repo`
- Backtick (`` ` ``) is the PowerShell line continuation character, not backslash

---

## Output files to save

For team review or comparison over time, save these:

```powershell
# Full graph report
uv run scatter --graph --search-scope "C:\path\to\repo" `
  --output-format json --output-file reports\graph_$(Get-Date -Format yyyyMMdd).json

# Target project analysis
uv run scatter --target-project "C:\path\to\Project.csproj" `
  --search-scope "C:\path\to\repo" `
  --output-format json --output-file reports\target_analysis.json

# PR risk (markdown for pasting)
uv run scatter --branch-name feature/your-branch --pr-risk `
  --repo-path "C:\path\to\repo" --search-scope "C:\path\to\repo" `
  --output-format markdown > reports\pr_risk.md
```
