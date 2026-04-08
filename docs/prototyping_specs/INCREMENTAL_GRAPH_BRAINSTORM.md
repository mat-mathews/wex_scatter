# Incremental Graph Updates — Team Brainstorm

**Date:** 2026-03-14
**Participants:** Diana Chen (Architect), Marcus Webb (Principal Engineer), Sam Torres (Senior Dev, graph/perf), Priya Kapoor (Senior Dev, CLI/DX), Jordan Liu (Dev, CI/CD/testing), Alex Novak (Dev, data structures/caching)

---

## Problem Statement

Today the graph cache is all-or-nothing — any `.cs` or `.csproj` change invalidates the entire cache and triggers a full rebuild. At 500 projects that's ~60 seconds. At enterprise scale (2,000+ projects), that's minutes. For the CI/CD gates planned in Tier 2, that's a pipeline blocker.

Git already tells us *exactly* which files changed. The graph builder already builds intermediate indexes (type_to_projects, namespace_to_project, etc.) that are keyed by file or project. We can surgically update only what changed.

---

## Three Strategies Considered

### Strategy 1: Per-File Facts Cache ("Patch the indexes")

Cache the intermediate indexes alongside the graph — per-file types declared, namespaces used, sproc references. On change detection, diff old facts against new facts and surgically update edges.

### Strategy 2: Git-Triggered Differential ("Replay the diff")

Hook into git events (post-merge, post-checkout, post-pull) and maintain a running graph via git hooks, file watchers, or lazy-on-next-run.

### Strategy 3: Layered Graph ("Base + Overlay")

Keep a full graph as a "base layer" built nightly or on major changes. Apply lightweight overlays for recent changes. Merge when overlay gets large.

---

## Research: What the Industry Does

### Build Systems (Bazel, Nx, Turborepo)
- **Bazel:** Content hashing with Merkle trees. SHA-256 of every input file. Action Cache maps action digests to outputs. Content-Addressable Store maps digests to file contents. Purely content-driven — no timestamps.
- **Nx "Affected" pattern:** `git diff --name-only base...head` → map files to projects via project graph → walk reverse dependencies → run tasks only on affected projects. No daemon required.
- **Turborepo:** Content-aware hashing ignoring file metadata. LRU cache pruning. Simpler than Bazel but environment fingerprinting can cause divergence.
- **Gradle:** Input/output fingerprinting. Compares file content hashes. Tasks must declare all inputs/outputs explicitly.

### Incremental Static Analysis (rust-analyzer, TypeScript, mypy)
- **Salsa/rust-analyzer "Red-Green" algorithm:** Tracks a query DAG with per-node revision stamps. On input change, walks dependencies to find affected queries. **Early cutoff:** if a derived value hasn't changed despite input changes, downstream is not invalidated. Critical for performance.
- **TypeScript `tsc --incremental`:** `.tsBuildInfo` stores dependency graph + file signatures. Compares signatures to determine minimal re-check set. Coarser than Salsa (file-level, not query-level).
- **mypy daemon:** Persistent process with in-memory module dependency graph. Re-analyzes changed module + dependents.

### Git-Based Change Detection
- **dotnet-affected:** .NET-specific tool that determines affected projects from git changes by parsing `.csproj`/`.sln` references. Directly relevant to scatter's domain.
- **General pattern:** git diff → file list → map to owning projects → walk project dependency graph (reverse deps) → affected project set.

### Content-Addressable Storage
- Git hashes are good for *change detection* (which files changed?). Content hashing is better for *cache keying* (can I reuse this output?). Best practice: combine both — git diff for fast affected-project detection, content hashing for actual cache validation.

### Incremental Graph Computation
- **Adjacency list with reverse index:** Both `project → deps` and `project → dependents`. Adding/removing an edge is O(1). Finding affected projects from a change is BFS on reverse index.
- **Key insight from academia (Fan & Hu, SIGMOD 2017):** If you can express the algorithm as iterative fixpoint computation, you can often derive an incremental version automatically. Cost proportional to affected area, not full graph.
- **Practical:** Edge deletion is fundamentally harder than addition for transitive closure.

