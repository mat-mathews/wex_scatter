# Future Research — Ideas Worth Exploring

These are techniques and features identified during competitive research that would
strengthen Scatter's graph engine, risk model, and analysis capabilities. None of
these are committed work — they're candidates for future initiatives, ordered by
how naturally they fit into what already exists.

---

## 1. PageRank for Architectural Centrality

**What it is:** Apply PageRank (damping factor 0.85) to the project dependency graph
to compute a "centrality" score for every node. Unlike fan-in, which only counts
direct dependents, PageRank captures *transitive* importance — a project with low
fan-in whose consumers themselves have high fan-in still ranks high.

**Why it matters for Scatter:** Fan-in and coupling score are good proxies for "how
important is this project?" but they miss indirect influence. A core utility library
might have fan-in of 3, but if those 3 consumers are the highest-coupled projects in
the graph, that utility is architecturally central in a way fan-in alone doesn't show.

**Where it fits:**
- `coupling_analyzer.py` — new `pagerank` field on `ProjectMetrics`
- Risk Engine — feeds into the structural coupling dimension as a complementary signal
- Graph reporter — surface top-N "architecturally central" projects in the health dashboard
- SOW scoping — changes to high-PageRank projects deserve wider confidence bands

**Implementation sketch:**
```python
def compute_pagerank(
    graph: DependencyGraph,
    damping: float = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    """Standard PageRank with dangling-node correction.

    Uses project_reference edges only (hardest coupling).
    Returns normalized scores summing to 1.0.
    """
    nodes = list(graph.nodes.keys())
    n = len(nodes)
    scores = {name: 1.0 / n for name in nodes}

    for _ in range(max_iterations):
        new_scores = {}
        dangling_sum = sum(
            scores[name] for name in nodes
            if not graph.get_outgoing(name)
        )
        for name in nodes:
            rank = (1 - damping) / n
            rank += damping * dangling_sum / n
            for source in graph.get_incoming_names(name):
                out_degree = len(graph.get_outgoing(source))
                if out_degree > 0:
                    rank += damping * scores[source] / out_degree
            new_scores[name] = rank

        # Check convergence
        delta = sum(abs(new_scores[n] - scores[n]) for n in nodes)
        scores = new_scores
        if delta < tolerance:
            break

    return scores
```

**Effort estimate:** Small. The algorithm is O(I × E) where I ≤ 100 iterations. The
graph already has the adjacency structures needed. This is a weekend addition, not an
initiative.

**Risk:** Low. Additive metric — doesn't change existing behavior, just adds a new
field to `ProjectMetrics`.

---

## 2. Cyclomatic Complexity Per Type Declaration

**What it is:** Compute cyclomatic complexity (number of independent execution paths)
for classes and methods in changed files. This is a per-symbol metric, not a
per-project metric — it measures how tangled the *implementation* is, not the
*dependency structure*.

**Why it matters for Scatter:** The Risk Engine's change surface dimension currently
looks at *what kind* of change (delete vs modify, interface vs class). It doesn't
know whether the changed code is a 10-line data class or a 500-line state machine
with 40 branches. A highly-coupled project containing simple code is less risky than
a highly-coupled project containing complex code. Complexity is the missing
multiplier.

**Where it fits:**
- Risk Engine — optional input to the change surface dimension
- PR Risk Scoring — flag "this PR modifies a high-complexity function in a
  high-coupling project" as a specific risk factor
- Not a standalone feature — only valuable when combined with graph-derived risk

**Implementation considerations:**
- Scatter uses regex and optional tree-sitter for type extraction. Cyclomatic
  complexity requires counting branch points (`if`, `else`, `switch`, `case`,
  `catch`, `&&`, `||`, `??`, ternary). Tree-sitter mode could do this accurately;
  regex mode would need a simpler heuristic (count branch keywords).
- Scope to *changed files only* — computing complexity for the entire codebase is
  out of scope and unnecessary. The PR risk analyzer already knows which files
  changed; complexity scoring should be lazy, not exhaustive.
- Cap the metric. Beyond ~50 cyclomatic complexity, the number doesn't matter — it's
  all "extremely complex." A bounded 0.0–1.0 score is more useful than a raw count.

**Effort estimate:** Medium. The tree-sitter path is straightforward (count branch
nodes in the AST). The regex fallback is less accurate but serviceable. The harder
part is deciding how complexity interacts with the existing risk dimensions — is it a
multiplier on change surface, or its own dimension?

**Risk:** Scope creep. Scatter is a graph tool, not a linter. This should stay
narrowly scoped to "complexity of changed code" and never expand to "complexity
dashboard for the whole codebase." NDepend already does that.

---

## 3. Architectural Layer Enforcement

**What it is:** Let teams declare dependency rules in `.scatter.yaml`:

```yaml
layers:
  - name: api
    pattern: "*.Api"
    allowed_dependencies: [service, core]
  - name: service
    pattern: "*.Service*"
    allowed_dependencies: [data, core]
  - name: data
    pattern: "*.Data*"
    allowed_dependencies: [core]
  - name: core
    pattern: "*.Core"
    allowed_dependencies: []

violations:
  severity: warning  # or "error" for CI gates
```

Then detect violations: "GalaxyWorks.Api depends on GalaxyWorks.Data directly,
bypassing the service layer."

**Why it matters for Scatter:** Domain clustering (label propagation) discovers
boundaries bottom-up from the graph structure. Layer enforcement is the top-down
complement — teams declare *intended* architecture and Scatter flags deviations.
Discovery tells you what the architecture *is*. Enforcement tells you where it
*drifted*.

