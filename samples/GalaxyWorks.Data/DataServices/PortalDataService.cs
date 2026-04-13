using System.Data; // For DbType
using GalaxyWorks.Data.Core;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.Data.DataServices
{
    public class PortalDataService : IDataAccessor
    {
        private readonly FakeDatabaseHelper _dbHelper;

        public PortalDataService()
        {
            // In a real app, connection string name might come from config
            _dbHelper = new FakeDatabaseHelper("CorePlatformDB");
        }

        public async Task<int> StorePortalConfigurationAsync(PortalConfiguration config)
        {
            using (var command = _dbHelper.GetStoredProcCommand("dbo.sp_InsertPortalConfiguration"))
            {
                _dbHelper.AddInParameter(command, "@PortalName_val", DbType.String, config.PortalName);
                _dbHelper.AddInParameter(command, "@EnableNotifications_fl", DbType.Boolean, config.EnableNotifications);
                _dbHelper.AddInParameter(command, "@MaxUsers_qty", DbType.Int32, config.MaxUsers);
                _dbHelper.AddInParameter(command, "@AdminApiKey_guid", DbType.Guid, config.AdminApiKey);
                _dbHelper.AddOutParameter(command, "@ConfigId_out", DbType.Int32, 4); // Size for int

                await _dbHelper.ExecuteNonQueryAsync(command);
                
                var newId = _dbHelper.GetParameterValue(command, "@ConfigId_out");
                return newId != null ? Convert.ToInt32(newId) : -1;
            }
        }

        public async Task UpdatePortalConfigurationAsync(PortalConfiguration config)
        {
            using (var command = _dbHelper.GetStoredProcCommand("dbo.sp_UpdatePortalConfiguration"))
            {
                _dbHelper.AddInParameter(command, "@ConfigId_pk", DbType.Int32, config.ConfigurationId);
                _dbHelper.AddInParameter(command, "@PortalName_val", DbType.String, config.PortalName);
                _dbHelper.AddInParameter(command, "@EnableNotifications_fl", DbType.Boolean, config.EnableNotifications);
                _dbHelper.AddInParameter(command, "@MaxUsers_qty", DbType.Int32, config.MaxUsers);
                // Assuming LastUpdated is set by the database via a trigger or default, or handled by SPROC
                
                await _dbHelper.ExecuteNonQueryAsync(command);
            }
        }

        public async Task<PortalConfiguration?> RetrievePortalConfigurationAsync(int adminId)
        {
            PortalConfiguration? settings = null;
            using (var command = _dbHelper.GetStoredProcCommand("dbo.sp_GetPortalConfigurationDetails"))
            {
                _dbHelper.AddInParameter(command, "@AdminIdentifier", DbType.Int32, adminId);

                var readerResults = await _dbHelper.ExecuteReaderAsync(command);
                if (readerResults.Any())
                {
                    var dr = readerResults.First(); // Expecting single row for this SPROC
                    settings = new PortalConfiguration
                    {
                        ConfigurationId = dr.Get<int>("ConfigId"),
                        PortalName = dr.Get<string>("PortalName"),
                        EnableNotifications = dr.Get<bool>("NotifyEnabled_fl"),
                        MaxUsers = dr.Get<int>("UserLimit"),
                        LastUpdated = dr.Get<DateTime>("ModifiedDate"),
                        AdminApiKey = dr.Get<Guid>("AdminKey")
                    };
                }
            }
            return settings;
        }

        public async Task<List<UserActivityLog>> GetUserActivityAsync(int userId, DateTime startDate, DateTime endDate)
        {
            var logs = new List<UserActivityLog>();
            using (var command = _dbHelper.GetStoredProcCommand("dbo.sp_RetrieveUserActivity"))
            {
                _dbHelper.AddInParameter(command, "@TargetUserId", DbType.Int32, userId);
                _dbHelper.AddInParameter(command, "@RangeStart_dt", DbType.DateTime, startDate);
                _dbHelper.AddInParameter(command, "@RangeEnd_dt", DbType.DateTime, endDate);

                var readerResults = await _dbHelper.ExecuteReaderAsync(command);
                foreach (var dr in readerResults)
                {
                    logs.Add(new UserActivityLog
                    {
                        LogId = dr.Get<long>("LogEntryId"),
                        UserId = dr.Get<int>("UserId_fk"),
                        ActionPerformed = dr.Get<string>("ActionName"),
                        Timestamp = dr.Get<DateTime>("EventTime"),
                        IpAddress = dr.Get<string?>("SourceIp", null) // Handle potential null
                    });
                }
            }
            return logs;
        }
         public async Task<SystemModule?> GetSystemModuleDetailsAsync(string moduleName)
        {
            SystemModule? module = null;
            using (var command = _dbHelper.GetStoredProcCommand("dbo.sp_FetchSystemModuleByName"))
            {
                _dbHelper.AddInParameter(command, "@ModuleName", DbType.String, moduleName);

                var readerResults = await _dbHelper.ExecuteReaderAsync(command);
                if (readerResults.Any())
                {
                    var dr = readerResults.First();
                    module = new SystemModule
                    {
                        ModuleId = dr.Get<int>("SysModId"),
                        ModuleName = dr.Get<string>("SysModName"),
                        Version = dr.Get<string>("ModVersion"),
                        IsCoreModule = dr.Get<bool>("IsCore_fl"),
                        CurrentStatus = dr.Get<StatusType>("ModStatus_cd") // Enum mapping
                    };
                }
            }
            return module;
        }
    }
}