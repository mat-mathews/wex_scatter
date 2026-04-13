namespace GalaxyWorks.Notifications.Templates;

/// <summary>
/// Slack message templates for operations alerts.
///
/// Another file where PortalDataService appears ONLY in strings/comments.
/// Combined with EmailTemplates.cs, this creates a project where multiple
/// files match the regex but only ConfigChangeNotifier.cs has real usage.
/// </summary>
public static class SlackTemplates
{
    // Slack blocks referencing service names — all in string literals

    public static readonly string ConfigChangeSlackBlock = """
        {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Portal Config Changed"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Service:* PortalDataService\n*Action:* Configuration update detected"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "The PortalDataService.GetPortalConfigurationDetails endpoint returned a different payload. Check the portal admin for details."
                    }
                }
            ]
        }
        """;

    // Commented-out code — classic false positive source
    // public static string FormatPortalDataServiceAlert(string message)
    // {
    //     var svc = new PortalDataService(connStr);
    //     var config = svc.GetPortalConfigurationDetails(1);
    //     return $"Alert: {message} — current status: {config.IsActive}";
    // }

    /// <summary>
    /// Format an operational alert for Slack.
    /// Does NOT reference PortalDataService in code — only uses string constants.
    /// </summary>
    public static string FormatOpsAlert(string service, string message)
    {
        return $$"""
            {
                "text": "{{service}} alert: {{message}}",
                "channel": "#ops-alerts"
            }
            """;
    }
}
