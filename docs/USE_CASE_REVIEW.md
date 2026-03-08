# Scatter Use Case Review & Capability Assessment

## Your Two Primary Use Cases

### Use Case 1: "Team has a SOW/CSE, wants to know blast radius before implementation"

**Status: Working, with caveats**

The `--sow` / `--sow-file` mode does this end-to-end:
- AI parses the SOW text into specific targets (projects, classes, sprocs)
- `find_consumers()` traces direct consumers
- BFS traces transitive consumers (depth 1, 2+)
- AI enriches with risk ratings, coupling narratives, complexity estimates
- Reports to console/JSON/CSV

**What works well:**
- Natural language input → structured impact report
- Transitive tracing catches indirect consumers (BatchProcessor via WebPortal)
- Risk ratings and effort estimates give PMs actionable sizing data
- Pipeline mapping (`--pipeline-csv`) links consumers to CI/CD pipelines

**What's broken or missing:**
- `--summarize-consumers` flag exists but **does nothing** — the AI summarization code exists in `gemini_provider.py` but is never called from `v1_bridge.py`. The `ConsumerFileSummaries` field is always `{}`.
- The dependency graph (`graph_builder.py`) is **not integrated** — impact analysis still uses the legacy `find_consumers()` which rescans the filesystem per target. With 5 targets in a SOW, that's 5 full filesystem scans instead of 1.
- Pipeline mapping requires a pre-generated CSV. There's no auto-detection from Azure DevOps pipeline YAML files (the `parse_pipeline_artifacts.py` tool generates the CSV but it's a separate manual step).

### Use Case 2: "Team implemented changes, wants to know which CI/CD pipelines to run on release night"

**Status: Partially supported, significant gaps**

The `--branch-name` mode does the closest thing:
- Diffs feature branch against main
- Extracts changed types from `.cs` files
- Finds consumers of those types
- Maps consumers to pipelines via `--pipeline-csv`

**What works well:**
- Actual git diff analysis (not theoretical — looks at what actually changed)
- `--enable-hybrid-git` uses AI to filter out types that weren't meaningfully changed (reduces false positives)
- Pipeline mapping connects consumers to deployment pipelines

**What's broken or missing:**
- **No "pipeline list" output mode** — the tool reports consumers with their pipelines as metadata, but doesn't produce a clean "here are the 7 pipelines you need to run tonight" summary. You have to read the full report and manually extract unique pipeline names.
- **No aggregate pipeline view** — JSON output has `pipeline_summary` (a list of unique pipeline names), but it's buried in the output structure. There's no `--output-format pipelines` that just gives you the deployment checklist.
- Same `--summarize-consumers` bug (always empty).
- Same dependency graph non-integration (rescans per target).

---

## Honest Capability Assessment

| Feature | README Says | Reality |
|---------|------------|---------|
| 4 analysis modes | All working | All working |
| Pipeline mapping | Working | Working (but manual CSV generation) |
| Batch job verification | Working | Working |
| AI consumer summarization | Working | **Broken** — flag exists, code exists, but never wired together |
| Dependency graph | Working | **Test-only** — not integrated into any analysis mode |
| AI impact analysis | Working | Working |
| Hybrid git analysis | Working | Working |

---

## Use Cases You Support Today

1. **Pre-implementation blast radius** (`--sow`) — "What will this CSE touch?"
2. **Post-implementation consumer tracing** (`--branch-name` / `--target-project`) — "What did we actually affect?"
3. **Stored procedure impact** (`--stored-procedure`) — "Who calls this sproc?"
4. **Pipeline identification** (`--pipeline-csv`) — "Which pipelines are involved?"
5. **Batch job correlation** (`--app-config-path`) — "Is this consumer a known batch job?"

## Use Cases You COULD Support (code exists, needs wiring)

6. **AI file summarization** — "What does each consumer actually *do* with this dependency?" The `summarize_csharp_file_with_gemini()` function works, it's just never called from the analysis pipeline. This is a ~20 line fix in `v1_bridge.py`.

