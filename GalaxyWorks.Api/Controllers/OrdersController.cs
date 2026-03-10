// Tests: Event subscription as a coupling vector.
// Controller subscribes to OrderProcessor.OrderCompleted event.
// Also tests record struct usage (Point) and Response<T> common name type.

using GalaxyWorks.Common.Events;
using Microsoft.AspNetCore.Mvc;

namespace GalaxyWorks.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class OrdersController : ControllerBase
{
    private readonly OrderProcessor _processor;

    public OrdersController()
    {
        _processor = new OrderProcessor();
        // Tests: event subscription creates hidden coupling
        _processor.OrderCompleted += OnOrderCompleted;
    }

    [HttpPost("{orderId}/process")]
    public async Task<ActionResult<Response<string>>> ProcessOrder(int orderId)
    {
        await _processor.ProcessOrderAsync(orderId);
        var response = new Response<string>
        {
            StatusCode = 200,
            Payload = $"Order {orderId} processed"
        };
        return Ok(response);
    }

    [HttpGet("location")]
    public ActionResult<Point> GetWarehouseLocation()
    {
        // Tests: record struct usage
        var location = new Point(47.6062, -122.3321);
        return Ok(location);
    }

    private void OnOrderCompleted(object? sender, OrderEventArgs args)
    {
        // In real code this would log, send notifications, etc.
        Console.WriteLine($"Order {args.OrderId} completed at {args.Timestamp}");
    }
}
