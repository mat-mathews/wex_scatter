# Architecture Overview

This is the technical map of Scatter. If you want to know where something lives, how data flows through the system, or why a module exists, start here.

---

## Directory Structure

```
scatter/
├── core/              # Data models, graph, parallel infrastructure
│   ├── graph.py       # DependencyGraph, ProjectNode, DependencyEdge
│   ├── models.py      # FilterPipeline, FilterStage, ImpactReport, constants
│   ├── parallel.py    # ProcessPoolExecutor orchestrators and workers
│   ├── patterns.py    # Compiled regex (IDENT, SPROC, USING patterns)
│   └── tree.py        # Tree rendering utilities
│
├── scanners/          # File, project, type, sproc, DB scanning
│   ├── file_scanner.py
│   ├── project_scanner.py   # .csproj parsing, namespace derivation
│   ├── type_scanner.py      # C# type declaration extraction
│   ├── sproc_scanner.py     # Stored procedure reference detection
│   └── db_scanner.py        # Database dependency scanning, comment stripping
│
├── analyzers/         # Consumer, git, graph builder, impact, coupling, domain, health
│   ├── consumer_analyzer.py  # 5-stage filter pipeline
│   ├── git_analyzer.py       # Branch diff analysis
│   ├── graph_builder.py      # Single-pass O(P+F) graph construction
│   ├── graph_enrichment.py   # Graph context loading, result enrichment
│   ├── impact_analyzer.py    # SOW-driven impact analysis
│   ├── coupling_analyzer.py  # Metrics + Tarjan's cycle detection
│   ├── domain_analyzer.py    # Clustering + extraction feasibility
│   └── health_analyzer.py    # Health dashboard computation
│
├── ai/                # Provider protocol, router, task modules
│   ├── base.py        # AIProvider protocol, AITaskType enum, AnalysisResult
│   ├── router.py      # AIRouter with lazy creation and task-type routing
│   ├── providers/
│   │   ├── gemini_provider.py
│   │   └── wex_provider.py    # WEX AI Platform (stubbed)
│   └── tasks/
│       ├── parse_work_request.py
│       ├── risk_assess.py
│       ├── coupling_narrative.py
│       ├── impact_narrative.py
│       └── complexity_estimate.py
│
├── reports/           # Console, JSON, CSV, markdown, graph, pipeline reporters
│   ├── console_reporter.py
│   ├── json_reporter.py
│   ├── csv_reporter.py
│   ├── markdown_reporter.py
│   ├── graph_reporter.py
│   └── pipeline_reporter.py
│
├── store/             # Graph cache, graph patcher
│   ├── graph_cache.py    # Persistence, invalidation, FileFacts, ProjectFacts
│   └── graph_patcher.py  # Incremental updates via git diff
│
├── compat/            # V1 bridge (solution lookup, pipeline mapping)
│   └── v1_bridge.py
│
├── config.py          # YAML config with layered precedence
├── cli.py             # Mode handlers, output dispatch (~766 lines)
├── cli_parser.py      # Argument parsing (~197 lines)
└── __main__.py        # Entry point, mode dispatch (~506 lines)
```

---

## Design Principles

Three rules govern every module in Scatter. Break one and you will hear about it in review.

**1. The graph is data. Analysis is functions.**

`DependencyGraph` is a pure data structure -- mutation, query, traversal, serialization. That is its entire job. Every analysis algorithm (cycles, metrics, clustering, feasibility scoring) is a standalone free function in its respective analyzer module, not a method on the graph. This keeps the graph lean and the analyzers independently testable.

```python
# This is how it works:
metrics = compute_all_metrics(graph)       # coupling_analyzer.py
cycles = detect_cycles(graph)              # coupling_analyzer.py
clusters = find_clusters(graph)            # domain_analyzer.py

# This is NOT how it works:
graph.compute_metrics()   # No. The graph doesn't know about metrics.
```

**2. Free functions over god objects.**

