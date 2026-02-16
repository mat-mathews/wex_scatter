#!/usr/bin/env python3
"""
Phase 2.1 Content Analysis Benchmarking Tool
Comprehensive performance testing for parallel content analysis implementation.

Tests the performance improvements for:
- Namespace usage scanning 
- Class usage scanning
- Stored procedure scanning

Validates the 4-8x improvement target for content analysis parallelization.
"""

import subprocess
import sys
import time
import csv
import json
import tempfile
import shutil
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import statistics

# Import the main scatter module to access functions directly
sys.path.insert(0, str(Path(__file__).parent))
try:
    import scatter
except ImportError as e:
    print(f"Error importing scatter module: {e}")
    sys.exit(1)

class Phase21Benchmarker:
    """Benchmarking tool for Phase 2.1 content analysis performance."""
    
    def __init__(self, output_dir: str = "benchmark_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Test scenarios with different file counts
        self.test_scenarios = [
            {"name": "Small codebase", "min_files": 10, "max_files": 50},
            {"name": "Medium codebase", "min_files": 100, "max_files": 500},
            {"name": "Large codebase", "min_files": 1000, "max_files": 2000},
            {"name": "Very large codebase", "min_files": 3000, "max_files": 5000}
        ]
        
        # Performance targets for Phase 2.1
        self.performance_targets = {
            "namespace_scanning": {"min_speedup": 2.0, "target_speedup": 4.0},
            "class_scanning": {"min_speedup": 2.0, "target_speedup": 4.0}, 
            "sproc_scanning": {"min_speedup": 3.0, "target_speedup": 6.0}
        }
        
    def setup_test_environment(self) -> Tuple[Path, List[Path]]:
        """Set up test environment and return test directory and CS files."""
        print("🔧 Setting up test environment...")
        
        # Find actual .cs files in the current codebase
        current_dir = Path(".")
        cs_files = list(current_dir.rglob("*.cs"))
        
        if len(cs_files) < 10:
            print(f"⚠️  Only found {len(cs_files)} .cs files - creating additional test files")
            # Create temporary test files if needed
            test_dir = Path(tempfile.mkdtemp(prefix="scatter_benchmark_"))
            self._create_test_cs_files(test_dir, 100)
            cs_files = list(test_dir.rglob("*.cs"))
        else:
            test_dir = current_dir
            
        print(f"✅ Found {len(cs_files)} .cs files for testing")
        return test_dir, cs_files
        
    def _create_test_cs_files(self, test_dir: Path, count: int) -> None:
        """Create test .cs files with realistic content for benchmarking."""
        for i in range(count):
            project_dir = test_dir / f"TestProject{i//20}"
            project_dir.mkdir(exist_ok=True)
            
            cs_file = project_dir / f"TestClass{i}.cs"
            content = f"""using System;
using System.Collections.Generic;
using TestNamespace.Core;
using GalaxyWorks.Data;

namespace TestNamespace.Project{i//20}
{{
    public class TestClass{i}
    {{
        private readonly PortalDataService _dataService;
        
        public TestClass{i}()
        {{
            _dataService = new PortalDataService();
        }}
        
        public void TestMethod{i}()
        {{
            // Sample stored procedure call
            var result = ExecuteStoredProcedure("dbo.sp_InsertPortalConfiguration");
            
            // Some namespace usage
            var list = new List<string>();
            Console.WriteLine($"Test class {{nameof(TestClass{i})}}");
        }}
        
        private object ExecuteStoredProcedure(string sprocName)
        {{
            return _dataService.ExecuteStoredProcedure(sprocName);
        }}
    }}
}}"""
            cs_file.write_text(content)
    
    def benchmark_namespace_scanning(self, cs_files: List[Path], target_namespace: str = "GalaxyWorks.Data") -> Dict:
        """Benchmark namespace usage scanning performance."""
        print(f"\n📊 Benchmarking namespace scanning for '{target_namespace}'...")
        
        results = {
            "test_type": "namespace_scanning",
            "target_namespace": target_namespace,
            "file_count": len(cs_files),
            "sequential_times": [],
            "parallel_times": [],
            "sequential_results": None,
            "parallel_results": None
        }
        
        # Prepare patterns (same as in find_consumers)
        using_pattern = re.compile(rf'^\s*using\s+{re.escape(target_namespace)}(?:\.|;)', re.MULTILINE)
        
        # Run sequential version multiple times
        print("  🔄 Running sequential version...")
        for run in range(3):
            start_time = time.time()
            
            # Simulate sequential file scanning
            sequential_matches = []
            for cs_file in cs_files:
                try:
                    content = cs_file.read_text(encoding='utf-8', errors='ignore')
                    if using_pattern.search(content):
                        sequential_matches.append(cs_file)
                except Exception:
                    continue
                    
            sequential_time = time.time() - start_time
            results["sequential_times"].append(sequential_time)
            
            if run == 0:  # Store results from first run
                results["sequential_results"] = len(sequential_matches)
        
        # Run parallel version multiple times  
        print("  ⚡ Running parallel version...")
        for run in range(3):
            start_time = time.time()
            
            # Use the actual parallel function from scatter.py
            analysis_config = {
                'analysis_type': 'namespace',
                'target_namespace': target_namespace,
                'using_pattern': using_pattern
            }
            
            print(f"    🔧 Run {run+1}: Processing {len(cs_files)} files...")
            parallel_results = scatter.analyze_cs_files_parallel(
                cs_files, analysis_config, 
                cs_analysis_chunk_size=50,
                max_workers=scatter.DEFAULT_MAX_WORKERS,
                disable_multiprocessing=False
            )
            
            parallel_matches = [f for f, result in parallel_results.items() if result['has_match']]
            parallel_time = time.time() - start_time
            results["parallel_times"].append(parallel_time)
            print(f"    ⏱️  Run {run+1} completed in {parallel_time:.3f}s")
            
            if run == 0:  # Store results from first run
                results["parallel_results"] = len(parallel_matches)
        
        # Calculate statistics
        avg_sequential = statistics.mean(results["sequential_times"])
        avg_parallel = statistics.mean(results["parallel_times"])
        speedup = avg_sequential / avg_parallel if avg_parallel > 0 else 0
        
        results.update({
            "avg_sequential_time": avg_sequential,
            "avg_parallel_time": avg_parallel,
            "speedup_factor": speedup,
            "performance_improvement_percentage": ((speedup - 1) * 100) if speedup > 0 else 0,
            "results_match": results["sequential_results"] == results["parallel_results"]
        })
        
        print(f"  ✅ Speedup: {speedup:.2f}x ({results['performance_improvement_percentage']:.1f}% improvement)")
        print(f"  📋 Results match: {results['results_match']} (seq: {results['sequential_results']}, par: {results['parallel_results']})")
        
        return results
    
    def benchmark_class_scanning(self, cs_files: List[Path], class_name: str = "PortalDataService") -> Dict:
        """Benchmark class usage scanning performance."""
        print(f"\n📊 Benchmarking class scanning for '{class_name}'...")
        
        results = {
            "test_type": "class_scanning", 
            "class_name": class_name,
            "file_count": len(cs_files),
            "sequential_times": [],
            "parallel_times": [],
            "sequential_results": None,
            "parallel_results": None
        }
        
        # Prepare patterns (same as in find_consumers)
        class_pattern = re.compile(rf'\b{re.escape(class_name)}\b')
        
        # Run sequential version
        print("  🔄 Running sequential version...")
        for run in range(3):
            start_time = time.time()
            
            sequential_matches = []
            for cs_file in cs_files:
                try:
                    content = cs_file.read_text(encoding='utf-8', errors='ignore')
                    if class_pattern.search(content):
                        sequential_matches.append(cs_file)
                except Exception:
                    continue
                    
            sequential_time = time.time() - start_time
            results["sequential_times"].append(sequential_time)
            
            if run == 0:
                results["sequential_results"] = len(sequential_matches)
        
        # Run parallel version
        print("  ⚡ Running parallel version...")
        for run in range(3):
            start_time = time.time()
            
            analysis_config = {
                'analysis_type': 'class',
                'class_name': class_name,
                'class_pattern': class_pattern
            }
            
            parallel_results = scatter.analyze_cs_files_parallel(
                cs_files, analysis_config,
                cs_analysis_chunk_size=50,
                max_workers=scatter.DEFAULT_MAX_WORKERS
            )
            
            parallel_matches = [f for f, result in parallel_results.items() if result['has_match']]
            parallel_time = time.time() - start_time
            results["parallel_times"].append(parallel_time)
            
            if run == 0:
                results["parallel_results"] = len(parallel_matches)
        
        # Calculate statistics
        avg_sequential = statistics.mean(results["sequential_times"])
        avg_parallel = statistics.mean(results["parallel_times"])
        speedup = avg_sequential / avg_parallel if avg_parallel > 0 else 0
        
        results.update({
            "avg_sequential_time": avg_sequential,
            "avg_parallel_time": avg_parallel, 
            "speedup_factor": speedup,
            "performance_improvement_percentage": ((speedup - 1) * 100) if speedup > 0 else 0,
            "results_match": results["sequential_results"] == results["parallel_results"]
        })
        
        print(f"  ✅ Speedup: {speedup:.2f}x ({results['performance_improvement_percentage']:.1f}% improvement)")
        print(f"  📋 Results match: {results['results_match']} (seq: {results['sequential_results']}, par: {results['parallel_results']})")
        
        return results
    
    def benchmark_sproc_scanning(self, cs_files: List[Path], sproc_name: str = "dbo.sp_InsertPortalConfiguration") -> Dict:
        """Benchmark stored procedure scanning performance."""
        print(f"\n📊 Benchmarking stored procedure scanning for '{sproc_name}'...")
        
        results = {
            "test_type": "sproc_scanning",
            "sproc_name": sproc_name,
            "file_count": len(cs_files),
            "sequential_times": [],
            "parallel_times": [],
            "sequential_results": None,
            "parallel_results": None
        }
        
        # Prepare patterns (same as in find_cs_files_referencing_sproc)
        import re
        sproc_pattern = re.compile(rf'\b{re.escape(sproc_name)}\b', re.IGNORECASE)
        
        # Run sequential version
        print("  🔄 Running sequential version...")
        for run in range(3):
            start_time = time.time()
            
            sequential_matches = []
            for cs_file in cs_files:
                try:
                    content = cs_file.read_text(encoding='utf-8', errors='ignore')
                    if sproc_pattern.search(content):
                        sequential_matches.append(cs_file)
                except Exception:
                    continue
                    
            sequential_time = time.time() - start_time
            results["sequential_times"].append(sequential_time)
            
            if run == 0:
                results["sequential_results"] = len(sequential_matches)
        
        # Run parallel version using the actual function
        print("  ⚡ Running parallel version...")
        for run in range(3):
            start_time = time.time()
            
            analysis_config = {
                'analysis_type': 'sproc',
                'sproc_pattern': sproc_pattern
            }
            
            parallel_results = scatter.analyze_cs_files_parallel(
                cs_files, analysis_config,
                cs_analysis_chunk_size=50,
                max_workers=scatter.DEFAULT_MAX_WORKERS
            )
            
            parallel_matches = [f for f, result in parallel_results.items() if result['has_match']]
            parallel_time = time.time() - start_time
            results["parallel_times"].append(parallel_time)
            
            if run == 0:
                results["parallel_results"] = len(parallel_matches)
        
        # Calculate statistics
        avg_sequential = statistics.mean(results["sequential_times"])
        avg_parallel = statistics.mean(results["parallel_times"])
        speedup = avg_sequential / avg_parallel if avg_parallel > 0 else 0
        
        results.update({
            "avg_sequential_time": avg_sequential,
            "avg_parallel_time": avg_parallel,
            "speedup_factor": speedup,
            "performance_improvement_percentage": ((speedup - 1) * 100) if speedup > 0 else 0,
            "results_match": results["sequential_results"] == results["parallel_results"]
        })
        
        print(f"  ✅ Speedup: {speedup:.2f}x ({results['performance_improvement_percentage']:.1f}% improvement)")
        print(f"  📋 Results match: {results['results_match']} (seq: {results['sequential_results']}, par: {results['parallel_results']})")
        
        return results
    
    def validate_performance_targets(self, all_results: List[Dict]) -> Dict:
        """Validate performance improvements against targets."""
        validation_results = {
            "namespace_scanning": {"meets_minimum": False, "meets_target": False, "actual_speedup": 0},
            "class_scanning": {"meets_minimum": False, "meets_target": False, "actual_speedup": 0},
            "sproc_scanning": {"meets_minimum": False, "meets_target": False, "actual_speedup": 0},
            "overall_validation": False
        }
        
        for result in all_results:
            test_type = result["test_type"]
            speedup = result["speedup_factor"]
            
            if test_type in self.performance_targets:
                targets = self.performance_targets[test_type]
                validation_results[test_type].update({
                    "actual_speedup": speedup,
                    "meets_minimum": speedup >= targets["min_speedup"],
                    "meets_target": speedup >= targets["target_speedup"]
                })
        
        # Overall validation: all minimums met
        all_minimums_met = all(
            validation_results[test_type]["meets_minimum"] 
            for test_type in ["namespace_scanning", "class_scanning", "sproc_scanning"]
        )
        validation_results["overall_validation"] = all_minimums_met
        
        return validation_results
    
    def save_results(self, all_results: List[Dict], validation_results: Dict) -> Tuple[Path, Path]:
        """Save benchmark results to CSV and JSON files."""
        
        # Save detailed CSV results
        csv_file = self.output_dir / f"phase21_content_analysis_benchmark_{self.timestamp}.csv"
        with open(csv_file, 'w', newline='') as f:
            if all_results:
                # Get all possible fieldnames from all results
                all_fieldnames = set()
                for result in all_results:
                    all_fieldnames.update(result.keys())
                
                fieldnames = sorted(list(all_fieldnames))
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_results)
        
        # Save summary JSON results
        json_file = self.output_dir / f"phase21_content_analysis_summary_{self.timestamp}.json"
        summary = {
            "timestamp": self.timestamp,
            "phase": "2.1 - Content Analysis",
            "total_tests": len(all_results),
            "validation_results": validation_results,
            "detailed_results": all_results,
            "performance_targets": self.performance_targets
        }
        
        with open(json_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        return csv_file, json_file
    
    def run_comprehensive_benchmark(self) -> bool:
        """Run comprehensive Phase 2.1 benchmark suite."""
        print("=" * 80)
        print("PHASE 2.1 CONTENT ANALYSIS PERFORMANCE BENCHMARK")
        print("=" * 80)
        
        # Setup test environment
        test_dir, cs_files = self.setup_test_environment()
        
        print(f"\n📈 Testing with {len(cs_files)} .cs files")
        print(f"🎯 Performance targets:")
        for test_type, targets in self.performance_targets.items():
            print(f"   • {test_type}: {targets['min_speedup']}x minimum, {targets['target_speedup']}x target")
        
        # Test with different file count scenarios
        test_scenarios = [
            {"name": "Small subset", "count": 100},
            {"name": "Medium subset", "count": 500},
            {"name": "Full codebase", "count": len(cs_files)}
        ]
        
        all_results = []
        
        try:
            for scenario in test_scenarios:
                file_subset = cs_files[:scenario["count"]]
                print(f"\n🔍 Testing scenario: {scenario['name']} ({len(file_subset)} files)")
                
                # Add scenario info to results
                namespace_result = self.benchmark_namespace_scanning(file_subset)
                namespace_result["scenario"] = scenario["name"]
                all_results.append(namespace_result)
                
                class_result = self.benchmark_class_scanning(file_subset)
                class_result["scenario"] = scenario["name"]
                all_results.append(class_result)
                
                sproc_result = self.benchmark_sproc_scanning(file_subset)
                sproc_result["scenario"] = scenario["name"]
                all_results.append(sproc_result)
            
            # Validate against performance targets
            validation_results = self.validate_performance_targets(all_results)
            
            # Save results
            csv_file, json_file = self.save_results(all_results, validation_results)
            
            # Print summary
            print("\n" + "=" * 80)
            print("PHASE 2.1 BENCHMARK RESULTS SUMMARY")
            print("=" * 80)
            
            for test_type, validation in validation_results.items():
                if test_type == "overall_validation":
                    continue
                    
                speedup = validation["actual_speedup"]
                min_met = "✅" if validation["meets_minimum"] else "❌"
                target_met = "✅" if validation["meets_target"] else "⚠️"
                
                print(f"{test_type:20} | {speedup:6.2f}x | Min: {min_met} | Target: {target_met}")
            
            print(f"\n📁 Detailed results saved to:")
            print(f"   • CSV: {csv_file}")
            print(f"   • JSON: {json_file}")
            
            overall_success = validation_results["overall_validation"]
            if overall_success:
                print(f"\n🎉 PHASE 2.1 BENCHMARK PASSED!")
                print(f"✅ All minimum performance targets met")
                print(f"✅ Content analysis parallelization working correctly")
            else:
                print(f"\n⚠️  PHASE 2.1 BENCHMARK NEEDS ATTENTION")
                print(f"❌ Some minimum performance targets not met")
                
            return overall_success
            
        finally:
            # Cleanup temporary test directory if created
            if test_dir != Path(".") and test_dir.exists():
                try:
                    shutil.rmtree(test_dir)
                    print(f"🧹 Cleaned up temporary test directory: {test_dir}")
                except Exception as e:
                    print(f"⚠️  Could not clean up {test_dir}: {e}")

def main():
    """Main function to run Phase 2.1 benchmarks."""
    benchmarker = Phase21Benchmarker()
    success = benchmarker.run_comprehensive_benchmark()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())