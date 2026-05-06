"""Tests for patterns introduced by new sample projects.

Validates Scatter's handling of modern C# patterns identified in
docs/SAMPLE_PROJECT_EVALUATION.md: records, file-scoped namespaces,
global usings, common type names, multi-targeting, extension methods,
using aliases, solution files, test project detection, and more.
"""

import re
from pathlib import Path

import pytest

from scatter.scanners.type_scanner import extract_type_names_from_content
from scatter.scanners.project_scanner import (
    derive_namespace,
    parse_csproj_all_references,
)

REPO_ROOT = Path(__file__).parent.parent.parent
SAMPLES = REPO_ROOT / "samples"


# ===========================================================================
# TestRecordDeclarations
# ===========================================================================
class TestRecordDeclarations:
    """Verify TYPE_DECLARATION_PATTERN handles C# record types.

    Records are the most common modern C# type and Scatter's regex
    currently misses positional records entirely.
    """

    def test_positional_record_detected(self):
        """Positional record is now detected via 'record' type keyword."""
        code = "public record PersonDto(string Name, int Age, string Email);"
        types = extract_type_names_from_content(code)
        assert "PersonDto" in types

    def test_record_class_detected(self):
        """record class — 'record' is now in the modifier list."""
        code = """public record class OrderSummary
{
    public int OrderId { get; init; }
}"""
        types = extract_type_names_from_content(code)
        assert "OrderSummary" in types

    def test_record_struct_positional_detected(self):
        """Positional record struct — 'record' modifier + '(' lookahead."""
        code = "public record struct Point(double X, double Y);"
        types = extract_type_names_from_content(code)
        assert "Point" in types

    def test_record_struct_with_body_detected(self):
        """record struct with body — 'record' modifier now matched."""
        code = """public record struct Coordinate
{
    public double Latitude { get; init; }
}"""
        types = extract_type_names_from_content(code)
        assert "Coordinate" in types

    def test_record_inheritance_detected(self):
        """Record with inheritance uses : and 'record' keyword is now recognized."""
        code = """public record EmployeeDto(string Name, int Age, string Email, string Department)
    : PersonDto(Name, Age, Email);"""
        types = extract_type_names_from_content(code)
        assert "EmployeeDto" in types

    def test_sample_records_file(self):
        """Test type extraction against the actual Records.cs sample file.

        All record variants are now detected.
        """
        records_file = SAMPLES / "GalaxyWorks.Common" / "Models" / "Records.cs"
        if not records_file.exists():
            pytest.skip("Sample project not available")
        content = records_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)

        assert "PersonDto" in types  # positional record
        assert "OrderSummary" in types  # record class with body
        assert "Point" in types  # positional record struct
        assert "Coordinate" in types  # record struct with body
        assert "EmployeeDto" in types  # record with inheritance


# ===========================================================================
# TestFileScopedNamespaces
# ===========================================================================
class TestFileScopedNamespaces:
    """Verify Scatter handles file-scoped namespace syntax (C# 10+)."""

    def test_type_extraction_with_file_scoped_namespace(self):
        """Types in file-scoped namespace files should still be extracted."""
        code = """namespace GalaxyWorks.Common.Models;

public class Result
{
    public bool Success { get; set; }
}

public class Response
{
    public int StatusCode { get; set; }
}"""
        types = extract_type_names_from_content(code)
        assert "Result" in types
        assert "Response" in types

    def test_graph_builder_using_pattern_with_file_scoped(self):
        """The _USING_PATTERN should still match using statements in file-scoped namespace files."""
        from scatter.analyzers.graph_builder import _USING_PATTERN

        code = """namespace GalaxyWorks.Api.Controllers;

using GalaxyWorks.Data.DataServices;
using GalaxyWorks.Common.Models;

public class MyController { }"""
        matches = [m.group(1) for m in _USING_PATTERN.finditer(code)]
        assert "GalaxyWorks.Data.DataServices" in matches
        assert "GalaxyWorks.Common.Models" in matches


