# Workflows

Seven real-world scenarios, each one pulled from actual team usage. Not hypothetical -- these are the problems Scatter was built to solve.

---

## 1. Pre-Merge Blast Radius Check

**Persona:** Developer preparing a PR for a feature branch.

**When:** Before requesting review. Before you write "small change" in the PR description and regret it.

**Why:** You changed three files in a shared library. You think you know who uses it. You are probably wrong. Scatter tells you who actually uses it, not who you assume does.

### Steps

**Quick scan -- what did this branch touch?**

```bash
python scatter.py --branch-name feature/add-caching \
  --repo-path /code/myrepo \
  --search-scope /code/myrepo
```

This compares your branch against `main`, extracts every type declaration from changed C# files, and finds every project that references those types. Takes seconds on a typical repo.

**Drill into the consumers with AI summaries:**

```bash
python scatter.py --branch-name feature/add-caching \
  --repo-path /code/myrepo \
  --search-scope /code/myrepo \
  --summarize-consumers
```

Now each consumer gets a 2-3 sentence summary of how it actually uses the types you changed. The difference between "ProjectX references this namespace" and "ProjectX calls `PortalDataService.GetConfig()` in its startup pipeline and caches the result for 30 minutes."

**High-precision mode with hybrid analysis:**

```bash
python scatter.py --branch-name feature/add-caching \
  --repo-path /code/myrepo \
  --search-scope /code/myrepo \
  --enable-hybrid-git \
  --summarize-consumers \
  --output-format markdown | pbcopy
```

The `--enable-hybrid-git` flag uses AI to identify precisely which types were affected in each changed file, rather than flagging every type declaration. More accurate, slower, costs API calls. Worth it for files with many types.

Pipe to clipboard, paste into the PR description. Reviewer sees the blast radius before they read a single line of code.

### What to Look For

- **Unexpected consumers.** You changed `GalaxyWorks.Data` and somehow `BillingReportGenerator` showed up? That's the conversation you need to have before merge, not after deploy.
- **Consumer count vs. expectation.** If your "small change" surfaces 10+ consumers, it is not a small change. Escalate to the team, get more eyes on it.
- **Pipeline names.** If the consumers span multiple pipelines, that's a coordinated deployment. Not a "merge and forget."
- **The filter chain.** The `142 -> 8 project refs -> 5 namespace -> 3 class match` line tells you how Scatter narrowed the field. If a stage drops to zero unexpectedly, your namespace or class filter might be wrong.

> **How this works:** Git branch analysis uses type extraction (regex or AI-assisted hybrid) to identify changed symbols, then traces consumers through project references and namespace matches. See [Architecture Overview](reference/architecture.md) for the analysis pipeline.

---

## 2. Release Night Pipeline List

**Persona:** Developer preparing a DevOps ticket for the monthly release.

**When:** After your changes are merged and before you fill out the deployment request. WEX does monthly releases. The monolith has hundreds of pipelines. Everything touches everything -- except when it doesn't, and that's the part nobody can keep straight.

**Why:** The DevOps team needs an exact list of pipelines to run on release night. Not "probably these five." Not "everything just in case." The actual pipelines affected by what you changed. Getting this wrong means either a broken release (missed a pipeline) or a 4-hour deployment window that should have been 45 minutes (ran everything).

**The pipeline list is only as complete as your `pipeline_to_app_mapping.csv`.** If a consumer project has no entry in the mapping file, it won't appear in the pipeline output. Keep the mapping current. Without `--pipeline-csv`, the `pipelines` output format produces empty output and consumer results won't include pipeline names.

### Steps

**From a feature branch -- what pipelines does my change affect?**

```bash
python scatter.py --branch-name feature/portal-tenant-isolation \
  --repo-path /code/myrepo \
  --search-scope /code/myrepo \
  --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines
```

```
galaxyworks-api-ci
galaxyworks-batch-ci
galaxyworks-webportal-ci
portal-consumer-ci
```

Four lines, four pipelines. Copy-paste into the DevOps ticket. Done.

Note: `--branch-name` requires the branch to still exist (not yet merged and deleted). Run this before merge, or use `--target-project` for changes that have already landed on `main`.

