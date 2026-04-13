using System;
using System.Collections.Concurrent;
using GalaxyWorks.Data.Models;
using GalaxyWorks.WebPortal.Helpers;

namespace GalaxyWorks.WebPortal.Services
{
    public interface IPortalCacheService
    {
        PortalConfiguration GetCachedConfig(int configId);
        void InvalidateConfig(int configId);
    }

    public partial class PortalCacheService : IPortalCacheService
    {
        private readonly ConcurrentDictionary<int, CacheEntry<PortalConfiguration>> _configCache;
        private readonly TimeSpan _cacheTimeout;

        public PortalCacheService()
        {
            _configCache = new ConcurrentDictionary<int, CacheEntry<PortalConfiguration>>();
            _cacheTimeout = ConfigHelper.GetCacheTimeout();
        }

        public PortalConfiguration GetCachedConfig(int configId)
        {
            if (_configCache.TryGetValue(configId, out var entry) && !entry.IsExpired(_cacheTimeout))
            {
                return entry.Value;
            }

            var config = LoadConfigFromDatabase(configId);
            if (config != null)
            {
                _configCache[configId] = new CacheEntry<PortalConfiguration>(config);
            }

            return config;
        }

        public void InvalidateConfig(int configId)
        {
            _configCache.TryRemove(configId, out _);
        }

        private class CacheEntry<T>
        {
            public T Value { get; }
            public DateTime CachedAt { get; }

            public CacheEntry(T value)
            {
                Value = value;
                CachedAt = DateTime.UtcNow;
            }

            public bool IsExpired(TimeSpan timeout)
            {
                return DateTime.UtcNow - CachedAt > timeout;
            }
        }
    }
}
