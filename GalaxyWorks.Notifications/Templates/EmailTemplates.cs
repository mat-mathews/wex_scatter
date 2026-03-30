using GalaxyWorks.Data.DataServices;

namespace GalaxyWorks.Notifications.Templates;

/// <summary>
/// Email templates for notification messages.
///
/// WARNING: This file mentions PortalDataService extensively in string
/// templates, but does NOT use it. All references are in string literals
/// or comments. This file should NOT cause a class filter match in hybrid
/// mode, even though regex will match \bPortalDataService\b many times.
/// </summary>
public static class EmailTemplates
{
    // These are all string literal mentions — documentation/template text only.

    public static readonly string ConfigChangeSubject =
        "Portal Configuration Changed — Review Required";

    public static readonly string ConfigChangeBody = @"
        <h2>Portal Configuration Change Detected</h2>

        <p>A change was detected in the portal configuration managed by
        <strong>PortalDataService</strong>.</p>

        <h3>What happened?</h3>
        <p>The PortalDataService.GetPortalConfigurationDetails method returned
        different data than the previous snapshot. This could indicate:</p>
        <ul>
            <li>A direct update via PortalDataService.UpdatePortalConfiguration</li>
            <li>A new record via PortalDataService.InsertPortalConfiguration</li>
            <li>A stored procedure execution (sp_UpdatePortalConfiguration)</li>
        </ul>

        <h3>Affected Service</h3>
        <p>Service: PortalDataService<br/>
        Assembly: GalaxyWorks.Data<br/>
        Interface: IDataAccessor</p>

        <p>Please review the change in the portal admin panel.</p>
    ";

    public static readonly string ErrorNotificationBody = @"
        <h2>PortalDataService Error</h2>

        <p>An error occurred in the PortalDataService layer:</p>

        <pre>
        System.TimeoutException: PortalDataService.GetPortalConfigurationDetails
        timed out after 30 seconds. The stored procedure
        sp_GetPortalConfigurationDetails may be blocked or the database
        may be under heavy load.

        Stack trace:
            at PortalDataService.GetPortalConfigurationDetails(Int32 configId)
            at ConfigChangeNotifier.CheckForChanges(IEnumerable`1 configIds)
        </pre>

        <p>This is an automated notification from GalaxyWorks.Notifications.</p>
    ";

    // More string mentions in log format templates
    public static string FormatAuditEntry(int configId, string action) =>
        $"[AUDIT] PortalDataService config {configId}: {action} at {DateTime.UtcNow:O}";

    // Comment with method reference — not real usage
    // TODO: Add template for PortalDataService.RetrieveUserActivity notifications
    // See: PortalDataService.GetSystemModuleByName for module-level alerts
}
