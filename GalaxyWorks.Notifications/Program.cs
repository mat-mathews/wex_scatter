// GalaxyWorks.Notifications — Portal change notification service
//
// This project is a MIXED consumer of PortalDataService:
//   - ConfigChangeNotifier.cs: REAL usage (instantiates + calls methods)
//   - EmailTemplates.cs: FALSE POSITIVE (string literals only)
//   - SlackTemplates.cs: FALSE POSITIVE (string literals + comments only)
//
// In regex mode, all 3 files match \bPortalDataService\b.
// In hybrid mode, only ConfigChangeNotifier.cs should match.
// The project is still a consumer either way — but the relevant_files
// list should be shorter in hybrid mode.

using GalaxyWorks.Notifications.Services;

var notifier = new ConfigChangeNotifier("Server=localhost;Database=GalaxyPortal;");
var changes = notifier.CheckForChanges(new[] { 1, 2, 3 });

foreach (var change in changes)
{
    Console.WriteLine(change);
}
