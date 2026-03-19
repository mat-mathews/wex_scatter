# Sample Projects

The 11 included .NET projects serve as a validation reference and integration test fixture. Moved here from the User Guide per Sam's feedback -- this is reference material, not a getting-started topic.

---

## Dependency Tree

```
GalaxyWorks.Data (SDK, net8.0, Library, no deps)
 |  Types: PortalDataService, EntityModels, IDataAccessor, FakeDatabaseHelper,
 |         FakeDbCommand, FakeDbParameter
 |  Sprocs: "dbo.sp_InsertPortalConfiguration", "dbo.sp_GetPortalSettings"
 |
 +-- GalaxyWorks.WebPortal (Framework, v4.7.2, Library, refs Data)
 |    |  Types: PortalController, BaseController, AdminApiController,
 |    |         PortalViewModels, ConfigHelper, PortalCacheService
 |    |
 |    +-- GalaxyWorks.BatchProcessor (Framework, v4.7.2, Exe, refs Data + WebPortal)
 |         Types: SyncJob, ReportJob, AppDbContext
 |
 +-- GalaxyWorks.Common (SDK, net48+net8.0, Library, refs Data)
 |    |  Types: Records, CommonNames, StringExtensions,
 |    |         ServiceCollectionExtensions, DomainEvents, InternalTypes
 |    |
 |    +-- GalaxyWorks.Api (SDK Web, net8.0, Web, refs Data + Common)
 |    |    Types: PortalApiController, OrdersController, ConfigurationService, Program
 |    |
 |    +-- GalaxyWorks.Data.Tests (SDK, net8.0, Test, refs Data + Common)
 |    |    Types: PortalDataServiceTests, InternalTypeTests
 |    |
 |    +-- MyGalaxyConsumerApp (SDK, net8.0, Exe, refs Data + Common)
 |         Types: Project, GlobalUsings, OrderConsumer
 |
 +-- MyGalaxyConsumerApp2 (SDK, net8.0, Exe, refs Data)
      Types: Project

MyDotNetApp (SDK, net8.0, Exe, independent)
 |  Types: Person, DataService, IDataService, Program
 |
 +-- MyDotNetApp.Consumer (SDK, net8.0, Exe, refs MyDotNetApp)
      Types: Program, ReportGenerator

MyDotNetApp2.Exclude (SDK, net8.0, Exe, standalone, no refs)
   Types: ReportGenerator, Program
```

### Notes on the Tree

- **GalaxyWorks.Data** is the hub. Everything in the GalaxyWorks cluster depends on it.
- **GalaxyWorks.BatchProcessor** has the highest instability (1.0) -- it depends on two projects and nothing depends on it.
- **GalaxyWorks.WebPortal** uses legacy framework-style `.csproj` (with `<ToolsVersion>` and `<ProjectGuid>`). BatchProcessor does too. This validates that Scatter handles both SDK and legacy formats.
- **GalaxyWorks.Common** multi-targets `net48` and `net8.0`. Scatter extracts the first framework.
- **MyDotNetApp** is completely independent from the GalaxyWorks cluster. They form separate connected components in the graph.
- **MyDotNetApp2.Exclude** is an island -- no incoming or outgoing project references. It exists specifically to test that Scatter correctly reports 0 consumers.

---

## Expected Values Table

These are the ground-truth results you should see when running Scatter against the repo root. If your changes break any of these, something is wrong.

| Scenario | Command | Expected |
|----------|---------|----------|
| GalaxyWorks.Data consumers | `--target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .` | 6 consumers: WebPortal, BatchProcessor, Common, Api, Data.Tests, MyGalaxyConsumerApp, MyGalaxyConsumerApp2 (7 with transitive) |
| GalaxyWorks.Data + class filter | `--target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . --class-name PortalDataService` | Consumers filtered to those referencing `PortalDataService` |
| GalaxyWorks.WebPortal consumers | `--target-project ./GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj --search-scope .` | 1 consumer: BatchProcessor |
| MyDotNetApp consumers | `--target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .` | 1 consumer: MyDotNetApp.Consumer |
| MyDotNetApp2.Exclude consumers | `--target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .` | 0 consumers |
| Sproc analysis | `--stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .` | Finds PortalDataService in GalaxyWorks.Data, then its consumers |
| Graph mode | `--graph --search-scope .` | 11 projects, multiple connected components, 0 cycles |

---

## Key Metrics (Graph Mode)

When you run `--graph --search-scope .`, Scatter computes coupling metrics for every project. Here are the notable values:

### GalaxyWorks.Data

- **fan_in**: 7 (everything in the cluster references it)
- **fan_out**: 0 (depends on nothing)
- **instability**: 0.0 (perfectly stable -- the foundation)
- **coupling_score**: ~8.6 (high, due to fan_in)

This is what a core library looks like. High fan-in, zero fan-out, zero instability. Changing GalaxyWorks.Data has maximum blast radius.

### GalaxyWorks.BatchProcessor

- **fan_in**: 0 (nothing depends on it)
- **fan_out**: 2 (depends on Data + WebPortal)
- **instability**: 1.0 (maximally unstable -- all dependencies, no dependents)

A leaf node. Safe to change -- nothing downstream breaks.

### MyDotNetApp Cluster

The MyDotNetApp and MyDotNetApp.Consumer form a small independent cluster. Feasibility scoring rates this as "easy" (1.000) for extraction -- it's already isolated from the GalaxyWorks ecosystem.

### Connected Components

The graph has at least 3 connected components:
1. The GalaxyWorks cluster (Data, WebPortal, BatchProcessor, Common, Api, Data.Tests, MyGalaxyConsumerApp, MyGalaxyConsumerApp2)
2. The MyDotNetApp cluster (MyDotNetApp, MyDotNetApp.Consumer)
3. MyDotNetApp2.Exclude (island)

### Cycles

Zero. The sample projects form a clean DAG. If you're testing cycle detection, you'll need to create a fixture with circular references (see `test_coupling.py` for examples).

---

## Project Style Inventory

The sample projects deliberately mix .NET project styles to validate Scatter's parser:

| Style | Projects | Characteristics |
|-------|----------|----------------|
| SDK-style | GalaxyWorks.Data, Common, Api, Data.Tests, MyGalaxyConsumerApp, MyGalaxyConsumerApp2, MyDotNetApp, MyDotNetApp.Consumer, MyDotNetApp2.Exclude | `<Project Sdk="...">`, compact XML, `<TargetFramework>` |
| Framework-style | GalaxyWorks.WebPortal, GalaxyWorks.BatchProcessor | `<ToolsVersion>`, `<ProjectGuid>`, `<TargetFrameworkVersion>`, explicit `<Compile Include>`, verbose XML |

This matters because the `.csproj` parser in `scatter/scanners/project_scanner.py` handles both formats. SDK-style uses `<TargetFramework>`, framework-style uses `<TargetFrameworkVersion>` with a `v` prefix. The parser normalizes both.

---

## Using Samples in Tests

```python
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def test_graph_against_samples():
    from scatter.analyzers.graph_builder import build_dependency_graph
    graph = build_dependency_graph(
        REPO_ROOT,
        disable_multiprocessing=True,
        exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
    )
    # 11 projects
    assert graph.node_count == 11

    # GalaxyWorks.Data has the most dependents
    data_edges = graph.get_edges_to("GalaxyWorks.Data")
    assert len(data_edges) >= 6
```

The `exclude_patterns` parameter filters out `bin/`, `obj/`, and `temp_test_data/` directories. Always include it when running against the repo root -- otherwise you'll pick up build artifacts.
