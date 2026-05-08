# Method-Focused Analysis: Plan and Futures

## Why This Matters

Scatter answers "what breaks if I change this project?" Today, the finest resolution is: `--class-name PortalDataService --method-name StorePortalConfigurationAsync` — which narrows the consumer set to projects that contain the string `.StorePortalConfigurationAsync(`. That tells you *which projects* call the method. It doesn't tell you *how* they call it, *why* they depend on it, or *what specifically would break* if you changed the signature.

The difference matters when you're in a planning meeting and someone asks: "If we add a `tenantId` parameter to `StorePortalConfigurationAsync`, how bad is it?" Right now the answer is "7 projects reference it." The answer should be: "3 projects call it from controller actions that would need UI changes, 2 projects call it from batch jobs that would need config updates, and 2 test projects that just need parameter additions. Here's the testing strategy."

That's the gap. The data to close it is already flowing through the system — we just need to ask the AI the right question.

---

## Why not just ask an LLM?

Fair question. Tools like Augment and Cursor aren't just autocomplete anymore — they build their own code graphs, index entire repos, and can find callers of a method across a codebase. If you ask Augment "who calls `StorePortalConfigurationAsync`?" it'll search the repo, find references, and give you a reasonable answer. That's real and useful.

So what does scatter add?

**The database layer.** This is the big one. `PortalDataService` calls `dbo.sp_InsertPortalConfiguration`. `BatchProcessor` calls the same sproc through a completely different code path. An SSRS report references it via RDL. That's three coupling vectors — sproc, config DI, RDL — that don't show up as code references. They're strings in `.config` files, `CommandText` values in XML, `CommandType.StoredProcedure` paired with a string literal two lines away. The SOW signal analysis measured this: without sproc tracing, we catch 50–60% of blast radius. The missing 40% lives in the data layer. A code graph — no matter how good — doesn't trace it, because it's not code coupling. It's database coupling encoded in strings and config.

**.NET build system semantics.** Augment's graph is language-generic. Scatter understands `.csproj` project references, `Directory.Build.props` ancestor chains with `GetPathOfFileAbove` chaining, `.sln` solution membership, SDK-style vs Framework-style project files. A generic code graph sees XML files. Scatter sees MSBuild semantics — which project *actually* imports which shared build props, and what breaks if you change one. That's a different kind of knowledge.

**Architectural metrics, not just references.** Augment can tell you who calls a method. Scatter computes coupling scores, instability indices, cycle membership, domain clusters, and extraction feasibility for every project in the graph. A method call from a project with coupling score 6,670 is a different conversation than the same call from a project scoring 14.9. That distinction requires a structural model of the architecture, not just a list of references.

**CI integration.** Scatter runs in CI with exit codes and PR comments. `--fail-on coupling:15.0` blocks a merge. It maps consumers to CI/CD pipelines — "change this method → these 5 pipelines need testing." That's a different deployment model than a dev tool in an editor. You can enforce architecture governance with scatter; you can't with Augment.

**Deterministic, structured output.** Run scatter twice, get the same JSON. Diff two runs, see what changed. Feed the output to a dashboard. An LLM gives you prose — useful for understanding, not for automation.

All that said — LLMs are great at the thing scatter is bad at: reading code and explaining what it *means*. "This method is called inside a retry loop with no parameter validation" is an insight that requires reading and understanding the code, not scanning a graph. That's exactly how this plan uses them. Scatter narrows 7,895 files to the 7 that matter, attaches structural context (coupling, instability, cycles, pipeline mapping), and *then* asks the AI a precise question about those 7 files.

The argument isn't scatter *or* LLMs. It's scatter *then* LLMs — structural analysis finds the complete set and computes the metrics, AI interprets what it means and recommends what to do about it.

---

## What We Have Today

Scatter's consumer pipeline already narrows files by method name:

```
1,591 projects → 40 project refs → 25 test-excluded → 18 namespace → 18 class → 7 method
```

At the method filter stage, Scatter knows:
- Which `.cs` files contain `.MethodName(` calls
- Which projects own those files
- The full file content (cached from Step 4)
- Graph metrics for each consumer project (coupling, fan-in, instability)

