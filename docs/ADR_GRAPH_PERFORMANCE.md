# How We Made the Graph Builder 100x Faster

**March 2026**

---

## The Story

We've got a legacy .NET monolith. 500+ projects, thousands of C# files, 20 years of organic growth. Scatter's `--graph` mode needs to build a complete dependency graph of this thing so teams can understand what depends on what before they start pulling pieces apart.

The graph builder was way too slow. Like, embarrassingly slow. At just 100 projects it took almost 3 minutes. At 250 projects we had to kill it after 10 minutes. At 500 projects? Don't even think about it.

We built synthetic codebases to simulate the real thing, profiled the hell out of it, considered a bunch of approaches, got a second opinion from another senior engineer (chatgpt), and landed on an approach that brought 100 projects from 172 seconds down to 1.7 seconds. 500 projects builds in under a minute now.

Here's how we got there, what we tried, what we rejected, and where we'd go next.

---

## What Was Actually Slow

The graph builder has about 7 internal stages. Most of them are fine. The killer was Stage 7: "type usage edge building." This is the step where we figure out which projects actually reference types declared in other projects.

The original code did this:

```python
for each_file in all_cs_files:
    content = read_the_file()
    for each_type_name in all_known_types:
        if regex_search(type_name, content):
            record_dependency()
```

That's an O(F x T x S) triple nested loop. For every file, for every known type, scan the entire file content with a freshly compiled regex. At 100 projects that's **1,170,320 regex operations**. At 500 projects it's tens of millions. Each one compiling a brand new regex pattern from scratch. Every single time.

The benchmark confirmed it: 156.7 seconds in that one stage alone. 91% of the total build time. Everything else was noise.

---

## Decision 1: The Inverted Index (the big win)

**Status: Done.**

Instead of asking "does this file contain Type A? Type B? Type C? ..." for every single type, flip it around. Read the file once, pull out every identifier, throw them in a set, and intersect with the set of known type names.

```python
identifiers_in_file = set(re.findall(r'[A-Za-z_]\w*', content))
types_found = identifiers_in_file & all_known_type_names
```

That's it. One regex pass over the file. One set intersection. The number of known types doesn't matter anymore -- it drops out of the equation entirely. O(F x S) instead of O(F x T x S).

### What we considered instead

**Mega-regex** -- combine all type names into one giant alternation pattern like `\b(?:TypeA|TypeB|TypeC|...)\b`. This was the first idea and it sounds clever. Problem is, Python's regex engine is NFA-based (backtracking), not DFA-based. A huge alternation doesn't magically become a trie lookup. The engine still tries each alternative at each position in the string. You're getting maybe 5-10x from reduced Python loop overhead, not the 1000x we needed. An external engineer we bounced this off of nailed it: "Mega-regex is a tactical optimization on the wrong abstraction boundary."

**Aho-Corasick** -- the textbook-correct answer for multi-pattern matching. Build a finite automaton, single-pass scan per file. Theoretically optimal. But it requires a C extension dependency (`pyahocorasick`), and in practice the inverted index achieves the same complexity class with zero dependencies. The tokenizer already gives us O(S) per file. Aho-Corasick would give us O(S + M). For our use case, that's the same thing.

**Pre-compiled patterns** -- at least stop recompiling the regex every time, right? Sure, but that only saves the compilation overhead. You're still running 1,170,320 searches. You optimized the wrong part.

### How we verified it

We tested 15 different C# edge cases comparing `\b<type>\b` regex against the `[A-Za-z_]\w*` tokenizer. Generics, arrays, nullables, `typeof()`, `nameof()`, XML doc comments, interpolated strings, partial-word overlaps, single-character types, underscore-prefixed types. All 15 produced identical results. The tokenizer finds every context where a type name appears as a real code dependency -- variable declarations, method parameters, base classes, `new` expressions -- because in all of those contexts, the type name is a standalone identifier token.

---

## Decision 2: Strip Comments First

**Status: Done.**

Both the old regex and the new tokenizer will match type names that appear in comments. A comment like `// TODO: refactor PortalDataService` creates a false dependency edge. That's noise in the graph.

We already had a comment stripper in the codebase (`_strip_cs_comments` in `db_scanner.py`) -- a char-by-char state machine that handles `//`, `/* */`, verbatim strings, regular strings, the whole deal. It was built for the DB scanner. We just reused it.

Tested it: stripped 3 false positives from a sample file (type names that only appeared in comments). Real code references were preserved. String literal contents are kept too -- if someone writes `"Use PortalDataService here"` that still matches, which is fine. Cross-project type names in strings are rare and harmless.

