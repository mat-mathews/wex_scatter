# Initiative 5 Phase 6: Graph Reporters + Health Dashboard

## Context

The `--graph` mode works with console and JSON output but lacks actionable insights. The console shows raw metric tables with no interpretation. The JSON always dumps the full graph topology (large). There's no CSV export, no Mermaid diagrams, and no health observations. This phase makes the graph output useful for humans (observations, member lists, Mermaid) and machines (CSV, health dashboard, topology control).

## Files to Create/Modify

| File | Changes |
|------|---------|
| `scatter/analyzers/health_analyzer.py` (NEW) | `HealthDashboard`, `Observation` dataclasses + `compute_health_dashboard()` |
| `scatter/reports/graph_reporter.py` | Add `generate_mermaid()`, `write_graph_csv_report()`; modify `print_graph_report()` + `build_graph_json()` + `write_graph_json_report()` |
| `scatter/__main__.py` | Add `--include-graph-topology` flag; wire dashboard; replace CSV error with export |
| `scatter/__init__.py` | Export new public symbols |
| `test_reporters.py` (NEW) | ~14 tests |

## Step 1: Health Analyzer (`scatter/analyzers/health_analyzer.py`)

### Data Models

```python
@dataclass
class Observation:
    project: str           # project or cluster name
    rule: str              # machine-readable id: "stable_core", "high_coupling", etc.
    message: str           # human-readable message
    severity: str          # "info" | "warning" | "critical"

@dataclass
class HealthDashboard:
    total_projects: int
    total_edges: int
    total_cycles: int
    total_clusters: int
    avg_fan_in: float
    avg_fan_out: float
    avg_instability: float
    avg_coupling_score: float
    max_coupling_project: Optional[str]
    max_coupling_score: float
    db_hotspots: List[str]               # sprocs shared by 3+ projects
    observations: List[Observation]
```

### `compute_health_dashboard(graph, metrics, cycles, clusters=None)`

- Compute averages from `metrics.values()`
- Find max coupling project from `metrics`
- Build DB hotspot list: iterate `graph.get_all_nodes()`, build sproc-to-projects map, find sprocs in 3+ projects
- Generate observations via `_generate_observations()` helper

### Observation Rules (deterministic, no AI)

Thresholds as module constants:

```python
HIGH_FAN_IN_THRESHOLD = 5
LOW_INSTABILITY_THRESHOLD = 0.3
HIGH_COUPLING_THRESHOLD = 8.0
LOW_COHESION_THRESHOLD = 0.3
HIGH_SHARED_DB_DENSITY_THRESHOLD = 0.5
```

| Condition | Rule ID | Severity | Message pattern |
|-----------|---------|----------|-----------------|
| fan_in >= 5 and instability <= 0.3 | `stable_core` | warning | "{name}: stable core (fan_in={n}, instability={x:.2f}) — change carefully" |
| coupling_score >= 8.0 | `high_coupling` | warning | "{name}: high coupling score ({x:.1f}) — review dependencies" |
| Project in any cycle | `in_cycle` | critical | "{name}: participates in circular dependency — must break before extraction" |
| Cluster max coupling >= 8.0 and cohesion <= 0.3 | `low_cohesion_cluster` | warning | "{cluster}: high coupling + low cohesion ({x:.3f}) — consider splitting" |
| Sproc shared by 3+ projects | `db_hotspot` | info | "{sproc}: shared by {n} projects — database coupling hotspot" |

## Step 2: Graph Reporter Additions (`scatter/reports/graph_reporter.py`)

### New: `generate_mermaid(graph, clusters=None, top_n=None) -> str`

- Render `project_reference` edges only (strongest signal, avoids noise)
- Sanitize node IDs: replace `.` with `_`, use `["original.name"]` labels
- If `clusters` provided, wrap grouped nodes in `subgraph` blocks
- If `top_n` set, include only the top-N nodes by degree (fan_in + fan_out of project_reference edges), filter edges to those where both endpoints are in the set
- Empty graph returns `graph TD\n`

### New: `write_graph_csv_report(graph, metrics, output_path, clusters=None)`

Fieldnames (13 columns):
```
Project, Namespace, FanIn, FanOut, Instability, CouplingScore,
AfferentCoupling, EfferentCoupling, SharedDbDensity, TypeExportCount,
ConsumerCount, Cluster, ExtractionFeasibility
```

- Build `project -> (cluster_name, feasibility)` lookup from clusters list
- Iterate `sorted(metrics.items())`, look up namespace from `graph.get_node(name)`
- Write via `csv.DictWriter`

### Modify: `print_graph_report(graph, ranked, cycles, clusters=None, dashboard=None)`

