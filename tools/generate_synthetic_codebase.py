"""Generate a synthetic .NET monolith for scatter benchmarking.

Creates a realistic directory tree of .csproj and .cs files that exercise
all scatter code paths: type declarations, using statements, project
references, sproc references, DbSet patterns, SQL statements, comments.

Usage:
    python tools/generate_synthetic_codebase.py --projects 500 --output /tmp/synthetic_monolith
    python tools/generate_synthetic_codebase.py --projects 100 --files-per-project 20 --output /tmp/small_test
    python tools/generate_synthetic_codebase.py --preset large --output /tmp/large_monolith
"""
import argparse
import random
import shutil
import sys
import textwrap
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS = {
    "small": {"projects": 100, "files_per_project": 10, "coupling_pct": 0.05, "sproc_pct": 0.15, "avg_file_kb": 8},
    "medium": {"projects": 250, "files_per_project": 20, "coupling_pct": 0.04, "sproc_pct": 0.12, "avg_file_kb": 15},
    "large": {"projects": 500, "files_per_project": 30, "coupling_pct": 0.03, "sproc_pct": 0.10, "avg_file_kb": 20},
    "xlarge": {"projects": 800, "files_per_project": 40, "coupling_pct": 0.02, "sproc_pct": 0.08, "avg_file_kb": 25},
}

# Namespace domains to simulate real organizational structure
DOMAINS = [
    "GalaxyWorks", "Portal", "Billing", "Auth", "Reporting",
    "Integration", "Notifications", "Admin", "Scheduling", "DataAccess",
    "Common", "Utilities", "Logging", "Security", "Workflow",
    "Documents", "Imaging", "Export", "Import", "BatchJobs",
]

SUBDOMAIN_SUFFIXES = [
    "Core", "Data", "Web", "Api", "Service", "Models",
    "Client", "Shared", "Tests", "Contracts", "Events",
    "Handlers", "Processors", "Validators", "Mappers",
]

# Subdirectories within projects (mimics real .NET folder structure)
PROJECT_SUBDIRS = ["Models", "Services", "Controllers", "Repositories", "Helpers", ""]

TYPE_KINDS = ["class", "interface", "struct", "enum", "record"]
TYPE_KIND_WEIGHTS = [0.55, 0.15, 0.10, 0.10, 0.10]

ACCESS_MODIFIERS = ["public", "internal"]
CLASS_MODIFIERS = ["", "abstract ", "sealed ", "static ", "partial "]
CLASS_MODIFIER_WEIGHTS = [0.50, 0.15, 0.15, 0.10, 0.10]

FRAMEWORKS = ["net8.0", "net6.0", "net48", "v4.7.2", "v4.6.1"]
FRAMEWORK_WEIGHTS = [0.30, 0.20, 0.25, 0.15, 0.10]

OUTPUT_TYPES = ["Library", "Exe", "Library", "Library", "Library"]  # mostly libraries

SPROC_PREFIXES = ["sp_", "usp_"]
SPROC_VERBS = ["Get", "Insert", "Update", "Delete", "Find", "Search", "Process", "Validate"]
SPROC_NOUNS = [
    "User", "Account", "Order", "Payment", "Invoice", "Customer",
    "Product", "Configuration", "Portal", "Report", "Document",
    "Schedule", "Notification", "Permission", "Role", "Session",
    "Transaction", "Audit", "Log", "Setting", "Preference",
]

TABLE_NAMES = [
    "Users", "Accounts", "Orders", "Payments", "Invoices",
    "Customers", "Products", "Configurations", "Reports", "Documents",
    "Schedules", "AuditLogs", "Sessions", "Roles", "Permissions",
]

