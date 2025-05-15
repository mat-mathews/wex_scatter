using System.Data; // For DbType

namespace GalaxyWorks.Data.Core
{
    public class FakeDbParameter
    {
        public string ParameterName { get; }
        public DbType DbType { get; }
        public object? Value { get; }

        public FakeDbParameter(string parameterName, DbType dbType, object? value)
        {
            ParameterName = parameterName;
            DbType = dbType;
            Value = value;
        }
    }
}