# Getting Started

## Prerequisites

- Python 3.10+
- Git (for branch analysis mode)
- Access to .NET solution/project files you want to analyze

## Installation

Clone the repository and install dependencies:

```bash
git clone <repo-url>
cd wex_scatter

python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\Activate.ps1  # Windows

pip install -r requirements.txt
```

## Verify Installation

```bash
python scatter.py --help
```

You should see the available CLI options and analysis modes.

## Your First Analysis

### Target Project Analysis

The simplest mode — point Scatter at a `.csproj` file and a search scope:

```bash
python scatter.py \
  --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
  --search-scope .
```

This will:

1. Parse the target `.csproj` to extract its type declarations
2. Find all projects in the search scope that reference it
3. Filter by namespace usage and class consumption
4. Print a dependency report to the console

### Git Branch Analysis

Analyze what a feature branch touches:

```bash
python scatter.py \
  --branch-name feature/new-widget \
  --repo-path .
```

Scatter diffs the branch against its base, extracts changed C# types, and finds their consumers.

### Stored Procedure Analysis

Find which projects reference a database stored procedure:

```bash
python scatter.py \
  --stored-procedure "dbo.sp_InsertPortalConfiguration" \
  --search-scope .
```

## Next Steps

- [Usage Guide](usage.md) — full CLI reference and advanced options
- [Configuration](configuration.md) — customize behavior via YAML config
- [API Reference](api/index.md) — use Scatter as a library