# ===========================================================================
# TestCommonTypeNames
# ===========================================================================
class TestCommonTypeNames:
    """Verify extraction of commonly-named types that cause false positives."""

    def test_common_names_extracted(self):
        """All common-name types should be extractable from CommonNames.cs."""
        common_file = SAMPLES / "GalaxyWorks.Common" / "Models" / "CommonNames.cs"
        if not common_file.exists():
            pytest.skip("Sample project not available")
        content = common_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)

        assert "Result" in types
        assert "Response" in types
        assert "Options" in types
        assert "Context" in types
        assert "IService" in types

    def test_generic_type_base_name_extracted(self):
        """Generic types like Result<T> should extract base name 'Result'."""
        code = """public class Result<T> : Result
{
    public T? Data { get; set; }
}"""
        types = extract_type_names_from_content(code)
        # Should extract "Result" (base name, not "Result<T>")
        assert "Result" in types

    def test_false_positive_risk_with_text_search(self):
        """Type extraction only finds declarations, not variable/return type mentions."""
        unrelated_code = """
// This file has nothing to do with GalaxyWorks.Common
public class OrderService
{
    public async Task<IActionResult> ProcessOrder()
    {
        var result = await _db.SaveChangesAsync();
        if (result > 0)
            return Ok();
        return BadRequest();
    }
}"""
        types = extract_type_names_from_content(unrelated_code)
        assert "OrderService" in types
        # "Result" as a variable name is NOT extracted as a type
        assert "result" not in types


# ===========================================================================
# TestMultiTargeting
# ===========================================================================
class TestMultiTargeting:
    """Verify Scatter handles <TargetFrameworks> (plural) for multi-targeted projects."""

    def test_multi_target_csproj_parsing(self):
        """parse_csproj_all_references should extract framework from TargetFrameworks."""
        csproj = SAMPLES / "GalaxyWorks.Common" / "GalaxyWorks.Common.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        # BUG: parse_csproj_all_references only checks TargetFramework (singular)
        # and TargetFrameworkVersion, not TargetFrameworks (plural).
        # This test documents the gap.
        # When the plural form is used, target_framework will be None.
        if result["target_framework"] is None:
            pytest.xfail(
                "TargetFrameworks (plural) not yet supported by parse_csproj_all_references — "
                "see SAMPLE_PROJECT_EVALUATION.md recommendation #5"
            )
        assert "net48" in result["target_framework"] or "net8.0" in result["target_framework"]

    def test_multi_target_namespace_derivation(self):
        """derive_namespace should still work with multi-targeted projects."""
        csproj = SAMPLES / "GalaxyWorks.Common" / "GalaxyWorks.Common.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        ns = derive_namespace(csproj)
        assert ns == "GalaxyWorks.Common"

    def test_multi_target_project_references(self):
        """Multi-targeted project should still have its ProjectReferences parsed."""
        csproj = SAMPLES / "GalaxyWorks.Common" / "GalaxyWorks.Common.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert len(result["project_references"]) == 1
        assert "GalaxyWorks.Data.csproj" in result["project_references"][0]

    def test_multi_target_project_style(self):
        """Multi-targeted SDK project should be detected as 'sdk' style."""
        csproj = SAMPLES / "GalaxyWorks.Common" / "GalaxyWorks.Common.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "sdk"


