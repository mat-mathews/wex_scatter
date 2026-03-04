#!/usr/bin/env python3
"""
Phase 2.2 & 2.3 Benchmarking Tool
Performance testing for parallel XML parsing and project mapping.

Phase 2.2: parse_csproj_files_parallel() — XML parsing of .csproj files
Phase 2.3: map_cs_to_projects_parallel() — .cs-to-.csproj directory resolution
"""

import sys
import time
import json
import tempfile
import shutil
import re
import statistics
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent))
try:
    import scatter
except ImportError as e:
    print(f"Error importing scatter module: {e}")
    sys.exit(1)


class Phase22_23Benchmarker:
    """Benchmarking tool for Phase 2.2 (XML parsing) and 2.3 (project mapping)."""

    def __init__(self, output_dir: str = "benchmark_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.performance_targets = {
            "csproj_parsing": {"min_speedup": 1.5, "target_speedup": 3.0},
            "project_mapping": {"min_speedup": 1.5, "target_speedup": 3.0},
        }

    def _create_test_structure(self, base_dir: Path, num_projects: int,
                                files_per_project: int) -> Tuple[Path, List[Path], List[Path]]:
        """Create a synthetic .NET project structure for benchmarking."""
        test_dir = base_dir / f"bench_{num_projects}proj"
        if test_dir.exists():
            shutil.rmtree(test_dir)
        test_dir.mkdir(parents=True)

        # Create a target project that others will reference
        target_dir = test_dir / "TargetLib"
        target_dir.mkdir()
        target_csproj = target_dir / "TargetLib.csproj"
        target_csproj.write_text('''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>TargetLib</RootNamespace>
  </PropertyGroup>
</Project>''')

        csproj_files = []
        cs_files = []

        for i in range(num_projects):
            proj_dir = test_dir / f"Consumer{i:03d}"
            proj_dir.mkdir()

            # Half the projects reference the target
            has_ref = i % 2 == 0
            ref_xml = f'''
  <ItemGroup>
    <ProjectReference Include="..\\TargetLib\\TargetLib.csproj" />
  </ItemGroup>''' if has_ref else ''

            csproj_path = proj_dir / f"Consumer{i:03d}.csproj"
            csproj_path.write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>Consumer{i:03d}</RootNamespace>
  </PropertyGroup>{ref_xml}
</Project>''')
            csproj_files.append(csproj_path)

            for j in range(files_per_project):
                sub = proj_dir / "Services" if j % 3 == 0 else proj_dir
                sub.mkdir(exist_ok=True)
                cs_path = sub / f"Class{j:03d}.cs"
                cs_path.write_text(f'''using System;
