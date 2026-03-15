"""Benchmark incremental graph patching vs full rebuild at various scales.

Generates synthetic codebases, builds a full graph with v2 facts, then
applies controlled mutations and times patch_graph() vs full rebuild.

Usage:
    python tools/benchmark_incremental.py
    python tools/benchmark_incremental.py --preset small
    python tools/benchmark_incremental.py --preset large --runs 3
    python tools/benchmark_incremental.py --json -o results.json
"""
import argparse
import gc
import json
import random
import shutil
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.generate_synthetic_codebase import generate_codebase, PRESETS


# ---------------------------------------------------------------------------
# Mutation helpers — apply controlled changes to a synthetic codebase
# ---------------------------------------------------------------------------

def _pick_random_cs(search_scope: Path, n: int = 1, seed: int = 99) -> list[Path]:
    """Pick n random .cs files from the codebase."""
    rng = random.Random(seed)
    all_cs = list(search_scope.rglob("*.cs"))
    return rng.sample(all_cs, min(n, len(all_cs)))


def _pick_random_csproj(search_scope: Path, n: int = 1, seed: int = 99) -> list[Path]:
    rng = random.Random(seed)
    all_csproj = list(search_scope.rglob("*.csproj"))
    return rng.sample(all_csproj, min(n, len(all_csproj)))


def mutate_usage_only(search_scope: Path, n_files: int = 1) -> list[str]:
    """Change a using statement in n .cs files (no declaration changes)."""
    targets = _pick_random_cs(search_scope, n_files, seed=42)
    changed = []
    for cs in targets:
        content = cs.read_text(encoding="utf-8", errors="ignore")
        # Add a harmless using statement
        content = "using System.Diagnostics;\n" + content
        cs.write_text(content, encoding="utf-8")
        changed.append(str(cs.relative_to(search_scope)))
    return changed


def mutate_declaration(search_scope: Path, n_files: int = 1) -> list[str]:
    """Add a new class declaration to n .cs files."""
    targets = _pick_random_cs(search_scope, n_files, seed=43)
    changed = []
    for i, cs in enumerate(targets):
        content = cs.read_text(encoding="utf-8", errors="ignore")
        new_class = f"\npublic class BenchNewType{i}_{int(time.time())} {{ }}\n"
        content += new_class
        cs.write_text(content, encoding="utf-8")
        changed.append(str(cs.relative_to(search_scope)))
    return changed


def mutate_new_file(search_scope: Path, n_files: int = 1) -> list[str]:
    """Add n new .cs files to existing projects."""
    rng = random.Random(44)
    projects = [p.parent for p in search_scope.rglob("*.csproj")]
    changed = []
    for i in range(min(n_files, len(projects))):
        proj_dir = rng.choice(projects)
        new_file = proj_dir / f"BenchNewFile{i}_{int(time.time())}.cs"
        proj_name = proj_dir.name.replace(".", "_")
        new_file.write_text(
            f"namespace {proj_name}\n{{\n    public class BenchNew{i} {{ }}\n}}\n",
            encoding="utf-8",
        )
        changed.append(str(new_file.relative_to(search_scope)))
    return changed


def mutate_delete_file(search_scope: Path, n_files: int = 1) -> list[str]:
    """Delete n .cs files."""
    targets = _pick_random_cs(search_scope, n_files, seed=45)
    changed = []
    for cs in targets:
        rel = str(cs.relative_to(search_scope))
        cs.unlink()
        changed.append(rel)
    return changed


