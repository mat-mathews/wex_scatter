# Analyzers

## Consumer Analyzer

::: scatter.analyzers.consumer_analyzer
    options:
      members:
        - find_consumers

## Git Analyzer

::: scatter.analyzers.git_analyzer
    options:
      members:
        - analyze_branch_changes
        - get_diff_for_file
        - find_project_file

## Graph Builder

::: scatter.analyzers.graph_builder
    options:
      members:
        - build_dependency_graph

## Impact Analyzer

::: scatter.analyzers.impact_analyzer
    options:
      members:
        - run_impact_analysis
        - trace_transitive_impact

## Coupling Analyzer

::: scatter.analyzers.coupling_analyzer
    options:
      members:
        - ProjectMetrics
        - CycleGroup
        - compute_all_metrics
        - rank_by_coupling
        - detect_cycles

## Domain Analyzer

::: scatter.analyzers.domain_analyzer
    options:
      members:
        - Cluster
        - find_clusters
        - score_extraction_feasibility

## Health Analyzer

::: scatter.analyzers.health_analyzer
    options:
      members:
        - Observation
        - HealthDashboard
        - compute_health_dashboard

## Graph Enrichment

::: scatter.analyzers.graph_enrichment
    options:
      members:
        - GraphContext
        - build_graph_context
        - enrich_legacy_results
        - enrich_consumers
