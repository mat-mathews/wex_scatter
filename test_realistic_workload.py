#!/usr/bin/env python3
"""
Test with a more realistic workload to find the proper multiprocessing threshold.
"""

import sys
import time
import re
import tempfile
import shutil
from pathlib import Path

# Add scatter to path
sys.path.insert(0, str(Path(__file__).parent))
import scatter

def create_larger_test_files(count: int) -> Path:
    """Create larger, more complex test files."""
    test_dir = Path(tempfile.mkdtemp(prefix="scatter_realistic_test_"))
    
    # Template for a larger, more realistic C# file
    template = """using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using GalaxyWorks.Data;
using GalaxyWorks.Core;
using GalaxyWorks.Models;

namespace TestNamespace.Project{project_num}
{{
    public class TestClass{file_num} : BaseService
    {{
        private readonly PortalDataService _dataService;
        private readonly IConfiguration _configuration;
        private readonly ILogger<TestClass{file_num}> _logger;
        
        public TestClass{file_num}(
            PortalDataService dataService,
            IConfiguration configuration,
            ILogger<TestClass{file_num}> logger)
        {{
            _dataService = dataService;
            _configuration = configuration;
            _logger = logger;
        }}
        
        public async Task<List<PortalConfiguration>> GetConfigurations()
        {{
            try
            {{
                _logger.LogInformation("Starting configuration retrieval");
                
                // Multiple stored procedure calls
                var configs = await _dataService.ExecuteStoredProcedureAsync("dbo.sp_InsertPortalConfiguration");
                var settings = await _dataService.ExecuteStoredProcedureAsync("dbo.sp_GetPortalSettings");
                var metadata = await _dataService.ExecuteStoredProcedureAsync("dbo.sp_GetPortalMetadata");
                
                // Complex business logic with multiple pattern matches
                var results = new List<PortalConfiguration>();
                foreach (var config in configs)
                {{
                    if (config.IsActive && ValidateConfiguration(config))
                    {{
                        results.Add(TransformConfiguration(config));
                    }}
                }}
                
                _logger.LogInformation($"Retrieved {{results.Count}} configurations");
                return results;
            }}
            catch (Exception ex)
            {{
                _logger.LogError(ex, "Error retrieving configurations");
                throw;
            }}
        }}
        
        private bool ValidateConfiguration(dynamic config)
        {{
            // Complex validation logic
            return config != null && 
                   !string.IsNullOrEmpty(config.Name) &&
                   config.CreatedDate > DateTime.Now.AddYears(-1);
        }}
        
        private PortalConfiguration TransformConfiguration(dynamic config)
        {{
            return new PortalConfiguration
            {{
                Id = config.Id,
                Name = config.Name,
                Value = config.Value,
                IsActive = config.IsActive,
                CreatedDate = config.CreatedDate
            }};
        }}
        
        public async Task<bool> UpdateConfiguration(int id, string value)
        {{
            try
            {{
                var result = await _dataService.ExecuteStoredProcedureAsync("dbo.sp_UpdatePortalConfiguration", 
                    new {{ Id = id, Value = value }});
                return result > 0;
            }}
            catch
            {{
                return false;
            }}
        }}
        
        // Additional methods with various patterns
        public void ProcessBatch()
        {{
            var processor = new PortalDataService();
            processor.BatchProcess();
        }}
        
        public string GenerateReport()
        {{
            return $"Report for {{nameof(TestClass{file_num})}} generated at {{DateTime.Now}}";
        }}
    }}
    
    public interface ITestInterface{file_num}
    {{
        Task<List<PortalConfiguration>> GetConfigurations();
        Task<bool> UpdateConfiguration(int id, string value);
    }}
    
    public enum TestEnum{file_num}
    {{
        Active,
        Inactive,
        Pending
    }}
}}"""
    
    for i in range(count):
        project_num = i // 50  # 50 files per project
        project_dir = test_dir / f"TestProject{project_num}"
        project_dir.mkdir(exist_ok=True)
        
        cs_file = project_dir / f"TestClass{i}.cs"
        content = template.format(file_num=i, project_num=project_num)
        cs_file.write_text(content)
    
    print(f"Created {count} realistic test files in {test_dir}")
    return test_dir

def test_realistic_workload():
    """Test with realistic file sizes and counts."""
    print("Testing with realistic workload...")
    
    # Test with different file counts
    test_counts = [100, 500, 1000, 2000, 5000]
    
    for count in test_counts:
        print(f"\n=== Testing with {count} realistic files ===")
        
        # Create test files
        test_dir = create_larger_test_files(count)
        cs_files = list(test_dir.rglob("*.cs"))
        
        try:
            # Sequential test
            using_pattern = re.compile(r'^\s*using\s+GalaxyWorks\.Data(?:\.|;)', re.MULTILINE)
            
            start_time = time.time()
            sequential_matches = []
            for cs_file in cs_files:
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
                cs_files, analysis_config,
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
                
                if speedup > 1.0:
                    print(f"✅ Parallel is faster!")
                    break
                else:
                    print(f"❌ Sequential still faster")
        
        finally:
            # Cleanup
            shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_realistic_workload()