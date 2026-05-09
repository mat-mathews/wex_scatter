# Monolith Run #1: `usp_SelectAdministratorByAlias`

*2026-05-08 — first full sproc trace against the CDH monolith via Docker*

---

## What we ran

```bash
MSYS_NO_PATHCONV=1 docker run \
  -v "//c/_/health-cdh-ondemand:/workspace" \
  -v scatter-cache:/workspace/.scatter \
  scatter \
    --stored-procedure "usp_SelectAdministratorByAlias" \
    --search-scope /workspace
```

Sproc mode, no AI, cached graph (graph was built on a prior run).

## The codebase

| Metric | Count |
|--------|-------|
| Directories walked | 14,580 |
| .csproj files | 1,633 |
| .cs files | 45,001 |
| .sln files | 358 |
| .config files | 1,533 |
| .rdl/.rdlc files | 1,180 |
| .props/.targets files | 38 |
| Graph nodes | 1,591 |
| Graph edges | 21,883 |

This is a real ~20-year-old .NET monolith. Not synthetic.

## Timing breakdown

| Phase | Timestamps | Duration |
|-------|-----------|----------|
| File discovery (walk 14,580 dirs) | 22:13:14 → 22:15:20 | **2m 6s** |
| Solution scanning (358 .sln files) | 22:15:20 → 22:15:22 | **2s** |
| Graph load from cache (1,591 nodes, 21,883 edges) | 22:15:22 | **<1s** |
| Sproc scan (45,001 .cs files) | 22:15:22 → 22:17:29 | **2m 7s** |
| Consumer analysis (10 classes × 10 targets) | 22:17:29 → 22:28:40 | **11m 11s** |
| **Total** | | **~15m 26s** |

### Where the time goes

**Consumer analysis is 72% of the run.** The three expensive targets:

| Target project | Graph consumers | After test exclusion | Class filter | Time |
|---------------|----------------|---------------------|--------------|------|
| `Lighthouse1.LH1OnDemand.Data.Daab` (DaabAdministratorRepository) | 271 | 226 | → 15 match | **3m 10s** |
| `NavSuiteBusiness` (HierarchyValidatorItem) | 289 | 233 | → 1 match | **3m 38s** |
| `NavSuiteBusiness` (AdministratorDB) | 289 | 233 | → 11 match | **4m 2s** |

The class filter stage scans .cs files in every non-test consumer project for the class name. For `NavSuiteBusiness` with 233 post-exclusion consumers, that means reading .cs files from 233 projects. Twice (two classes in the same project). That's the bottleneck.

The other 7 targets (4 consumers or fewer each) completed in seconds. The cost is proportional to the consumer set size before class filtering — not the result count.

**Sproc scanning is the second cost center at 2m 7s.** This is a sequential scan of 45,001 .cs files looking for the string `usp_SelectAdministratorByAlias`. No parallelism on the sproc scan path right now.

**File discovery at 2m 6s** is Docker/WSL2 overhead. The `walk_and_collect` optimization (single os.walk pass) is working — it collects .csproj, .cs, .sln, .config, .rdl, .props, and .targets in one walk. On native Linux this would be ~20s based on prior benchmarks.

**Graph load is instant** — cached graph with 1,591 nodes and 21,883 edges loaded in under a second. The incremental cache is doing its job.

## Results

28 consumers across 4 targets (of 10 classes found). The sproc appears in:

| Project | Class | Consumers found |
|---------|-------|----------------|
| Lighthouse1.LH1OnDemand.Data.Daab | DaabAdministratorRepository | 15 |
| NavSuiteBusiness | AdministratorDB | 11 |
| NavSuiteBusiness | HierarchyValidatorItem | 1 |
| Lighthouse1.Demographic.Data | DemographicDataLoader | 1 |
| LH1OnDemand.WebApp.Admin | AdministratorRepository | 0 (all consumers are test projects) |
| WexHealth.Apps.Web.Employer.Auth.Data | AdministratorRepository | 0 |
| WexHealth.Apps.Web.Employer.Auth.Data | SsoRepository | 0 |
| WexHealth.CDH.Apps.Web.EmployerUser.Data | AdministratorRepository | 0 |
| Lighthouse1.BankIntegration.Data | AdoCommandSet | 0 |
| LH1OnDemand.WebApp.Admin.UnitTests | DbConnectionExtensionsTests | 0 (test project, 0 consumers) |

6 of 10 classes had zero consumers after filtering. The analysis still ran class filtering against their consumer sets — wasted work. An early exit when all consumers are test projects would skip those scans entirely.

