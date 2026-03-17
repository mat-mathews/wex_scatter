"""Tests for Initiative 5 Phase 4: Database dependency mapping."""
from pathlib import Path
from textwrap import dedent

import pytest

from scatter.scanners.db_scanner import (
    DbDependency,
    DEFAULT_SPROC_PREFIXES,
    _strip_cs_comments,
    _build_sproc_pattern,
    _scan_file,
    scan_db_dependencies,
    build_db_dependency_matrix,
    add_db_edges_to_graph,
)
from scatter.core.graph import DependencyEdge, DependencyGraph, ProjectNode
from scatter.config import DbConfig, ScatterConfig, load_config

REPO_ROOT = Path(__file__).parent


# ===========================================================================
# TestCommentStripping
# ===========================================================================
class TestCommentStripping:
    def test_strip_single_line_comments(self):
        """Single-line // comments are removed, code preserved."""
        code = dedent("""\
            var x = "sp_Foo"; // this is sp_Bar
            var y = "sp_Baz";
        """)
        result = _strip_cs_comments(code)
        assert '"sp_Foo"' in result
        assert '"sp_Baz"' in result
        assert "sp_Bar" not in result

    def test_strip_multi_line_comments(self):
        """Multi-line /* */ comments are removed."""
        code = dedent("""\
            var x = "sp_Foo";
            /* This calls sp_Bar
               and sp_Baz */
            var y = "sp_Qux";
        """)
        result = _strip_cs_comments(code)
        assert '"sp_Foo"' in result
        assert '"sp_Qux"' in result
        assert "sp_Bar" not in result
        assert "sp_Baz" not in result

    def test_preserve_strings(self):
        """Comment-like patterns inside string literals are preserved."""
        code = 'var s = "// not a comment sp_Foo";'
        result = _strip_cs_comments(code)
        assert "// not a comment sp_Foo" in result

    def test_preserve_verbatim_strings(self):
        """Verbatim strings (@"...") are preserved including quotes."""
        code = 'var s = @"line1\nline2 // not stripped sp_Foo";'
        result = _strip_cs_comments(code)
        assert "sp_Foo" in result

    def test_mixed_comments_and_code(self):
        """Interleaved comments and code handled correctly."""
        code = dedent("""\
            // header comment
            var a = "sp_A";
            /* block */ var b = "sp_B";
            var c = "sp_C"; // inline
        """)
        result = _strip_cs_comments(code)
        assert '"sp_A"' in result
        assert '"sp_B"' in result
        assert '"sp_C"' in result
        assert "header comment" not in result
        assert "block" not in result
        assert "inline" not in result

    def test_block_comment_preserves_newlines(self):
        """Block comments preserve newlines so line numbers stay correct."""
        code = "line1\n/* comment\nspanning\nlines */\nline5"
        result = _strip_cs_comments(code)
        # Original line 5 should still be on line 5
        lines = result.split('\n')
        assert len(lines) == 5
        assert lines[0] == "line1"
        assert lines[4] == "line5"


# ===========================================================================
# TestSprocDetection
# ===========================================================================
class TestSprocDetection:
    def test_detect_sproc_with_schema(self):
        """Detects sproc with schema prefix like dbo.sp_Foo."""
        code = 'command.Text = "dbo.sp_InsertPortalConfiguration";'
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) == 1
        assert sproc_deps[0].db_object_name == "dbo.sp_InsertPortalConfiguration"

    def test_detect_sproc_without_schema(self):
        """Detects sproc without schema prefix."""
        code = 'var name = "sp_GetPortalConfigurationDetails";'
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) == 1
        assert sproc_deps[0].db_object_name == "sp_GetPortalConfigurationDetails"

    def test_detect_sproc_usp_prefix(self):
        """Detects sprocs with usp_ prefix."""
        code = 'Execute("usp_ProcessBatch");'
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) == 1
        assert sproc_deps[0].db_object_name == "usp_ProcessBatch"

    def test_detect_sproc_custom_prefix(self):
        """Detects sprocs with custom prefix list."""
        code = 'Execute("proc_MyCustom");'
        pattern = _build_sproc_pattern(["proc_"])
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) == 1
        assert sproc_deps[0].db_object_name == "proc_MyCustom"

    def test_no_false_positive_on_comments(self):
        """Sproc in comments not detected after comment stripping."""
        code = dedent("""\
            // Execute("sp_OldProc");
            /* Execute("sp_Removed"); */
            var real = "sp_Active";
        """)
        stripped = _strip_cs_comments(code)
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(stripped, Path("test.cs"), "TestProject", pattern)
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) == 1
        assert sproc_deps[0].db_object_name == "sp_Active"

    def test_multiple_sprocs_in_file(self):
        """Multiple sproc references in one file all detected."""
        code = dedent("""\
            Execute("dbo.sp_Insert");
            Execute("dbo.sp_Update");
            Execute("dbo.sp_Delete");
        """)
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) == 3


