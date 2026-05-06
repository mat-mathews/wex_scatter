# Leiden in Scatter: Implementation Gap Analysis

**Date:** 2026-04-29 (updated 2026-05-02)
**Context:** Analysis of `docs/leiden_in_scatter_analysis_report.md` against current Scatter implementation. What exists, what's missing, what to build first.

---

## The Three-Lens Model

Scatter's graph analysis uses three complementary algorithms, each answering a different question:

| Algorithm | Question it answers | Status |
|---|---|---|
| **Tarjan SCC** | "What's mechanically tangled?" — hard dependency knots, cycles that block separation | Done |
| **Connected components + label propagation** | "What's in the same blob?" — rough structural grouping | Done |
| **Leiden** (proposed) | "What belongs together?" — density-based neighborhoods within large connected components | Not yet built |

These are additive, not competing. Tarjan finds knots. Label propagation finds blobs. Leiden finds the neighborhoods *inside* those blobs — where the domain seams are in a tightly-coupled monolith that's one giant connected component.

The practical scenario: the OD monolith is probably one large connected component. Label propagation with a threshold of 20 nodes tries to subdivide it via neighbor-majority voting, but it's a simple algorithm that can miss density-based structure. Leiden optimizes a modularity function to find the densest internal communities — specifically what you want for "where are the domain seams in this coupled system."

Leiden does not replace Tarjan (structural decomposition) or connected components (coarse grouping). It adds a higher-resolution lens between "everything connected" and "everything in a cycle."

---

## Current State

### What Scatter already has

| Capability | Status | Location |
|---|---|---|
| Project-level dependency graph | Done — 5 edge types, weighted | `core/graph.py`, `analyzers/graph_builder.py` |
| Tarjan SCC (cycle detection) | Done — iterative, project_reference edges | `analyzers/coupling_analyzer.py` |
| Clustering | Done — connected components + label propagation for large clusters | `analyzers/domain_analyzer.py` |
| Extraction feasibility scoring | Done — 4 weighted penalties (coupling, DB, cycles, API surface) | `analyzers/domain_analyzer.py` |
| Solution alignment | Done — dominant solution per cluster | `analyzers/domain_analyzer.py` |
| Health dashboard | Done — rule-based observations from metrics + clusters | `analyzers/health_analyzer.py` |
| Coupling metrics (fan-in/out, instability, coupling score) | Done | `analyzers/coupling_analyzer.py` |
| PR risk scoring | Done — 6 dimensions, GREEN/YELLOW/RED | `analyzers/pr_risk_analyzer.py` |
| SOW-driven impact analysis | Done — AI parses work request, traces blast radius | `analyzers/impact_analyzer.py` |
| Effort estimation | Done — graph-derived with confidence bands | `analyzers/effort_estimator.py` |

### Current clustering implementation details

- **Level 1:** Connected components via undirected BFS — O(N+E)
- **Level 2:** Label propagation for components > 20 nodes — deterministic, sorted iteration, alphabetic tie-breaking, capped at 100 iterations
- **Feasibility scoring:** 4 weighted penalties — cross-boundary coupling (40%), shared DB (25%), cycle participation (20%), API surface (15%)
- **No external dependencies:** Zero graph libraries (no igraph, NetworkX, leidenalg, python-louvain)
- **18 unit tests** covering correctness, edge cases, and determinism (5 identical runs)

### What label propagation gets right

- Deterministic (5-run reproducibility proven)
- Fast on project-level graphs (hundreds of nodes)
- Zero dependencies
- Well-tested

### Where label propagation is limited

- On large connected components, neighbor-majority voting can produce unstable or overly coarse groupings
- No modularity optimization — it doesn't explicitly maximize internal density vs external sparsity
- Tie-breaking is alphabetical, not structural
- On the OD monolith (likely one giant connected component), it may produce a single dominant cluster or clusters that split on naming artifacts rather than domain boundaries

Leiden addresses these limitations specifically. It's designed for finding well-connected communities in dense graphs where simpler algorithms struggle.

---

## Gap Analysis

### Small gaps (days of work, no new dependencies)

**Community-aware PR risk**
PR risk exists but doesn't know about clusters. The data is there — clusters and changed files just aren't connected yet. Wire them together: map changed files to projects to clusters, count boundary crossings, flag bridge nodes. The PR risk comment goes from "7 consumers affected" to "crosses 3 domain clusters, touches 2 bridge nodes."

**Boundary/bridge node detection**
The graph has all the edges. Finding nodes that connect multiple clusters is a straightforward computation on existing data — for each node, count how many clusters it connects, rank them. One new free function. Immediately useful in health dashboard and PR risk.

**Cluster metrics in effort estimator**
`effort_estimator.py` already accepts clusters and counts distinct clusters touched, but doesn't use cohesion, boundary pressure, or feasibility scores. A SOW landing in a cluster with 0.3 cohesion and 0.67 boundary pressure should get wider confidence bands than one in a clean 0.85/0.12 cluster.

### Medium gaps (weeks of work)

**Leiden as additional clustering lens**
Add Leiden as a higher-quality sub-clustering step for large connected components, alongside (not replacing) the existing label propagation. Requires `leidenalg` + `igraph` as optional dependencies (like the `ast` extra). Falls back to label propagation when not installed. The value is better community quality on dense monolith graphs where label propagation produces one giant blob.

