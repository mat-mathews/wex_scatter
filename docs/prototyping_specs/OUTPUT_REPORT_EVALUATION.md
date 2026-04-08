# Output Report Evaluation

An evaluation of Scatter's three output formats (console, JSON, CSV) across all five analysis modes, with suggestions for improving usefulness and developer-friendliness.

---

## Evaluation Criteria

Each report is assessed on:

- **Scannability** — Can you quickly find the answer you came for?
- **Completeness** — Does it include everything needed to act on the results?
- **Noise** — Are there empty or irrelevant fields cluttering the output?
- **Programmatic usability** — Can downstream tools consume it easily?
- **Consistency** — Does the structure follow the same patterns across modes?

---

## 1. Console Report

### Legacy Modes (Git / Target / Sproc)

**Current output:**

```
============================================================
  Consumer Analysis
============================================================
  Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
  Consumers: 4

  Consumer                                   Score  Fan-In Fan-Out Instab. Solutions
  ---------------------------------------- ------- ------- ------- ------- -------------------------
  GalaxyWorks.WebPortal                       12.7       1       1    0.50 GalaxyWorks.sln
  GalaxyWorks.BatchProcessor                  10.8       0       2    1.00 GalaxyWorks.sln
  MyGalaryConsumerApp                          4.3       0       2    1.00 GalaxyWorks.sln
  MyGalaryConsumerApp2                         1.8       0       1    1.00 GalaxyWorks.sln

Analysis complete. 4 consumer(s) found across 1 target(s).
```

**Strengths:**
- Aligned columnar table — easy to scan and compare metrics
- Sorted by coupling score (highest risk first)
- Per-target consumer count shown inline
- "N/A (Project Reference)" suppressed when no class filter is used
- Clean `====` header block matching graph mode style
- Summary footer with total count

**Resolved issues (from prior evaluation):**
1. ~~"Type/Level: N/A" noise~~ — suppressed when not applicable
2. ~~No per-target count~~ — `Consumers: N` shown per target
3. ~~"done." debug output~~ — replaced with `Analysis complete.` summary
4. ~~No visual separator~~ — `====` block header
5. **Pipeline and solution info only appear when populated.** This is good behavior (no noise), but there's no indication that these enrichments are *available* — a user who doesn't know about `--pipeline-csv` won't discover it from the output.
6. **Paths are relative and consistent.** Target paths show `GalaxyWorks.Data/GalaxyWorks.Data.csproj` (relative), which is good for readability.
- Drop or rephrase "Type/Level: N/A (Project Reference)" — when there's no class filter, omit the line entirely or say "Filter: none"
- Remove the "done." line, or replace it with a clean footer like a horizontal rule
- Add a hint when no pipeline mapping is provided: `(Tip: add --pipeline-csv to see CI/CD pipeline mappings)`

### Impact Analysis Mode

**Strengths:**
- Excellent header: `Overall Risk: High | Complexity: Medium (3-5 developer-days)` — this is exactly what a tech lead needs at a glance
- Depth labeling (`direct` vs `depth: 1`) clearly shows transitive relationships
- Coupling narrative and vectors explain *why* the dependency exists, not just *that* it exists
- The complexity and impact narrative sections at the bottom provide executive-summary material

**Issues:**
1. **Confidence labels (HIGH/MEDIUM/LOW) are shown but confidence scores are not.** The console shows `[HIGH]` but not `1.0`. For a developer, the label is enough; for someone comparing entries, the numeric score would help.
2. **Long coupling narratives can dominate the output.** They're wrapped at 80 chars, which is good, but when there are many consumers each with a multi-line narrative, the report becomes very long and hard to scan.
3. **No visual grouping or color.** All consumers under a target look the same — high-risk and low-risk consumers aren't visually differentiated.

**Suggestions:**
- Add the confidence score in parentheses after the label: `[HIGH (1.0)]`
- Consider a compact mode that shows only the risk table without narratives, with a flag like `--detail` to expand
- Add a summary table at the top listing all consumers with their risk level before the detailed breakdown

### Graph Analysis Mode

