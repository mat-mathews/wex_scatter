# Output Formats

Scatter speaks six output languages. Each exists because someone had a real need -- a PR review, a deployment checklist, a Confluence page, a Mermaid diagram. The `--output-format` flag controls which one you get. Default is `console`.

---

## 1. Console (default)

When you just want to see what's going on. No flags, no files, no ceremony.

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv
```

```
Search scope: /code/myrepo (scanned 142 projects, 3,891 files)
Filter: 142 → 8 project refs[graph] → 5 namespace → 3 class match

============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
  Consumers: 3
  Triggering type: PortalDataService

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  PortalBatchProcessor                         8.2       0       3    1.00 PortalServices.sln
  MyGalaxyConsumerApp                          4.3       0       2    1.00 GalaxyWorks.sln
  MyGalaxyConsumerApp2                         1.8       0       1    1.00 GalaxyWorks.sln

    [portal-nightly-sync] PortalBatchProcessor

Analysis complete. 3 consumer(s) found across 1 target(s).
```

Consumers are sorted by coupling score (highest risk first). When a graph cache exists, the table includes Score, Fan-In, Fan-Out, and Instability columns automatically.

High coupling score on a project you depend on is one you do not want to surprise with a breaking change on a Friday afternoon.

---

## 2. JSON

Structured data for programmatic consumption -- ticket automation, dashboards, diffing between runs.

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file report.json
```

Requires `--output-file`. Scatter won't dump JSON to stdout -- that path leads to accidental pipe disasters with multi-megabyte payloads.

```json
{
    "metadata": {
        "scatter_version": "0.12.0",
        "timestamp": "2026-03-17T14:32:01.123456+00:00",
        "cli_args": { "..." : "..." },
        "search_scope": "/code/myrepo",
        "duration_seconds": 2.41,
        "graph_enriched": true
    },
    "filter_pipeline": {
        "search_scope": "/code/myrepo",
        "total_projects_scanned": 142,
        "total_files_scanned": 3891,
        "stages": [ "..." ]
    },
    "pipeline_summary": [
        "galaxy-consumer-ci",
        "galaxy-consumer2-ci",
        "portal-batch-ci"
    ],
    "all_results": [
        {
            "TargetProjectName": "GalaxyWorks.Data",
            "TargetProjectPath": "GalaxyWorks.Data/GalaxyWorks.Data.csproj",
            "TriggeringType": "PortalDataService",
            "ConsumerProjectName": "MyGalaxyConsumerApp",
            "ConsumerProjectPath": "MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj",
            "ConsumingSolutions": ["GalaxyWorks.sln"],
            "ConsumerFileSummaries": {},
            "PipelineName": "galaxy-consumer-ci",
            "BatchJobVerification": null,
            "CouplingScore": 4.3,
            "FanIn": 1,
            "FanOut": 3,
            "Instability": 0.75,
            "InCycle": false
        }
    ]
}
```

A few things worth knowing:

- **`pipeline_summary`** is sorted and deduplicated. Quick "what needs to deploy" check without iterating `all_results`.
- **`ConsumerFileSummaries`** is a native JSON object (not stringified). Keys are relative file paths, values are AI-generated summaries. Empty `{}` when `--summarize-consumers` is not used.
- **`PipelineName`** and **`BatchJobVerification`** are `null` when absent, not empty strings.
- **Path objects** serialize as strings. The custom serializer handles this transparently -- you'll never see a `PosixPath(...)` in the output.
- **Graph metrics** (`CouplingScore`, `FanIn`, `FanOut`, `Instability`, `InCycle`) appear only when graph enrichment ran. Otherwise those keys are absent entirely.

---

## 3. CSV

One row per consumer. For Excel, pivot tables, and people who think in spreadsheets.

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format csv --output-file report.csv
```

Requires `--output-file`.

```
# Search scope: /code/myrepo (142 projects, 3,891 files)
# Filter: 142 → 8 project refs[graph] → 5 namespace → 3 class match
TargetProjectName,TargetProjectPath,TriggeringType,ConsumerProjectName,ConsumerProjectPath,ConsumingSolutions,PipelineName,BatchJobVerification
GalaxyWorks.Data,GalaxyWorks.Data/GalaxyWorks.Data.csproj,PortalDataService,MyGalaxyConsumerApp,MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj,GalaxyWorks.sln,galaxy-consumer-ci,
```

The `#`-prefixed lines at the top are comment headers showing the search scope and filter chain. Most CSV parsers skip them automatically. If yours doesn't, strip lines starting with `#` before parsing.

