#!/usr/bin/env python3
"""
Quick test to understand Phase 2.1 overhead issues.
"""

import sys
import time
import re
from pathlib import Path

# Add scatter to path
sys.path.insert(0, str(Path(__file__).parent))
import scatter

def main():
    print("Testing Phase 2.1 parallel overhead...")
    
    # Find .cs files
    current_dir = Path(".")
    cs_files = list(current_dir.rglob("*.cs"))
    
    print(f"Found {len(cs_files)} .cs files")
    
    # Test with different file counts
    test_counts = [50, 100, 500, 1000]
    
    for count in test_counts:
        if count > len(cs_files):
            continue
            
        file_subset = cs_files[:count]
        print(f"\n=== Testing with {count} files ===")
        
        # Sequential test
        using_pattern = re.compile(r'^\s*using\s+GalaxyWorks\.Data(?:\.|;)', re.MULTILINE)
        
        start_time = time.time()
        sequential_matches = []
        for cs_file in file_subset:
            try:
                content = cs_file.read_text(encoding='utf-8', errors='ignore')
                if using_pattern.search(content):
                    sequential_matches.append(cs_file)
            except Exception:
                continue
        sequential_time = time.time() - start_time
        
        print(f"Sequential: {sequential_time:.3f}s, {len(sequential_matches)} matches")
        
        # Parallel test
        analysis_config = {
            'analysis_type': 'namespace',
            'target_namespace': 'GalaxyWorks.Data',
            'using_pattern': using_pattern
        }
        
        start_time = time.time()
        parallel_results = scatter.analyze_cs_files_parallel(
            file_subset, analysis_config,
            cs_analysis_chunk_size=50,
            max_workers=scatter.DEFAULT_MAX_WORKERS,
            disable_multiprocessing=False
        )
        parallel_time = time.time() - start_time
        parallel_matches = [f for f, result in parallel_results.items() if result['has_match']]
        
        print(f"Parallel:   {parallel_time:.3f}s, {len(parallel_matches)} matches")
        
        if sequential_time > 0:
            speedup = sequential_time / parallel_time
            print(f"Speedup: {speedup:.2f}x")
        
        # Test if parallel is actually being used
        if count >= 50:
            print(f"Should use parallel: YES (file count {count} >= 50)")
        else:
            print(f"Should use parallel: NO (file count {count} < 50)")

if __name__ == "__main__":
    main()