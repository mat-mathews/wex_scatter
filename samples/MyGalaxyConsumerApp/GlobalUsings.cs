// Tests: Global usings — these apply to all .cs files in this project.
// Scatter's per-file namespace filter won't find `using GalaxyWorks.Common.*`
// in consumer .cs files because the imports are here instead.

global using GalaxyWorks.Common.Models;
global using GalaxyWorks.Common.Extensions;
