#!/usr/bin/env python3
"""
Benchmarking Framework for scatter.py Performance Analysis
Measures and validates multiprocessing performance improvements across all phases.
"""

import time
import statistics
import json
import csv
import logging
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import tempfile
import shutil
import multiprocessing
import sys
import os

# Add the current directory to path for scatter imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scatter


@dataclass
class BenchmarkResult:
    """Structured result from a single benchmark run."""
    function_name: str
    test_scenario: str
    execution_time_seconds: float
    multiprocessing_enabled: bool
    max_workers: int
    chunk_size: int
    files_found: int
    directories_scanned: int
    error_occurred: bool = False
    error_message: str = ""


@dataclass
class BenchmarkComparison:
    """Comparison between sequential and parallel execution."""
    function_name: str
    test_scenario: str
    sequential_time: float
    parallel_time: float
    speedup_factor: float
    performance_improvement_percentage: float
    files_found_sequential: int
    files_found_parallel: int
    results_match: bool


class BenchmarkFramework:
    """
    Comprehensive benchmarking framework for scatter.py performance analysis.
    
    Provides utilities for:
    - Timing function execution with multiple runs
    - Comparing sequential vs parallel performance
    - Generating test data of various sizes
    - Creating detailed performance reports
    """
    
    def __init__(self, output_dir: Path = None):
        """Initialize the benchmarking framework."""
        self.output_dir = output_dir or Path("benchmark_results")
        self.output_dir.mkdir(exist_ok=True)
        self.results: List[BenchmarkResult] = []
        self.comparisons: List[BenchmarkComparison] = []
        
        # Configure logging for benchmarking
        self._setup_logging()
        
        # System information
        self.cpu_count = multiprocessing.cpu_count()
        self.default_max_workers = scatter.DEFAULT_MAX_WORKERS
        self.default_chunk_size = scatter.DEFAULT_CHUNK_SIZE
        
        logging.info(f"Benchmark Framework initialized")
        logging.info(f"System CPU cores: {self.cpu_count}")
        logging.info(f"Default max workers: {self.default_max_workers}")
        logging.info(f"Default chunk size: {self.default_chunk_size}")
        logging.info(f"Output directory: {self.output_dir}")
    
    def _setup_logging(self):
        """Configure logging for benchmark operations."""
        log_file = self.output_dir / "benchmark.log"
        
        # Create a separate logger for benchmarking to avoid interference
        self.logger = logging.getLogger('benchmark')
        self.logger.setLevel(logging.DEBUG)
        
        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def time_function(self, 
                     func: Callable, 
                     args: tuple = (), 
                     kwargs: dict = None,
                     runs: int = 3) -> Tuple[float, Any, bool, str]:
        """
        Time a function execution with multiple runs and return statistics.
        
        Args:
            func: Function to benchmark
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            runs: Number of runs to average
            
        Returns:
            Tuple of (average_time, result, error_occurred, error_message)
        """
        if kwargs is None:
            kwargs = {}
            
        times = []
        result = None
        error_occurred = False
        error_message = ""
        
        for run in range(runs):
            try:
                start_time = time.perf_counter()
                result = func(*args, **kwargs)
                end_time = time.perf_counter()
                execution_time = end_time - start_time
                times.append(execution_time)
                
                self.logger.debug(f"Run {run + 1}/{runs}: {execution_time:.4f}s")
                
            except Exception as e:
                error_occurred = True
                error_message = str(e)
                self.logger.error(f"Error in run {run + 1}: {e}")
                break
        
        if times:
            avg_time = statistics.mean(times)
            if len(times) > 1:
                std_dev = statistics.stdev(times)
                self.logger.debug(f"Average time: {avg_time:.4f}s ± {std_dev:.4f}s")
            else:
                self.logger.debug(f"Single run time: {avg_time:.4f}s")
        else:
            avg_time = 0.0
            
        return avg_time, result, error_occurred, error_message
    
    def benchmark_file_discovery(self,
                                search_path: Path,
                                pattern: str,
                                test_scenario: str,
                                max_workers: int = None,
                                chunk_size: int = None,
                                runs: int = 3) -> BenchmarkComparison:
        """
        Benchmark find_files_with_pattern_parallel() in both sequential and parallel modes.
        
        Args:
            search_path: Directory to search
            pattern: File pattern to match
            test_scenario: Description of the test scenario
            max_workers: Number of workers for parallel execution
            chunk_size: Chunk size for parallel execution
            runs: Number of runs to average
            
        Returns:
            BenchmarkComparison object with performance comparison
        """
        if max_workers is None:
            max_workers = self.default_max_workers
        if chunk_size is None:
            chunk_size = self.default_chunk_size
            
        self.logger.info(f"Benchmarking file discovery: {test_scenario}")
        self.logger.info(f"Search path: {search_path}")
        self.logger.info(f"Pattern: {pattern}")
        
        # Benchmark sequential execution
        self.logger.info("Running sequential benchmark...")
        seq_time, seq_result, seq_error, seq_error_msg = self.time_function(
            scatter.find_files_with_pattern_parallel,
            args=(search_path, pattern),
            kwargs={
                'max_workers': max_workers,
                'chunk_size': chunk_size,
                'disable_multiprocessing': True
            },
            runs=runs
        )
        
        # Record sequential result
        seq_benchmark = BenchmarkResult(
            function_name="find_files_with_pattern_parallel",
            test_scenario=test_scenario,
            execution_time_seconds=seq_time,
            multiprocessing_enabled=False,
            max_workers=max_workers,
            chunk_size=chunk_size,
            files_found=len(seq_result) if seq_result else 0,
            directories_scanned=0,  # TODO: Add directory counting
            error_occurred=seq_error,
            error_message=seq_error_msg
        )
        self.results.append(seq_benchmark)
        
        # Benchmark parallel execution
        self.logger.info("Running parallel benchmark...")
        par_time, par_result, par_error, par_error_msg = self.time_function(
            scatter.find_files_with_pattern_parallel,
            args=(search_path, pattern),
            kwargs={
                'max_workers': max_workers,
                'chunk_size': chunk_size,
                'disable_multiprocessing': False
            },
            runs=runs
        )
        
        # Record parallel result
        par_benchmark = BenchmarkResult(
            function_name="find_files_with_pattern_parallel",
            test_scenario=test_scenario,
            execution_time_seconds=par_time,
            multiprocessing_enabled=True,
            max_workers=max_workers,
            chunk_size=chunk_size,
            files_found=len(par_result) if par_result else 0,
            directories_scanned=0,  # TODO: Add directory counting
            error_occurred=par_error,
            error_message=par_error_msg
        )
        self.results.append(par_benchmark)
        
        # Calculate comparison
        if seq_time > 0 and not seq_error and not par_error:
            speedup = seq_time / par_time if par_time > 0 else 0
            improvement_pct = ((seq_time - par_time) / seq_time) * 100 if seq_time > 0 else 0
        else:
            speedup = 0
            improvement_pct = 0
            
        results_match = (seq_result == par_result) if (seq_result and par_result) else False
        
        comparison = BenchmarkComparison(
            function_name="find_files_with_pattern_parallel",
            test_scenario=test_scenario,
            sequential_time=seq_time,
            parallel_time=par_time,
            speedup_factor=speedup,
            performance_improvement_percentage=improvement_pct,
            files_found_sequential=len(seq_result) if seq_result else 0,
            files_found_parallel=len(par_result) if par_result else 0,
            results_match=results_match
        )
        
        self.comparisons.append(comparison)
        
        self.logger.info(f"Benchmark complete:")
        self.logger.info(f"  Sequential: {seq_time:.4f}s ({len(seq_result) if seq_result else 0} files)")
        self.logger.info(f"  Parallel:   {par_time:.4f}s ({len(par_result) if par_result else 0} files)")
        self.logger.info(f"  Speedup:    {speedup:.2f}x ({improvement_pct:.1f}% improvement)")
        self.logger.info(f"  Results match: {results_match}")
        
        return comparison
    
    def generate_test_directory_structure(self, 
                                        base_path: Path,
                                        num_projects: int = 10,
                                        files_per_project: int = 5,
                                        nested_levels: int = 2) -> Path:
        """
        Generate a test directory structure with mock .NET projects.
        
        Args:
            base_path: Base directory for test structure
            num_projects: Number of mock projects to create
            files_per_project: Number of .cs files per project
            nested_levels: Depth of nested directories
            
        Returns:
            Path to the created test structure
        """
        test_dir = base_path / f"test_codebase_{num_projects}proj_{files_per_project}files"
        
        if test_dir.exists():
            shutil.rmtree(test_dir)
        test_dir.mkdir(parents=True)
        
        self.logger.info(f"Generating test directory: {test_dir}")
        self.logger.info(f"Projects: {num_projects}, Files per project: {files_per_project}, Nested levels: {nested_levels}")
        
        for proj_idx in range(num_projects):
            proj_dir = test_dir / f"TestProject{proj_idx:03d}"
            proj_dir.mkdir()
            
            # Create .csproj file
            csproj_content = f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <RootNamespace>TestProject{proj_idx:03d}</RootNamespace>
  </PropertyGroup>
