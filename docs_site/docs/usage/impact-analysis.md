# Impact Analysis

A work request or CSE comes in... Before anyone writes code, you need to know what it'll touch and how risky it is. This mode turns Scatter from a developer tool into a project-scoping tool.

Describe the change in plain English. Get back a risk-rated blast radius report with a tree view of affected consumers, confidence labels by depth, and an AI-generated narrative you can paste straight into a ticket.

This mode requires a Google API key (`--google-api-key` or `$GOOGLE_API_KEY`). Other modes work without AI. The core consumer tracing, graph building, and blast radius tree are pure code — AI adds risk ratings, coupling narratives, and the executive summary on top.

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
+-- MyGalaxyConsumerApp  [HIGH]  direct
|   Risk: Medium -- "Uses PortalDataService but only reads, does not write"
|   Coupling vectors: method_invocation
+-- MyGalaxyConsumerApp2  [HIGH]  direct
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

**Risk comes from two sources:**

| Layer | How it works | Reproducible? |
|-------|-------------|---------------|
| **Graph-derived** | Scores each target across 7 dimensions (coupling, instability, cycles, database, blast radius, domain boundaries, change surface) | Yes — same input, same score |
| **AI enrichment** | Can escalate a rating (e.g. "High" → "Critical") when it detects business context the graph can't see. Can never lower a graph-derived rating. | No — AI variance applies |

Overall risk is the worst-case across all targets. Complexity is an AI effort estimate.

**The tree view** shows direct consumers at root level, transitive consumers nested beneath:

- **[HIGH]** — direct consumer. References the target and uses the relevant class.
- **[MEDIUM]** — one hop away. References a direct consumer, not the target itself.
- **[LOW]** — two or more hops away. Real impact possible but increasingly unlikely.

**Coupling vectors** (`method_invocation`, `constructor_injection`, `type_reference`) tell you *how* a consumer is connected — useful for estimating how hard the update will be.

**The impact summary** at the bottom is AI-generated prose. Paste it into a Jira ticket or a Slack message. It covers scope, highest-risk consumers, and a deployment recommendation.

## From a File

```bash
scatter \
  --sow-file examples/sample_sow.md \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY
```

For longer work requests -- feature specs, change proposals, migration plans -- write the description in a text file and pass it via `--sow-file`. The file is read as UTF-8.

## Codebase Index

Scatter sends the LLM a compact **codebase index** — every project name, its type names, and its stored procedure names — so it can match domain language to real code artifacts instead of guessing. The graph builds and caches automatically; you don't configure this.

!!! note "What leaves the network"
    The codebase index contains project names, type names, namespace names, and stored procedure names. It does **not** contain source code, file contents, or business logic. Your SOW text is also sent. Both go to Google's Gemini API. Use `--dump-index` to see exactly what the LLM receives.

The index is what makes vague SOWs work. A request like "update the portal configuration workflow to support multi-tenant isolation" maps to `GalaxyWorks.Data`, `PortalDataService`, and `dbo.sp_InsertPortalConfiguration` because those names are in the index.

You can inspect the index directly:

```bash
scatter --dump-index --search-scope .
```

```
=== Codebase Index (13 projects) ===
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

The `--sow-min-confidence` flag (default: 0.3) excludes targets below the threshold. Targets that get filtered out are logged so you can see what was dropped. Raise the threshold when you want fewer, sharper results. Keep the default when you'd rather see everything and triage manually.

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

Same 7-dimension risk engine as PR risk scoring. Graph-derived scores are deterministic. AI can escalate but never lower them. See [Risk Engine](risk-engine.md) for the full model.

---

!!! info "How this works"
    Scatter builds a codebase index from the dependency graph and sends it alongside the SOW to the LLM. The AI parses the work request into structured targets, Scatter runs consumer detection per target, then BFS traces transitive consumers up to `--max-depth`. Risk scoring and AI enrichment follow (see [Reading the Report](#reading-the-report) above). Target names not in the index get their confidence halved automatically. See [Architecture Overview](../reference/architecture.md) for the full pipeline.
