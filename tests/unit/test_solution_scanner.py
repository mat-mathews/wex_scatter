"""Tests for scatter/scanners/solution_scanner.py"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from scatter.scanners.solution_scanner import (
    SolutionInfo,
    parse_solution_file,
    scan_solutions,
    build_project_to_solutions,
)

# --- Fixtures: .sln content strings ---

SLN_HEADER = "Microsoft Visual Studio Solution File, Format Version 12.00\n"

SLN_THREE_CSHARP = (
    SLN_HEADER
    + "# Visual Studio Version 17\n"
    + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Alpha", "Alpha\\Alpha.csproj", "{AAAA}"\n'
    + "EndProject\n"
    + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Beta", "libs\\Beta\\Beta.csproj", "{BBBB}"\n'
    + "EndProject\n"
    + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Gamma", "Gamma/Gamma.csproj", "{CCCC}"\n'
    + "EndProject\n"
)

SLN_SDK_STYLE = (
    SLN_HEADER
    + 'Project("{9A19103F-16F7-4668-BE54-9A1E7A4F7556}") = "SdkProject", "SdkProject\\SdkProject.csproj", "{DDDD}"\n'
    + "EndProject\n"
)

SLN_MIXED_TYPES = (
    SLN_HEADER
    + "# C# project\n"
    + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "CSharp", "CSharp\\CSharp.csproj", "{1111}"\n'
    + "EndProject\n"
    + "# Solution Folder\n"
    + 'Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "Solution Items", "Solution Items", "{2222}"\n'
    + "EndProject\n"
    + "# VB.NET project\n"
    + 'Project("{F184B08F-C81C-45F6-A57F-5ABD9991F28F}") = "VBProject", "VBProject\\VBProject.vbproj", "{3333}"\n'
    + "EndProject\n"
    + "# F# project\n"
    + 'Project("{F2A71F9B-5D33-465A-A702-920D77279786}") = "FSharp", "FSharp\\FSharp.fsproj", "{4444}"\n'
    + "EndProject\n"
)

SLN_DUPLICATE = (
    SLN_HEADER
    + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Dup", "Dup\\Dup.csproj", "{AAAA}"\n'
    + "EndProject\n"
    + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Dup", "Dup\\Dup.csproj", "{BBBB}"\n'
    + "EndProject\n"
)

SLN_EMPTY_VALID = SLN_HEADER + "Global\nEndGlobal\n"


# --- Helpers ---


def _write_sln(tmp_path: Path, content: str, name: str = "Test.sln") -> Path:
    sln = tmp_path / name
    sln.write_text(content, encoding="utf-8")
    return sln


# === Parsing Tests ===


class TestParseSolutionFile:
    def test_parse_csharp_projects(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_THREE_CSHARP)
        info = parse_solution_file(sln)

        assert info.name == "Test"
        assert info.path == sln.resolve()
        assert info.project_entries == ["Alpha", "Beta", "Gamma"]
        assert len(info.project_paths) == 3

    def test_parse_sdk_style_guid(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_SDK_STYLE)
        info = parse_solution_file(sln)

        assert info.project_entries == ["SdkProject"]
        assert len(info.project_paths) == 1

    def test_parse_skips_solution_folders(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_MIXED_TYPES)
        info = parse_solution_file(sln)

        assert info.project_entries == ["CSharp"]
        assert len(info.project_paths) == 1

    def test_parse_skips_non_csharp(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_MIXED_TYPES)
        info = parse_solution_file(sln)

        names = info.project_entries
        assert "VBProject" not in names
        assert "FSharp" not in names
        assert "Solution Items" not in names

    def test_parse_backslash_paths_resolved(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_THREE_CSHARP)
        info = parse_solution_file(sln)

        # Alpha uses backslash path Alpha\Alpha.csproj
        alpha_path = info.project_paths[0]
        assert alpha_path.is_absolute()
        assert alpha_path == (tmp_path / "Alpha" / "Alpha.csproj").resolve()

    def test_parse_forward_slash_paths_resolved(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_THREE_CSHARP)
        info = parse_solution_file(sln)

        # Gamma uses forward slash path Gamma/Gamma.csproj
        gamma_path = info.project_paths[2]
        assert gamma_path.is_absolute()
        assert gamma_path == (tmp_path / "Gamma" / "Gamma.csproj").resolve()

    def test_parse_with_bom(self, tmp_path):
        sln = tmp_path / "Bom.sln"
        # Write with BOM bytes directly
        sln.write_bytes(b"\xef\xbb\xbf" + SLN_THREE_CSHARP.encode("utf-8"))
        info = parse_solution_file(sln)

        assert len(info.project_entries) == 3

    def test_parse_deduplicates(self, tmp_path, caplog):
        sln = _write_sln(tmp_path, SLN_DUPLICATE)

        with caplog.at_level(logging.WARNING):
            info = parse_solution_file(sln)

        assert len(info.project_entries) == 1
        assert "duplicate" in caplog.text.lower()

    def test_parse_empty_valid_sln(self, tmp_path, caplog):
        sln = _write_sln(tmp_path, SLN_EMPTY_VALID)

        with caplog.at_level(logging.WARNING):
            info = parse_solution_file(sln)

        assert info.project_entries == []
        assert info.project_paths == []
        # Valid empty solution — no warning about unrecognized format
        assert "does not appear to be a valid" not in caplog.text

    def test_parse_unrecognized_format(self, tmp_path, caplog):
        sln = _write_sln(tmp_path, "This is not a solution file.\nJust garbage.\n")

        with caplog.at_level(logging.WARNING):
            info = parse_solution_file(sln)

        assert info.project_entries == []
        assert "does not appear to be a valid" in caplog.text

    def test_parse_malformed_sln(self, tmp_path, caplog):
        # Has header but mangled Project lines
        content = SLN_HEADER + "Project(broken line\nmore garbage\n"
        sln = _write_sln(tmp_path, content)

        with caplog.at_level(logging.WARNING):
            info = parse_solution_file(sln)

        assert info.project_entries == []
        # No crash, no unrecognized-format warning (it has the header)
        assert "does not appear to be a valid" not in caplog.text

    def test_parse_unreadable_file(self, tmp_path, caplog):
        sln = tmp_path / "Missing.sln"
        # Don't create the file

        with caplog.at_level(logging.WARNING):
            info = parse_solution_file(sln)

        assert info.project_entries == []
        assert "could not read" in caplog.text.lower()


# === Scanning Tests ===


class TestScanSolutions:
    def test_scan_real_repo(self):
        """Integration test against the actual GalaxyWorks.sln in the repo."""
        repo_root = Path(__file__).parent.parent.parent
        solutions = scan_solutions(repo_root)

        names = [s.name for s in solutions]
        assert "GalaxyWorks" in names

        gw = next(s for s in solutions if s.name == "GalaxyWorks")
        # 12 C# projects, excluding "Solution Items" folder
        assert len(gw.project_entries) == 12
        assert "GalaxyWorks.Data" in gw.project_entries
        assert "GalaxyWorks.WebPortal" in gw.project_entries

    def test_scan_sorted(self, tmp_path):
        _write_sln(tmp_path, SLN_THREE_CSHARP, "Zebra.sln")
        _write_sln(tmp_path, SLN_SDK_STYLE, "Alpha.sln")

        solutions = scan_solutions(tmp_path)
        names = [s.name for s in solutions]
        assert names == sorted(names)

    def test_scan_empty_dir(self, tmp_path):
        solutions = scan_solutions(tmp_path)
        assert solutions == []


# === Reverse Index Tests ===


class TestBuildProjectToSolutions:
    def test_reverse_index_basic(self, tmp_path):
        sln = _write_sln(tmp_path, SLN_THREE_CSHARP)
        info = parse_solution_file(sln)

        index = build_project_to_solutions([info])

        assert "Alpha" in index
        assert "Beta" in index
        assert "Gamma" in index
        assert index["Alpha"][0].name == "Test"

    def test_reverse_index_multi_solution(self, tmp_path):
        sln_a = _write_sln(tmp_path, SLN_THREE_CSHARP, "First.sln")
        # Second solution also contains Alpha
        sln_b_content = (
            SLN_HEADER
            + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Alpha", "Alpha\\Alpha.csproj", "{XXXX}"\n'
            + "EndProject\n"
        )
        sln_b = _write_sln(tmp_path, sln_b_content, "Second.sln")

        info_a = parse_solution_file(sln_a)
        info_b = parse_solution_file(sln_b)
        index = build_project_to_solutions([info_a, info_b])

        assert len(index["Alpha"]) == 2
        sol_names = {si.name for si in index["Alpha"]}
        assert sol_names == {"First", "Second"}

    def test_reverse_index_stem_collision(self, tmp_path, caplog):
        # Two different paths with the same stem
        sub_a = tmp_path / "dir_a"
        sub_b = tmp_path / "dir_b"
        sub_a.mkdir()
        sub_b.mkdir()

        sln_a_content = (
            SLN_HEADER
            + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Utils", "dir_a\\Utils.csproj", "{AAAA}"\n'
            + "EndProject\n"
        )
        sln_b_content = (
            SLN_HEADER
            + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Utils", "dir_b\\Utils.csproj", "{BBBB}"\n'
            + "EndProject\n"
        )
        sln_a = _write_sln(tmp_path, sln_a_content, "A.sln")
        sln_b = _write_sln(tmp_path, sln_b_content, "B.sln")

        info_a = parse_solution_file(sln_a)
        info_b = parse_solution_file(sln_b)

        with caplog.at_level(logging.WARNING):
            index = build_project_to_solutions([info_a, info_b])

        # Both indexed under same stem
        assert len(index["Utils"]) == 2
        assert "stem collision" in caplog.text.lower()


# === Migration Tests ===


class TestMigration:
    def test_migration_with_index(self, tmp_path):
        """find_solutions_for_project uses index when provided."""
        from scatter.compat.v1_bridge import find_solutions_for_project

        sln = _write_sln(tmp_path, SLN_THREE_CSHARP)
        info = parse_solution_file(sln)
        index = build_project_to_solutions([info])

        csproj = tmp_path / "Alpha" / "Alpha.csproj"
        result = find_solutions_for_project(csproj, solution_cache=[], solution_index=index)

        assert len(result) == 1
        assert result[0] == sln.resolve()

    def test_migration_fallback(self, tmp_path):
        """find_solutions_for_project falls back to text search without index."""
        from scatter.compat.v1_bridge import find_solutions_for_project

        sln = _write_sln(tmp_path, SLN_THREE_CSHARP)
        csproj = tmp_path / "Alpha" / "Alpha.csproj"

        result = find_solutions_for_project(csproj, solution_cache=[sln])

        assert len(result) == 1
        assert result[0] == sln

    def test_no_false_positive_substring(self, tmp_path):
        """Index lookup by stem prevents substring false matches."""
        from scatter.compat.v1_bridge import find_solutions_for_project

        content = (
            SLN_HEADER
            + 'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "MyAuth.Core", "MyAuth.Core\\MyAuth.Core.csproj", "{AAAA}"\n'
            + "EndProject\n"
        )
        sln = _write_sln(tmp_path, content)
        info = parse_solution_file(sln)
        index = build_project_to_solutions([info])

        # "Auth.Core" should NOT match "MyAuth.Core" via index
        csproj = tmp_path / "Auth.Core" / "Auth.Core.csproj"
        result = find_solutions_for_project(csproj, solution_cache=[], solution_index=index)

        assert result == []
