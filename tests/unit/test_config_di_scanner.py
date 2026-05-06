"""Tests for config-based DI scanner."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scatter.scanners.config_di_scanner import (
    ConfigDIReference,
    add_config_di_edges,
    scan_config_files,
)


@pytest.fixture
def samples_dir():
    return Path(__file__).parent.parent.parent / "samples"


def _write_config(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


def _project_dir_index(tmp_path, project_name="TestProject"):
    """Map tmp_path directory to a project name."""
    return {tmp_path: project_name}


class TestScanConfigFiles:
    def test_unity_register_element(self, tmp_path):
        config = _write_config(
            tmp_path,
            "unity.config",
            """<?xml version="1.0"?>
            <configuration>
              <unity>
                <container>
                  <register type="Foo.Bar.IService, Foo.Bar"
                            mapTo="Foo.Bar.ServiceImpl, Foo.Bar" />
                </container>
              </unity>
            </configuration>""",
        )
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        type_names = {r.type_fqtn for r in refs}
        assert "Foo.Bar.IService" in type_names
        assert "Foo.Bar.ServiceImpl" in type_names

    def test_autofac_component(self, tmp_path):
        config = _write_config(
            tmp_path,
            "autofac.config",
            """<?xml version="1.0"?>
            <autofac>
              <components>
                <component type="MyApp.Data.Repository, MyApp.Data" />
              </components>
            </autofac>""",
        )
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        assert len(refs) == 1
        assert refs[0].type_fqtn == "MyApp.Data.Repository"
        assert refs[0].element_tag == "component"

    def test_deduplicates_same_type(self, tmp_path):
        config = _write_config(
            tmp_path,
            "web.config",
            """<?xml version="1.0"?>
            <configuration>
              <register type="Foo.Bar.Service, Foo.Bar" />
              <register mapTo="Foo.Bar.Service, Foo.Bar" />
            </configuration>""",
        )
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        # Same FQTN should appear only once
        assert len(refs) == 1

    def test_no_type_registrations(self, tmp_path):
        config = _write_config(
            tmp_path,
            "app.config",
            """<?xml version="1.0"?>
            <configuration>
              <appSettings>
                <add key="Timeout" value="30" />
              </appSettings>
            </configuration>""",
        )
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        assert refs == []

    def test_malformed_xml_skipped(self, tmp_path):
        config = _write_config(tmp_path, "bad.config", "this is not xml at all")
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        assert refs == []

    def test_oversized_file_skipped(self, tmp_path):
        config = tmp_path / "huge.config"
        # Write just over 1 MB
        config.write_text("x" * (1_048_577), encoding="utf-8")
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        assert refs == []

    def test_empty_file_list(self, tmp_path):
        refs = scan_config_files([], {}, tmp_path)
        assert refs == []

    def test_file_outside_project_skipped(self, tmp_path):
        config = _write_config(
            tmp_path,
            "orphan.config",
            """<?xml version="1.0"?>
            <register type="Foo.Bar.Baz, Foo.Bar" />""",
        )
        # Empty project index — no project owns this file
        refs = scan_config_files([config], {}, tmp_path)
        assert refs == []

    def test_type_in_text_content(self, tmp_path):
        config = _write_config(
            tmp_path,
            "custom.config",
            """<?xml version="1.0"?>
            <plugins>
              <type>MyApp.Plugins.Reporter, MyApp.Plugins</type>
            </plugins>""",
        )
        refs = scan_config_files([config], _project_dir_index(tmp_path), tmp_path)
        assert len(refs) == 1
        assert refs[0].type_fqtn == "MyApp.Plugins.Reporter"


class TestAddConfigDiEdges:
    def test_creates_edge_for_matching_type(self):
        graph = MagicMock()
        graph.get_node.return_value = True  # node exists

        refs = [
            ConfigDIReference(
                type_fqtn="GalaxyWorks.Data.PortalDataService",
                config_file=Path("unity.config"),
                containing_project="GalaxyWorks.Api",
                element_tag="register",
            )
        ]
        type_to_projects = {"PortalDataService": {"GalaxyWorks.Data"}}

        count = add_config_di_edges(graph, refs, type_to_projects)
        assert count == 1
        graph.add_edge.assert_called_once()
        edge = graph.add_edge.call_args[0][0]
        assert edge.source == "GalaxyWorks.Api"
        assert edge.target == "GalaxyWorks.Data"
        assert edge.edge_type == "config_di"
        assert edge.weight == 1.0  # 1 evidence item

    def test_skips_self_reference(self):
        graph = MagicMock()
        graph.get_node.return_value = True

        refs = [
            ConfigDIReference(
                type_fqtn="GalaxyWorks.Api.SomeService",
                config_file=Path("web.config"),
                containing_project="GalaxyWorks.Api",
                element_tag="register",
            )
        ]
        type_to_projects = {"SomeService": {"GalaxyWorks.Api"}}

        count = add_config_di_edges(graph, refs, type_to_projects)
        assert count == 0

    def test_skips_unresolved_type(self):
        graph = MagicMock()

        refs = [
            ConfigDIReference(
                type_fqtn="External.Library.Thing",
                config_file=Path("web.config"),
                containing_project="GalaxyWorks.Api",
                element_tag="register",
            )
        ]
        type_to_projects = {"PortalDataService": {"GalaxyWorks.Data"}}

        count = add_config_di_edges(graph, refs, type_to_projects)
        assert count == 0

    def test_empty_references(self):
        graph = MagicMock()
        count = add_config_di_edges(graph, [], {})
        assert count == 0


class TestSamplesIntegration:
    def test_unity_config_in_samples(self, samples_dir):
        if not samples_dir.is_dir():
            pytest.skip("samples/ not found")

        config_files = list(samples_dir.rglob("*.config"))
        assert len(config_files) >= 1

        # Build a basic project dir index from samples
        project_dir_index = {}
        for csproj in samples_dir.rglob("*.csproj"):
            project_dir_index[csproj.parent] = csproj.stem

        refs = scan_config_files(config_files, project_dir_index, samples_dir)
        assert (
            len(refs) >= 2
        )  # unity.config has IDataAccessor + PortalDataService + IHealthMonitor + HealthMonitor

        type_names = {r.type_fqtn for r in refs}
        assert "GalaxyWorks.Data.PortalDataService" in type_names
        assert "GalaxyWorks.Data.IDataAccessor" in type_names

        # All refs should be owned by GalaxyWorks.Api
        for ref in refs:
            if ref.config_file.name == "unity.config":
                assert ref.containing_project == "GalaxyWorks.Api"