When graph enrichment is active, five additional columns appear: `CouplingScore`, `FanIn`, `FanOut`, `Instability`, `InCycle`.

`ConsumingSolutions` uses semicolons as the delimiter when a consumer belongs to multiple solutions (e.g., `GalaxyWorks.sln; PortalServices.sln`).

---

## 4. Markdown

Paste-ready for PRs, Jira tickets, Confluence pages, ADO work items. Designed for humans reading rendered text, not raw data.

Unlike CSV and JSON, Markdown does **not** require `--output-file`. Without it, Scatter prints to stdout. This is intentional -- pipe it straight to clipboard:

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format markdown | pbcopy
```

```markdown
# Consumer Analysis Report

> **Search scope:** /code/myrepo (scanned 142 projects, 3,891 files)
> **Filter:** 142 → 8 project refs[graph] → 5 namespace → 3 class match

## GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (3 consumer(s))

Triggering type: PortalDataService

| Consumer | Path | Pipeline | Solutions |
| --- | --- | --- | --- |
| MyGalaxyConsumerApp | MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj | galaxy-consumer-ci | GalaxyWorks.sln |
| MyGalaxyConsumerApp2 | MyGalaxyConsumerApp2/MyGalaxyConsumerApp2.csproj | galaxy-consumer2-ci | GalaxyWorks.sln |
| PortalBatchProcessor | PortalBatchProcessor/PortalBatchProcessor.csproj | portal-batch-ci | PortalServices.sln |

---
**Total:** 3 consuming relationship(s) across 1 target(s).
```

Impact mode includes a blast radius tree rendered as a code block (so it survives Markdown rendering without losing structure):

```text
+-- MyGalaxyConsumerApp  [HIGH]  direct
|   Pipeline: galaxy-consumer-ci
|   +-- GalaxyPortalUI  [MEDIUM]  via MyGalaxyConsumerApp
+-- MyGalaxyConsumerApp2  [HIGH]  direct
|   Pipeline: galaxy-consumer2-ci
+-- PortalBatchProcessor  [HIGH]  direct
    Pipeline: portal-batch-ci
```

When `--graph-metrics` is active, the table gains five extra columns: Coupling, Fan-In, Fan-Out, Instability, In Cycle.

---

## 5. Mermaid

Graph mode only. Raw Mermaid diagram syntax -- no wrapping markdown, no summary tables.

```bash
scatter --graph --search-scope . --output-format mermaid
```

```
graph TD
  GalaxyWorks_Data["GalaxyWorks.Data"]
  MyDotNetApp["MyDotNetApp"]
  MyDotNetApp_Consumer["MyDotNetApp.Consumer"]
  MyGalaxyConsumerApp["MyGalaxyConsumerApp"]
  MyGalaxyConsumerApp2["MyGalaxyConsumerApp2"]
  MyDotNetApp_Consumer --> MyDotNetApp
  MyGalaxyConsumerApp --> GalaxyWorks_Data
  MyGalaxyConsumerApp2 --> GalaxyWorks_Data
```

If domain clusters were detected, nodes are grouped into Mermaid subgraphs. Renders natively in GitHub PRs, Azure DevOps wikis, and Confluence.

Using `--output-format mermaid` outside of `--graph` mode is an error -- Scatter will tell you so and exit.

```bash
# Save to file
scatter --graph --search-scope . --output-format mermaid --output-file deps.mmd
```

---

## 6. Pipelines

One pipeline name per line, sorted alphabetically. Built for deployment scripts and shell pipelines (the other kind).

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines
```

```
galaxy-consumer-ci
galaxy-consumer2-ci
portal-batch-ci
```

Three lines, three pipelines that need to deploy. That's the entire output.

Requires `--pipeline-csv` to map consumer projects to pipeline names. Without it, the output will be empty. Scatter warns you about this, but won't stop you.

Not supported in `--graph` mode. Graph analysis is about architecture, not deployments.

```bash
# Feed directly into a deployment script
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --pipeline-csv pipeline_to_app_mapping.csv \
  --output-format pipelines | xargs -I {} ./trigger-pipeline.sh {}
```

---

## Quick Reference

| Format | Requires `--output-file`? | Available modes |
| --- | --- | --- |
| Console (default) | No | All |
| JSON | Yes | All |
| CSV | Yes | All |
| Markdown | No | All |
| Mermaid | No | Graph only |
| Pipelines | No | All except Graph |

> **How this works:** Each reporter is a standalone module in `scatter/reports/`. See [Architecture Overview](reference/architecture.md) for the module map.
