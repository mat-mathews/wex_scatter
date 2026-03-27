# Git Branch Analysis

You're about to merge a feature branch and want to know what you might break. Someone asks "what's the blast radius?" and you'd rather answer with data than a shrug.

Give Scatter a branch name. It diffs against the base, extracts the type declarations from changed `.cs` files (classes, structs, interfaces, enums, records, delegates), and runs consumer detection for each one. The result: a list of every project affected by the types you touched.

## Basic Example

```bash
scatter --branch-name feature/new-widget --repo-path .
```

```
--- Running Git Branch Analysis Mode ---
Comparing branch 'feature/new-widget' against base 'main' in repo '.'

Step 1: Analyzing Git changes...
Processed 3 changed C# file(s). Identified 2 project(s) with changes.

Step 2: Extracting type declarations from changed C# files...
Found 5 unique type declaration(s) across 2 project(s).

Step 3: Analyzing consumers...

--- Analyzing Target Project 1/2: GalaxyWorks.Data ---
Analyzing consumers for 3 types detected in changed files: FakeDatabaseHelper, IDataAccessor, PortalDataService

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (4 consumer(s))
    Type/Level: PortalDataService
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)

Analysis complete. 6 consumer(s) found across 2 target(s).
```

Each type gets its own consumer list. If `PortalDataService` has 4 consumers and `FakeDatabaseHelper` has 2, they show up separately so you can see which type drives the most impact.

## Different Base Branch

```bash
scatter \
  --branch-name feature/hotfix \
  --base-branch develop \
  --repo-path /path/to/repo
```

When your team branches off `develop` instead of `main`, override the base. Scatter finds the merge-base (the common ancestor), not just the tip of `develop`.

## Default vs. Hybrid Extraction

Scatter offers two ways to figure out which types changed. This is a practical choice, not a technical curiosity.

**Default (regex)** -- fast, no API key needed. Scatter extracts ALL types declared in changed files, even if you only touched a comment inside one of them. On a file with 5 classes where you changed one, it reports all 5.

**Hybrid (`--enable-hybrid-git`)** -- more precise. Sends each changed file plus its diff to Gemini, which identifies only the types whose body or signature actually changed. Falls back to regex automatically if the API call fails.

```bash
scatter \
  --branch-name feature/refactor-data-layer \
  --repo-path . \
  --enable-hybrid-git \
  --google-api-key $GOOGLE_API_KEY
```

Use default for quick checks and CI pipelines where speed matters and false positives are acceptable. Use hybrid when precision matters -- a complex PR with many types per file, or when you need a clean report for a review meeting.

The practical difference: on a branch that touches 15 files across 3 projects, regex might report 40 types. Hybrid might report 12. Both find the same consumers for the types they do report. The difference is in the starting set.

| | Regex (default) | Hybrid (`--enable-hybrid-git`) |
|---|---|---|
| **Speed** | Milliseconds per file | 1-3 seconds per file (API round-trip) |
| **Precision** | All types in changed files | Only types with actual changes |
| **Comment-only changes** | Reports types as changed | Correctly identifies no type changes |
| **API key required** | No | Yes (Gemini) |
| **Failure mode** | Regex errors are rare | Falls back to regex on API failure |

## Filter by Class

```bash
scatter \
  --branch-name feature/new-widget \
  --repo-path . \
  --class-name WidgetFactory
```

Even though the branch touched files declaring `WidgetFactory`, `WidgetConfig`, and `WidgetValidator`, this restricts analysis to only `WidgetFactory`. Useful when you know exactly which type you care about and want to skip the noise.

## Full Pipeline Integration

```bash
scatter \
  --branch-name feature/data-migration \
  --repo-path /path/to/repo \
  --search-scope /path/to/services \
  --pipeline-csv build/pipeline_map.csv \
  --output-format json \
  --output-file reports/analysis.json
```

This combines everything: git analysis, pipeline name resolution (maps consumer project names to their CI/CD pipeline names via CSV), and JSON output. The JSON report includes pipeline names alongside each consumer, so you know which builds to watch after merging.

Output formats (json, csv, markdown) work the same as in target project mode. See [Output Formats](../output-formats.md) for details.

## Git-Specific Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-r`, `--repo-path` | `.` | Path to the git repository |
| `-b`, `--base-branch` | `main` | Branch to compare against |
| `--enable-hybrid-git` | off | Use Gemini for precise type extraction |

When `--search-scope` is omitted, the repo path doubles as the search scope. Specify `--search-scope` separately when you want to analyze changes in one repo but search for consumers across a broader directory.

---

!!! info "How this works"
    Scatter diffs the branch against its base, extracts type declarations from changed `.cs` files, and runs consumer detection per type. The hybrid mode sends the diff to a Gemini LLM to identify which types were meaningfully changed. See [Type Extraction](../reference/type-extraction.md) for the regex pattern and LLM prompt design.