# Realistic method body templates for padding files to target size
_METHOD_TEMPLATES = [
    textwrap.dedent("""\
        /// <summary>
        /// Validates the {name} before processing.
        /// Checks required fields, business rules, and data integrity.
        /// </summary>
        /// <param name="input">The input to validate.</param>
        /// <returns>True if valid, false otherwise.</returns>
        public bool Validate{name}({name}Request input)
        {{
            if (input == null)
                throw new ArgumentNullException(nameof(input));

            if (string.IsNullOrWhiteSpace(input.Name))
            {{
                _logger.LogWarning("Validation failed: Name is required for {{Type}}", nameof({name}));
                return false;
            }}

            /* Multi-line validation logic:
             * 1. Check field lengths
             * 2. Validate business rules
             * 3. Cross-reference with existing data */
            if (input.Name.Length > 255)
            {{
                _logger.LogWarning("Validation failed: Name exceeds maximum length");
                return false;
            }}

            // Additional business rule checks
            var existingItems = _repository.FindByName(input.Name);
            if (existingItems.Any(x => x.Id != input.Id))
            {{
                _logger.LogWarning("Duplicate name detected: {{Name}}", input.Name);
                return false;
            }}

            return true;
        }}"""),
    textwrap.dedent("""\
        /// <summary>
        /// Processes the {name} operation asynchronously.
        /// </summary>
        public async Task<{name}Result> Process{name}Async(
            {name}Request request,
            CancellationToken cancellationToken = default)
        {{
            _logger.LogInformation("Processing {{Operation}} for {{Id}}",
                nameof({name}), request.Id);

            // Validate input parameters
            if (request == null)
                throw new ArgumentNullException(nameof(request));

            try
            {{
                /* Begin transaction scope for data consistency.
                 * This ensures all database operations either
                 * complete successfully or roll back together. */
                using var scope = new TransactionScope(
                    TransactionScopeAsyncFlowOption.Enabled);

                var entity = await _repository
                    .GetByIdAsync(request.Id, cancellationToken)
                    .ConfigureAwait(false);

                if (entity == null)
                {{
                    _logger.LogWarning("Entity not found: {{Id}}", request.Id);
                    return new {name}Result {{ Success = false, ErrorCode = "NOT_FOUND" }};
                }}

                // Apply business logic transformations
                entity.UpdatedAt = DateTime.UtcNow;
                entity.UpdatedBy = request.UserId;
                entity.Status = CalculateNewStatus(entity, request);

                await _repository.UpdateAsync(entity, cancellationToken);
                scope.Complete();

                _logger.LogInformation("Successfully processed {{Operation}}", nameof({name}));
                return new {name}Result {{ Success = true, Data = entity }};
            }}
            catch (DbUpdateConcurrencyException ex)
            {{
                _logger.LogError(ex, "Concurrency conflict processing {{Operation}}", nameof({name}));
                return new {name}Result {{ Success = false, ErrorCode = "CONCURRENCY_CONFLICT" }};
            }}
        }}"""),
    textwrap.dedent("""\
        /// <summary>
        /// Retrieves a filtered and paginated list of {name} entities.
        /// </summary>
        /// <param name="filter">Filter criteria.</param>
        /// <param name="page">Page number (1-based).</param>
        /// <param name="pageSize">Items per page.</param>
        public async Task<PagedResult<{name}Dto>> Get{name}ListAsync(
            {name}Filter filter, int page = 1, int pageSize = 25)
        {{
            // Ensure valid pagination parameters
            page = Math.Max(1, page);
            pageSize = Math.Clamp(pageSize, 1, 100);

            var query = _dbContext.Set<{name}Entity>().AsQueryable();

            // Apply filters conditionally
            if (!string.IsNullOrEmpty(filter.SearchTerm))
            {{
                var term = filter.SearchTerm.ToLowerInvariant();
                query = query.Where(x =>
                    x.Name.ToLower().Contains(term) ||
                    x.Description.ToLower().Contains(term));
            }}

            if (filter.Status.HasValue)
                query = query.Where(x => x.Status == filter.Status.Value);

            if (filter.CreatedAfter.HasValue)
                query = query.Where(x => x.CreatedAt >= filter.CreatedAfter.Value);

            // Get total count for pagination
            var totalCount = await query.CountAsync();

            // Apply sorting and pagination
            var items = await query
                .OrderByDescending(x => x.CreatedAt)
                .Skip((page - 1) * pageSize)
                .Take(pageSize)
                .Select(x => new {name}Dto
                {{
                    Id = x.Id,
                    Name = x.Name,
                    Status = x.Status.ToString(),
                    CreatedAt = x.CreatedAt,
                }})
                .ToListAsync();

            return new PagedResult<{name}Dto>
            {{
                Items = items,
                TotalCount = totalCount,
                Page = page,
                PageSize = pageSize,
            }};
        }}"""),
    textwrap.dedent("""\
        // Configuration and dependency injection setup
        private readonly ILogger<{name}Service> _logger;
        private readonly IConfiguration _configuration;
        private readonly IMemoryCache _cache;
        private readonly TimeSpan _cacheDuration;

        /*
         * Constructor initializes all dependencies.
         * Uses the options pattern for configuration binding.
         * Cache duration is configurable via appsettings.json.
         */
        public {name}Service(
            ILogger<{name}Service> logger,
            IConfiguration configuration,
            IMemoryCache cache)
        {{
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _configuration = configuration ?? throw new ArgumentNullException(nameof(configuration));
            _cache = cache ?? throw new ArgumentNullException(nameof(cache));
            _cacheDuration = TimeSpan.FromMinutes(
                _configuration.GetValue<int>("{name}:CacheDurationMinutes", 30));
        }}

        /// <summary>
        /// Gets or creates a cached {name} instance.
        /// Uses IMemoryCache with sliding expiration.
        /// </summary>
        public async Task<{name}Data> GetCached{name}Async(string key)
        {{
            var cacheKey = $"{name}_{{key}}";

            if (_cache.TryGetValue(cacheKey, out {name}Data cached))
            {{
                _logger.LogDebug("Cache hit for {{Key}}", cacheKey);
                return cached;
            }}

            _logger.LogDebug("Cache miss for {{Key}}, loading from source", cacheKey);

            var data = await LoadFrom{name}SourceAsync(key);

            var cacheOptions = new MemoryCacheEntryOptions()
                .SetSlidingExpiration(_cacheDuration)
                .SetAbsoluteExpiration(TimeSpan.FromHours(4));

            _cache.Set(cacheKey, data, cacheOptions);
            return data;
        }}"""),
]

