using GalaxyWorks.Data.DataServices;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.Notifications.Services;

/// <summary>
/// Monitors portal configuration changes and sends notifications.
///
/// This class ACTUALLY uses PortalDataService — it's a real consumer.
/// It calls GetPortalConfigurationDetails to fetch current state and
/// compare against cached snapshots.
/// </summary>
public class ConfigChangeNotifier
{
    private readonly PortalDataService _dataService;
    private readonly Dictionary<int, PortalConfiguration?> _cache = new();

    public ConfigChangeNotifier(string connectionString)
    {
        _dataService = new PortalDataService(connectionString);
    }

    /// <summary>
    /// Check for changes and notify subscribers.
    /// Calls PortalDataService.GetPortalConfigurationDetails for each tracked config.
    /// </summary>
    public List<string> CheckForChanges(IEnumerable<int> configIds)
    {
        var notifications = new List<string>();

        foreach (var id in configIds)
        {
            var current = _dataService.GetPortalConfigurationDetails(id);
            var previous = _cache.GetValueOrDefault(id);

            if (previous != null && current != null)
            {
                if (current.IsActive != previous.IsActive)
                {
                    notifications.Add($"Config {id} status changed: {previous.IsActive} -> {current.IsActive}");
                }
            }

            _cache[id] = current;
        }

        return notifications;
    }
}
