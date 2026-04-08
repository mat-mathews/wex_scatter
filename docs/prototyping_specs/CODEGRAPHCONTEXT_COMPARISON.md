# CodeGraphContext vs Scatter — Comparison Analysis

**Date:** 2026-03-13
**Source:** https://github.com/CodeGraphContext/CodeGraphContext (~1,960 stars)

## Overview

CodeGraphContext (CGC) is a general-purpose code graph tool that indexes source code into a graph database (KuzuDB/Neo4j/FalkorDB), making it queryable by AI assistants via MCP or directly via CLI. It supports 18 languages using tree-sitter for AST parsing.

Scatter is a .NET-focused dependency analyzer that answers "If I change this class, which projects are affected?" — tracing consumers through project references, namespace usage, class/method references, stored procedures, and CI/CD pipelines.

## Architectural Differences

| Aspect | CodeGraphContext | Scatter |
|--------|-----------------|---------|
| **Scope** | General-purpose, 18 languages | .NET-focused, deep domain knowledge |
| **Parsing** | tree-sitter AST + optional SCIP | Regex patterns |
| **Graph storage** | Persistent graph DB (KuzuDB/Neo4j) | In-memory + JSON cache |
| **Project-level analysis** | None (source code only) | .csproj references, namespaces, pipelines |
| **Build/deploy awareness** | None | Pipeline mapping, batch job verification |
| **Git integration** | None | Branch diff, hybrid LLM extraction |
| **DB dependencies** | None | Sproc tracing, shared DB state |
| **Output** | CLI, MCP server, interactive HTML | Console, CSV, JSON |
| **AI integration** | MCP server (AI queries the graph) | Gemini (summarization, impact analysis) |

## CGC Architecture

### Graph Data Model

CGC captures 14 node types (Repository, Directory, File, Module, Function, Class, Variable, Interface, Struct, Enum, Trait, Record, Property, Parameter) and 7 relationship types (CONTAINS, CALLS, IMPORTS, INHERITS, IMPLEMENTS, HAS_PARAMETER, INCLUDES).

Each node carries rich metadata: source code, line numbers, docstrings, cyclomatic complexity, decorators, and language. Nodes are uniquely constrained by (name, path, line_number).

### Indexing Pipeline

1. **File Discovery** — Recursive scan respecting `.cgcignore` files (gitignore syntax)
2. **Pre-scan** — Quick pass over all files to build a global `symbol → file` map
3. **First Pass** — tree-sitter AST parsing creates File, Function, Class, Variable nodes and CONTAINS edges
4. **Second Pass** — Cross-file CALLS and INHERITS resolution using the pre-scan imports map

### Cross-File Resolution

CALLS edges use cascading heuristic resolution:
1. Check for `self`/`this`/`super` context → resolve to caller's file
2. Check if called name is local to the file
3. Check inferred object type
4. Look up in imports map with disambiguation
5. Multiple Cypher MERGE attempts (Function→Function, Function→Class with `__init__`, etc.)
6. Global fallback search

This approach has known limitations — Issue #686 confirms "find_all_callers misses callers across files."

### Notable Techniques

- **Hybrid SCIP + tree-sitter**: SCIP provides compiler-level accuracy for CALLS edges; tree-sitter supplements source text, complexity metrics, and decorators
- **Dictionary-based indirect call detection** (Python): Detects `tool_map = {"name": self.method}` patterns
- **KuzuDB Cypher translation layer**: Translates Neo4j Cypher to KuzuDB Cypher on the fly, enabling backend-agnostic graph building
- **Standalone HTML visualization**: vis-network.js with dark mode, click-to-inspect panels, live search, force-directed layouts — all inlined in a single HTML file
- **Pre-indexed bundles (.cgc files)**: Famous repos can be pre-indexed and distributed

## What CGC Lacks That Scatter Already Has

- **No project-level dependency analysis** — doesn't understand .csproj, NuGet, or build systems
- **No incremental indexing** — re-scans everything on any file change
- **No CI/CD mapping** — no pipeline awareness
- **No git branch analysis** — can't diff feature branches
- **No stored procedure / DB dependency tracking**
- **No impact analysis or risk assessment**
- **Single-threaded indexing** — no parallel processing
- **No domain boundary detection** — no clustering or extraction feasibility scoring
- **No coupling metrics** — no fan_in/fan_out/instability/coupling_score

