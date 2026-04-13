using System;
using System.ComponentModel.DataAnnotations;

namespace GalaxyWorks.WebPortal.Models
{
    public class PortalConfigViewModel
    {
        public int ConfigurationId { get; set; }

        [Display(Name = "Portal Name")]
        public string PortalName { get; set; }

        [Display(Name = "Notifications Enabled")]
        public bool EnableNotifications { get; set; }

        [Display(Name = "Max Users")]
        public int MaxUsers { get; set; }

        [Display(Name = "Last Updated")]
        [DisplayFormat(DataFormatString = "{0:yyyy-MM-dd HH:mm}")]
        public DateTime LastUpdated { get; set; }
    }

    public class PortalConfigEditModel
    {
        public int ConfigurationId { get; set; }

        [Required(ErrorMessage = "Portal name is required.")]
        [StringLength(200, MinimumLength = 3, ErrorMessage = "Portal name must be between 3 and 200 characters.")]
        [Display(Name = "Portal Name")]
        public string PortalName { get; set; }

        [Display(Name = "Enable Notifications")]
        public bool EnableNotifications { get; set; }

        [Required]
        [Range(1, 10000, ErrorMessage = "Max users must be between 1 and 10,000.")]
        [Display(Name = "Maximum Users")]
        public int MaxUsers { get; set; }
    }

    public class UserActivityViewModel
    {
        public long LogId { get; set; }

        [Display(Name = "User ID")]
        public int UserId { get; set; }

        [Display(Name = "Action")]
        public string ActionPerformed { get; set; }

        [Display(Name = "Timestamp")]
        [DisplayFormat(DataFormatString = "{0:g}")]
        public DateTime Timestamp { get; set; }

        [Display(Name = "IP Address")]
        public string IpAddress { get; set; }
    }
}
