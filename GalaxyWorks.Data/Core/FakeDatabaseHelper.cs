using System;
using System.Collections.Generic;
using System.Data; // For DbType and IDataRecord
using System.Threading.Tasks;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.Data.Core
{
    // Fake IDataRecord for simulating database reader rows
    public interface IFakeDataRecord
    {
        object? this[string name] { get; }
        T Get<T>(string name);
        T Get<T>(string name, T defaultValueIfNull);
    }

    public class DictionaryDataRecord : IFakeDataRecord
    {
        private readonly Dictionary<string, object?> _data;

        public DictionaryDataRecord(Dictionary<string, object?> data)
        {
            _data = data ?? throw new ArgumentNullException(nameof(data));
        }

        public object? this[string name] => _data.TryGetValue(name, out var value) ? value : null;

        public T Get<T>(string name)
        {
            if (_data.TryGetValue(name, out var value))
            {
                if (value == null && Nullable.GetUnderlyingType(typeof(T)) != null)
                {
                    return default(T)!; // Or throw if strict null handling is desired
                }
                if (value is T typedValue)
                {
                    return typedValue;
                }
                // Try to convert, especially for enums stored as int
                if (typeof(T).IsEnum && value is int intValue)
                {
                    return (T)Enum.ToObject(typeof(T), intValue);
                }
                return (T)Convert.ChangeType(value!, typeof(T));
            }
            throw new KeyNotFoundException($"Column '{name}' not found.");
        }
        
        public T Get<T>(string name, T defaultValueIfNull)
        {
            if (_data.TryGetValue(name, out var value))
            {
                if (value == null) return defaultValueIfNull;
                if (value is T typedValue) return typedValue;
                if (typeof(T).IsEnum && value is int intValue)
                {
                    return (T)Enum.ToObject(typeof(T), intValue);
                }
                return (T)Convert.ChangeType(value, typeof(T));
            }
            return defaultValueIfNull; // Or throw if column must exist
        }
    }


    public class FakeDatabaseHelper
    {
        private string _connectionString; // Not really used, but for show

        public FakeDatabaseHelper(string connectionStringName)
        {
            // In a real scenario, you'd look up the connection string
            _connectionString = $"FakeConnectionStringFor-{connectionStringName}";
            Console.WriteLine($"FakeDatabaseHelper initialized with: {_connectionString}");
        }

        public FakeDbCommand GetStoredProcCommand(string procedureName)
        {
            Console.WriteLine($"FakeDatabaseHelper: Creating command for SPROC: {procedureName}");
            return new FakeDbCommand(procedureName) { CommandType = CommandType.StoredProcedure };
        }

        public void AddInParameter(FakeDbCommand command, string paramName, DbType dbType, object? value)
        {
            Console.WriteLine($"FakeDatabaseHelper: Adding param to {command.CommandText}: {paramName} = {value ?? "NULL"}");
            command.Parameters.Add(new FakeDbParameter(paramName, dbType, value));
        }

        public void AddOutParameter(FakeDbCommand command, string paramName, DbType dbType, int size) // Simplified
        {
             Console.WriteLine($"FakeDatabaseHelper: Adding OUT param to {command.CommandText}: {paramName}");
            // In a real fake, you might store this to set its value later
            command.Parameters.Add(new FakeDbParameter(paramName, dbType, null)); // Placeholder
        }

        public object? GetParameterValue(FakeDbCommand command, string paramName)
        {
            // Simulate getting an OUT parameter's value
            if (command.CommandText == "dbo.sp_InsertPortalConfiguration" && paramName == "@ConfigId_out")
            {
                return new Random().Next(1000, 9999); // Fake generated ID
            }
            return null;
        }


        public async Task<int> ExecuteNonQueryAsync(FakeDbCommand command)
        {
            Console.WriteLine($"FakeDatabaseHelper: Executing NonQuery for: {command.CommandText}");
            // Simulate rows affected
            await Task.Delay(50); // Simulate network latency
            if (command.CommandText.StartsWith("dbo.sp_Insert") || command.CommandText.StartsWith("dbo.sp_Update"))
            {
                return 1; // Simulate 1 row affected
            }
            return 0;
        }

        public async Task<List<IFakeDataRecord>> ExecuteReaderAsync(FakeDbCommand command)
        {
            Console.WriteLine($"FakeDatabaseHelper: Executing Reader for: {command.CommandText}");
            await Task.Delay(70); // Simulate network latency
            var results = new List<IFakeDataRecord>();

            // Simulate different results based on the "stored procedure"
            if (command.CommandText == "dbo.sp_GetPortalConfigurationDetails")
            {
                // Find the adminId parameter
                var adminIdParam = command.Parameters.FirstOrDefault(p => p.ParameterName == "@AdminIdentifier");
                if (adminIdParam?.Value is int adminId && adminId > 0)
                {
                     results.Add(new DictionaryDataRecord(new Dictionary<string, object?>
                    {
                        { "ConfigId", adminId * 10 }, // Make it somewhat dynamic based on input
                        { "PortalName", "GalaxyNet Central" },
                        { "NotifyEnabled_fl", true },
                        { "UserLimit", 500 },
                        { "ModifiedDate", DateTime.UtcNow.AddDays(-5) },
                        { "AdminKey", Guid.NewGuid() }
                    }));
                }
            }
            else if (command.CommandText == "dbo.sp_RetrieveUserActivity")
            {
                var userIdParam = command.Parameters.FirstOrDefault(p => p.ParameterName == "@TargetUserId");
                if (userIdParam?.Value is int userId)
                {
                    results.Add(new DictionaryDataRecord(new Dictionary<string, object?>
                    {
                        { "LogEntryId", 12345L },
                        { "UserId_fk", userId },
                        { "ActionName", "UserLogin" },
                        { "EventTime", DateTime.UtcNow.AddHours(-2) },
                        { "SourceIp", "192.168.1.100" }
                    }));
                    results.Add(new DictionaryDataRecord(new Dictionary<string, object?>
                    {
                        { "LogEntryId", 12346L },
                        { "UserId_fk", userId },
                        { "ActionName", "ProfileUpdate" },
                        { "EventTime", DateTime.UtcNow.AddHours(-1) },
                        { "SourceIp", "192.168.1.100" }
                    }));
                }
            }
            else if (command.CommandText == "dbo.sp_FetchSystemModuleByName")
            {
                 var moduleNameParam = command.Parameters.FirstOrDefault(p => p.ParameterName == "@ModuleName");
                 if (moduleNameParam?.Value is string moduleName)
                 {
                    results.Add(new DictionaryDataRecord(new Dictionary<string, object?>
                    {
                        { "SysModId", 77 },
                        { "SysModName", moduleName },
                        { "ModVersion", "2.3.1b" },
                        { "IsCore_fl", moduleName.Contains("Auth") }, // Fake logic
                        { "ModStatus_cd", (int)StatusType.Active }
                    }));
                 }
            }
            // Add more SPROC simulations here

            return results;
        }
    }
}