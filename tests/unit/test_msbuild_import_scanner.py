"""Tests for MSBuild implicit import resolution and explicit import extraction."""

from pathlib import Path
from typing import List

import pytest

from scatter.scanners.msbuild_import_scanner import (
    build_directory_build_index,
    resolve_directory_build_imports,
)
from scatter.scanners.project_scanner import parse_csproj


def _parse_explicit_imports(csproj_path: Path, search_scope: Path) -> List[Path]:
    """Thin wrapper: extract explicit imports via parse_csproj (moved in PR 3)."""
    result = parse_csproj(csproj_path, search_scope=search_scope)
    if result is None:
        return []
    return result["explicit_imports"]


@pytest.fixture
def samples_dir():
    return Path(__file__).parent.parent.parent / "samples"


class TestBuildDirectoryBuildIndex:
    def test_indexes_directory_build_props(self, tmp_path):
        root_props = tmp_path / "Directory.Build.props"
        root_props.write_text("<Project/>")
        custom_props = tmp_path / "build" / "custom.props"
        custom_props.parent.mkdir()
        custom_props.write_text("<Project/>")

        props_index, targets_index = build_directory_build_index(
            [root_props, custom_props], []
        )

        assert tmp_path in props_index
        assert props_index[tmp_path] == root_props
        assert (tmp_path / "build") not in props_index
        assert len(targets_index) == 0

    def test_indexes_directory_build_targets(self, tmp_path):
        root_targets = tmp_path / "Directory.Build.targets"
        root_targets.write_text("<Project/>")

        _, targets_index = build_directory_build_index([], [root_targets])

        assert tmp_path in targets_index

    def test_empty_input(self):
        props_index, targets_index = build_directory_build_index([], [])
        assert len(props_index) == 0
        assert len(targets_index) == 0


class TestResolveDirectoryBuildImports:
    def test_root_props_affects_child_project(self, tmp_path):
        root_props = tmp_path / "Directory.Build.props"
        root_props.write_text("<Project/>")
        project_dir = tmp_path / "src" / "MyProject"
        project_dir.mkdir(parents=True)

        props_index, targets_index = build_directory_build_index([root_props], [])
        result = resolve_directory_build_imports(
            project_dir, props_index, targets_index, tmp_path
        )

        assert root_props in result

    def test_nearest_ancestor_wins(self, tmp_path):
        root_props = tmp_path / "Directory.Build.props"
        root_props.write_text("<Project/>")
        sub_props = tmp_path / "src" / "Directory.Build.props"
        sub_props.parent.mkdir(parents=True)
        sub_props.write_text("<Project/>")
        project_dir = tmp_path / "src" / "MyProject"
        project_dir.mkdir(parents=True)

        props_index, _ = build_directory_build_index([root_props, sub_props], [])
        result = resolve_directory_build_imports(project_dir, props_index, {}, tmp_path)

        assert sub_props in result
        assert root_props not in result

    def test_chaining_includes_parent(self, tmp_path):
        root_props = tmp_path / "Directory.Build.props"
        root_props.write_text("<Project><PropertyGroup><Foo>bar</Foo></PropertyGroup></Project>")
        sub_props = tmp_path / "tests" / "Directory.Build.props"
        sub_props.parent.mkdir(parents=True)
        sub_props.write_text(
            '<Project>\n'
            '  <Import Project="$([MSBuild]::GetPathOfFileAbove(\'Directory.Build.props\', '
            "'$(MSBuildThisFileDirectory)../'))\"/>\n"
            "</Project>"
        )
        project_dir = tmp_path / "tests" / "MyTests"
        project_dir.mkdir(parents=True)

        props_index, _ = build_directory_build_index([root_props, sub_props], [])
        result = resolve_directory_build_imports(project_dir, props_index, {}, tmp_path)

        assert sub_props in result
        assert root_props in result
        assert result.index(sub_props) < result.index(root_props)

    def test_standalone_override_no_chain(self, tmp_path):
        root_props = tmp_path / "Directory.Build.props"
        root_props.write_text("<Project><PropertyGroup><Foo>bar</Foo></PropertyGroup></Project>")
        override_props = tmp_path / "isolated" / "Directory.Build.props"
        override_props.parent.mkdir(parents=True)
        override_props.write_text(
            "<Project><PropertyGroup><TreatWarningsAsErrors>false"
            "</TreatWarningsAsErrors></PropertyGroup></Project>"
        )
        project_dir = tmp_path / "isolated" / "MyProject"
        project_dir.mkdir(parents=True)

        props_index, _ = build_directory_build_index([root_props, override_props], [])
        result = resolve_directory_build_imports(project_dir, props_index, {}, tmp_path)

        assert override_props in result
        assert root_props not in result

    def test_both_props_and_targets(self, tmp_path):
        root_props = tmp_path / "Directory.Build.props"
        root_props.write_text("<Project/>")
        root_targets = tmp_path / "Directory.Build.targets"
        root_targets.write_text("<Project/>")
        project_dir = tmp_path / "MyProject"
        project_dir.mkdir()

        props_index, targets_index = build_directory_build_index(
            [root_props], [root_targets]
        )
        result = resolve_directory_build_imports(
            project_dir, props_index, targets_index, tmp_path
        )

        assert root_props in result
        assert root_targets in result

    def test_no_directory_build_files(self, tmp_path):
        project_dir = tmp_path / "MyProject"
        project_dir.mkdir()

        result = resolve_directory_build_imports(project_dir, {}, {}, tmp_path)
        assert result == []


