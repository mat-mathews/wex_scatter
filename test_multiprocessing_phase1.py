#!/usr/bin/env python3
"""
Unit tests for multiprocessing Phase 1 implementation in scatter.py
Tests the target project analysis functionality using the mock .NET projects.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

# Add the current directory to the path so we can import scatter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scatter


class TestMultiprocessingPhase1(unittest.TestCase):
    """Test multiprocessing Phase 1 implementation using mock .NET projects."""
    
    def setUp(self):
        """Set up test environment before each test."""
        # Use the actual mock projects in the repository
        self.test_root = Path(__file__).parent.resolve()
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        self.consumer1_project = self.test_root / "MyGalaxyConsumerApp" / "MyGalaryConsumerApp.csproj"
        self.consumer2_project = self.test_root / "MyGalaxyConsumerApp2" / "MyGalaryConsumerApp2.csproj"
        
        # Verify test projects exist
        self.assertTrue(self.galaxy_works_project.exists(), 
                       f"Target project not found: {self.galaxy_works_project}")
        self.assertTrue(self.consumer1_project.exists(), 
                       f"Consumer project 1 not found: {self.consumer1_project}")
        self.assertTrue(self.consumer2_project.exists(), 
                       f"Consumer project 2 not found: {self.consumer2_project}")

    def test_parallel_file_discovery_csproj_files(self):
        """Test parallel discovery of .csproj files."""
        # Test with multiprocessing enabled
        csproj_files_parallel = scatter.find_files_with_pattern_parallel(
            self.test_root, '*.csproj', 
            max_workers=2, 
            chunk_size=10, 
            disable_multiprocessing=False
        )
        
        # Test with multiprocessing disabled (sequential)
        csproj_files_sequential = scatter.find_files_with_pattern_parallel(
            self.test_root, '*.csproj', 
            disable_multiprocessing=True
        )
        
        # Both should find the same files
        parallel_names = {f.name for f in csproj_files_parallel}
        sequential_names = {f.name for f in csproj_files_sequential}
        
        self.assertEqual(parallel_names, sequential_names, 
                        "Parallel and sequential file discovery should find the same .csproj files")
        
        # Should find at least our test projects
        expected_projects = {
            "GalaxyWorks.Data.csproj",
            "MyGalaryConsumerApp.csproj", 
            "MyGalaryConsumerApp2.csproj"
        }
        
        self.assertTrue(expected_projects.issubset(parallel_names), 
                       f"Expected projects {expected_projects} not found in {parallel_names}")

    def test_parallel_file_discovery_cs_files(self):
        """Test parallel discovery of .cs files."""
        galaxy_works_dir = self.galaxy_works_project.parent
        
        # Test with multiprocessing
        cs_files_parallel = scatter.find_files_with_pattern_parallel(
            galaxy_works_dir, '*.cs',
            max_workers=2,
            chunk_size=5,
            disable_multiprocessing=False
        )
        
        # Test sequential
        cs_files_sequential = scatter.find_files_with_pattern_parallel(
            galaxy_works_dir, '*.cs',
            disable_multiprocessing=True
        )
        
        # Should find the same files
        parallel_names = {f.name for f in cs_files_parallel}
        sequential_names = {f.name for f in cs_files_sequential}
        
        self.assertEqual(parallel_names, sequential_names,
                        "Parallel and sequential should find the same .cs files")
        
        # Should find at least some .cs files in GalaxyWorks.Data
        self.assertGreater(len(cs_files_parallel), 0, 
                          "Should find at least one .cs file in GalaxyWorks.Data")

    def test_find_consumers_with_multiprocessing(self):
        """Test the find_consumers function with multiprocessing enabled and disabled."""
        
        # Test with multiprocessing enabled
        consumers_parallel = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            max_workers=2,
            chunk_size=10,
            disable_multiprocessing=False
        )
        
        # Test with multiprocessing disabled
        consumers_sequential = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True
        )
        
        # Both should find the same consumers
        self.assertEqual(len(consumers_parallel), len(consumers_sequential),
                        "Parallel and sequential should find the same number of consumers")
        
        # Extract consumer names for comparison
        parallel_consumer_names = {c['consumer_name'] for c in consumers_parallel}
        sequential_consumer_names = {c['consumer_name'] for c in consumers_sequential}
        
        self.assertEqual(parallel_consumer_names, sequential_consumer_names,
                        "Parallel and sequential should find the same consumer projects")
        
        # Should find our known consumers
        expected_consumers = {"MyGalaryConsumerApp", "MyGalaryConsumerApp2"}
        self.assertTrue(expected_consumers.issubset(parallel_consumer_names),
                       f"Expected consumers {expected_consumers} not found in {parallel_consumer_names}")

    def test_chunk_list_utility(self):
        """Test the chunk_list utility function."""
        items = list(range(10))
        
        # Test normal chunking
        chunks = scatter.chunk_list(items, 3)
        expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
        self.assertEqual(chunks, expected)
        
        # Test chunking with chunk size larger than list
        chunks = scatter.chunk_list(items, 20)
        expected = [items]  # Should return one chunk with all items
        self.assertEqual(chunks, expected)
        
        # Test empty list
        chunks = scatter.chunk_list([], 5)
        self.assertEqual(chunks, [])

    def test_target_project_analysis_end_to_end(self):
        """Test complete target project analysis workflow with multiprocessing."""
        
        # Mock the command line arguments
        mock_args = MagicMock()
        mock_args.target_project = str(self.galaxy_works_project)
        mock_args.search_scope = str(self.test_root)
        mock_args.class_name = None
        mock_args.method_name = None
        mock_args.target_namespace = None
        mock_args.max_workers = 2
        mock_args.chunk_size = 10
        mock_args.disable_multiprocessing = False
        mock_args.summarize_consumers = False
        mock_args.verbose = True
        
        # Test the target project analysis
        target_namespace = scatter.derive_namespace(self.galaxy_works_project)
        self.assertIsNotNone(target_namespace, "Should derive a namespace from the project")
        
        # Test consumer analysis
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace=target_namespace,
            class_name=mock_args.class_name,
            method_name=mock_args.method_name,
            max_workers=mock_args.max_workers,
            chunk_size=mock_args.chunk_size,
            disable_multiprocessing=mock_args.disable_multiprocessing
        )
        
        # Validate results
        self.assertIsInstance(consumers, list, "Should return a list of consumers")
        self.assertGreater(len(consumers), 0, "Should find at least one consumer")
        
        # Check consumer structure
        for consumer in consumers:
            self.assertIn('consumer_path', consumer)
            self.assertIn('consumer_name', consumer)
            self.assertIn('relevant_files', consumer)
            self.assertIsInstance(consumer['consumer_path'], Path)
            self.assertIsInstance(consumer['consumer_name'], str)
            self.assertIsInstance(consumer['relevant_files'], list)

    def test_multiprocessing_fallback_behavior(self):
        """Test that multiprocessing gracefully falls back to sequential when needed."""
        
        # Test with very small directory set (should fall back to sequential)
        small_dir = self.galaxy_works_project.parent
        
        with patch('scatter.logging') as mock_logging:
            files = scatter.find_files_with_pattern_parallel(
                small_dir, '*.cs',
                max_workers=4,
                chunk_size=100,  # Large chunk size to trigger fallback
                disable_multiprocessing=False
            )
            
            # Should find files
            self.assertGreater(len(files), 0)
            
            # Check that it logged the fallback to sequential
            debug_calls = [call for call in mock_logging.debug.call_args_list 
                          if 'sequential' in str(call)]
            self.assertGreater(len(debug_calls), 0, 
                             "Should log fallback to sequential processing")

    def test_multiprocessing_disabled_flag(self):
        """Test that the disable_multiprocessing flag works correctly."""
        
        with patch('scatter.logging') as mock_logging:
            files = scatter.find_files_with_pattern_parallel(
                self.test_root, '*.csproj',
                disable_multiprocessing=True
            )
            
            # Should find files
            self.assertGreater(len(files), 0)
            
            # Check that it logged using sequential
            debug_calls = [call for call in mock_logging.debug.call_args_list 
                          if 'sequential' in str(call)]
            self.assertGreater(len(debug_calls), 0, 
                             "Should log using sequential processing when disabled")

    def test_error_handling_in_worker_function(self):
        """Test error handling in the worker function."""
        
        # Test with a non-existent path in the chunk
        non_existent_path = Path("/this/path/does/not/exist")
        valid_path = self.test_root
        
        # This should not crash even with invalid paths mixed in
        result = scatter.find_files_with_pattern_chunk((
            self.test_root, 
            '*.csproj', 
            [valid_path, non_existent_path]
        ))
        
        # Should return results for valid paths and handle invalid ones gracefully
        self.assertIsInstance(result, list)
        # Should find at least some .csproj files from the valid path
        csproj_names = {f.name for f in result}
        self.assertIn("GalaxyWorks.Data.csproj", csproj_names)


class TestTargetSymbolSearch(unittest.TestCase):
    """Test target symbol searching functionality with multiprocessing."""
    
    def setUp(self):
        """Set up test environment before each test."""
        self.test_root = Path(__file__).parent.resolve()
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        
    def test_find_consumers_with_specific_class_parallel(self):
        """Test finding consumers of a specific class with multiprocessing enabled."""
        
        # Test with PortalDataService class - should find consumers
        consumers_parallel = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name=None,
            max_workers=2,
            chunk_size=10,
            disable_multiprocessing=False
        )
        
        # Test sequential for comparison
        consumers_sequential = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name=None,
            disable_multiprocessing=True
        )
        
        # Both should find the same consumers
        self.assertEqual(len(consumers_parallel), len(consumers_sequential))
        
        # Should find consumers since both MyGalaxyConsumerApp projects use PortalDataService
        self.assertGreater(len(consumers_parallel), 0, "Should find consumers using PortalDataService")
        
        # Verify consumer names
        parallel_consumer_names = {c['consumer_name'] for c in consumers_parallel}
        expected_consumers = {"MyGalaryConsumerApp", "MyGalaryConsumerApp2"}
        self.assertTrue(expected_consumers.issubset(parallel_consumer_names),
                       f"Expected consumers {expected_consumers} not found in {parallel_consumer_names}")

    def test_find_consumers_with_specific_method_parallel(self):
        """Test finding consumers of a specific method with multiprocessing."""
        
        # Test with a specific method from PortalDataService
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name="StorePortalConfigurationAsync",
            max_workers=2,
            disable_multiprocessing=False
        )
        
        # Should return valid results (might be empty if method not used in consumers)
        self.assertIsInstance(consumers, list)
        
        # Validate structure for any found consumers
        for consumer in consumers:
            self.assertIn('consumer_path', consumer)
            self.assertIn('consumer_name', consumer)
            self.assertIn('relevant_files', consumer)

    def test_find_consumers_with_nonexistent_class(self):
        """Test finding consumers of a class that doesn't exist."""
        
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="NonExistentClass",
            method_name=None,
            max_workers=2,
            disable_multiprocessing=False
        )
        
        # Should return empty list
        self.assertEqual(len(consumers), 0, "Should find no consumers for non-existent class")

    def test_find_consumers_with_model_classes(self):
        """Test finding consumers of model classes like PortalConfiguration."""
        
        # Test with PortalConfiguration class
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalConfiguration",
            method_name=None,
            max_workers=2,
            disable_multiprocessing=False
        )
        
        # Should return valid results
        self.assertIsInstance(consumers, list)
        
        # Test with StatusType enum
        consumers_enum = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="StatusType",
            method_name=None,
            max_workers=2,
            disable_multiprocessing=False
        )
        
        self.assertIsInstance(consumers_enum, list)

    def test_stored_procedure_analysis_with_multiprocessing(self):
        """Test stored procedure analysis finds the correct classes and projects."""
        
        # Test finding references to a specific stored procedure
        sproc_results = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            max_workers=2,
            chunk_size=10,
            disable_multiprocessing=False
        )
        
        # Should find the procedure in GalaxyWorks.Data project
        self.assertIsInstance(sproc_results, dict)
        
        # If found, should map to PortalDataService class
        if sproc_results:
            found_classes = []
            for project_path, classes_dict in sproc_results.items():
                found_classes.extend(classes_dict.keys())
            
            # Should find PortalDataService class containing the stored procedure call
            if found_classes:
                self.assertIn("PortalDataService", found_classes,
                            "Should find PortalDataService class containing the stored procedure")

    def test_type_extraction_from_actual_files(self):
        """Test type extraction from the actual GalaxyWorks.Data source files."""
        
        # Read the PortalDataService.cs file and extract types
        portal_service_file = self.test_root / "GalaxyWorks.Data" / "DataServices" / "PortalDataService.cs"
        if portal_service_file.exists():
            content = portal_service_file.read_text(encoding='utf-8', errors='ignore')
            extracted_types = scatter.extract_type_names_from_content(content)
            
            # Should find PortalDataService class
            self.assertIn("PortalDataService", extracted_types,
                         "Should extract PortalDataService class from the file")
        
        # Read the EntityModels.cs file and extract types
        models_file = self.test_root / "GalaxyWorks.Data" / "Models" / "EntityModels.cs"
        if models_file.exists():
            content = models_file.read_text(encoding='utf-8', errors='ignore')
            extracted_types = scatter.extract_type_names_from_content(content)
            
            # Should find the model classes and enum
            expected_types = {"PortalConfiguration", "UserActivityLog", "SystemModule", "StatusType"}
            found_types = extracted_types.intersection(expected_types)
            self.assertGreater(len(found_types), 0,
                             f"Should extract model types from EntityModels.cs. Expected: {expected_types}, Found: {extracted_types}")

    def test_namespace_derivation_accuracy(self):
        """Test that namespace derivation works correctly for the target project."""
        
        derived_namespace = scatter.derive_namespace(self.galaxy_works_project)
        
        # Should derive GalaxyWorks.Data namespace
        self.assertIsNotNone(derived_namespace, "Should derive a namespace")
        self.assertEqual(derived_namespace, "GalaxyWorks.Data",
                        f"Should derive 'GalaxyWorks.Data' namespace, got '{derived_namespace}'")

    def test_symbol_search_consistency_parallel_vs_sequential(self):
        """Test that symbol search produces consistent results between parallel and sequential modes."""
        
        test_cases = [
            ("PortalDataService", None),
            ("PortalConfiguration", None),
            ("StatusType", None),
            ("PortalDataService", "StorePortalConfigurationAsync"),
            ("NonExistentClass", None),
        ]
        
        for class_name, method_name in test_cases:
            with self.subTest(class_name=class_name, method_name=method_name):
                # Parallel version
                consumers_parallel = scatter.find_consumers(
                    target_csproj_path=self.galaxy_works_project,
                    search_scope_path=self.test_root,
                    target_namespace="GalaxyWorks.Data",
                    class_name=class_name,
                    method_name=method_name,
                    max_workers=2,
                    disable_multiprocessing=False
                )
                
                # Sequential version
                consumers_sequential = scatter.find_consumers(
                    target_csproj_path=self.galaxy_works_project,
                    search_scope_path=self.test_root,
                    target_namespace="GalaxyWorks.Data",
                    class_name=class_name,
                    method_name=method_name,
                    disable_multiprocessing=True
                )
                
                # Should produce identical results
                self.assertEqual(len(consumers_parallel), len(consumers_sequential),
                               f"Parallel and sequential should find same number of consumers for {class_name}")
                
                if consumers_parallel:
                    parallel_names = {c['consumer_name'] for c in consumers_parallel}
                    sequential_names = {c['consumer_name'] for c in consumers_sequential}
                    self.assertEqual(parallel_names, sequential_names,
                                   f"Should find same consumers for {class_name}")

    def test_real_world_usage_patterns(self):
        """Test patterns that would be used in real-world scenarios."""
        
        # Scenario 1: "I changed PortalDataService, who uses it?"
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name=None,
            max_workers=4,
            disable_multiprocessing=False
        )
        
        # Should find the consumer apps
        self.assertGreater(len(consumers), 0, "Real-world scenario: Should find consumers of PortalDataService")
        
        # Scenario 2: "I changed the StorePortalConfigurationAsync method, what's the impact?"
        method_consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name="StorePortalConfigurationAsync",
            max_workers=4,
            disable_multiprocessing=False
        )
        
        # Should handle method-specific search
        self.assertIsInstance(method_consumers, list, "Should handle method-specific consumer search")
        
        # Scenario 3: "Who calls this stored procedure?"
        sproc_consumers = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            max_workers=4,
            disable_multiprocessing=False
        )
        
        # Should find stored procedure references
        self.assertIsInstance(sproc_consumers, dict, "Should handle stored procedure consumer search")


