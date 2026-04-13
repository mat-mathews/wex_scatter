// Tests: Minimal API pattern — no controller class, just lambda handlers.
// Scatter can't detect these as consumers because there's no class declaration.

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

// Minimal API endpoints — coupling without controller classes
app.MapGet("/api/health", () => Results.Ok(new { Status = "Healthy" }));

app.MapGet("/api/version", () =>
{
    var options = new GalaxyWorks.Common.Models.Options { MaxRetries = 1 };
    return Results.Ok(new { Version = "1.0", MaxRetries = options.MaxRetries });
});

app.Run();