def mutate_csproj_ref(search_scope: Path) -> list[str]:
    """Change a project reference in a .csproj (modify, not add/remove project)."""
    targets = _pick_random_csproj(search_scope, 1, seed=46)
    changed = []
    for csproj in targets:
        content = csproj.read_text(encoding="utf-8", errors="ignore")
        # Add a comment (changes content hash without structural change)
        content = content.replace("</Project>", "  <!-- benchmark touch -->\n</Project>")
        csproj.write_text(content, encoding="utf-8")
        changed.append(str(csproj.relative_to(search_scope)))
    return changed


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "name": "1 file usage-only",
        "mutate": lambda scope: mutate_usage_only(scope, 1),
    },
    {
        "name": "5 files usage-only",
        "mutate": lambda scope: mutate_usage_only(scope, 5),
    },
    {
        "name": "10 files usage-only",
        "mutate": lambda scope: mutate_usage_only(scope, 10),
    },
    {
        "name": "1 file declaration change",
        "mutate": lambda scope: mutate_declaration(scope, 1),
    },
    {
        "name": "5 files declaration change",
        "mutate": lambda scope: mutate_declaration(scope, 5),
    },
    {
        "name": "1 new file",
        "mutate": lambda scope: mutate_new_file(scope, 1),
    },
    {
        "name": "5 new files",
        "mutate": lambda scope: mutate_new_file(scope, 5),
    },
    {
        "name": "1 file deleted",
        "mutate": lambda scope: mutate_delete_file(scope, 1),
    },
    {
        "name": "1 csproj modified",
        "mutate": lambda scope: mutate_csproj_ref(scope),
    },
]


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_full_build(search_scope: Path) -> tuple:
    """Full graph build with fact capture. Returns (graph, file_facts, project_facts, elapsed_s)."""
    from scatter.analyzers.graph_builder import build_dependency_graph

    gc.collect()
    t0 = time.perf_counter()
    graph, file_facts, project_facts = build_dependency_graph(
        search_scope,
        disable_multiprocessing=True,
        exclude_patterns=["*/bin/*", "*/obj/*"],
        capture_facts=True,
    )
    elapsed = time.perf_counter() - t0
    return graph, file_facts, project_facts, elapsed


def run_patch(graph, file_facts, project_facts, changed_files, search_scope) -> tuple:
    """Run incremental patch. Returns (PatchResult, elapsed_s)."""
    from scatter.store.graph_patcher import patch_graph
    from scatter.store.graph_cache import compute_project_set_hash
    import copy

    # Deep copy graph to avoid mutation across scenarios
    graph_copy = copy.deepcopy(graph)
    ff_copy = dict(file_facts)
    pf_copy = dict(project_facts)
    proj_hash = compute_project_set_hash(list(pf_copy.keys()))

    gc.collect()
    t0 = time.perf_counter()
    result = patch_graph(
        graph_copy, ff_copy, pf_copy,
        changed_files, search_scope,
        cached_project_set_hash=proj_hash,
    )
    elapsed = time.perf_counter() - t0
    return result, elapsed