namespace Consumer{i:03d} {{
    public class Class{j:03d} {{
        public void Run() {{ }}
    }}
}}''')
                cs_files.append(cs_path)

        return target_csproj, csproj_files, cs_files

    def _run_timed(self, func, args=(), kwargs=None, runs=3):
        """Run a function multiple times and return (avg_time, result)."""
        kwargs = kwargs or {}
        times = []
        result = None
        for r in range(runs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        return statistics.mean(times), result

    def benchmark_csproj_parsing(self, csproj_files: List[Path],
                                  target_csproj: Path,
                                  scenario: str, runs: int = 3) -> Dict:
        """Benchmark parse_csproj_files_parallel (Phase 2.2)."""
        print(f"\n  Phase 2.2 — csproj XML parsing ({len(csproj_files)} files)...")

        seq_time, seq_result = self._run_timed(
            scatter.parse_csproj_files_parallel,
            args=(csproj_files, target_csproj),
            kwargs={"disable_multiprocessing": True, "csproj_analysis_chunk_size": 25},
            runs=runs,
        )

        par_time, par_result = self._run_timed(
            scatter.parse_csproj_files_parallel,
            args=(csproj_files, target_csproj),
            kwargs={"disable_multiprocessing": False, "csproj_analysis_chunk_size": 25},
            runs=runs,
        )

        speedup = seq_time / par_time if par_time > 0 else 0
        seq_refs = sum(1 for v in seq_result.values() if v.get("has_reference"))
        par_refs = sum(1 for v in par_result.values() if v.get("has_reference"))

        result = {
            "test_type": "csproj_parsing",
            "scenario": scenario,
            "file_count": len(csproj_files),
            "avg_sequential_time": round(seq_time, 4),
            "avg_parallel_time": round(par_time, 4),
            "speedup_factor": round(speedup, 2),
            "refs_found_sequential": seq_refs,
            "refs_found_parallel": par_refs,
            "results_match": seq_refs == par_refs,
        }

        status = "MATCH" if result["results_match"] else "MISMATCH"
        print(f"    Sequential: {seq_time:.4f}s  Parallel: {par_time:.4f}s  "
              f"Speedup: {speedup:.2f}x  Refs: {seq_refs}/{par_refs} ({status})")
        return result

    def benchmark_project_mapping(self, cs_files: List[Path],
                                   scenario: str, runs: int = 3) -> Dict:
        """Benchmark map_cs_to_projects_parallel (Phase 2.3)."""
        print(f"\n  Phase 2.3 — project mapping ({len(cs_files)} files)...")

        seq_time, seq_result = self._run_timed(
            scatter.map_cs_to_projects_parallel,
            args=(cs_files,),
            kwargs={"disable_multiprocessing": True, "cs_analysis_chunk_size": 50},
            runs=runs,
        )

        par_time, par_result = self._run_timed(
            scatter.map_cs_to_projects_parallel,
            args=(cs_files,),
            kwargs={"disable_multiprocessing": False, "cs_analysis_chunk_size": 50},
            runs=runs,
        )

        speedup = seq_time / par_time if par_time > 0 else 0
        seq_mapped = sum(1 for v in seq_result.values() if v is not None)
        par_mapped = sum(1 for v in par_result.values() if v is not None)

        result = {
            "test_type": "project_mapping",
            "scenario": scenario,
            "file_count": len(cs_files),
            "avg_sequential_time": round(seq_time, 4),
            "avg_parallel_time": round(par_time, 4),
            "speedup_factor": round(speedup, 2),
            "mapped_sequential": seq_mapped,
            "mapped_parallel": par_mapped,
            "results_match": seq_mapped == par_mapped,
        }

        status = "MATCH" if result["results_match"] else "MISMATCH"
        print(f"    Sequential: {seq_time:.4f}s  Parallel: {par_time:.4f}s  "
              f"Speedup: {speedup:.2f}x  Mapped: {seq_mapped}/{par_mapped} ({status})")
        return result

    def run_comprehensive_benchmark(self) -> bool:
        """Run full Phase 2.2/2.3 benchmark suite."""
        print("=" * 72)
        print("PHASE 2.2 & 2.3 PERFORMANCE BENCHMARK")
        print("=" * 72)

        scenarios = [
            {"name": "Small (20 projects)", "projects": 20, "files_per": 5},
            {"name": "Medium (50 projects)", "projects": 50, "files_per": 10},
            {"name": "Large (150 projects)", "projects": 150, "files_per": 15},
            {"name": "Very large (300 projects)", "projects": 300, "files_per": 20},
        ]

        all_results = []
        tmp_base = Path(tempfile.mkdtemp(prefix="scatter_bench_"))

        try:
            for scenario in scenarios:
                print(f"\n--- {scenario['name']} ---")
                target_csproj, csproj_files, cs_files = self._create_test_structure(
                    tmp_base, scenario["projects"], scenario["files_per"]
                )

                csproj_result = self.benchmark_csproj_parsing(
                    csproj_files, target_csproj, scenario["name"]
                )
                all_results.append(csproj_result)

                mapping_result = self.benchmark_project_mapping(
                    cs_files, scenario["name"]
                )
                all_results.append(mapping_result)

            # Validate
            validation = {}
            for test_type, targets in self.performance_targets.items():
                type_results = [r for r in all_results if r["test_type"] == test_type]
                if type_results:
                    best = max(r["speedup_factor"] for r in type_results)
                    avg = statistics.mean(r["speedup_factor"] for r in type_results)
                    validation[test_type] = {
                        "best_speedup": best,
                        "avg_speedup": round(avg, 2),
                        "meets_minimum": best >= targets["min_speedup"],
                        "meets_target": best >= targets["target_speedup"],
                        "all_results_match": all(r["results_match"] for r in type_results),
                    }

            validation["overall_pass"] = all(
                v.get("all_results_match", False) for v in validation.values()
                if isinstance(v, dict)
            )

            # Save
            json_file = self.output_dir / f"phase22_23_benchmark_{self.timestamp}.json"
            summary = {
                "timestamp": self.timestamp,
                "phase": "2.2 & 2.3 — XML Parsing + Project Mapping",
                "validation": validation,
                "results": all_results,
                "targets": self.performance_targets,
            }
            with open(json_file, "w") as f:
                json.dump(summary, f, indent=2, default=str)

            # Print summary
            print("\n" + "=" * 72)
            print("SUMMARY")
            print("=" * 72)
            for test_type, v in validation.items():
                if not isinstance(v, dict):
                    continue
                min_ok = "PASS" if v["meets_minimum"] else "FAIL"
                tgt_ok = "PASS" if v["meets_target"] else "MISS"
                match = "PASS" if v["all_results_match"] else "FAIL"
                print(f"  {test_type:20s}  best={v['best_speedup']:.2f}x  "
                      f"avg={v['avg_speedup']:.2f}x  "
                      f"min:{min_ok}  target:{tgt_ok}  correctness:{match}")

            print(f"\n  Results saved to: {json_file}")

            overall = validation["overall_pass"]
            print(f"\n  {'ALL CORRECTNESS CHECKS PASSED' if overall else 'CORRECTNESS ISSUES DETECTED'}")
            return overall

        finally:
            shutil.rmtree(tmp_base, ignore_errors=True)


def main():
    benchmarker = Phase22_23Benchmarker()
    success = benchmarker.run_comprehensive_benchmark()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
