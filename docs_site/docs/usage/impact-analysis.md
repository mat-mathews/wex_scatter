# Impact Analysis

A work request or CSE comes in... Before anyone writes code, you need to know what it'll touch and how risky it is. This mode turns Scatter from a developer tool into a project-scoping tool.

Describe the change in plain English. Get back a risk-rated blast radius report with a tree view of affected consumers, confidence labels by depth, and an AI-generated narrative you can paste straight into a ticket.

The `--sow` mode requires a configured AI provider (currently Google Gemini via `--google-api-key` or `$GOOGLE_API_KEY`; WEX AI Platform coming soon). Other modes (`--target-project`, `--branch-name`, `--graph`) work without AI. The core consumer tracing, graph building, and blast radius tree are pure code -- AI adds risk ratings, coupling narratives, complexity estimates, and executive summaries on top.

## Basic Example

```bash
scatter \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY
```

```
=== Impact Analysis Report ===
Work Request: Modify PortalDataService in GalaxyWorks.Data to add a new parameter...
Overall Risk: High | Complexity: Medium (3-5 developer-days)

--- Target: GalaxyWorks.Data ---
Direct Consumers: 4 | Transitive: 2

+-- GalaxyWorks.WebPortal  [HIGH]  direct
|   Risk: High -- "WebPortal directly invokes StorePortalConfigurationAsync"
|   Pipeline: galaxyworks-webportal-ci
|   Coupling: WebPortal uses PortalDataService in 3 controller files for
|     all portal configuration CRUD operations.
|   Coupling vectors: method_invocation, constructor_injection
|   +-- GalaxyWorks.BatchProcessor  [MEDIUM]  via GalaxyWorks.WebPortal
|       Risk: Medium -- "Transitively affected through WebPortal dependency"
|       Pipeline: galaxyworks-batch-ci
+-- MyGalaryConsumerApp  [HIGH]  direct
|   Risk: Medium -- "Uses PortalDataService but only reads, does not write"
|   Coupling vectors: method_invocation
+-- MyGalaryConsumerApp2  [HIGH]  direct
|   Risk: Medium -- "Minimal usage of PortalDataService"
+-- GalaxyWorks.Api  [HIGH]  direct
    Risk: High -- "API controller exposes PortalDataService methods to external callers"
    Pipeline: galaxyworks-api-ci

--- Complexity ---
Medium: Change requires modifying one class in GalaxyWorks.Data and updating
4 direct consumers. Two consumers require signature changes in controller code.

--- Impact Summary ---
This change affects the core data access layer used by 4 direct consumers and
2 transitive consumers. The highest risk is in GalaxyWorks.WebPortal and
GalaxyWorks.Api, which both directly invoke the affected method. Recommend
coordinated deployment with WebPortal and API teams.

Analysis complete. 6 consumer(s) found across 1 target(s).
```

That's a lot of information from a one-line description. Let's break down what you're looking at.

## Reading the Report

**Overall Risk and Complexity** appear at the top. Complexity is always an AI estimate of effort. Risk uses a two-layer model:

1. **Graph-derived risk** (deterministic) — when a dependency graph is available, the risk engine scores each target across 7 dimensions: structural coupling, instability, cycle entanglement, database coupling, blast radius, domain boundaries, and change surface. This produces a reproducible rating — same input, same score, no AI variance.
2. **AI enrichment** (escalation-only) — AI can raise a rating (e.g. "High" to "Critical") when it detects business context the graph can't see, but it can never lower a graph-derived rating. Without a graph, AI provides the primary risk rating directly.

Overall risk is the worst-case across all targets.

**The tree view** shows direct consumers at the root level and transitive consumers nested beneath the consumer they flow through. The brackets show confidence:

- **[HIGH]** -- direct consumer. This project references the target and uses the relevant class.
- **[MEDIUM]** -- one hop away. It references a direct consumer, not the target itself.
- **[LOW]** -- two or more hops away. Real impact is possible but increasingly unlikely.

**Coupling vectors** tell you how a consumer is connected: `method_invocation`, `constructor_injection`, `type_reference`, etc. These help you estimate how hard the consumer update will be.

**The impact summary** at the bottom is AI-generated prose, suitable for pasting into a Jira ticket or a Slack message to your manager. It covers the scope, highest-risk consumers, and a deployment recommendation.

## From a File

```bash
scatter \
  --sow-file examples/sample_sow.md \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY
```

For longer work requests -- feature specs, change proposals, migration plans -- write the description in a text file and pass it via `--sow-file`. The file is read as UTF-8.

## Codebase Index

When a dependency graph is available (which it usually is -- Scatter builds and caches one automatically), impact analysis sends a compact **codebase index** alongside the SOW to the LLM. This index lists every project, its types, and its stored procedures, so the LLM can match domain language to real code artifacts instead of guessing.

