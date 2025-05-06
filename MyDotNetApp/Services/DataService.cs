// --- DataService.cs ---
// Typically placed in a 'Services' folder or similar namespace

using System;
using System.Collections.Generic; // Required for List<T>, Dictionary<TKey, TValue>
using System.Linq; // Required for LINQ extension methods (Where, Select, etc.)
using System.Threading.Tasks; // Required for asynchronous programming (Task, async, await)
using MyDotNetApp.Models; // Using the Person model defined above

namespace MyDotNetApp.Services
{
    // Interfaces define contracts that classes can implement
    public interface IDataService
    {
        Task<List<Person>> GetPeopleAsync();
        IEnumerable<Person> FindPeopleByLastName(string lastName);
        void ProcessPeopleData(List<Person> people);
    }

    /// <summary>
    /// Simulates a service responsible for retrieving and processing Person data.
    /// Demonstrates common service patterns, collections, LINQ, async/await, and error handling.
    /// </summary>
    public class DataService : IDataService // Implementing the interface
    {
        // Private field to hold data (in a real app, this might come from a database)
        private List<Person> _peopleStore = new List<Person>();

        // Constructor - could be used for dependency injection (e.g., injecting a database context)
        public DataService()
        {
            // Initialize with some sample data
            _peopleStore.AddRange(new[] {
                new Person(1, "Alice", "Smith", new DateTime(1990, 5, 15)),
                new Person(2, "Bob", "Johnson", new DateTime(1985, 8, 22)),
                new Person(3, "Charlie", "Smith", new DateTime(2001, 1, 10))
            });
        }

        /// <summary>
        /// Asynchronously retrieves a list of people (simulating I/O).
        /// Demonstrates async/await pattern.
        /// </summary>
        /// <returns>A Task representing the asynchronous operation, containing a List of Person.</returns>
        public async Task<List<Person>> GetPeopleAsync()
        {
            Console.WriteLine("Simulating fetching data asynchronously...");
            // Simulate an asynchronous delay (like network or database latency)
            await Task.Delay(50); // Non-blocking delay for 50 milliseconds
            Console.WriteLine("Data fetch complete.");
            // Return a copy of the list
            return new List<Person>(_peopleStore);
        }

        /// <summary>
        /// Finds people matching a specific last name using LINQ.
        /// Demonstrates LINQ query syntax and deferred execution (IEnumerable).
        /// </summary>
        /// <param name="lastName">The last name to search for.</param>
        /// <returns>An IEnumerable of matching Person objects.</returns>
        public IEnumerable<Person> FindPeopleByLastName(string lastName)
        {
            // Basic input validation
            if (string.IsNullOrWhiteSpace(lastName))
            {
                // Returning an empty collection is often preferred over null
                return Enumerable.Empty<Person>();
            }

            // LINQ query (Method Syntax)
            // 'Where' filters the collection based on a condition (lambda expression)
            // StringComparison.OrdinalIgnoreCase ensures case-insensitive comparison
            var query = _peopleStore.Where(p =>
                p.LastName.Equals(lastName, StringComparison.OrdinalIgnoreCase));

            // The query is executed only when iterated (e.g., in a foreach loop or ToList())
            return query;
        }

        /// <summary>
        /// Processes a list of people, demonstrating control flow and error handling.
        /// </summary>
        /// <param name="people">The list of people to process.</param>
        public void ProcessPeopleData(List<Person> people)
        {
            // Check for null input
            if (people == null)
            {
                // Throwing exceptions is common for unrecoverable errors or invalid arguments
                throw new ArgumentNullException(nameof(people), "Input list cannot be null.");
            }

            Console.WriteLine($"\nProcessing {people.Count} people:");

            // foreach loop iterates over collections
            foreach (var person in people)
            {
                // try-catch block handles potential exceptions during processing
                try
                {
                    // if-else statement for conditional logic
                    if (person.Age >= 18)
                    {
                        Console.WriteLine($"- {person.FullName} is an adult (Age: {person.Age}).");
                    }
                    else
                    {
                        Console.WriteLine($"- {person.FullName} is a minor (Age: {person.Age}).");
                    }

                    // Example of potentially problematic operation
                    if (person.LastName == "Error")
                    {
                        throw new InvalidOperationException($"Simulated processing error for {person.FullName}");
                    }
                }
                catch (InvalidOperationException ex)
                {
                    Console.WriteLine($"[WARN] Could not process {person.FullName}: {ex.Message}");
                    // Continue processing other people
                }
                catch (Exception ex) // Catching general exceptions (use specific ones when possible)
                {
                    Console.WriteLine($"[ERROR] An unexpected error occurred for {person.FullName}: {ex.Message}");
                    // Depending on severity, you might re-throw, log, or stop processing
                }
                finally
                {
                    // The 'finally' block always executes, whether an exception occurred or not.
                    // Useful for cleanup (e.g., closing files, releasing resources).
                    // Console.WriteLine($"Finished processing entry for {person.FullName}.");
                }
            }
        }
    }
}