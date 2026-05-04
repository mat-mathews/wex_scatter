#!/usr/bin/env python3
"""
Unit tests for multiprocessing Phase 1 implementation in scatter.py
Tests the target project analysis functionality using the mock .NET projects.
"""

import unittest
from pathlib import Path
import sys
import os

# Add the current directory to the path so we can import scatter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scatter


class TestMultiprocessingPhase1(unittest.TestCase):
    """Test multiprocessing Phase 1 implementation using mock .NET projects."""

    def setUp(self):
        """Set up test environment before each test."""
        # Use the actual mock projects in the repository
        self.test_root = Path(__file__).parent.parent.parent.resolve() / "samples"
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"
        self.consumer1_project = (
            self.test_root / "MyGalaxyConsumerApp" / "MyGalaxyConsumerApp.csproj"
        )
        self.consumer2_project = (
            self.test_root / "MyGalaxyConsumerApp2" / "MyGalaxyConsumerApp2.csproj"
        )

        # Verify test projects exist
        self.assertTrue(
            self.galaxy_works_project.exists(),
            f"Target project not found: {self.galaxy_works_project}",
        )
        self.assertTrue(
            self.consumer1_project.exists(),
            f"Consumer project 1 not found: {self.consumer1_project}",
        )
        self.assertTrue(
            self.consumer2_project.exists(),
            f"Consumer project 2 not found: {self.consumer2_project}",
        )

    def test_parallel_file_discovery_csproj_files(self):
        """Test parallel discovery of .csproj files."""
        # Test with multiprocessing enabled
        csproj_files_parallel = scatter.find_files_with_pattern_parallel(
            self.test_root, "*.csproj", max_workers=2, chunk_size=10, disable_multiprocessing=False
        )

        # Test with multiprocessing disabled (sequential)
        csproj_files_sequential = scatter.find_files_with_pattern_parallel(
            self.test_root, "*.csproj", disable_multiprocessing=True
        )

        # Both should find the same files
        parallel_names = {f.name for f in csproj_files_parallel}
        sequential_names = {f.name for f in csproj_files_sequential}

        self.assertEqual(
            parallel_names,
            sequential_names,
            "Parallel and sequential file discovery should find the same .csproj files",
        )

        # Should find at least our test projects
        expected_projects = {
            "GalaxyWorks.Data.csproj",
            "MyGalaxyConsumerApp.csproj",
            "MyGalaxyConsumerApp2.csproj",
        }

        self.assertTrue(
            expected_projects.issubset(parallel_names),
            f"Expected projects {expected_projects} not found in {parallel_names}",
        )

    def test_parallel_file_discovery_cs_files(self):
        """Test parallel discovery of .cs files."""
        galaxy_works_dir = self.galaxy_works_project.parent

        # Test with multiprocessing
        cs_files_parallel = scatter.find_files_with_pattern_parallel(
            galaxy_works_dir, "*.cs", max_workers=2, chunk_size=5, disable_multiprocessing=False
        )

        # Test sequential
        cs_files_sequential = scatter.find_files_with_pattern_parallel(
            galaxy_works_dir, "*.cs", disable_multiprocessing=True
        )

        # Should find the same files
        parallel_names = {f.name for f in cs_files_parallel}
        sequential_names = {f.name for f in cs_files_sequential}

        self.assertEqual(
            parallel_names,
            sequential_names,
            "Parallel and sequential should find the same .cs files",
        )

        # Should find at least some .cs files in GalaxyWorks.Data
        self.assertGreater(
            len(cs_files_parallel), 0, "Should find at least one .cs file in GalaxyWorks.Data"
        )

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

    def test_error_handling_in_worker_function(self):
        """Test error handling in the worker function."""

        # Test with a non-existent path in the chunk
        non_existent_path = Path("/this/path/does/not/exist")
        valid_path = self.test_root

        # This should not crash even with invalid paths mixed in
        result = scatter.find_files_with_pattern_chunk(
            (self.test_root, "*.csproj", [valid_path, non_existent_path])
        )

        # Should return results for valid paths and handle invalid ones gracefully
        self.assertIsInstance(result, list)
        # Should find at least some .csproj files from the valid path
        csproj_names = {f.name for f in result}
        self.assertIn("GalaxyWorks.Data.csproj", csproj_names)


class TestTargetSymbolSearch(unittest.TestCase):
    """Test target symbol searching functionality with multiprocessing."""

    def setUp(self):
        """Set up test environment before each test."""
        self.test_root = Path(__file__).parent.parent.parent.resolve() / "samples"
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"

    def test_find_consumers_with_specific_method_parallel(self):
        """Test finding consumers of a specific method with multiprocessing."""

        # Test with a specific method from PortalDataService
        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name="PortalDataService",
            method_name="StorePortalConfigurationAsync",
            max_workers=2,
            disable_multiprocessing=False,
        )

        # Should return valid results (might be empty if method not used in consumers)
        self.assertIsInstance(consumers, list)

        # Validate structure for any found consumers
        for consumer in consumers:
            self.assertIn("consumer_path", consumer)
            self.assertIn("consumer_name", consumer)
            self.assertIn("relevant_files", consumer)

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
                consumers_parallel, _pipeline = scatter.find_consumers(
                    target_csproj_path=self.galaxy_works_project,
                    search_scope_path=self.test_root,
                    target_namespace="GalaxyWorks.Data",
                    class_name=class_name,
                    method_name=method_name,
                    max_workers=2,
                    disable_multiprocessing=False,
                )

                # Sequential version
                consumers_sequential, _pipeline = scatter.find_consumers(
                    target_csproj_path=self.galaxy_works_project,
                    search_scope_path=self.test_root,
                    target_namespace="GalaxyWorks.Data",
                    class_name=class_name,
                    method_name=method_name,
                    disable_multiprocessing=True,
                )

                # Should produce identical results
                self.assertEqual(
                    len(consumers_parallel),
                    len(consumers_sequential),
                    f"Parallel and sequential should find same number of consumers for {class_name}",
                )

                if consumers_parallel:
                    parallel_names = {c["consumer_name"] for c in consumers_parallel}
                    sequential_names = {c["consumer_name"] for c in consumers_sequential}
                    self.assertEqual(
                        parallel_names,
                        sequential_names,
                        f"Should find same consumers for {class_name}",
                    )


class TestBackwardsCompatibility(unittest.TestCase):
    """Test that the multiprocessing implementation maintains backwards compatibility."""

    def setUp(self):
        """Set up test environment before each test."""
        self.test_root = Path(__file__).parent.parent.parent.resolve() / "samples"
        self.galaxy_works_project = self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"

    def test_find_consumers_default_params(self):
        """Test that find_consumers works without passing multiprocessing parameters."""

        consumers, _pipeline = scatter.find_consumers(
            target_csproj_path=self.galaxy_works_project,
            search_scope_path=self.test_root,
            target_namespace="GalaxyWorks.Data",
            class_name=None,
            method_name=None,
            # Note: NOT passing max_workers, chunk_size, or disable_multiprocessing
        )

        # Should work and return valid results
        self.assertIsInstance(consumers, list)
        self.assertGreater(len(consumers), 0, "Should find consumers with default params")

        # Validate structure is unchanged
        for consumer in consumers:
            self.assertIn("consumer_path", consumer)
            self.assertIn("consumer_name", consumer)
            self.assertIn("relevant_files", consumer)


if __name__ == "__main__":
    # Configure logging for tests
    import logging

    logging.basicConfig(level=logging.WARNING)  # Reduce noise during tests

    # Run the tests
    unittest.main(verbosity=2)
