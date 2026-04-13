// Tests: InternalsVisibleTo — internal types shared across assemblies.
// GalaxyWorks.Data.Tests has access via [InternalsVisibleTo] in .csproj.
// Scatter wouldn't normally detect internal type usage across projects.

namespace GalaxyWorks.Common.Models;

/// <summary>Internal helper — only visible to GalaxyWorks.Data.Tests via InternalsVisibleTo.</summary>
internal class InternalCacheKey
{
    public string Region { get; set; } = "default";
    public string Key { get; set; } = string.Empty;
    public DateTime Expiry { get; set; } = DateTime.UtcNow.AddMinutes(30);

    public override string ToString() => $"{Region}:{Key}";
}

/// <summary>Internal record — tests both internal + record visibility.</summary>
internal record InternalAuditEntry(string Action, string UserId, DateTime Timestamp);
