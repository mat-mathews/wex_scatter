using System;
using System.Configuration;

namespace GalaxyWorks.WebPortal.Helpers
{
    public static class ConfigHelper
    {
        public static string GetAppSetting(string key)
        {
            return ConfigurationManager.AppSettings[key] ?? string.Empty;
        }

        public static int GetAppSettingInt(string key, int defaultValue = 0)
        {
            string value = ConfigurationManager.AppSettings[key];
            return int.TryParse(value, out int result) ? result : defaultValue;
        }

        public static bool GetAppSettingBool(string key, bool defaultValue = false)
        {
            string value = ConfigurationManager.AppSettings[key];
            return bool.TryParse(value, out bool result) ? result : defaultValue;
        }

        public static string GetConnectionString(string name)
        {
            var cs = ConfigurationManager.ConnectionStrings[name];
            if (cs == null)
            {
                throw new InvalidOperationException($"Connection string '{name}' not found in configuration.");
            }
            return cs.ConnectionString;
        }

        public static TimeSpan GetCacheTimeout()
        {
            int minutes = GetAppSettingInt("CacheTimeoutMinutes", 30);
            return TimeSpan.FromMinutes(minutes);
        }
    }
}