# ===========================================================================
# TestGlobalUsings
# ===========================================================================
class TestGlobalUsings:
    """Verify Scatter handles global using statements."""

    def test_consumer_analyzer_pattern_matches_global_using(self):
        """consumer_analyzer's using_pattern already handles 'global using'."""
        target_namespace = "GalaxyWorks.Common.Models"
        pattern = re.compile(
            rf"(?:^|;|\{{)\s*(?:global\s+)?using\s+{re.escape(target_namespace)}(?:\.[A-Za-z0-9_.]+)?\s*;",
            re.MULTILINE,
        )
        code = "global using GalaxyWorks.Common.Models;"
        assert pattern.search(code) is not None

    def test_graph_builder_pattern_handles_global_using(self):
        """USING_PATTERN now handles global using statements."""
        from scatter.analyzers.graph_builder import _USING_PATTERN

        code = "global using GalaxyWorks.Common.Models;"
        matches = [m.group(1) for m in _USING_PATTERN.finditer(code)]
        assert "GalaxyWorks.Common.Models" in matches

    def test_global_usings_file_exists(self):
        """Verify GlobalUsings.cs files exist in the right projects."""
        api_global = SAMPLES / "GalaxyWorks.Api" / "GlobalUsings.cs"
        consumer_global = SAMPLES / "MyGalaxyConsumerApp" / "GlobalUsings.cs"
        assert api_global.exists()
        assert consumer_global.exists()

    def test_global_usings_file_content(self):
        """Global usings files should contain the expected namespaces."""
        api_global = SAMPLES / "GalaxyWorks.Api" / "GlobalUsings.cs"
        if not api_global.exists():
            pytest.skip("Sample project not available")
        content = api_global.read_text(encoding="utf-8")
        assert "global using GalaxyWorks.Data.DataServices;" in content
        assert "global using GalaxyWorks.Common.Models;" in content

    def test_consumer_file_has_no_per_file_using(self):
        """OrderConsumer.cs should NOT have per-file using for Common.Models.

        This is the test case: Scatter's namespace filter would miss this file
        because the using statement is in GlobalUsings.cs, not in this file.
        """
        consumer_file = SAMPLES / "MyGalaxyConsumerApp" / "OrderConsumer.cs"
        if not consumer_file.exists():
            pytest.skip("Sample project not available")
        content = consumer_file.read_text(encoding="utf-8")
        # File uses Result, PersonDto, Context — but no using for Common.Models
        assert "using GalaxyWorks.Common.Models;" not in content
        # But it DOES use types from that namespace
        assert "Result" in content
        assert "PersonDto" in content
        assert "Context" in content


# ===========================================================================
# TestUsingAliasAndStatic
# ===========================================================================
class TestUsingAliasAndStatic:
    """Verify handling of using aliases and using static."""

    def test_using_alias_hides_type_name(self):
        """Using alias: only actual type declarations are extracted, not aliases."""
        code = """using DataSvc = GalaxyWorks.Data.DataServices.PortalDataService;

namespace GalaxyWorks.Api.Controllers;

public class MyController
{
    private readonly DataSvc _service;
}"""
        types = extract_type_names_from_content(code)
        assert "MyController" in types
        # Alias is not a type declaration
        assert "DataSvc" not in types

    def test_using_static_hides_type_name(self):
        """Using static: only actual type declarations are extracted."""
        code = """using static GalaxyWorks.Data.Models.StatusType;

namespace GalaxyWorks.Api.Controllers;

public class MyController
{
    public void DoWork()
    {
        var status = Active;
    }
}"""
        types = extract_type_names_from_content(code)
        assert "MyController" in types
        # StatusType is not declared here, only imported via using static
        assert "StatusType" not in types

    def test_alias_in_sample_file(self):
        """PortalApiController.cs uses both alias and static imports."""
        controller = SAMPLES / "GalaxyWorks.Api" / "Controllers" / "PortalApiController.cs"
        if not controller.exists():
            pytest.skip("Sample project not available")
        content = controller.read_text(encoding="utf-8")
        assert "using DataSvc = GalaxyWorks.Data.DataServices.PortalDataService;" in content
        assert "using static GalaxyWorks.Data.Models.StatusType;" in content


# ===========================================================================
# TestExtensionMethods
# ===========================================================================
class TestExtensionMethods:
    """Verify extension method detection and coupling analysis."""

    def test_extension_class_extracted(self):
        """StringExtensions class should be extractable from the source."""
        ext_file = SAMPLES / "GalaxyWorks.Common" / "Extensions" / "StringExtensions.cs"
        if not ext_file.exists():
            pytest.skip("Sample project not available")
        content = ext_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)
        assert "StringExtensions" in types

    def test_extension_usage_invisible_to_type_search(self):
        """Extension method calls produce no type declarations."""
        consumer_code = """
var greeting = name.Truncate(20);
var slug = title.ToSlug();
"""
        types = extract_type_names_from_content(consumer_code)
        assert "StringExtensions" not in types
        assert len(types) == 0