**Where it fits:**
- Graph mode — new "layer violations" section in the health dashboard
- CI/CD exit codes (`--fail-on layers`) — fail the build if forbidden dependencies exist
- PR Risk Scoring — "this PR introduces a new layer violation" as a risk factor
- Pairs naturally with extraction feasibility: clusters that violate layer rules are
  harder to extract cleanly

**Implementation considerations:**
- Layer assignment via glob pattern matching against project names (already have this
  pattern in config)
- Violation detection is O(E) — one pass over edges checking if `edge.target`'s layer
  is in `edge.source`'s `allowed_dependencies`
- Need to handle projects that don't match any layer pattern (unclassified — warn but
  don't flag as violation)
- Layer definitions should be optional. Scatter works fine without them. This is an
  opt-in governance feature for teams that want it.

**Effort estimate:** Medium. The detection logic is simple. The config schema,
reporting integration, and CI gate behavior are the real work.

**Risk:** Adoption friction. If the layer config is too verbose or the violations too
noisy, teams will disable it. Start with "warning" severity and let teams opt into
"error" once they've cleaned up existing violations.

---

## 4. Token-Budgeted Context Assembly

**What it is:** When Scatter sends code context to an AI provider (for risk
narratives, coupling analysis, SOW parsing), assemble the context within a token
budget, prioritizing by relevance rather than sending everything and hoping it fits.

**Why it matters for Scatter:** The AI enrichment layer currently sends full file
contents or truncated snippets to the LLM. For large consumers with many files,
this either blows the context window or loses important code. A smarter approach:
rank code snippets by relevance to the analysis question, then pack them into the
available token budget highest-relevance-first.

**Where it fits:**
- `ai/providers/` — token counting utility (tiktoken or provider-specific)
- `ai/tasks/` — each task defines a relevance ranking for its input context
- Risk Engine AI enrichment — "given 8000 tokens of budget, which code from these
  14 consumers best explains the coupling?"

**Implementation considerations:**
- Relevance ranking per task: coupling narrative cares about import statements and
  method calls; risk assessment cares about interface signatures and shared types
- Token counting needs to be fast and approximate — exact counts per-provider are
  expensive. A character-based heuristic (chars / 4 ≈ tokens) is good enough for
  budgeting.
- Diminishing returns: the first 2000 tokens of context add more value than the
  next 2000. Consider a "context summary" for overflow rather than hard truncation.

**Effort estimate:** Medium-large. The token counting is easy. The relevance ranking
per task is the design work — each AI task has different priorities for what code
matters most.

**Risk:** Over-engineering. The current approach (send what fits, truncate the rest)
works. This becomes important when AI enrichment is the primary output (SOW
scoping) rather than optional polish (graph mode). Defer until SOW scoping Phase 2.

---

## 5. Symbol-Level Importance Scoring

**What it is:** Extend PageRank or a similar centrality measure from the project
level down to the type/class level. Instead of "GalaxyWorks.Data is central,"
surface "PortalDataService is the most architecturally important type in the graph."

**Why it matters for Scatter:** The Risk Engine scores risk per target (class,
interface, sproc). Knowing that a target is architecturally central — not just
highly coupled but *transitively important* — makes the risk score more accurate.
A change to `PortalDataService` (PageRank 0.12) is fundamentally different from a
change to `PortalDataServiceTests` (PageRank 0.001), even if both live in
highly-coupled projects.

**Where it fits:**
- Risk Engine — structural coupling dimension, as a per-target signal
- PR Risk Scoring — "this PR modifies the #2 most architecturally central type"
- Would require building a type-level graph (types as nodes, usage as edges) on top
  of the existing project-level graph

**Implementation considerations:**
- The project graph already tracks `type_declarations` per node and `type_usage`
  edges with evidence. A type-level subgraph could be derived from this data without
  re-scanning the codebase.
- Scale concern: a project graph might have 100 nodes. A type graph could have
  10,000+. PageRank is O(I × E) and should still be fast, but the graph construction
  and storage need to be lazy (build on demand, not cached by default).
- Start with project-level PageRank (Research Item 1) and validate the signal before
  investing in type-level granularity.

**Effort estimate:** Large. This is a new graph layer, not an addition to an existing
one. Defer until project-level PageRank has proven its value.

**Risk:** Premature granularity. Project-level centrality may be sufficient signal for
the Risk Engine. Type-level adds precision but also noise (internal helper classes
that are "central" within a project but meaningless architecturally). Needs careful
filtering.

---

## Priority Ordering

| # | Item | Effort | Value | When |
|---|------|--------|-------|------|
| 1 | PageRank | Small | High | Risk Engine Phase 1 — drop it in alongside existing metrics |
| 3 | Layer enforcement | Medium | High | After CI/CD exit codes — natural pairing with `--fail-on` |
| 2 | Cyclomatic complexity | Medium | Medium | Risk Engine Phase 2 — change surface enrichment |
| 4 | Token-budgeted context | Medium-large | Medium | SOW Scoping Phase 2 — when AI context quality matters |
| 5 | Symbol-level importance | Large | Medium | After PageRank proves value at project level |

Items 1 and 3 are the strongest candidates. PageRank is cheap and immediately useful.
Layer enforcement fills a real governance gap and pairs with existing CI/CD plans.
The rest are good ideas that need the right moment.
