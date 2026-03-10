// Tests: C# records — Scatter's TYPE_DECLARATION_PATTERN currently misses these.
// Positional records have no class/struct/interface/enum keyword.

namespace GalaxyWorks.Common.Models;  // file-scoped namespace (C# 10+)

/// <summary>Positional record — invisible to current regex.</summary>
public record PersonDto(string Name, int Age, string Email);

/// <summary>Explicit record class — partially matched (has 'class').</summary>
public record class OrderSummary
{
    public int OrderId { get; init; }
    public decimal Total { get; init; }
    public DateTime CreatedAt { get; init; }
}

/// <summary>Record struct — partially matched (has 'struct').</summary>
public record struct Point(double X, double Y);

/// <summary>Record struct with body — partially matched.</summary>
public record struct Coordinate
{
    public double Latitude { get; init; }
    public double Longitude { get; init; }

    public double DistanceTo(Coordinate other)
    {
        var dx = X - other.Latitude;
        var dy = Longitude - other.Longitude;
        return Math.Sqrt(dx * dx + dy * dy);
    }

    private double X => Latitude;
}

/// <summary>Record inheriting another record.</summary>
public record EmployeeDto(string Name, int Age, string Email, string Department)
    : PersonDto(Name, Age, Email);