### Trigger Models
- **File watchers:** FSEvents (macOS, excellent), inotify (Linux, needs tuning, ~1KB kernel memory per watch), kqueue (BSD, poor — FD limits). All require daemon processes.
- **Git hooks:** Don't survive clones, fragile in CI (shallow clones, detached HEAD).
- **Lazy-on-next-run:** Check git diff on next invocation, patch before analysis. Zero infrastructure, works everywhere.

---

## Team Debate

### Round 1: Trigger Model

**Marcus:** File watchers are a trap for a CLI tool. We'd need a daemon, and that's operational burden we don't want. Git hooks don't survive clones and are fragile in CI.

**Alex:** Lazy-on-next-run — check `git diff --name-only <cached_hash> HEAD` when scatter runs. Zero infrastructure. Works everywhere git works.

**Diana:** That's the Nx model. No daemon, no hooks, no watchers.

**Marcus:** Leave the door open for `scatter --update-graph` as an explicit CI entry point. Same logic, different trigger.

> **Decision: Lazy-on-next-run. Git diff as trigger. Optional `--update-graph` for CI.**

### Round 2: What to Cache

**Sam:** Per-file facts (types_declared, namespaces_used, sprocs_referenced) add ~4 MB at 500 projects. Acceptable.

**Sam:** Identifier sets (for type_usage matching) would be 50-200 MB. NOT worth caching. Re-tokenizing a changed file takes ~1ms.

**Marcus:** Cache parsed representation, not raw analysis. That's the Salsa model.

> **Decision: Cache per-file facts. Do NOT cache identifier sets — re-tokenize on demand.**

### Round 3: Edge Attribution

**Marcus:** To remove edges when files change, we need to know which files contributed. Current evidence lists are capped at 10 — insufficient for invalidation.

**Diana:** What about project-level attribution instead of file-level? When a file in project A changes, rebuild all outgoing edges from project A. Coarser but much simpler.

**Sam:** At ~30 files per project, rebuilding all outgoing edges takes 50-100ms. For a PR touching 5 projects, that's 500ms. Way better than 60s.

**Jordan:** What about declaration changes? If a file declares a new type, `type_to_projects` changes and we need to rebuild type_usage edges globally.

**Diana:** Compare old `types_declared` against new. If identical → usage-only → cheap. If different → declaration change → broader rebuild. That's Salsa's early cutoff.

**Sam:** 90%+ of file changes are usage-only. Declaration changes are rare.

> **Decision: Project-level edge attribution. Early cutoff on types_declared comparison.**

### Round 4: Rebuild Scope Decision Tree

```
git diff → changed files
  │
  ├── No changes → serve cached graph (instant)
  │
  ├── .cs files changed:
  │   ├── Map to affected projects
  │   ├── Re-extract facts, compare types_declared
  │   ├── If types unchanged (COMMON): rebuild outgoing edges only
  │   └── If types changed (RARE): update type_to_projects, broader rebuild
  │
  ├── .csproj changed:
  │   ├── Added/removed → FULL REBUILD
  │   └── Modified → rebuild project_reference edges, check namespace
  │
  └── >50 projects affected or >30% files → FULL REBUILD (safety valve)
```

### Round 5: Cache Format

**Alex proposed v2 format:**

```json
{
  "version": 2,
  "created_at": "...",
  "search_scope": "/path/to/repo",
  "git_head": "abc123...",
  "project_set_hash": "<hash of sorted .csproj paths>",
  "graph": { "nodes": {...}, "edges": [...] },
  "file_facts": {
    "src/Foo/Bar.cs": {
      "project": "Foo",
      "types_declared": ["BarService", "BarModel"],
      "namespaces_used": ["GalaxyWorks.Data", "System.Linq"],
      "sprocs_referenced": ["sp_InsertBar"],
      "content_hash": "sha256:abcdef..."
    }
  },
  "project_facts": {
    "Foo": {
      "namespace": "GalaxyWorks.Foo",
      "project_references": ["Bar", "Common"],
      "csproj_content_hash": "sha256:123456..."
    }
  }
}
```

