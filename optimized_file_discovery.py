#!/usr/bin/env python3
"""
Optimized file discovery implementation for scatter.py
Fixes the performance issues identified in Phase 1 benchmarking.
"""

import logging
import time
from pathlib import Path
from typing import List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# Import scatter for constants and utilities
import scatter

def estimate_file_count(search_path: Path, pattern: str, sample_dirs: int = 5) -> int:
    """
    Estimate total file count by sampling a few directories.
    
    Args:
        search_path: Root directory to search
        pattern: File pattern to match
        sample_dirs: Number of directories to sample for estimation
        
    Returns:
        Estimated total file count
    """
    try:
        # Get first few directories for sampling
        dirs_to_sample = []
        dirs_to_sample.append(search_path)
        
        # Add a few subdirectories for sampling
        for subdir in search_path.rglob('*'):
            if subdir.is_dir() and len(dirs_to_sample) < sample_dirs:
                dirs_to_sample.append(subdir)
            if len(dirs_to_sample) >= sample_dirs:
                break
        
        # Count files in sample directories
        total_files_sampled = 0
        total_dirs_sampled = len(dirs_to_sample)
        
        for sample_dir in dirs_to_sample:
            files_in_dir = len(list(sample_dir.glob(pattern)))
            total_files_sampled += files_in_dir
        
        if total_dirs_sampled == 0:
            return 0
            
        # Estimate total directories (rough approximation)
        # This is much faster than enumerating all directories
        if total_dirs_sampled >= sample_dirs:
            # Estimate based on depth and breadth observed
            avg_files_per_dir = total_files_sampled / total_dirs_sampled
            estimated_total_dirs = max(total_dirs_sampled * 2, 10)  # Conservative estimate
            estimated_files = int(avg_files_per_dir * estimated_total_dirs)
        else:
            # Small directory structure, likely accurate count
            estimated_files = total_files_sampled
            
        logging.debug(f"File estimation: {total_files_sampled} files in {total_dirs_sampled} sampled dirs, "
                     f"estimated total: {estimated_files}")
        
        return estimated_files
        
    except Exception as e:
        logging.debug(f"File estimation failed: {e}, defaulting to 0")
        return 0


def find_files_with_pattern_optimized(search_path: Path, 
                                    pattern: str, 
                                    max_workers: int = None,
                                    chunk_size: int = None, 
                                    disable_multiprocessing: bool = False,
                                    parallel_threshold: int = 50) -> List[Path]:
    """
    Optimized parallel file discovery with intelligent threshold detection.
    
    Key improvements:
    1. Uses file count estimation instead of directory enumeration
    2. Adaptive worker scaling based on estimated work
    3. Avoids unnecessary overhead for small file counts
    4. Falls back gracefully to sequential for small tasks
    
    Args:
        search_path: Directory to search
        pattern: File pattern to match  
        max_workers: Maximum number of workers (auto-scaled if None)
        chunk_size: Directories per worker chunk
        disable_multiprocessing: Force sequential processing
        parallel_threshold: Minimum estimated files to use parallel processing
        
    Returns:
        List of matching file paths
    """
    # Set defaults
    if max_workers is None:
        max_workers = scatter.DEFAULT_MAX_WORKERS
    if chunk_size is None:
        chunk_size = scatter.DEFAULT_CHUNK_SIZE
    
    # Force sequential if disabled
    if disable_multiprocessing or not scatter.MULTIPROCESSING_ENABLED:
        logging.debug(f"Using sequential file discovery for pattern '{pattern}' (disabled)")
        return list(search_path.rglob(pattern))
    
    # Estimate file count efficiently 
    estimated_files = estimate_file_count(search_path, pattern)
    
    # Use sequential for small file counts (avoid overhead)
    if estimated_files < parallel_threshold:
        logging.debug(f"Using sequential file discovery for pattern '{pattern}' - "
                     f"estimated {estimated_files} files < {parallel_threshold} threshold")
        return list(search_path.rglob(pattern))
    
    # For larger file counts, use intelligent parallel processing
    logging.debug(f"Using parallel file discovery for pattern '{pattern}' - "
                 f"estimated {estimated_files} files >= {parallel_threshold} threshold")
    
    try:
        # NOW enumerate directories (only when we know we'll use parallel)
        all_dirs = [search_path] + [d for d in search_path.rglob('*') if d.is_dir()]
        
        # Adaptive worker scaling based on work size
        if estimated_files < 200:
            # Small-medium: Use fewer workers to reduce overhead
            scaled_workers = min(max_workers, 4)
        elif estimated_files < 1000:
            # Medium: Use moderate worker count
            scaled_workers = min(max_workers, 8)
        else:
            # Large: Use full worker count
            scaled_workers = max_workers
            
        logging.debug(f"Parallel processing: {len(all_dirs)} directories, "
                     f"{scaled_workers} workers, {estimated_files} estimated files")
        
        # Chunk the directories
        dir_chunks = scatter.chunk_list(all_dirs, chunk_size)
        all_results = []
        completed_chunks = 0
        
        with ProcessPoolExecutor(max_workers=scaled_workers) as executor:
            # Submit all chunks
            future_to_chunk = {
                executor.submit(scatter.find_files_with_pattern_chunk, (search_path, pattern, chunk)): chunk 
                for chunk in dir_chunks
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_chunk):
                try:
                    chunk_results = future.result(timeout=300)
                    all_results.extend(chunk_results)
                    completed_chunks += 1
                    
                    # Progress reporting every 10 chunks or at completion
                    if completed_chunks % 10 == 0 or completed_chunks == len(dir_chunks):
                        logging.debug(f"File discovery progress: {completed_chunks}/{len(dir_chunks)} chunks completed")
                        
                except Exception as e:
                    logging.warning(f"Error processing directory chunk: {e}")
                    completed_chunks += 1
        
        # Remove duplicates while preserving order
        seen = set()
        unique_results = []
        for path in all_results:
            if path not in seen:
                seen.add(path)
                unique_results.append(path)
        
        logging.debug(f"Parallel file discovery completed: found {len(unique_results)} unique files matching '{pattern}'")
        return unique_results
        
    except Exception as e:
        logging.warning(f"Parallel file discovery failed: {e}. Falling back to sequential.")
        return list(search_path.rglob(pattern))