What it doesn't capture:
- **Which method in the consumer calls the target method** (the caller context)
- **How the method is called** (direct invocation, through an interface, in a constructor, in a loop)
- **What the caller does with the return value** (stored, passed, ignored)
- **How hard the consumer update would be** (signature change vs behavior change vs breaking change)

The AI already reads these files via `--summarize-consumers`, but the prompt says "summarize this file's purpose" — it doesn't say "tell me specifically how this file uses `StorePortalConfigurationAsync`."

---

## The Plan: AI-Assisted Method-Level Analysis

### Approach

When `--method-name` and `--ai-summary` are both present, enhance the analysis in two ways:

1. **Method-focused file summarization** — change the per-file prompt from "what does this file do?" to "how does this file use this specific method?"
2. **Method-aware report summary** — change the report prompt from "summarize the consumer set" to "analyze how each consumer uses this method and what would break if it changed"

No Roslyn. No new graph. No method-level nodes. Just better questions to the same AI, with the same files it already reads.

### Phase 1: Method-Focused File Summarization

**File:** `scatter/analysis.py` — `_summarize_consumer_files()`

Currently, when `--summarize-consumers` is passed, each consumer's relevant `.cs` files are sent to the AI with a generic prompt. The method name is available in `ModeContext` but never used in the prompt.

**Change:** When `ctx.method_name` is set, use a method-focused prompt instead of the generic one:

```
Analyze the following C# code from '{filename}'.

The target method being analyzed is: {class_name}.{method_name}

For this file, answer:
1. How is {method_name} called? (direct invocation, through interface, via dependency injection, in a loop, etc.)
2. Which method(s) in this file call {method_name}? (list the caller method names)
3. What does the caller do with the return value or side effects?
4. If {method_name}'s signature changed (e.g., new required parameter), what would need to change in this file?
5. Risk level for this caller: Low (test code, easily updated), Medium (business logic, needs review), High (critical path, needs careful coordination)

Return a JSON object with:
- "caller_methods": list of method names that call {method_name}
- "call_pattern": how it's called (e.g., "direct invocation in controller action", "called in batch loop")
- "change_impact": what breaks if the signature changes
- "risk": "Low" | "Medium" | "High" (AI-assessed — distinct from graph-derived risk)
- "summary": 2-3 sentence explanation

Note: this file is a {file_type} file.
```

The `{file_type}` is pre-labeled before sending: files matching `*Test*`, `*Mock*`, `*Fixture*`, `*Fake*` patterns are labeled as "test code" so the AI calibrates risk appropriately (a test helper calling the method is Low risk, not High).

**Result storage:** The existing `consumer_file_summaries: Dict[str, str]` field would store the structured summary. Alternatively, add a new field `method_analysis: Optional[Dict]` to `ConsumerResult` for the structured data.

**Risk label distinction:** The per-file risk is "AI-assessed risk" — a subjective LLM judgment based on code context. This is separate from the deterministic graph-derived risk (coupling score, instability index) that the risk engine computes. Both are valuable; don't conflate them.

**Effort:** S — prompt change + conditional in `_summarize_consumer_files()`. The file reading, AI call, and result injection paths are already built.

### Phase 2: Method-Aware Report Summary

**File:** `scatter/ai/tasks/report_summary.py`

When `--method-name` is present, the report prompt should shift from project-level coupling analysis to method-level usage analysis.

**Change:** Detect when `triggering_type` contains a method name (format: `ClassName.MethodName`). When it does, build a method-aware prompt:

```
You are analyzing the impact of changing a specific method in a .NET codebase.

METHOD: {class_name}.{method_name}
PROJECT: {target_project}
CONSUMERS: {count} projects call this method

[per-consumer data: project name, coupling score, caller methods, call patterns, risk levels — from Phase 1]

Write a structured markdown report:

## Method Impact Summary
What is this method, how widely is it used, and what's the blast radius of changing it?

## Consumer Breakdown
For each consumer, explain: who calls it, how, and what breaks.
Group by risk level (High/Medium/Low).

## Change Strategy
If the signature changes (e.g., new parameter):
- Which consumers need code changes?
- Which just need recompilation?
- What's the recommended testing order?
- What's the deployment sequence?

## Effort Estimate
Rough categorization: how many consumers are trivial updates vs. significant rework?
```

