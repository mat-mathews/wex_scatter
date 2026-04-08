# Sample Project Evaluation

Principal engineer assessment of whether the Galaxy sample projects cover the C# patterns Scatter would encounter in an enterprise .NET monolith.

---

## What the samples cover well

The 8 sample projects do a solid job of representing the **core dependency patterns** that Scatter's analysis pipeline needs to trace:

| Pattern | Where | Scatter relevance |
|---------|-------|-------------------|
| SDK-style .csproj | GalaxyWorks.Data, MyDotNetApp, consumers | ProjectReference parsing |
| Framework-style .csproj (MSBuild XML namespace) | WebPortal, BatchProcessor | Legacy XML parsing path |
| ProjectReference chains (A → B → C) | BatchProcessor → WebPortal → Data | Transitive tracing |
| Interface + implementation | IDataAccessor / PortalDataService | Type extraction |
| Abstract + sealed classes | BaseController, AdminApiController, ReportJob | Keyword handling in regex |
| Partial classes (split across files) | PortalCacheService + .DataAccess.cs | Type appears in multiple files |
| Static classes | ConfigHelper | `static` keyword before `class` |
| Nested generic types | CacheEntry\<T\> inside PortalCacheService | Nested type extraction |
| Multiple types per file | EntityModels.cs (enum + 3 classes) | Multi-type file handling |
| Enum declarations | StatusType | Type keyword coverage |
| Stored proc calls (ADO.NET style) | PortalDataService with parameters | Sproc detection |
| Stored proc calls (EF style) | PortalCacheService.DataAccess, SyncJob, ReportJob | EF sproc patterns |
| DbContext / DbSet\<T\> | AppDbContext | DB scanner detection |
| Async/await methods | Throughout | Not directly relevant, but realistic |
| Data annotations | PortalViewModels | Attribute-decorated types |
| Constructor-based DI | Controllers, SyncJob | Consumer pattern (type usage) |
| Cross-project namespace usage | `using GalaxyWorks.Data.DataServices` | Namespace filter stage |
| Standalone project (no consumers) | MyDotNetApp2.Exclude | Zero-result test case |

The dependency graph shape is well-designed: a core library (Data) with fan-out to 4 consumers, a mid-tier library (WebPortal) with 1 consumer (BatchProcessor), an independent chain (MyDotNetApp → Consumer), and an isolated project (Exclude). This exercises all graph traversal paths.

---

## What's missing: patterns that would break or blind Scatter

### Critical gaps (would cause Scatter to miss real dependencies or produce wrong results)

**1. C# records**

Records are the most common modern C# type declaration and Scatter's regex will miss them entirely.

```csharp
// Scatter's regex matches: class, struct, interface, enum
// It does NOT match: record

public record PersonDto(string Name, int Age);                    // positional record
public record class OrderSummary { public int Id { get; init; } } // explicit record class
public record struct Point(double X, double Y);                   // record struct
```

The type extraction regex requires `(?:class|struct|interface|enum)` — records don't contain any of these keywords in the positional syntax. `record class` and `record struct` would partially match (the `class`/`struct` is present), but positional records like `public record PersonDto(...)` are invisible.

In a modern .NET 6+ codebase, records are used heavily for DTOs, API contracts, events, and value objects. Missing them means Scatter would fail to detect consumers of those types.

**Impact**: High. Any codebase targeting .NET 6+ will have records. Scatter silently misses them.

**2. File-scoped namespaces**

```csharp
// All samples use block-scoped namespaces:
namespace GalaxyWorks.Data.DataServices
{
    public class PortalDataService { ... }
}

// Modern C# 10+ code uses file-scoped:
namespace GalaxyWorks.Data.DataServices;

public class PortalDataService { ... }
```

Scatter's `using` statement detection and namespace derivation should still work (it scans for `using Namespace;` lines). But this should be tested — there might be edge cases in how the scanner extracts the root namespace from a file if it expects a `{ }` block.

**Impact**: Medium. Probably works but is untested. A single file-scoped namespace sample would prove it.

**3. Type name collisions**

The samples use distinctive names (`PortalDataService`, `PortalConfiguration`) that don't collide across projects. Enterprise codebases are full of generic names:

```
ProjectA/Models/Result.cs       → public class Result { }
ProjectB/Models/Result.cs       → public class Result { }
ProjectC/Common/Result.cs       → public class Result { }
```

Scatter does a text-based search for type names. If `ProjectA` declares `Result` and `ProjectB` also contains the word `Result`, Scatter will report a false dependency. There are no samples testing how Scatter handles type name ambiguity, and the current pipeline has no namespace-qualified type matching.

