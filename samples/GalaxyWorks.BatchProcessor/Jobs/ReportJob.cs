using System;
using System.Data.Entity;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.BatchProcessor.Jobs
{
    public sealed class ReportJob
    {
        private readonly DbContext _dbContext;

        public ReportJob(DbContext dbContext)
        {
            _dbContext = dbContext;
        }

        public void GenerateReport(int configId)
        {
            Console.WriteLine($"[ReportJob] Generating report for config {configId}...");

            // Different sproc call style — ExecuteSqlCommand pattern for scatter detection
            _dbContext.Database.ExecuteSqlCommand(
                "dbo.sp_InsertPortalConfiguration",
                configId,
                "DailyReport");

            var config = _dbContext.Database
                .SqlQuery<PortalConfiguration>("dbo.sp_GetPortalConfigurationDetails", configId)
                .FirstOrDefault();

            if (config != null)
            {
                Console.WriteLine($"[ReportJob] Report generated for portal: {config.PortalName}");
            }
        }
    }
}
