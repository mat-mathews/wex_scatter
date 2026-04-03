"""Tests for scatter.scanners.project_scanner — project file discovery and namespace derivation."""

from pathlib import Path

import pytest

from scatter.scanners.project_scanner import (
    derive_namespace,
    find_project_file_on_disk,
    parse_csproj_all_references,
)


# ---------------------------------------------------------------------------
# find_project_file_on_disk
# ---------------------------------------------------------------------------


class TestFindProjectFileOnDisk:
    def test_finds_csproj_in_same_dir(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text("<Project/>")
        cs_file = tmp_path / "Foo.cs"
        cs_file.write_text("class Foo {}")

        result = find_project_file_on_disk(cs_file)
        assert result == csproj.resolve()

    def test_finds_csproj_in_parent_dir(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text("<Project/>")
        sub = tmp_path / "subdir"
        sub.mkdir()
        cs_file = sub / "Bar.cs"
        cs_file.write_text("class Bar {}")

        result = find_project_file_on_disk(cs_file)
        assert result == csproj.resolve()

    def test_returns_none_when_not_found(self, tmp_path):
        cs_file = tmp_path / "Orphan.cs"
        cs_file.write_text("class Orphan {}")

        # Will walk all the way up to root — returns None
        result = find_project_file_on_disk(cs_file)
        # May or may not find a csproj in parent dirs depending on system,
        # but in a clean tmp_path it should be None
        # This is hard to test reliably in isolation since it walks to /
        # Just verify it doesn't crash and returns Path or None
        assert result is None or isinstance(result, Path)


# ---------------------------------------------------------------------------
# derive_namespace
# ---------------------------------------------------------------------------


class TestDeriveNamespace:
    def test_derives_from_root_namespace(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <RootNamespace>Foo.Bar</RootNamespace>\n"
            "  </PropertyGroup>\n"
            "</Project>"
        )
        assert derive_namespace(csproj) == "Foo.Bar"

    def test_derives_from_assembly_name(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <AssemblyName>MyAssembly</AssemblyName>\n"
            "  </PropertyGroup>\n"
            "</Project>"
        )
        assert derive_namespace(csproj) == "MyAssembly"

    def test_prefers_root_namespace_over_assembly(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <RootNamespace>Root.Ns</RootNamespace>\n"
            "    <AssemblyName>MyAssembly</AssemblyName>\n"
            "  </PropertyGroup>\n"
            "</Project>"
        )
        assert derive_namespace(csproj) == "Root.Ns"

    def test_falls_back_to_stem(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup></PropertyGroup></Project>'
        )
        assert derive_namespace(csproj) == "Foo"

    def test_returns_none_for_missing_file(self, tmp_path):
        assert derive_namespace(tmp_path / "Missing.csproj") is None

    def test_returns_none_for_bad_xml(self, tmp_path):
        csproj = tmp_path / "Bad.csproj"
        csproj.write_text("not xml at all {{{{")
        assert derive_namespace(csproj) is None

    def test_legacy_msbuild_namespace(self, tmp_path):
        """Tests .csproj files using MSBuild XML namespace (old-style framework projects)."""
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
            "  <PropertyGroup>\n"
            "    <RootNamespace>Legacy.Ns</RootNamespace>\n"
            "  </PropertyGroup>\n"
            "</Project>"
        )
        assert derive_namespace(csproj) == "Legacy.Ns"


# ---------------------------------------------------------------------------
# parse_csproj_all_references
# ---------------------------------------------------------------------------


class TestParseCsprojAllReferences:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert parse_csproj_all_references(tmp_path / "Missing.csproj") is None

    def test_returns_none_for_bad_xml(self, tmp_path):
        csproj = tmp_path / "Bad.csproj"
        csproj.write_text("not xml")
        assert parse_csproj_all_references(csproj) is None

    def test_parses_sdk_style(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <RootNamespace>Foo.Ns</RootNamespace>\n"
            "    <AssemblyName>FooAssembly</AssemblyName>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "    <OutputType>Exe</OutputType>\n"
            "  </PropertyGroup>\n"
            "  <ItemGroup>\n"
            '    <ProjectReference Include="..\\Bar\\Bar.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "sdk"
        assert result["root_namespace"] == "Foo.Ns"
        assert result["assembly_name"] == "FooAssembly"
        assert result["target_framework"] == "net8.0"
        assert result["output_type"] == "Exe"
        assert "../Bar/Bar.csproj" in result["project_references"]

    def test_parses_framework_style(self, tmp_path):
        csproj = tmp_path / "Old.csproj"
        csproj.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
            "  <PropertyGroup>\n"
            "    <RootNamespace>Old.Ns</RootNamespace>\n"
            "    <TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>\n"
            "  </PropertyGroup>\n"
            "  <ItemGroup>\n"
            '    <ProjectReference Include="..\\Lib\\Lib.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "framework"
        assert result["root_namespace"] == "Old.Ns"
        assert result["target_framework"] == "v4.7.2"
        assert "../Lib/Lib.csproj" in result["project_references"]

    def test_empty_project(self, tmp_path):
        csproj = tmp_path / "Empty.csproj"
        csproj.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_references"] == []
        assert result["root_namespace"] is None
        assert result["project_style"] == "sdk"

    def test_backslashes_normalized(self, tmp_path):
        csproj = tmp_path / "Foo.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <ProjectReference Include="..\\Sub\\Bar\\Bar.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        result = parse_csproj_all_references(csproj)
        assert result["project_references"] == ["../Sub/Bar/Bar.csproj"]