**Strengths:**
- Clean, well-aligned tabular output for coupled projects and clusters
- Key metrics (projects, dependencies, components, cycles) are prominently displayed in the header
- Feasibility ratings with numeric scores give both a quick label and precision

**Issues:**
1. **No list of projects.** The report tells you there are 108 projects but doesn't list them. You can't see which projects were discovered without using JSON output.
2. **No edge details.** You can see fan-in/fan-out counts but not which specific projects are connected. The console report doesn't show any individual edges.
3. **Cluster members are not shown.** You see "cluster_0 has 100 projects" but can't see which projects are in it without switching to JSON output.
4. **TestProject artifacts from temp_test_data are polluting results.** The top coupled projects table is dominated by `TestProject049`, `TestProject003`, etc. — these are synthetic test fixtures that probably shouldn't appear in a real analysis. This is a search-scope / exclude-pattern issue rather than a reporting issue, but it affects the report's usefulness.
5. **"Instab." column header abbreviation is non-standard.** Consider "Instability" or at least "Inst." which is more recognizable.

**Suggestions:**
- Add a `--detail` flag to show cluster members and top edges in console output
- Show the top 3-5 projects in each cluster inline: `cluster_1 (8): GalaxyWorks.Data, GalaxyWorks.WebPortal, ...`
- Show cycle members prominently (currently only shown if cycles exist, which is correct)
- Consider showing a mini dependency tree for the highest-coupled project

---

## 2. JSON Report

### Legacy Modes (Git / Target / Sproc)

**Current output:**

```json
{
    "pipeline_summary": [],
    "all_results": [
        {
            "TargetProjectName": "GalaxyWorks.Data",
            "TargetProjectPath": "GalaxyWorks.Data/GalaxyWorks.Data.csproj",
            "TriggeringType": "N/A (Project Reference)",
            "ConsumerProjectName": "GalaxyWorks.BatchProcessor",
            "ConsumerProjectPath": "GalaxyWorks.BatchProcessor/...",
            "ConsumingSolutions": "",
            "PipelineName": "",
            "BatchJobVerification": "",
            "ConsumerFileSummaries": "{}"
        }
    ]
}
```

**Issues:**
1. **Empty strings everywhere.** `ConsumingSolutions`, `PipelineName`, `BatchJobVerification` are empty strings (`""`) instead of `null` or being omitted entirely. This forces consumers to check for both `null` and `""`. A JSON consumer has to write `if data["PipelineName"]` rather than `if data.get("PipelineName") is not None`.
2. **`ConsumerFileSummaries` is a JSON string inside JSON.** The value is `"{}"` — a string containing JSON, not an actual JSON object. This means consumers have to `json.loads()` the field to use it. This is a significant DX issue: `result["ConsumerFileSummaries"]["Program.cs"]` fails because the value is a string, not a dict.
3. **`ConsumingSolutions` is a CSV string inside JSON.** Same problem — `"Solution1, Solution2"` should be `["Solution1", "Solution2"]`. Embedding a comma-separated format inside a structured format defeats the purpose of JSON.
4. **Flat structure repeats target info on every row.** Each result repeats `TargetProjectName` and `TargetProjectPath`. For a target with 20 consumers, this is 20 copies of the same target info. A hierarchical structure (target → consumers[]) would be cleaner and smaller.
5. **`TriggeringType` naming is unclear.** The key name doesn't convey its meaning to someone unfamiliar with the codebase. Consider `filter_level` or `analysis_trigger`.
6. **PascalCase field names are unusual for JSON.** JSON convention is camelCase or snake_case. PascalCase suggests these were mapped directly from C# DTOs. For a Python tool, snake_case would be more natural.
7. **No metadata.** No timestamp, tool version, command-line arguments used, or analysis duration. This makes it hard to reproduce or compare reports.

**Suggestions:**
- Use `null` instead of `""` for absent optional fields, or omit them entirely
- Make `ConsumerFileSummaries` a proper JSON object, not a stringified one
- Make `ConsumingSolutions` a proper JSON array
- Consider a hierarchical structure matching the impact mode format
- Add a `metadata` top-level key with timestamp, scatter version, and the CLI arguments used
- Consider migrating to snake_case field names (with a deprecation period if needed)