# Property block template for padding
_PROPERTY_BLOCK = textwrap.dedent("""\
        public int {name}Id {{ get; set; }}
        public string {name}Name {{ get; set; }}
        public string {name}Description {{ get; set; }}
        public DateTime {name}CreatedAt {{ get; set; }}
        public DateTime? {name}UpdatedAt {{ get; set; }}
        public string {name}CreatedBy {{ get; set; }}
        public bool Is{name}Active {{ get; set; }}
        public int {name}SortOrder {{ get; set; }}
""")


# ---------------------------------------------------------------------------
# Name generators
# ---------------------------------------------------------------------------

def generate_project_names(n: int) -> list[str]:
    """Generate realistic .NET project names."""
    names = set()
    for domain in DOMAINS:
        for suffix in SUBDOMAIN_SUFFIXES:
            names.add(f"{domain}.{suffix}")
            if len(names) >= n:
                return sorted(names)[:n]

    # Need more — add numbered variants
    i = 2
    while len(names) < n:
        domain = random.choice(DOMAINS)
        suffix = random.choice(SUBDOMAIN_SUFFIXES)
        names.add(f"{domain}.{suffix}{i}")
        i += 1

    return sorted(names)[:n]


def generate_type_name(project_name: str, index: int) -> tuple[str, str]:
    """Generate a type name and its kind. Returns (name, kind).

    Uses project_name prefix to avoid cross-project collisions.
    """
    kind = random.choices(TYPE_KINDS, weights=TYPE_KIND_WEIGHTS, k=1)[0]
    # Use full dotted name (sanitized) as prefix to avoid collisions
    safe_prefix = project_name.replace(".", "_")

    suffixes = {
        "class": ["Service", "Repository", "Handler", "Processor", "Manager", "Factory", "Builder", "Provider", "Controller", "Helper"],
        "interface": ["Repository", "Service", "Handler", "Provider", "Factory", "Validator"],
        "struct": ["Info", "Result", "Key", "Point", "Range", "Options"],
        "enum": ["Type", "Status", "Mode", "Level", "Category", "State"],
        "record": ["Request", "Response", "Event", "Command", "Dto", "ViewModel"],
    }

    prefix = "I" if kind == "interface" else ""
    suffix = random.choice(suffixes[kind])
    name = f"{prefix}{safe_prefix}_{suffix}{index if index > 0 else ''}"

    return name, kind


