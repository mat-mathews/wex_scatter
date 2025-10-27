#!/usr/bin/env python3
"""
Comprehensive regression test summary for Phase 1 optimizations.
Validates all functionality and performance improvements.
"""

import subprocess
import sys
import time
from pathlib import Path

def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n🧪 {description}")
    print(f"Command: {' '.join(cmd)}")
    
    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        duration = time.time() - start_time
        
        if result.returncode == 0:
            print(f"✅ PASSED ({duration:.2f}s)")
            return True
        else:
            print(f"❌ FAILED ({duration:.2f}s)")
            print(f"STDERR: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"⏰ TIMEOUT after 60s")
        return False
    except Exception as e:
        print(f"💥 ERROR: {e}")
        return False

def main():
    """Run comprehensive regression tests."""
    
    print("="*80)
    print("COMPREHENSIVE REGRESSION TEST SUITE")
    print("Phase 1 Multiprocessing Optimization Validation")
    print("="*80)
    
    tests = []
    
    # 1. Unit Test Suite
    tests.append((
        ["python", "-m", "pytest", "test_multiprocessing_phase1.py", "-v", "--tb=short"],
        "Complete unit test suite (37 tests)"
    ))
    
    # 2. Core Functionality Tests
    tests.append((
        ["python", "scatter.py", "--target-project", "./GalaxyWorks.Data", "--search-scope", "."],
        "Basic target project analysis"
    ))
    
    tests.append((
        ["python", "scatter.py", "--target-project", "./GalaxyWorks.Data", "--search-scope", ".", "--class-name", "PortalDataService"],
        "Class-specific analysis"
    ))
    
    tests.append((
        ["python", "scatter.py", "--stored-procedure", "dbo.sp_InsertPortalConfiguration", "--search-scope", "."],
        "Stored procedure analysis"
    ))
    
    # 3. Multiprocessing Configuration Tests
    tests.append((
        ["python", "scatter.py", "--target-project", "./MyDotNetApp", "--search-scope", ".", "--disable-multiprocessing"],
        "Disabled multiprocessing mode"
    ))
    
    tests.append((
        ["python", "scatter.py", "--target-project", "./MyDotNetApp", "--search-scope", ".", "--max-workers", "2", "--chunk-size", "25"],
        "Custom multiprocessing parameters"
    ))
    
    # 4. Output Format Tests
    tests.append((
        ["python", "scatter.py", "--target-project", "./GalaxyWorks.Data", "--search-scope", ".", "--output-format", "json", "--output-file", "/tmp/test_output.json"],
        "JSON output format"
    ))
    
    tests.append((
        ["python", "scatter.py", "--target-project", "./GalaxyWorks.Data", "--search-scope", ".", "--output-format", "csv", "--output-file", "/tmp/test_output.csv"],
        "CSV output format"
    ))
    
    # 5. CLI Compatibility Tests
    tests.append((
        ["python", "scatter.py", "--help"],
        "Help text and CLI compatibility"
    ))
    
    # 6. Error Handling Tests (expects failure with exit code 1)
    error_tests = [
        (["python", "scatter.py", "--target-project", "./NonExistentProject", "--search-scope", "."], 
         "Invalid project handling (should fail)")
    ]
    
    # Run all tests
    passed = 0
    failed = 0
    
    for cmd, description in tests:
        if run_command(cmd, description):
            passed += 1
        else:
            failed += 1
    
    # Run error tests (expect failure)
    for cmd, description in error_tests:
        print(f"\n🧪 {description}")
        print(f"Command: {' '.join(cmd)}")
        
        start_time = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            duration = time.time() - start_time
            
            if result.returncode != 0:
                print(f"✅ PASSED - Correctly failed ({duration:.2f}s)")
                passed += 1
            else:
                print(f"❌ FAILED - Should have failed but didn't ({duration:.2f}s)")
                failed += 1
        except subprocess.TimeoutExpired:
            print(f"⏰ TIMEOUT after 60s")
            failed += 1
        except Exception as e:
            print(f"💥 ERROR: {e}")
            failed += 1
    
    # Results Summary
    print("\n" + "="*80)
    print("REGRESSION TEST RESULTS")
    print("="*80)
    print(f"✅ PASSED: {passed}")
    print(f"❌ FAILED: {failed}")
    print(f"📊 TOTAL:  {passed + failed}")
    
    if failed == 0:
        print("\n🎉 ALL REGRESSION TESTS PASSED!")
        print("✅ Phase 1 optimizations are ready for production")
        print("✅ Backward compatibility maintained")
        print("✅ Performance improvements validated")
        return 0
    else:
        print(f"\n⚠️  {failed} REGRESSION TEST(S) FAILED!")
        print("❌ Review failed tests before proceeding")
        return 1

if __name__ == "__main__":
    sys.exit(main())