### Impact Analysis Mode

**Strengths:**
- Uses `dataclasses.asdict()` which produces clean, hierarchical JSON
- Proper nesting: `targets[].consumers[]` — no repeated target info
- Lists are proper JSON arrays (solutions, coupling_vectors)
- Path objects are properly serialized to strings

**Issues:**
1. **Inconsistent with legacy mode.** Legacy mode uses PascalCase flat rows; impact mode uses snake_case nested objects. A developer using both modes has to handle two completely different schemas.
2. **No metadata** (same as legacy).
3. **`target.project_path`** can be `null` when the target was identified by name only. This is correct behavior but should be documented.

**Suggestions:**
- Add metadata (timestamp, version, CLI args)
- Document the schema differences between legacy and impact mode, or plan to unify them

### Graph Analysis Mode

**Strengths:**
- Comprehensive: includes summary, top_coupled, cycles, per-project metrics, clusters, and the full graph topology
- Metrics are properly rounded
- Cluster feasibility_details breaks down individual penalty factors — very useful for actionable follow-up
- The full graph (nodes + edges) is included, enabling custom analysis

**Issues:**
1. **Massive output size.** Including the full `graph.to_dict()` with all 108 nodes and 117 edges makes the file very large. For a real enterprise codebase with thousands of projects, this could be megabytes. Consider making the full graph optional (e.g., `--include-graph-topology`).
2. **No metadata** (same as other modes).
3. **`top_coupled` doesn't include all metric fields.** It has coupling_score, fan_in, fan_out, instability — but not afferent_coupling, efferent_coupling, shared_db_density, type_export_count, consumer_count. You have to cross-reference with the `metrics` section by project name.
4. **Cluster `shared_db_objects` is always an empty list** in the sample output. If this field is frequently empty, consider omitting it when empty.

**Suggestions:**
- Add a `--include-graph-topology` flag, default to omitting the raw graph to keep JSON reports focused on the analysis results
- Add metadata
- Include all metric fields in `top_coupled` entries so they're self-contained
- Consider adding a `generated_at` timestamp to each section for staleness detection

---

## 3. CSV Report

### Legacy Modes (Git / Target / Sproc)

**Current output:**

```
TargetProjectName,TargetProjectPath,TriggeringType,ConsumerProjectName,ConsumerProjectPath,ConsumingSolutions,PipelineName,BatchJobVerification,ConsumerFileSummaries
GalaxyWorks.Data,...,N/A (Project Reference),GalaxyWorks.BatchProcessor,...,,,,{}
```

**Issues:**
1. **`ConsumerFileSummaries` column contains `{}`** — a JSON object in a CSV cell. This is messy for spreadsheet users. Excel will display `{}` as text, and when summaries are populated, the JSON-in-CSV will break column alignment and may cause parsing issues with embedded commas/quotes.
2. **Empty columns are included.** When no pipeline mapping or batch job verification is configured, every row has trailing empty columns. This adds visual noise in spreadsheets.
3. **No header documentation.** Column names like `TriggeringType` and `BatchJobVerification` aren't self-explanatory.

**Suggestions:**
- Omit `ConsumerFileSummaries` from CSV output entirely — JSON is the right format for nested data. If summaries are needed, point users to JSON output.
- Consider omitting columns that are entirely empty across all rows (e.g., if no `--pipeline-csv` was provided, omit `PipelineName`)
- Add a comment row or companion README explaining column meanings

### Impact Analysis Mode

**Strengths:**
- Clean column structure: `Target, TargetType, Consumer, ConsumerPath, Depth, Confidence, ConfidenceLabel, RiskRating, RiskJustification, Pipeline, Solutions, CouplingVectors`
- One row per consumer makes it easy to sort/filter in a spreadsheet
- Depth and confidence as numeric columns enable sorting

