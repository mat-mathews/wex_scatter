using GalaxyWorks.Data.Models;

namespace GalaxyWorks.Data.Core
{
    public interface IDataAccessor
    {
        Task<int> StorePortalConfigurationAsync(PortalConfiguration config);
        Task UpdatePortalConfigurationAsync(PortalConfiguration config);
        Task<PortalConfiguration?> RetrievePortalConfigurationAsync(int adminId);
        Task<List<UserActivityLog>> GetUserActivityAsync(int userId, DateTime startDate, DateTime endDate);
        Task<SystemModule?> GetSystemModuleDetailsAsync(string moduleName);
    }
}