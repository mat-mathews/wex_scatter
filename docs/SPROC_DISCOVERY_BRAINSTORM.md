# Stored Procedure Discovery Brainstorm

**Date:** 2026-04-06
**Context:** WEX monolith is very sproc-heavy — potentially thousands of stored procedures. Current Scatter requires a specific sproc name via `--stored-procedure`. This doc explores how to automatically discover all sproc references from C# source files without database access.

---

## Why this matters at scale

When a codebase has thousands of stored procedures, the current approach ("tell me about this one sproc") doesn't scale. The value shifts to:

1. **Sproc inventory** — a complete map of every sproc referenced in C# code, built automatically
2. **Shared sproc detection** — which sprocs are referenced by 3+ projects? Those are coupling hotspots
3. **Graph edges** — sproc-based coupling added to the dependency graph without manual input
4. **SOW matching** — when analyzing a work request, cross-reference business concepts against the sproc inventory to find hidden database coupling

With thousands of sprocs, just knowing "this project calls stored procedures" is not useful — every project does. You need the actual names to find the shared ones.

---

## Detection strategies

### Tier 1 — Unambiguous signals (zero/near-zero false positives)

**`CommandType.StoredProcedure` + name extraction**

The strongest signal in .NET. When `CommandType.StoredProcedure` is set, the associated `CommandText` is definitionally a sproc name. Appears in two major patterns:

```csharp
// ADO.NET
cmd.CommandType = CommandType.StoredProcedure;
cmd.CommandText = "dbo.usp_GetUser";

// Dapper
connection.Query<User>("dbo.usp_GetUser", params, commandType: CommandType.StoredProcedure);
connection.Execute("dbo.usp_GetUser", params, commandType: CommandType.StoredProcedure);
```

Challenge: `CommandType` and `CommandText` may be 5-15 lines apart. Need a method-scoped window, not line-by-line matching. For Dapper, the sproc name is the first positional argument — easier to extract.

**`.sql` files with `CREATE PROCEDURE` / `ALTER PROCEDURE`**

If the repo contains SQL migration files or sproc definition scripts, these are the authoritative catalog of what exists. Regex: `CREATE\s+(OR\s+ALTER\s+)?PROC(EDURE)?\s+(\[?\w+\]?\.?\[?\w+\]?)`. Cross-reference with C# references to find:
- Sprocs defined but never referenced in C# (dead code or called from SSRS/other non-.NET consumers)
- Sprocs referenced in C# but not defined in repo (defined elsewhere or dynamically created)

Both are worth surfacing.

**EF migration `CREATE PROCEDURE` statements**

```csharp
migrationBuilder.Sql("CREATE PROCEDURE dbo.usp_GetUser ...");
```

Sproc definitions embedded in C# migration files. Same regex as `.sql` files, applied to string literals in migration classes.

### Tier 2 — High confidence (low false positive rate)

**`EXEC` / `EXECUTE` in string literals**

SQL keywords in C# strings are almost always sproc invocations or dynamic SQL. Regex for string literals containing `EXEC\s+(\[?\w+\]?\.?\[?\w+\]?)`. Handle bracketed names (`[dbo].[usp_GetUser]`) and schema-qualified names.

Common in EF patterns:
```csharp
Database.SqlQuery<User>("exec dbo.usp_GetUser @p1", param);
Database.ExecuteSqlCommand("exec dbo.usp_UpdateUser @p1, @p2", params);
```

**`MapToStoredProcedures()` in EF6 fluent config**

```csharp
modelBuilder.Entity<User>()
    .MapToStoredProcedures(s => s
        .Insert(i => i.HasName("usp_InsertUser"))
        .Update(u => u.HasName("usp_UpdateUser"))
        .Delete(d => d.HasName("usp_DeleteUser"))
    );
```

Dead giveaway that entity CRUD maps to sprocs. Names inside `HasName()` calls.

**`FromSqlRaw` / `ExecuteSqlRaw` / `ExecuteSqlInterpolated` (EF Core)**

```csharp
context.Users.FromSqlRaw("EXEC dbo.usp_GetUser {0}", userId);
context.Database.ExecuteSqlRaw("EXEC dbo.usp_UpdateUser @p0", param);
```

The string argument may be a sproc call or inline SQL. Check for `EXEC` prefix or bare name (which EF treats as a sproc).

### Tier 3 — Medium confidence (needs heuristics)

**Sproc name constants in dedicated classes**

Enterprise .NET codebases often centralize sproc names:
```csharp
public static class StoredProcedures
{
    public const string GetUser = "dbo.usp_GetUser";
    public const string UpdateUser = "dbo.usp_UpdateUser";
}
```

