# Scatter vs. CDH PowerShell Dependency Analyzers — Comparative Analysis

Source-verified comparison of the `scatter` Python codebase against the CDH PR-gating
PowerShell scripts (`Analyze-DependencyImpact.ps1` / `Analyze-RealReferenceImpact.ps1`).

All claims below are grounded in:
- `scatter/analyzers/graph_builder.py`, `scatter/scanners/*.py`,
  `scatter/store/graph_cache.py`, `scatter/store/graph_patcher.py`,
  `scatter/analyzers/graph_enrichment.py`, `scatter/__main__.py`
- `c:\_\health-cdh-ondemand\.github\scripts\Analyze-DependencyImpact.ps1` (2,077 LOC)
- `c:\_\health-cdh-ondemand\.github\scripts\Analyze-RealReferenceImpact.ps1` (2,334 LOC)
- `walk_perf_5.txt` performance timeline

## 1. Contrast — at a glance

| Dimension | **Scatter** (Python) | **CDH scripts** (PowerShell) |
|---|---|---|
| **Purpose** | Offline indexer + query surface (impact/coupling/bridges/health/PR-risk) over any .NET monorepo | PR-gating: binary allow/block decision based on blast radius vs threshold |
| **Consumer** | Humans reading reports, optional GitHub Action | Azure DevOps / GitHub Actions PR status check |
| **LOC** | ~17k Python across `scatter/` (excluding tests) | 2,077 + 2,334 = **4,411** PS1 LOC (two scripts) |
| **Graph construction** | 6-step pipeline in `graph_builder.build_dependency_graph` | `Build-DependencyGraph` in `Analyze-DependencyImpact.ps1:439-624` |
| **Parallelism** | ThreadPoolExecutor on step 4 file read/parse; also used in impact analyzer for parallel AI enrichment | `ForEach-Object -Parallel -ThrottleLimit 8` on csproj parsing (PS7+) |
| **Cache** | `.scatter/graph_cache.json` v2, git-HEAD invalidation, per-file/project facts, **incremental patch** via `graph_patcher.patch_graph` | `.github/cache/dependency-graph.json` + meta, 24h TTL, invalidated on any csproj/props/targets change (whole-cache swap, no patch) |
| **Reverse graph** | Built on demand from `graph._outgoing` | Built inline (`$reverseGraph`) during `Build-DependencyGraph` |
| **Transitive propagation** | Query-layer BFS (consumer-analyzer / impact-analyzer) | `Get-AffectedProjects` BFS queue (`Analyze-DependencyImpact.ps1:625-1000`), Distance-tracked |

## 2. Edge types / reference detection — verified

