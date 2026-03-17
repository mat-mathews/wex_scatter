# Core Models

## Data Models

::: scatter.core.models
    options:
      members:
        - AnalysisTarget
        - EnrichedConsumer
        - TargetImpact
        - ImpactReport
        - FilterStage
        - FilterPipeline

## Dependency Graph

::: scatter.core.graph
    options:
      members:
        - ProjectNode
        - DependencyEdge
        - DependencyGraph

## Parallel Processing

::: scatter.core.parallel
    options:
      members:
        - chunk_list
        - parse_csproj_files_parallel
        - map_cs_to_projects_parallel
        - analyze_cs_files_parallel
        - find_files_with_pattern_parallel
        - estimate_file_count
