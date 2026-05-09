# Sproc Mode Performance Plan

Based on the first real monolith run (`perf_runs/1.txt`, 2026-05-08): `--stored-procedure "usp_SelectAdministratorByAlias"` against 1,591 projects, 45,001 .cs files. Total runtime: 15m 26s.

---

## Where the time goes

| Phase | Duration | % of total |
|-------|---------|------------|
| File discovery (walk 14,580 dirs) | 2m 6s | 14% |
| Solution scanning | 2s | 0% |
| Graph load from cache | <1s | 0% |
| Sproc file scan (45,001 .cs files) | 2m 7s | 14% |
| Consumer analysis (10 classes, sequential) | 11m 11s | 72% |
| **Total** | **15m 26s** | |

Consumer analysis dominates. The sproc scan itself is secondary. Here's why consumer analysis is slow and what to do about it.

---

## The real problem: repeated rescanning

`run_sproc_analysis()` in `analysis.py:645-730` finds 10 classes that reference the sproc, then calls `find_consumers()` once per class, sequentially. Each call independently:
1. Looks up the target project's consumers via the graph (fast — <1s)
2. Excludes test projects (fast)
3. Scans .cs files in every remaining consumer for namespace matches (slow)
4. Scans matching files for the class name (slow)

The sproc was found in 10 classes across 8 projects. Two projects (`NavSuiteBusiness`, `WexHealth.Apps.Web.Employer.Auth.Data`) had multiple classes each. For `NavSuiteBusiness` with 289 graph consumers and 233 after test exclusion, the namespace + class scan ran twice — once for `AdministratorDB`, once for `HierarchyValidatorItem`. Same 233 projects scanned both times. That's ~7 minutes of duplicate work.

The consumer analysis pipeline is already parallelized internally — `analyze_cs_files_parallel` handles the per-file regex matching. The problem isn't parallelism within a single `find_consumers()` call. It's that we make 10 separate calls when most of them hit the same consumer sets.

---

## The plan

### Phase 1: Deduplicate consumer analysis per target project

**The fix:** Group sproc results by target project before calling `find_consumers()`. For each unique target project, call `find_consumers()` once with no class filter. Then apply class filters locally on the already-fetched consumer file data.

**Currently:** 10 calls to `find_consumers()` (one per class).
**After:** 8 calls (one per unique project). For the two projects with multiple classes, the namespace scan runs once instead of twice.

```
Before: NavSuiteBusiness × AdministratorDB      → find_consumers() → 233 projects scanned → 4m
         NavSuiteBusiness × HierarchyValidatorItem → find_consumers() → 233 projects scanned → 3m 38s
                                                                                    Total: 7m 38s

After:  NavSuiteBusiness (both classes)          → find_consumers() → 233 projects scanned → ~4m
        Class filter locally on cached results   → <1s
                                                                                    Total: ~4m
```

**Where to change:** `analysis.py`, `run_sproc_analysis()`. Group the sproc scanner results by project, call `find_consumers()` once per project, then filter by class from the returned consumer file data.

**Effort:** S — restructure the loop, no new infrastructure.

**Risk:** Low. The consumer results include file-level data already. Class filtering is a string match on the file content that's already been read.