**Same command, different entry points:**

Every analysis mode supports `--pipeline-csv` and `--output-format pipelines`. Pick the entry point that matches your situation:

| Entry point | Flag | When to use |
|-------------|------|-------------|
| Feature branch | `--branch-name` | You have an open branch with changes |
| Target project | `--target-project` | You know which .csproj changed (hotfix, config change, post-merge) |
| Stored procedure | `--stored-procedure` | Database migration — sproc rename, new parameter, deprecation |
| Work request | `--sow` | Sprint planning — scope the deployment before writing code |

Just swap the mode flag. The rest of the command is the same: add `--pipeline-csv pipeline_to_app_mapping.csv --output-format pipelines`.

**Get the full consumer report with pipelines for the ticket attachment:**

```bash
python scatter.py --branch-name feature/portal-tenant-isolation \
  --repo-path /code/myrepo \
  --search-scope /code/myrepo \
  --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format csv --output-file release-pipelines.csv
```

The CSV includes one row per consumer with key columns: `ConsumerProjectName`, `PipelineName`, `TargetProjectName`, `TriggeringType`, and (when graph enrichment is available) `CouplingScore`, `FanIn`, `FanOut`, `Instability`, `InCycle`. Attach it to the DevOps ticket as backup evidence for the pipeline list.

**Feed directly into a deployment script:**

```bash
python scatter.py --branch-name feature/portal-tenant-isolation \
  --repo-path /code/myrepo \
  --search-scope /code/myrepo \
  --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines | xargs -I {} ./trigger-pipeline.sh {}
```

The `pipelines` output format is designed for this -- one name per line, sorted alphabetically, deduplicated. The output is unordered by deployment priority — if your pipelines need to run in a specific sequence (e.g., data migration before API), that sequencing is still a human decision. Pipe the list into whatever your deployment tooling expects.

**Combine pipeline lists from multiple branches for the team's monthly release:**

```bash
for branch in feature/portal-isolation feature/billing-fix feature/cache-update; do
  python scatter.py --branch-name $branch \
    --repo-path /code/myrepo \
    --search-scope /code/myrepo \
    --pipeline-csv pipeline_to_app_mapping.csv \
    --output-format pipelines
done | sort -u > release-pipelines.txt
```

### What to Look For

- **Pipeline count.** If your "small change" surfaces 8+ pipelines, that's not a small deployment. Flag it to the release coordinator early.
- **Unexpected pipelines.** `billing-reports-ci` showed up and you only touched portal code? That's a hidden dependency. Investigate before release night, not during.
- **Missing pipelines.** If you know a consumer exists but it doesn't appear in the pipeline list, the `pipeline_to_app_mapping.csv` may be out of date. Check the mapping file.
- **Sproc + code changes in the same release.** Database migrations deploy before application code. If your pipeline list includes both sproc-triggered and code-triggered consumers, make sure the migration is sequenced first in the release runbook.
- **The total list across all your team's PRs.** Run Scatter for each merged branch, concatenate the pipeline lists, sort and deduplicate. That's your team's release footprint for the month.

> **How this works:** The `pipelines` output format extracts pipeline names from consumer results (mapped via `--pipeline-csv`), deduplicates them, and prints one per line. The pipeline CSV maps `Application Name` to `Pipeline Name`. See [Output Formats](output-formats.md) for details and [Configuration](configuration.md) for pipeline mapping setup.

---

## 3. Stored Procedure Change Impact

**Persona:** Developer or DBA modifying a stored procedure.

**When:** Before changing `dbo.sp_InsertPortalConfiguration` in the database and hoping for the best.

**Why:** Sproc changes are invisible to Git branch analysis -- the SQL lives in a different repo (or no repo at all). Scatter traces from the sproc name through C# code to find every caller, then finds every consumer of those callers. The full chain.

### Steps

**Find every C# project that references the sproc:**

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope /code/myrepo
```

Scatter scans every `.cs` file for references to the sproc name, identifies which class contains the call, then finds consumers of that class.

**Export a CSV for the DBA team:**

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope /code/myrepo \
  --output-format csv --output-file sproc_impact.csv
```

DBAs love spreadsheets. Give them a spreadsheet.

