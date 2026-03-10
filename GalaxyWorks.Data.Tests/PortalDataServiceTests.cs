// Tests: Test project referencing GalaxyWorks.Data via ProjectReference.
// Uses xUnit PackageReference alongside ProjectReference.
// Uses file-scoped namespace.
// Verifies Scatter handles test projects (include or exclude via patterns).

using GalaxyWorks.Data.Core;
using GalaxyWorks.Data.DataServices;
using GalaxyWorks.Data.Models;
using Xunit;

namespace GalaxyWorks.Data.Tests;

public class PortalDataServiceTests
{
    private readonly PortalDataService _service;

    public PortalDataServiceTests()
    {
        _service = new PortalDataService();
    }

    [Fact]
    public async Task StorePortalConfiguration_ReturnsPositiveId()
    {
        var config = new PortalConfiguration
        {
            PortalName = "TestPortal",
            EnableNotifications = true,
            MaxUsers = 100,
            AdminApiKey = Guid.NewGuid()
        };

        var result = await _service.StorePortalConfigurationAsync(config);
        Assert.True(result > 0);
    }

    [Fact]
    public async Task RetrievePortalConfiguration_WithValidAdmin_ReturnsConfig()
    {
        var config = await _service.RetrievePortalConfigurationAsync(42);
        Assert.NotNull(config);
        Assert.Equal("GalaxyNet Central", config.PortalName);
    }

    [Fact]
    public async Task GetUserActivity_ReturnsLogs()
    {
        var logs = await _service.GetUserActivityAsync(
            userId: 1,
            startDate: DateTime.UtcNow.AddDays(-7),
            endDate: DateTime.UtcNow);

        Assert.NotEmpty(logs);
        Assert.All(logs, log => Assert.True(log.LogId > 0));
    }

    [Fact]
    public async Task GetSystemModuleDetails_ReturnsModule()
    {
        var module = await _service.GetSystemModuleDetailsAsync("AuthModule");
        Assert.NotNull(module);
        Assert.Equal("AuthModule", module.ModuleName);
        Assert.Equal(StatusType.Active, module.CurrentStatus);
    }
}