| Reference type | Scatter | CDH |
|---|:---:|:---:|
| `<ProjectReference>` | ✅ `graph_builder.py:483-541` (`_build_project_reference_edges`) | ✅ `Get-ProjectReferences:317-438` |
| `<PackageReference>` (NuGet) | ❌ | ⚠️ parsed but not used for impact (stored for report context) |
| `<Import Project="…props/.targets">` (explicit) | ✅ `project_scanner._extract_explicit_imports()` — single-pass XML parse, filters SDK/system imports, resolves `$(MSBuildThisFileDirectory)` | ✅ `Get-ProjectReferences` `-IncludeImports` |
| **Implicit `Directory.Build.props/.targets`** | ✅ `msbuild_import_scanner.py` — nearest-ancestor walk + `GetPathOfFileAbove` parent chaining, integrated in `graph_builder.py` step 2b as `msbuild_import` edges | ✅ `Find-NearestFileInAncestors` walks up from each project dir, attaches nearest to `PropsTargetsMap` (lines ~548-620) |
| `namespace_usage` (derived: A uses namespace matching B's) | ✅ `graph_builder.py:302-331` (step 5b) | ❌ |
| `type_usage` (derived: A declares T, B references T) | ✅ `graph_builder.py:333-418` (step 5c) with per-file scope gate | ❌ (but `Analyze-Real*` does a narrower variant for config DI) |
| **Soft refs: config-based DI** (type FQTN in .config) | ✅ `config_di_scanner.py` — scans assembly-qualified type names in .config XML, creates `config_di` edges | ✅ `Find-ConfigFilesReferencingTypesWithNamespaces` |
| **Soft refs: SSRS .rdl → sproc** | ✅ `rdl_scanner.py` — extracts sproc names from `<CommandText>` in .rdl/.rdlc/.rds, creates `rdl_sproc` edges | ✅ `Find-RdlFilesReferencingStoredProcs` |
| **Soft refs: plugin XML** (`AppMonitoringTypes.xml`, `RegisteredTypes.xml`) | ❌ | ✅ `Find-PluginXmlFilesReferencingTypes` |
| Stored-proc refs in source | ✅ `db_scanner.py` with comment stripping, configurable prefixes, reuses content cache | ❌ (CDH only trips on sproc name when `.sql` file itself changes) |
| EF DbSet/DbContext | ✅ `db_scanner.py` | ❌ |
| Direct SQL literals (SELECT/INSERT/…) | ✅ `db_scanner.py` | ❌ |
| Connection strings | ✅ `db_scanner.py` | ❌ |
| `.rptproj` (SSRS projects) | ✅ `solution_scanner._SUPPORTED_PROJECT_GUIDS` includes SSRS GUID; `.rptproj` parsed as graph nodes with `project_style="ssrs"` | ✅ `.rdl` files attribute to nearest `.rptproj`, which is a gateable unit |
| `.vbproj` / `.fsproj` | ✅ GUIDs added to `_SUPPORTED_PROJECT_GUIDS`; parsed via existing `parse_csproj()` (same MSBuild schema) | ❌ |

## 3. Change-type classification — CDH has a gating taxonomy, scatter doesn't

`Get-AffectedProjects` classifies each changed file into a `ChangeType` (`Analyze-DependencyImpact.ps1:656-990`) with an explicit upgrade lattice:

```
ProjectFile / SharedBuildFile  (build-only, won't gate CD by default)
         ↓ (upgradeable)
SourceFile / ContentFile / ReportFile / ReportProjectFile  (gates CD)
```

With file-type routing:

- `.cs .cshtml .razor .resx .xaml .aspx .ascx .htm .html .ts .js .css .scss .tt` → `SourceFile`
- `.config .json .xml .sql .xslt .xsl .xsd .datasource .wsdl .svcinfo` → `ContentFile`
- `.pdf .gif .png .jpg .jpeg .bmp .svg .ico .cur .wav .ttf .woff .woff2 .eot` → `ContentFile` (with path-fallback when no .csproj found)
- `.rdl .rds .rdlc` → `ReportFile` (attributed to nearest `.rptproj`)
- `.rptproj` → `ReportProjectFile`
- `.props .targets` → `SharedBuildFile` (incl. implicit `Directory.Build.*` root-scope fallback)
- `.csproj` → `ProjectFile`

Scatter has no parallel to this. It emits a homogeneous edge graph; classification happens (if at all) in the analyzer layer, and the notion of "build-only change that shouldn't gate CD" doesn't exist.

## 4. Decision layer — the reason CDH is 4,400 LOC

Past graph + BFS, CDH spends ~70% of its code on decisions scatter has no analog for:

- **`pipeline-mappings.json`**: regex include/exclude patterns per pipeline, matched against affected project names/paths (`Test-ProjectMatchesPatterns`)
- **YAML artifact-name derivation**: `Get-PipelineYamlArtifactNames`, `Get-PipelineYamlDerivedPatterns`, `New-DerivedIncludePatternsForPipeline` (~400 LOC) — infers which pipeline builds which projects by reading pipeline YAML `artifactName` fields when explicit mappings are absent
- **Test-project exclusion**: `Is-TestProjectPath` — test projects don't count toward blast radius. _(Scatter now also has `consumer_analyzer.is_test_project()` with `exclude_test_projects` config flag.)_
- **Build-only origin suppression**: `Test-YamlEligibilityByOrigin` — walks back the `DependsOn` chain; won't gate CD if the root cause is only a `ProjectFile`/`SharedBuildFile` change
- **Pipeline grouping**: multiple pipelines grouped into "affected_pipeline_groups" for deduplication
- **Threshold enforcement**: `MaxAllowedPipelines = 5` default → blocks PR if exceeded

`Analyze-RealReferenceImpact.ps1` additionally does:
- GitHub API unified-diff fetch per file → method-name extraction from the patch hunks (line ~700)
- Roslyn-based member resolution (referenced as `roslynSucceeded` metric)
- A separate JSON report with `MemberReasons`, `DirectSeedProjects`, `ReferenceSeedProjects`

## 5. Strengths

### Scatter's strengths (things CDH can't do or does worse)

1. **Richer edge semantics in-graph**: `namespace_usage` and `type_usage` catch references that survive without a `<ProjectReference>` (common in legacy codebases where the csproj graph lies). CDH is 100% at the mercy of whether the `.csproj` is honest.
2. **Incremental graph patching**: v2 cache with per-file `FileFacts` + git-diff-driven `patch_graph` → warm re-runs are sub-second for small diffs. CDH's cache is all-or-nothing: any `.csproj`/`.props`/`.targets` change invalidates the entire cache and triggers a full rebuild.
3. **DB surface coverage**: Sproc/EF/SQL/connection-string detection in source gives a full cross-DB dependency view. CDH only sees DB edges when a `.sql` file changes and happens to share a name with an RDL reference.
4. **Performance at scale**: Synthetic benchmarks show 2.6s for 250 projects and 25.8s for 800 projects (cold graph build); incremental patching delivers 110-954x speedups for warm runs. CDH benchmarks in `Test-WorstCasePerformance.ps1` target 1,000-project repos with a ~30% parallel speedup; warm-cache hits save ~2m — but the cold path is also the common case in practice because almost any PR touches a `.csproj`.
5. **General-purpose query surface**: coupling, cycles, bridges, instability, PR-risk, consumer analysis — all derived from the same graph. CDH produces one artifact: a pipeline gating decision.
6. **Language-idiomatic extensibility**: Python + typed dataclasses + tree-sitter queries hooks (parsers dir) + clear scanner/analyzer/store separation. PowerShell hashtables with `PSObject.Properties` gymnastics, StrictMode workarounds, and 400-line regex-pattern functions are a maintainability tax — verified by the `try { … } catch {}` empty blocks scattered through `Get-AffectedProjects`.

### CDH's strengths (things scatter doesn't do)

1. ~~**MSBuild implicit imports**~~ — **CLOSED.** Scatter now has `msbuild_import_scanner.py` with nearest-ancestor walk + `GetPathOfFileAbove` parent chaining, plus explicit `<Import>` extraction in `project_scanner._extract_explicit_imports()`. Integrated in `graph_builder.py` step 2b. 21 tests cover ancestor resolution, chaining, standalone overrides, and system-import filtering.
2. ~~**Soft-reference detection**~~ — **PARTIALLY CLOSED.** Config DI scanning (`config_di_scanner.py`) and RDL→sproc scanning (`rdl_scanner.py`) are implemented with `config_di` and `rdl_sproc` edge types. Plugin XML (`Find-PluginXmlFilesReferencingTypes`) remains open — deferred until actual plugin XML files from the monolith are available for testing.
3. **File-type coverage** — CDH classifies 25+ file extensions into gating categories. Scatter ingests `.cs/.csproj/.sln/.props/.targets` but nothing beyond that. A PR that changes only `.cshtml`, `.razor`, `.json`, `.xml`, `.resx`, images, or `.rdl` produces zero nodes/edges in scatter.
4. ~~**`.rptproj` support**~~ — **CLOSED.** `solution_scanner._SUPPORTED_PROJECT_GUIDS` includes the SSRS GUID. `.rptproj` files are parsed as graph nodes. `.rdl` files within them are scanned for sproc references via `rdl_scanner.py`.
5. **Decision framework / CD gating taxonomy** — the `ChangeType` upgrade lattice + build-only suppression is a thoughtful design for avoiding CD-pipeline spam on metadata-only changes. Scatter has nothing equivalent.
6. **Pipeline mapping layer** — `pipeline-mappings.json` + YAML-derived artifact patterns → project → pipeline mapping. Scatter uses `pipeline_to_app_mapping.csv` for runtime mapping; a YAML-to-CSV converter exists (`tools/parse_pipeline_artifacts.py`) but YAML introspection is not integrated into the runtime.
7. **Method-level impact (Analyze-Real*)** — fetches the unified diff and extracts changed method names, then uses Roslyn to resolve references. Scatter has method-level *filtering* (`consumer_analyzer.find_consumers_with_method_filter()`) via regex pattern matching, but no Roslyn AST or git-hunk-level method extraction.
8. **Fail-safe error paths** — on any failure, `Analyze-RealReferenceImpact.ps1` writes a valid "error report" JSON and exits with a deterministic outcome so the PR check never hangs. Scatter's CLI surfaces exceptions up.
9. ~~**Test-project awareness**~~ — **CLOSED.** Scatter now has `consumer_analyzer.is_test_project()` with pattern matching and an `exclude_test_projects` config flag.


## 6. Gaps in scatter (ordered by severity)

| # | Gap | Severity | Fix effort | Notes |
|---|---|---|---|---|
| ~~1~~ | ~~No `Directory.Build.props/.targets` indexing~~ | ~~High~~ | ~~S~~ | **CLOSED.** `msbuild_import_scanner.py` — nearest-ancestor walk + `GetPathOfFileAbove` chaining. Integrated in `graph_builder.py` step 2b. 21 tests. |
| ~~2~~ | ~~No `<Import>` parsing in `parse_csproj`~~ | ~~High~~ | ~~S~~ | **CLOSED.** `project_scanner._extract_explicit_imports()` — single-pass XML, filters SDK imports, resolves `$(MSBuildThisFileDirectory)`. 6 tests. |
| ~~3~~ | ~~No soft-reference scanners (config/RDL/plugin XML)~~ | ~~High~~ | ~~M~~ | **PARTIALLY CLOSED.** `config_di_scanner.py` (config DI, 14 tests) and `rdl_scanner.py` (RDL→sproc, 13 tests). Plugin XML deferred — no monolith fixtures available. |
| ~~4~~ | ~~No `.rptproj` / `.vbproj` / `.fsproj`~~ | ~~Medium~~ | ~~S~~ | **CLOSED.** `_SUPPORTED_PROJECT_GUIDS` expanded with VB.NET, F#, SSRS GUIDs. `.vbproj`/`.fsproj` parsed via `parse_csproj()`. `.rptproj` as lightweight graph nodes. |
| 5 | No change-type classification / gating taxonomy | **Medium** | M | Add a `ChangeType` to consumer/impact analyzer outputs. |
| 6 | No pipeline-mapping decision layer | **Medium** | M | `scatter/reports` has pipeline mapping infrastructure; needs the include/exclude regex + threshold gate on top. |
| 7 | Step 2 csproj parse sequential | Low | S | Parallelize the same way step 4 is parallelized; ~15-20s saved. |
| 8 | No method-level impact | Low | L | **Partial.** `consumer_analyzer.find_consumers_with_method_filter()` provides regex-based method filtering. Still missing: Roslyn/tree-sitter method boundary detection + git-hunk-level changed-method extraction. |
| 9 | `<PackageReference>` not captured | Low | S | Scanner already parses it for fact capture; extend to emit `nuget_package` edges for NuGet version-drift analysis. |
| 10 | Unified walk isn't cached across runs | Low | S | Serialize `discovered_files` alongside `graph_cache.json`, keyed on git HEAD. Would reduce warm re-runs from 6m → ~1m. |

## 7. Gaps in CDH (where scatter leads)

| # | Gap | Severity | Notes |
|---|---|---|---|
| 1 | No incremental graph patching | High | Any `.csproj`/`.props`/`.targets` change = full rebuild. Most PRs touch at least one of these. |
| 2 | Dependencies only reach as far as the `.csproj` graph is honest | High | No `namespace_usage`/`type_usage` derivation. A project that imports `using Foo.Bar;` but doesn't `<ProjectReference>` it is invisible. |
| 3 | No sproc/EF/SQL scanning in .cs | Medium | DB dependencies are inferred only via RDL + filename match on changed `.sql`. Misses 90%+ of code→sproc couplings. |
| 4 | PowerShell maintainability / error handling | Medium | Pervasive `try {} catch {}` empties, StrictMode workarounds, 400-line regex functions. Type safety via PSObject + hashtables is fragile. |
| 5 | Regex-based type extraction with heuristic filters | Medium | `Get-TypeNamesWithNamespacesFromCSharpFile` filters to types ending in `Repository`/`Service`/etc. — loses anything else (e.g., DTOs, POCOs, handlers without the suffix). Scatter's type extractor is naming-agnostic. |
| 6 | No coupling/bridge/cycle metrics | Low-Medium | Only answers "what breaks?" — not "what's fragile?" |
| 7 | Two parallel scripts with duplicated graph-building logic | Low | `Analyze-Dependency*` and `Analyze-RealReference*` both build partial graphs. No shared core. |
| 8 | 24h TTL cache validity | Low | Wall-clock time-based invalidation isn't correctness-preserving. Scatter's git-HEAD + content-hash model is sounder. |

## 8. Crossover — what's already portable in both directions

### CDH → scatter (highest-ROI ports)

1. ~~**`Find-NearestFileInAncestors` → `msbuild_import_scanner`**~~ — **DONE.** `msbuild_import_scanner.py` (124 LOC) with ancestor walk, `GetPathOfFileAbove` chaining, and 21 tests. Integrated in `graph_builder.py` step 2b.
2. ~~**Explicit `<Import>` parsing in `project_scanner.parse_csproj`**~~ — **DONE.** `_extract_explicit_imports()` with SDK-import filtering, `$(MSBuildThisFileDirectory)` resolution, and 6 tests. Single XML parse pass (Devon's review point).
3. **ChangeType taxonomy**. Adding the file-extension → change-type classifier to `impact_analyzer` unlocks CDH-style CD gating without touching the graph. Medium, 1-2 days.
4. ~~**Test-project filter**~~ — **DONE.** `consumer_analyzer.is_test_project()` with pattern matching + `exclude_test_projects` config flag.
5. **Fail-safe JSON output**. The pattern of "write valid error report + exit deterministic" is a small CLI change with high operational value for CI usage.

### Scatter → CDH (if CDH ever gets rewritten)

1. **Per-file/project facts cache**. CDH's 24h-TTL approach is the weakest part of its caching. Scatter's `FileFacts` + git-diff patcher is proven to work and would reduce CDH's cold-path frequency dramatically.
2. **Namespace/type-derived edges**. Would catch the "forgotten `<ProjectReference>`" class of bugs that CDH silently misses today.
3. **Sproc/EF/SQL source scanning**. Ports cleanly — `db_scanner.py`'s comment-stripping state machine is the key piece.
4. **Separation of concerns**. Scatter's scanner/parser/analyzer/store layering is the structural antidote to CDH's 2,300-line monoliths.

## 9. Complementary — where they plug together

They solve complementary halves of the problem and could be composed:

```
                 ┌──────────────────────────────────────────────┐
                 │              Index layer (scatter)           │
                 │  Unified walk · facts cache · incremental    │
                 │  patch · full edge graph (project_ref +      │
                 │  msbuild_import + namespace + type + sproc   │
                 │  + EF + SQL + config_di + rdl_sproc)         │
                 └──────────────────┬───────────────────────────┘
                                    │  exports graph.json +
                                    │  file_facts.json
                                    ▼
                 ┌──────────────────────────────────────────────┐
                 │         Decision layer (CDH-style)           │
                 │  ChangeType taxonomy · pipeline-mappings     │
                 │  regex · YAML artifact derivation · BFS      │
                 │  over reverse graph · threshold gate         │
                 └──────────────────────────────────────────────┘
```

**Concrete composition path**:

1. **Scatter emits a canonical graph JSON + facts** (already does via `graph_cache.json`). Expose a stable query API (`scatter graph export --format impact-json`).
2. **CDH's `Analyze-DependencyImpact.ps1` replaces `Build-DependencyGraph`** with a read of that JSON. Keep `Get-AffectedProjects`, `Get-AffectedSolutions`, `Test-YamlEligibilityByOrigin`, `pipeline-mappings.json`, threshold gate — these are the pieces that encode the team's CD policy and shouldn't move to Python.
3. **Alternatively, implement the decision layer in Python** as `scatter/modes/pr_gate.py`, consuming `pipeline-mappings.json` directly. Kills the PowerShell entirely, at the cost of losing the PS7 parallel+Azure-DevOps integration that already works.

Option (2) is lower-risk and preserves the CDH team's institutional knowledge of their pipeline mapping. Option (3) is cleaner long-term.

The hybrid also means scatter gets pushed on its remaining gaps (plugin XML, change-type classification, pipeline gating) — because the CDH layer consuming the graph would be broken without them, which is the right forcing function.

## 10. Bottom line

- **Not redundant; complementary.** They address different ends of the pipeline: scatter is the better indexer (richer edges, sounder caching, better performance per LOC, more extensible), CDH is the better policy layer (change-type classification, pipeline gating).
- **Scatter's indexing gaps are nearly closed** — `Directory.Build.*` imports, explicit `<Import>` parsing, test-project exclusion, config DI scanning, RDL→sproc scanning, and `.rptproj`/`.vbproj`/`.fsproj` support are all implemented and tested. **Remaining gaps are plugin XML scanning (deferred), change-type classification, and the pipeline decision layer.**
- **CDH's correctness gaps are architectural** — no derived edges means entire classes of dependency go undetected, and the full-cache-invalidation model is a ceiling on its warm-path performance that won't come down without a v2 cache design.
- **The convergent path**: scatter indexes, CDH-style layer decides. Both codebases shrink; neither's strengths are lost.