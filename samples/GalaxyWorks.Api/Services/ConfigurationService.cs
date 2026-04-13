// Tests: IOptions<T> configuration binding pattern (common in ASP.NET Core).
// Also tests: file-scoped namespace, Context usage (common name collision test).

#if NET8_0_OR_GREATER
using Microsoft.Extensions.Options;
#endif

namespace GalaxyWorks.Api.Services;

/// <summary>App-specific options — tests common name "Options" collision.</summary>
public class GalaxyApiOptions
{
    public string ApiVersion { get; set; } = "v1";
    public int RateLimitPerMinute { get; set; } = 100;
    public bool EnableSwagger { get; set; } = true;
}

public class ConfigurationService
{
    private readonly Context _context;

    public ConfigurationService()
    {
        // Tests: Context from GalaxyWorks.Common — common name collision
        _context = new Context { UserId = "system" };
    }

    public Context GetCurrentContext() => _context;

    public Result ValidateConfiguration(GalaxyApiOptions options)
    {
        // Tests: Result from GalaxyWorks.Common — common name collision
        if (options.RateLimitPerMinute <= 0)
            return Result.Fail("Rate limit must be positive");

        return Result.Ok();
    }
}
