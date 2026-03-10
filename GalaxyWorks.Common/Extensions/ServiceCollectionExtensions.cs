// Tests: Extension methods on framework types (IServiceCollection pattern).
// This is the most common DI registration pattern in ASP.NET Core.
// Consumers call `services.AddGalaxyServices()` — no reference to this class name.

#if NET8_0_OR_GREATER
using Microsoft.Extensions.Logging;
#endif

namespace GalaxyWorks.Common.Extensions;

public static class ServiceCollectionExtensions
{
    /// <summary>Registers GalaxyWorks services — consumers don't reference this class by name.</summary>
    public static void AddGalaxyDefaults(this Options options)
    {
        options.MaxRetries = 5;
        options.Timeout = TimeSpan.FromSeconds(60);
        options.EnableCaching = true;
    }
}