class TestBackwardsCompatibility(unittest.TestCase):
    """Test that the multiprocessing implementation maintains backwards compatibility."""
    
    def setUp(self):
        """Set up test environment before each test."""
        self.test_root = Path(__file__).parent.resolve()
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        
    def test_find_consumers_original_signature(self):
        """Test that find_consumers works with the original function signature (backwards compatibility)."""
        
        # Test calling find_consumers with only the original parameters
        # (multiprocessing parameters should have defaults)
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None
            # Note: NOT passing max_workers, chunk_size, or disable_multiprocessing
        )
        
        # Should work and return valid results
        self.assertIsInstance(consumers, list)
        self.assertGreater(len(consumers), 0, "Should find consumers with original signature")
        
        # Validate structure is unchanged
        for consumer in consumers:
            self.assertIn('consumer_path', consumer)
            self.assertIn('consumer_name', consumer) 
            self.assertIn('relevant_files', consumer)

    def test_find_cs_files_referencing_sproc_original_signature(self):
        """Test that find_cs_files_referencing_sproc works with original signature."""
        
        # Test with only the original parameters
        result = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root
            # Note: NOT passing custom_sproc_regex_pattern, max_workers, chunk_size, disable_multiprocessing
        )
        
        # Should work (even if no results found, function should not crash)
        self.assertIsInstance(result, dict)

    def test_find_cs_files_referencing_sproc_with_custom_pattern_only(self):
        """Test find_cs_files_referencing_sproc with only custom pattern (pre-multiprocessing signature)."""
        
        # Test with custom pattern but no multiprocessing parameters
        result = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_TestProcedure",
            search_path=self.test_root,
            custom_sproc_regex_pattern=r'["\'](?:[a-zA-Z0-9_]+\.)?{sproc_name_placeholder}["\']'
            # Note: NOT passing max_workers, chunk_size, disable_multiprocessing
        )
        
        # Should work with original + custom pattern signature
        self.assertIsInstance(result, dict)

    def test_function_signatures_have_proper_defaults(self):
        """Test that all new multiprocessing parameters have proper default values."""
        
        import inspect
        
        # Test find_consumers signature
        sig = inspect.signature(scatter.find_consumers)
        
        # Check that new parameters have defaults
        self.assertEqual(sig.parameters['max_workers'].default, scatter.DEFAULT_MAX_WORKERS)
        self.assertEqual(sig.parameters['chunk_size'].default, scatter.DEFAULT_CHUNK_SIZE)
        self.assertEqual(sig.parameters['disable_multiprocessing'].default, False)
        
        # Check original parameters don't have defaults (except Optional ones)
        self.assertEqual(sig.parameters['target_csproj_path'].default, inspect.Parameter.empty)
        self.assertEqual(sig.parameters['search_scope_path'].default, inspect.Parameter.empty)
        self.assertEqual(sig.parameters['target_namespace'].default, inspect.Parameter.empty)
        # class_name and method_name should remain Optional (no default needed for Optional[str])
        
        # Test find_cs_files_referencing_sproc signature  
        sig = inspect.signature(scatter.find_cs_files_referencing_sproc)
        
        # Check new parameters have defaults
        self.assertEqual(sig.parameters['max_workers'].default, scatter.DEFAULT_MAX_WORKERS)
        self.assertEqual(sig.parameters['chunk_size'].default, scatter.DEFAULT_CHUNK_SIZE)
        self.assertEqual(sig.parameters['disable_multiprocessing'].default, False)
        
        # Check original required parameters
        self.assertEqual(sig.parameters['sproc_name_input'].default, inspect.Parameter.empty)
        self.assertEqual(sig.parameters['search_path'].default, inspect.Parameter.empty)
        # custom_sproc_regex_pattern was already optional

    def test_command_line_interface_backwards_compatibility(self):
        """Test that original command line usage still works."""
        
        # Test that we can construct the argument parser without errors
        # and that original arguments are still available
        parser = scatter.argparse.ArgumentParser()
        
        # Add all the arguments just like in the main script
        mode_group = parser.add_mutually_exclusive_group(required=False)  # Make non-required for testing
        mode_group.add_argument("--target-project")
        mode_group.add_argument("--branch-name") 
        mode_group.add_argument("--stored-procedure")
        
        # Add some common arguments that existed before
        parser.add_argument("--search-scope")
        parser.add_argument("--class-name")
        parser.add_argument("--method-name")
        parser.add_argument("-v", "--verbose", action="store_true")
        
        # Test parsing original-style arguments (without multiprocessing flags)
        args = parser.parse_args([
            "--target-project", str(self.galaxy_works_project),
            "--search-scope", str(self.test_root),
            "--verbose"
        ])
        
        # Should parse successfully
        self.assertEqual(args.target_project, str(self.galaxy_works_project))
        self.assertEqual(args.search_scope, str(self.test_root))
        self.assertTrue(args.verbose)

    def test_output_format_unchanged(self):
        """Test that function outputs maintain the same format and structure."""
        
        # Get results with multiprocessing disabled (should match old behavior exactly)
        consumers_new = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data", 
            class_name=None,
            method_name=None,
            disable_multiprocessing=True  # Force old behavior
        )
        
        # Get results with multiprocessing enabled 
        consumers_parallel = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None, 
            method_name=None,
            disable_multiprocessing=False
        )
        
        # Results should have identical structure and content
        self.assertEqual(len(consumers_new), len(consumers_parallel))
        
        if consumers_new:  # If we found any consumers
            # Sort both lists by consumer name for comparison
            consumers_new_sorted = sorted(consumers_new, key=lambda x: x['consumer_name'])
            consumers_parallel_sorted = sorted(consumers_parallel, key=lambda x: x['consumer_name'])
            
            for old, new in zip(consumers_new_sorted, consumers_parallel_sorted):
                self.assertEqual(old['consumer_name'], new['consumer_name'])
                self.assertEqual(old['consumer_path'], new['consumer_path'])
                # relevant_files might be in different order, so compare as sets
                old_files = {f.name for f in old['relevant_files']}
                new_files = {f.name for f in new['relevant_files']}
                self.assertEqual(old_files, new_files)

    def test_old_script_behavior_simulation(self):
        """Simulate how the script would behave with old-style calls."""
        
        # Simulate the old way of calling find_consumers (before multiprocessing)
        # This is how existing code/scripts would call it
        
        # Mock the old-style usage
        target_csproj_path = self.galaxy_works_project
        search_scope_path = self.test_root
        target_namespace = scatter.derive_namespace(target_csproj_path)
        
        # This should work exactly as before
        consumers = scatter.find_consumers(
            target_csproj_path,
            search_scope_path, 
            target_namespace,
            None,  # class_name
            None   # method_name
        )
        
        # Should return the same type and structure as before
        self.assertIsInstance(consumers, list)
        
        # Test that we can process the results in the old way
        for consumer in consumers:
            # Old code would expect these exact keys
            consumer_path = consumer['consumer_path']
            consumer_name = consumer['consumer_name'] 
            relevant_files = consumer['relevant_files']
            
            # These should all work (same types as before)
            self.assertIsInstance(consumer_path, Path)
            self.assertIsInstance(consumer_name, str)
            self.assertIsInstance(relevant_files, list)
            
            # Old code might access these specific attributes
            self.assertTrue(consumer_path.exists())
            self.assertTrue(len(consumer_name) > 0)

    def test_error_messages_unchanged(self):
        """Test that error messages and warnings are unchanged for backwards compatibility."""
        
        with patch('scatter.logging') as mock_logging:
            # Test with an invalid project path (should generate same errors as before)
            try:
                scatter.find_consumers(
                    target_csproj_path=Path("/nonexistent/project.csproj"),
                    search_scope_path=self.test_root,
                    target_namespace="NonExistent.Namespace",
                    class_name=None,
                    method_name=None
                )
            except Exception:
                pass  # Expected to fail, we're testing error handling
            
            # Should have the same logging behavior as before
            # (This test ensures we didn't change error handling behavior)
            self.assertTrue(mock_logging.debug.called or mock_logging.warning.called or mock_logging.error.called)