def benchmark_optimized_vs_original():
    """Compare optimized implementation against the original."""
    
    print("="*80)
    print("OPTIMIZED VS ORIGINAL IMPLEMENTATION BENCHMARK")  
    print("="*80)
    
    current_dir = Path(".")
    
    # Test scenarios
    scenarios = [
        ("*.csproj", "C# Project Files"),
        ("*.cs", "C# Source Files"),
        ("*.py", "Python Files")
    ]
    
    for pattern, description in scenarios:
        print(f"\n{description} ({pattern}):")
        print("-" * 40)
        
        # Time original implementation 
        start_time = time.perf_counter()
        original_results = scatter.find_files_with_pattern_parallel(
            current_dir, pattern, disable_multiprocessing=False
        )
        original_time = time.perf_counter() - start_time
        
        # Time optimized implementation
        start_time = time.perf_counter()  
        optimized_results = find_files_with_pattern_optimized(
            current_dir, pattern, disable_multiprocessing=False
        )
        optimized_time = time.perf_counter() - start_time
        
        # Time sequential for baseline
        start_time = time.perf_counter()
        sequential_results = list(current_dir.rglob(pattern))
        sequential_time = time.perf_counter() - start_time
        
        # Results
        files_found = len(sequential_results)
        original_speedup = sequential_time / original_time if original_time > 0 else 0
        optimized_speedup = sequential_time / optimized_time if optimized_time > 0 else 0
        
        print(f"Files found: {files_found}")
        print(f"Sequential:  {sequential_time:.4f}s")
        print(f"Original:    {original_time:.4f}s ({original_speedup:.2f}x)")
        print(f"Optimized:   {optimized_time:.4f}s ({optimized_speedup:.2f}x)")
        
        # Verify results match
        results_match = set(original_results) == set(optimized_results) == set(sequential_results)
        print(f"Results match: {results_match}")
        
        if optimized_time < original_time:
            improvement = ((original_time - optimized_time) / original_time) * 100
            print(f"✅ Optimization improved by {improvement:.1f}%")
        else:
            degradation = ((optimized_time - original_time) / original_time) * 100
            print(f"⚠️  Optimization degraded by {degradation:.1f}%")


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.DEBUG)
    
    benchmark_optimized_vs_original()