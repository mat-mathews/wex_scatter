# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Python Environment Setup
```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (creates .venv automatically)
uv sync

# Or without uv:
pip install .
```

### Running the Main Analysis Tool
```bash
# Git branch analysis (analyze changes between branches)
python scatter.py --branch-name feature/new-widget --repo-path .

# Target project analysis (find consumers of specific project)
python scatter.py --target-project ./samples/MyDotNetApp/MyDotNetApp.csproj --search-scope .

# Stored procedure analysis (find consumers via database dependencies)
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# With pipeline mapping (uses the included example CSV)
python scatter.py --target-project ./samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . --pipeline-csv examples/pipeline_to_app_mapping.csv

# Advanced analysis with AI summarization
python scatter.py --target-project ./samples/MyDotNetApp/MyDotNetApp.csproj --search-scope . --summarize-consumers --google-api-key YOUR_API_KEY --output-format json --output-file analysis_results.json
```

### Pipeline Artifact Parsing
```bash
# Parse Azure DevOps YAML pipelines to extract application mappings
python parse_pipeline_artifacts.py <search_directory> -o pipeline_to_app_mapping.csv
```

### .NET Development
```bash
# Build all C# projects
dotnet build

# Run a specific project
dotnet run --project samples/MyDotNetApp/MyDotNetApp.csproj

# Build specific project
dotnet build samples/GalaxyWorks.Data/GalaxyWorks.Data.csproj
```

## High-Level Architecture

### Core Analysis Tool (`scatter.py`)
The main application is a **source code dependency analyzer** that helps answer questions like "If I change this class, which other projects are actually using it?" It operates in three modes:

1. **Git Branch Analysis**: Compares feature branches against base branches, extracts C# type declarations from changed files, and finds consuming projects
2. **Target Project Analysis**: Analyzes a specific .csproj file to find all projects that reference and use its types/classes
3. **Stored Procedure Analysis**: Finds C# projects that reference specific stored procedures and analyzes their consumers

The tool uses regex pattern matching to identify C# type declarations (`class`, `struct`, `interface`, `enum`) and performs multi-level filtering:
- Direct project references (via `<ProjectReference>` in .csproj files)
- Namespace usage (via `using` statements)
- Class/method usage (text-based search with optional filters)

### Sample .NET Projects Structure
The `samples/` directory contains example .NET 8 projects demonstrating the analysis:

- **`samples/GalaxyWorks.Data/`**: Core data access library with `PortalDataService` class that calls stored procedures
- **`samples/MyDotNetApp/`**: Basic .NET console application
- **`samples/MyDotNetApp.Consumer/`**: Consumer application demonstrating dependencies
- **`samples/MyGalaxyConsumerApp/` & `samples/MyGalaxyConsumerApp2/`**: Example consumer applications that reference `GalaxyWorks.Data`

### Pipeline Integration
- **`parse_pipeline_artifacts.py`**: Utility for extracting application artifact mappings from Azure DevOps YAML pipeline files
- **`app_to_directory_mapping.json`**: Pre-generated mapping of application names to CI/CD pipeline names
- **`pipeline_to_app_mapping.csv`**: Output format for pipeline-to-application mappings

### Key Dependencies
- **GitPython**: For Git repository operations and branch analysis
- **google-generativeai**: Optional AI-powered code summarization via Google Gemini API
- **PyYAML & pandas**: For pipeline artifact parsing

### Analysis Output Formats
- **Console**: Human-readable reports with dependency relationships
- **CSV**: Tabular format with pipeline mappings and batch job verification
- **JSON**: Structured data with pipeline summaries and detailed results for programmatic use

### Optional Features
- **AI Summarization**: Uses Google Gemini API to generate 2-3 sentence summaries of relevant C# files in consuming projects
- **Pipeline Mapping**: Maps discovered consumer projects to their CI/CD pipelines via CSV lookup
- **Batch Job Verification**: Validates if consumer projects correspond to known batch jobs in app-config repositories

The tool is designed as a "proof-of-concept utility" for assessing blast radius and identifying integration dependencies before merging feature branches or deploying changes.

---

## Team Personas

Full persona definitions live in **[docs/PERSONAS.md](docs/PERSONAS.md)**. Read that file when asked to review, critique, or discuss code "as the team" or as any individual persona.

### Quick Reference

| Name | Role | Focus areas |
|------|------|-------------|
| **Priya Chandrasekaran** | Architect (20 yrs) | System design, coupling, domain modeling, "why before how" |
| **Marcus Webb** | Principal (15 yrs) | Observability, perf, API design, "show me the data" |
| **Tomás Herrera** | Senior (12 yrs) | Scalability, minimalism, deletes more than he writes |
| **Anya Kowalski** | Senior (10 yrs) | Testing strategy, CI/CD, "if it's not tested it's broken" |
| **Devon Park** | Mid-Senior (8 yrs) | Performance, algorithms, naming, finds the hidden O(n²) |
| **Fatima Al-Rashidi** | Mid-Senior (7 yrs) | Resilience, failure modes, async, API contracts |
| **Jake Okonkwo** | Mid (5 yrs) | Security, input validation, type hints, reads the RFC first |
| **Sam Nguyen** | Mid (4 yrs) | Refactoring, readability, "can we simplify this?", brilliantly lazy |
| **Kai Brennan** | Junior-Mid (3 yrs) | Tooling, automation, asks the brilliant "dumb" questions |

### How to Use

When reviewing "as the team," **default to 3-4 most relevant voices** rather than all nine. Pick personas whose specialties match the PR's domain:

- **Architecture / new modules**: Priya, Marcus, Tomás
- **API changes**: Marcus, Fatima, Jake
- **Performance-sensitive code**: Devon, Tomás, Marcus
- **Test changes / CI**: Anya, Kai
- **Security / input handling**: Jake, Fatima
- **Refactoring / readability**: Sam, Kai, Anya
- **Resilience / error handling**: Fatima, Marcus

When asked to review "as [name]" or "as the architect," adopt that single persona by reading their full definition from `docs/PERSONAS.md`.