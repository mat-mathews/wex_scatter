# Target Project Analysis

You're refactoring a shared library and need to know who's using it. Maybe someone said "we want to modernize GalaxyWorks.Data" and you need to find out how many teams will have opinions about that. This is the mode for that.

Point Scatter at a `.csproj` file. It finds every project that references it, confirms they actually import the namespace, and optionally drills down to specific class or method usage.

## Basic Example

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .
```

```
Search scope: /code/scatter (scanned 11 projects, 27 files)
Filter: 11 → 7 project refs[graph] → 6 namespace

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (6 consumer(s))
         -> Consumed by: GalaxyWorks.Api (GalaxyWorks.Api/GalaxyWorks.Api.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=7.1, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=10.8, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.Data.Tests (GalaxyWorks.Data.Tests/GalaxyWorks.Data.Tests.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=3.5, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=12.7, fan-in=1, fan-out=1, instability=0.500, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp (MyGalaxyConsumerApp/MyGalaryConsumerApp.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=4.3, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp2 (MyGalaxyConsumerApp2/MyGalaryConsumerApp2.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=1.8, fan-in=0, fan-out=1, instability=1.000, in-cycle=no

--- Total Consuming Relationships Found: 6 ---

Analysis complete. 6 consumer(s) found across 1 target(s).
```

Six consumers. That's your blast radius. Now you know who to talk to before you start moving things around.

## Narrowing the Results

Six consumers is manageable. But GalaxyWorks.Data exports a lot of types, and maybe you only care about one class.

### Filter by Class

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --class-name PortalDataService
```

```
Filter: 11 → 7 project refs[graph] → 6 namespace → 6 class match
```

All 6 consumers reference `PortalDataService` -- it's the main type in GalaxyWorks.Data. For libraries with multiple types, this filter cuts aggressively.

### Filter by Method

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --class-name PortalDataService \
  --method-name StorePortalConfigurationAsync
```

```
Filter: 11 → 7 project refs[graph] → 6 namespace → 6 class match → 1 method match
```

Only one project actually calls `StorePortalConfigurationAsync`. If you're changing that method's signature, this is the only consumer that needs updating.

Note: `--method-name` requires `--class-name`. Pass `--method-name` alone and Scatter warns and ignores it.

## Other Scenarios

### Mid-Tier Library (1 Consumer)

```bash
scatter --target-project ./GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj --search-scope .
```

WebPortal sits in the middle of the dependency chain. Only GalaxyWorks.BatchProcessor references it. One consumer -- small blast radius, straightforward coordination.

### Leaf Project (1 Consumer)

```bash
scatter --target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .
```

MyDotNetApp has a single consumer: MyDotNetApp.Consumer. Leaf projects are the easy ones. Change it, update the one consumer, move on.

### Standalone Project (0 Consumers)

```bash
scatter --target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .
```

Nobody references this project. Zero consumers. If you expected consumers and see zero, check whether the consuming code uses NuGet packages instead of `<ProjectReference>` entries -- Scatter only tracks project references, not package references.

## Override Namespace

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --target-namespace Company.Product.OldStuff
```

Scatter normally derives the namespace from `<RootNamespace>` in the target's `.csproj`. When that doesn't match what the code actually uses (legacy projects, renamed assemblies, shared namespace conventions), override it with `--target-namespace`. Scatter will look for `using Company.Product.OldStuff;` instead of the auto-derived namespace.

## AI Summaries

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --summarize-consumers --google-api-key $GOOGLE_API_KEY
```

For each consumer, Scatter sends its relevant `.cs` files to Gemini and gets back a 2-3 sentence summary of what that code does. Useful when you're triaging a long consumer list and need to quickly understand "what does MyGalaryConsumerApp actually do with PortalDataService?" without opening 15 files.

## Output Formats

**JSON** -- for downstream tooling:

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format json --output-file reports/target_analysis.json
```

**CSV** -- for the teammates who live in spreadsheets:

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format csv --output-file reports/target_analysis.csv
```

**Markdown** -- for pasting into a PR or wiki:

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope . --output-format markdown --output-file reports/target_analysis.md
```

Markdown also works without `--output-file` -- it prints to stdout so you can pipe it wherever you need it. See [Output Formats](../output-formats.md) for detailed structure of each format.

## Reading the Filter Pipeline

The most important line in the output is the arrow chain. Read it left to right:

```
Filter: 200 → 12 project refs[graph] → 8 namespace → 4 class match
```

Translation: "200 projects in scope. 12 have a `<ProjectReference>` to the target. 8 of those import the namespace. 4 of those reference the class."

Each arrow is a stage that narrows the set. When you're debugging a surprising result -- too many consumers, or zero when you expected some -- this chain tells you exactly where things went wrong.

### When a Stage Drops to Zero

When a filter stage produces zero results, Scatter prints a diagnostic hint:

```
Filter: 200 → 12 project refs[graph] → 0 namespace
  Hint: 0 of 12 project-reference-matching projects contained 'GalaxyWorks.Data'
        — verify the namespace name
```

This usually means the auto-derived namespace doesn't match what the code uses. Fix it with `--target-namespace`.

If the project reference stage itself drops to zero, nobody has a `<ProjectReference>` to the target. Possible causes: the consuming code references it as a NuGet package, or you're looking in the wrong `--search-scope`.

---

!!! info "How this works"
    Scatter runs a 5-stage filter pipeline (discovery, project references, namespace, class, method). When a dependency graph cache is available, stages 1-2 use a cached reverse index instead of scanning the filesystem. See [Consumer Detection Pipeline](../reference/consumer-pipeline.md) for the full stage-by-stage breakdown.
