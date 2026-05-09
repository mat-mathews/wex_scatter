"""Tests for the SQL catalog scanner — .sql file sproc detection + EF migrations."""

import logging
from pathlib import Path
from unittest.mock import patch

from scatter.scanners.sql_catalog_scanner import (
    normalize_sproc_name,
    scan_ef_migrations,
    scan_sql_catalog,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_sql(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _make_project_dir_index(tmp_path: Path, project_name: str = "TestProject") -> dict:
    """Build a project_dir_index that maps tmp_path to a project name."""
    return {tmp_path: project_name}


# ---------------------------------------------------------------------------
# normalize_sproc_name
# ---------------------------------------------------------------------------


class TestNormalizeSprocName:
    def test_schema_qualified(self):
        assert normalize_sproc_name("dbo.sp_Foo") == "dbo.sp_Foo"

    def test_bracketed_schema_and_name(self):
        assert normalize_sproc_name("[dbo].[sp_Foo]") == "dbo.sp_Foo"

    def test_no_schema(self):
        assert normalize_sproc_name("sp_Foo") == "sp_Foo"

    def test_schema_lowercased(self):
        assert normalize_sproc_name("DBO.sp_Foo") == "dbo.sp_Foo"

    def test_mixed_brackets(self):
        assert normalize_sproc_name("[dbo].sp_Foo") == "dbo.sp_Foo"

    def test_preserves_procedure_name_case(self):
        assert normalize_sproc_name("dbo.SP_GetUserData") == "dbo.SP_GetUserData"

    def test_different_schemas_stay_distinct(self):
        """dbo.GetUser and reporting.GetUser are different sprocs."""
        assert normalize_sproc_name("dbo.GetUser") != normalize_sproc_name("reporting.GetUser")

    def test_whitespace_stripped(self):
        assert normalize_sproc_name("  dbo.sp_Foo  ") == "dbo.sp_Foo"

    def test_whitespace_around_dot(self):
        """Regex may capture whitespace between schema and dot — must normalize."""
        assert normalize_sproc_name("[dbo] .[sp_Foo]") == "dbo.sp_Foo"
        assert normalize_sproc_name("dbo .sp_Foo") == "dbo.sp_Foo"


# ---------------------------------------------------------------------------
# scan_sql_catalog
# ---------------------------------------------------------------------------


class TestScanSqlCatalog:
    def test_create_procedure(self, tmp_path):
        sql = _write_sql(
            tmp_path / "sproc.sql",
            "CREATE PROCEDURE dbo.sp_GetUser\n    @Id INT\nAS\nBEGIN\nEND",
        )
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert len(results) == 1
        assert results[0].db_object_name == "dbo.sp_GetUser"
        assert results[0].detection_method == "sql_catalog"
        assert results[0].db_object_type == "sproc"
        assert results[0].source_project == "TestProject"

    def test_alter_procedure_without_create(self, tmp_path):
        """ALTER PROCEDURE is valid without a preceding CREATE in migration scripts."""
        sql = _write_sql(
            tmp_path / "alter.sql",
            "ALTER PROCEDURE dbo.usp_UpdateEmail\n    @Email NVARCHAR(200)\nAS\nBEGIN\nEND",
        )
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert len(results) == 1
        assert results[0].db_object_name == "dbo.usp_UpdateEmail"

    def test_create_or_alter(self, tmp_path):
        sql = _write_sql(
            tmp_path / "sproc.sql",
            "CREATE OR ALTER PROCEDURE dbo.sp_Upsert\nAS\nBEGIN\nEND",
        )
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert len(results) == 1
        assert results[0].db_object_name == "dbo.sp_Upsert"

    def test_bracketed_names(self, tmp_path):
        sql = _write_sql(
            tmp_path / "sproc.sql",
            "CREATE PROCEDURE [dbo].[sp_GetConfig]\nAS\nBEGIN\nEND",
        )
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert len(results) == 1
        assert results[0].db_object_name == "dbo.sp_GetConfig"

    def test_multiple_procedures_per_file(self, tmp_path):
        sql = _write_sql(
            tmp_path / "multi.sql",
            (
                "CREATE PROCEDURE dbo.sp_First\nAS BEGIN END\nGO\n\n"
                "CREATE PROCEDURE dbo.sp_Second\nAS BEGIN END\nGO\n\n"
                "ALTER PROCEDURE dbo.sp_Third\nAS BEGIN END\n"
            ),
        )
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert len(results) == 3
        names = {r.db_object_name for r in results}
        assert names == {"dbo.sp_First", "dbo.sp_Second", "dbo.sp_Third"}

    def test_file_size_cap(self, tmp_path, caplog):
        """Files larger than 1MB are skipped with a warning."""
        big_sql = tmp_path / "huge.sql"
        big_sql.write_text("CREATE PROCEDURE dbo.sp_Big\nAS\n" + "x" * 1_100_000)
        idx = _make_project_dir_index(tmp_path)
        with caplog.at_level(logging.WARNING):
            results = scan_sql_catalog([big_sql], idx, tmp_path)
        assert len(results) == 0
        assert "Skipping oversized" in caplog.text

    def test_no_owning_project(self, tmp_path):
        """Files with no parent project are skipped silently."""
        sql = _write_sql(
            tmp_path / "orphan.sql",
            "CREATE PROCEDURE dbo.sp_Orphan\nAS BEGIN END",
        )
        # Empty index — no project owns this file
        results = scan_sql_catalog([sql], {}, tmp_path)
        assert len(results) == 0

    def test_empty_file_list(self):
        results = scan_sql_catalog([], {}, Path("/fake"))
        assert results == []

    def test_malformed_sql(self, tmp_path):
        """Partial/broken SQL that doesn't match the pattern produces no results."""
        sql = _write_sql(tmp_path / "bad.sql", "CREATE PROCED dbo.sp_Broken\nAS")
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert len(results) == 0

    def test_line_number_correct(self, tmp_path):
        sql = _write_sql(
            tmp_path / "sproc.sql",
            "-- header comment\n-- another line\nCREATE PROCEDURE dbo.sp_OnLine3\nAS BEGIN END",
        )
        idx = _make_project_dir_index(tmp_path)
        results = scan_sql_catalog([sql], idx, tmp_path)
        assert results[0].line_number == 3

    def test_encoding_error_handled(self, tmp_path, caplog):
        """Binary/unreadable files are skipped with a warning."""
        bad_file = tmp_path / "binary.sql"
        bad_file.write_bytes(b"\xff\xfe" + b"\x00" * 100)
        idx = _make_project_dir_index(tmp_path)
        with caplog.at_level(logging.WARNING):
            results = scan_sql_catalog([bad_file], idx, tmp_path)
        # errors="ignore" means it reads but content is garbage — no matches
        assert len(results) == 0


# ---------------------------------------------------------------------------
# scan_ef_migrations
# ---------------------------------------------------------------------------


class TestScanEfMigrations:
    def test_migration_with_create_procedure(self, tmp_path):
        migrations_dir = tmp_path / "Migrations"
        migrations_dir.mkdir()
        mig = migrations_dir / "20240101_AddSproc.cs"
        mig.write_text('migrationBuilder.Sql("CREATE PROCEDURE dbo.sp_NewSproc AS BEGIN END");')
        project_map = {"TestProject": [mig]}
        results = scan_ef_migrations([mig], project_map)
        assert len(results) == 1
        assert results[0].db_object_name == "dbo.sp_NewSproc"
        assert results[0].detection_method == "ef_migration"

    def test_comments_stripped_before_scan(self, tmp_path):
        """Commented-out CREATE PROCEDURE should not be detected."""
        migrations_dir = tmp_path / "Migrations"
        migrations_dir.mkdir()
        mig = migrations_dir / "20240102_Commented.cs"
        mig.write_text(
            '// migrationBuilder.Sql("CREATE PROCEDURE dbo.sp_Ghost AS BEGIN END");\n'
            'migrationBuilder.Sql("SELECT 1");'
        )
        project_map = {"TestProject": [mig]}
        results = scan_ef_migrations([mig], project_map)
        assert len(results) == 0

    def test_non_migration_file_skipped(self, tmp_path):
        """Regular .cs files without Migration in name or path are skipped."""
        regular = tmp_path / "Service.cs"
        regular.write_text('var sql = "CREATE PROCEDURE dbo.sp_ShouldNotMatch AS BEGIN END";')
        project_map = {"TestProject": [regular]}
        results = scan_ef_migrations([regular], project_map)
        assert len(results) == 0

    def test_migration_filename_heuristic(self, tmp_path):
        """File named *Migration*.cs is detected even outside Migrations/ dir."""
        mig = tmp_path / "AddUserMigration.cs"
        mig.write_text('migrationBuilder.Sql("CREATE PROCEDURE dbo.sp_AddUser AS BEGIN END");')
        project_map = {"TestProject": [mig]}
        results = scan_ef_migrations([mig], project_map)
        assert len(results) == 1

    def test_content_from_cache(self, tmp_path):
        """When content_by_path is provided, uses cached content instead of disk."""
        migrations_dir = tmp_path / "Migrations"
        migrations_dir.mkdir()
        mig = migrations_dir / "20240103_Cached.cs"
        mig.write_text("disk content should not be used")

        cached_content = 'migrationBuilder.Sql("CREATE PROCEDURE dbo.sp_FromCache AS BEGIN END");'
        project_map = {"TestProject": [mig]}
        results = scan_ef_migrations([mig], project_map, content_by_path={mig: cached_content})
        assert len(results) == 1
        assert results[0].db_object_name == "dbo.sp_FromCache"

    def test_normalization_collision_dedup(self, tmp_path):
        """Two raw names that normalize to the same string both appear (dedup is catalog's job)."""
        migrations_dir = tmp_path / "Migrations"
        migrations_dir.mkdir()
        mig = migrations_dir / "20240104_Multi.cs"
        mig.write_text(
            'migrationBuilder.Sql("CREATE PROCEDURE [dbo].[sp_Foo] AS BEGIN END");\n'
            'migrationBuilder.Sql("ALTER PROCEDURE dbo.sp_Foo AS BEGIN END");'
        )
        project_map = {"TestProject": [mig]}
        results = scan_ef_migrations([mig], project_map)
        # Both matches returned — catalog layer handles dedup
        assert len(results) == 2
        assert all(r.db_object_name == "dbo.sp_Foo" for r in results)