- Content hashes for early cutoff (Bazel insight: if hash matches, skip re-extraction)
- `project_set_hash` detects structural changes (project add/remove)
- ~8 MB at 500 projects, acceptable
- v1 cache → full rebuild → save as v2 (no backward compat shim)

### Round 6: Patch Algorithm

```python
def patch_graph(cached_graph, cached_file_facts, cached_project_facts,
                changed_files, search_scope):
    # 1. Classify: .cs vs .csproj, added/modified/deleted
    # 2. Structural change (.csproj add/remove)? → full rebuild
    # 3. Map changed .cs to projects, handle deletions
    # 4. Re-extract facts, content hash early cutoff
    # 5. Handle .csproj modifications (refs, namespace)
    # 6. Remove + rebuild outgoing edges from affected projects
    # 7. If declarations changed → broader type_usage rebuild
    # 8. Recompute metrics + cycles (always cheap, <1s)
    # 9. Save updated cache
```

Requires adding `remove_edges_from()` to DependencyGraph (currently append-only).

### Round 7: Testing Strategy

**Marcus:** Property-based testing. Invariant: `full_rebuild(modified_codebase) == patch_graph(cached, changes)`.

Use existing `generate_synthetic_codebase.py` + new `mutate_codebase()`. Run 100 iterations with random mutations.

Explicit edge-case tests: file deleted, file added, type renamed, ProjectReference added, namespace changed, content hash unchanged, threshold exceeded, v1 cache migration.

### Round 8: Module Placement

New `scatter/store/graph_patcher.py` — clean separation from cache and builder. Imports from both. Minimal CLI changes via `build_graph_context()`.

---

## Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Trigger** | Lazy on next run (git diff) | Zero infrastructure, works everywhere |
| **Cache format** | v2: graph + file_facts + project_facts + content hashes | Enables surgical updates, ~8 MB at 500 projects |
| **Change detection** | git diff + content hash early cutoff | Git for file list, hash for false-positive filtering |
| **Edge attribution** | Project-level (not file-level) | Simpler, fast enough (50-100ms per project) |
| **Declaration changes** | Early cutoff: compare types_declared old vs new | 90%+ of changes are usage-only → cheap path |
| **Structural changes** | Full rebuild on .csproj add/remove | Rare, cascading invalidation too complex to patch |
| **Safety valve** | Full rebuild if >50 projects affected or >30% files | Prevents pathological incremental updates |
| **Graph mutation** | Add `remove_edges_from()` to DependencyGraph | Required for edge replacement during patch |
| **Module placement** | New `scatter/store/graph_patcher.py` | Clean separation from cache and builder |
| **Testing** | Property-based (synthetic mutations) + explicit edge cases | Correctness is paramount |
| **Migration** | v1 cache → full rebuild → save as v2 | No backward compat shim needed |

---

## Performance Projections

| Scenario | Today | With Incremental |
|----------|-------|-----------------|
| PR with 10 changed files, 500-project repo | 60s rebuild | <1s patch |
| `git pull` with 50 changed files | 60s rebuild | 2-3s patch |
| New project added (.csproj) | 60s rebuild | 60s rebuild (structural) |
| Nightly CI baseline | 60s rebuild | 60s rebuild (scheduled) |
| Metrics recomputation after patch | included | <1s (O(N+E)) |
| 2,000+ projects, PR with 10 files | 4-5 min rebuild | <2s patch |

## Strategic Value

- **Tier 2 CI/CD gates become viable:** Sub-second graph update means `--fail-on coupling:15.0` doesn't slow pipelines
- **Developer experience:** `scatter --target-project X --graph-metrics` responds instantly after a pull
- **Enterprise scale:** 2,000+ project repos go from "unusable" to "invisible overhead"
