#!/usr/bin/env python3
"""
Unit tests for multiprocessing Phase 1 implementation in scatter.py
Tests the target project analysis functionality using the mock .NET projects.
"""

import unittest
from pathlib import Path
from unittest.mock import patch
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
        """Test complete target project analysis workflow."""

        # Test the target project analysis
        target_namespace = scatter.derive_namespace(self.galaxy_works_project)
        self.assertIsNotNone(target_namespace, "Should derive a namespace from the project")

        # Test consumer analysis
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace=target_namespace,
            class_name=None,
            method_name=None,
            max_workers=2,
            chunk_size=10,
            disable_multiprocessing=False
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
        self.assertGreater(len(sproc_results), 0, "Should find at least one project with the sproc")

        found_classes = []
        for project_path, classes_dict in sproc_results.items():
            found_classes.extend(classes_dict.keys())

        # Should find PortalDataService class containing the stored procedure call
        self.assertIn("PortalDataService", found_classes,
                      "Should find PortalDataService class containing the stored procedure")

    def test_type_extraction_from_actual_files(self):
        """Test type extraction from the actual GalaxyWorks.Data source files."""

        # Read the PortalDataService.cs file and extract types
        portal_service_file = self.test_root / "GalaxyWorks.Data" / "DataServices" / "PortalDataService.cs"
        self.assertTrue(portal_service_file.exists(), f"Expected file: {portal_service_file}")
        content = portal_service_file.read_text(encoding='utf-8', errors='ignore')
        extracted_types = scatter.extract_type_names_from_content(content)

        # Should find PortalDataService class
        self.assertIn("PortalDataService", extracted_types,
                     "Should extract PortalDataService class from the file")

        # Read the EntityModels.cs file and extract types
        models_file = self.test_root / "GalaxyWorks.Data" / "Models" / "EntityModels.cs"
        self.assertTrue(models_file.exists(), f"Expected file: {models_file}")
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


class TestBackwardsCompatibility(unittest.TestCase):
    """Test that the multiprocessing implementation maintains backwards compatibility."""

    def setUp(self):
        """Set up test environment before each test."""
        self.test_root = Path(__file__).parent.resolve()
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"

    def test_find_consumers_default_params(self):
        """Test that find_consumers works without passing multiprocessing parameters."""

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
        self.assertGreater(len(consumers), 0, "Should find consumers with default params")

        # Validate structure is unchanged
        for consumer in consumers:
            self.assertIn('consumer_path', consumer)
            self.assertIn('consumer_name', consumer)
            self.assertIn('relevant_files', consumer)

    def test_parallel_sequential_identical_results(self):
        """Test that parallel and sequential modes produce identical results."""

        # Get results with multiprocessing disabled (sequential)
        consumers_sequential = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            disable_multiprocessing=True
        )

        # Get results with multiprocessing enabled (parallel)
        consumers_parallel = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            disable_multiprocessing=False
        )

        # Results should have identical structure and content
        self.assertEqual(len(consumers_sequential), len(consumers_parallel))

        # Sort both lists by consumer name for comparison
        consumers_seq_sorted = sorted(consumers_sequential, key=lambda x: x['consumer_name'])
        consumers_par_sorted = sorted(consumers_parallel, key=lambda x: x['consumer_name'])

        for seq, par in zip(consumers_seq_sorted, consumers_par_sorted):
            self.assertEqual(seq['consumer_name'], par['consumer_name'])
            self.assertEqual(seq['consumer_path'], par['consumer_path'])
            # relevant_files might be in different order, so compare as sets
            seq_files = {f.name for f in seq['relevant_files']}
            par_files = {f.name for f in par['relevant_files']}
            self.assertEqual(seq_files, par_files)

    def test_return_type_consistency(self):
        """Test that function return types match the expected contract."""

        # Test find_consumers return type: List[Dict[str, Union[Path, str, List[Path]]]]
        consumers = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None
        )

        self.assertIsInstance(consumers, list)
        for consumer in consumers:
            self.assertIsInstance(consumer, dict)
            self.assertIsInstance(consumer['consumer_path'], Path)
            self.assertIsInstance(consumer['consumer_name'], str)
            self.assertIsInstance(consumer['relevant_files'], list)
            for file_path in consumer['relevant_files']:
                self.assertIsInstance(file_path, Path)

        # Test find_cs_files_referencing_sproc return type: Dict[Path, Dict[str, Set[Path]]]
        sproc_result = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root
        )

        self.assertIsInstance(sproc_result, dict)
        for proj_path, classes_dict in sproc_result.items():
            self.assertIsInstance(proj_path, Path)
            self.assertIsInstance(classes_dict, dict)
            for class_name, file_set in classes_dict.items():
                self.assertIsInstance(class_name, str)
                self.assertIsInstance(file_set, set)
                for file_path in file_set:
                    self.assertIsInstance(file_path, Path)


if __name__ == '__main__':
    # Configure logging for tests
    import logging
    logging.basicConfig(level=logging.WARNING)  # Reduce noise during tests

    # Run the tests
    unittest.main(verbosity=2)
