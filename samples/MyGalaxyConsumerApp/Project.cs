using System;
using GalaxyWorks.Data;

namespace MyGalaxyConsumerApp
{
    internal class Program
    {
        static void Main(string[] args)
        {
            Console.WriteLine("Hello from MyGalaxyConsumerApp!");

            // Example of using a class from GalaxyWorks.Data
            // This assumes PortalDataService has a public constructor and a method.
            try
            {
                PortalDataService dataService = new PortalDataService();
                Console.WriteLine("Successfully created an instance of PortalDataService.");

            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error interacting with PortalDataService: {ex.Message}");
            }

            Console.WriteLine("Press any key to exit.");
            Console.ReadKey();
        }
    }
}