def run_benchmark_suite(
    preset_name: str,
    output_base: Path,
    runs: int = 1,
) -> dict:
    """Generate a codebase at a given scale and benchmark all scenarios."""
    preset = PRESETS[preset_name]
    search_scope = output_base / f"bench_{preset_name}"

    print(f"\n{'='*70}")
    print(f"PRESET: {preset_name} ({preset['projects']} projects, "
          f"{preset['files_per_project']} files/project)")
    print(f"{'='*70}")

    # Generate codebase
    print("Generating synthetic codebase...", end=" ", flush=True)
    t0 = time.perf_counter()
    stats = generate_codebase(
        output_dir=search_scope,
        num_projects=preset["projects"],
        files_per_project=preset["files_per_project"],
        coupling_pct=preset["coupling_pct"],
        sproc_pct=preset["sproc_pct"],
        avg_file_kb=preset["avg_file_kb"],
        seed=42,
    )
    gen_time = time.perf_counter() - t0
    print(f"{gen_time:.1f}s ({stats['cs_files']} .cs, {stats['csproj_files']} .csproj)")

    # Full build (baseline)
    print("Running full build (baseline)...", end=" ", flush=True)
    full_times = []
    for r in range(runs):
        # Regenerate between runs to reset mutations
        if r > 0:
            generate_codebase(
                output_dir=search_scope,
                num_projects=preset["projects"],
                files_per_project=preset["files_per_project"],
                coupling_pct=preset["coupling_pct"],
                sproc_pct=preset["sproc_pct"],
                avg_file_kb=preset["avg_file_kb"],
                seed=42,
            )
        graph, file_facts, project_facts, elapsed = run_full_build(search_scope)
        full_times.append(elapsed)
    full_median = sorted(full_times)[len(full_times) // 2]
    print(f"{full_median:.2f}s (median of {runs}), "
          f"{graph.node_count} nodes, {graph.edge_count} edges")

    # Run each scenario
    scenario_results = []
    for scenario in SCENARIOS:
        name = scenario["name"]

        patch_times = []
        patch_results = []
        for r in range(runs):
            # Reset codebase to clean state
            generate_codebase(
                output_dir=search_scope,
                num_projects=preset["projects"],
                files_per_project=preset["files_per_project"],
                coupling_pct=preset["coupling_pct"],
                sproc_pct=preset["sproc_pct"],
                avg_file_kb=preset["avg_file_kb"],
                seed=42,
            )
            # Re-build baseline graph from clean state
            graph, file_facts, project_facts, _ = run_full_build(search_scope)

            # Apply mutation
            changed = scenario["mutate"](search_scope)

            # Patch
            result, elapsed = run_patch(graph, file_facts, project_facts, changed, search_scope)
            patch_times.append(elapsed)
            patch_results.append(result)

        patch_median = sorted(patch_times)[len(patch_times) // 2]
        last_result = patch_results[-1]
        speedup = full_median / patch_median if patch_median > 0 else float("inf")

        scenario_results.append({
            "name": name,
            "patch_applied": last_result.patch_applied,
            "files_processed": last_result.files_processed,
            "projects_affected": last_result.projects_affected,
            "declarations_changed": last_result.declarations_changed,
            "patch_time_s": round(patch_median, 4),
            "patch_time_ms": round(patch_median * 1000, 1),
            "full_build_s": round(full_median, 4),
            "speedup": round(speedup, 1),
        })

        status = "PATCHED" if last_result.patch_applied else "REBUILD"
        print(f"  {name:<30} {patch_median*1000:>8.1f}ms  "
              f"{speedup:>6.1f}x  [{status}] "
              f"({last_result.files_processed} files, "
              f"{last_result.projects_affected} projects)")

    # Cleanup
    if search_scope.exists():
        shutil.rmtree(search_scope)

    return {
        "preset": preset_name,
        "config": preset,
        "codebase_stats": stats,
        "full_build_median_s": round(full_median, 4),
        "graph_nodes": graph.node_count,
        "graph_edges": graph.edge_count,
        "scenarios": scenario_results,
    }


def print_summary(all_results: list[dict]):
    """Print a comparison table across presets."""
    print(f"\n{'='*90}")
    print("INCREMENTAL PATCH BENCHMARK SUMMARY")
    print(f"{'='*90}")

    # Header
    presets = [r["preset"] for r in all_results]
    header = f"{'Scenario':<32}"
    for p in presets:
        header += f"  {p:>12}"
    print(f"\n{header}")
    print("-" * (32 + 14 * len(presets)))

    # Full build row
    row = f"{'Full rebuild (baseline)':<32}"
    for r in all_results:
        row += f"  {r['full_build_median_s']*1000:>10.0f}ms"
    print(row)
    print("-" * (32 + 14 * len(presets)))

    # Scenario rows (show speedup)
    scenario_names = [s["name"] for s in all_results[0]["scenarios"]]
    for sname in scenario_names:
        row = f"  {sname:<30}"
        for r in all_results:
            s = next(s for s in r["scenarios"] if s["name"] == sname)
            if s["patch_applied"]:
                row += f"  {s['speedup']:>9.0f}x  "
            else:
                row += f"  {'REBUILD':>10}  "
        print(row)

    print()
    print("(Higher speedup = better. REBUILD = fell back to full build.)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark incremental graph patching vs full rebuild."
    )
    parser.add_argument(
        "--preset", choices=list(PRESETS.keys()), nargs="*",
        default=["small", "medium"],
        help="Preset sizes to benchmark (default: small medium)",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Runs per scenario for median timing (default: 1)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="/tmp/scatter_bench",
        help="Temp directory for generated codebases (default: /tmp/scatter_bench)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "-o", "--output-file", type=str,
        help="Write JSON results to file",
    )

    args = parser.parse_args()
    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    import logging
    logging.basicConfig(level=logging.WARNING)

    all_results = []
    for preset_name in args.preset:
        result = run_benchmark_suite(preset_name, output_base, runs=args.runs)
        all_results.append(result)

    if args.json or args.output_file:
        output = json.dumps(all_results, indent=2, default=str)
        if args.output_file:
            Path(args.output_file).write_text(output)
            print(f"\nResults written to {args.output_file}")
        else:
            print(output)
    elif len(all_results) > 1:
        print_summary(all_results)


if __name__ == "__main__":
    main()