No class accumulates responsibilities across multiple concerns. `ModeContext` is a typed bag of resolved config -- it does not run analysis. `AIRouter` selects providers -- it does not call them. The mode handlers in `cli.py` are plain functions (`run_target_analysis`, `run_git_analysis`, `run_sproc_analysis`) that compose scanners, analyzers, and reporters. If you find yourself adding a method to a class and the class already does something unrelated, you are in the wrong place.

**3. Reporters are pure transforms.**

Every reporter takes structured data in, produces formatted output. No reporter queries the filesystem, calls git, or touches the graph. If a reporter needs data it does not have, the caller must provide it. This means reporters are trivially testable and cannot cause side effects.

---

## Data Flow

Every mode follows the same shape:

```
CLI args --> config --> mode handler --> scanners --> analyzers --> reporters --> output
```

### Target Project Mode

```
__main__.py: parse args, load config, build ModeContext
  --> cli.py: run_target_analysis()
    --> project_scanner: derive_namespace(target.csproj)
    --> consumer_analyzer: find_consumers()
        Stage 1: discover .csproj files (filesystem or graph)
        Stage 2: filter by ProjectReference
        Stage 3: filter by namespace usage
        Stage 4: filter by class name (optional)
        Stage 5: filter by method name (optional)
    --> graph_enrichment: enrich_legacy_results() (if graph available)
    --> v1_bridge: map to pipelines, solutions, batch jobs
  --> dispatch_legacy_output()
    --> console_reporter | json_reporter | csv_reporter | markdown_reporter
```

### Git Branch Mode

```
__main__.py: parse args, load config, build ModeContext
  --> cli.py: run_git_analysis()
    --> git_analyzer: analyze_branch_changes(repo, branch, base)
    --> type_scanner: extract_type_names_from_content() per changed file
    --> [optional] ai_provider: extract_affected_symbols() (hybrid mode)
    --> consumer_analyzer: find_consumers() per changed project/type
    --> graph_enrichment: enrich_legacy_results()
  --> dispatch_legacy_output()
```

### Impact Analysis Mode (SOW-driven)

```
__main__.py: parse args, load config, resolve SOW text
  --> impact_analyzer: run_impact_analysis()
    --> ai: parse work request --> extract AnalysisTargets
    --> consumer_analyzer: find_consumers() per target
    --> graph: transitive consumer BFS
    --> ai: risk assessment, coupling narrative per consumer
    --> ai: impact narrative, complexity estimate for report
  --> apply_impact_graph_enrichment()
  --> console_reporter | json_reporter | csv_reporter | markdown_reporter
```

### Graph Analysis Mode

```
__main__.py: parse args, load config
  --> graph_cache: load_and_validate() (try cache first)
  --> graph_builder: build_dependency_graph() (if no cache)
  --> graph_cache: save_graph()
  --> coupling_analyzer: compute_all_metrics(), detect_cycles(), rank_by_coupling()
  --> domain_analyzer: find_clusters()
  --> health_analyzer: compute_health_dashboard()
  --> graph_reporter | json_reporter | markdown_reporter | mermaid
```

---

## The AI Provider System

The AI layer follows a protocol-based design with three moving parts.

### AIProvider Protocol

Defined in `ai/base.py`. Any class that implements these five methods is a valid provider:

```python
@runtime_checkable
class AIProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def max_context_size(self) -> int: ...

    def analyze(self, prompt: str, context: str, task_type: AITaskType) -> AnalysisResult: ...
    def supports(self, task_type: AITaskType) -> bool: ...
    def estimate_tokens(self, context: str) -> int: ...
```

Eight task types are defined in `AITaskType`:

