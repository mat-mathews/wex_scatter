// Program.cs in the MyDotNetApp.Consumer project

// --- Using Directives ---
// We need to use the namespaces from the referenced project (MyDotNetApp)
// to access its classes (Person, IDataService, DataService).
using MyDotNetApp.Models;
using MyDotNetApp.Services;

// Implicit usings will cover System, System.Collections.Generic, System.Threading.Tasks etc.

// Define the namespace for this consumer application
namespace MyDotNetApp.Consumer
{
    class Program
    {
        // Use async Task Main to allow awaiting async methods from the service
        static async Task Main(string[] args)
        {
            Console.WriteLine("--- Starting MyDotNetApp.Consumer ---");
            Console.WriteLine("This application uses classes from the MyDotNetApp project.");

            // --- Using the Referenced Project's Classes ---

            // 1. Create an instance of the service from the referenced project
            //    (In real apps, use Dependency Injection)
            IDataService dataService = new DataService();
            Console.WriteLine("\nCreated DataService instance from MyDotNetApp.Services.");

            try
            {
                // 2. Call methods on the service
                Console.WriteLine("\nFetching all people using DataService...");
                List<Person> people = await dataService.GetPeopleAsync(); // Await the async call

                if (people.Any())
                {
                    Console.WriteLine($"Successfully fetched {people.Count} people:");
                    foreach (Person person in people)
                    {
                        // Use the Person object (defined in MyDotNetApp.Models)
                        // and its properties/methods (like ToString).
                        Console.WriteLine($"- {person.ToString()}");

                        // You can also access individual properties directly
                        // Console.WriteLine($"  - First Name: {person.FirstName}");
                    }
                }
                else
                {
                    Console.WriteLine("No people data was returned by the service.");
                }

                // 3. Use other service methods
                string lastNameToSearch = "Smith";
                Console.WriteLine($"\nFinding people with last name '{lastNameToSearch}'...");
                IEnumerable<Person> smiths = dataService.FindPeopleByLastName(lastNameToSearch);
                Console.WriteLine($"Found {smiths.Count()} person(s):"); // .Count() executes the LINQ query
                foreach(var smith in smiths)
                {
                     Console.WriteLine($"- {smith.FullName}");
                }

                // 4. Directly create instances of models from the referenced project
                Console.WriteLine("\nCreating a new Person instance directly...");
                var newPerson = new Person(99, "Jane", "Doe", new DateTime(1995, 11, 30));
                Console.WriteLine($"Created: {newPerson.FullName}, Age: {newPerson.Age}");
                // Note: This newPerson is local to this consumer app;
                // it's not automatically added to the DataService's internal list.

            }
            catch (Exception ex)
            {
                Console.WriteLine($"\n[ERROR] An error occurred while using the DataService: {ex.Message}");
                // Consider logging ex.ToString() for full details
            }

            Console.WriteLine("\n--- MyDotNetApp.Consumer Finished ---");
            Console.WriteLine("Press any key to exit.");
            Console.ReadKey();
        }
    }
}
