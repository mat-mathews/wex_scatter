// --- Person.cs ---
// Typically placed in a 'Models' folder or similar namespace

// Namespaces organize code and prevent naming conflicts
using System; // Provides fundamental types like string, DateTime, etc.

namespace MyDotNetApp.Models
{
    /// <summary>
    /// Represents a person. Demonstrates basic class structure.
    /// XML documentation comments like this are used for generating help files
    /// and providing IntelliSense information.
    /// </summary>
    public class Person // 'public' makes it accessible from other parts of the application
    {
        // --- Properties ---
        // Auto-implemented properties are the most common way to define properties.
        // The compiler generates the backing field automatically.
        public int Id { get; set; } // Integer property for unique identification
        public string FirstName { get; set; } = string.Empty; // String property, initialized to empty
        public string LastName { get; set; } = string.Empty; // String property, initialized to empty
        public DateTime DateOfBirth { get; set; } // DateTime property

        // Read-only calculated property using expression-bodied syntax (C# 6+)
        public string FullName => $"{FirstName} {LastName}";

        // Read-only property with a getter block
        public int Age
        {
            get
            {
                DateTime today = DateTime.Today;
                int age = today.Year - DateOfBirth.Year;
                // Adjust if birthday hasn't occurred yet this year
                if (DateOfBirth.Date > today.AddYears(-age))
                {
                    age--;
                }
                return age;
            }
        }

        // --- Constructors ---
        // Default constructor (parameterless) - often needed by frameworks (like EF Core, serializers)
        public Person() { }

        // Parameterized constructor for easier object initialization
        public Person(int id, string firstName, string lastName, DateTime dateOfBirth)
        {
            // 'this' refers to the current instance of the class
            this.Id = id;
            this.FirstName = firstName;
            this.LastName = lastName;
            this.DateOfBirth = dateOfBirth;
        }

        // --- Methods ---
        /// <summary>
        /// Returns a string representation of the Person object.
        /// Overriding base class methods is common.
        /// </summary>
        /// <returns>A formatted string with person details.</returns>
        public override string ToString()
        {
            // String interpolation ($) simplifies formatting strings
            return $"ID: {Id}, Name: {FullName}, DoB: {DateOfBirth:yyyy-MM-dd}, Age: {Age}";
        }

        /// <summary>
        /// A simple example method.
        /// </summary>
        public void PrintGreeting()
        {
            Console.WriteLine($"Hello, my name is {FullName}!");
        }
    }
}