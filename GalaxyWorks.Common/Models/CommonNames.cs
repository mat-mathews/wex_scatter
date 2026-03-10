// Tests: Common type names that collide across projects.
// Scatter's text-based search for "Result" will match unrelated projects.
// This is the #1 false positive risk in production use.

namespace GalaxyWorks.Common.Models;

/// <summary>Generic operation result — name collides with System.Result, other projects.</summary>
public class Result
{
    public bool Success { get; set; }
    public string? Message { get; set; }

    public static Result Ok() => new() { Success = true };
    public static Result Fail(string message) => new() { Success = false, Message = message };
}

/// <summary>Typed result wrapper.</summary>
public class Result<T> : Result
{
    public T? Data { get; set; }

    public static Result<T> Ok(T data) => new() { Success = true, Data = data };
    public new static Result<T> Fail(string message) => new() { Success = false, Message = message };
}

/// <summary>API response wrapper — extremely common name.</summary>
public class Response
{
    public int StatusCode { get; set; }
    public string? Body { get; set; }
}

/// <summary>API response with typed payload.</summary>
public class Response<T> : Response
{
    public T? Payload { get; set; }
}

/// <summary>Configuration options — collides with Microsoft.Extensions.Options.</summary>
public class Options
{
    public int MaxRetries { get; set; } = 3;
    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(30);
    public bool EnableCaching { get; set; } = true;
}

/// <summary>Request context — common name across service layers.</summary>
public class Context
{
    public string CorrelationId { get; set; } = Guid.NewGuid().ToString();
    public string? UserId { get; set; }
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
}

/// <summary>Generic service interface — common name.</summary>
public interface IService
{
    Task<Result> ExecuteAsync(Context context);
}

/// <summary>Handler interface — common in CQRS patterns.</summary>
public interface IHandler<TRequest, TResponse>
{
    Task<TResponse> HandleAsync(TRequest request);
}
