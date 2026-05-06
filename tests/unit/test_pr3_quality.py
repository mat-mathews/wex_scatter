"""PR 3 tests: csproj parse consolidation, JSON schema versioning, credential scanning."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scatter.ai.base import redact_credentials
from scatter.reports.json_reporter import REPORT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Part A: parse_csproj explicit imports (Anya's edge cases)
# ---------------------------------------------------------------------------

from scatter.scanners.project_scanner import parse_csproj


class TestParseCsprojExplicitImports:
    def test_zero_explicit_imports(self, tmp_path):
        csproj = tmp_path / "NoImports.csproj"
        csproj.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        result = parse_csproj(csproj, search_scope=tmp_path)
        assert result is not None
        assert result["explicit_imports"] == []

    def test_system_only_imports_filtered(self, tmp_path):
        csproj = tmp_path / "SystemOnly.csproj"
        csproj.write_text(
            "<Project>\n"
            '  <Import Project="$(MSBuildExtensionsPath)\\foo.props" />\n'
            '  <Import Project="$(MSBuildBinPath)\\Microsoft.CSharp.targets" />\n'
            "</Project>"
        )
        result = parse_csproj(csproj, search_scope=tmp_path)
        assert result["explicit_imports"] == []

    def test_msbuild_this_file_directory_resolved(self, tmp_path):
        props = tmp_path / "build" / "shared.props"
        props.parent.mkdir()
        props.write_text("<Project/>")
        csproj = tmp_path / "src" / "App.csproj"
        csproj.parent.mkdir()
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <Import Project="$(MSBuildThisFileDirectory)..\\build\\shared.props" />\n'
            "</Project>"
        )
        result = parse_csproj(csproj, search_scope=tmp_path)
        assert len(result["explicit_imports"]) == 1
        assert result["explicit_imports"][0].name == "shared.props"

    def test_import_extraction_failure_returns_empty(self, tmp_path):
        csproj = tmp_path / "Good.csproj"
        csproj.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        with patch(
            "scatter.scanners.project_scanner._extract_explicit_imports",
            side_effect=RuntimeError("boom"),
        ):
            result = parse_csproj(csproj, search_scope=tmp_path)
        assert result is not None
        assert result["explicit_imports"] == []
        assert result["project_references"] == []

    def test_no_search_scope_skips_imports(self, tmp_path):
        csproj = tmp_path / "App.csproj"
        csproj.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        result = parse_csproj(csproj)
        assert result is not None
        assert result["explicit_imports"] == []

    def test_project_references_still_extracted(self, tmp_path):
        other = tmp_path / "Other" / "Other.csproj"
        other.parent.mkdir()
        other.write_text("<Project/>")
        csproj = tmp_path / "App.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <ItemGroup>\n"
            '    <ProjectReference Include="Other/Other.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>"
        )
        result = parse_csproj(csproj, search_scope=tmp_path)
        assert "Other/Other.csproj" in result["project_references"]


class TestCacheBackwardCompat:
    def test_v2_cache_without_explicit_imports_loads_gracefully(self):
        from scatter.store.graph_cache import ProjectFacts

        facts = ProjectFacts(namespace="Foo", project_references=["Bar"], csproj_content_hash="abc")
        assert facts.namespace == "Foo"


# ---------------------------------------------------------------------------
# Part B: JSON schema versioning
# ---------------------------------------------------------------------------


class TestSchemaVersioning:
    def test_report_schema_version_is_string(self):
        assert isinstance(REPORT_SCHEMA_VERSION, str)
        assert "." in REPORT_SCHEMA_VERSION

    def test_legacy_consumer_report_has_schema_version(self, tmp_path):
        from scatter.reports.json_reporter import write_json_report

        out = tmp_path / "report.json"
        metadata = {"schema_version": REPORT_SCHEMA_VERSION, "scatter_version": "test"}
        write_json_report([], out, metadata=metadata)
        data = json.loads(out.read_text())
        assert data["metadata"]["schema_version"] == REPORT_SCHEMA_VERSION

    def test_impact_report_has_schema_version(self, tmp_path):
        from scatter.core.models import ImpactReport
        from scatter.reports.json_reporter import write_impact_json_report

        report = ImpactReport(sow_text="test", targets=[])
        out = tmp_path / "impact.json"
        metadata = {"schema_version": REPORT_SCHEMA_VERSION}
        write_impact_json_report(report, out, metadata=metadata)
        data = json.loads(out.read_text())
        assert data["metadata"]["schema_version"] == REPORT_SCHEMA_VERSION

    def test_pr_risk_report_has_schema_version(self, tmp_path):
        from scatter.core.models import PRRiskReport
        from scatter.core.risk_models import AggregateRisk, RiskLevel
        from scatter.reports.json_reporter import write_pr_risk_json_report

        report = PRRiskReport(
            branch_name="test",
            base_branch="main",
            aggregate=AggregateRisk(profiles=[]),
            changed_types=[],
            profiles=[],
        )
        out = tmp_path / "pr-risk.json"
        metadata = {"schema_version": REPORT_SCHEMA_VERSION}
        write_pr_risk_json_report(report, out, metadata=metadata)
        data = json.loads(out.read_text())
        assert data["metadata"]["schema_version"] == REPORT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Part C: Credential scanning + SOW length cap
# ---------------------------------------------------------------------------


class TestCredentialScanning:
    def test_redacts_aws_access_key(self):
        content = 'var key = "AKIAIOSFODNN7EXAMPLE";'
        result = redact_credentials(content)
        assert "AKIA" not in result
        assert "[REDACTED: AWS access key]" in result

    def test_redacts_private_key(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK"
        result = redact_credentials(content)
        assert "PRIVATE KEY" not in result
        assert "[REDACTED: private key]" in result

    def test_redacts_connection_string(self):
        content = 'connectionString = "Server=prod-db;Database=main;User=admin;Password=s3cret"'
        result = redact_credentials(content)
        assert "prod-db" not in result
        assert "[REDACTED:" in result

    def test_redacts_password_assignment(self):
        content = 'password = "SuperSecret123!"'
        result = redact_credentials(content)
        assert "SuperSecret123" not in result
        assert "[REDACTED: password assignment]" in result

    def test_redacts_api_key_assignment(self):
        content = 'api_key = "sk-1234567890abcdef"'
        result = redact_credentials(content)
        assert "sk-1234567890" not in result
        assert "[REDACTED: API key assignment]" in result

    def test_preserves_clean_code(self):
        content = "public class MyService {\n    public void Execute() { }\n}"
        result = redact_credentials(content)
        assert result == content

    def test_preserves_non_matching_lines(self):
        content = 'line one\npassword = "secret123"\nline three'
        result = redact_credentials(content)
        assert "line one" in result
        assert "line three" in result
        assert "secret123" not in result


class TestSOWLengthCap:
    def test_rejects_oversized_sow(self):
        from scatter.ai.tasks.parse_work_request import (
            MAX_SOW_TEXT_LENGTH,
            parse_work_request_with_model,
        )

        huge_sow = "x" * (MAX_SOW_TEXT_LENGTH + 1)
        result = parse_work_request_with_model(MagicMock(), huge_sow)
        assert result is None

    def test_accepts_normal_sow(self):
        from scatter.ai.tasks.parse_work_request import parse_work_request_with_model

        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(
            text='[{"type":"project","name":"Foo","confidence":0.8,"match_evidence":"test"}]'
        )
        result = parse_work_request_with_model(mock_model, "modify Foo project")
        assert result is not None
        assert len(result) == 1
