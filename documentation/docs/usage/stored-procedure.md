# Stored Procedure Analysis

Your DBA is changing a stored procedure. Which C# services are about to break?

This is the question nobody can answer quickly, because sproc callers are invisible in the project reference graph. No `<ProjectReference>` points at a stored procedure. The coupling lives inside `.cs` files as string literals -- `"dbo.sp_InsertPortalConfiguration"` buried in a data access layer somewhere. Your DBA changes a parameter list and has no idea which services just broke.

Scatter makes that invisible coupling visible. Give it a sproc name, and it traces the full chain: sproc to containing class to consumer projects.

## Basic Example

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```

```
Search scope: /code/scatter (scanned 11 projects, 38 files)
Filter: 11 → 7 project refs[graph] → 6 namespace → 6 class match

--- Combined Consumer Analysis Report ---

--- Consuming Relationships Found ---

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (6 consumer(s))
    Type/Level: PortalDataService (via Sproc: dbo.sp_InsertPortalConfiguration)
         -> Consumed by: GalaxyWorks.Api (GalaxyWorks.Api/GalaxyWorks.Api.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=7.1, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=10.8, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=12.7, fan-in=1, fan-out=1, instability=0.500, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp (MyGalaxyConsumerApp/MyGalaryConsumerApp.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=4.3, fan-in=0, fan-out=2, instability=1.000, in-cycle=no
         -> Consumed by: MyGalaryConsumerApp2 (MyGalaxyConsumerApp2/MyGalaryConsumerApp2.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=1.8, fan-in=0, fan-out=1, instability=1.000, in-cycle=no
         -> Consumed by: GalaxyWorks.Data.Tests (GalaxyWorks.Data.Tests/GalaxyWorks.Data.Tests.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=3.5, fan-in=0, fan-out=2, instability=1.000, in-cycle=no

Target: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj) (1 consumer(s))
    Type/Level: PortalCacheService (via Sproc: dbo.sp_InsertPortalConfiguration)
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)
           Solutions: GalaxyWorks.sln
           Graph: coupling=10.8, fan-in=0, fan-out=2, instability=1.000, in-cycle=no

--- Total Consuming Relationships Found: 7 ---

Analysis complete. 7 consumer(s) found across 2 target(s).
```

Notice the multi-hop chain: the sproc is referenced by `PortalDataService` in GalaxyWorks.Data (6 consumers) and `PortalCacheService` in GalaxyWorks.WebPortal (1 consumer). The `(via Sproc: dbo.sp_InsertPortalConfiguration)` annotation preserves the provenance so readers understand why these consumers were flagged.

## Different Stored Procedure

```bash
scatter --stored-procedure "dbo.sp_GetPortalConfigurationDetails" --search-scope .
```

Same flow, different sproc. If multiple classes in multiple projects reference this sproc, Scatter reports all of them and traces their consumers independently.

## Filter by Class

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . --class-name PortalDataService
```

When the sproc is referenced from multiple classes (maybe a test helper also calls it), filter to only the class you care about. The `--class-name` filter is applied before consumer analysis, so it narrows the search early.

## Custom Regex Pattern

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . --sproc-regex-pattern "EXECUTE\s+{sproc_name_placeholder}"
```

The default regex matches quoted sproc names -- the common ADO.NET and Dapper pattern. If your codebase uses raw SQL strings with `EXECUTE` or a custom invocation pattern, provide a custom regex. The `{sproc_name_placeholder}` token gets replaced with the escaped sproc name.

## Export for the DBA Team

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . --output-format csv --output-file sproc_impact.csv
```

CSV is the lingua franca of cross-team communication. Hand this to your DBA and they can see exactly which applications need coordination before modifying the sproc.

## With Pipeline Mapping

```bash
scatter --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . --pipeline-csv build/pipeline_map.csv \
  --output-format csv --output-file sproc_impact.csv
```

When combined with `--pipeline-csv`, each consumer row includes the CI/CD pipeline name. This answers the deployment question: "if we change this sproc, which pipelines need to be redeployed, and in what order?"

## Output Formats

JSON, CSV, and Markdown all work the same as in other modes. The JSON output includes the triggering info formatted as `PortalDataService (via Sproc: dbo.sp_InsertPortalConfiguration)` so you can trace the full chain programmatically. See [Output Formats](../output-formats.md) for detailed structure.

---

!!! info "How this works"
    Scatter scans `.cs` files for the sproc name in string literals, maps each match to its parent `.csproj` and enclosing class, then runs the standard consumer detection pipeline for each class. See [Consumer Detection Pipeline](../reference/consumer-pipeline.md) for details.