**Estimated savings:** ~3-4 minutes on this run (eliminates duplicate scans of `NavSuiteBusiness`'s 233 consumers).

### Phase 2: Early exit when all consumers are test projects

**The fix:** After test project exclusion, if the consumer set is empty, skip all downstream stages. Currently `find_consumers()` does return early at line 260-262 — so this is already handled inside `find_consumers()`. But `run_sproc_analysis()` still logs and processes the empty result.

The real win is at the `run_sproc_analysis()` level: if a target project has zero non-test consumers in the graph, don't call `find_consumers()` at all. Check the graph directly.

**Where to change:** `analysis.py`, `run_sproc_analysis()`. Before calling `find_consumers()`, check `graph.get_consumers(project)` and filter test projects. If empty, skip with a log line.

**Effort:** S — 5-10 lines.

**Estimated savings:** Saves the overhead of entering `find_consumers()`, setting up the pipeline, and logging for the 6 targets that had zero results. Minor per target (~2-5s each), but adds up across multiple zero-result classes.

### Phase 3: Cache namespace scan results across calls

**The fix:** The namespace stage in `find_consumers()` scans .cs files in each consumer project for `using` statements matching the target namespace. When two classes live in the same target project, they share a namespace — so the namespace scan produces identical results both times.

Add a cache keyed on `(consumer_project_path, target_namespace)` → set of matching files. The cache lives for the duration of the `run_sproc_analysis()` call (not persisted).

**Where to change:** `consumer_analyzer.py`, `find_consumers()`. Accept an optional `namespace_cache` dict parameter. Before scanning, check the cache. After scanning, populate it. `run_sproc_analysis()` creates the cache and passes it to each `find_consumers()` call.

**Effort:** S-M — threading the cache through is the main work. The scan logic doesn't change.

**Estimated savings:** On this run, `NavSuiteBusiness` and `WexHealth.Apps.Web.Employer.Auth.Data` each had 2 classes. The namespace scan for their consumer sets ran twice each. Cache hit would skip ~3-4 minutes of duplicate scanning.

**Note:** This stacks with Phase 1. Phase 1 eliminates same-project duplicates entirely. Phase 3 catches cross-project cases where different projects share consumers (less common but possible via transitive dependencies). If Phase 1 ships first, Phase 3 may not be needed — measure first.

### Phase 4: Parallelize the post-match class extraction in sproc scanner

**The fix:** `sproc_scanner.py:118-174` reads each matched file sequentially to extract the enclosing class name via `find_enclosing_type_name()`. This is file I/O + regex per file, done one at a time.

The sproc scan found 10 files. At monolith scale with a widely-used sproc, this could be 50+. Batch the file reads using `ThreadPoolExecutor` (I/O-bound, not CPU-bound — threads are fine).

**Where to change:** `sproc_scanner.py`, `find_cs_files_referencing_sproc()`. Replace the sequential loop at line 118 with a `ThreadPoolExecutor.map()` over the matched files.

**Effort:** S — straightforward thread pool, same pattern as `analyze_cs_files_parallel`.

**Estimated savings:** Minimal on this run (10 files, ~1s total). Matters for sprocs referenced in 50+ files.

### Phase 5: Sproc result caching alongside graph cache

**The fix:** The sproc scan reads 45,001 .cs files looking for a string. This is 2m 7s that produces a small result (10 files). If the graph cache knows which files reference which sprocs, the scan can be skipped on repeat queries.

**Approach:** During graph build Step 6 (DB scanner), sproc references are already extracted and stored as `ProjectNode.sproc_references`. The mapping `{sproc_name → [(project, class, file)]}` is derivable from the graph without rescanning.

**Where to change:** `analysis.py`, `run_sproc_analysis()`. Before calling `find_cs_files_referencing_sproc()`, check if the graph has sproc reference data. If yes, build the sproc→class mapping from graph node metadata instead of scanning files.

**Effort:** M — need to verify the graph's sproc data is complete enough (it stores sproc names per project but may not store the containing class or file path).

**Estimated savings:** Eliminates the 2m 7s sproc scan entirely on cached runs. First run still pays the cost.

---

## Team review (2026-05-08)

Nine-person review surfaced seven action items. Key feedback incorporated below.

### API design: don't post-filter, batch the class stage

Priya and Sam both flagged that calling `find_consumers()` with `class_name=None` and then reimplementing class filtering in `run_sproc_analysis()` leaks the pipeline's internals across modules. Two options:

1. **`class_names: List[str]` parameter on `find_consumers()`** (Sam's suggestion) — runs the class stage once against all class names in a single pass. Keeps all filtering logic in one place.
2. **`find_consumers_batch(targets: Dict[Path, List[str]])`** (Priya's suggestion) — one namespace scan, fan out into N class filters on the same file set. Cleaner abstraction but bigger surface area change.

**Decision:** Option 1 (Sam's). Lower risk, smaller diff. `find_consumers()` already has `class_name: Optional[str]`. Change it to `class_name: Optional[Union[str, List[str]]]`, run the class stage once with all names, partition results by class. Backward compatible — a single string still works.

### Kai's question: do we even need class filtering in sproc mode?

If a project has a `<ProjectReference>` to the sproc-containing project, it's a consumer. The namespace and class scans verify that consumers actually *use* the specific class — but for sproc mode, the user asked "who's affected by this sproc?" not "who calls this exact class." Project-reference consumers might be sufficient.

**Decision:** Measure the false positive rate. On this run, `NavSuiteBusiness` has 289 graph consumers → 233 after test exclusion → 11 after class filtering. That's a 95% filter rate. Class filtering clearly matters here. But the question is worth revisiting if we find sprocs where the filter rate is low (<50%) — the class scan is expensive and may not be worth the precision in every case. Add a note in the code.

### Kill Phases 3 and 4

Tomás and Marcus agree: Phase 3 is likely dead after Phase 1 (same-project dedup eliminates the duplicate namespace scans). Phase 4 saves <10s for 10 files — not worth the complexity. Measure after Phase 1 ships.

### Phase 5: defer until graph schema question is answered

Two blockers (Anya, Priya):
1. `ProjectNode.sproc_references` stores sproc names but not the containing class or file path. Extending the schema is a separate design decision.
2. Staleness risk: if a new .cs file referencing the sproc is added after the graph was built, the cached path misses it. The graph patcher re-extracts sproc references for affected projects (`graph_patcher.py:391`), but only for projects it knows changed. A new file in an unaffected project would be missed.

**Decision:** Defer Phase 5. Write a separate plan if needed after Phases 1-2 ship and we have measured numbers.

### Error handling for grouped failures (Fatima)

If `find_consumers()` fails for a project, the current loop continues to the next class. After Phase 1 groups by project, a project-level failure takes out all classes in that project. Log which classes were skipped, not just the project name.

---

## Implementation order (revised)

| Phase | What | Effort | Estimated savings | Status |
|-------|------|--------|-------------------|--------|
| 1+2 | Deduplicate per project + early exit on zero consumers | S | ~3.5 min | **Ship first** |
| 3 | Cache namespace scan results | — | — | **Killed** (Phase 1 makes it unnecessary) |
| 4 | Parallelize sproc class extraction | — | — | **Killed** (<10s savings, not worth it) |
| 5 | Sproc result caching from graph data | M | 2 min | **Deferred** (graph schema + staleness) |

### Phase 1+2 implementation checklist

- [ ] Add `class_name: Optional[Union[str, List[str]]]` to `find_consumers()` signature
- [ ] When `class_name` is a list, run class stage once matching all names, partition results
- [ ] Group sproc scanner results by target project in `run_sproc_analysis()`
- [ ] Call `find_consumers()` once per unique project with `class_name=[list of classes]`
- [ ] Before calling `find_consumers()`, check graph for non-test consumers; skip if empty
- [ ] Wrap project-level call in try/except; log skipped class names on failure (Fatima)
- [ ] Regression test: two-class-same-project fixture, assert identical output to sequential
- [ ] Add code comment: class filtering is 95% filter rate on `NavSuiteBusiness` (Kai's question)
- [ ] Measure and log wall-clock time per project for comparison with `perf_runs/1.txt`

**Projected total after Phase 1+2:** ~15m → ~10-11m (~30% reduction).

---

## What this doesn't fix

**Docker/WSL2 file discovery overhead (2m 6s).** The `walk_and_collect` single-pass optimization is already in place. The remaining cost is the 9P filesystem bridge between Windows and the Linux container. Running natively on Linux (or on a Mac) would cut this to ~20s. Not a scatter problem — it's a Docker-on-Windows problem.

**Consumer analysis scaling with fan-out.** A project with 289 graph consumers will always require scanning those consumers' .cs files for class matches. The parallelism inside `analyze_cs_files_parallel` helps, but the work is proportional to the consumer set size. The only way to make this fundamentally faster is to precompute class-to-project mappings in the graph — which is what the tree-sitter method graph (ROADMAP_2026.md, "The longer arc") would provide.

**The duplicate project tree.** `BatchProcess.ExtractPublisher/Current/` inflates the graph with duplicate projects. Scatter can't fix the repo layout. The user should scope to `--search-scope /workspace/Dev` to avoid it, or we could add an `exclude_paths` config option.