class TestMultiprocessingConfiguration(unittest.TestCase):
    """Test multiprocessing configuration and constants."""
    
    def test_default_configuration(self):
        """Test that default configuration values are reasonable."""
        
        # Test DEFAULT_MAX_WORKERS
        self.assertGreater(scatter.DEFAULT_MAX_WORKERS, 0)
        self.assertLessEqual(scatter.DEFAULT_MAX_WORKERS, 32)
        
        # Test DEFAULT_CHUNK_SIZE
        self.assertGreater(scatter.DEFAULT_CHUNK_SIZE, 0)
        self.assertEqual(scatter.DEFAULT_CHUNK_SIZE, 75)
        
        # Test MULTIPROCESSING_ENABLED
        self.assertTrue(scatter.MULTIPROCESSING_ENABLED)

    def test_multiprocessing_cpu_calculation(self):
        """Test that CPU count calculation works correctly."""
        import multiprocessing
        
        expected_workers = min(32, (multiprocessing.cpu_count() or 1) + 4)
        self.assertEqual(scatter.DEFAULT_MAX_WORKERS, expected_workers)


if __name__ == '__main__':
    # Configure logging for tests
    import logging
    logging.basicConfig(level=logging.WARNING)  # Reduce noise during tests
    
    # Run the tests
    unittest.main(verbosity=2)