### The trade-off

Comment stripping is now the most expensive single operation in Stage 7. At 500 projects it eats 18 seconds -- 77% of the stage time. The stripper is a Python char-by-char loop processing 232 MB of source. That's a lot of Python bytecode iterations.

We accepted this because the precision matters more than the seconds right now. The graph is for humans making decisions about what to decouple. False edges from commented-out code are confusing and erode trust. And 60 seconds total for a 500-project cold build is fine. We can make the stripper faster later without changing the architecture (see the roadmap below).

---

## Decision 3: Fix the Type Name Collision Bug

**Status: Done.**

Found this one thanks to an external review. The original code mapped each type name to a single project:

```python
type_to_project[type_name] = project_name  # last writer wins
```

If `Order` exists as a class in both `Billing.Core` and `Sales.Models`, only whichever project happened to process last would get recorded. The other one gets silently dropped. That's a data-loss bug -- you'd miss real dependency edges.

Fixed it with a multi-owner map:

```python
type_to_projects[type_name].add(project_name)  # track all owners
```

Now if a file uses `Order` and it exists in 3 projects, we create edges to all 3. Is that overly broad? A little. But it's correct in the sense that we're capturing all possibilities. Future work (namespace disambiguation, see below) can prune the ambiguous ones using `using` directives we already collect. But dropping data silently? That's way worse than being a little broad.

---

## Decision 4: Don't Do Mega-Regex

**Status: Formally rejected.**

Covered this above, but it deserves its own record because it was the initial hypothesis and we deliberately walked away from it. The short version:

- Python's regex engine doesn't turn alternations into efficient lookups
- You're still O(F x T x S), just with a smaller constant factor
- At 6,000+ types the pattern string is 120KB -- you're asking for trouble
- It doesn't compose cleanly with comment stripping
- An independent engineer review agreed: wrong tool for the job

The inverted index gave us 100x. Mega-regex would've given us maybe 5-10x. When you're choosing between fixing the algorithm and polishing the implementation, fix the algorithm.

---

## The Numbers

### Before and After

| Scale | Projects | Files | Before | After | Speedup |
|-------|----------|-------|--------|-------|---------|
| Small | 100 | 1,135 | 172s | **1.7s** | **101x** |
| Medium | 250 | 4,760 | >10min (killed) | **10.1s** | **>60x** |
| Large | 500 | 13,986 | projected hours | **42.8s** | -- |

### Where the Time Goes Now (500 projects, 60s total)

| Stage | Time | % | What it's doing |
|-------|------|---|-----------------|
| type_usage_edges | 26.1s | 43% | Comment strip (18s) + tokenize (4s) + file reads (1.4s) + set ops (0.2s) |
| find_clusters | 16.7s | 28% | Label propagation on one giant 500-node component |
| type_extraction | 13.9s | 23% | Reading 14K files, running 3 regex patterns each |
| cs_mapping | 2.7s | 4% | Mapping .cs files to parent projects |
| everything else | 1.0s | 2% | File discovery, csproj parsing, metrics, cycles, health |

Three things dominate: comment stripping, label propagation, and type extraction. Everything else is in the noise.

### Inside the Comment Stripping (18s)

This is 77% of the type_usage_edges stage. The `_strip_cs_comments()` function appends characters one at a time to a Python list. For 232 MB of source that's ~232 million `list.append()` calls. Python bytecode is not fast at this.

### Inside Label Propagation (21s)

The clustering algorithm calls `get_edges_between(a, b)` about 205,000 times per iteration, and it runs 3 iterations. Each call does a linear scan through all of node A's edges to find the ones pointing at B. With 500 nodes averaging 434 edges each, that's a lot of linear scans. The fix is obvious -- build a lookup dict once -- we just haven't done it yet.

### A gotcha: tracemalloc

Our benchmark tool uses Python's `tracemalloc` for memory measurement. This hooks every allocation. The comment stripper does millions of tiny allocations (one per character). Under tracemalloc, Stage 7 reports 26 seconds. Without it, the actual wall-clock time is about 5 seconds. We almost chased the wrong bottleneck before we figured this out. Lesson learned: always verify performance numbers with a clean timing run, no instrumentation.

---

## Where We'd Go Next

### Phase 1: Knock Out the Easy Stuff (2-3 days)

**Faster comment stripping.** The current stripper appends one character at a time. Refactor it to track start/end positions and slice the string in chunks instead. Same logic, same correctness, 2-3x faster. No risk. If we want more, add a `--fast-graph` flag that skips stripping entirely for people who just want speed over precision.

