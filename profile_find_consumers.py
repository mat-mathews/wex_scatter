#!/usr/bin/env python3
"""
End-to-end profiling of find_consumers() pipeline.
Instruments each step to identify remaining bottlenecks.
"""

import sys
import time
import tempfile
import shutil
import logging
import re
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, str(Path(__file__).parent))
import scatter


def create_profiling_codebase(base_dir: Path, num_projects: int,
                               files_per_project: int) -> Path:
    """Create a realistic test codebase for profiling."""
    test_dir = base_dir / "profile_codebase"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    # Target library
    target_dir = test_dir / "CoreLib"
    target_dir.mkdir()
    (target_dir / "CoreLib.csproj").write_text('''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>CoreLib</RootNamespace>
  </PropertyGroup>
</Project>''')
    (target_dir / "CoreService.cs").write_text('''using System;
namespace CoreLib {
    public class CoreService {
        public void DoWork() { }
        public string GetData(int id) { return ""; }
    }
}''')

    for i in range(num_projects):
        proj_dir = test_dir / f"App{i:03d}"
        proj_dir.mkdir()

        has_ref = i % 3 != 2  # ~67% reference CoreLib
        ref_xml = '''
  <ItemGroup>
    <ProjectReference Include="..\\CoreLib\\CoreLib.csproj" />
  </ItemGroup>''' if has_ref else ''

        (proj_dir / f"App{i:03d}.csproj").write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>App{i:03d}</RootNamespace>
  </PropertyGroup>{ref_xml}
</Project>''')

        for j in range(files_per_project):
            uses_namespace = has_ref and j % 2 == 0
            uses_class = uses_namespace and j % 4 == 0
            uses_method = uses_class and j % 8 == 0

            using_line = "using CoreLib;" if uses_namespace else "using System.IO;"
            class_usage = "var svc = new CoreService();" if uses_class else "var x = 1;"
            method_usage = "svc.DoWork();" if uses_method else "Console.Write(x);"

            sub = proj_dir / ("Services" if j % 3 == 0 else "Models" if j % 3 == 1 else ".")
            sub.mkdir(exist_ok=True)
            (sub / f"File{j:03d}.cs").write_text(f'''using System;
{using_line}

namespace App{i:03d} {{
    public class File{j:03d} {{
        public void Run() {{
            {class_usage}
            {method_usage}
        }}
    }}
}}''')

    return test_dir


def profile_find_consumers(test_dir: Path, target_csproj: Path,
                            namespace: str, class_name: str,
                            method_name: str, label: str,
                            disable_mp: bool = False):
    """Run find_consumers and report timing."""
    print(f"\n  [{label}] disable_multiprocessing={disable_mp}")

    start = time.perf_counter()
    results = scatter.find_consumers(
        target_csproj_path=target_csproj,
        search_scope_path=test_dir,
        target_namespace=namespace,
        class_name=class_name,
        method_name=method_name,
        disable_multiprocessing=disable_mp,
    )
    elapsed = time.perf_counter() - start

    print(f"    Time: {elapsed:.4f}s  Consumers found: {len(results)}")
    return elapsed, len(results)


def main():
    logging.basicConfig(level=logging.WARNING)

    scenarios = [
        {"projects": 50, "files_per": 10, "label": "50 projects / 500 files"},
        {"projects": 100, "files_per": 15, "label": "100 projects / 1500 files"},
        {"projects": 200, "files_per": 20, "label": "200 projects / 4000 files"},
    ]

    print("=" * 72)
    print("find_consumers() END-TO-END PROFILING")
    print("=" * 72)

    tmp_base = Path(tempfile.mkdtemp(prefix="scatter_profile_"))

    try:
        for scenario in scenarios:
            print(f"\n--- {scenario['label']} ---")
            test_dir = create_profiling_codebase(
                tmp_base, scenario["projects"], scenario["files_per"]
            )
            target_csproj = test_dir / "CoreLib" / "CoreLib.csproj"

            # Namespace-only (steps 1-3)
            seq_t, seq_n = profile_find_consumers(
                test_dir, target_csproj, "CoreLib", None, None,
                "Namespace only — sequential", disable_mp=True
            )
            par_t, par_n = profile_find_consumers(
                test_dir, target_csproj, "CoreLib", None, None,
                "Namespace only — parallel", disable_mp=False
            )
            print(f"    Speedup: {seq_t/par_t:.2f}x  Results match: {seq_n == par_n}")

            # Class filter (steps 1-4)
            seq_t, seq_n = profile_find_consumers(
                test_dir, target_csproj, "CoreLib", "CoreService", None,
                "Class filter — sequential", disable_mp=True
            )
            par_t, par_n = profile_find_consumers(
                test_dir, target_csproj, "CoreLib", "CoreService", None,
                "Class filter — parallel", disable_mp=False
            )
            print(f"    Speedup: {seq_t/par_t:.2f}x  Results match: {seq_n == par_n}")

            # Method filter (steps 1-5)
            seq_t, seq_n = profile_find_consumers(
                test_dir, target_csproj, "CoreLib", "CoreService", "DoWork",
                "Method filter — sequential", disable_mp=True
            )
            par_t, par_n = profile_find_consumers(
                test_dir, target_csproj, "CoreLib", "CoreService", "DoWork",
                "Method filter — parallel", disable_mp=False
            )
            print(f"    Speedup: {seq_t/par_t:.2f}x  Results match: {seq_n == par_n}")

    finally:
        shutil.rmtree(tmp_base, ignore_errors=True)

    print("\n" + "=" * 72)
    print("PROFILING COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()
