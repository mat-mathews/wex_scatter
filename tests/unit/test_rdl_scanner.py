"""Tests for RDL scanner — sproc references in SSRS report files."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.scanners.rdl_scanner import (
    RdlSprocReference,
    add_rdl_sproc_edges,
    scan_rdl_files,
)


@pytest.fixture
def samples_dir():
    return Path(__file__).parent.parent.parent / "samples"


def _write_rdl(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


def _project_dir_index(tmp_path, project_name="TestProject"):
    return {tmp_path: project_name}


_RDL_WITH_SPROC = """\
<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">
  <DataSets>
    <DataSet Name="MainData">
      <Query>
        <DataSourceName>MyDB</DataSourceName>
        <CommandType>StoredProcedure</CommandType>
        <CommandText>dbo.sp_GetReport</CommandText>
      </Query>
    </DataSet>
  </DataSets>
</Report>"""

_RDL_NO_COMMAND_TYPE = """\
<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition">
  <DataSets>
    <DataSet Name="RawQuery">
      <Query>
        <CommandText>dbo.sp_LegacySproc</CommandText>
      </Query>
    </DataSet>
  </DataSets>
</Report>"""

_RDL_MULTIPLE_DATASETS = """\
<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">
  <DataSets>
    <DataSet Name="First">
      <Query>
        <CommandText>dbo.sp_Alpha</CommandText>
      </Query>
    </DataSet>
    <DataSet Name="Second">
      <Query>
        <CommandText>dbo.sp_Beta</CommandText>
      </Query>
    </DataSet>
  </DataSets>
</Report>"""

_RDL_NO_QUERY = """\
<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">
  <Body><Height>11in</Height></Body>
</Report>"""


class TestScanRdlFiles:
    def test_extracts_sproc_with_command_type(self, tmp_path):
        rdl = _write_rdl(tmp_path, "report.rdl", _RDL_WITH_SPROC)
        refs = scan_rdl_files([rdl], _project_dir_index(tmp_path), tmp_path)

        assert len(refs) == 1
        assert refs[0].sproc_name == "dbo.sp_GetReport"
        assert refs[0].dataset_name == "MainData"
        assert refs[0].containing_project == "TestProject"

    def test_extracts_sproc_without_command_type(self, tmp_path):
        rdl = _write_rdl(tmp_path, "legacy.rdl", _RDL_NO_COMMAND_TYPE)
        refs = scan_rdl_files([rdl], _project_dir_index(tmp_path), tmp_path)

        assert len(refs) == 1
        assert refs[0].sproc_name == "dbo.sp_LegacySproc"

    def test_multiple_datasets(self, tmp_path):
        rdl = _write_rdl(tmp_path, "multi.rdl", _RDL_MULTIPLE_DATASETS)
        refs = scan_rdl_files([rdl], _project_dir_index(tmp_path), tmp_path)

        assert len(refs) == 2
        sproc_names = {r.sproc_name for r in refs}
        assert sproc_names == {"dbo.sp_Alpha", "dbo.sp_Beta"}

    def test_no_query_elements(self, tmp_path):
        rdl = _write_rdl(tmp_path, "empty.rdl", _RDL_NO_QUERY)
        refs = scan_rdl_files([rdl], _project_dir_index(tmp_path), tmp_path)
        assert refs == []

    def test_malformed_xml_skipped(self, tmp_path):
        rdl = _write_rdl(tmp_path, "bad.rdl", "not xml at all")
        refs = scan_rdl_files([rdl], _project_dir_index(tmp_path), tmp_path)
        assert refs == []

    def test_oversized_file_skipped(self, tmp_path):
        rdl = tmp_path / "huge.rdl"
        rdl.write_text("x" * (1_048_577), encoding="utf-8")
        refs = scan_rdl_files([rdl], _project_dir_index(tmp_path), tmp_path)
        assert refs == []

    def test_orphaned_rdl_skipped(self, tmp_path):
        rdl = _write_rdl(tmp_path, "orphan.rdl", _RDL_WITH_SPROC)
        # Empty project index — no project owns this file
        refs = scan_rdl_files([rdl], {}, tmp_path)
        assert refs == []

    def test_empty_file_list(self, tmp_path):
        refs = scan_rdl_files([], {}, tmp_path)
        assert refs == []


class TestAddRdlSprocEdges:
    def test_creates_edge_for_matching_sproc(self):
        graph = MagicMock()
        graph.get_node.return_value = True

        refs = [
            RdlSprocReference(
                sproc_name="dbo.sp_GetReport",
                rdl_file=Path("report.rdl"),
                containing_project="Reports",
                dataset_name="MainData",
            )
        ]
        sproc_map = {"dbo.sp_GetReport": {"DataProject"}}

        count = add_rdl_sproc_edges(graph, refs, sproc_map)
        assert count == 1
        edge = graph.add_edge.call_args[0][0]
        assert edge.source == "Reports"
        assert edge.target == "DataProject"
        assert edge.edge_type == "rdl_sproc"

    def test_skips_self_reference(self):
        graph = MagicMock()
        graph.get_node.return_value = True

        refs = [
            RdlSprocReference(
                sproc_name="dbo.sp_Internal",
                rdl_file=Path("report.rdl"),
                containing_project="SameProject",
                dataset_name="DS",
            )
        ]
        sproc_map = {"dbo.sp_Internal": {"SameProject"}}

        count = add_rdl_sproc_edges(graph, refs, sproc_map)
        assert count == 0

    def test_accumulates_evidence(self):
        graph = MagicMock()
        graph.get_node.return_value = True

        refs = [
            RdlSprocReference("dbo.sp_A", Path("r1.rdl"), "Reports", "DS1"),
            RdlSprocReference("dbo.sp_B", Path("r2.rdl"), "Reports", "DS2"),
        ]
        sproc_map = {
            "dbo.sp_A": {"DataProject"},
            "dbo.sp_B": {"DataProject"},
        }

        count = add_rdl_sproc_edges(graph, refs, sproc_map)
        assert count == 1  # one edge with 2 evidence items
        edge = graph.add_edge.call_args[0][0]
        assert edge.weight == 2.0
        assert len(edge.evidence) == 2

    def test_empty_references(self):
        graph = MagicMock()
        count = add_rdl_sproc_edges(graph, [], {})
        assert count == 0


class TestSamplesIntegration:
    def test_rdl_files_in_samples(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        rdl_files = list(samples_dir.rglob("*.rdl"))
        assert len(rdl_files) == 2

        # Build project dir index
        project_dir_index = {}
        for proj_file in list(samples_dir.rglob("*.csproj")) + list(samples_dir.rglob("*.rptproj")):
            project_dir_index[proj_file.parent] = proj_file.stem

        refs = scan_rdl_files(rdl_files, project_dir_index, samples_dir)
        assert len(refs) == 2

        sproc_names = {r.sproc_name for r in refs}
        assert "dbo.sp_GetPortalConfigurationDetails" in sproc_names
        assert "dbo.sp_InsertPortalConfiguration" in sproc_names

        for ref in refs:
            assert ref.containing_project == "GalaxyWorks.Reports"