**Issues:**
1. **`RiskJustification` can contain long multi-sentence text.** This makes rows very wide in a spreadsheet. Consider truncating to N characters in CSV and directing users to JSON for full text.
2. **`CouplingVectors` is a comma-separated list inside a CSV cell.** This is the same CSV-in-CSV problem. Consider using semicolons or pipe characters as the inner delimiter.
3. **No target-level summary row.** You get individual consumer rows but no subtotal row showing the aggregate for each target (total direct, total transitive, overall risk).

**Suggestions:**
- Use semicolons for list fields within CSV cells (Solutions, CouplingVectors) to avoid delimiter collision
- Add a summary row per target with aggregated counts
- Consider a `--csv-compact` mode that drops narrative columns (RiskJustification, CouplingVectors) for spreadsheet-friendly output

### Graph Analysis Mode

**Not supported.** Attempting `--graph --output-format csv` falls through to console output silently.

**Suggestions:**
- Either add CSV support (one row per project with metrics, or one row per edge) or print an explicit error message: `"CSV output is not supported for graph analysis. Use --output-format json instead."`
- A project-metrics CSV (one row per project with fan_in, fan_out, instability, coupling_score, cluster_name) would be valuable for importing into spreadsheets or dashboards.

---

## Cross-Cutting Issues

### 1. Schema inconsistency between modes

The three legacy modes and impact mode use completely different JSON schemas:

| Aspect | Legacy Modes | Impact Mode |
|--------|-------------|-------------|
| Field naming | PascalCase | snake_case |
| Structure | Flat rows | Nested hierarchy |
| Lists | CSV strings | JSON arrays |
| Dicts | Stringified JSON | Native objects |
| Empty values | `""` | `null` or omitted |

This means any tool consuming Scatter's JSON output has to implement two separate parsers. Ideally, the legacy mode output would migrate toward the impact mode's conventions, which follow JSON best practices.

### 2. No metadata in any output

None of the three formats include:
- **Timestamp** — when was this analysis run?
- **Tool version** — which version of Scatter produced this?
- **CLI arguments** — what command produced this output? (critical for reproducibility)
- **Analysis duration** — how long did it take?
- **Search scope** — what directory was scanned?

This metadata is essential for auditing, comparing reports over time, and debugging unexpected results.

### 3. No "zero results" explanation

When an analysis finds zero consumers, all three formats give minimal feedback:
- Console: `"No Consuming Relationships Found"`
- JSON: `{"pipeline_summary": [], "all_results": []}`
- CSV: header row only

None explain *why* zero results were found. Was the search scope wrong? Was the project name misspelled? Did namespace filtering exclude everything? A suggestion like `"No consumers found. Verify the search scope includes the consuming projects."` would save debugging time.

### 4. "done." appears after every analysis

The string `"done."` is printed at the end of every run. This reads as debugging output rather than a professional tool's completion signal. It should be removed or replaced with a summary line like `"Analysis complete. 4 consumers found across 1 target."` that adds information.

---

## Priority Recommendations

Ranked by impact on developer experience:

| Priority | Change | Effort | Impact |
|----------|--------|--------|--------|
| 1 | Fix `ConsumerFileSummaries` — make it a native JSON object, not a stringified one | Low | High — this is a bug-level issue for JSON consumers |
| 2 | Fix `ConsumingSolutions` — make it a proper JSON array | Low | High — same issue |
| 3 | Add metadata block (timestamp, CLI args, version) to JSON output | Low | High — essential for reproducibility and comparison |
| 4 | Use `null` instead of `""` for absent fields in JSON | Low | Medium — cleaner consumption |
| 5 | Replace "done." with an informative completion summary | Low | Medium — polished feel |
| 6 | Drop or rephrase "Type/Level: N/A (Project Reference)" in console | Low | Medium — less confusing for new users |
| 7 | Add per-target consumer count to console output | Low | Medium — quicker scanning |
| 8 | Omit `ConsumerFileSummaries` column from CSV output | Low | Medium — cleaner spreadsheets |
| 9 | Add explicit error for `--graph --output-format csv` | Low | Low — prevents silent fallback |
| 10 | Add cluster member names to graph console output | Medium | Medium — actionable without switching to JSON |
| 11 | Unify legacy and impact JSON schemas (snake_case, nested) | High | High — breaking change, needs migration plan |
| 12 | Add a project-metrics CSV export for graph mode | Medium | Medium — dashboard integration |
| 13 | Add `--compact` / `--detail` flags for controlling output verbosity | Medium | Medium — different audiences need different detail levels |

