// Tests: Consumer that uses types from GalaxyWorks.Common without per-file usings.
// All imports come from GlobalUsings.cs — Scatter's namespace filter would miss this file.
// Also tests: extension method usage, record usage, common name types.

using GalaxyWorks.Common.Events;

namespace MyGalaxyConsumerApp;

/// <summary>
/// Demonstrates consuming GalaxyWorks.Common types via global usings.
/// No per-file imports for Common.Models or Common.Extensions namespaces.
/// </summary>
public class OrderConsumer
{
    private readonly OrderProcessor _processor;

    public OrderConsumer()
    {
        _processor = new OrderProcessor();
        _processor.OrderCompleted += OnOrderCompleted;
    }

    public Result ProcessIncomingOrder(string customerName)
    {
        // Uses Result from GalaxyWorks.Common.Models — via GlobalUsings.cs
        if (customerName.IsNullOrWhiteSpace())
            return Result.Fail("Customer name required");

        // Uses PersonDto record from GalaxyWorks.Common.Models — via GlobalUsings.cs
        var customer = new PersonDto(customerName, 0, "");

        // Uses string extension method — via GlobalUsings.cs
        var displayName = customerName.Truncate(50);

        Console.WriteLine($"Processing order for: {displayName}");
        return Result.Ok();
    }

    public Context CreateOrderContext()
    {
        // Uses Context from GalaxyWorks.Common.Models — common name, via GlobalUsings.cs
        return new Context { UserId = "order-consumer" };
    }

    private void OnOrderCompleted(object? sender, OrderEventArgs args)
    {
        Console.WriteLine($"Order {args.OrderId} completed at {args.Timestamp}");
    }
}