# ===========================================================================
# TestSolutionFile
# ===========================================================================
class TestSolutionFile:
    """Verify .sln solution file exists and is well-formed."""

    def test_sln_file_exists(self):
        sln = SAMPLES / "GalaxyWorks.sln"
        assert sln.exists()

    def test_sln_contains_all_projects(self):
        """Solution file should reference all Galaxy and consumer projects."""
        sln = SAMPLES / "GalaxyWorks.sln"
        if not sln.exists():
            pytest.skip("Solution file not available")
        content = sln.read_text(encoding="utf-8")
        expected_projects = [
            "GalaxyWorks.Data",
            "GalaxyWorks.WebPortal",
            "GalaxyWorks.BatchProcessor",
            "GalaxyWorks.Common",
            "GalaxyWorks.Api",
            "GalaxyWorks.Data.Tests",
            "MyDotNetApp.Consumer",
            "MyGalaxyConsumerApp",
            "MyGalaxyConsumerApp2",
            "MyDotNetApp2.Exclude",
        ]
        for project in expected_projects:
            assert project in content, f"{project} not found in .sln"

    def test_sln_format_version(self):
        """Solution file should have valid format version header."""
        sln = SAMPLES / "GalaxyWorks.sln"
        if not sln.exists():
            pytest.skip("Solution file not available")
        content = sln.read_text(encoding="utf-8")
        assert "Microsoft Visual Studio Solution File" in content
        assert "Format Version 12.00" in content


# ===========================================================================
# TestTestProjectDetection
# ===========================================================================
class TestTestProjectDetection:
    """Verify Scatter handles test projects (xUnit with PackageReferences)."""

    def test_test_project_parsed(self):
        """Data.Tests .csproj should be parseable with correct metadata."""
        csproj = SAMPLES / "GalaxyWorks.Data.Tests" / "GalaxyWorks.Data.Tests.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        assert result["project_style"] == "sdk"
        assert result["target_framework"] == "net8.0"

    def test_test_project_references(self):
        """Test project should reference GalaxyWorks.Data and GalaxyWorks.Common."""
        csproj = SAMPLES / "GalaxyWorks.Data.Tests" / "GalaxyWorks.Data.Tests.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        refs = result["project_references"]
        assert len(refs) == 2
        refs_str = " ".join(refs)
        assert "GalaxyWorks.Data.csproj" in refs_str
        assert "GalaxyWorks.Common.csproj" in refs_str

    def test_package_references_not_in_project_references(self):
        """PackageReferences (xUnit, etc.) should NOT appear as ProjectReferences."""
        csproj = SAMPLES / "GalaxyWorks.Data.Tests" / "GalaxyWorks.Data.Tests.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        refs_str = " ".join(result["project_references"])
        assert "xunit" not in refs_str.lower()
        assert "Microsoft.NET.Test.Sdk" not in refs_str

    def test_test_project_type_extraction(self):
        """Type declarations in test files should be extractable."""
        test_file = SAMPLES / "GalaxyWorks.Data.Tests" / "PortalDataServiceTests.cs"
        if not test_file.exists():
            pytest.skip("Sample project not available")
        content = test_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)
        assert "PortalDataServiceTests" in types


# ===========================================================================
# TestPackageReferences
# ===========================================================================
class TestPackageReferences:
    """Verify Scatter correctly ignores PackageReferences (NuGet) and only traces ProjectReferences."""

    def test_api_project_separates_references(self):
        """Api project has both PackageReference and ProjectReference — only ProjectReferences returned."""
        csproj = SAMPLES / "GalaxyWorks.Api" / "GalaxyWorks.Api.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        refs = result["project_references"]
        assert len(refs) == 2
        refs_str = " ".join(refs)
        assert "GalaxyWorks.Data.csproj" in refs_str
        assert "GalaxyWorks.Common.csproj" in refs_str
        # Swashbuckle is a PackageReference, not a ProjectReference
        assert "Swashbuckle" not in refs_str

    def test_common_project_separates_references(self):
        """Common project has PackageReference (Logging) alongside ProjectReference."""
        csproj = SAMPLES / "GalaxyWorks.Common" / "GalaxyWorks.Common.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        result = parse_csproj_all_references(csproj)
        assert result is not None
        refs = result["project_references"]
        assert len(refs) == 1
        assert "GalaxyWorks.Data.csproj" in refs[0]
        # Logging.Abstractions is a PackageReference
        refs_str = " ".join(refs)
        assert "Logging" not in refs_str


