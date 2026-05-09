"""Tests for sproc catalog assembly."""

from pathlib import Path

from scatter.analyzers.sproc_catalog import SprocCatalogEntry, build_sproc_catalog
from scatter.scanners.db_scanner import DbDependency


def _dep(name, project, method="string_literal", obj_type="sproc"):
    return DbDependency(
        db_object_name=name,
        db_object_type=obj_type,
        source_file=Path(f"/fake/{project}/file.cs"),
        source_project=project,
        detection_method=method,
    )


class TestBuildSprocCatalog:
    def test_basic_assembly(self):
        deps = [
            _dep("dbo.sp_Foo", "ProjectA"),
            _dep("dbo.sp_Foo", "ProjectB"),
            _dep("dbo.sp_Bar", "ProjectA"),
        ]
        catalog = build_sproc_catalog(deps)
        assert catalog.total_sprocs == 2
        assert catalog.total_referenced == 2

    def test_defined_and_referenced(self):
        deps = [
            _dep("dbo.sp_Foo", "ProjectA", method="sql_catalog"),
            _dep("dbo.sp_Foo", "ProjectB", method="string_literal"),
        ]
        catalog = build_sproc_catalog(deps)
        entry = catalog.entries[0]
        assert entry.status == "defined_and_referenced"
        assert entry.defined_in_sql is True

    def test_referenced_only_status(self):
        """Sproc without .sql definition labeled 'referenced_only'."""
        deps = [_dep("dbo.sp_Foo", "ProjectA")]
        catalog = build_sproc_catalog(deps)
        assert catalog.entries[0].status == "referenced_only"

    def test_defined_only_status(self):
        """Sproc in .sql but not referenced in C#."""
        deps = [_dep("dbo.sp_Foo", "ProjectA", method="sql_catalog")]
        catalog = build_sproc_catalog(deps)
        assert catalog.entries[0].status == "defined_only"

    def test_coverage_calculation(self):
        """Coverage = defined-and-referenced / total-referenced, not defined / total."""
        deps = [
            _dep("dbo.sp_Defined", "P", method="sql_catalog"),
            _dep("dbo.sp_Defined", "P", method="string_literal"),  # also referenced
            _dep("dbo.sp_Undefined", "P", method="string_literal"),
        ]
        catalog = build_sproc_catalog(deps)
        # 1 defined+referenced / 2 referenced = 50%
        assert catalog.coverage_pct == 50.0

    def test_coverage_excludes_dead_definitions(self):
        """Dead .sql definitions don't inflate coverage."""
        deps = [
            _dep("dbo.sp_Dead1", "P", method="sql_catalog"),  # defined only, not referenced
            _dep("dbo.sp_Dead2", "P", method="sql_catalog"),  # defined only
            _dep("dbo.sp_Live", "P", method="sql_catalog"),  # defined
            _dep("dbo.sp_Live", "P", method="string_literal"),  # also referenced
        ]
        catalog = build_sproc_catalog(deps)
        # 1 defined+referenced / 1 referenced = 100% (not 3/4 = 75%)
        assert catalog.coverage_pct == 100.0

    def test_shared_count(self):
        deps = [
            _dep("dbo.sp_Shared", "ProjectA"),
            _dep("dbo.sp_Shared", "ProjectB"),
            _dep("dbo.sp_Solo", "ProjectA"),
        ]
        catalog = build_sproc_catalog(deps)
        assert catalog.total_shared == 1

    def test_normalization_deduplication(self):
        """[dbo].[sp_Foo] and dbo.sp_Foo normalize to same entry."""
        deps = [
            _dep("[dbo].[sp_Foo]", "ProjectA"),
            _dep("dbo.sp_Foo", "ProjectB"),
        ]
        catalog = build_sproc_catalog(deps)
        assert catalog.total_sprocs == 1
        assert len(catalog.entries[0].referencing_projects) == 2

    def test_sort_by_reference_count(self):
        deps = [
            _dep("dbo.sp_Less", "P1"),
            _dep("dbo.sp_More", "P1"),
            _dep("dbo.sp_More", "P2"),
            _dep("dbo.sp_More", "P3"),
        ]
        catalog = build_sproc_catalog(deps)
        assert catalog.entries[0].name == "dbo.sp_More"

    def test_ef_migration_detection(self):
        deps = [_dep("dbo.sp_Mig", "P", method="ef_migration")]
        catalog = build_sproc_catalog(deps)
        assert catalog.entries[0].defined_in_migration is True
        assert catalog.entries[0].status == "defined_only"

    def test_non_sproc_deps_ignored(self):
        """DbDependencies with db_object_type != 'sproc' are skipped."""
        deps = [
            _dep("UserTable", "P", obj_type="ef_model"),
            _dep("dbo.sp_Real", "P"),
        ]
        catalog = build_sproc_catalog(deps)
        assert catalog.total_sprocs == 1
        assert catalog.entries[0].name == "dbo.sp_Real"

    def test_empty_deps(self):
        catalog = build_sproc_catalog([])
        assert catalog.total_sprocs == 0
        assert catalog.coverage_pct == 0.0

    def test_undefined_count(self):
        deps = [
            _dep("dbo.sp_HasSql", "P", method="sql_catalog"),
            _dep("dbo.sp_HasSql", "P", method="string_literal"),
            _dep("dbo.sp_NoSql", "P", method="string_literal"),
        ]
        catalog = build_sproc_catalog(deps)
        assert catalog.total_undefined == 1
