# Scanners

## Type Scanner

::: scatter.scanners.type_scanner
    options:
      members:
        - extract_type_names_from_content
        - find_enclosing_type_name

## Project Scanner

::: scatter.scanners.project_scanner
    options:
      members:
        - find_project_file_on_disk
        - derive_namespace
        - parse_csproj_all_references

## Stored Procedure Scanner

::: scatter.scanners.sproc_scanner
    options:
      members:
        - find_cs_files_referencing_sproc

## Database Scanner

::: scatter.scanners.db_scanner
    options:
      members:
        - DbDependency
        - scan_db_dependencies
        - build_db_dependency_matrix
        - add_db_edges_to_graph
