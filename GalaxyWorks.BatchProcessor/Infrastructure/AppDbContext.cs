using System.Data.Entity;
using GalaxyWorks.Data.Models;

namespace GalaxyWorks.BatchProcessor.Infrastructure
{
    public abstract class AppDbContext : DbContext
    {
        protected AppDbContext(string connectionString)
            : base(connectionString)
        {
        }

        public virtual DbSet<PortalConfiguration> PortalConfigurations { get; set; }
        public virtual DbSet<UserActivityLog> UserActivityLogs { get; set; }
        public virtual DbSet<SystemModule> SystemModules { get; set; }

        protected virtual void ConfigureModelBuilder(DbModelBuilder modelBuilder)
        {
            modelBuilder.Entity<PortalConfiguration>()
                .ToTable("PortalConfigurations", "dbo");

            modelBuilder.Entity<UserActivityLog>()
                .ToTable("UserActivityLogs", "dbo");
        }
    }
}
