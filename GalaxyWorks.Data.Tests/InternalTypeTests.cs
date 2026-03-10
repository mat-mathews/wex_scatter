// Tests: InternalsVisibleTo — accessing internal types from GalaxyWorks.Common.
// GalaxyWorks.Common.csproj has <InternalsVisibleTo Include="GalaxyWorks.Data.Tests" />.
// Scatter wouldn't normally detect this dependency because the types are internal.

using GalaxyWorks.Common.Models;
using Xunit;

namespace GalaxyWorks.Data.Tests;

public class InternalTypeTests
{
    [Fact]
    public void InternalCacheKey_ToString_FormatsCorrectly()
    {
        // This compiles only because of InternalsVisibleTo
        var key = new InternalCacheKey
        {
            Region = "users",
            Key = "user-42"
        };

        Assert.Equal("users:user-42", key.ToString());
    }

    [Fact]
    public void InternalAuditEntry_CreatesCorrectly()
    {
        // Internal record accessed via InternalsVisibleTo
        var entry = new InternalAuditEntry("Login", "user-42", DateTime.UtcNow);

        Assert.Equal("Login", entry.Action);
        Assert.Equal("user-42", entry.UserId);
    }
}