class TestParseExplicitImports:
    def test_finds_local_props_import(self, tmp_path):
        shared_props = tmp_path / "build" / "wex.common.props"
        shared_props.parent.mkdir()
        shared_props.write_text("<Project/>")
        csproj = tmp_path / "src" / "MyProject" / "MyProject.csproj"
        csproj.parent.mkdir(parents=True)
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <Import Project="..\\..\\build\\wex.common.props" />\n'
            "</Project>"
        )

        result = _parse_explicit_imports(csproj, tmp_path)
        assert len(result) == 1
        assert result[0].name == "wex.common.props"

    def test_filters_system_imports(self, tmp_path):
        csproj = tmp_path / "MyProject.csproj"
        csproj.write_text(
            '<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
            '  <Import Project="$(MSBuildExtensionsPath)\\$(MSBuildToolsVersion)\\Microsoft.Common.props" />\n'
            '  <Import Project="$(MSBuildBinPath)\\Microsoft.CSharp.targets" />\n'
            '  <Import Project="$(VSToolsPath)\\WebApplications\\Microsoft.WebApplication.targets" />\n'
            "</Project>"
        )

        result = _parse_explicit_imports(csproj, tmp_path)
        assert result == []

    def test_skips_unresolvable_variables(self, tmp_path):
        csproj = tmp_path / "MyProject.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <Import Project="$(SomeCustomVar)\\thing.props" />\n'
            "</Project>"
        )

        result = _parse_explicit_imports(csproj, tmp_path)
        assert result == []

    def test_skips_nonexistent_import(self, tmp_path):
        csproj = tmp_path / "MyProject.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <Import Project="..\\missing.props" />\n'
            "</Project>"
        )

        result = _parse_explicit_imports(csproj, tmp_path)
        assert result == []

    def test_skips_directory_build_files(self, tmp_path):
        """Explicit <Import> of Directory.Build.props is handled by the ancestor
        walk, not by explicit import extraction — avoid double-counting."""
        db_props = tmp_path / "Directory.Build.props"
        db_props.write_text("<Project/>")
        csproj = tmp_path / "sub" / "MyProject.csproj"
        csproj.parent.mkdir()
        csproj.write_text(
            '<Project>\n'
            '  <Import Project="..\\Directory.Build.props" />\n'
            "</Project>"
        )

        result = _parse_explicit_imports(csproj, tmp_path)
        assert result == []

    def test_handles_malformed_csproj(self, tmp_path):
        csproj = tmp_path / "Bad.csproj"
        csproj.write_text("this is not xml at all")

        result = _parse_explicit_imports(csproj, tmp_path)
        assert result == []


