// GalaxyWorks.DevTools — Internal developer tooling
//
// This project references GalaxyWorks.Data for model types (PortalConfiguration,
// StatusType) but does NOT use PortalDataService at runtime. All mentions of
// PortalDataService in this project are in comments, strings, or documentation
// templates.
//
// This makes it a false positive for Scatter's regex-based class filter:
// regex \bPortalDataService\b matches, but the type is never instantiated,
// called, or referenced in executable code.

using GalaxyWorks.DevTools.Generators;
using GalaxyWorks.DevTools.Diagnostics;

var generator = new DocGenerator();
Console.WriteLine(generator.GenerateServiceCatalog());

var exporter = new SchemaExporter();
exporter.ExportSchema("/tmp/schema.sql");

var checker = new DependencyChecker();
var issues = checker.RunChecks();
if (issues.Count > 0)
{
    Console.WriteLine($"Found {issues.Count} issue(s):");
    foreach (var issue in issues)
    {
        Console.WriteLine($"  - {issue}");
    }
}