</Project>'''
            
            (proj_dir / f"TestProject{proj_idx:03d}.csproj").write_text(csproj_content)
            
            # Create nested directory structure
            current_dir = proj_dir
            for level in range(nested_levels):
                current_dir = current_dir / f"Level{level}"
                current_dir.mkdir()
                
                # Create .cs files at each level
                files_at_level = files_per_project // (nested_levels + 1)
                if level == 0:  # Put remaining files in first level
                    files_at_level += files_per_project % (nested_levels + 1)
                    
                for file_idx in range(files_at_level):
                    cs_content = f'''using System;

namespace TestProject{proj_idx:03d}.Level{level}
{{
    public class Class{file_idx:03d}
    {{
        public void Method{file_idx:03d}()
        {{
            Console.WriteLine("Test method {file_idx}");
        }}
    }}
}}'''
                    (current_dir / f"Class{file_idx:03d}.cs").write_text(cs_content)
        
        # Count created files for verification
        csproj_count = len(list(test_dir.rglob("*.csproj")))
        cs_count = len(list(test_dir.rglob("*.cs")))
        dir_count = len([d for d in test_dir.rglob("*") if d.is_dir()])
        
        self.logger.info(f"Test structure created:")
        self.logger.info(f"  .csproj files: {csproj_count}")
        self.logger.info(f"  .cs files: {cs_count}")
        self.logger.info(f"  Directories: {dir_count}")
        
        return test_dir
    
    def save_results(self, filename_prefix: str = "benchmark"):
        """Save benchmark results to JSON and CSV files."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # Save detailed results as JSON
        json_file = self.output_dir / f"{filename_prefix}_results_{timestamp}.json"
        json_data = {
            "system_info": {
                "cpu_count": self.cpu_count,
                "default_max_workers": self.default_max_workers,
                "default_chunk_size": self.default_chunk_size
            },
            "benchmark_results": [asdict(result) for result in self.results],
            "comparisons": [asdict(comparison) for comparison in self.comparisons]
        }
        
        with open(json_file, 'w') as f:
            json.dump(json_data, f, indent=2)
        
        self.logger.info(f"Detailed results saved to: {json_file}")
        
        # Save comparisons as CSV
        csv_file = self.output_dir / f"{filename_prefix}_comparisons_{timestamp}.csv"
        with open(csv_file, 'w', newline='') as f:
            if self.comparisons:
                writer = csv.DictWriter(f, fieldnames=asdict(self.comparisons[0]).keys())
                writer.writeheader()
                for comparison in self.comparisons:
                    writer.writerow(asdict(comparison))
        
        self.logger.info(f"Comparison summary saved to: {csv_file}")
        
        return json_file, csv_file
    
    def print_summary_report(self):
        """Print a summary of benchmark results to console."""
        print("\n" + "="*80)
        print("BENCHMARK SUMMARY REPORT")
        print("="*80)
        
        if not self.comparisons:
            print("No benchmark comparisons available.")
            return
        
        print(f"System Info: {self.cpu_count} CPU cores, {self.default_max_workers} default workers")
        print(f"Total benchmarks: {len(self.comparisons)}")
        print()
        
        # Calculate overall statistics
        speedups = [c.speedup_factor for c in self.comparisons if c.speedup_factor > 0]
        improvements = [c.performance_improvement_percentage for c in self.comparisons if c.speedup_factor > 0]
        
        if speedups:
            avg_speedup = statistics.mean(speedups)
            max_speedup = max(speedups)
            min_speedup = min(speedups)
            avg_improvement = statistics.mean(improvements)
            
            print(f"PERFORMANCE SUMMARY:")
            print(f"  Average speedup: {avg_speedup:.2f}x")
            print(f"  Best speedup: {max_speedup:.2f}x")
            print(f"  Worst speedup: {min_speedup:.2f}x")
            print(f"  Average improvement: {avg_improvement:.1f}%")
            print()
        
        # Detailed results
        print("DETAILED RESULTS:")
        print("-" * 80)
        print(f"{'Test Scenario':<30} {'Sequential':<12} {'Parallel':<12} {'Speedup':<10} {'Improvement':<12} {'Match':<8}")
        print("-" * 80)
        
        for comp in self.comparisons:
            match_status = "✓" if comp.results_match else "✗"
            print(f"{comp.test_scenario[:29]:<30} "
                  f"{comp.sequential_time:<12.4f} "
                  f"{comp.parallel_time:<12.4f} "
                  f"{comp.speedup_factor:<10.2f} "
                  f"{comp.performance_improvement_percentage:<12.1f}% "
                  f"{match_status:<8}")
        
        print("="*80)


if __name__ == "__main__":
    # Example usage
    framework = BenchmarkFramework()
    
    # Test with the existing mock projects
    current_dir = Path(__file__).parent
    
    # Benchmark existing mock projects
    comparison = framework.benchmark_file_discovery(
        search_path=current_dir,
        pattern="*.csproj",
        test_scenario="Mock Projects - .csproj files"
    )
    
    # Generate and benchmark a larger test set
    test_structure = framework.generate_test_directory_structure(
        base_path=current_dir / "temp_test_data",
        num_projects=20,
        files_per_project=10
    )
    
    framework.benchmark_file_discovery(
        search_path=test_structure,
        pattern="*.cs", 
        test_scenario="Generated Test - 20 projects"
    )
    
    # Test with larger generated structure to verify parallel benefits
    large_test_structure = framework.generate_test_directory_structure(
        base_path=current_dir / "temp_test_data",
        num_projects=100,
        files_per_project=20,
        nested_levels=3
    )
    
    framework.benchmark_file_discovery(
        search_path=large_test_structure,
        pattern="*.cs",
        test_scenario="Large Test - 100 projects, 2000 files"
    )
    
    # Save results and print summary
    framework.save_results("phase1_file_discovery")
    framework.print_summary_report()