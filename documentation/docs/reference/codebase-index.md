# Codebase Index

The codebase index is a compact text representation of your codebase's structure, built from the dependency graph and sent to the LLM as grounding context during AI-powered analysis modes (`--sow`, `--summarize-consumers`).

## Why it exists

LLMs hallucinate when asked to reason about code they can't see. Sending entire source files is expensive and noisy. The codebase index solves both problems: it gives the LLM a complete inventory of project names, type declarations, namespaces, and stored procedure references — enough to map domain language to real code artifacts, without sending any source code.

When a user writes `--sow "Add tenant isolation to portal configuration"`, the LLM doesn't guess which projects might be relevant. It selects from the index, matching "portal configuration" to actual types like `PortalDataService` and `PortalConfiguration` in `GalaxyWorks.Data`.

## Format

The index uses a one-line-per-project format optimized for token efficiency:

```
=== Codebase Index (11 projects) ===
P=Project NS=Namespace (omitted when same as project name) T=Types SP=StoredProcs
P:GalaxyWorks.Api T:GalaxyWorksApiService,StartupExtensions
P:GalaxyWorks.BatchProcessor T:BatchProcessorService
P:GalaxyWorks.Common T:CommonHelper
P:GalaxyWorks.Data T:PortalConfiguration,PortalDataService SP:dbo.sp_InsertPortalConfiguration,dbo.sp_GetPortalConfig
P:GalaxyWorks.WebPortal T:WebPortalController
P:MyDotNetApp T:MyService
P:MyDotNetApp.Consumer T:ConsumerService
...

=== Shared Stored Procedures ===
  dbo.sp_InsertPortalConfiguration: GalaxyWorks.Data, GalaxyWorks.Api
```

Key design decisions:

- **Namespace suppression** — `NS:` is only included when it differs from the project name, saving tokens in the common case
- **Sorted output** — projects are alphabetical for deterministic prompts (same input = same LLM behavior)
- **Sproc cross-reference** — stored procedures used by 2+ projects get a dedicated section, surfacing shared database coupling that project references alone would miss
- **No source code** — only structural metadata (names, types, namespaces, sprocs). Source file contents are never sent to the LLM

## Size considerations

The index always includes all types — there is no truncation. At WEX scale (250-800 projects), the full index is ~120K tokens, roughly 12% of a 1M context window. This is well within the budget for modern LLMs.

If the index exceeds a model's context window, the API call will fail with an actionable error message suggesting you narrow `--search-scope` or use a model with a larger context window.

## How it integrates

```
Dependency Graph
      │
      ▼
build_codebase_index()  ──→  CodebaseIndex.text
      │                            │
      │                            ▼
      │                    LLM prompt context
      │                    (SOW parsing, risk
      │                     assessment, etc.)
      │
      ▼
CodebaseIndex metrics
(project_count, type_count,
 sproc_count, file_count,
 size_bytes)
```

The index is built lazily — only when an AI-powered mode is invoked. The dependency graph provides all the data; no additional file I/O is needed.

### Call sites

| Mode | How the index is used |
|------|----------------------|
| `--sow` / `--sow-file` | Grounding context for target identification — LLM matches SOW language to index entries |
| `--summarize-consumers` | Not used (summarization works on individual file content) |
| `--enable-hybrid-git` | Not used (hybrid extraction works on individual diffs) |
| `--dump-index` | Prints the index to stdout for inspection |

## Inspecting the index

Use `--dump-index` to see exactly what the LLM sees:

```bash
$ scatter --dump-index --search-scope .

=== Codebase Index (11 projects) ===
P=Project NS=Namespace (omitted when same as project name) T=Types SP=StoredProcs
P:GalaxyWorks.Api T:GalaxyWorksApiService,StartupExtensions
P:GalaxyWorks.Data T:PortalConfiguration,PortalDataService SP:dbo.sp_InsertPortalConfiguration
...

# 11 projects, 18 types, 2 sprocs, 27 files, 1,245 bytes
```

This is useful for:

- **Debugging AI results** — if the LLM misidentified a target, check whether the type appears in the index
- **Verifying coverage** — confirm that all expected projects and types are present
- **Estimating token cost** — the `size_bytes` metric maps roughly to token count (divide by ~4 for English/code)

## Implementation

The index is implemented in `scatter/ai/codebase_index.py`:

- `CodebaseIndex` — dataclass holding the text and metrics
- `build_codebase_index(graph, search_scope)` — builds the index from a `DependencyGraph`
- `_build_index_text(nodes, sproc_to_projects)` — formats the compact text

The dump mode handler lives in `scatter/modes/dump_index.py`.