**Fix label propagation.** Build a `neighbor_weights` lookup dict once at the start of the function instead of calling `get_edges_between()` 600K times. This is a 20x improvement for about 20 lines of code. The 21-second stage drops to under a second.

**Parallelize type extraction.** We already have `ProcessPoolExecutor` infrastructure. Chunk the 14K files across workers, each worker reads + extracts types/usings/sprocs, merge the results. The pattern is already established in `parallel.py`. Maybe 4-8x on an 8-core machine.

**After Phase 1:** 500 projects in ~15-20 seconds.

### Phase 2: Improve the Architecture (3-5 days)

**Namespace disambiguation.** When a type name maps to multiple projects, use the `using` directives we already collect to figure out which one the source file actually imports. This cuts down false edges from common names like `Result`, `Status`, `Type` without dropping any real ones.

**Per-file facts cache.** Right now the same file gets read in Stage 4 (extraction) and again in Stage 7 (type usage). Build a `FileFacts` dataclass that holds the content, stripped content, identifier set, declared types, and using statements. Compute it once, use it everywhere. Clean architecture, eliminates redundant I/O.

**Edge confidence levels.** Label edges as `lexical` (we saw the identifier) vs `resolved` (we confirmed via namespace/using). This is a product improvement more than a performance one, but it makes the graph output more trustworthy.

**After Phase 2:** 500 projects in ~12 seconds. More importantly, better graph quality.

### Phase 3: Only If We Need It

**C extension for comment stripping.** The state machine is trivial C code. If Python is still the bottleneck after the slice refactor, a Cython or cffi version would crush it. But only if we actually need sub-10-second builds at 1000+ projects.

**Roslyn semantic resolution.** The nuclear option for type accuracy. Actually compile the projects and ask the .NET compiler which types are referenced. Correct by definition, but requires the .NET SDK on the machine, the projects need to be buildable, and it's slow. Use it surgically -- only for the ambiguous cases that namespace disambiguation can't resolve.

**Incremental graph updates.** Instead of rebuilding the whole graph, diff against the last build and only reprocess changed files. Huge win for repeated builds but the cache invalidation logic is tricky. The current JSON cache already handles the simple case (full rebuild on any change).

### Projected Timeline

| Scale | Now | Phase 1 | Phase 2 | Phase 3 |
|-------|-----|---------|---------|---------|
| 100 projects | 1.7s | ~1s | ~1s | <1s |
| 250 projects | 10s | ~4s | ~3s | ~2s |
| 500 projects | 43s | ~15s | ~12s | ~5s |
| 800 projects | ~130s | ~35s | ~25s | ~10s |
| 1,000 projects | ~220s | ~60s | ~45s | ~20s |

---

## The Tools We Built

**Synthetic codebase generator** (`tools/generate_synthetic_codebase.py`). Makes realistic .NET monolith directory trees at any scale. SDK and Framework style csproj files, .cs files with real type declarations, using statements, sproc references, comments, method bodies. Hub-leaf coupling topology that mimics how real monoliths are wired. Presets from 100 to 800 projects.

**Benchmark harness** (`tools/benchmark_graph_build.py`). Instruments the graph builder with per-stage timing and memory tracking. Two modes: black-box (time the whole function) and stages (time each internal step). Just remember the tracemalloc caveat -- it inflates numbers for allocation-heavy code.

---

## What We Learned

**Measure first.** We suspected the type usage loop was slow. The benchmark proved it was 91% of build time. But it also revealed that `find_clusters` becomes 28% of the build at 500 projects -- something nobody would've predicted from reading the code. You don't know where the time goes until you measure.

**Fix the algorithm, not the constants.** Mega-regex would've been a 5-10x improvement by reducing Python loop overhead. The inverted index was a 100x improvement by eliminating an entire dimension from the computation. When you're looking at a triple nested loop, the answer isn't "make the inner loop faster." The answer is "get rid of a loop."

**Get a second set of eyes.** The type name collision bug was found by an external engineer review, not by our performance analysis. Profiling finds speed problems. Code review finds correctness problems. You need both.

**Synthetic benchmarks reveal scaling curves.** At 100 projects, label propagation is 0.04 seconds and invisible. At 500 projects it's 21 seconds and 28% of the build. Super-linear growth is invisible at small scale. If you only test small, you ship problems that blow up in production.

**Be careful with your measurement tools.** tracemalloc is great for finding memory leaks. It is terrible for performance measurement. It made 5-second work look like 26-second work because the comment stripper does millions of tiny allocations. We almost optimized the wrong thing.