# ===========================================================================
# TestDbSetDetection
# ===========================================================================
class TestDbSetDetection:
    def test_detect_dbset_pattern(self):
        """DbSet<ModelName> detected as ef_model."""
        code = dedent("""\
            public class MyContext : DbContext
            {
                public DbSet<User> Users { get; set; }
                public DbSet<Order> Orders { get; set; }
            }
        """)
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        ef_deps = [d for d in deps if d.db_object_type == "ef_model"]
        names = {d.db_object_name for d in ef_deps}
        assert "User" in names
        assert "Order" in names
        assert all(d.detection_method == "ef_dbset" for d in ef_deps)

    def test_detect_dbcontext_subclass(self):
        """DbContext subclass detected as ef_context."""
        code = "public class AppDbContext : DbContext { }"
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        ctx_deps = [d for d in deps if d.db_object_type == "ef_context"]
        assert len(ctx_deps) == 1
        assert ctx_deps[0].db_object_name == "AppDbContext"


# ===========================================================================
# TestDirectSqlDetection
# ===========================================================================
class TestDirectSqlDetection:
    def test_detect_select_from(self):
        """SELECT ... FROM table detected in string literal."""
        code = 'var sql = "SELECT * FROM Users WHERE id = @id";'
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sql_deps = [d for d in deps if d.db_object_type == "sql_table"]
        assert len(sql_deps) == 1
        assert sql_deps[0].db_object_name == "Users"

    def test_detect_insert_into(self):
        """INSERT INTO table detected."""
        code = 'cmd.Text = "INSERT INTO Orders (Name) VALUES (@n)";'
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        sql_deps = [d for d in deps if d.db_object_type == "sql_table"]
        assert len(sql_deps) == 1
        assert sql_deps[0].db_object_name == "Orders"

    def test_no_match_bare_sql_keyword(self):
        """Bare SQL keyword outside string literal not matched."""
        code = "// SELECT * FROM Users\nvar x = 1;"
        stripped = _strip_cs_comments(code)
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(stripped, Path("test.cs"), "TestProject", pattern)
        sql_deps = [d for d in deps if d.db_object_type == "sql_table"]
        assert len(sql_deps) == 0


# ===========================================================================
# TestConnectionStringDetection
# ===========================================================================
class TestConnectionStringDetection:
    def test_detect_connection_string(self):
        """Connection string pattern in string literal detected."""
        code = 'var cs = "Server=myserver;Database=mydb;Trusted_Connection=True";'
        pattern = _build_sproc_pattern(DEFAULT_SPROC_PREFIXES)
        deps = _scan_file(code, Path("test.cs"), "TestProject", pattern)
        conn_deps = [d for d in deps if d.db_object_type == "connection_string"]
        assert len(conn_deps) >= 1
        names = {d.db_object_name for d in conn_deps}
        assert any("myserver" in n or "mydb" in n for n in names)


# ===========================================================================
# TestBuildDbMatrix
# ===========================================================================
class TestBuildDbMatrix:
    def test_shared_sprocs_appear_in_matrix(self):
        """Sprocs shared by 2+ projects appear in matrix."""
        deps = [
            DbDependency("dbo.sp_Insert", "sproc", Path("a.cs"), "ProjectA",
                          "string_literal"),
            DbDependency("dbo.sp_Insert", "sproc", Path("b.cs"), "ProjectB",
                          "string_literal"),
            DbDependency("dbo.sp_OnlyA", "sproc", Path("a2.cs"), "ProjectA",
                          "string_literal"),
        ]
        matrix = build_db_dependency_matrix(deps)
        assert "dbo.sp_Insert" in matrix
        assert len(matrix["dbo.sp_Insert"]) == 2
        assert "dbo.sp_OnlyA" in matrix
        assert len(matrix["dbo.sp_OnlyA"]) == 1

    def test_ef_models_in_matrix(self):
        """EF models shared across projects appear in matrix."""
        deps = [
            DbDependency("User", "ef_model", Path("a.cs"), "ProjectA", "ef_dbset"),
            DbDependency("User", "ef_model", Path("b.cs"), "ProjectB", "ef_dbset"),
        ]
        matrix = build_db_dependency_matrix(deps)
        assert "User" in matrix
        assert len(matrix["User"]) == 2


