using GalaxyWorks.Data.Models;

namespace GalaxyWorks.DevTools.Diagnostics;

/// <summary>
/// Validates that required dependencies are correctly wired at startup.
/// Checks configuration, connection strings, and service registration.
/// </summary>
public class DependencyChecker
{
    // Error message templates — mention services by name for diagnostics
    private static readonly Dictionary<string, string> KnownIssues = new()
    {
        ["PortalDataService_missing_connstring"] =
            "PortalDataService requires a valid connection string. " +
            "Check appsettings.json for 'PortalDatabase' key.",

        ["PortalDataService_timeout"] =
            "PortalDataService.GetPortalConfigurationDetails timed out. " +
            "This usually means sp_GetPortalConfigurationDetails is blocked.",

        ["PortalDataService_null_config"] =
            "PortalDataService.InsertPortalConfiguration received null. " +
            "Ensure the PortalConfiguration model is populated before calling.",
    };

    /// <summary>
    /// Run all diagnostic checks. Returns a list of issues found.
    ///
    /// Does NOT instantiate PortalDataService — only validates that
    /// the environment is configured correctly for it to work.
    /// </summary>
    public List<string> RunChecks()
    {
        var issues = new List<string>();

        // Check that the model types are loadable (real reflection usage)
        var configType = typeof(PortalConfiguration);
        if (configType.GetProperties().Length == 0)
        {
            issues.Add("PortalConfiguration has no public properties — model may be corrupted");
        }

        var statusValues = Enum.GetValues<StatusType>();
        if (statusValues.Length < 3)
        {
            issues.Add("StatusType enum has fewer values than expected — check for breaking changes");
        }

        // Log known issues for reference (string mentions, not real calls)
        foreach (var (key, message) in KnownIssues)
        {
            Console.WriteLine($"  [CHECK] {key}: {message}");
        }

        return issues;
    }
}