| Task Type | Used By |
|-----------|---------|
| `SUMMARIZATION` | Consumer file summaries |
| `SYMBOL_EXTRACTION` | Hybrid git analysis |
| `WORK_REQUEST_PARSING` | Impact analysis SOW parsing |
| `RISK_ASSESSMENT` | Per-consumer risk rating |
| `COUPLING_NARRATIVE` | Per-consumer coupling story |
| `IMPACT_NARRATIVE` | Report-level impact summary |
| `COMPLEXITY_ESTIMATE` | Effort/complexity rating |
| `BOUNDARY_ASSESSMENT` | Domain extraction analysis |

### AIRouter

`ai/router.py` resolves which provider handles which task. Resolution order:

1. `task_overrides[task_type]` from config (if specified)
2. `default_provider` from config (defaults to `"gemini"`)

Providers are lazily created on first use and cached in a dict. If creation fails (missing credentials, import error), the router returns `None` and the caller gracefully degrades.

```python
router = AIRouter(config)
provider = router.get_provider(AITaskType.SUMMARIZATION)
# Returns GeminiProvider or None
```

### Task Modules

Each `ai/tasks/` module contains prompt templates and response parsing for a specific task type. The task module builds the prompt, the provider executes it, the task module parses the response. Clean separation.

### Providers

**GeminiProvider** (`ai/providers/gemini_provider.py`) — the current default. Wraps the `google-generativeai` SDK. Supports all eight task types. Model defaults to `gemini-2.0-flash`, configurable via `ai.gemini_model` in config or `--gemini-model` CLI flag.

**WexProvider** (`ai/providers/wex_provider.py`) — stubbed for the WEX AI Platform, the company's centralized AI gateway. Instantiation succeeds (validates API key), but analysis calls raise `NotImplementedError` until the API contract is finalized. Will become the default provider once integrated. Configurable via `WEX_AI_API_KEY` env var or `--wex-api-key` CLI flag.

---

## Configuration System

Defined in `config.py`. Four dataclasses, five precedence layers.

### Dataclasses

```python
@dataclass
class ScatterConfig:
    ai: AIConfig           # Provider, model, credentials, task overrides
    graph: GraphConfig     # Cache dir, rebuild flag, invalidation strategy, coupling weights
    db: DbConfig           # Sproc prefixes, include_db_edges flag
    max_depth: int = 2
    disable_multiprocessing: bool = False
    max_workers: Optional[int] = None
    chunk_size: Optional[int] = None
    exclude_patterns: List[str] = ["*/bin/*", "*/obj/*"]
```

### Layered Precedence

Highest wins. Each layer can override any field set by a lower layer.

| Priority | Source | Location |
|----------|--------|----------|
| 1 (highest) | CLI flags | `--google-api-key`, `--max-depth`, etc. |
| 2 | Repo config | `.scatter.yaml` in the repository root |
| 3 | User config | `~/.scatter/config.yaml` |
| 4 | Environment | `GOOGLE_API_KEY`, `SCATTER_DEFAULT_PROVIDER` |
| 5 (lowest) | Defaults | Hardcoded in dataclass definitions |

The loading sequence in `load_config()` applies layers bottom-up: start with defaults, apply env vars, apply user config, apply repo config, apply CLI overrides. Later layers overwrite earlier ones.

### Example `.scatter.yaml`

```yaml
ai:
  default_provider: gemini
  gemini_model: gemini-1.5-pro
  task_overrides:
    risk_assessment: gemini

graph:
  invalidation: git
  coupling_weights:
    project_reference: 1.0
    sproc_shared: 0.8
    namespace_usage: 0.5
    type_usage: 0.3

db:
  sproc_prefixes: ["sp_", "usp_", "proc_"]
  include_db_edges: true

search:
  max_depth: 3
  exclude_patterns:
    - "*/bin/*"
    - "*/obj/*"
    - "*/test/*"

multiprocessing:
  disabled: false
  max_workers: 16
  chunk_size: 100
```

Note that `exclude_patterns` in config **replaces** the default list entirely -- if you override it, you must re-include `*/bin/*` and `*/obj/*` if you still want them excluded. This follows the convention that list-valued config is explicit, not additive.
