# Scatter

**Scatter** is a .NET dependency analyzer that answers the question: *"If I change this, what else is affected?"*

It traces blast radius across C# projects by analyzing project references, namespace usage, and type/method consumption — then reports which projects, pipelines, and batch jobs are impacted.

## Analysis Modes

Scatter operates in three modes:

| Mode | Use Case |
|------|----------|
| **Git Branch** | Compare a feature branch against its base and find consumers of changed types |
| **Target Project** | Find all projects that reference and use types from a specific `.csproj` |
| **Stored Procedure** | Find C# projects that reference specific database stored procedures |

## Key Features

- **Dependency graph** with caching and incremental per-file patching
- **Multi-format output** — console, JSON, CSV, Markdown, Mermaid diagrams
- **AI-powered analysis** — optional Gemini integration for code summarization, risk assessment, and complexity estimation
- **Pipeline mapping** — maps consumer projects to their CI/CD pipelines
- **Parallel processing** — multiprocessing support for large codebases
- **Configurable** — YAML-based config with CLI / env / file layering

## Quick Start

```bash
pip install -r requirements.txt

# Find consumers of a target project
python scatter.py --target-project ./MyLib/MyLib.csproj --search-scope .

# Analyze a feature branch
python scatter.py --branch-name feature/new-widget --repo-path .
```

See the [Getting Started](getting-started.md) guide for full setup instructions.
