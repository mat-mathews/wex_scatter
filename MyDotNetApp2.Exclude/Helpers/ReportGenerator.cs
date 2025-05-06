// ReportGenerator.cs in the MyDotNetApp.Consumer project

// --- Using Directives ---
// Need access to the service interface and models from the referenced project
using MyDotNetApp.Models;
using MyDotNetApp.Services;
// Also need standard collections
using System.Text; // For StringBuilder

// Define the namespace for this consumer application's components
namespace MyDotNetApp.Consumer.Helpers // Placing it in a sub-namespace 'Helpers'
{
    /// <summary>
    /// Generates simple reports based on data retrieved from the IDataService.
    /// Demonstrates using services and models from a referenced project within
    /// a separate class in the consuming project.
    /// </summary>
    public class ReportGenerator
    {
        // Store a reference to the service (dependency)
        private readonly IDataService _dataService;

        /// <summary>
        /// Constructor that takes the data service as a dependency.
        /// This promotes better testability (Dependency Injection pattern).
        /// </summary>
        /// <param name="dataService">The service implementation to use for fetching data.</param>
        public ReportGenerator(IDataService dataService)
        {
            // Basic null check for the dependency
            _dataService = dataService ?? throw new ArgumentNullException(nameof(dataService));
            Console.WriteLine("ReportGenerator initialized with a DataService instance.");
        }

        /// <summary>
        /// Generates a simple summary report of all people.
        /// Uses async/await because it calls an async method on the service.
        /// </summary>
        /// <returns>A Task representing the asynchronous operation, containing the report string.</returns>
        public async Task<string> GeneratePeopleSummaryReportAsync()
        {
            Console.WriteLine("Generating people summary report...");
            var reportBuilder = new StringBuilder();
            reportBuilder.AppendLine("--- People Summary Report ---");
            reportBuilder.AppendLine($"Generated on: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            reportBuilder.AppendLine("-----------------------------");

            try
            {
                // Use the injected service to get data from the referenced project
                List<Person> people = await _dataService.GetPeopleAsync();

                if (people.Any())
                {
                    reportBuilder.AppendLine($"Total People Found: {people.Count}");
                    reportBuilder.AppendLine(); // Add a blank line
                    foreach (Person person in people.OrderBy(p => p.LastName).ThenBy(p => p.FirstName)) // Example: Sort the data
                    {
                        // Access properties of the Person model
                        reportBuilder.AppendLine($"- Name: {person.FullName}, Age: {person.Age}");
                    }
                }
                else
                {
                    reportBuilder.AppendLine("No people data available.");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[REPORT ERROR] Failed to retrieve data for report: {ex.Message}");
                reportBuilder.AppendLine("\n*** Error generating report data ***");
            }

            reportBuilder.AppendLine("-----------------------------");
            reportBuilder.AppendLine("--- End of Report ---");

            Console.WriteLine("Report generation complete.");
            return reportBuilder.ToString();
        }

        /// <summary>
        /// Example of another method that might use the service.
        /// Finds people by last name and returns a simple list.
        /// </summary>
        /// <param name="lastName">Last name to search for.</param>
        /// <returns>A list of full names matching the criteria.</returns>
        public List<string> GetNamesByLastName(string lastName)
        {
            Console.WriteLine($"Searching for names with last name '{lastName}' for report...");
            // This service method is synchronous in our example
            IEnumerable<Person> people = _dataService.FindPeopleByLastName(lastName);
            // Use LINQ Select to transform the Person objects into strings (FullName)
            return people.Select(p => p.FullName).ToList();
        }
    }
}