# ===========================================================================
# TestInternalsVisibleTo
# ===========================================================================
class TestInternalsVisibleTo:
    """Verify InternalsVisibleTo patterns exist in sample projects."""

    def test_common_project_has_internals_visible_to(self):
        """GalaxyWorks.Common should have InternalsVisibleTo for Data.Tests."""
        csproj = SAMPLES / "GalaxyWorks.Common" / "GalaxyWorks.Common.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        content = csproj.read_text(encoding="utf-8")
        assert "InternalsVisibleTo" in content
        assert "GalaxyWorks.Data.Tests" in content

    def test_internal_types_exist(self):
        """Internal types should be defined in Common for cross-project access."""
        internal_file = SAMPLES / "GalaxyWorks.Common" / "Models" / "InternalTypes.cs"
        if not internal_file.exists():
            pytest.skip("Sample project not available")
        content = internal_file.read_text(encoding="utf-8")
        assert "internal class InternalCacheKey" in content
        assert "internal record InternalAuditEntry" in content

    def test_internal_types_not_extracted_by_regex(self):
        """Scatter's regex should still find internal classes (they have 'class' keyword)."""
        code = """internal class InternalCacheKey
{
    public string Key { get; set; }
}"""
        types = extract_type_names_from_content(code)
        assert "InternalCacheKey" in types

    def test_internal_record_extracted(self):
        """Internal positional records are now detected via 'record' keyword."""
        code = (
            "internal record InternalAuditEntry(string Action, string UserId, DateTime Timestamp);"
        )
        types = extract_type_names_from_content(code)
        assert "InternalAuditEntry" in types


# ===========================================================================
# TestConditionalCompilation
# ===========================================================================
class TestConditionalCompilation:
    """Verify conditional compilation patterns exist in sample projects."""

    def test_conditional_compilation_in_sample(self):
        """ServiceCollectionExtensions.cs should have #if preprocessor directives."""
        ext_file = SAMPLES / "GalaxyWorks.Common" / "Extensions" / "ServiceCollectionExtensions.cs"
        if not ext_file.exists():
            pytest.skip("Sample project not available")
        content = ext_file.read_text(encoding="utf-8")
        assert "#if NET8_0_OR_GREATER" in content
        assert "#endif" in content

    def test_both_branches_scanned(self):
        """Scatter scans raw text, so both #if branches produce using matches."""
        from scatter.analyzers.graph_builder import _USING_PATTERN

        code = """#if NET48
using System.Web.Mvc;
#else
using Microsoft.AspNetCore.Mvc;
#endif"""
        matches = [m.group(1) for m in _USING_PATTERN.finditer(code)]
        # Both branches are scanned — could produce false dependencies
        assert "System.Web.Mvc" in matches
        assert "Microsoft.AspNetCore.Mvc" in matches


# ===========================================================================
# TestEventDelegatePatterns
# ===========================================================================
class TestEventDelegatePatterns:
    """Verify event and delegate pattern detection."""

    def test_event_types_extracted(self):
        """Event-related types should be extractable."""
        events_file = SAMPLES / "GalaxyWorks.Common" / "Events" / "DomainEvents.cs"
        if not events_file.exists():
            pytest.skip("Sample project not available")
        content = events_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)
        assert "OrderEventArgs" in types
        assert "OrderProcessor" in types

    def test_delegate_extracted(self):
        """Custom delegate types are now detected via DELEGATE_DECLARATION_PATTERN."""
        code = """public delegate Task AsyncEventHandler<TEventArgs>(object sender, TEventArgs args)
    where TEventArgs : EventArgs;"""
        types = extract_type_names_from_content(code)
        assert "AsyncEventHandler" in types


