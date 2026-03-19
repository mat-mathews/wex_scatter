"""Dump codebase index to file for inspection."""
import sys
from pathlib import Path

from scatter.analyzers.graph_builder import build_dependency_graph
from scatter.store.graph_cache import get_default_cache_path, load_and_validate, save_graph
from scatter.ai.codebase_index import build_codebase_index
from scatter.config import load_config


def main():
    search_scope = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("codebase_index.txt")

    search_scope = search_scope.resolve()
    config = load_config(repo_root=search_scope)

    # Try cache first
    cache_path = get_default_cache_path(search_scope)
    graph = None
    result = load_and_validate(cache_path, search_scope, config.graph.invalidation)
    if result:
        graph = result[0]
        print("Loaded graph from cache.")
    else:
        print("Building graph...")
        graph = build_dependency_graph(search_scope, exclude_patterns=config.exclude_patterns)
        save_graph(graph, cache_path, search_scope)

    index = build_codebase_index(graph, search_scope)
    output_file.write_text(index.text, encoding="utf-8")

    print(f"Wrote index to {output_file}")
    print(f"  {index.project_count} projects, {index.type_count} types, "
          f"{index.sproc_count} sprocs, {index.file_count} files, "
          f"{index.size_bytes:,} bytes")


if __name__ == "__main__":
    main()
