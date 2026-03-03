using System;
using System.Data.Entity;
using GalaxyWorks.Data.DataServices;
using GalaxyWorks.Data.Models;
using GalaxyWorks.WebPortal.Services;

namespace GalaxyWorks.BatchProcessor.Jobs
{
    public class SyncJob
    {
        private readonly PortalDataService _dataService;
        private readonly IPortalCacheService _cacheService;
        private readonly DbContext _dbContext;

        public SyncJob(DbContext dbContext)
        {
            _dataService = new PortalDataService();
            _cacheService = new PortalCacheService();
            _dbContext = dbContext;
        }

        public void Execute()
        {
            Console.WriteLine("[SyncJob] Starting portal configuration sync...");

            // Use GalaxyWorks.Data types
            var config = new PortalConfiguration
            {
                PortalName = "BatchSync",
                EnableNotifications = true,
                MaxUsers = 500
            };

            // EF-style sproc call — SqlQuery<T> pattern for scatter detection
            var existing = _dbContext.Database
                .SqlQuery<PortalConfiguration>("dbo.sp_InsertPortalConfiguration", config.PortalName)
                .FirstOrDefault();

            if (existing != null)
            {
                _cacheService.InvalidateConfig(existing.ConfigurationId);
            }

            Console.WriteLine("[SyncJob] Sync complete.");
        }
    }
}