7. **Graph-powered multi-target analysis** — Build the graph once, answer all queries from memory. Right now 5 targets in a SOW = 5 filesystem scans. With the graph integrated, it's 1 scan + 5 dict lookups. Also enables: "show me ALL projects that transitively depend on GalaxyWorks.Data with the full edge chain."

8. **Graph persistence/caching** — `to_dict()` / `from_dict()` already works. Could cache the graph to `.scatter/graph_cache.json` and skip reconstruction on subsequent runs (invalidate when `.csproj` or `.cs` files change).

## Use Cases You SHOULD Support (high value, not yet built)

9. **Deployment checklist mode** — A `--output-format deployment-checklist` or `--pipelines-only` flag that outputs JUST the unique pipelines that need to run, sorted by deployment order if possible. This is the #1 thing a release manager needs on release night — not a full impact report, just "run these 7 pipelines in this order."

10. **Pipeline auto-discovery from Azure DevOps YAML** — `parse_pipeline_artifacts.py` already parses pipeline YAML to extract artifact→app mappings. This should be integrated into the main CLI: `--pipeline-source ./pipelines/` that scans for YAML pipeline definitions and builds the mapping automatically, eliminating the manual CSV step.

11. **Diff-to-pipelines shortcut** — A single command: "I'm on this feature branch, tell me which pipelines need to run." Something like:
    ```bash
    scatter pipelines --branch feature/CSE-1234 --repo-path . --pipeline-csv mapping.csv
    ```
    Output: just the pipeline names, one per line, suitable for piping to a deployment script.

12. **SOW-to-pipelines shortcut** — Same but from a SOW document:
    ```bash
    scatter pipelines --sow-file CSE-1234.docx --search-scope /repo --pipeline-csv mapping.csv
    ```
    (Would need .docx parsing — or just require plain text/markdown input from the SOW.)

13. **Watch mode / CI integration** — Run scatter as a PR check that comments on the PR with: "This PR affects 4 projects across 3 pipelines. Transitive blast radius: 7 projects." Could be a GitHub Action or Azure DevOps task.

14. **Historical analysis** — "Over the last 20 PRs, which pipelines were most frequently affected?" This would use the graph + git log to identify coupling hotspots and frequently co-deployed pipelines.

15. **Dependency health dashboard** — Using the graph's connected components, cycle detection (Phase 2), and coupling metrics to produce a static report: "Your codebase has 3 dependency clusters. Cluster 1 has 45 projects with 12 cycles. The most coupled pair is X↔Y with 230 type_usage edges." This is the "tech debt radar" use case.

16. **Extraction planning** — "If we wanted to extract GalaxyWorks.Data into its own deployable service, what would break?" The graph can answer this: show all incoming edges, classify by edge type, estimate effort to decouple. This is high-value for teams planning microservice extraction from monoliths.

---

## Prioritization

If shipping this to teams tomorrow:

| Priority | Item | Effort | Value |
|----------|------|--------|-------|
| **P0** | Fix consumer summarization (wire the existing code) | ~1 hour | Broken feature in README |
| **P0** | Deployment checklist output mode | ~2 hours | Your #1 release-night use case |
| **P1** | Integrate graph into `--sow` mode | ~4 hours | 5x faster multi-target analysis |
| **P1** | Pipeline auto-discovery from YAML | ~3 hours | Eliminates manual CSV maintenance |
| **P1** | `scatter pipelines` shortcut command | ~2 hours | The thing teams will actually alias |
| **P2** | Graph caching to disk | ~2 hours | Repeat runs go from 30s → <1s |
| **P2** | CI/CD PR comment integration | ~4 hours | Shift-left pipeline awareness |
| **P3** | Historical coupling analysis | ~1 week | Tech debt visibility |
| **P3** | Extraction planning mode | ~1 week | Strategic architecture value |

The README should be honest about the summarization gap, and the "deployment checklist" use case should be front-and-center — that's the thing a release manager Slacks the team about at 4pm on release day.