**Namespace-level graph**
Namespace data exists in the graph (derived per project, used for namespace_usage edges) but edges aren't grouped at that level. Would need a projection step: collapse project-level nodes into namespace-level nodes, aggregate edges.

**Architecture drift over time**
Would need snapshot comparison. Graph cache exists with versioned metadata, but there's no "compare two cached graphs" path. Needs: snapshot storage strategy, community-matching across snapshots (communities shift IDs between runs), delta metrics.

### Large gaps (multi-week initiatives)

**Historical co-change graph**
Requires git log mining, time windowing, noise filtering. New data source entirely. Files that change together in the same commit/PR imply coupling that static analysis misses. Powerful signal but needs careful noise reduction (bulk reformats, merge commits, multi-concern PRs).

**Feature flag graph integration**
Scatter doesn't scan for feature flags today. Would need: pattern detection for flag checks in C# code, flag-to-community mapping, cross-community flag spread scoring. Useful for release risk but requires defining what a "feature flag check" looks like in the target codebase.

**Class/method-level graph**
Current graph is project-level. Going deeper needs significantly more parsing — Roslyn-grade analysis or heavy tree-sitter work. The existing type_scanner extracts declarations but doesn't build call graphs or track constructor injection. This is also a fundamentally different performance regime — tens of thousands of nodes, potentially millions of edges.

**Multi-layer graph**
The "everything graph" from the report — projects + classes + methods + DB + flags + pipelines + teams. Each layer is its own initiative. Aspirational target, not a near-term build.

---

## Recommended Build Order

### Phase 1: Community-aware PR risk + bridge nodes (days)

Wire existing clusters into PR risk scoring. Map changed files to projects to clusters. Count:
- How many clusters the PR touches
- Which nodes are bridge nodes (connect multiple clusters)
- Whether the change stays inside one cluster or crosses boundaries

Add community context to the PR risk comment: "This PR primarily affects the GalaxyWorks cluster but crosses into the MyDotNet cluster via GalaxyWorks.Common."

This proves the thesis — if clusters are meaningful in PR risk, they're trustworthy for everything else. Algorithm-agnostic: works with label propagation today, benefits from Leiden later.

### Phase 2: Cluster metrics in effort estimator (hours, on top of Phase 1)

Wire cohesion, boundary pressure, and bridge node counts into the existing `--scope-estimate` output. SOWs that cross domain boundaries get wider confidence bands. No new CLI surface — the existing effort table gets smarter numbers.

### Phase 3: Add Leiden as optional clustering lens (days)

Add `leidenalg` + `igraph` as an optional dependency extra (`uv sync --extra leiden`). When available, use Leiden for sub-clustering large connected components alongside the existing label propagation. When not installed, behavior is identical to today.

This is the right time to add Leiden — after Phase 1-2 prove that community data is useful in PR risk and effort estimation, and after running the existing clusters against the OD monolith to identify where label propagation falls short.

### Phase 4+: SOW scope mapping, architecture drift, co-change graph

These are the strategic features from the report (sections 12, 15, 18). Each is a real initiative. Sequence based on what the team needs most — SOW scoping if estimation is the pain point, drift detection if architecture erosion is the concern.

---

## Key Design Decisions to Make

1. **Leiden as addition, not replacement.** Leiden, Tarjan, and label propagation answer different questions. All three belong in the analysis pipeline. Leiden adds density-based community detection that the other two don't provide.

2. **Optional dependency.** Leiden requires `leidenalg` + `igraph` (C extensions). Add as an optional extra like `ast`. Falls back gracefully when not installed. No forced dependency burden on the base install.

3. **Cluster ID stability.** Before exposing community data in JSON schema, decide whether clusters are identified by stable content-derived names or ephemeral indices. Current `cluster_N` naming shifts between runs. Name-based identification (longest common prefix) is more stable but breaks down on diverse clusters. Needs resolution before downstream automation can depend on cluster identity.

4. **Confidence indicator for community-aware scoring.** If the largest cluster contains 60%+ of the codebase, community crossing is meaningless as a risk signal. Suppress community-aware scoring when clusters are too coarse, and fall back to the existing non-community risk path.

5. **Edge weighting for clustering vs coupling.** Currently the same weights serve both. The report argues different questions need different weight profiles. This is a Phase 3+ decision — don't over-engineer the weight system before proving communities are useful.

6. **Community naming.** Current approach: longest common prefix or `cluster_N`. AI-generated labels from top terms and file names is a natural extension of the existing AI enrichment pattern — deterministic detection, AI explanation. Phase 3+ feature.

7. **New CLI surface.** The report proposes 12 new commands. Most should be views inside `--graph` mode (`--graph --show-communities`, `--graph --show-bridge-nodes`), not top-level modes. Keep the CLI simple.

---

## Reference

- Vision document: `docs/leiden_in_scatter_analysis_report.md` (3,475 lines, 38 sections)
- Current clustering: `scatter/analyzers/domain_analyzer.py` (388 lines, 18 tests)
- Current cycle detection: `scatter/analyzers/coupling_analyzer.py` (428 lines)
- Current health dashboard: `scatter/analyzers/health_analyzer.py` (258 lines)
- Current PR risk: `scatter/analyzers/pr_risk_analyzer.py`
- Current effort estimation: `scatter/analyzers/effort_estimator.py`
