# Graph Store

## Graph Cache

::: scatter.store.graph_cache
    options:
      members:
        - FileFacts
        - ProjectFacts
        - save_graph
        - load_graph
        - load_and_validate
        - is_cache_valid
        - get_default_cache_path
        - compute_content_hash

## Graph Patcher

::: scatter.store.graph_patcher
    options:
      members:
        - PatchResult
        - extract_file_facts
        - extract_project_facts
        - get_changed_files
        - patch_graph