**Effort:** M — new prompt path in `_build_prompt`, conditional on method presence in stats. Requires Phase 1 data (caller methods, call patterns) to be available in the stats dict.

### Phase 3: Structured Method Evidence

**File:** `scatter/analyzers/consumer_analyzer.py`

Currently the method filter returns a binary result (file matches or doesn't). Enhance it to extract context around each match.

**Change:** When `method_name` is provided and matches are found, extract a window of lines around each match (e.g., 5 lines before and after). Store this as evidence:

```python
@dataclass
class MethodCallEvidence:
    file_path: Path
    line_number: int
    caller_method: Optional[str]  # enclosing method name (via find_enclosing_type_name pattern)
    context_lines: str            # 5 lines before and after the call
```

This evidence feeds into the Phase 1 and Phase 2 prompts — the AI sees not just the full file but the specific call sites. More precise, fewer tokens wasted on irrelevant code.

**Effort:** M — extend the method filter stage to capture line numbers and context. The `find_enclosing_type_name` walk-backward pattern in `type_scanner.py` can be adapted to find the enclosing method instead of the enclosing type.

---

## Implementation Order

| Phase | What | Effort | Depends on |
|-------|------|--------|------------|
| 1 | Method-focused file summarization | S | Nothing — prompt change only |
| 2 | Method-aware report summary | M | Phase 1 (needs caller data) |
| 3 | Structured method evidence | M | Nothing (but enriches Phases 1-2) |

Phase 1 is shippable alone. It immediately makes `--method-name --summarize-consumers` produce method-specific insights instead of generic file summaries. Phase 2 makes `--method-name --ai-summary` produce a change-impact report. Phase 3 makes both more precise by extracting the exact call sites.

---

## What This Enables

With all three phases:

```bash
scatter --target-project ./src/Card/Business/Core/Core.csproj \
    --search-scope . \
    --class-name PortalDataService \
    --method-name StorePortalConfigurationAsync \
    --ai-summary --summarize-consumers
```

Output includes:
1. **Consumer table** — 7 projects that call this method, with coupling scores
2. **Per-consumer method analysis** — how each consumer calls it, caller method names, call patterns, risk level
3. **Method impact report** — executive summary, consumer breakdown by risk, change strategy with deployment sequence, effort estimate

That's the answer to "how bad is it if we add a `tenantId` parameter?" in one command.

---

## Futures

### Near-Term Enhancements (builds on this plan)

**Interface-aware method tracing.** When `StorePortalConfigurationAsync` is defined on an interface `IDataAccessor`, the method filter should also find consumers that call it through the interface. Currently it matches `.StorePortalConfigurationAsync(` — which catches both direct and interface calls. But the AI summary should know the difference: "this consumer calls through the interface, so it's decoupled and only needs a recompile" vs "this consumer calls the concrete class directly."

**Method rename impact.** A common refactoring: rename `StorePortalConfigurationAsync` to `SavePortalConfigAsync`. Scatter could show: "7 consumers call the old name. Here's the find-and-replace scope." The method filter already identifies the files — the AI could generate the migration checklist.

**Cross-method analysis.** "I'm changing `StorePortalConfigurationAsync` AND `GetPortalConfiguration`. What's the combined blast radius?" Currently you'd run two commands. A `--method-name` flag that accepts multiple values (comma-separated) would deduplicate consumers and show the union.

**Method-level coupling score.** Instead of project-level coupling, compute how many distinct callers a method has across all consumers. A method with 50 call sites across 7 projects is a different risk profile than a method with 7 call sites (one per project). This is computable from the method evidence without a Roslyn graph.

### Medium-Term: Tree-Sitter Method Graph (thinking out loud — not committed)

**What it is.** A lightweight class/method-level dependency graph built with tree-sitter (local C# parser, no .NET SDK required). Tree-sitter can extract:
- Method declarations with signatures
- Method calls with receiver expressions
- Class inheritance and interface implementations
- Constructor parameter types (DI wiring)

**What it enables.** Fan-in/fan-out at the method level. "This method has fan-in of 23 — it's a stable core method. That method has fan-in of 1 — it's a leaf." Method-level instability indices. Call chain visualization: `Controller.Save → Service.Store → Repository.Insert → sproc`.

**Scale.** A 1,591-project codebase with ~8,000 .cs files will have 150,000-300,000 methods (enterprise code averages 100-200 methods per project). The graph is 100-200x larger than the project graph. Tree-sitter parsing is fast (~100ms per file), so building the method graph would take ~15 minutes cold. Incremental patching via git diff (same approach as the project graph patcher) would make subsequent runs fast. At this scale, JSON serialization starts to strain (~15 seconds for 200K nodes, ~200MB file) — see the PostgreSQL section below for the migration path.

**Risk.** Tree-sitter's C# grammar handles most syntax but struggles with some edge cases (advanced generics, pattern matching expressions, global usings). Coverage is ~95% of real-world code. The 5% gap means some method calls would be missed — document the limitation and use regex as fallback.

### Long-Term: PostgreSQL Graph Backend (thinking out loud — not committed)

**Why consider it.** The current graph lives in a JSON file (`.scatter/graph_cache.json`). For the project-level graph (1,591 nodes, ~20K edges), this is fine — loads in <1 second, patches in milliseconds. But a method-level graph with 150K-300K nodes and 500K+ edges would produce a ~200MB JSON file with ~15 second serialization. And a multi-repo federated graph (post-monolith, multiple services with cross-repo edges) would be too large for a single JSON file.

**What PostgreSQL enables:**

| Capability | JSON file | PostgreSQL |
|---|---|---|
| Single-repo project graph | Fast (<1s load) | Overkill |
| Single-repo method graph (50K nodes) | Slow (5-10s load, large file) | Fast (indexed queries) |
| Multi-repo federated graph | Not feasible (no merge strategy) | Natural (one DB, many repos) |
| Historical graph snapshots | Manual file copies | Timestamped rows, diff queries |
| Concurrent access (CI + dev) | File locking issues | Connection pooling |
| Graph queries (shortest path, reachability) | Python BFS in-memory | `WITH RECURSIVE` or pgRouting |
| Coupling trend over time | Rebuild from git history | Store snapshots, query trends |

**Schema sketch:**

```sql
-- Nodes
CREATE TABLE project_nodes (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    name TEXT NOT NULL,
    namespace TEXT,
    path TEXT,
    project_style TEXT,
    snapshot_id INT REFERENCES snapshots(id),
    UNIQUE(repo, name, snapshot_id)
);

-- Edges
CREATE TABLE dependency_edges (
    id SERIAL PRIMARY KEY,
    source_id INT REFERENCES project_nodes(id),
    target_id INT REFERENCES project_nodes(id),
    edge_type TEXT NOT NULL,  -- project_reference, namespace_usage, type_usage, sproc_shared, config_di, rdl_sproc
    weight FLOAT DEFAULT 1.0,
    evidence JSONB,
    snapshot_id INT REFERENCES snapshots(id)
);

-- Method-level nodes (future)
CREATE TABLE method_nodes (
    id SERIAL PRIMARY KEY,
    project_id INT REFERENCES project_nodes(id),
    class_name TEXT NOT NULL,
    method_name TEXT NOT NULL,
    signature TEXT,
    file_path TEXT,
    line_number INT,
    snapshot_id INT REFERENCES snapshots(id)
);

-- Method-level edges (future)
CREATE TABLE method_edges (
    id SERIAL PRIMARY KEY,
    caller_id INT REFERENCES method_nodes(id),
    callee_id INT REFERENCES method_nodes(id),
    call_type TEXT,  -- direct, interface, virtual, delegate
    file_path TEXT,
    line_number INT,
    snapshot_id INT REFERENCES snapshots(id)
);

-- Snapshots for time-series analysis
CREATE TABLE snapshots (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    git_head TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    node_count INT,
    edge_count INT
);

CREATE INDEX idx_edges_source ON dependency_edges(source_id);
CREATE INDEX idx_edges_target ON dependency_edges(target_id);
CREATE INDEX idx_edges_type ON dependency_edges(edge_type);
CREATE INDEX idx_method_edges_caller ON method_edges(caller_id);
CREATE INDEX idx_method_edges_callee ON method_edges(callee_id);
```

**Snapshot diffing strategy:** Comparing two 200K-row snapshots via full table scan is expensive. Two approaches: (a) a materialized `edge_changes` table that records adds/removes/weight-changes per snapshot transition, computed at snapshot creation time; or (b) a content-hash column on edges that enables hash-based diff without comparing every field. Option (a) is more storage but faster queries; option (b) is leaner but requires a diff pass. Decide based on query patterns when the time comes.

**What this unlocks:**

- **Coupling trend dashboards.** Weekly snapshots → graph "how is coupling evolving?" Plot coupling score for `Card.Business.Core` over 12 months. Did it get worse after the last feature push?

- **Cross-repo blast radius.** Service A calls Service B's API. Service B changes its contract. The federated graph shows the edge and the downstream consumers. Currently invisible because Scatter runs per-repo.

- **"What changed since last sprint?"** Diff two snapshots: new edges, removed edges, coupling score deltas. Automatic architecture drift detection.

- **Team-level views.** Tag nodes with owning team. Query: "show me all edges crossing team boundaries." That's the coordination cost of a change.

- **Graph queries in SQL.** "Find all paths from `PortalDataService` to `BatchProcessor` with length <= 3." That's a `WITH RECURSIVE` query, not an in-memory BFS.

**When to build it.** Not now. The JSON cache is sufficient for single-repo project-level analysis. Build the PostgreSQL backend when one of these measurable triggers fires:
1. Graph cache JSON exceeds 50MB or serialization exceeds 5 seconds
2. Multi-repo federated graph needed (post-monolith decomposition) — note: requires PackageReference support (gap #9) as a prerequisite for tracing cross-repo NuGet edges
3. Historical trend analysis requested (coupling over time)
4. Multiple CI runners need concurrent graph access (file lock contention)

The migration path is clean: implement the PostgreSQL backend as an alternative to `graph_cache.py`. The `DependencyGraph` in-memory structure stays the same — only the serialization layer changes. Everything above the cache (analyzers, reporters, AI tasks) is unaffected.

**Security note:** If the graph database stores project names, method names, and code structure metadata, it's an attack surface. The database should be on the internal network, not internet-accessible. Treat the graph as internal architecture documentation — same classification as source code.

### Speculative: Real-Time Graph in the IDE (thinking out loud — not committed)

**What if the dependency graph updated as you type?** A Language Server Protocol (LSP) extension that watches file saves, patches the graph incrementally (Scatter already does this via git diff), and shows coupling impact in the gutter. You rename a method → the IDE shows "12 callers across 4 projects" before you commit.

This requires:
- The method-level tree-sitter graph (medium-term)
- A persistent graph backend (PostgreSQL or SQLite for local)
- An LSP server that exposes Scatter queries
- IDE extension (VS Code, JetBrains)

Far out, but the foundation is being built now. Each phase of this plan makes it more feasible.

---

## Summary

| Horizon | What | Effort | Prerequisite |
|---------|------|--------|--------------|
| **Now** | AI-assisted method analysis (prompt changes) | S-M | Existing infrastructure |
| **Near** | Method evidence extraction, multi-method analysis | M | Phase 1 of this plan |
| **Medium** | Tree-sitter method graph (50K nodes) | L | Tree-sitter C# grammar |
| **Long** | PostgreSQL backend, multi-repo, trend analysis | L | Method graph justifies it |
| **Speculative** | Real-time IDE integration via LSP | XL | All of the above |

The AI-assisted path is the fastest way to deliver method-level insight. It builds on infrastructure that already exists, requires no new parsers, and ships in days. The deeper paths (tree-sitter graph, PostgreSQL, IDE integration) are where Scatter goes if the monolith decomposition succeeds and the tool becomes a platform.