**Impact**: High for real codebases. Common type names like `Result`, `Response`, `Request`, `Options`, `Context`, `Service`, `Helper`, `Manager`, `Handler`, `Model`, `Entity`, `Config` will generate false positives. This is the #1 accuracy risk in production use.

**4. NuGet PackageReference dependencies**

All samples use only `<ProjectReference>`. Real projects also have:

```xml
<PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
<PackageReference Include="MediatR" Version="12.0.0" />
```

Scatter correctly ignores PackageReferences (it only traces ProjectReferences), but this should be explicitly tested. A project with both ProjectReferences and PackageReferences would verify Scatter doesn't confuse them, especially in Framework-style .csproj where NuGet references appear as `<Reference>` with `<HintPath>` pointing to a `packages/` folder.

**Impact**: Low (Scatter correctly ignores these), but a sample would confirm no false positives.

**5. Extension methods**

Extension methods are one of the most common coupling vectors in enterprise .NET:

```csharp
// In ProjectA:
namespace ProjectA.Extensions;
public static class StringExtensions
{
    public static string Truncate(this string s, int maxLength) => ...;
}

// In ProjectB:
using ProjectA.Extensions;
"hello world".Truncate(5);  // No explicit reference to StringExtensions
```

The consumer (`ProjectB`) never writes the type name `StringExtensions` — it calls `"hello".Truncate()` which looks like a method on `string`. Scatter's type-usage detection (text search for `StringExtensions`) would miss this. The namespace import would still catch it at the namespace filter level, but the class-level filter would fail.

**Impact**: Medium. Namespace-level detection still works, but `--class-name StringExtensions` would miss consumers that only call the extension methods.

**6. Global usings and implicit usings**

Modern .NET 6+ projects with `<ImplicitUsings>enable</ImplicitUsings>` get automatic `using System;`, `using System.Linq;`, etc. More importantly, projects can define global usings:

```csharp
// GlobalUsings.cs (or anywhere)
global using GalaxyWorks.Data.DataServices;
global using GalaxyWorks.Data.Models;
```

This means a consumer file can use `PortalDataService` without any `using` statement in that file. Scatter's namespace filter stage scans individual `.cs` files for `using TargetNamespace;` — if the using is in a global usings file, the consumer files themselves won't have the `using` line and could be filtered out.

**Impact**: High for .NET 6+ codebases. The namespace filter stage could reject legitimate consumers.

**7. `using` aliases and static usings**

```csharp
using DataSvc = GalaxyWorks.Data.DataServices.PortalDataService;
using static GalaxyWorks.Data.Models.StatusType;

// Then later:
var svc = new DataSvc();           // Scatter won't see "PortalDataService"
var status = Active;                // Scatter won't see "StatusType"
```

Type aliasing and static imports make the actual type name invisible at the usage site. The `using` line still references the namespace, so namespace-level detection works, but type-level detection would miss the alias.

**Impact**: Low-medium. Aliases are uncommon in practice; static usings for enums are more common.

### Moderate gaps (would affect analysis quality but not core functionality)

**8. No ASP.NET Core project**

All web projects are .NET Framework MVC (System.Web.Mvc). Modern enterprise codebases are migrating to ASP.NET Core with completely different patterns:

- `ControllerBase` instead of `Controller`
- `[ApiController]` attribute
- `IServiceCollection` DI registration (Scatter can't trace DI bindings)
- Minimal APIs: `app.MapGet("/api/users", () => ...)` (no controller class at all)
- `IOptions<T>` configuration binding
- Middleware pipeline: `app.UseMiddleware<ExceptionMiddleware>()`

The WebPortal project uses .NET Framework MVC, which is realistic for a legacy monolith, but doesn't test Scatter's ability to handle .NET Core patterns. Since many monoliths are partially migrated, you'd typically see both in the same solution.

**9. No test project**

Enterprise solutions always have test projects (xUnit, NUnit, MSTest). Test projects reference the project under test via ProjectReference and use its types. They're typically excluded from blast radius analysis but Scatter should handle them correctly (either include or filter them via exclude patterns).

A `GalaxyWorks.Data.Tests` project would verify this scenario and test that `--class-name PortalDataService` correctly shows test projects as consumers (or that they can be excluded).

**10. No multi-targeting**

```xml
<TargetFrameworks>net48;net8.0</TargetFrameworks>
```

Multi-targeted projects are common during migration. The .csproj structure changes (`TargetFrameworks` plural vs `TargetFramework` singular). Scatter's project scanner should handle both — the samples only test the singular form.

**11. No conditional compilation**

```csharp
#if NET48
    using System.Web.Mvc;
#else
    using Microsoft.AspNetCore.Mvc;
#endif
```

Scatter scans raw text, so it would pick up both `using` lines regardless of the active target framework. This could produce false dependencies for the inactive branch.

**12. No solution file (.sln)**

The `ConsumingSolutions` field in reports is populated from solution files, but there's no `.sln` in the sample projects. This means that code path is never tested against the samples.

**13. No InternalsVisibleTo**

```csharp
[assembly: InternalsVisibleTo("GalaxyWorks.Data.Tests")]
```

This attribute creates a dependency that Scatter doesn't detect. An `internal class` in Project A is used by Project B through `InternalsVisibleTo` — Scatter would miss this since it only traces `public`/`protected` types (and `internal` types wouldn't normally be accessible).