**Add pipeline mappings for deployment planning:**

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope /code/myrepo \
  --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format csv --output-file sproc_impact.csv
```

Now each row includes the CI/CD pipeline name. The deployment plan writes itself.

**Narrow to a specific class if the sproc is used in multiple places:**

```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope /code/myrepo \
  --class-name PortalDataService
```

### What to Look For

- **The containing class matters.** The sproc might be called from `PortalDataService`, but the consumers are using `IPortalDataService` through dependency injection. Look at the `TriggeringType` column to see what's actually being traced.
- **Multiple containing classes.** If the sproc is referenced in more than one class, Scatter traces consumers for each one separately. The total blast radius is the union of all those chains.
- **Sproc change = coordinated deployment.** Database changes go out before application changes. The pipeline list tells you what needs to deploy after the migration runs. Get the order wrong and you get runtime exceptions at 2am.

> **How this works:** Stored procedure analysis scans `.cs` files for sproc name references, identifies the containing classes, then runs the same consumer-tracing pipeline as target project mode. See [Architecture Overview](reference/architecture.md) for the analysis pipeline.

---

## 4. Work Request Scoping with AI

**Persona:** Tech lead during sprint planning or backlog grooming.

**When:** Someone hands you a work request and asks "how big is this?" You need a number, not a feeling.

**Why:** Impact analysis mode (`--sow`) reads a natural language work description, uses AI to identify which projects, classes, or sprocs are affected, then runs the full consumer analysis automatically. It answers "what breaks if you do this" before anyone writes code.

### Steps

**Quick inline description:**

```bash
python scatter.py --sow "Add Redis caching to PortalDataService.GetConfiguration method" \
  --search-scope /code/myrepo
```

The AI parses the description, identifies `GalaxyWorks.Data` as the target project and `PortalDataService` as the class, then traces consumers through the dependency graph.

**Longer work request from a file:**

```bash
python scatter.py --sow-file /docs/work-requests/WR-2024-0342.txt \
  --search-scope /code/myrepo \
  --pipeline-csv pipeline_to_app_mapping.csv
```

For multi-paragraph work requests, point to a file. The AI does a better job with more context.

**Save structured output for the ticket:**

```bash
python scatter.py --sow-file /docs/work-requests/WR-2024-0342.txt \
  --search-scope /code/myrepo \
  --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format json --output-file WR-0342-impact.json
```

The JSON includes everything: identified targets, consumer trees, risk ratings, complexity assessment, effort estimate. Attach it to the Jira ticket.

**Paste-ready for a planning meeting:**

```bash
python scatter.py --sow "Add Redis caching to PortalDataService.GetConfiguration method" \
  --search-scope /code/myrepo \
  --output-format markdown | pbcopy
```

### What to Look For

- **Overall Risk and Complexity ratings.** AI-assessed based on the number of consumers, their depth, and the nature of the change. "Low/Medium/High/Critical" with a justification. Not a magic number -- a starting point for discussion.
- **Effort estimate.** Expressed as developer-days (e.g., "3-5 developer-days"). Calibrate against your team's actual velocity.
- **Direct vs. transitive consumers.** 3 direct + 12 transitive is a very different shape than 15 direct + 0 transitive. The first is manageable with interface contracts. The second is a rewrite.
- **Confidence labels.** HIGH means Scatter found a direct project reference and namespace match. MEDIUM means the namespace match is fuzzy. LOW means it's inferring based on naming conventions. Treat LOW-confidence consumers as "check manually."

> **How this works:** Impact analysis runs five AI tasks (parsing, risk, coupling, complexity, narrative) against structured context -- not raw code. See [Impact Analysis](usage/impact-analysis.md) for the full details and [Architecture Overview](reference/architecture.md) for the AI provider system.

---

## 5. Architecture Health Assessment

**Persona:** Architect evaluating the codebase before a modernization initiative, platform migration, or service extraction.

**When:** Before you commit to "let's extract this into a microservice" in the architecture review. Before you draw boxes on a whiteboard that don't match reality.

**Why:** Graph mode builds a full dependency graph from every `.csproj` in scope, computes coupling metrics, detects circular dependencies, identifies domain clusters, and tells you which extractions are feasible and which are fantasy.

### Steps

**Build the graph and see the summary:**

```bash
python scatter.py --graph --search-scope /code/myrepo
```

First run builds the graph from scratch and caches it. Subsequent runs load from cache in under a second.

**Get the full report with domain clusters:**

```bash
python scatter.py --graph --search-scope /code/myrepo \
  --output-format markdown | pbcopy