The index is what makes vague SOWs work. A request like "update the portal configuration workflow to support multi-tenant isolation" maps to `GalaxyWorks.Data`, `PortalDataService`, and `dbo.sp_InsertPortalConfiguration` because those names are in the index.

You can inspect the index directly:

```bash
scatter --dump-index --search-scope .
```

```
=== Codebase Index (11 projects) ===
P=Project NS=Namespace (omitted when same as project name) T=Types SP=StoredProcs
P:GalaxyWorks.Data T:PortalDataService,PortalConfiguration,IDataAccessor SP:dbo.sp_InsertPortalConfiguration,...
P:GalaxyWorks.WebPortal T:PortalController,PortalCacheService SP:dbo.sp_GetPortalConfigurationDetails,...
...
```

When the LLM returns a target name not found in the index, its confidence is automatically halved. This prevents hallucinated project names from driving analysis.

## Target Quality

After parsing, Scatter classifies the target set:

- **clear** -- 5 or fewer targets, average confidence >= 0.7. The SOW was specific.
- **moderate** -- 6-10 targets, or average confidence between 0.4-0.7. Some ambiguity.
- **vague** -- more than 10 targets, or average confidence below 0.4. The SOW is broad.

This appears in the report header:

```
Target Quality: moderate (7 targets, avg confidence 0.62)
```

Each target also shows **match evidence** -- a one-sentence explanation of why the LLM identified it:

```
--- Target: GalaxyWorks.Data ---
Evidence: Project contains PortalDataService which handles portal configuration persistence
```

## Confidence Filtering

```bash
scatter \
  --sow-file examples/sample_sow.md \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --sow-min-confidence 0.5
```

The `--sow-min-confidence` flag (default: 0.3) excludes targets below the threshold. Excluded targets are logged:

```
Excluded target 'Billing.Data' (confidence 0.30, threshold 0.50)
```

Use a higher threshold when you want fewer, higher-confidence results. Use the default when you want broader coverage and are willing to triage.

## Deeper Tracing

```bash
scatter \
  --sow "Refactor GalaxyWorks.Data to split PortalDataService into separate read/write classes" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --max-depth 3
```

Default transitive depth is 2. Increase `--max-depth` when you need to trace further through the dependency chain. Be aware that each depth level multiplies the consumer detection calls, and each hop reduces confidence. Depth 3 is usually sufficient. Beyond that, you're mapping theoretical risk rather than practical impact.

## Output Formats

**JSON** -- includes everything: targets, consumers with depth and confidence, risk ratings, coupling vectors, complexity estimates, and narrative summaries. This is the format for feeding impact data into other tools.

```bash
scatter \
  --sow "Add caching to GalaxyWorks.Data" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file impact_report.json
```

**CSV** -- flattens the tree into rows (one per consumer) with columns for depth, confidence, risk rating, and pipeline name. Good for spreadsheet triage.

```bash
scatter \
  --sow "Modify stored procedure sp_InsertPortalConfiguration" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --output-format csv --output-file impact_report.csv
```

**Markdown** -- prints to stdout without `--output-file`. Pipe it into a PR description, paste it into Confluence, or redirect to a file.

```bash
scatter \
  --sow "Deprecate FakeDatabaseHelper" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --output-format markdown
```

See [Output Formats](../output-formats.md) for detailed structure of each format.

## Effort Estimation

Add `--scope-estimate` to get a structured effort breakdown on top of the impact report:

```bash
scatter \
  --sow "Add tenant isolation to the portal configuration system" \
  --search-scope . \
  --scope-estimate \
  --graph-metrics
```

This adds an effort table with five categories (investigation, implementation, testing, integration risk, database migration), confidence bands, and database impact assessment. The numbers are graph-derived — no AI involved in the base estimate.

See [SOW Scoping](scoping.md) for the full breakdown of categories, heuristics, and confidence levels.

## Risk Model

Impact analysis uses the same 7-dimension risk engine as PR risk scoring. When a dependency graph is available, each target gets a deterministic risk profile across structural coupling, instability, cycles, database coupling, blast radius, domain boundaries, and change surface. AI can escalate but never lower graph-derived ratings.

See [Risk Engine](risk-engine.md) for the full model.

---

!!! info "How this works"
    Scatter builds a codebase index from the dependency graph and sends it alongside the SOW to the LLM. The AI parses the work request into structured targets, Scatter runs consumer detection per target, then BFS traces transitive consumers up to `--max-depth`. Risk scoring and AI enrichment follow (see [Reading the Report](#reading-the-report) above). Target names not in the index get their confidence halved automatically. See [Architecture Overview](../reference/architecture.md) for the full pipeline.
