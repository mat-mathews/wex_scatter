// Tests: Extension methods as coupling vectors.
// Consumers call "hello".Truncate(5) — never reference StringExtensions by name.
// Scatter's type-usage detection (text search) would miss this.
// Namespace-level detection still works via `using GalaxyWorks.Common.Extensions;`

namespace GalaxyWorks.Common.Extensions;

public static class StringExtensions
{
    public static string Truncate(this string value, int maxLength)
    {
        if (string.IsNullOrEmpty(value)) return value;
        return value.Length <= maxLength ? value : value[..maxLength] + "...";
    }

    public static string ToSlug(this string value)
    {
        if (string.IsNullOrEmpty(value)) return value;
        return value.ToLowerInvariant()
            .Replace(' ', '-')
            .Replace("--", "-");
    }

    public static bool IsNullOrWhiteSpace(this string? value)
        => string.IsNullOrWhiteSpace(value);
}