# ===========================================================================
# TestAddDbEdges
# ===========================================================================
class TestAddDbEdges:
    def _make_graph(self) -> DependencyGraph:
        g = DependencyGraph()
        g.add_node(ProjectNode(path=Path("/a/A.csproj"), name="A"))
        g.add_node(ProjectNode(path=Path("/b/B.csproj"), name="B"))
        g.add_node(ProjectNode(path=Path("/c/C.csproj"), name="C"))
        return g

    def test_add_sproc_shared_edges(self):
        """Shared sproc between A and B creates bidirectional edges."""
        graph = self._make_graph()
        deps = [
            DbDependency("dbo.sp_Shared", "sproc", Path("a.cs"), "A",
                          "string_literal"),
            DbDependency("dbo.sp_Shared", "sproc", Path("b.cs"), "B",
                          "string_literal"),
        ]
        edges_added = add_db_edges_to_graph(graph, deps)
        assert edges_added == 2

        # Check edges exist in both directions
        a_edges = graph.get_edges_from("A")
        b_edges = graph.get_edges_from("B")
        assert any(e.target == "B" and e.edge_type == "sproc_shared" for e in a_edges)
        assert any(e.target == "A" and e.edge_type == "sproc_shared" for e in b_edges)

    def test_no_edges_for_single_project(self):
        """Sproc used by only one project creates no edges."""
        graph = self._make_graph()
        deps = [
            DbDependency("dbo.sp_OnlyA", "sproc", Path("a.cs"), "A",
                          "string_literal"),
        ]
        edges_added = add_db_edges_to_graph(graph, deps)
        assert edges_added == 0

    def test_three_way_sharing(self):
        """Sproc shared by 3 projects creates 6 edges (3 pairs, bidirectional)."""
        graph = self._make_graph()
        deps = [
            DbDependency("dbo.sp_All", "sproc", Path("a.cs"), "A", "string_literal"),
            DbDependency("dbo.sp_All", "sproc", Path("b.cs"), "B", "string_literal"),
            DbDependency("dbo.sp_All", "sproc", Path("c.cs"), "C", "string_literal"),
        ]
        edges_added = add_db_edges_to_graph(graph, deps)
        assert edges_added == 6

    def test_multiple_shared_objects_aggregated(self):
        """Multiple shared sprocs between A and B produce 1 edge per direction."""
        graph = self._make_graph()
        deps = [
            DbDependency("dbo.sp_X", "sproc", Path("a.cs"), "A", "string_literal"),
            DbDependency("dbo.sp_X", "sproc", Path("b.cs"), "B", "string_literal"),
            DbDependency("dbo.sp_Y", "sproc", Path("a2.cs"), "A", "string_literal"),
            DbDependency("dbo.sp_Y", "sproc", Path("b2.cs"), "B", "string_literal"),
            DbDependency("dbo.sp_Z", "sproc", Path("a3.cs"), "A", "string_literal"),
            DbDependency("dbo.sp_Z", "sproc", Path("b3.cs"), "B", "string_literal"),
        ]
        edges_added = add_db_edges_to_graph(graph, deps)
        # 1 pair * 2 directions = 2 edges (aggregated, not 6)
        assert edges_added == 2

        a_edges = [e for e in graph.get_edges_from("A") if e.edge_type == "sproc_shared"]
        assert len(a_edges) == 1
        assert a_edges[0].weight == 3.0
        assert set(a_edges[0].evidence) == {"dbo.sp_X", "dbo.sp_Y", "dbo.sp_Z"}

    def test_missing_node_skipped(self):
        """Edges not added if project node doesn't exist in graph."""
        graph = self._make_graph()
        deps = [
            DbDependency("dbo.sp_X", "sproc", Path("a.cs"), "A", "string_literal"),
            DbDependency("dbo.sp_X", "sproc", Path("z.cs"), "Z", "string_literal"),
        ]
        edges_added = add_db_edges_to_graph(graph, deps)
        assert edges_added == 0


