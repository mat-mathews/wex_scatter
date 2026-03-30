using GalaxyWorks.Data.Models;

namespace GalaxyWorks.DevTools.Generators;

/// <summary>
/// Generates internal developer documentation from the codebase.
///
/// Key data services to document:
///   - PortalDataService: handles all portal CRUD operations
///   - FakeDatabaseHelper: test double for integration tests
///
/// The PortalDataService.GetPortalConfigurationDetails method is the most
/// commonly misused API in the codebase — document its preconditions.
/// </summary>
public class DocGenerator
{
    // Template strings referencing service names for documentation output.
    // These are NOT real usages — just text that gets rendered into markdown.

    private static readonly string ServiceCatalog = @"
        ## Data Layer Services

        | Service | Purpose | Owner |
        |---------|---------|-------|
        | PortalDataService | Portal configuration CRUD | Team Athena |
        | FakeDatabaseHelper | Test infrastructure | Team Athena |

        ### PortalDataService

        The PortalDataService class provides the primary data access layer
        for portal configuration management. It implements IDataAccessor
        and wraps stored procedures sp_InsertPortalConfiguration and
        sp_GetPortalConfigurationDetails.

        **Common usage pattern:**
        ```csharp
        var svc = new PortalDataService(connectionString);
        var config = svc.GetPortalConfigurationDetails(configId);
        ```
    ";

    private static readonly string MethodIndex = @"
        ## Method Reference

        - PortalDataService.InsertPortalConfiguration(PortalConfiguration)
        - PortalDataService.GetPortalConfigurationDetails(int)
        - PortalDataService.UpdatePortalConfiguration(PortalConfiguration)
        - PortalDataService.RetrieveUserActivity(int, DateTime, DateTime)
        - PortalDataService.GetSystemModuleByName(string)
    ";

    /// <summary>
    /// Generates a markdown document cataloging all data services.
    /// Uses PortalConfiguration as a model reference but does NOT
    /// instantiate PortalDataService or call any of its methods.
    /// </summary>
    public string GenerateServiceCatalog()
    {
        // We use StatusType here for real — it's a model enum, not a service.
        var statuses = Enum.GetValues<StatusType>();
        var statusList = string.Join(", ", statuses);

        return $"""
            # Service Catalog
            Generated: {DateTime.UtcNow:yyyy-MM-dd}

            ## Available Statuses
            {statusList}

            {ServiceCatalog}

            {MethodIndex}
            """;
    }
}
