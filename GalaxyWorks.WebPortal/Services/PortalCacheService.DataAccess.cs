using System.Data.Entity;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.WebPortal.Services
{
    public partial class PortalCacheService
    {
        private DbContext _dbContext;

        private PortalConfiguration LoadConfigFromDatabase(int configId)
        {
            // Entity Framework sproc call pattern — exercises scatter's stored procedure detection
            var sprocName = "dbo.sp_InsertPortalConfiguration";
            _dbContext.Database.ExecuteSqlCommand(
                string.Format("exec {0} @configId", sprocName), configId);

            var result = _dbContext.Database
                .SqlQuery<PortalConfiguration>("dbo.sp_GetPortalConfigurationDetails", configId)
                .FirstOrDefault();

            return result;
        }

        private void PersistConfigToDatabase(PortalConfiguration config)
        {
            _dbContext.Database.ExecuteSqlCommand(
                "dbo.sp_UpdatePortalConfiguration",
                config.ConfigurationId,
                config.PortalName,
                config.EnableNotifications,
                config.MaxUsers);
        }
    }
}