def generate_sproc_name() -> str:
    prefix = random.choice(SPROC_PREFIXES)
    verb = random.choice(SPROC_VERBS)
    noun = random.choice(SPROC_NOUNS)
    return f"dbo.{prefix}{verb}{noun}"


# ---------------------------------------------------------------------------
# File content generators
# ---------------------------------------------------------------------------

def _generate_padding_content(target_bytes: int, type_name: str) -> str:
    """Generate realistic C# padding to reach target file size.

    Uses method templates and property blocks with comments to create
    content that exercises scatter's regex patterns (type names, comments,
    string literals) at realistic file sizes.
    """
    lines = []
    current_bytes = 0
    method_idx = 0
    prop_names = ["Item", "Record", "Entry", "Detail", "Config", "Param", "Field", "Attr"]

    while current_bytes < target_bytes:
        # Alternate between method templates and property blocks
        if method_idx < len(_METHOD_TEMPLATES):
            block = _METHOD_TEMPLATES[method_idx].format(name=type_name.split("_")[-1])
            method_idx += 1
        else:
            pname = random.choice(prop_names) + str(random.randint(1, 99))
            block = _PROPERTY_BLOCK.format(name=pname)

        lines.append("")
        lines.append(block)
        current_bytes += len(block.encode("utf-8"))

    return "\n".join(lines)


def generate_csproj(
    project_name: str,
    references: list[str],
    framework: str,
    output_type: str,
) -> str:
    """Generate a .csproj file."""
    ref_items = ""
    if references:
        ref_lines = []
        for ref in references:
            ref_lines.append(f'    <ProjectReference Include="..\\{ref}\\{ref}.csproj" />')
        ref_items = "\n  <ItemGroup>\n" + "\n".join(ref_lines) + "\n  </ItemGroup>"

    namespace = project_name.replace("-", ".").replace(" ", ".")

    if framework.startswith("v"):
        # Framework-style .csproj
        return (
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
            f'  <PropertyGroup>\n'
            f'    <TargetFrameworkVersion>{framework}</TargetFrameworkVersion>\n'
            f'    <RootNamespace>{namespace}</RootNamespace>\n'
            f'    <AssemblyName>{project_name}</AssemblyName>\n'
            f'    <OutputType>{output_type}</OutputType>\n'
            f'  </PropertyGroup>{ref_items}\n'
            f'</Project>\n'
        )
    else:
        # SDK-style .csproj
        return (
            f'<Project Sdk="Microsoft.NET.Sdk">\n'
            f'  <PropertyGroup>\n'
            f'    <TargetFramework>{framework}</TargetFramework>\n'
            f'    <RootNamespace>{namespace}</RootNamespace>\n'
            f'    <AssemblyName>{project_name}</AssemblyName>\n'
            f'    <OutputType>{output_type}</OutputType>\n'
            f'  </PropertyGroup>{ref_items}\n'
            f'</Project>\n'
        )