# ===========================================================================
# TestDbConfig
# ===========================================================================
class TestDbConfig:
    def test_default_db_config(self):
        cfg = DbConfig()
        assert cfg.sproc_prefixes == ["sp_", "usp_"]
        assert cfg.include_db_edges is True

    def test_scatter_config_has_db(self):
        cfg = ScatterConfig()
        assert isinstance(cfg.db, DbConfig)

    def test_db_config_from_yaml(self, tmp_path):
        yaml_content = """\
db:
  sproc_prefixes:
    - "sp_"
    - "usp_"
    - "proc_"
  include_db_edges: false
"""
        (tmp_path / ".scatter.yaml").write_text(yaml_content)
        config = load_config(repo_root=tmp_path)
        assert config.db.sproc_prefixes == ["sp_", "usp_", "proc_"]
        assert config.db.include_db_edges is False

    def test_include_db_cli_override(self, tmp_path):
        """--include-db CLI flag flows through to config.db.include_db_edges."""
        from scatter.cli_parser import _build_cli_overrides
        import argparse

        ns = argparse.Namespace(
            google_api_key=None,
            gemini_model=None,
            disable_multiprocessing=False,
            max_depth=None,
            rebuild_graph=False,
            include_db=True,
        )
        overrides = _build_cli_overrides(ns)
        assert overrides.get("db.include_db_edges") is True

        config = load_config(repo_root=tmp_path, cli_overrides=overrides)
        assert config.db.include_db_edges is True


# ===========================================================================
# TestScanSampleProjects (integration)
# ===========================================================================
# ===========================================================================
# TestFileIndex — enclosing_class with non-class types
# ===========================================================================
class TestFileIndex:
    def test_enclosing_struct(self):
        """_FileIndex.enclosing_class finds struct after regex fix."""
        from scatter.scanners.db_scanner import _FileIndex
        code = "public struct MyStruct {\n    var x = 1;\n}"
        idx = _FileIndex(code)
        offset = code.index("var x")
        assert idx.enclosing_class(offset) == "MyStruct"

    def test_enclosing_record(self):
        """_FileIndex.enclosing_class finds record."""
        from scatter.scanners.db_scanner import _FileIndex
        code = "public record MyRecord {\n    var x = 1;\n}"
        idx = _FileIndex(code)
        offset = code.index("var x")
        assert idx.enclosing_class(offset) == "MyRecord"

    def test_enclosing_interface(self):
        """_FileIndex.enclosing_class finds interface."""
        from scatter.scanners.db_scanner import _FileIndex
        code = "public interface IMyService {\n    void Do();\n}"
        idx = _FileIndex(code)
        offset = code.index("void Do")
        assert idx.enclosing_class(offset) == "IMyService"

    def test_before_any_declaration_returns_none(self):
        """No enclosing type before any declaration."""
        from scatter.scanners.db_scanner import _FileIndex
        code = "using System;\nnamespace Foo {\n    public class Bar { }\n}"
        idx = _FileIndex(code)
        offset = code.index("namespace")
        assert idx.enclosing_class(offset) is None


class TestScanSampleProjects:
    def test_scan_real_codebase(self):
        """Integration test against the sample .NET projects in this repo."""
        deps = scan_db_dependencies(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )

        # Should find sproc references in GalaxyWorks.Data and BatchProcessor
        sproc_deps = [d for d in deps if d.db_object_type == "sproc"]
        assert len(sproc_deps) > 0

        # Should find known sprocs
        sproc_names = {d.db_object_name for d in sproc_deps}
        assert "dbo.sp_InsertPortalConfiguration" in sproc_names

        # Should find across multiple projects
        projects_with_sprocs = {d.source_project for d in sproc_deps}
        assert len(projects_with_sprocs) >= 2

    def test_scan_detects_ef_models(self):
        """Integration: EF DbSet models detected in BatchProcessor."""
        deps = scan_db_dependencies(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
        )

        ef_deps = [d for d in deps if d.db_object_type == "ef_model"]
        assert len(ef_deps) > 0
        model_names = {d.db_object_name for d in ef_deps}
        assert "PortalConfiguration" in model_names

    def test_integration_with_graph_builder(self):
        """Integration: DB edges added to graph via graph_builder."""
        from scatter.analyzers.graph_builder import build_dependency_graph
        from scatter.analyzers.coupling_analyzer import compute_all_metrics

        graph = build_dependency_graph(
            REPO_ROOT,
            disable_multiprocessing=True,
            exclude_patterns=["*/bin/*", "*/obj/*", "*/temp_test_data/*"],
            include_db_dependencies=True,
        )

        # Should have sproc_shared edges
        sproc_edges = [e for e in graph.all_edges if e.edge_type == "sproc_shared"]
        assert len(sproc_edges) > 0

        # Metrics still work with new edge type
        metrics = compute_all_metrics(graph)
        assert len(metrics) == graph.node_count