---

## Principal Engineer's Addendum: What These Reports Should Become

The evaluation above is a good QA pass on what's broken. This section asks a different question: **if we could rebuild Scatter's reporting layer from scratch, what would make it genuinely powerful?**

The core insight is that Scatter's reports currently describe *what exists* but never tell you *what to do about it* or *what changed since last time*. They're snapshots without context. The fixes above make the snapshots cleaner — the ideas below make them useful for decision-making.

---

### A. The filter pipeline is invisible

When Scatter finds 4 consumers, the user has no idea how many candidates were eliminated along the way. The analysis runs a multi-stage filter:

```
200 .csproj files discovered
  → 12 have a <ProjectReference> to the target
    → 8 match the namespace filter
      → 4 match the class/method filter
```

**This funnel is never shown to the user.** If someone gets 0 results and doesn't know why, they can't tell whether the search scope was wrong, the namespace detection failed, or the class filter was too narrow.

**Suggestion:** Add a filter summary to every report format:

Console:
```
Search scope: /path/to/repo (scanned 200 projects, 1,847 source files)
Filter pipeline: 200 projects → 12 with project reference → 8 with namespace match → 4 with class match
```

JSON: Include as a top-level `filter_pipeline` array with stage names and counts.

This is cheap to implement (the data already flows through these stages) and dramatically improves debuggability. It also gives confidence that the tool is working correctly — "I can see it scanned everything and narrowed correctly."

---

### B. The blast radius needs a visual propagation path

The tool is named "Scatter" and the README talks about "blast radius" — but the reports show a flat list of consumers, not the propagation shape. For impact analysis with transitive tracing, the most important thing a reader needs to see is the dependency chain:

```
GalaxyWorks.Data  (target — you're changing this)
├── GalaxyWorks.WebPortal       [HIGH]  depth 0, direct consumer
│   └── GalaxyWorks.BatchProcessor  [MEDIUM]  depth 1, via WebPortal
├── MyGalaxyConsumerApp         [MEDIUM] depth 0, direct consumer
└── MyGalaxyConsumerApp2        [LOW]    depth 0, direct consumer
```

This tells a fundamentally different story than a flat list. You can see the propagation path, identify the critical chain (Data → WebPortal → BatchProcessor), and understand that BatchProcessor is at risk because of WebPortal, not because of a direct dependency.

**Suggestion:** Add a tree view as the default console output for impact analysis. The flat list with depth numbers forces the reader to mentally reconstruct the tree. The report should do that work for them.

For JSON: add a `propagation_tree` field that nests consumers under the consumer that exposed them, preserving the BFS traversal structure. The flat `consumers[]` array can stay for backward compatibility.

---

### C. Diff reports: comparing two analyses over time

The single most valuable feature Scatter's reporting could add is **differential analysis**. Right now, every run produces an isolated snapshot. But the real questions teams ask are:

- "We ran this last month — what changed?"
- "Did that refactoring effort actually reduce coupling?"
- "Are there new circular dependencies since the last release?"

**Suggestion:** Add `--compare-to <previous_report.json>` that produces a diff report:

```
=== Scatter Diff Report ===
Comparing: 2026-02-01 → 2026-03-08

Projects:  108 → 112 (+4 new)
Edges:     117 → 125 (+8 new, -0 removed)
Cycles:    0 → 1 (NEW CYCLE: ProjectA → ProjectB → ProjectA)

Coupling changes (top movers):
  GalaxyWorks.Data:   coupling_score 9.5 → 12.3 (+29%)  ⚠ significant increase
  NewProject.Api:     — → 4.2 (new)

Cluster changes:
  cluster_1:  feasibility easy → moderate (cross_boundary_penalty increased 0.0 → 0.3)

New consumers of GalaxyWorks.Data:
  + NewProject.Api (direct, project_reference)
  + NewProject.Worker (transitive via NewProject.Api)
```

