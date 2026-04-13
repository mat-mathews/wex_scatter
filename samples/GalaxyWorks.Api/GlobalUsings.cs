// Tests: Global usings — these apply to ALL .cs files in this project.
// Consumer files can use PortalDataService, PersonDto, etc. without
// a per-file `using` statement. Scatter's namespace filter scans individual
// files for `using TargetNamespace;` — if the using is here instead,
// the consumer files themselves won't have the `using` line.

global using GalaxyWorks.Data.DataServices;
global using GalaxyWorks.Data.Models;
global using GalaxyWorks.Common.Models;
global using GalaxyWorks.Common.Extensions;