Add `dashboard: Optional[HealthDashboard] = None` parameter. Two new sections:

**Cluster members** — after each cluster row, print top 5 member names:
```
  GalaxyWorks                         3      0.333      0.500   moderate (0.650)
    Members: GalaxyWorks.Data, GalaxyWorks.WebPortal, GalaxyWorks.BatchProcessor
```

**Observations** — if dashboard provided and has observations:
```
  Observations:
    [warning] GalaxyWorks.Data: stable core (fan_in=7, instability=0.00) — change carefully
    [critical] ProjectA: participates in circular dependency — must break before extraction
```

### Modify: `build_graph_json(...)` — add two params

```python
include_topology: bool = True,              # True preserves backward compat for direct callers
dashboard: Optional[HealthDashboard] = None,
```

- When `include_topology` is False, omit the `"graph": graph.to_dict()` key
- When `dashboard` provided, add `"health_dashboard"` key with `dataclasses.asdict(dashboard)`

### Modify: `write_graph_json_report(...)` — pass through new params

Add `include_topology: bool = True` and `dashboard` params, forward to `build_graph_json()`.

## Step 3: CLI Wiring (`scatter/__main__.py`)

### New flag

```python
common_group.add_argument(
    "--include-graph-topology", action="store_true",
    help="Include raw graph topology (nodes/edges) in JSON output. Omitted by default to reduce file size."
)
```

Not wired through config — just a direct CLI flag.

### Graph mode block changes

After computing `clusters`:
```python
from scatter.analyzers.health_analyzer import compute_health_dashboard
dashboard = compute_health_dashboard(graph, metrics, cycles, clusters=clusters)
```

Console call gets `dashboard=dashboard`.

JSON call gets `include_topology=args.include_graph_topology` and `dashboard=dashboard`.

Replace CSV error block with:
```python
elif args.output_format == "csv":
    if not args.output_file:
        logging.error("CSV output format requires the --output-file argument.")
        sys.exit(1)
    from scatter.reports.graph_reporter import write_graph_csv_report
    write_graph_csv_report(graph, metrics, Path(args.output_file), clusters=clusters)
    logging.info(f"Graph CSV report written to {args.output_file}")
```

## Step 4: Exports (`scatter/__init__.py`)

```python
from scatter.analyzers.health_analyzer import (
    HealthDashboard,
    Observation,
    compute_health_dashboard,
)
from scatter.reports.graph_reporter import generate_mermaid, write_graph_csv_report
```

## Step 5: Tests (`test_reporters.py`)

Pytest-style classes, `tmp_path` fixture. Helper: `_make_node()`, `_sample_graph()` (A→B→C DAG), plus a cycle variant for observation tests.

### TestMermaidOutput (~4)
- `test_mermaid_basic` — starts with `graph TD`, contains project_reference edge `A` → `B`, omits namespace_usage edge
- `test_mermaid_with_clusters` — `subgraph` keyword present
- `test_mermaid_top_n` — with top_n=2, at most 2 node IDs in output
- `test_mermaid_empty_graph` — returns `graph TD\n`

### TestHealthDashboard (~4)
- `test_computes_averages` — avg_fan_in/avg_fan_out are reasonable floats
- `test_stable_core_observation` — high fan_in + low instability triggers "stable_core"
- `test_cycle_observation` — graph with cycle produces "in_cycle" observation
- `test_empty_graph` — no crash, zeroed dashboard

### TestGraphConsoleOutput (~2)
- `test_cluster_members_shown` — "Members:" in captured stdout
- `test_observations_shown` — severity tag `[warning]` or `[critical]` in output

### TestGraphCsvExport (~2)
- `test_csv_columns_and_rows` — 13 columns in header, row count matches project count
- `test_csv_cluster_column` — cluster name populated for clustered projects

### TestGraphJsonTopologyFlag (~2)
- `test_includes_topology_by_default` — `"graph"` key present when `include_topology=True`
- `test_omits_topology_when_false` — `"graph"` key absent when `include_topology=False`

## Implementation Order

1. Create `scatter/analyzers/health_analyzer.py` (no deps on reporter changes)
2. Modify `scatter/reports/graph_reporter.py` (all additions + modifications)
3. Modify `scatter/__main__.py` (wire flag, dashboard, CSV)
4. Modify `scatter/__init__.py` (exports)
5. Create `test_reporters.py`
6. Run full test suite

## Verification

```bash
python -m pytest test_reporters.py -v
python -m pytest test_graph.py test_coupling.py test_domain.py test_report_quality.py -v
python -m pytest --tb=short   # full suite — expect 421+ existing + ~14 new
```
