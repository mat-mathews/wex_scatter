namespace GalaxyWorks.Data.Models
{
    public enum StatusType
    {
        Unknown = 0,
        Active = 1,
        Inactive = 2,
        Pending = 3
    }

    public class PortalConfiguration
    {
        public int ConfigurationId { get; set; }
        public string PortalName { get; set; } = string.Empty;
        public bool EnableNotifications { get; set; }
        public int MaxUsers { get; set; }
        public DateTime LastUpdated { get; set; }
        public Guid AdminApiKey { get; set; }
    }

    public class UserActivityLog
    {
        public long LogId { get; set; }
        public int UserId { get; set; }
        public string ActionPerformed { get; set; } = string.Empty;
        public DateTime Timestamp { get; set; }
        public string? IpAddress { get; set; }
    }

    public class SystemModule
    {
        public int ModuleId { get; set; }
        public string ModuleName { get; set; } = string.Empty;
        public string Version { get; set; } = string.Empty;
        public bool IsCoreModule { get; set; }
        public StatusType CurrentStatus { get; set; }
    }
}