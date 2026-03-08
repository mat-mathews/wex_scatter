# Scatter

*A .NET source code dependency analyzer and impact assessment tool*

Scatter answers questions like "If I change this class, which other projects are actually using it?" and "What's the blast radius of this work request?" It analyzes .NET codebases to find consumers of code changes, trace transitive dependencies, and produce AI-enriched impact reports for project scoping.

It works in four modes:

* **Git Branch Analysis**: Compares a feature branch against a base branch, extracts type declarations from changed `.cs` files, and finds consuming projects.
* **Target Project Analysis**: Analyzes a specific `.csproj` file to find all projects that reference and use its types.
* **Stored Procedure Analysis**: Finds C# projects that reference a specific stored procedure and traces their consumers.
* **Impact Analysis** (new): Accepts a natural language work request, uses AI to identify affected components, traces transitive blast radius, and produces a risk-rated impact report with complexity estimates.

The repository includes a set of sample .NET projects that form a realistic dependency graph, making it possible to test all analysis modes without an external codebase.

---

## Quick Start

### Installation

```bash
# Clone and set up
git clone <repository_url>
cd scatter

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
.\.venv\Scripts\Activate.ps1    # Windows

# Install dependencies
pip install -r requirements.txt
```

### Try It with the Included Sample Projects