This transforms Scatter from a "run it once" tool into a continuous monitoring tool. The JSON schema already contains everything needed for comparison — it just needs a diff engine and a diff reporter.

For graph mode specifically, the diff between two `graph_report.json` files could be computed without re-running the analysis, making it fast enough for CI gates.

---

### D. Reports should include actionable next steps

The graph console report tells you `GalaxyWorks.Data` has coupling_score 9.5 and instability 0.0. So what? What should an architect *do* with that information?

**Current report says:** "Here are the numbers."
**A useful report says:** "Here's what these numbers mean and what you should consider doing."

**Suggestion:** Add an interpretation section to the graph console report:

```
Observations:
  • GalaxyWorks.Data has the highest coupling score (9.5) with 4 direct consumers
    and zero outgoing dependencies (instability = 0.00). This is a stable core
    library — changes here propagate widely. Consider interface extraction to
    reduce direct coupling.

  • cluster_0 contains 100 projects but has very low cohesion (0.010). This
    suggests these projects are loosely related and may belong to multiple
    domain boundaries. Consider reviewing whether this cluster should be
    split.

  • No circular dependencies detected. Build ordering is clean.
```

This doesn't require AI — it's deterministic pattern matching on the metrics. High fan-in + low instability = "stable core, change carefully." High coupling_score + low cohesion = "consider splitting." Cycles present = "these must be broken before extraction." The rules are well-established in software architecture literature (Robert Martin's stability metrics, etc.).

For impact mode, the AI-generated impact narrative already does this partially. The suggestion is to extend the same principle to graph mode using rule-based heuristics, which don't require an API key.

---

### E. Markdown output format

Console output can't be pasted into a pull request description, a Confluence page, or a Slack message without losing its formatting. JSON is for machines. CSV is for spreadsheets. None of these serve the most common sharing workflow: **"paste this into a ticket/PR/wiki."**

**Suggestion:** Add `--output-format markdown` that produces a report designed for pasting:

```markdown
## Impact Analysis: Modify PortalDataService

**Overall Risk:** High | **Complexity:** Medium (3-5 developer-days)

### GalaxyWorks.Data
| Consumer | Risk | Depth | Pipeline |
|----------|------|-------|----------|
| GalaxyWorks.WebPortal | High | direct | portal-pipeline |
| GalaxyWorks.BatchProcessor | Medium | transitive (via WebPortal) | batch-pipeline |
| MyGalaxyConsumerApp | Medium | direct | consumer-pipeline |
| MyGalaxyConsumerApp2 | Low | direct | — |

**Impact Summary:** This change affects a core data access service used by 4 direct consumers...
```

Markdown is the universal interchange format for technical communication. GitHub renders it, ADO renders it, Confluence renders it, Slack renders it (partially). This single addition would make Scatter's output immediately shareable without manual reformatting.

For graph mode, Markdown tables for metrics and Mermaid diagrams for dependency visualization (GitHub and ADO both render Mermaid natively).

---

### F. Exit codes for CI/CD integration

Scatter always exits 0 unless it crashes. This means you can't use it as a CI gate. A pipeline that runs `scatter --graph` and finds a new circular dependency still exits successfully.

**Suggestion:** Add `--fail-on` flags:

```bash
# Fail (exit 1) if any circular dependencies are found
python scatter.py --graph --search-scope . --fail-on cycles

# Fail if overall risk is High or Critical
python scatter.py --sow "..." --search-scope . --google-api-key $KEY \
  --fail-on risk:high

# Fail if any project's coupling score exceeds a threshold
python scatter.py --graph --search-scope . --fail-on coupling:15.0

# Fail if consumer count exceeds threshold (blast radius guard)
python scatter.py --target-project ./Core.csproj --search-scope . \
  --fail-on consumers:20
```

This turns Scatter into a CI-enforceable architecture governance tool. Teams can set thresholds and prevent merges that violate architectural constraints — without the report being the end of the story.

The exit code should be non-zero (e.g., exit 1) when the condition is violated. The console/JSON/CSV report should still be produced normally so the developer can see what triggered the failure.

---

### G. Streaming progress for large codebases

On a codebase with thousands of projects, the user stares at a blank terminal for 30+ seconds while the graph builds. There's no indication of progress, no sense of how much work remains.

**Suggestion:** Add a progress indicator to stderr (so stdout remains clean for piping):

```
Scanning projects... 1,247 .csproj files found
Parsing project files... [=========>          ] 45% (562/1247)
Scanning source files... 18,432 .cs files found
Building edges... [==================>] 92% (11,247/12,180)
Computing metrics...
Done in 47.3s
```

This is a stderr concern, not a report format concern — but it dramatically improves the experience of waiting for a report. The `logging.info` calls already exist at each stage; this is about surfacing them as a progress bar rather than DEBUG log lines.

---

### H. Report as a first-class data object

The three reporter modules (`console_reporter.py`, `json_reporter.py`, `csv_reporter.py`) each receive raw data structures and format them independently. This means:
- The console reporter and JSON reporter can show different information from the same analysis
- Adding a new output format means writing a new formatter from scratch
- There's no single "report" object that captures what the analysis found

Impact mode already has this right: `ImpactReport` is a dataclass that captures all results, and each reporter just serializes it differently. Legacy modes don't — they pass around `List[Dict]` and each reporter picks fields from it.

**Suggestion:** Introduce a unified `AnalysisReport` dataclass that all five modes populate:

```python
@dataclass
class AnalysisReport:
    mode: str                          # "git", "target", "sproc", "impact", "graph"
    metadata: ReportMetadata           # timestamp, version, CLI args, duration
    filter_pipeline: List[FilterStage] # stage name + count at each stage
    targets: List[TargetResult]        # normalized target → consumers structure
    graph_summary: Optional[GraphSummary]  # for graph mode
    impact_summary: Optional[ImpactSummary]  # for impact mode
```

Every reporter receives this one object and formats it. Adding Markdown output becomes trivial — write one new formatter, no data plumbing required. The diff report feature also becomes straightforward: compare two `AnalysisReport` objects field by field.

This is the highest-effort suggestion but it's the architectural foundation that makes everything else easier. Without it, every new feature (diff reports, markdown output, CI gates) requires touching all three reporters independently.

---

### Summary: What to build and in what order (updated 2026-03-13)

Items marked ✅ are completed. Remaining items resequenced by adoption impact.

| Phase | What | Status | Why |
|-------|------|--------|-----|
| **Done** | Fix JSON serialization bugs (items 1-4) | ✅ Initiative 6 Phase 1 | Correctness issues |
| **Done** | Filter pipeline visibility (A) | ✅ Initiative 6 Phase 2 | Debuggability |
| **Done** | Blast radius tree view (B) | ✅ Initiative 6 Phase 3 | Core value proposition |
| **Done** | Markdown output (E) | ✅ Initiative 6 Phase 4 | Sharing format |
| **Done** | Rule-based observations in graph mode (D) | ✅ Initiative 5 Phase 6 | Actionable without AI |
| **Now** | Exit codes for CI (F) | Tier 2 priority | Unlocks governance — makes scatter infrastructure, not optional |
| **Next** | Diff reports (C) | Tier 3 priority | Needs real baseline history from actual users first |
| **Later** | Unified `AnalysisReport` dataclass (H) | Tier 4 — deferred | Internal refactor no user sees; do when a 5th format is needed |
| **Later** | Streaming progress (G) | Tier 4 — deferred | Graph cache means most runs <2s; nice DX but not urgent |

Note: Exit codes (F) were previously ranked below the unified report model (H).
Resequenced because CI/CD gates drive stickier adoption than internal refactoring.
The unified report model is correct architecturally but can wait until schema
inconsistency actually blocks a concrete feature.
