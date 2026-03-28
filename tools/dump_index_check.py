"""Sanity-check the codebase index at scale.

Builds the dependency graph for a given search scope, generates the
codebase index, prints diagnostics, and optionally writes the full
index text to a file for manual inspection.

Usage:
    python tools/dump_index_check.py /path/to/monolith
    python tools/dump_index_check.py /path/to/monolith -o index_output.txt
    python tools/dump_index_check.py /path/to/monolith --full-type-scan
"""

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scatter.analyzers.graph_builder import build_dependency_graph
from scatter.ai.codebase_index import build_codebase_index
from scatter.scanners.solution_scanner import scan_solutions, build_project_to_solutions
from scatter.modes.setup import populate_graph_solutions


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanity-check codebase index at scale")
    parser.add_argument("search_scope", type=Path, help="Root directory to scan")
    parser.add_argument("-o", "--output", type=Path, help="Write index text to file")
    parser.add_argument("--full-type-scan", action="store_true", help="Enable full type scanning")
    parser.add_argument("--no-multiprocessing", action="store_true", help="Disable multiprocessing")
    args = parser.parse_args()

    scope = args.search_scope.resolve(strict=True)

    # --- Build graph ---
    print(f"Building graph for: {scope}")
    t0 = time.perf_counter()
    graph = build_dependency_graph(
        scope,
        disable_multiprocessing=args.no_multiprocessing,
        full_type_scan=args.full_type_scan,
    )
    solutions = scan_solutions(scope)
    sol_index = build_project_to_solutions(solutions)
    populate_graph_solutions(graph, sol_index)
    graph_time = time.perf_counter() - t0
    print(f"Graph built in {graph_time:.2f}s")

    # --- Build index ---
    t1 = time.perf_counter()
    index = build_codebase_index(graph, scope)
    index_time = time.perf_counter() - t1
    print(f"Index built in {index_time:.2f}s")

    # --- Diagnostics ---
    print()
    print("=== Index Diagnostics ===")
    print(f"  Projects:    {index.project_count}")
    print(f"  Types:       {index.type_count}")
    print(f"  Sprocs:      {index.sproc_count}")
    print(f"  Files:       {index.file_count}")
    print(f"  Size:        {index.size_bytes:,} bytes")
    print(f"  ~Tokens:     ~{index.size_bytes // 4:,}")

    # Sanity checks
    problems = []
    if index.project_count == 0:
        problems.append("FAIL: zero projects in index")
    if index.type_count == 0:
        problems.append("WARN: zero types extracted — index has no type data for LLM")

    # Check for empty projects (projects with no types)
    lines = index.text.splitlines()
    project_lines = [l for l in lines if l.startswith("P:")]
    empty_projects = [l for l in project_lines if "T:" not in l]
    coverage_pct = ((len(project_lines) - len(empty_projects)) / max(len(project_lines), 1)) * 100

    print(f"  Coverage:    {coverage_pct:.1f}% of projects have types")
    print(f"  Empty:       {len(empty_projects)} projects with no type declarations")

    if coverage_pct < 50:
        problems.append(f"WARN: only {coverage_pct:.0f}% type coverage — most projects have no types")

    if problems:
        print()
        for p in problems:
            print(f"  ** {p}")

    # --- Output ---
    if args.output:
        args.output.write_text(index.text, encoding="utf-8")
        print(f"\nIndex written to: {args.output}")
    else:
        print("\nFirst 40 lines of index:")
        print("---")
        for line in lines[:40]:
            print(line)
        if len(lines) > 40:
            print(f"... ({len(lines) - 40} more lines)")
        print("---")
        print(f"\nTip: use -o index.txt to write full index to file")

    return 1 if any(p.startswith("FAIL") for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