class TestSamplesIntegration:
    """Integration tests against the enriched samples/ directory."""

    def test_root_props_affects_most_projects(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        all_props = list(samples_dir.rglob("*.props"))
        all_targets = list(samples_dir.rglob("*.targets"))
        props_index, targets_index = build_directory_build_index(all_props, all_targets)

        csproj_files = list(samples_dir.rglob("*.csproj"))
        assert len(csproj_files) >= 13

        root_props = samples_dir / "Directory.Build.props"
        assert root_props.exists()

        affected = []
        not_affected = []
        for csproj in csproj_files:
            imports = resolve_directory_build_imports(
                csproj.parent, props_index, targets_index, samples_dir
            )
            import_paths = {p.resolve() for p in imports}
            if root_props.resolve() in import_paths:
                affected.append(csproj.stem)
            else:
                not_affected.append(csproj.stem)

        assert "MyDotNetApp2.Exclude" in not_affected
        assert len(affected) >= 11

    def test_exclude_project_gets_own_props_only(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        all_props = list(samples_dir.rglob("*.props"))
        props_index, _ = build_directory_build_index(all_props, [])

        exclude_dir = samples_dir / "MyDotNetApp2.Exclude"
        result = resolve_directory_build_imports(exclude_dir, props_index, {}, samples_dir)

        assert len(result) == 1
        assert result[0].name == "Directory.Build.props"
        assert result[0].parent.name == "MyDotNetApp2.Exclude"

    def test_data_tests_chains_to_root(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        all_props = list(samples_dir.rglob("*.props"))
        props_index, _ = build_directory_build_index(all_props, [])

        tests_dir = samples_dir / "GalaxyWorks.Data.Tests"
        result = resolve_directory_build_imports(tests_dir, props_index, {}, samples_dir)

        props_names = [(p.parent.name, p.name) for p in result]
        assert len(result) == 2
        assert result[0].parent.name == "GalaxyWorks.Data.Tests"
        assert result[1].parent == samples_dir

    def test_explicit_import_wex_common_props(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        api_csproj = samples_dir / "GalaxyWorks.Api" / "GalaxyWorks.Api.csproj"
        notifications_csproj = (
            samples_dir / "GalaxyWorks.Notifications" / "GalaxyWorks.Notifications.csproj"
        )
        data_csproj = samples_dir / "GalaxyWorks.Data" / "GalaxyWorks.Data.csproj"

        api_imports = _parse_explicit_imports(api_csproj, samples_dir)
        notif_imports = _parse_explicit_imports(notifications_csproj, samples_dir)
        data_imports = _parse_explicit_imports(data_csproj, samples_dir)

        assert any(p.name == "wex.common.props" for p in api_imports)
        assert any(p.name == "wex.common.props" for p in notif_imports)
        assert not any(p.name == "wex.common.props" for p in data_imports)

    def test_system_imports_filtered_from_legacy_projects(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        portal_csproj = samples_dir / "GalaxyWorks.WebPortal" / "GalaxyWorks.WebPortal.csproj"
        result = _parse_explicit_imports(portal_csproj, samples_dir)

        for imp in result:
            assert "Microsoft.Common.props" not in str(imp)
            assert "Microsoft.CSharp.targets" not in str(imp)
            assert "Microsoft.WebApplication.targets" not in str(imp)

    def test_orphaned_props_no_phantom_edges(self, samples_dir):
        """A .props file that no project imports should not produce results."""
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        all_props = list(samples_dir.rglob("*.props"))
        props_index, _ = build_directory_build_index(all_props, [])

        # wex.common.props lives in build/ — it's not a Directory.Build.props
        # so it won't appear in the directory build index
        assert (samples_dir / "build") not in props_index
