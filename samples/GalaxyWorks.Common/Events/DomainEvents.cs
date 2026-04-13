// Tests: Event and delegate patterns as coupling vectors.
// Consumers subscribe via processor.OrderCompleted += handler
// without necessarily referencing OrderEventArgs by name in a searchable way.

namespace GalaxyWorks.Common.Events;

/// <summary>Event args for order lifecycle — delegates create coupling through subscription.</summary>
public class OrderEventArgs : EventArgs
{
    public int OrderId { get; }
    public string Status { get; }
    public DateTime Timestamp { get; }

    public OrderEventArgs(int orderId, string status)
    {
        OrderId = orderId;
        Status = status;
        Timestamp = DateTime.UtcNow;
    }
}

/// <summary>Custom delegate type for typed event handling.</summary>
public delegate Task AsyncEventHandler<TEventArgs>(object sender, TEventArgs args)
    where TEventArgs : EventArgs;

/// <summary>Event publisher — consumers subscribe to events, creating hidden coupling.</summary>
public class OrderProcessor
{
    public event EventHandler<OrderEventArgs>? OrderCompleted;
    public event EventHandler<OrderEventArgs>? OrderFailed;
    public event AsyncEventHandler<OrderEventArgs>? OrderProcessing;

    public async Task ProcessOrderAsync(int orderId)
    {
        try
        {
            OrderProcessing?.Invoke(this, new OrderEventArgs(orderId, "Processing"));
            await Task.Delay(100); // simulate work
            OrderCompleted?.Invoke(this, new OrderEventArgs(orderId, "Completed"));
        }
        catch (Exception)
        {
            OrderFailed?.Invoke(this, new OrderEventArgs(orderId, "Failed"));
            throw;
        }
    }
}
