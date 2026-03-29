# Testing Guide for scatter.py Multiprocessing Implementation

This guide provides comprehensive manual testing instructions for the Phase 1 multiprocessing implementation using the mock .NET projects included in this repository.

## Table of Contents
- [Quick Start](#quick-start)
- [Mock Project Overview](#mock-project-overview)
- [Automated Unit Tests](#automated-unit-tests)
- [Manual Testing Commands](#manual-testing-commands)
- [Performance Testing](#performance-testing)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Prerequisites
```bash
# Navigate to the project directory
cd /Users/mat/Documents/__src__/wex_scatter

# Verify mock projects exist
ls -la */
# Should show: GalaxyWorks.Data/, MyGalaxyConsumerApp/, MyGalaxyConsumerApp2/, etc.

# Verify scatter.py works
python scatter.py --help
```

### Run Basic Test
```bash
# Basic functionality test (should find 2 consumers)
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose
```

## Mock Project Overview

The repository contains realistic mock .NET projects for testing:

### **Target Project: GalaxyWorks.Data**
- **Location**: `./GalaxyWorks.Data/`
- **Contains**:
  - `PortalDataService` class (main service)
  - `PortalConfiguration`, `UserActivityLog`, `SystemModule` model classes
  - `StatusType` enum
  - Stored procedure calls: `dbo.sp_InsertPortalConfiguration`, `dbo.sp_UpdatePortalConfiguration`, etc.

### **Consumer Projects**
- **MyGalaxyConsumerApp**: References and uses `PortalDataService` from GalaxyWorks.Data
- **MyGalaxyConsumerApp2**: References and uses `PortalDataService` from GalaxyWorks.Data
- **MyDotNetApp**: Basic .NET project with its own consumer
- **MyDotNetApp.Consumer**: References and uses MyDotNetApp

### **Project Relationships**
```
GalaxyWorks.Data (target)
├── MyGalaxyConsumerApp (consumer) ✅
└── MyGalaxyConsumerApp2 (consumer) ✅

MyDotNetApp (target)
└── MyDotNetApp.Consumer (consumer) ✅
```

## Automated Unit Tests

### Run All Tests
```bash
# Using pytest (recommended)
python -m pytest test_multiprocessing_phase1.py -v

# Using unittest
python test_multiprocessing_phase1.py
```

### Run Specific Test Categories
```bash
# Core multiprocessing functionality
python -m pytest test_multiprocessing_phase1.py::TestMultiprocessingPhase1 -v

# Target symbol search tests
python -m pytest test_multiprocessing_phase1.py::TestTargetSymbolSearch -v

# Backwards compatibility tests
python -m pytest test_multiprocessing_phase1.py::TestBackwardsCompatibility -v

# Configuration tests
python -m pytest test_multiprocessing_phase1.py::TestMultiprocessingConfiguration -v
```

### Expected Test Results
- **Total Tests**: 27
- **Expected Result**: All tests should PASS
- **Runtime**: ~10-15 seconds

## Manual Testing Commands

### 1. Basic Target Project Analysis

#### Test: Find all consumers of GalaxyWorks.Data
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope .
```
**Expected Result**: Should find 2 consumers (MyGalaxyConsumerApp, MyGalaxyConsumerApp2)

#### Test: Same with verbose logging
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose
```
**Expected Result**: Same as above + detailed multiprocessing debug logs

#### Test: Using project directory instead of .csproj file
```bash
python scatter.py --target-project ./GalaxyWorks.Data/ --search-scope . --verbose
```
**Expected Result**: Should auto-detect the .csproj file and work identically

### 2. Multiprocessing Configuration Testing

#### Test: Custom multiprocessing settings
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose --max-workers 2 --chunk-size 25
```
**Expected Result**: Should show "with 2 workers" in debug logs

#### Test: Disable multiprocessing (force sequential)
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose --disable-multiprocessing
```
**Expected Result**: Should show "Using sequential file discovery" in debug logs

#### Test: Compare parallel vs sequential results
```bash
# Run parallel
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . > parallel_results.txt

# Run sequential  
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --disable-multiprocessing > sequential_results.txt

# Compare (should be identical)
diff parallel_results.txt sequential_results.txt
```
**Expected Result**: No differences (empty diff output)

### 3. Symbol-Specific Analysis

#### Test: Find consumers of specific class
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "PortalDataService" --verbose
```
**Expected Result**: Should find 2 consumers, report "Triggering type: PortalDataService"

#### Test: Find consumers of model class
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "PortalConfiguration" --verbose
```
**Expected Result**: May find 0 consumers (model not directly used in consumer apps)

#### Test: Find consumers of enum
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "StatusType" --verbose
```
**Expected Result**: May find 0 consumers (enum not directly used in consumer apps)

#### Test: Find consumers of non-existent class
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "NonExistentClass" --verbose
```
**Expected Result**: Should find 0 consumers, complete without errors

#### Test: Method-specific analysis
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "PortalDataService" --method-name "StorePortalConfigurationAsync" --verbose
```
**Expected Result**: May find 0 consumers (method not called in simple consumer examples)

#### Test: Method without class (should be ignored)
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --method-name "SomeMethod" --verbose
```
**Expected Result**: Should ignore method-name and work like basic analysis (warning about method-name being ignored)

### 4. Stored Procedure Analysis

#### Test: Find stored procedure consumers
```bash
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . --verbose
```
**Expected Result**: Should find the procedure in GalaxyWorks.Data project, in PortalDataService class

#### Test: Find stored procedure with different pattern
```bash
python scatter.py --stored-procedure "sp_InsertPortalConfiguration" --search-scope . --verbose
```
**Expected Result**: Should find the same procedure (without "dbo." prefix)

#### Test: Find non-existent stored procedure
```bash
python scatter.py --stored-procedure "dbo.sp_NonExistent" --search-scope . --verbose
```
**Expected Result**: Should find 0 projects/classes, complete without errors

#### Test: Custom regex pattern for stored procedures
```bash
python scatter.py --stored-procedure "sp_InsertPortalConfiguration" --search-scope . --sproc-regex-pattern '["\'']{sproc_name_placeholder}["\']' --verbose
```
**Expected Result**: Should find references using custom pattern

### 5. Output Format Testing

#### Test: CSV output
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --output-format csv --output-file test_results.csv
cat test_results.csv
```
**Expected Result**: Should create CSV file with consumer data

#### Test: JSON output
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --output-format json --output-file test_results.json
cat test_results.json | python -m json.tool
```
**Expected Result**: Should create well-formatted JSON file

#### Test: Console output (default)
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --output-format console
```
**Expected Result**: Should display results in console (same as without --output-format)

### 6. Edge Case Testing

#### Test: Different target projects
```bash
# Test with MyDotNetApp (should find 1 consumer)
python scatter.py --target-project ./MyDotNetApp --search-scope . --verbose

# Test with MyDotNetApp.Consumer (should find 0 consumers - it's a leaf node)
python scatter.py --target-project ./MyDotNetApp.Consumer --search-scope . --verbose
```
**Expected Result**: MyDotNetApp should find 1 consumer (MyDotNetApp.Consumer), MyDotNetApp.Consumer should find 0

#### Test: Invalid project path
```bash
python scatter.py --target-project ./NonExistentProject --search-scope .
```
**Expected Result**: Should exit with error about project not found

#### Test: Invalid search scope
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope /nonexistent/path
```
**Expected Result**: Should exit with error about search scope not found

#### Test: Missing required arguments
```bash
# Missing search scope for target mode
python scatter.py --target-project ./GalaxyWorks.Data

# Missing search scope for stored procedure mode
python scatter.py --stored-procedure "dbo.sp_test"
```
**Expected Result**: Should show error about missing --search-scope

### 7. Backwards Compatibility Testing

#### Test: Original command format (no multiprocessing flags)
```bash
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . -v
```
**Expected Result**: Should work identically to the verbose command with multiprocessing enabled

#### Test: All original argument combinations
```bash
# Basic target analysis
python scatter.py --target-project ./GalaxyWorks.Data --search-scope .

# With class filter
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "PortalDataService"

# With target namespace
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --target-namespace "GalaxyWorks.Data"

# Stored procedure analysis
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope .
```
**Expected Result**: All should work without any multiprocessing flags specified

## Performance Testing

### Measure File Discovery Performance

#### Test: Large chunk size (forces sequential for small directories)
```bash
time python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --chunk-size 1000 --verbose
```

#### Test: Small chunk size (forces parallel even for small directories) 
```bash
time python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --chunk-size 5 --verbose
```

#### Test: Sequential vs Parallel timing
```bash
# Time sequential
time python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --disable-multiprocessing

# Time parallel
time python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --max-workers 4
```

### Memory Usage Testing
```bash
# Monitor memory usage during execution
/usr/bin/time -l python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose
```

## Expected Results Summary

| Test Type | Expected Consumers | Expected Projects | Notes |
|-----------|-------------------|-------------------|-------|
| Basic GalaxyWorks.Data analysis | 2 | MyGalaxyConsumerApp, MyGalaxyConsumerApp2 | Core functionality |
| PortalDataService class filter | 2 | Same as above | Class is used in both consumers |
| PortalConfiguration class filter | 0 | None | Model not directly referenced |
| StatusType enum filter | 0 | None | Enum not directly referenced |
| MyDotNetApp analysis | 1 | MyDotNetApp.Consumer | Basic .NET project with consumer |
| MyDotNetApp.Consumer analysis | 0 | None | Leaf node project |
| Stored procedure sp_InsertPortalConfiguration | 1 project, 1-2 classes | GalaxyWorks.Data | Found in PortalDataService |
| Non-existent class/procedure | 0 | None | Should handle gracefully |

## Troubleshooting

### Common Issues

#### No consumers found when expected
```bash
# Check if projects actually reference each other
grep -r "GalaxyWorks.Data" */Project.cs
grep -r "ProjectReference" */*.csproj
```

#### Multiprocessing not activating
```bash
# Check directory count (needs sufficient directories to trigger parallel mode)
find . -type d | wc -l

# Force parallel with small chunk size
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --chunk-size 1 --verbose
```

#### Import errors
```bash
# Check Python environment
python -c "import concurrent.futures; print('OK')"
python -c "import git; print('GitPython OK')"

# Install missing dependencies
pip install -r requirements.txt
```

### Debug Commands

#### Verify mock project structure
```bash
# Check .csproj files exist
find . -name "*.csproj" -exec echo "Found: {}" \;

# Check C# files exist  
find . -name "*.cs" -exec echo "Found: {}" \;

# Check project references
grep -r "ProjectReference" */*.csproj
```

#### Test file discovery functions directly
```bash
# Test Python imports
python -c "import scatter; print('Import successful')"

# Test basic functions
python -c "
from pathlib import Path
import scatter
files = scatter.find_files_with_pattern_parallel(Path('.'), '*.csproj')
print(f'Found {len(files)} .csproj files: {[f.name for f in files]}')
"
```

### Performance Validation

For performance testing on larger codebases, you can create additional mock projects:

```bash
# Create additional test projects (optional)
for i in {1..10}; do
    mkdir -p TestProject$i
    echo '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>' > TestProject$i/TestProject$i.csproj
    echo 'namespace TestProject'$i' { class Program { static void Main() {} } }' > TestProject$i/Program.cs
done

# Run analysis on expanded project set
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose
```

## Test Completion Checklist

- [ ] All automated unit tests pass
- [ ] Basic target project analysis works
- [ ] Multiprocessing configuration options work
- [ ] Symbol-specific analysis works
- [ ] Stored procedure analysis works
- [ ] Output format options work
- [ ] Edge cases handle gracefully
- [ ] Backwards compatibility maintained
- [ ] Performance shows improvement or equivalent timing
- [ ] Memory usage is reasonable

## Getting Help

If tests fail or you encounter issues:

1. **Check the logs**: Always run with `--verbose` for detailed information
2. **Verify environment**: Ensure all dependencies are installed
3. **Check mock projects**: Verify the mock .NET projects are intact
4. **Compare results**: Use `--disable-multiprocessing` to compare against sequential processing
5. **Run unit tests**: Use the automated test suite to isolate issues

For additional help, run:
```bash
python scatter.py --help
```

## Quick Reference Commands

### Essential Test Commands
```bash
# Basic functionality test
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --verbose

# Run all unit tests
python -m pytest test_multiprocessing_phase1.py -v

# Test multiprocessing vs sequential
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --disable-multiprocessing --verbose

# Test class-specific analysis
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --class-name "PortalDataService" --verbose

# Test stored procedure analysis
python scatter.py --stored-procedure "dbo.sp_InsertPortalConfiguration" --search-scope . --verbose

# Test output formats
python scatter.py --target-project ./GalaxyWorks.Data --search-scope . --output-format json --output-file results.json
```

### Multiprocessing Options Quick Reference
```bash
--disable-multiprocessing     # Force sequential processing
--max-workers N              # Set number of worker processes (default: 14)
--chunk-size N               # Set directories per worker chunk (default: 75)
```

### Expected Results Quick Reference
- **GalaxyWorks.Data consumers**: 2 (MyGalaxyConsumerApp, MyGalaxyConsumerApp2)
- **MyDotNetApp consumers**: 1 (MyDotNetApp.Consumer)
- **PortalDataService usage**: Found in both Galaxy consumer apps
- **Stored procedure sp_InsertPortalConfiguration**: Found in GalaxyWorks.Data/PortalDataService
- **Leaf projects (MyDotNetApp.Consumer)**: 0 consumers found (expected)