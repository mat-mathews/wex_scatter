using System.Data; // For CommandType

namespace GalaxyWorks.Data.Core
{
    public class FakeDbCommand
    {
        public string CommandText { get; set; }
        public CommandType CommandType { get; set; }
        public List<FakeDbParameter> Parameters { get; } = new List<FakeDbParameter>();

        public FakeDbCommand(string commandText)
        {
            CommandText = commandText;
            CommandType = CommandType.Text; // Default, can be changed to StoredProcedure
        }
    }
}