def generate_cs_file(
    project_name: str,
    file_index: int,
    types: list[tuple[str, str]],
    using_namespaces: list[str],
    sproc_names: list[str],
    include_db_patterns: bool = False,
    target_size_bytes: int = 0,
) -> str:
    """Generate a .cs file with type declarations, usings, and optional DB patterns."""
    namespace = project_name.replace("-", ".").replace(" ", ".")

    lines = []

    # Using statements
    standard_usings = ["System", "System.Collections.Generic", "System.Linq", "System.Threading.Tasks"]
    all_usings = sorted(set(standard_usings + using_namespaces))
    for ns in all_usings:
        lines.append(f"using {ns};")

    lines.append("")
    lines.append(f"namespace {namespace}")
    lines.append("{")

    for type_name, kind in types:
        access = random.choice(ACCESS_MODIFIERS)
        modifier = ""
        if kind == "class":
            modifier = random.choices(CLASS_MODIFIERS, weights=CLASS_MODIFIER_WEIGHTS, k=1)[0]

        if kind == "interface":
            lines.append(f"    {access} {kind} {type_name}")
            lines.append("    {")
            lines.append(f"        /// <summary>Processes the {type_name[1:]} operation.</summary>")
            lines.append(f"        void Process{type_name[1:]}();")
            lines.append("")
            lines.append(f"        /// <summary>Validates the {type_name[1:]} state.</summary>")
            lines.append(f"        bool Validate{type_name[1:]}();")
            lines.append("    }")
        elif kind == "enum":
            lines.append(f"    /// <summary>Defines the possible states for {type_name}.</summary>")
            lines.append(f"    {access} {kind} {type_name}")
            lines.append("    {")
            lines.append("        None = 0,")
            lines.append("        Active = 1,")
            lines.append("        Inactive = 2,")
            lines.append("        Pending = 3,")
            lines.append("        Processing = 4,")
            lines.append("        Completed = 5,")
            lines.append("        Failed = 6,")
            lines.append("    }")
        elif kind == "struct":
            lines.append(f"    {access} {kind} {type_name}")
            lines.append("    {")
            lines.append(f"        public int Id {{ get; set; }}")
            lines.append(f"        public string Name {{ get; set; }}")
            lines.append(f"        public DateTime CreatedAt {{ get; set; }}")
            lines.append("    }")
        elif kind == "record":
            lines.append(f"    /// <summary>Immutable data transfer record for {type_name}.</summary>")
            lines.append(f"    {access} {kind} {type_name}(string Value, int Count, DateTime Timestamp);")
        else:
            # class
            base_class = ""
            if modifier == "abstract ":
                base_class = ""
            elif random.random() < 0.2:
                base_class = " : IDisposable"

            lines.append(f"    {access} {modifier}{kind} {type_name}{base_class}")
            lines.append("    {")

            # Sproc references in string literals
            for sproc in sproc_names:
                lines.append(f'        private const string SprocName = "{sproc}";')
                lines.append(f"        // Execute stored procedure {sproc}")

            # DB patterns
            if include_db_patterns:
                table = random.choice(TABLE_NAMES)
                lines.append(f'        private readonly string _sql = "SELECT * FROM {table} WHERE Id = @Id";')
                if random.random() < 0.3:
                    lines.append(f'        private readonly string _connStr = "Data Source=server.db;Database=MyDB";')

            # Method with body
            lines.append(f"        public void Execute()")
            lines.append("        {")
            lines.append(f"            // {type_name} implementation")
            lines.append("        }")

            # Add padding to reach target size
            if target_size_bytes > 0:
                current_size = sum(len(line.encode("utf-8")) + 1 for line in lines)
                remaining = target_size_bytes - current_size - 100  # leave room for closing braces
                if remaining > 0:
                    padding = _generate_padding_content(remaining, type_name)
                    lines.append(padding)

            lines.append("    }")

        lines.append("")

    # DbContext pattern (for DB scanner to find)
    if include_db_patterns and random.random() < 0.3:
        ctx_name = f"{project_name.split('.')[-1]}Context"
        lines.append(f"    public class {ctx_name} : DbContext")
        lines.append("    {")
        for type_name, kind in types:
            if kind == "class" and not type_name.startswith("I"):
                lines.append(f"        public DbSet<{type_name}> {type_name}s {{ get; set; }}")
        lines.append("    }")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def generate_type_usage_file(
    project_name: str,
    file_index: int,
    foreign_types: list[str],
    using_namespaces: list[str],
    target_size_bytes: int = 0,
) -> str:
    """Generate a .cs file that references types from other projects."""
    namespace = project_name.replace("-", ".").replace(" ", ".")

    lines = []
    standard_usings = ["System", "System.Collections.Generic", "System.Linq"]
    all_usings = sorted(set(standard_usings + using_namespaces))
    for ns in all_usings:
        lines.append(f"using {ns};")

    lines.append("")
    lines.append(f"namespace {namespace}")
    lines.append("{")

    class_name = f"Consumer{file_index}"
    lines.append(f"    /// <summary>")
    lines.append(f"    /// Consumes services from referenced projects.")
    lines.append(f"    /// Auto-generated for benchmark testing.")
    lines.append(f"    /// </summary>")
    lines.append(f"    public class {class_name}")
    lines.append("    {")

    for ft in foreign_types:
        field_name = f"_{ft[0].lower() + ft[1:]}"
        lines.append(f"        private readonly {ft} {field_name};")

    lines.append("")

    # Constructor with DI
    if foreign_types:
        params = ", ".join(f"{ft} {ft[0].lower() + ft[1:]}" for ft in foreign_types)
        lines.append(f"        public {class_name}({params})")
        lines.append("        {")
        for ft in foreign_types:
            field_name = f"_{ft[0].lower() + ft[1:]}"
            param_name = ft[0].lower() + ft[1:]
            lines.append(f"            {field_name} = {param_name} ?? throw new ArgumentNullException(nameof({param_name}));")
        lines.append("        }")
        lines.append("")

    # Methods that use the foreign types
    for ft in foreign_types:
        field_name = f"_{ft[0].lower() + ft[1:]}"
        lines.append(f"        public {ft} Get{ft}() => {field_name};")

    # Add padding to reach target size
    if target_size_bytes > 0:
        current_size = sum(len(line.encode("utf-8")) + 1 for line in lines)
        remaining = target_size_bytes - current_size - 50
        if remaining > 0:
            padding = _generate_padding_content(remaining, class_name)
            lines.append(padding)

    lines.append("    }")
    lines.append("}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate_codebase(
    output_dir: Path,
    num_projects: int,
    files_per_project: int,
    coupling_pct: float,
    sproc_pct: float,
    avg_file_kb: int = 15,
    seed: int = 42,
):
    """Generate the full synthetic codebase."""
    random.seed(seed)

    # Clean output directory if it exists
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    project_names = generate_project_names(num_projects)
    num_projects = len(project_names)

    target_file_bytes = avg_file_kb * 1024

    # Pre-generate all types per project (5-15 types each for realism)
    project_types: dict[str, list[tuple[str, str]]] = {}
    all_types: dict[str, str] = {}  # type_name -> owning project

    for pname in project_names:
        types = []
        num_types = random.randint(5, 15)
        for i in range(num_types):
            tname, tkind = generate_type_name(pname, i)
            # Names include project prefix, so collisions are extremely unlikely
            if tname not in all_types:
                types.append((tname, tkind))
                all_types[tname] = pname
        project_types[pname] = types

    # Generate project references (coupling)
    project_refs: dict[str, list[str]] = {p: [] for p in project_names}

    # Hub projects: first 10% are "core" libraries everyone references
    num_hubs = max(3, int(num_projects * 0.10))
    hub_projects = project_names[:num_hubs]

    for pname in project_names:
        if pname in hub_projects:
            continue  # hubs don't reference many things

        # Reference 1-3 hub projects
        num_hub_refs = random.randint(1, min(3, num_hubs))
        hub_refs = random.sample(hub_projects, num_hub_refs)
        project_refs[pname].extend(hub_refs)

        # Reference some non-hub projects based on coupling_pct
        other_projects = [p for p in project_names if p != pname and p not in hub_refs]
        num_other_refs = int(len(other_projects) * coupling_pct)
        if num_other_refs > 0:
            other_refs = random.sample(other_projects, min(num_other_refs, len(other_projects)))
            project_refs[pname].extend(other_refs)

    # Generate sproc names (shared across projects)
    num_sprocs = max(10, int(num_projects * 0.15))
    sproc_pool = list(set(generate_sproc_name() for _ in range(num_sprocs)))

    # Assign sprocs to projects
    project_sprocs: dict[str, list[str]] = {}
    for pname in project_names:
        if random.random() < sproc_pct:
            num_sp = random.randint(1, 4)
            project_sprocs[pname] = random.sample(sproc_pool, min(num_sp, len(sproc_pool)))
        else:
            project_sprocs[pname] = []

    # Force some sprocs to be shared by 3+ projects (triggers db_hotspot)
    shared_sprocs = random.sample(sproc_pool, min(5, len(sproc_pool)))
    shared_targets = random.sample(project_names, min(15, num_projects))
    for sproc in shared_sprocs:
        targets = random.sample(shared_targets, random.randint(3, 6))
        for t in targets:
            if sproc not in project_sprocs.get(t, []):
                project_sprocs.setdefault(t, []).append(sproc)

    # Stats tracking
    total_cs_files = 0
    total_csproj_files = 0
    total_bytes = 0

    # Generate each project
    for pname in project_names:
        project_dir = output_dir / pname
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in PROJECT_SUBDIRS:
            if subdir:
                (project_dir / subdir).mkdir(exist_ok=True)

        # Framework and output type
        framework = random.choices(FRAMEWORKS, weights=FRAMEWORK_WEIGHTS, k=1)[0]
        output_type = random.choice(OUTPUT_TYPES)

        # Write .csproj
        csproj_content = generate_csproj(pname, project_refs[pname], framework, output_type)
        csproj_path = project_dir / f"{pname}.csproj"
        csproj_path.write_text(csproj_content, encoding="utf-8")
        total_csproj_files += 1
        total_bytes += len(csproj_content.encode())

        # Using namespaces from referenced projects
        using_ns = [ref.replace("-", ".").replace(" ", ".") for ref in project_refs[pname]]

        types_for_project = project_types[pname]
        sprocs_for_project = project_sprocs.get(pname, [])

        # Split types across declaration files (1 type per file, like real codebases)
        num_declaration_files = len(types_for_project)
        num_consumer_files = max(0, files_per_project - num_declaration_files)

        # Type declaration files — placed in subdirectories
        for i, (tname, tkind) in enumerate(types_for_project):
            include_db = random.random() < 0.2
            sprocs_for_file = sprocs_for_project if i == 0 else []

            content = generate_cs_file(
                pname, i, [(tname, tkind)], using_ns, sprocs_for_file, include_db,
                target_size_bytes=target_file_bytes,
            )

            # Place in a subdirectory
            subdir = random.choice(PROJECT_SUBDIRS)
            parent = project_dir / subdir if subdir else project_dir
            cs_path = parent / f"{tname}.cs"
            cs_path.write_text(content, encoding="utf-8")
            total_cs_files += 1
            total_bytes += len(content.encode())

        # Consumer files (reference types from other projects)
        for i in range(num_consumer_files):
            foreign_types = []
            for ref in project_refs[pname]:
                ref_types = project_types.get(ref, [])
                if ref_types:
                    sample_size = min(random.randint(1, 3), len(ref_types))
                    for tname, tkind in random.sample(ref_types, sample_size):
                        if tkind in ("class", "struct", "record", "interface"):
                            foreign_types.append(tname)

            if not foreign_types:
                continue

            foreign_types = foreign_types[:8]

            content = generate_type_usage_file(
                pname, i, foreign_types, using_ns,
                target_size_bytes=target_file_bytes,
            )

            subdir = random.choice(PROJECT_SUBDIRS)
            parent = project_dir / subdir if subdir else project_dir
            cs_path = parent / f"Consumer{i}.cs"
            cs_path.write_text(content, encoding="utf-8")
            total_cs_files += 1
            total_bytes += len(content.encode())

    return {
        "projects": num_projects,
        "csproj_files": total_csproj_files,
        "cs_files": total_cs_files,
        "total_files": total_csproj_files + total_cs_files,
        "total_bytes": total_bytes,
        "total_types": len(all_types),
        "total_sprocs": len(sproc_pool),
        "hub_projects": num_hubs,
        "avg_file_kb": avg_file_kb,
        "output_dir": str(output_dir),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a synthetic .NET monolith for scatter benchmarking."
    )
    parser.add_argument("--output", "-o", type=str, required=True,
                        help="Output directory for generated codebase")
    parser.add_argument("--projects", "-p", type=int, default=None,
                        help="Number of projects to generate")
    parser.add_argument("--files-per-project", "-f", type=int, default=None,
                        help="Average .cs files per project")
    parser.add_argument("--coupling-pct", type=float, default=None,
                        help="Coupling density (0.0-1.0): fraction of other projects referenced")
    parser.add_argument("--sproc-pct", type=float, default=None,
                        help="Fraction of projects that reference stored procedures")
    parser.add_argument("--avg-file-kb", type=int, default=None,
                        help="Target average .cs file size in KB (default: preset-dependent)")
    parser.add_argument("--preset", choices=PRESETS.keys(), default=None,
                        help="Use a named preset (overridden by explicit flags)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")

    args = parser.parse_args()

    # Resolve parameters from preset + overrides
    params = PRESETS.get(args.preset, PRESETS["medium"]).copy()
    if args.projects is not None:
        params["projects"] = args.projects
    if args.files_per_project is not None:
        params["files_per_project"] = args.files_per_project
    if args.coupling_pct is not None:
        params["coupling_pct"] = args.coupling_pct
    if args.sproc_pct is not None:
        params["sproc_pct"] = args.sproc_pct
    if args.avg_file_kb is not None:
        params["avg_file_kb"] = args.avg_file_kb

    output_dir = Path(args.output)

    print(f"Generating synthetic codebase:")
    print(f"  Projects:          {params['projects']}")
    print(f"  Files/project:     {params['files_per_project']}")
    print(f"  Coupling density:  {params['coupling_pct']:.1%}")
    print(f"  Sproc density:     {params['sproc_pct']:.1%}")
    print(f"  Avg file size:     {params['avg_file_kb']} KB")
    print(f"  Output:            {output_dir}")
    print()

    t0 = time.perf_counter()

    stats = generate_codebase(
        output_dir=output_dir,
        num_projects=params["projects"],
        files_per_project=params["files_per_project"],
        coupling_pct=params["coupling_pct"],
        sproc_pct=params["sproc_pct"],
        avg_file_kb=params["avg_file_kb"],
        seed=args.seed,
    )

    elapsed = time.perf_counter() - t0

    print(f"Generated in {elapsed:.1f}s:")
    print(f"  Projects:     {stats['projects']}")
    print(f"  .csproj files: {stats['csproj_files']}")
    print(f"  .cs files:    {stats['cs_files']}")
    print(f"  Total size:   {stats['total_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  Unique types: {stats['total_types']}")
    print(f"  Sproc pool:   {stats['total_sprocs']}")
    print(f"  Hub projects: {stats['hub_projects']}")
    print(f"  Output:       {stats['output_dir']}")


if __name__ == "__main__":
    main()
