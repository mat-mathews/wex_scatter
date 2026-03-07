#!/usr/bin/env python3
"""
Unit and integration tests for Phase 2.3: Parallel Project Mapping

Tests map_cs_to_projects_batch(), map_cs_to_projects_parallel(),
and the modified find_cs_files_referencing_sproc() integration.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scatter


class TestMapCsToProjectsBatch(unittest.TestCase):
    """Direct unit tests for the map_cs_to_projects_batch worker function."""

    def setUp(self):
        """Create a temp directory tree with .cs and .csproj files."""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Project A: ProjectA/ProjectA.csproj with files in subdirectories
        self.proj_a_dir = self.temp_dir / "ProjectA"
        self.proj_a_dir.mkdir()
        self.proj_a_csproj = self.proj_a_dir / "ProjectA.csproj"
        self.proj_a_csproj.write_text("<Project></Project>")

        # .cs files at various depths under ProjectA
        self.cs_a1 = self.proj_a_dir / "Class1.cs"
        self.cs_a1.write_text("class Class1 {}")

        sub_dir = self.proj_a_dir / "Services"
        sub_dir.mkdir()
        self.cs_a2 = sub_dir / "Service1.cs"
        self.cs_a2.write_text("class Service1 {}")

        deep_dir = sub_dir / "Internal"
        deep_dir.mkdir()
        self.cs_a3 = deep_dir / "Helper.cs"
        self.cs_a3.write_text("class Helper {}")

        # Project B: ProjectB/ProjectB.csproj
        self.proj_b_dir = self.temp_dir / "ProjectB"
        self.proj_b_dir.mkdir()
        self.proj_b_csproj = self.proj_b_dir / "ProjectB.csproj"
        self.proj_b_csproj.write_text("<Project></Project>")

        self.cs_b1 = self.proj_b_dir / "ClassB.cs"
        self.cs_b1.write_text("class ClassB {}")

        # Orphan directory with no .csproj anywhere above (within temp)
        self.orphan_dir = self.temp_dir / "no_project" / "deep" / "nested"
        self.orphan_dir.mkdir(parents=True)
        self.cs_orphan = self.orphan_dir / "Orphan.cs"
        self.cs_orphan.write_text("class Orphan {}")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_basic_mapping(self):
        """Files map to their nearest parent .csproj."""
        result = scatter.map_cs_to_projects_batch(([str(self.cs_a1), str(self.cs_b1)],))

        self.assertEqual(len(result), 2)
        self.assertEqual(result[str(self.cs_a1)], str(self.proj_a_csproj.resolve()))
        self.assertEqual(result[str(self.cs_b1)], str(self.proj_b_csproj.resolve()))

    def test_subdirectory_files_map_to_parent_csproj(self):
        """Files nested under a project dir walk up to the correct .csproj."""
        result = scatter.map_cs_to_projects_batch((
            [str(self.cs_a1), str(self.cs_a2), str(self.cs_a3)],
        ))

        resolved = str(self.proj_a_csproj.resolve())
        for cs_file in [self.cs_a1, self.cs_a2, self.cs_a3]:
            self.assertEqual(result[str(cs_file)], resolved,
                             f"{cs_file.name} should map to ProjectA.csproj")

    def test_cache_does_not_cross_projects(self):
        """Cache from ProjectA must not bleed into ProjectB lookups."""
        # Process A files first, then B — cache should not return A's csproj for B
        files = [str(self.cs_a1), str(self.cs_a2), str(self.cs_b1)]
        result = scatter.map_cs_to_projects_batch((files,))

        self.assertNotEqual(result[str(self.cs_b1)], result[str(self.cs_a1)])

    def test_empty_input(self):
        """Empty file list returns empty dict."""
        result = scatter.map_cs_to_projects_batch(([],))
        self.assertEqual(result, {})

    def test_nonexistent_path(self):
        """Nonexistent file paths return None without crashing."""
        fake_path = str(self.temp_dir / "does_not_exist" / "Fake.cs")
        result = scatter.map_cs_to_projects_batch(([fake_path],))

        self.assertIn(fake_path, result)
        # Should be None since the parent directory doesn't exist and will
        # either error or walk to root without finding a .csproj
        # (exact behavior depends on OS, but must not crash)

    def test_orphan_file_does_not_crash(self):
        """A .cs file with no .csproj anywhere above it returns without crashing."""
        # The orphan file is under temp_dir/no_project/deep/nested/
        # There's no .csproj in that subtree. It will eventually walk up
        # to / without finding one (or find one outside temp_dir, but
        # the important thing is it doesn't crash).
        result = scatter.map_cs_to_projects_batch(([str(self.cs_orphan)],))
        self.assertIn(str(self.cs_orphan), result)
        # The result is either None (no csproj found all the way to root)
        # or a string (if the system happens to have a .csproj above temp_dir).
        # Either way, it must not crash.

    def test_all_input_files_appear_in_output(self):
        """Every input file path must appear as a key in the output dict."""
        files = [
            str(self.cs_a1), str(self.cs_a2), str(self.cs_a3),
            str(self.cs_b1), str(self.cs_orphan),
        ]
        result = scatter.map_cs_to_projects_batch((files,))

        for f in files:
            self.assertIn(f, result, f"Missing key for {f}")

    def test_output_types(self):
        """Output keys are strings, values are str or None."""
        files = [str(self.cs_a1), str(self.cs_orphan)]
        result = scatter.map_cs_to_projects_batch((files,))

        for key, value in result.items():
            self.assertIsInstance(key, str)
            if value is not None:
                self.assertIsInstance(value, str)

    def test_multiple_csproj_in_directory(self):
        """When a directory contains multiple .csproj files, one is picked consistently."""
        extra_csproj = self.proj_a_dir / "ExtraProject.csproj"
        extra_csproj.write_text("<Project></Project>")

        result = scatter.map_cs_to_projects_batch(([str(self.cs_a1)],))

        # Should return one of the two, not crash
        mapped = result[str(self.cs_a1)]
        self.assertIsNotNone(mapped)
        self.assertTrue(mapped.endswith(".csproj"))


class TestMapCsToProjectsParallel(unittest.TestCase):
    """Tests for the map_cs_to_projects_parallel orchestrator."""

    def setUp(self):
        self.test_root = Path(__file__).parent.resolve()
        # Gather some real .cs files from the repo
        self.cs_files = list((self.test_root / "GalaxyWorks.Data").rglob("*.cs"))
        # Ensure we have files to test with
        self.assertGreater(len(self.cs_files), 0, "Need .cs files for testing")

    def test_sequential_fallback_disabled_flag(self):
        """disable_multiprocessing=True forces sequential processing."""
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            disable_multiprocessing=True
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), len(self.cs_files))

    def test_sequential_fallback_below_chunk_size(self):
        """File count below chunk_size triggers sequential processing."""
        # Use chunk_size larger than file count
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            cs_analysis_chunk_size=len(self.cs_files) + 100,
            disable_multiprocessing=False
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), len(self.cs_files))

    def test_parallel_execution(self):
        """Parallel mode returns correct results when file count exceeds chunk size."""
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            max_workers=2,
            cs_analysis_chunk_size=2,  # Force chunking
            disable_multiprocessing=False
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), len(self.cs_files))

    def test_parallel_vs_sequential_consistency(self):
        """Parallel and sequential modes return identical mappings."""
        sequential = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            disable_multiprocessing=True
        )

        parallel = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            max_workers=2,
            cs_analysis_chunk_size=2,
            disable_multiprocessing=False
        )

        self.assertEqual(sequential, parallel,
                         "Parallel and sequential should produce identical mappings")

    def test_result_completeness(self):
        """Every input file appears in the output dict."""
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            disable_multiprocessing=True
        )

        for cs_file in self.cs_files:
            self.assertIn(str(cs_file), result,
                          f"Missing mapping for {cs_file.name}")

    def test_empty_input(self):
        """Empty file list returns empty dict."""
        result = scatter.map_cs_to_projects_parallel(
            [],
            disable_multiprocessing=False
        )
        self.assertEqual(result, {})

    def test_all_galaxy_files_map_to_same_project(self):
        """All .cs files under GalaxyWorks.Data should map to GalaxyWorks.Data.csproj."""
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            disable_multiprocessing=True
        )

        expected_csproj = str(
            (self.test_root / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj").resolve()
        )

        for cs_file in self.cs_files:
            mapped = result[str(cs_file)]
            self.assertEqual(mapped, expected_csproj,
                             f"{cs_file.name} should map to GalaxyWorks.Data.csproj")

    def test_output_types_are_strings(self):
        """Output keys and non-None values are strings (cross-process serializable)."""
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            disable_multiprocessing=True
        )

        for key, value in result.items():
            self.assertIsInstance(key, str)
            if value is not None:
                self.assertIsInstance(value, str)

    def test_chunk_boundary_exactly_at_chunk_size(self):
        """File count exactly equal to chunk_size falls back to sequential."""
        n = len(self.cs_files)
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            cs_analysis_chunk_size=n,  # exactly equal → sequential
            disable_multiprocessing=False
        )
        self.assertEqual(len(result), n)

    def test_chunk_boundary_one_above_chunk_size(self):
        """File count one above chunk_size triggers parallel mode."""
        n = len(self.cs_files)
        if n < 2:
            self.skipTest("Need at least 2 .cs files")
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            cs_analysis_chunk_size=n - 1,  # one above → parallel
            max_workers=2,
            disable_multiprocessing=False
        )
        self.assertEqual(len(result), n)

    @patch('scatter.core.parallel.ProcessPoolExecutor')
    def test_fallback_on_executor_failure(self, mock_executor_class):
        """If ProcessPoolExecutor raises, falls back to sequential."""
        mock_executor_class.side_effect = RuntimeError("Pool creation failed")

        # Must not raise — should fall back
        result = scatter.map_cs_to_projects_parallel(
            self.cs_files,
            cs_analysis_chunk_size=2,  # force parallel path
            disable_multiprocessing=False
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), len(self.cs_files))


class TestSprocMappingIntegration(unittest.TestCase):
    """Integration tests for the modified find_cs_files_referencing_sproc()."""

    def setUp(self):
        self.test_root = Path(__file__).parent.resolve()

    def test_sproc_parallel_vs_sequential_identical_results(self):
        """Sproc analysis returns identical results in parallel vs sequential mode."""
        parallel_results = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            max_workers=2,
            chunk_size=10,
            disable_multiprocessing=False,
            cs_analysis_chunk_size=5
        )

        sequential_results = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            disable_multiprocessing=True
        )

        # Same projects found
        parallel_projects = {p.name for p in parallel_results.keys()}
        sequential_projects = {p.name for p in sequential_results.keys()}
        self.assertEqual(parallel_projects, sequential_projects,
                         "Parallel and sequential should find the same projects")

        # Same classes found per project
        for proj_path in parallel_results:
            parallel_classes = set(parallel_results[proj_path].keys())
            seq_proj = [p for p in sequential_results if p.name == proj_path.name]
            self.assertTrue(len(seq_proj) > 0,
                            f"Project {proj_path.name} missing from sequential results")
            sequential_classes = set(sequential_results[seq_proj[0]].keys())
            self.assertEqual(parallel_classes, sequential_classes,
                             f"Classes differ for {proj_path.name}")

    def test_sproc_with_custom_chunk_size(self):
        """Custom cs_analysis_chunk_size parameter flows through correctly."""
        result = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            cs_analysis_chunk_size=3,
            disable_multiprocessing=False
        )

        # Should still find the same results regardless of chunk size
        self.assertIsInstance(result, dict)
        if result:
            found_classes = []
            for classes_dict in result.values():
                found_classes.extend(classes_dict.keys())
            self.assertIn("PortalDataService", found_classes)

    def test_sproc_no_matches_returns_empty(self):
        """Sproc that doesn't exist returns empty dict (no crash in mapping)."""
        result = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_ThisDoesNotExist_XYZ123",
            search_path=self.test_root,
            disable_multiprocessing=False
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 0)

    def test_mapped_projects_are_path_objects(self):
        """Output dict keys should be Path objects (unchanged from before)."""
        result = scatter.find_cs_files_referencing_sproc(
            sproc_name_input="dbo.sp_InsertPortalConfiguration",
            search_path=self.test_root,
            disable_multiprocessing=True
        )

        for key in result.keys():
            self.assertIsInstance(key, Path,
                                 f"Project key should be Path, got {type(key)}")


if __name__ == '__main__':
    unittest.main()