**14. No event/delegate patterns**

```csharp
public class OrderProcessor
{
    public event EventHandler<OrderEventArgs> OrderCompleted;
}
```

Events create coupling through subscription — `processor.OrderCompleted += OnOrderCompleted;`. Scatter's text search would find `OrderProcessor` usage but wouldn't trace the event coupling vector specifically. This matters for coupling narratives.

---

## What the samples get right that other sample suites often miss

Credit where due — several design choices in the samples are excellent for testing:

1. **Mixed SDK and Framework .csproj styles** — tests both XML parsing paths
2. **Partial class split across files** — PortalCacheService verifies type appears in both files
3. **Multiple types in one file** — EntityModels.cs with 4 types
4. **The standalone/exclude project** — MyDotNetApp2.Exclude is essential for testing zero-result accuracy
5. **Sproc calls via both ADO.NET and EF patterns** — tests both detection paths
6. **Realistic depth** — Data → WebPortal → BatchProcessor gives a 3-level chain for transitive tracing
7. **Intentionally wrong namespace** in MyDotNetApp2.Exclude (uses `MyDotNetApp.Consumer.Helpers`) — tests namespace collision handling

---

## Recommendations

### Must-add (would catch real bugs in Scatter)

| Priority | Sample to add | What it tests |
|----------|---------------|---------------|
| **1** | Add `record` declarations to GalaxyWorks.Data models | Verifies type regex catches records — currently broken |
| **2** | Add a project with common type names (`Result`, `Response`, `Options`) | Tests false positive rate from type name collisions |
| **3** | Add `global using` to one SDK-style project | Tests namespace filter with global usings |
| **4** | Add file-scoped namespace to at least one .cs file | Tests scanner handles `namespace Foo;` syntax |
| **5** | Add a multi-targeted project (`net48;net8.0`) | Tests .csproj parsing of `<TargetFrameworks>` plural |

### Should-add (improves coverage of real-world patterns)

| Priority | Sample to add | What it tests |
|----------|---------------|---------------|
| **6** | Add a `.sln` solution file grouping the Galaxy projects | Tests ConsumingSolutions report field |
| **7** | Add extension methods in GalaxyWorks.Data consumed by WebPortal | Tests class-level filter with extension method usage |
| **8** | Add an ASP.NET Core Web API project (ControllerBase) | Tests .NET Core patterns alongside Framework |
| **9** | Add a test project (xUnit) for GalaxyWorks.Data | Tests test project handling / exclusion |
| **10** | Add `using` alias and `using static` in a consumer | Tests type-level detection with aliased types |

### Nice-to-have

| Priority | Sample to add | What it tests |
|----------|---------------|---------------|
| 11 | Add `InternalsVisibleTo` between two projects | Documents a known blind spot |
| 12 | Add conditional compilation (`#if`) with different usings | Tests false positive from inactive code paths |
| 13 | Add event/delegate declarations and subscriptions | Tests coupling vector detection |
| 14 | Add PackageReference alongside ProjectReference | Verifies Scatter ignores NuGet correctly |

---

## Impact on Scatter's detection accuracy

Based on this evaluation, against a real enterprise .NET 6+ codebase:

| Detection stage | Estimated accuracy | Primary risk |
|-----------------|-------------------|--------------|
| .csproj discovery | ~99% | Multi-targeted `<TargetFrameworks>` parsing untested |
| ProjectReference extraction | ~98% | Framework-style with MSBuild namespace edge cases |
| Namespace filter | ~90% | Global usings bypass per-file `using` detection |
| Type extraction | ~85% | Records missing, generic constraints can confuse regex |
| Type usage (text search) | ~75% | Common name collisions produce false positives |
| Sproc detection | ~95% | Well covered by both ADO.NET and EF patterns |
| DB dependency detection | ~90% | EF Core patterns (`IQueryable`, `Include()`) differ from EF6 |

The **type usage text search** at ~75% is the weakest link. In a codebase with 500 projects, a type named `Result` declared in one project would match text in dozens of unrelated projects. This is the strongest argument for the planned Roslyn-based semantic analysis (mentioned in the product definition Section 7.2).