```

Paste into Confluence. The Mermaid diagram renders inline. The domain clusters table shows extraction feasibility scores.

**Export JSON for deeper analysis:**

```bash
python scatter.py --graph --search-scope /code/myrepo \
  --output-format json --output-file graph-report.json \
  --include-graph-topology
```

The `--include-graph-topology` flag adds the raw nodes and edges to the JSON. Omitted by default because it can get large, but you need it for custom analysis.

**Include database dependencies:**

```bash
python scatter.py --graph --search-scope /code/myrepo \
  --include-db \
  --output-format json --output-file graph-with-db.json
```

The `--include-db` flag scans for stored procedure references and direct SQL in C# files. This adds edges to the graph that represent shared database coupling -- the kind of coupling that `.csproj` references don't show you.

**Export the Mermaid diagram separately:**

```bash
python scatter.py --graph --search-scope . --output-format mermaid > deps.mmd
```

**Force a rebuild if the cache is suspect:**

```bash
python scatter.py --graph --search-scope /code/myrepo --rebuild-graph
```

### What to Look For

- **Circular dependencies.** Listed explicitly with the projects involved and the cycle path. Every circular dependency must be broken before you can extract anything cleanly.
- **Top coupled projects.** Sorted by coupling score. The top entries are the projects that are hardest to change in isolation. If your extraction target tops this list, reconsider.
- **Domain clusters.** Scatter groups projects by namespace prefix and computes cohesion and coupling for each cluster. High cohesion + low coupling = good extraction candidate. The `extraction_feasibility` field rates each cluster as `EASY`, `MODERATE`, `HARD`, or `INFEASIBLE`.
- **Health dashboard observations.** Automated observations like "4 projects have instability > 0.8" or "Cluster 'Billing' has 3 shared database objects crossing boundary." These are the things an architect would notice in a manual review -- Scatter just finds them faster.

> **How this works:** Graph mode builds a directed dependency graph from `.csproj` references and (optionally) database edges, then computes structural metrics and clustering. See [Architecture Overview](reference/architecture.md) for the graph engine and [Dependency Graph](usage/dependency-graph.md) for detailed usage.

---

## 6. Target Project Dependency Audit

**Persona:** Developer planning to refactor, version, or deprecate a shared library.

**When:** Before you change the public API of `GalaxyWorks.Data` and discover in production that 14 projects were using that method you thought was internal.

**Why:** Target project mode gives you a precise, progressively narrowable view of who consumes what. Start broad, filter down to the exact method, get AI explanations of each usage.

### Steps

**Broad scan -- who references this project at all?**

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope /code/myrepo
```

The filter chain in the output shows the funnel: total projects -> those with a `<ProjectReference>` -> those using the namespace -> those referencing specific types.

**Narrow to a specific class:**

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope /code/myrepo \
  --class-name PortalDataService
```

Now you see only consumers that actually reference `PortalDataService`, not just the namespace.

**Narrow further to a specific method:**

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope /code/myrepo \
  --class-name PortalDataService \
  --method-name GetConfiguration
```

Down to the exact call sites. If you're deprecating `GetConfiguration()`, these are the projects that need updating.

**Add AI summaries to understand the usage patterns:**

```bash
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope /code/myrepo \
  --class-name PortalDataService \
  --summarize-consumers \
  --output-format json --output-file audit.json
```

Each consumer now includes summaries of the relevant C# files, explaining not just that they reference the class but how they use it. "Calls `GetConfiguration()` during startup and caches the result" versus "Calls `GetConfiguration()` on every request in a hot loop" are very different migration stories.

### What to Look For

