// --- Program.cs ---
// The main entry point for the application

using System;
using System.Collections.Generic;
using System.Linq; // Needed for ToList() if using IEnumerable result directly
using System.Threading.Tasks;
using MyDotNetApp.Models; // Use the models
using MyDotNetApp.Services; // Use the services

namespace MyDotNetApp
{
    class Program
    {
        // async Task Main allows using await directly in the main entry point
        static async Task Main(string[] args)
        {
            Console.WriteLine("Starting DotNet App Demo...");

            // Dependency Injection is common in real apps, but here we instantiate directly
            IDataService dataService = new DataService();

            try
            {
                // --- Using the Service ---
                Console.WriteLine("\n--- Getting All People (Async) ---");
                List<Person> allPeople = await dataService.GetPeopleAsync(); // Use await for async methods
                foreach (var person in allPeople)
                {
                    Console.WriteLine(person.ToString()); // Uses the overridden ToString() method
                    // person.PrintGreeting(); // Calling another method from Person
                }

                Console.WriteLine("\n--- Finding People by Last Name ---");
                string searchLastName = "Smith";
                IEnumerable<Person> smiths = dataService.FindPeopleByLastName(searchLastName);
                // Use ToList() to execute the LINQ query immediately and get a list
                List<Person> smithList = smiths.ToList();
                Console.WriteLine($"Found {smithList.Count} person(s) with last name '{searchLastName}':");
                foreach (var smith in smithList)
                {
                    Console.WriteLine($"- {smith.FullName}");
                }

                // Add a person that might cause an error during processing
                allPeople.Add(new Person(4, "Error", "User", new DateTime(1995, 1, 1)));

                Console.WriteLine("\n--- Processing People Data ---");
                dataService.ProcessPeopleData(allPeople);

            }
            catch (ArgumentNullException ex) // Catch specific exceptions
            {
                Console.WriteLine($"[FATAL ERROR] Invalid argument: {ex.Message}");
            }
            catch (Exception ex) // Catch any other unexpected errors at the top level
            {
                Console.WriteLine($"[FATAL ERROR] An unexpected application error occurred: {ex.Message}");
                // In a real app, log the full exception details (ex.ToString())
            }

            Console.WriteLine("\nDotNet App Demo finished. Press any key to exit.");
            Console.ReadKey();
        }
    }
}