## Lessons for Scatter

### 1. Interactive HTML Visualization (HIGH VALUE)

CGC generates standalone HTML files using vis-network.js with:
- Click-to-inspect side panels with symbol details and code snippets
- Live search/filter across the graph
- Force-directed and hierarchical layout options
- Dark mode with glassmorphism styling
- Zero external dependencies (all JS/CSS inlined)

This directly maps to our planned HTML report engine (Initiative 6). The single self-contained file pattern is ideal for enterprise sharing (email, SharePoint, Confluence). Their implementation (`visualizer.py`, ~1,000 lines) is a good reference.

### 2. MCP Server for AI Assistants (MEDIUM-HIGH VALUE)

CGC exposes 16 tools via the Model Context Protocol, letting AI IDEs (Cursor, VS Code, Claude) query the code graph conversationally. Scatter could expose blast radius queries, dependency lookups, and impact analysis as MCP tools — e.g., "If I change PortalDataService, what pipelines are affected?" This would differentiate Scatter in the AI-assisted development ecosystem.

### 3. Tree-sitter / Roslyn for Parsing (HIGH VALUE, longer term)

CGC uses tree-sitter for proper AST parsing instead of regex. For C# specifically, the more relevant option is **SCIP via scip-dotnet** (Roslyn-based), which provides compiler-level accuracy for type resolution, method calls, and inheritance. This would eliminate our regex edge cases (comments in some contexts, strings, complex generics, partial classes across files). CGC validates the hybrid approach — use fast heuristics by default, upgrade to compiler-level when available.

### 4. Two-Pass Symbol Resolution (VALIDATED)

CGC pre-scans all files to build a global `symbol → file` map, then resolves cross-file references in a second pass. This is conceptually identical to our inverted index for type_usage edges (tokenize identifiers, intersect with known types). Validates our architectural approach.

### 5. Embedded Graph Database (MEDIUM VALUE)

CGC defaults to KuzuDB — an embedded graph database with zero config, cross-platform support, and Cypher queries. This sits between our in-memory graph and a full Neo4j server. For Scatter, an embedded graph DB could enable ad-hoc Cypher queries (useful for power users and AI agents) without operational burden. Worth evaluating if our JSON cache becomes a bottleneck or if we add an MCP server.

### 6. Cyclomatic Complexity on Nodes (LOW-MEDIUM VALUE)

CGC computes cyclomatic complexity during parsing and stores it on Function nodes, enabling queries like "find the 10 most complex functions." This could augment Scatter's blast radius analysis — flagging that a consumer has high-complexity code paths increases its testing priority.

## Recommendations (Prioritized — updated 2026-03-13)

Resequenced to align with adoption-driven priorities. Adoption enablers
(Claude skills, CI/CD gates) come before polish features (HTML, MCP).

1. **Claude Code skills** — Ship 5 skills in `.claude/skills/` that invoke scatter CLI. Zero new Python code, 1 day effort. This is the fastest path to adoption and makes scatter conversational. (See `CLAUDE_INTEGRATION_EVALUATION.md` for details.)

2. **HTML visualization** — Adopt the self-contained HTML pattern with vis-network.js for Initiative 6's HTML report engine. CGC's approach is proven. **Tier 3 priority** — ship after CI/CD gates and adoption is established.

3. **MCP server** — Consider adding an MCP server mode when cross-client demand materializes. AI-assisted dependency querying is a compelling differentiator. **Tier 4 — deferred** per CLAUDE_INTEGRATION_EVALUATION: skills first.

4. **SCIP/Roslyn evaluation** — Investigate `scip-dotnet` as a potential replacement for regex-based type extraction. Significant accuracy improvement, but also a significant undertaking. **Tier 4 — deferred** until regex edge cases become a real adoption blocker.

5. **KuzuDB evaluation** — If our JSON graph cache becomes a bottleneck at scale, KuzuDB's embedded approach is worth benchmarking. **Tier 4 — deferred** until scale demands it.

## Summary

CGC is broader but shallower — it indexes 18 languages at the source code level. Scatter is narrower but deeper — it understands .NET project structures, build systems, deployment pipelines, database dependencies, and produces AI-enriched impact reports. The biggest transferable ideas are interactive HTML visualization, MCP server integration, and (longer term) compiler-level parsing via SCIP/Roslyn.