- **The filter funnel.** Watch the numbers drop at each stage: `142 -> 8 project refs -> 5 namespace -> 3 class match -> 2 method match`. If project refs is high but namespace match is low, you may have phantom dependencies from copy-paste .csproj editing.
- **Solutions column.** A consumer appearing in multiple solutions is harder to coordinate. Single-solution consumers can be updated in one PR.
- **Zero results at a stage.** The diagnostic hint tells us why: `Hint: 0 of 8 project-reference-matching projects contained 'PortalDataService' -- verify the class name`. Usually a spelling issue or a rename.
- **Summarization patterns.** When AI summaries show consumers doing the same thing in slightly different ways, that's a sign you need a shared abstraction, not N individual migrations.

> **How this works:** Target project analysis walks `.csproj` references, then filters by namespace usage, type references, and method calls in successive passes. See [Architecture Overview](reference/architecture.md) for the filtering pipeline and [Target Project](usage/target-project.md) for detailed usage.

---

## 7. Full Codebase Analysis Pipeline

**Persona:** DevOps engineer or architect running periodic health checks. The person who maintains the "state of the codebase" dashboard.

**When:** Weekly, on a schedule, or before quarterly planning. Trending matters more than any single snapshot.

**Why:** One graph report is a picture. A series of graph reports is a story. Coupling trending upward? New cycles appearing? Cluster feasibility eroding? These are the signals that architecture decisions get made from.

### Steps

**Generate a timestamped report:**

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
python scatter.py --graph --search-scope /code/myrepo \
  --include-db \
  --output-format json --output-file "reports/graph_${TIMESTAMP}.json" \
  --include-graph-topology
```

Run this on a schedule. Each report is a snapshot of the entire dependency graph with full metrics.

**Compare key metrics between two reports:**

```python
import json

with open("reports/graph_20260310_090000.json") as f:
    old = json.load(f)
with open("reports/graph_20260317_090000.json") as f:
    new = json.load(f)

print(f"Nodes: {old['summary']['node_count']} -> {new['summary']['node_count']}")
print(f"Edges: {old['summary']['edge_count']} -> {new['summary']['edge_count']}")
print(f"Cycles: {old['summary']['cycle_count']} -> {new['summary']['cycle_count']}")

# Compare top coupled projects
old_top = {p['project']: p['coupling_score'] for p in old['top_coupled']}
new_top = {p['project']: p['coupling_score'] for p in new['top_coupled']}
for project in new_top:
    delta = new_top[project] - old_top.get(project, 0)
    if abs(delta) > 0.5:
        print(f"  {project}: coupling {old_top.get(project, 'NEW'):>6} -> {new_top[project]:>6} ({'+' if delta > 0 else ''}{delta:.1f})")
```

This is a 15-line script that tells you more about architecture drift than a week of code review.

**Force a full rebuild if the cache is suspect:**

```bash
python scatter.py --graph --search-scope /code/myrepo \
  --rebuild-graph \
  --output-format json --output-file "reports/graph_${TIMESTAMP}.json"
```

Cache invalidation is automatic (Scatter checks file hashes and project sets), but if you've moved directories around or done major restructuring, a forced rebuild ensures clean data.

**Generate a Markdown dashboard for the team:**

```bash
python scatter.py --graph --search-scope /code/myrepo \
  --output-format markdown --output-file "reports/health-dashboard.md"
```

Commit this to the repo wiki. The Mermaid diagram renders inline. Update weekly.

### What to Look For

- **Increasing edge counts.** More edges = more coupling. If `edge_count` is trending up faster than `node_count`, the codebase is getting more tangled, not less.
- **New cycles.** A cycle count going from 2 to 3 means someone introduced a circular dependency this week. Find it while the context is fresh.
- **Feasibility erosion.** If a cluster's extraction feasibility drops from `MODERATE` to `HARD`, something crossed a boundary that shouldn't have.
- **Top coupled project churn.** The same project topping the coupling list every week is expected (legacy core libraries tend to live there). A new project appearing in the top 5 is a signal worth investigating.
- **Health dashboard observations.** The automated observations highlight the things that changed or crossed thresholds -- designed for exactly this trending use case.

> **How this works:** Graph reports are JSON snapshots of the full dependency graph with structural metrics. The graph engine caches aggressively and invalidates via git diff. See [Architecture Overview](reference/architecture.md) for the graph engine and caching system.