Heuristic: class names matching `*Sproc*`, `*Procedure*`, `*SqlConstants*`, `*DataAccess*Constants*` — extract all `const string` and `static readonly string` values. False positive risk from non-sproc constants in the same class.

**Custom attributes**

```csharp
[StoredProcedure("dbo.usp_GetUser")]
public User GetUser(int userId) { ... }
```

Framework-specific convention. Grep for attribute names containing "StoredProcedure", "Sproc", "Procedure". Low effort, low risk, but only present in codebases that use this pattern.

**Configuration files**

Sproc names in `appsettings.json`, `web.config`, or custom XML:
```json
{ "Procedures": { "GetUser": "dbo.usp_GetUser" } }
```
```xml
<add key="GetUserProcedure" value="dbo.usp_GetUser" />
```

Requires scanning non-`.cs` files. Keys containing "proc", "sproc", "procedure" are candidates.

### Two-pass gateway detection

In mature codebases, direct `SqlCommand` usage is often wrapped:

```csharp
// Base class (one file)
protected T ExecuteStoredProc<T>(string procedureName, params SqlParameter[] parameters)
{
    cmd.CommandType = CommandType.StoredProcedure;
    cmd.CommandText = procedureName;
    // ...
}

// Callers (many files)
var user = ExecuteStoredProc<User>("dbo.usp_GetUser", new SqlParameter("@id", userId));
```

`CommandType.StoredProcedure` appears in one file (the base class). The sproc names appear in every caller. Detection:

1. Find files containing `CommandType.StoredProcedure`
2. Identify public/protected method signatures that accept a string parameter (the sproc name)
3. Find all call sites of those methods across the codebase
4. Extract the string argument at each call site

Higher effort but critical for codebases with a shared data access layer — which is exactly what a 20-year monolith is likely to have.

---

## Scale considerations (thousands of sprocs)

When the sproc count is in the thousands:

- **Name extraction is mandatory.** "This project calls sprocs" tells you nothing when every project does. You need actual sproc names to identify shared coupling.
- **The sproc inventory becomes a first-class artifact.** A map of `{sproc_name: [project1, project2, ...]}` is something nobody at the company has today. Surface it in graph mode.
- **Shared sprocs are the signal.** A sproc called by 1 project is normal. A sproc called by 5 projects is a coupling hotspot. Rank by reference count.
- **Two-pass gateway detection is likely critical.** A 20-year monolith almost certainly has a shared data access layer. Most sproc names will be at the call sites, not next to `CommandType.StoredProcedure`.
- **Performance matters.** Scanning thousands of `.cs` files for string patterns is I/O bound. The sproc discovery pass should use the same parallel file scanning infrastructure as consumer detection.
- **The SQL catalog (`.sql` files) becomes the ground truth.** If the repo has sproc definitions, cross-referencing gives you completeness metrics: "347 of 412 known sprocs are referenced in C# code."

---

## Implementation priority

| Phase | Strategy | Value at scale | Effort |
|-------|----------|---------------|--------|
| 1 | `.sql` file catalog (`CREATE PROCEDURE`) | Ground truth sproc list | Low |
| 1 | `EXEC`/`EXECUTE` in string literals | Direct name extraction | Low |
| 1 | `CommandType.StoredProcedure` ± window scan | Anchor signal + names | Medium |
| 1 | Sproc inventory as graph edges | Automatic shared coupling | Medium |
| 2 | Two-pass gateway detection | Catches abstracted calls | High |
| 2 | `MapToStoredProcedures` / EF patterns | EF-specific coverage | Medium |
| 2 | Constant class heuristics | Centralized name stores | Low |
| 3 | Config file scanning | Edge cases | Low |
| 3 | Custom attribute detection | Framework-specific | Low |
| 3 | EF migration scanning | Sproc definitions in C# | Low |

**Recommended approach:** Ship phase 1, run against the WEX monolith, measure coverage (how many known sprocs did we find?). Let the coverage gap tell you which phase 2 strategies to prioritize.

---

## Output: what the sproc inventory enables

Once the inventory exists, Scatter can:

1. **`--graph` mode:** add sproc edges automatically, surface "shared by N projects" in observations
2. **`--target-project` mode:** show which sprocs the target exposes and which consumers call them
3. **`--sow` mode:** match SOW text against sproc names and their containing classes for better target identification
4. **New: `--sproc-inventory` mode:** dump the full sproc map — every sproc, every project that references it, reference count, sorted by sharing degree
5. **PR risk:** if a branch modifies a file that references shared sprocs, flag the database coupling dimension automatically