The repository ships with 8 sample .NET projects that form two dependency chains (see [Sample Project Structure](#sample-project-structure) for the full graph). You can run every analysis mode against them immediately — no external codebase needed.

#### Target Project Analysis

```bash
# Find all consumers of the core GalaxyWorks.Data library
# Expected: 4 consumers (WebPortal, BatchProcessor, MyGalaxyConsumerApp, MyGalaxyConsumerApp2)
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

# Narrow to only consumers that use PortalDataService
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService

# Narrow further to consumers calling StorePortalConfigurationAsync
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --method-name StorePortalConfigurationAsync

# Find consumers of a mid-tier library (WebPortal)
# Expected: 1 consumer (BatchProcessor references both Data and WebPortal)
python scatter.py --target-project ./GalaxyWorks.WebPortal/GalaxyWorks.WebPortal.csproj --search-scope .

# Find consumers of a leaf project with only one consumer
# Expected: 1 consumer (MyDotNetApp.Consumer)
python scatter.py --target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .

# Verify a standalone project has zero consumers
# Expected: 0 consumers
python scatter.py --target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .
```

#### Stored Procedure Analysis

```bash
# Trace who ultimately consumes the sproc sp_InsertPortalConfiguration
# Finds PortalDataService in GalaxyWorks.Data, then finds its consumers
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# Trace a different sproc — sp_GetPortalConfigurationDetails
python scatter.py --stored-procedure "dbo.sp_GetPortalConfigurationDetails" --search-scope .

# Sproc trace filtered to a specific containing class
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --class-name PortalDataService
```

#### Output Formats

```bash
# JSON output — structured data with pipeline summary
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format json --output-file /tmp/scatter_results.json

# CSV output — one row per consumer relationship
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format csv --output-file /tmp/scatter_results.csv

# Verbose logging — see every step of the analysis pipeline
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . -v
```

#### AI-Powered Features (require `$GOOGLE_API_KEY`)

```bash
# AI consumer summarization — explains what each consumer file does with the dependency
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# AI summarization on sproc analysis
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# AI summarization with class filter + JSON output
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/summarized.json

# Impact Analysis — natural language work request → risk-rated impact report
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . --google-api-key $GOOGLE_API_KEY

# Impact Analysis with deeper transitive tracing
# BatchProcessor → WebPortal → GalaxyWorks.Data (2 hops deep)
python scatter.py \
  --sow "Refactor the FakeDatabaseHelper connection handling in GalaxyWorks.Data" \
  --search-scope . --max-depth 2 --google-api-key $GOOGLE_API_KEY

# Impact Analysis from a file containing a longer SOW description
python scatter.py \
  --sow-file docs/INITIATIVE_2_PLAN.md \
  --search-scope . --google-api-key $GOOGLE_API_KEY

# Impact Analysis with JSON output for programmatic consumption
python scatter.py \
  --sow "Add a new stored procedure sp_ArchivePortalConfiguration and integrate it into PortalDataService" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/impact_report.json

# Impact Analysis with CSV output — one row per affected consumer
python scatter.py \
  --sow "Modify the PortalConfiguration model to add a new IsArchived field" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format csv --output-file /tmp/impact_report.csv
```

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Sample Project Structure](#sample-project-structure)
3. [Analysis Modes](#analysis-modes)
4. [AI Features](#ai-features)
5. [Impact Analysis (Mode 4)](#impact-analysis-mode-4)
6. [Parallel Processing](#parallel-processing)
7. [Configuration & Mapping](#configuration--mapping) — YAML config files, precedence, env vars
8. [Command-Line Reference](#command-line-reference)
9. [Output Formats](#output-formats)
10. [Testing](#testing)
11. [Technical Details](#technical-details)
12. [Dependency Graph](#dependency-graph) — Architecture, performance, construction pipeline, programmatic API
13. [Roadmap](#roadmap)

---

## Sample Project Structure

The repository includes sample .NET projects that demonstrate realistic dependency patterns. These are used by the test suite and can be used to explore Scatter's features interactively.

### Dependency Graph

```
GalaxyWorks.Data                    (core library — no dependencies)
├── PortalDataService               calls sp_InsertPortalConfiguration
├── Models: PortalConfiguration, UserActivityLog, SystemModule, StatusType
└── Core: IDataAccessor interface
     │
     ├── GalaxyWorks.WebPortal      (references GalaxyWorks.Data)
     │   ├── PortalController       uses PortalDataService
     │   └── PortalCacheService     uses PortalConfiguration
     │        │
     │        └── GalaxyWorks.BatchProcessor  (references Data + WebPortal)
     │            └── SyncJob       uses PortalDataService + PortalCacheService
     │
     ├── MyGalaxyConsumerApp        (references GalaxyWorks.Data)
     │   └── Program               creates PortalDataService instance
     │
     └── MyGalaxyConsumerApp2       (references GalaxyWorks.Data)
         └── Program               creates PortalDataService instance

MyDotNetApp                         (independent library — no dependencies)
├── Person, DataService, IDataService
     │
     └── MyDotNetApp.Consumer       (references MyDotNetApp)
         └── Program               uses Person & DataService

MyDotNetApp2.Exclude                (standalone — no references, tests exclusion)
```

### What You Can Test

| Scenario | Command |
|----------|---------|
| Find all consumers of a core library | `--target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .` |
| Filter to a specific class | Add `--class-name PortalDataService` |
| Filter to a specific method | Add `--class-name PortalDataService --method-name InsertPortalConfiguration` |
| Trace stored procedure consumers | `--stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .` |
| Find consumers of a leaf project | `--target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .` |
| Verify no false positives | `--target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .` (should find 0 consumers) |
| Impact analysis with transitive tracing | `--sow "Modify PortalDataService" --search-scope . --max-depth 2 --google-api-key $KEY` |

---

## Analysis Modes

### Mode 1: Git Branch Analysis (`--branch-name`)

Analyzes the `.cs` files changed on a feature branch to identify potential downstream impact.

**How it works:**
1. Finds the merge base between the feature branch and base branch
2. Identifies all changed `.cs` files in the diff
3. Maps changed files to their parent `.csproj` projects
4. Extracts type declarations (`class`, `struct`, `interface`, `enum`) from changed files
5. Finds consuming projects for each changed type

**Type extraction** uses regex by default, matching C# type declarations with access modifiers, generics, and keywords like `static`, `abstract`, `sealed`, and `partial`. With `--enable-hybrid-git`, Scatter sends both the full file content and the git diff to an LLM, which identifies only the types whose body, signature, or members were *actually changed* — ignoring types that merely appear in the same file. This significantly reduces false positives. See [AI-Enhanced Type Extraction](#ai-enhanced-type-extraction-hybrid-git) for details.

```bash
# Basic usage — regex type extraction
python scatter.py --branch-name feature/new-widget --repo-path .

# Against a different base branch
python scatter.py --branch-name feature/hotfix --base-branch develop --repo-path /path/to/repo

# With LLM-enhanced diff analysis (reduces false positives)
python scatter.py --branch-name feature/refactor --repo-path . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY

# Filter to a specific class
python scatter.py --branch-name feature/refactor --repo-path . --class-name WidgetFactory

# Full analysis with pipeline mapping and JSON output
python scatter.py --branch-name feature/new-api --repo-path . \
  --search-scope src/services \
  --pipeline-csv build/pipeline_map.csv \
  --output-format json --output-file reports/analysis.json
```

### Mode 2: Target Project Analysis (`--target-project`)

Finds all projects that consume a specific `.csproj` file.

**How it works:**
1. Parses the target `.csproj` to determine its namespace
2. Finds all `.csproj` files in the search scope with a `<ProjectReference>` to the target
3. Filters by namespace usage (`using` statements)
4. Optionally filters by class and method usage

When `--summarize-consumers` is enabled, Scatter sends each relevant consumer `.cs` file to the Gemini API and includes a 2-3 sentence AI-generated summary in the output explaining the file's purpose. See [AI Consumer Summarization](#ai-consumer-summarization) for details and example output.

```bash
# Basic usage
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

# Override namespace detection
python scatter.py --target-project ./LegacyLib/LegacyLib.csproj --search-scope . \
  --target-namespace Company.Product.OldStuff

# Filter by class and method
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --method-name InsertPortalConfiguration

# With AI summarization — explains what each consumer file does
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# AI summarization with JSON output
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file reports/summary.json
```

### Mode 3: Stored Procedure Analysis (`--stored-procedure`)

Finds C# projects that reference a stored procedure, then traces their consumers.

**How it works:**
1. Scans the search scope for `.cs` files containing the stored procedure name
2. Maps matching files to their parent `.csproj` projects and containing classes
3. For each class referencing the sproc, finds consumer projects

```bash
# Basic usage
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# Custom regex pattern
python scatter.py --stored-procedure "UpdateUser" --search-scope . \
  --sproc-regex-pattern "EXECUTE sp_prefix_{sproc_name_placeholder}"

# Filter by class
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --class-name PortalDataService

# JSON output
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --output-format json --output-file reports/sproc_consumers.json
```

### Mode 4: Impact Analysis (`--sow` / `--sow-file`)

Accepts a natural language work request and produces an AI-enriched impact report. See [Impact Analysis (Mode 4)](#impact-analysis-mode-4) for the full breakdown.

---

## AI Features

Scatter integrates with the Google Gemini API in three distinct ways. Each is optional and activated by specific flags. All require a Gemini API key via `--google-api-key` or the `GOOGLE_API_KEY` environment variable.

| Feature | Flag | Available In | Purpose |
|---------|------|-------------|---------|
| [Consumer Summarization](#ai-consumer-summarization) | `--summarize-consumers` | Git, Target, Sproc modes | Explain *what* each consumer file does |
| [Hybrid Type Extraction](#ai-enhanced-type-extraction-hybrid-git) | `--enable-hybrid-git` | Git mode only | Identify *which* types were actually changed in a diff |
| [Impact Analysis](#impact-analysis-mode-4) | `--sow` / `--sow-file` | Impact mode | Full AI-powered scoping: parse SOW, assess risk, estimate effort |

### AI Consumer Summarization

When `--summarize-consumers` is enabled, Scatter identifies the specific `.cs` files in each consumer project that caused the match (e.g., the file containing the `using GalaxyWorks.Data;` statement and the `PortalDataService` reference). It sends each file's content to the Gemini API and gets back a concise 2-3 sentence summary of the file's purpose.

This is useful when you have dozens of consumers and want to quickly understand *what* each one does with the dependency, without opening every file.

**Try it with the sample projects:**

```bash
# Summarize what each consumer of GalaxyWorks.Data does with it
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarize consumers of a stored procedure
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Combine with class filter and JSON output
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file reports/summarized.json
```

**Example console output with summarization:**

```
Target: GalaxyWorks.Data (GalaxyWorks.Data/GalaxyWorks.Data.csproj)
    Type/Level: PortalDataService
         -> Consumed by: MyGalaxyConsumerApp (MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj)
           Summaries:
             File: Program.cs
              This console application creates an instance of PortalDataService
              and calls its methods to insert and retrieve portal configuration
              data. It serves as a simple client for the GalaxyWorks.Data library.
```

**In JSON output**, summaries appear in the `ConsumerFileSummaries` field as a JSON object mapping file paths to summary text:

```json
{
  "ConsumerProjectName": "MyGalaxyConsumerApp",
  "ConsumerFileSummaries": "{\"Program.cs\": \"This console application creates an instance of...\"}"
}
```

### AI-Enhanced Type Extraction (Hybrid Git)

In Git Branch mode, Scatter needs to determine which C# types (`class`, `struct`, `interface`, `enum`) were modified in the diff. By default, it uses a regex pattern that extracts *every* type declaration found in any changed file. This can produce false positives — if you modify one class in a file that declares five classes, all five are flagged as changed.

With `--enable-hybrid-git`, Scatter sends the **full file content** and the **git diff** to the Gemini API. The LLM analyzes the diff to determine which types had their body, signature, or members *actually modified*, and returns only those. Types that merely appear in the same file but weren't touched are excluded.

**Regex extraction (default):**
- Finds all type declarations in every changed `.cs` file
- Fast, no API calls
- May over-report: a one-line change in a file with 5 classes flags all 5

**LLM-enhanced extraction (`--enable-hybrid-git`):**
- Analyzes the actual diff to identify meaningfully changed types
- Filters out comment-only and import-only changes (returns empty for those)
- Falls back to regex automatically if the LLM call fails
- Requires a Gemini API key

**Try it with the sample projects:**

```bash
# First, create a branch with changes to test against
git checkout -b feature/test-hybrid

# Make a change to a file in GalaxyWorks.Data (e.g., add a comment to PortalDataService)
# Then run with regex (default):
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope .

# Same analysis with LLM-enhanced extraction:
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY -v
```

With `--verbose`, you can see the LLM's analysis for each file:

```
Hybrid analysis for GalaxyWorks.Data/DataServices/PortalDataService.cs:
  1 affected type(s) identified by LLM: {'PortalDataService'}
```

If a change only affects comments or `using` statements, the LLM returns an empty list and no consumers are searched for that file — avoiding unnecessary analysis.

---

## Impact Analysis (Mode 4)

Impact analysis turns Scatter from a developer tool into a project-scoping tool. Instead of needing to know the exact `.csproj` or class name to analyze, you describe the change in natural language and get back a comprehensive risk assessment.

### Pipeline

```
Work request text
  → AI parses into structured AnalysisTargets
    → find_consumers() per target
      → BFS transitive tracing (consumers of consumers)
        → AI enrichment:
           • Risk assessment per target (Low/Medium/High/Critical)
           • Coupling narrative (why dependencies exist)
           • Complexity estimate with effort range
           • Manager-friendly impact summary
          → ImpactReport → console / JSON / CSV
```

### Usage

```bash
# Inline work request
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY

# Work request from file
python scatter.py \
  --sow-file docs/sample_sow.txt \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY

# Control transitive tracing depth (default: 2)
python scatter.py \
  --sow "Refactor GalaxyWorks.Data connection handling" \
  --search-scope . \
  --max-depth 3 \
  --google-api-key $GOOGLE_API_KEY

# JSON output for programmatic use
python scatter.py \
  --sow "Add caching to PortalDataService" \
  --search-scope . \
  --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file impact_report.json
```

### Console Output Format

```
=== Impact Analysis Report ===
Work Request: Modify PortalDataService in GalaxyWorks.Data...
Overall Risk: High | Complexity: Medium (3-5 developer-days)

--- Target: GalaxyWorks.Data ---
Direct Consumers: 4 | Transitive: 1

  [HIGH] MyGalaxyConsumerApp (direct)
    Risk: Medium — "Uses PortalDataService directly..."
    Pipeline: consumer-app-pipeline

  [HIGH] GalaxyWorks.WebPortal (direct)
    Risk: High — "Core portal controller depends on this service..."
    Coupling: PortalController instantiates PortalDataService and calls multiple methods.
    Coupling vectors: Direct class instantiation, Method calls

  [MEDIUM] GalaxyWorks.BatchProcessor (depth: 1)
    Risk: Medium — "Transitive dependency through WebPortal..."

--- Complexity ---
Medium: Moderate blast radius with 4 direct and 1 transitive consumers.

--- Impact Summary ---
This change affects a core data access service used by 4 direct consumers
including the web portal and batch processing systems. Careful coordination
of deployments across the affected pipelines is recommended.
```

### Transitive Tracing

Impact analysis traces dependencies beyond direct consumers using BFS:

| Depth | Meaning | Confidence |
|-------|---------|------------|
| 0 | Direct consumer — has a `<ProjectReference>` and uses the target's namespace/class | HIGH (1.0) |
| 1 | Consumer of a consumer — one hop away from the change | MEDIUM (0.6) |
| 2+ | Deeply transitive — multiple hops, increasingly indirect | LOW (0.3) |

Cycle detection prevents infinite loops (A→B→A). The `--max-depth` flag controls how far the trace goes (default: 2).

### AI Enrichment

Impact mode makes several AI calls to enrich the raw dependency data:

| AI Task | Purpose | Output |
|---------|---------|--------|
| Work request parsing | Extract project names, classes, sprocs from natural language | `AnalysisTarget` list |
| Risk assessment | Rate risk per target based on consumer count, depth, pipelines | Low/Medium/High/Critical + justification |
| Coupling narrative | Explain *why* a dependency exists by reading consumer source code | Narrative text + coupling vectors |
| Complexity estimate | Estimate implementation effort based on blast radius metrics | Rating + effort range (e.g., "3-5 developer-days") |
| Impact narrative | Generate a manager-friendly summary of the full analysis | 1-2 paragraph summary |

All AI tasks require a Google Gemini API key (`--google-api-key` or `GOOGLE_API_KEY` env var).

---

## Parallel Processing

Scatter uses Python's `multiprocessing` module to parallelize file discovery and content analysis. This is enabled by default.

### What Gets Parallelized

| Phase | Operation | Default Chunk Size |
|-------|-----------|-------------------|
| File Discovery | Scanning directories for `.cs` and `.csproj` files | 75 directories |
| Content Analysis | Scanning `.cs` files for namespace usage, class references, sproc patterns | 50 files |
| XML Parsing | Parsing `.csproj` files to resolve `<ProjectReference>` dependencies | 25 files |
| Project Mapping | Mapping `.cs` files to their parent `.csproj` by directory walk | 50 files |

### Adaptive Worker Scaling

- < 200 files: up to 4 workers
- < 1000 files: up to 8 workers
- 1000+ files: up to `--max-workers` (default: CPU cores + 4, max 32)

If multiprocessing fails, processing falls back to sequential mode automatically.

### Multiprocessing Options

| Flag | Default | Description |
|------|---------|-------------|
| `--disable-multiprocessing` | `false` | Force sequential processing |
| `--max-workers N` | CPU cores + 4 (max 32) | Maximum worker processes |
| `--chunk-size N` | 75 | Directories per batch (file discovery) |
| `--cs-analysis-chunk-size N` | 50 | `.cs` files per batch (content analysis) |
| `--csproj-analysis-chunk-size N` | 25 | `.csproj` files per batch (XML parsing) |

```bash
# Tuning for a large codebase
python scatter.py --target-project src/Core/Core.csproj --search-scope /large/monorepo \
  --max-workers 16 --chunk-size 100 --cs-analysis-chunk-size 75

# Force sequential mode for debugging
python scatter.py --stored-procedure "dbo.sp_GetUser" --search-scope . --disable-multiprocessing
```

---

## Configuration & Mapping

Scatter loads configuration from multiple sources with layered precedence. You can set defaults in config files and override them per-invocation with CLI flags.

### Precedence Order

Settings are resolved from highest to lowest priority — the first source that provides a value wins:

| Priority | Source | Scope |
|----------|--------|-------|
| 1 (highest) | CLI flags (`--gemini-model`, etc.) | Single invocation |
| 2 | Repo config `.scatter.yaml` | Per-repository |
| 3 | User config `~/.scatter/config.yaml` | All repos for this user |
| 4 | Environment variables (`GOOGLE_API_KEY`, etc.) | Session / machine-wide |
| 5 (lowest) | Built-in defaults | Always present |

Missing config files are silently ignored — you don't need any config files to use Scatter.

### Config File Format

Both `.scatter.yaml` (repo-level) and `~/.scatter/config.yaml` (user-level) use the same schema:

```yaml
# .scatter.yaml — place in repo root (next to .git/)
ai:
  default_provider: gemini               # AI provider to use (currently only "gemini")
  gemini_model: gemini-2.0-flash         # Gemini model name
  task_overrides:                         # route specific AI tasks to specific providers
    work_request_parsing: gemini
    risk_assessment: gemini
  credentials:
    gemini:
      api_key: ""                         # prefer env var or user config for secrets

search:
  max_depth: 2                            # transitive tracing depth for impact analysis
  exclude_patterns:                       # glob patterns to skip during file scanning
    - "*/bin/*"                           # NOTE: this list REPLACES the defaults,
    - "*/obj/*"                           #       so re-list any defaults you want to keep
    - "*/node_modules/*"

multiprocessing:
  disabled: false
  max_workers: null                       # null = auto (CPU cores + 4, max 32)
  chunk_size: null                        # null = use built-in default (75)
```

### Typical Setup

**User-level config** (`~/.scatter/config.yaml`) — set your API key once, used across all repos:

```yaml
ai:
  credentials:
    gemini:
      api_key: "your-google-api-key-here"
```

**Repo-level config** (`.scatter.yaml`) — set repo-specific defaults:

```yaml
ai:
  gemini_model: gemini-2.0-flash
search:
  max_depth: 3
  exclude_patterns:
    - "*/bin/*"
    - "*/obj/*"
    - "*/test-fixtures/*"
```

CLI flags override everything — useful for one-off runs:

```bash
# Override the model for a single run, even if .scatter.yaml sets it differently
python scatter.py --sow "Modify PortalDataService" --search-scope . --gemini-model gemini-1.5-pro
```

### Environment Variables

| Variable | Maps to | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | `ai.credentials.gemini.api_key` | Google Gemini API key |
| `SCATTER_DEFAULT_PROVIDER` | `ai.default_provider` | Default AI provider name |

Environment variables sit below config files in precedence — a `.scatter.yaml` value overrides the env var, and a CLI flag overrides both.

### Google API Key

Required for AI summarization (`--summarize-consumers`), hybrid git analysis (`--enable-hybrid-git`), and impact analysis (`--sow` / `--sow-file`). Set it via any of these methods (highest precedence first):

```bash
# CLI flag (highest priority)
python scatter.py --sow "..." --search-scope . --google-api-key "your-key"

# Config file (user-level, recommended for persistent setup)
# ~/.scatter/config.yaml
# ai:
#   credentials:
#     gemini:
#       api_key: "your-key"

# Environment variable
export GOOGLE_API_KEY="your-key"
```

### Pipeline Mapping

Provide a CSV file (`--pipeline-csv`) to map project names to CI/CD pipelines. The CSV needs `Application Name` and `Pipeline Name` columns.

### Batch Job Verification

Use `--app-config-path` to verify if consumer projects correspond to known batch jobs in a configuration repository.

---

## Command-Line Reference

### Mode Selection (mutually exclusive, one required)

| Flag | Mode |
|------|------|
| `--branch-name BRANCH` | Git branch analysis |
| `--target-project PATH` | Target project analysis |
| `--stored-procedure NAME` | Stored procedure analysis |
| `--sow "TEXT"` | Impact analysis (inline) |
| `--sow-file PATH` | Impact analysis (from file) |

### Common Options

| Flag | Default | Description |
|------|---------|-------------|
| `--search-scope PATH` | (required) | Root directory to search for consumers |
| `--output-format FORMAT` | `console` | Output format: `console`, `csv`, `json` |
| `--output-file PATH` | — | Output file path (required for csv/json) |
| `--class-name NAME` | — | Filter by class/type name |
| `--method-name NAME` | — | Filter by method name (requires `--class-name`) |
| `--max-depth N` | `2` | Transitive tracing depth (impact mode) |
| `--pipeline-csv PATH` | — | CSV file for pipeline mapping |
| `--app-config-path PATH` | — | App-config repo for batch job verification |
| `--target-namespace NS` | — | Override namespace detection |
| `-v, --verbose` | `false` | Enable DEBUG logging |

### Git Branch Options

| Flag | Default | Description |
|------|---------|-------------|
| `-r, --repo-path PATH` | `.` | Path to the Git repository |
| `-b, --base-branch BRANCH` | `main` | Base branch to compare against |
| `--enable-hybrid-git` | `false` | LLM-enhanced diff analysis |

### Stored Procedure Options

| Flag | Description |
|------|-------------|
| `--sproc-regex-pattern PATTERN` | Custom regex for finding sproc references |

### AI / Summarization Options

| Flag | Default | Description |
|------|---------|-------------|
| `--summarize-consumers` | `false` | AI-summarize relevant consumer files |
| `--google-api-key KEY` | `$GOOGLE_API_KEY` | Google Gemini API key |
| `--gemini-model MODEL` | `gemini-1.5-flash` | Gemini model to use |

Run `python scatter.py --help` for the full list with defaults.

---

## Output Formats

### Console (default)

Human-readable report listing each target and its consumers with pipeline mappings, solutions, and optional AI summaries.

### JSON (`--output-format json --output-file report.json`)

Structured JSON. For legacy modes (git/target/sproc), the output includes `pipeline_summary` and `all_results`. For impact mode, the output is the full `ImpactReport` structure:

```json
{
  "sow_text": "Modify PortalDataService...",
  "targets": [
    {
      "target": { "target_type": "project", "name": "GalaxyWorks.Data", ... },
      "consumers": [
        {
          "consumer_name": "MyGalaxyConsumerApp",
          "depth": 0,
          "confidence": 1.0,
          "confidence_label": "HIGH",
          "risk_rating": "Medium",
          "risk_justification": "...",
          "pipeline_name": "...",
          ...
        }
      ],
      "total_direct": 4,
      "total_transitive": 1
    }
  ],
  "complexity_rating": "Medium",
  "effort_estimate": "3-5 developer-days",
  "impact_narrative": "...",
  "overall_risk": "High"
}
```

### CSV (`--output-format csv --output-file report.csv`)

For legacy modes: one row per consumer relationship with columns for target, consumer, pipeline, etc.

For impact mode: one row per consumer with columns: `Target`, `TargetType`, `Consumer`, `ConsumerPath`, `Depth`, `Confidence`, `ConfidenceLabel`, `RiskRating`, `RiskJustification`, `Pipeline`, `Solutions`, `CouplingVectors`.

---

## Testing

### Running Tests

```bash
# Run the full test suite
python -m pytest -v

# Run only impact analysis tests
python -m pytest test_impact_analysis.py -v

# Run only multiprocessing tests
python -m pytest test_multiprocessing_phase1.py -v

# Run only project mapping tests
python -m pytest test_phase2_3_project_mapping.py -v

# Run with short output
python -m pytest -q
```

### Test Suite Overview

The test suite includes **178 tests** across 8 test files:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_config.py` | 24 | Config loading, YAML precedence, env vars, CLI overrides, AI router (caching, task overrides, unknown providers) |
| `test_graph.py` | 46 | Graph data structures, construction, traversal, serialization, `.csproj` parsing, integration with sample projects |
| `test_multiprocessing_phase1.py` | 37 | File discovery, consumer analysis, backwards compatibility |
| `test_phase2_3_project_mapping.py` | 25 | Batch project mapping, parallel orchestration, sproc integration |
| `test_impact_analysis.py` | 53 | Impact analysis: data models, CLI args, work request parsing, transitive tracing, risk assessment, coupling narrative, impact narrative, complexity estimate, reporters, end-to-end |
| `test_hybrid_git.py` | 7 | LLM-enhanced git diff analysis |
| `test_phase21_overhead.py` | — | Phase 2.1 overhead measurement |
| `test_realistic_workload.py` | 1 | Scalability benchmark with synthetic codebases |

### What the Tests Cover

**Data model construction** — All 4 impact analysis dataclasses (`AnalysisTarget`, `EnrichedConsumer`, `TargetImpact`, `ImpactReport`) with defaults and field validation.

**CLI argument parsing** — Mutual exclusivity between modes (`--sow` vs `--branch-name` vs `--target-project` vs `--stored-procedure`), required argument validation.

**AI task modules** — Each AI task (work request parsing, risk assessment, coupling narrative, impact narrative, complexity estimate) is tested with mock AI responses for:
- Valid JSON responses
- Empty responses
- Invalid JSON / non-list responses
- Markdown code fence stripping
- API failures / exceptions
- No-provider graceful fallback

**Transitive tracing** — Depth-0 returns only direct consumers, depth-1 finds transitive, cycle detection (A→B→A), confidence decay by depth, max depth enforcement.

**Reporters** — Console output formatting, JSON serialization (including `Path` objects), CSV column structure, empty report handling.

**Hybrid git type extraction** — LLM-based symbol extraction with mock model responses, fallback to regex on failure, JSON parsing of model output, markdown fence stripping.

**End-to-end integration** — Full pipeline with all AI mocked: SOW text → parse → find_consumers → transitive tracing → enrichment → report generation.

**Parallel vs sequential consistency** — Every parallel operation is verified to produce identical results when run sequentially with `--disable-multiprocessing`.

All AI-dependent tests use mock models (no real API calls). The mocks simulate valid JSON responses, empty responses, malformed JSON, API exceptions, and markdown-fenced output to verify graceful handling of every failure mode.

### Testing with the Sample Projects

The sample .NET projects in the repository provide real-world test scenarios. Commands below are grouped by what they verify.

**Core analysis (no API key needed):**

```bash
# Verify GalaxyWorks.Data has 4 consumers (WebPortal, BatchProcessor, 2x ConsumerApp)
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope .

# Verify MyDotNetApp has exactly 1 consumer (MyDotNetApp.Consumer)
python scatter.py --target-project ./MyDotNetApp/MyDotNetApp.csproj --search-scope .

# Verify MyDotNetApp2.Exclude has 0 consumers (standalone project)
python scatter.py --target-project ./MyDotNetApp2.Exclude/MyDotNetApp2.Exclude.csproj --search-scope .

# Verify sproc tracing finds PortalDataService as the referencing class
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .

# Verify class filtering narrows results
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService

# Test output formats
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format json --output-file /tmp/test_output.json

python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --output-format csv --output-file /tmp/test_output.csv
```

**AI Consumer Summarization (requires `$GOOGLE_API_KEY`):**

```bash
# Summarize what each consumer of GalaxyWorks.Data does with it
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarize with class filter — only PortalDataService consumers
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --class-name PortalDataService --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarize consumers of a stored procedure
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY

# Summarization with JSON output — summaries in ConsumerFileSummaries field
python scatter.py --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj --search-scope . \
  --summarize-consumers --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/summarized.json
```

**AI Hybrid Git Type Extraction (requires `$GOOGLE_API_KEY` + a feature branch):**

```bash
# Create a test branch, modify a file, then analyze
git checkout -b feature/test-hybrid
echo "// test change" >> GalaxyWorks.Data/DataServices/PortalDataService.cs
git add GalaxyWorks.Data/DataServices/PortalDataService.cs

# Regex extraction (default) — may flag all types in the file
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope . -v

# LLM extraction — only flags types whose body/signature actually changed
python scatter.py --branch-name feature/test-hybrid --repo-path . --search-scope . \
  --enable-hybrid-git --google-api-key $GOOGLE_API_KEY -v

# Clean up
git checkout main && git branch -D feature/test-hybrid
```

**AI Impact Analysis (requires `$GOOGLE_API_KEY`):**

```bash
# Natural language work request → risk-rated impact report
python scatter.py \
  --sow "Modify PortalDataService in GalaxyWorks.Data to add a new parameter to sp_InsertPortalConfiguration" \
  --search-scope . --google-api-key $GOOGLE_API_KEY

# Transitive tracing — BatchProcessor is a transitive consumer of WebPortal
python scatter.py \
  --sow "Modify PortalCacheService in GalaxyWorks.WebPortal" \
  --search-scope . --max-depth 1 --google-api-key $GOOGLE_API_KEY

# Impact report as JSON
python scatter.py \
  --sow "Refactor GalaxyWorks.Data connection handling" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format json --output-file /tmp/impact.json

# Impact report as CSV
python scatter.py \
  --sow "Refactor GalaxyWorks.Data connection handling" \
  --search-scope . --google-api-key $GOOGLE_API_KEY \
  --output-format csv --output-file /tmp/impact.csv
```

### Benchmarking

```bash
# Run synthetic codebase benchmark (100 to 5,000 files)
python test_realistic_workload.py

# Compare parallel vs sequential on your own codebase
time python scatter.py --target-project ./MyLib/MyLib.csproj --search-scope /your/codebase -v
time python scatter.py --target-project ./MyLib/MyLib.csproj --search-scope /your/codebase --disable-multiprocessing -v
```

---

## Technical Details

### Type Extraction

In Git Branch mode, type declarations are extracted from changed `.cs` files. Scatter supports two extraction strategies:

**Regex extraction (default)** uses a compiled pattern to find type declarations with access modifiers, generics, and keywords like `static`, `abstract`, `sealed`, and `partial`:

```python
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"  # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*"  # Optional keywords
    r"(?:class|struct|interface|enum)\s+"  # Type keyword
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)"  # Capture type name (non-greedy)
    r"\s*(?::|{|where|<)",  # Look for end of declaration
    re.MULTILINE
)
```

This is fast and requires no API calls, but extracts *every* type declared in each changed file — even types whose code was not touched by the diff.

**LLM extraction (`--enable-hybrid-git`)** sends both the file content and the git diff to the Gemini API with a prompt asking it to identify only types whose body, signature, or members were meaningfully changed. The LLM returns a JSON array of affected type names. If the LLM call fails or returns invalid JSON, Scatter falls back to regex automatically.

| Aspect | Regex (default) | LLM (`--enable-hybrid-git`) |
|--------|-----------------|----------------------------|
| Speed | Instant (no API call) | ~1-2s per file (API round-trip) |
| Precision | Extracts all types in file | Only types with meaningful changes |
| Comment-only changes | Flags all types in file | Returns empty (no analysis needed) |
| API key required | No | Yes |
| Failure mode | N/A | Falls back to regex |

### Consumer Detection Pipeline

The core consumer detection runs in 5 stages, each progressively filtering:

1. **File Discovery** — Find all `.csproj` files in the search scope
2. **ProjectReference Filter** — Keep only projects with a `<ProjectReference>` to the target
3. **Namespace Filter** — Keep only projects with `using TargetNamespace;` statements
4. **Class Filter** (optional) — Keep only projects referencing the specific class name
5. **Method Filter** (optional) — Keep only projects calling the specific method

### Impact Analysis Architecture

Impact analysis adds an orchestrator layer (`scatter/analyzers/impact_analyzer.py`) on top of the existing consumer detection pipeline:

```
scatter/
├── config.py              # YAML config loading with layered precedence
├── core/
│   ├── models.py          # AnalysisTarget, EnrichedConsumer, TargetImpact, ImpactReport
│   ├── graph.py           # ProjectNode, DependencyEdge, DependencyGraph (pure data structure)
│   └── parallel.py        # Multiprocessing infrastructure
├── ai/
│   ├── base.py            # AIProvider protocol, AITaskType enum
│   ├── router.py          # AIRouter — provider selection per task type
│   ├── providers/
│   │   └── gemini_provider.py
│   └── tasks/
│       ├── parse_work_request.py    # SOW → AnalysisTarget list
│       ├── risk_assess.py           # Per-target risk rating
│       ├── coupling_narrative.py    # Dependency explanation
│       ├── impact_narrative.py      # Manager-friendly summary
│       └── complexity_estimate.py   # Effort/complexity rating
├── analyzers/
│   ├── consumer_analyzer.py   # Core find_consumers() pipeline
│   ├── git_analyzer.py        # Git branch diff analysis
│   ├── graph_builder.py       # Single-pass O(P+F) graph construction
│   └── impact_analyzer.py     # Impact analysis orchestrator + transitive tracing
├── scanners/                  # Type, project, sproc scanners
├── reports/
│   ├── console_reporter.py    # print_console_report() + print_impact_report()
│   ├── json_reporter.py       # write_json_report() + write_impact_json_report()
│   └── csv_reporter.py        # write_csv_report() + write_impact_csv_report()
└── __main__.py                # CLI entry point with 4-mode dispatch
```

---

## Dependency Graph

The dependency graph is a persistent, in-memory data structure that captures the full project-to-project dependency topology of a .NET codebase. It replaces repeated calls to `find_consumers()` (each of which re-scans the filesystem) with a single upfront construction pass, after which all queries — consumers, dependencies, transitive impact, connected components — are answered from the graph in constant or linear time relative to the graph size, not the filesystem.

### Architecture

The graph follows a strict **Single Responsibility Principle** separation: `DependencyGraph` in `scatter/core/graph.py` is a pure data structure (mutation, query, traversal, serialization only), while all construction logic lives in `scatter/analyzers/graph_builder.py`. Analysis algorithms (cycle detection, coupling metrics, clustering) are standalone functions in their respective analyzer modules — they are never methods on the graph itself.

#### Data Structures

**`ProjectNode`** — A dataclass representing a single `.csproj` project:

| Field | Type | Description |
|-------|------|-------------|
| `path` | `Path` | Absolute path to the `.csproj` file |
| `name` | `str` | Project name (filename stem, e.g. `GalaxyWorks.Data`) |
| `namespace` | `Optional[str]` | Root namespace from `<RootNamespace>`, `<AssemblyName>`, or filename |
| `framework` | `Optional[str]` | Target framework (e.g. `net8.0`, `v4.7.2`) |
| `project_style` | `str` | `"sdk"` or `"framework"` — detected from `<Project Sdk="...">` attribute |
| `output_type` | `Optional[str]` | `Library`, `Exe`, etc. |
| `file_count` | `int` | Number of `.cs` files belonging to this project |
| `type_declarations` | `List[str]` | Sorted list of type names declared in this project's `.cs` files |
| `sproc_references` | `List[str]` | Sorted list of stored procedure names referenced in string literals |

Design note: `file_count` stores a count, not a `List[Path]` of file paths — this prevents unbounded memory growth in large codebases (thousands of `.cs` files per project would bloat the serialized graph).

**`DependencyEdge`** — A directed edge between two projects:

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Name of the project that *depends on* the target |
| `target` | `str` | Name of the project being depended upon |
| `edge_type` | `str` | One of `"project_reference"`, `"namespace_usage"`, `"type_usage"` |
| `weight` | `float` | Strength of the dependency (1.0 for project refs, evidence count for others) |
| `evidence` | `Optional[List[str]]` | File paths or `file:TypeName` pairs showing where the dependency occurs |
| `evidence_total` | `int` | Total evidence count (may exceed `len(evidence)` due to capping) |

Evidence is capped at `MAX_EVIDENCE_ENTRIES = 10` entries per edge. If an edge has 500 evidence entries (e.g., a utility project referenced from 500 `.cs` files), only the first 10 are stored and `evidence_total` records the true count of 500. This bounds serialization size while preserving the magnitude signal.

**`DependencyGraph`** — The container holding all nodes and edges with four internal indexes:

```
_nodes:    Dict[str, ProjectNode]        # name → node (O(1) lookup)
_outgoing: Dict[str, List[DependencyEdge]]  # source → edges leaving this node
_incoming: Dict[str, List[DependencyEdge]]  # target → edges arriving at this node
_forward:  Dict[str, Set[str]]           # source → set of dependency names (adjacency)
_reverse:  Dict[str, Set[str]]           # target → set of consumer names (reverse adjacency)
```

The dual index design (`_outgoing`/`_incoming` for full edge data, `_forward`/`_reverse` for fast adjacency checks) means every query — "what does project X depend on?", "what consumes project X?", "what are all edges between A and B?" — runs in O(degree) time without scanning all edges in the graph.

#### Edge Types

The graph captures three categories of inter-project dependency:

| Edge Type | Source | Meaning | Weight |
|-----------|--------|---------|--------|
| `project_reference` | `<ProjectReference Include="...">` in `.csproj` | Explicit build-time dependency | 1.0 (always) |
| `namespace_usage` | `using Namespace;` in `.cs` matching another project's root namespace | Import-level coupling | Count of `.cs` files with that `using` |
| `type_usage` | Regex match of a type name declared in project B found in project A's source | Code-level coupling (class/interface usage) | Count of `file:TypeName` matches |

A single pair of projects may have multiple edges (e.g., A has a `project_reference` to B *and* a `namespace_usage` edge *and* a `type_usage` edge). The `get_edges_between(a, b)` method returns all of them.

### Performance and Big O

#### Graph Construction — `build_dependency_graph()`

Construction is a **single-pass O(P + F)** algorithm where P = number of `.csproj` files and F = number of `.cs` files:

| Step | Operation | Complexity |
|------|-----------|------------|
| 1 | Discover `.csproj` files (parallel glob) | O(dirs) |
| 2 | Parse each `.csproj` — XML parse, extract metadata | O(P × avg_xml_size) |
| 3 | Discover `.cs` files (parallel glob) | O(dirs) |
| 4 | Build reverse directory index, map `.cs` → parent project | O(F × P) worst-case, O(F × log P) typical |
| 5 | Read each `.cs` file, extract types + sprocs + usings | O(F × avg_file_size) |
| 6 | Build `project_reference` edges (resolve Include paths) | O(P × avg_refs) |
| 7 | Build `namespace_usage` edges (match usings to project namespaces) | O(P × U) where U = unique usings per project |
| 8 | Build `type_usage` edges (scan for type names across projects) | O(F × T) where T = total types across all projects |

Step 8 (`type_usage` edge construction) is the most expensive — for each `.cs` file, it checks every type name declared in other projects using regex word-boundary search. For a codebase with 1,000 `.cs` files and 500 total type declarations, this is ~500,000 regex checks. This is acceptable for typical enterprise codebases but is the primary candidate for optimization in future phases (planned: inverted type index).

**Contrast with per-query scanning:** Without the graph, each call to `find_consumers("ProjectX")` rescans the entire filesystem — discovering `.csproj` files, parsing XML, scanning `.cs` files for namespace and class usage. For N target projects, this is O(N × (P + F)). The graph pays O(P + F) once and answers all N queries from memory.

#### Graph Queries

| Operation | Method | Complexity |
|-----------|--------|------------|
| Get a node by name | `get_node(name)` | O(1) dict lookup |
| Get all nodes | `get_all_nodes()` | O(N) |
| Direct dependencies | `get_dependencies(name)` | O(out-degree) |
| Direct consumers | `get_consumers(name)` | O(in-degree) |
| Outgoing edges (with full edge data) | `get_edges_from(name)` | O(out-degree) |
| Incoming edges (with full edge data) | `get_edges_to(name)` | O(in-degree) |
| All edges for a node | `get_edges_for(name)` | O(degree) |
| Edges between two nodes (both directions) | `get_edges_between(a, b)` | O(degree of a + degree of b) |
| Transitive consumers (BFS) | `get_transitive_consumers(name, max_depth)` | O(V + E) within depth bound |
| Transitive dependencies (BFS) | `get_transitive_dependencies(name, max_depth)` | O(V + E) within depth bound |
| Connected components | `connected_components` property | O(V + E) full BFS |
| Node count | `node_count` property | O(1) |
| Edge count | `edge_count` property | O(N) — iterates outgoing lists |
| All edges (flat list) | `all_edges` property | O(E) |

All traversal methods use a `visited` set to ensure cycle safety — even if the graph contains cycles (A → B → C → A), BFS never visits the same node twice.

#### Serialization

| Operation | Method | Complexity |
|-----------|--------|------------|
| Export to dict | `to_dict()` | O(V + E) |
| Import from dict | `DependencyGraph.from_dict(data)` | O(V + E) |

The `to_dict()` / `from_dict()` roundtrip produces JSON-compatible dicts. All `Path` objects are serialized as strings. The graph can be persisted to disk as JSON and reconstructed without rescanning the filesystem.

### Construction Pipeline

`build_dependency_graph()` in `scatter/analyzers/graph_builder.py` orchestrates a six-step pipeline:

```
search_scope (Path)
  │
  ├─ Step 1: Discover all .csproj files (parallel glob)
  │    └─ Filter by exclude_patterns (default: */bin/*, */obj/*, */temp_test_data/*)
  │
  ├─ Step 2: Parse each .csproj
  │    ├─ parse_csproj_all_references() → project_references, framework, style, output_type
  │    └─ derive_namespace() → root namespace (RootNamespace > AssemblyName > filename stem)
  │
  ├─ Step 3: Discover all .cs files (parallel glob)
  │    ├─ Filter by exclude_patterns
  │    └─ Map each .cs to parent project via reverse directory index
  │         (index sorted deepest-first so nested projects match before parents)
  │
  ├─ Step 4: For each project's .cs files, extract:
  │    ├─ Type declarations (class, struct, interface, enum names)
  │    ├─ Sproc references (sp_/usp_ in string literals)
  │    └─ Using statements (namespace imports)
  │
  ├─ Step 5: Build nodes (one ProjectNode per .csproj with aggregated metadata)
  │
  └─ Step 6: Build edges
       ├─ 6a: project_reference — resolve <ProjectReference Include="..."> paths
       ├─ 6b: namespace_usage — match using statements to project namespaces
       └─ 6c: type_usage — scan .cs content for type names from other projects
```

**`.csproj` parsing** handles both SDK-style projects (`<Project Sdk="Microsoft.NET.Sdk">`) and legacy Framework-style projects (with MSBuild XML namespace `http://schemas.microsoft.com/developer/msbuild/2003`). The `parse_csproj_all_references()` function tries XPath queries without namespace first, then with the MSBuild namespace prefix, ensuring both styles are parsed correctly.

**Reverse directory index** maps `.cs` files to their parent `.csproj` by building a sorted list of `(project_directory, project_name)` pairs, sorted deepest-first by path depth. For each `.cs` file, it walks up the parent chain and returns the first matching project directory. This handles nested project structures where a `.cs` file under `src/Lib/SubLib/` should match the `SubLib.csproj` in that directory, not the `Lib.csproj` one level up.

**Exclude patterns** default to `["*/bin/*", "*/obj/*", "*/temp_test_data/*"]` and use `fnmatch.fnmatch()` for glob-style matching. They can be overridden via the `exclude_patterns` parameter or through `.scatter.yaml` config.

### Programmatic API

#### Building a Graph

```python
from pathlib import Path
from scatter.analyzers.graph_builder import build_dependency_graph

# Build the graph from a codebase directory
graph = build_dependency_graph(
    search_scope=Path("/path/to/dotnet/solution"),
    max_workers=8,              # parallel workers (default: CPU cores + 4)
    chunk_size=75,              # directories per parallel batch
    disable_multiprocessing=False,
    exclude_patterns=["*/bin/*", "*/obj/*", "*/test-fixtures/*"],
)

print(f"Discovered {graph.node_count} projects, {graph.edge_count} edges")
```

#### Querying the Graph

```python
# Get a specific project node
node = graph.get_node("GalaxyWorks.Data")
print(f"Project: {node.name}")
print(f"Namespace: {node.namespace}")
print(f"Framework: {node.framework}")
print(f"Style: {node.project_style}")
print(f"Files: {node.file_count}")
print(f"Types: {node.type_declarations}")
print(f"Sprocs: {node.sproc_references}")

# Find direct consumers (who depends on this project?)
consumers = graph.get_consumers("GalaxyWorks.Data")
for c in consumers:
    print(f"  Consumer: {c.name} ({c.framework})")

# Find direct dependencies (what does this project depend on?)
deps = graph.get_dependencies("GalaxyWorks.BatchProcessor")
for d in deps:
    print(f"  Depends on: {d.name}")

# Get detailed edge information between two projects
edges = graph.get_edges_between("GalaxyWorks.WebPortal", "GalaxyWorks.Data")
for edge in edges:
    print(f"  {edge.source} → {edge.target} [{edge.edge_type}] weight={edge.weight}")
    if edge.evidence:
        for ev in edge.evidence:
            print(f"    Evidence: {ev}")
```

#### Transitive Traversal

```python
# Find all transitive consumers of a core library (up to 3 hops)
transitive = graph.get_transitive_consumers("GalaxyWorks.Data", max_depth=3)
for node, depth in transitive:
    print(f"  {'  ' * depth}{node.name} (depth {depth})")

# Example output for the sample projects:
#   GalaxyWorks.WebPortal (depth 1)
#   MyGalaxyConsumerApp (depth 1)
#   MyGalaxyConsumerApp2 (depth 1)
#     GalaxyWorks.BatchProcessor (depth 2)

# Find all transitive dependencies (what does this project ultimately rely on?)
deps = graph.get_transitive_dependencies("GalaxyWorks.BatchProcessor", max_depth=3)
for node, depth in deps:
    print(f"  {'  ' * depth}{node.name} (depth {depth})")

# Example output:
#   GalaxyWorks.Data (depth 1)
#   GalaxyWorks.WebPortal (depth 1)
```

Both traversal methods use BFS with a visited set, guaranteeing cycle safety. If the graph contains A → B → C → A, the BFS visits each node exactly once and terminates.

#### Connected Components

```python
# Find clusters of related projects
components = graph.connected_components
print(f"Found {len(components)} connected component(s)")
for i, component in enumerate(components):
    print(f"  Component {i+1}: {component}")

# For the sample projects (with namespace/type edges connecting everything):
#   Component 1: ['GalaxyWorks.BatchProcessor', 'GalaxyWorks.Data', 'GalaxyWorks.WebPortal',
#                  'MyDotNetApp', 'MyDotNetApp.Consumer', 'MyDotNetApp2.Exclude',
#                  'MyGalaxyConsumerApp', 'MyGalaxyConsumerApp2']
```

Components are sorted largest-first and alphabetically within each component. They treat all edges as undirected — if A → B exists, A and B are in the same component regardless of direction.

#### Serialization and Persistence

```python
import json

# Serialize to JSON-compatible dict
data = graph.to_dict()

# Persist to disk
with open("graph_cache.json", "w") as f:
    json.dump(data, f, indent=2)

# Reconstruct from disk (no filesystem scanning needed)
with open("graph_cache.json") as f:
    data = json.load(f)
graph2 = DependencyGraph.from_dict(data)

assert graph2.node_count == graph.node_count
assert graph2.edge_count == graph.edge_count
```

The `to_dict()` / `from_dict()` roundtrip is lossless — all nodes, edges, evidence, and metadata survive serialization. `Path` objects are serialized as strings and reconstructed on deserialization. This enables graph caching: build once, persist to disk, reload in subsequent runs without rescanning the filesystem.

#### Working with the Sample Projects

The repository's 8 sample projects produce this graph:

```
Nodes (8):
  GalaxyWorks.Data          (sdk, net8.0, Library, 4 types, 2 sprocs)
  GalaxyWorks.WebPortal     (framework, v4.7.2, Library)
  GalaxyWorks.BatchProcessor (framework, v4.7.2, Exe)
  MyDotNetApp               (framework, net8.0, Exe)
  MyDotNetApp.Consumer      (sdk, net8.0, Exe)
  MyDotNetApp2.Exclude      (sdk, net8.0, Exe)
  MyGalaxyConsumerApp       (sdk, net8.0, Exe)
  MyGalaxyConsumerApp2      (sdk, net8.0, Exe)

project_reference edges (6):
  GalaxyWorks.WebPortal       → GalaxyWorks.Data
  GalaxyWorks.BatchProcessor  → GalaxyWorks.Data
  GalaxyWorks.BatchProcessor  → GalaxyWorks.WebPortal
  MyDotNetApp.Consumer        → MyDotNetApp
  MyGalaxyConsumerApp         → GalaxyWorks.Data
  MyGalaxyConsumerApp2        → GalaxyWorks.Data
```

Additional `namespace_usage` and `type_usage` edges are generated automatically based on `using` statements and type references found in the `.cs` files.

---

## Roadmap

### Completed

- **Multiprocessing** — Parallel file discovery, content analysis, XML parsing, and project mapping with adaptive worker scaling
- **Hybrid Git Analysis** — LLM-enhanced diff analysis for more precise symbol extraction
- **Modularization** — Extracted into `scatter/` package with clean module boundaries
- **Impact Analysis** — AI-powered work request parsing, transitive blast radius tracing, risk assessment, coupling narrative, complexity estimation, and impact reporting
- **Configuration System** — YAML config files (`.scatter.yaml`, `~/.scatter/config.yaml`) with layered precedence, environment variable support, and AI task router for provider selection
- **Dependency Graph (Phase 1)** — Graph model (`ProjectNode`, `DependencyEdge`, `DependencyGraph`) with per-node edge indexes, single-pass O(P+F) builder, BFS traversal, connected components, JSON serialization roundtrip, and 46 tests

### Planned

- **Dependency Graph (Phase 2-6)** — Tarjan's SCC cycle detection, configurable coupling metrics, git-based cache invalidation, label propagation clustering, domain boundary analysis
- **Reporting & Extraction Planning** — Enhanced reporting with visualization and extraction recommendations
- **CI/CD Integration** — Pipeline-aware analysis with automated impact checks