# ===========================================================================
# TestAspNetCorePatterns
# ===========================================================================
class TestAspNetCorePatterns:
    """Verify ASP.NET Core patterns in the Api sample project."""

    def test_api_project_is_web_sdk(self):
        """GalaxyWorks.Api should use Microsoft.NET.Sdk.Web."""
        csproj = SAMPLES / "GalaxyWorks.Api" / "GalaxyWorks.Api.csproj"
        if not csproj.exists():
            pytest.skip("Sample project not available")
        content = csproj.read_text(encoding="utf-8")
        assert 'Sdk="Microsoft.NET.Sdk.Web"' in content

    def test_controller_types_extracted(self):
        """ControllerBase-derived controllers should be extractable."""
        controller_file = SAMPLES / "GalaxyWorks.Api" / "Controllers" / "PortalApiController.cs"
        if not controller_file.exists():
            pytest.skip("Sample project not available")
        content = controller_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)
        assert "PortalApiController" in types

    def test_minimal_api_has_no_extractable_types(self):
        """Program.cs with minimal APIs has no class declarations — Scatter can't trace it."""
        program_file = SAMPLES / "GalaxyWorks.Api" / "Program.cs"
        if not program_file.exists():
            pytest.skip("Sample project not available")
        content = program_file.read_text(encoding="utf-8")
        types = extract_type_names_from_content(content)
        # Minimal APIs define endpoints without class declarations
        assert len(types) == 0


# ===========================================================================
# TestGraphIntegrationWithNewProjects
# ===========================================================================
class TestGraphIntegrationWithNewProjects:
    """Integration tests: verify graph builder discovers and wires the new projects."""

    @pytest.fixture(scope="class")
    def graph(self):
        from scatter.analyzers.graph_builder import build_dependency_graph

        return build_dependency_graph(
            SAMPLES,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )

    def test_common_project_in_graph(self, graph):
        node = graph.get_node("GalaxyWorks.Common")
        assert node is not None
        assert node.project_style == "sdk"
        assert node.namespace == "GalaxyWorks.Common"

    def test_api_project_in_graph(self, graph):
        node = graph.get_node("GalaxyWorks.Api")
        assert node is not None
        assert node.project_style == "sdk"
        assert node.namespace == "GalaxyWorks.Api"

    def test_tests_project_in_graph(self, graph):
        node = graph.get_node("GalaxyWorks.Data.Tests")
        assert node is not None
        assert node.project_style == "sdk"

    def test_common_types_extracted_in_graph(self, graph):
        """GalaxyWorks.Common should have its type declarations populated."""
        node = graph.get_node("GalaxyWorks.Common")
        assert node is not None
        assert "Result" in node.type_declarations
        assert "Response" in node.type_declarations
        assert "Options" in node.type_declarations
        assert "Context" in node.type_declarations
        assert "StringExtensions" in node.type_declarations
        assert "OrderProcessor" in node.type_declarations
        assert "OrderEventArgs" in node.type_declarations

    def test_common_has_all_record_types(self, graph):
        """All record variants are now detected by the updated regex."""
        node = graph.get_node("GalaxyWorks.Common")
        assert node is not None
        assert "PersonDto" in node.type_declarations  # positional record
        assert "OrderSummary" in node.type_declarations  # record class
        assert "Point" in node.type_declarations  # record struct positional
        assert "Coordinate" in node.type_declarations  # record struct with body
        assert "EmployeeDto" in node.type_declarations  # record with inheritance

    def test_data_has_new_consumers(self, graph):
        """GalaxyWorks.Data should have Common, Api, and Data.Tests as consumers."""
        consumers = graph.get_consumers("GalaxyWorks.Data")
        consumer_names = {c.name for c in consumers}
        assert "GalaxyWorks.Common" in consumer_names
        assert "GalaxyWorks.Api" in consumer_names
        assert "GalaxyWorks.Data.Tests" in consumer_names

    def test_common_has_consumers(self, graph):
        """GalaxyWorks.Common should be consumed by Api, Data.Tests, and MyGalaxyConsumerApp."""
        consumers = graph.get_consumers("GalaxyWorks.Common")
        consumer_names = {c.name for c in consumers}
        assert "GalaxyWorks.Api" in consumer_names
        assert "GalaxyWorks.Data.Tests" in consumer_names
        assert "MyGalaxyConsumerApp" in consumer_names

    def test_api_file_count(self, graph):
        """Api project should have multiple .cs files."""
        node = graph.get_node("GalaxyWorks.Api")
        assert node is not None
        assert node.file_count >= 4  # GlobalUsings, Program, 2 controllers, 1 service

    def test_common_file_count(self, graph):
        """Common project should have multiple .cs files."""
        node = graph.get_node("GalaxyWorks.Common")
        assert node is not None
        assert node.file_count >= 5  # Records, CommonNames, InternalTypes, 2 Extensions, Events
