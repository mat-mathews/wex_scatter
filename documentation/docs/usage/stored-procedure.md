# Stored Procedure Analysis

Your DBA is changing a stored procedure. Which C# services are about to break?

This is the question nobody can answer quickly, because sproc callers are invisible in the project reference graph. No `<ProjectReference>` points at a stored procedure. The coupling lives inside `.cs` files as string literals -- `"dbo.sp_InsertPortalConfiguration"` buried in a data access layer somewhere. Your DBA changes a parameter list and has no idea which services just broke.

Scatter makes that invisible coupling visible. Give it a sproc name, and it traces the full chain: sproc to containing class to consumer projects.

## Basic Example

```bash
python scatter.py \
  --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope .
```

```
--- Running Stored Procedure Analysis Mode ---
Identifying projects/classes referencing stored procedure: 'dbo.sp_InsertPortalConfiguration' within scope '.'
Scanning 42 C# files in '.' for references to sproc 'dbo.sp_InsertPortalConfiguration'.
Found 1 C# file(s) with potential sproc references. Mapped references to 1 unique class(es) across 1 project(s).

--- Analyzing Consumers for Class 1/1: 'PortalDataService' in Project: GalaxyWorks.Data ---

--- Combined Consumer Analysis Report ---

--- Consuming Relationships Found ---

Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj) (4 consumer(s))
    Type/Level: PortalDataService (via Sproc: dbo.sp_InsertPortalConfiguration)
         -> Consumed by: GalaxyWorks.WebPortal (GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj)
         -> Consumed by: GalaxyWorks.BatchProcessor (GalaxyWorks.BatchProcessor/GalaxyWorks.BatchProcessor.csproj)
         -> Consumed by: MyGalaryConsumerApp (MyGalaxyConsumerApp/MyGalaryConsumerApp.csproj)
         -> Consumed by: MyGalaryConsumerApp2 (MyGalaxyConsumerApp2/MyGalaryConsumerApp2.csproj)

--- Total Consuming Relationships Found: 4 ---

Analysis complete. 4 consumer(s) found across 1 target(s).
```

Notice the two-hop chain in the output: the sproc lives in `PortalDataService`, and four projects consume that class. The `(via Sproc: dbo.sp_InsertPortalConfiguration)` annotation preserves the provenance so readers understand why these consumers were flagged.

## Different Stored Procedure

```bash
python scatter.py \
  --stored-procedure "dbo.sp_GetPortalConfigurationDetails" \
  --search-scope .
```

Same flow, different sproc. If multiple classes in multiple projects reference this sproc, Scatter reports all of them and traces their consumers independently.

## Filter by Class

```bash
python scatter.py \
  --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . \
  --class-name PortalDataService
```

When the sproc is referenced from multiple classes (maybe a test helper also calls it), filter to only the class you care about. The `--class-name` filter is applied before consumer analysis, so it narrows the search early.

## Custom Regex Pattern

```bash
python scatter.py \
  --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . \
  --sproc-regex-pattern "EXECUTE\s+{sproc_name_placeholder}"
```

The default regex matches quoted sproc names -- the common ADO.NET and Dapper pattern. If your codebase uses raw SQL strings with `EXECUTE` or a custom invocation pattern, provide a custom regex. The `{sproc_name_placeholder}` token gets replaced with the escaped sproc name.

## Export for the DBA Team

```bash
python scatter.py \
  --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . \
  --output-format csv \
  --output-file sproc_impact.csv
```

CSV is the lingua franca of cross-team communication. Hand this to your DBA and they can see exactly which applications need coordination before modifying the sproc.

## With Pipeline Mapping

```bash
python scatter.py \
  --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope . \
  --pipeline-csv build/pipeline_map.csv \
  --output-format csv \
  --output-file sproc_impact.csv
```

When combined with `--pipeline-csv`, each consumer row includes the CI/CD pipeline name. This answers the deployment question: "if we change this sproc, which pipelines need to be redeployed, and in what order?"

## Output Formats

JSON, CSV, and Markdown all work the same as in other modes. The JSON output includes the triggering info formatted as `PortalDataService (via Sproc: dbo.sp_InsertPortalConfiguration)` so you can trace the full chain programmatically. See [Output Formats](../output-formats.md) for detailed structure.

---

!!! info "How this works"
    Scatter scans `.cs` files for the sproc name in string literals, maps each match to its parent `.csproj` and enclosing class, then runs the standard consumer detection pipeline for each class. See [Consumer Detection Pipeline](../reference/consumer-pipeline.md) for details.