## Issues found

### 1. Duplicate project tree inflates everything

The monolith has `BatchProcess.ExtractPublisher/Current/` which appears to be a vendored copy of large parts of the source tree. This produces **60+ stem collisions** — same project name at two or more paths. Examples:

- `TestHarness` → 7 different .csproj files
- `LH1OnDemand.WebApp.Admin` → 2 copies
- `ExtractPublisher` → 3 copies

**Impact:** The graph has 1,591 nodes but some are duplicates. Consumer counts are inflated. The stem collision resolution picks one arbitrarily. This is a data quality problem, not a scatter bug — but scatter should surface it better. A `--search-scope /workspace/Dev` would avoid the `5.3/` and `Current/` copies.

### 2. Missing `<RootNamespace>` in newer projects

Two projects (`WexHealth.Apps.Web.Employer.Auth.Data`, `WexHealth.CDH.Apps.Web.EmployerUser.Data`) are missing `<RootNamespace>` and `<AssemblyName>` tags. Scatter falls back to the filename stem, which works but is a correctness risk if the actual namespace differs from the filename.

**Impact:** Low. SDK-style projects derive namespace from the directory by default, which typically matches the filename stem. But worth verifying.

### 3. `google.generativeai` SDK deprecation warning

```
FutureWarning: All support for the `google.generativeai` package has ended.
Please switch to the `google.genai` package.
```

Not blocking (no AI was used in this run), but the Gemini provider needs migration before the old SDK stops working.

### 4. Consumer analysis doesn't short-circuit on zero non-test consumers

`LH1OnDemand.WebApp.Admin` has 4 graph consumers, all test projects. After test exclusion: 0. But scatter still logs "No projects directly referencing the target were found" — it ran the exclusion check but didn't skip the class filtering stage. For targets with no non-test consumers, the class filter stage is pure overhead.

### 5. Sproc scan is sequential

The sproc scanner reads 45,001 .cs files sequentially looking for the string. This is 2m 7s that could be parallelized. The consumer analysis pipeline already uses `analyze_cs_files_parallel` for the class/method filter — the sproc scanner should do the same.

## Performance opportunities

| Fix | Estimated impact | Effort |
|-----|-----------------|--------|
| Skip class filter when all consumers are test projects | Saves ~1-2 min for the 6 zero-result targets | S |
| Parallelize sproc scan (reuse `analyze_cs_files_parallel`) | 2m → ~30s (4x on 4 cores) | S |
| Narrow `--search-scope` to `/workspace/Dev` to avoid duplicate tree | Fewer nodes, fewer collisions, cleaner results | Config (user-side) |
| Deduplicate same-stem projects at graph build time | Cleaner graph, accurate consumer counts | M |
| Cache the sproc scan results alongside graph cache | Skip 45K file scan on repeat sproc queries | M |

## What this validates

**Graph caching works.** 1,591 nodes, 21,883 edges, loaded in <1s. No rebuild needed.

**Graph-accelerated consumer lookup works.** "Using graph-accelerated consumer lookup (271 direct consumer(s))" — the O(1) reverse lookup replaces the filesystem scan for stages 1-2.

**Test project exclusion works.** Excluded 1-56 test projects per target. Correctly prevented test-only consumers from appearing in results.

**Sproc tracing end-to-end works.** Found the sproc in 10 classes across 8 projects, traced consumers through the dependency graph, produced a ranked table with coupling scores and solution membership.

**The 15-minute runtime is acceptable for a first real run.** But for interactive use (a dev asking "what calls this sproc?"), it needs to be under 2 minutes. The parallelization and short-circuit fixes above would get it there.

## Roadmap implications

This run is the "validate on real monolith" item from ROADMAP_2026.md Tier 1. Key takeaways:

1. **Scatter works on the real codebase.** No crashes, no incorrect results (that we can verify), correct consumer ranking with graph metrics.
2. **The duplicate project tree is the biggest data quality issue.** The `BatchProcess.ExtractPublisher/Current/` vendored copy inflates everything. Recommend scoping to `/workspace/Dev` or implementing project deduplication.
3. **15 minutes is too slow for interactive sproc queries.** Two fixes (parallelize sproc scan + short-circuit empty consumer sets) would cut it to ~5-8 minutes. Narrowing the search scope would cut it further.
4. **The Gemini SDK needs migration.** Not urgent but the deprecation warning is a signal.
5. **Graph build performance is not the issue.** Graph loads from cache in <1s. The bottleneck is the class filter scanning .cs files in 200+ consumer projects — that's the consumer analysis pipeline, not the graph.
