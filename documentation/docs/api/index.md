# API Reference

Scatter can be used as a Python library in addition to the CLI. This reference is auto-generated from source docstrings.

## Package Structure

```
scatter/
  core/         # Data models, graph structures, parallel utilities
  analyzers/    # Analysis engines (consumer, git, graph, impact, coupling, health)
  scanners/     # File and project scanners (types, projects, sprocs, DB)
  reports/      # Output formatters (console, JSON, CSV, Markdown, Mermaid)
  store/        # Graph caching and incremental patching
  ai/           # AI provider integration (Gemini)
  config.py     # Configuration system
```

## Quick Example

```python
from pathlib import Path
from scatter.analyzers.consumer_analyzer import find_consumers
from scatter.analyzers.graph_builder import build_dependency_graph

# Build the dependency graph
graph = build_dependency_graph(Path("."))

# Find consumers of a target type
consumers = find_consumers(
    target_project=Path("MyLib/MyLib.csproj"),
    search_scope=Path("."),
)
```
