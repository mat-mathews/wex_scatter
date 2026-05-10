"""Tests for extract_pr_changed_types() and _diff_type_sets()."""

import pytest
import git

from scatter.analyzers.git_analyzer import _diff_type_sets, extract_pr_changed_types


CS_INITIAL = "namespace MyProject\n{\n    public class Initial { }\n}\n"


@pytest.fixture
def repo_path(tmp_path):
    """Return resolved tmp_path (handles macOS /var -> /private/var symlink)."""
    return tmp_path.resolve()


def _init_repo(repo_dir):
    """Create a git repo with a .csproj and initial commit on main."""
    repo = git.Repo.init(repo_dir)
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    proj_dir = repo_dir / "MyProject"
    proj_dir.mkdir()

    csproj = proj_dir / "MyProject.csproj"
    csproj.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup></PropertyGroup></Project>')

    initial_cs = proj_dir / "Initial.cs"
    initial_cs.write_text(CS_INITIAL)

    repo.index.add([str(csproj), str(initial_cs)])
    repo.index.commit("Initial commit")

    if repo.active_branch.name != "main":
        repo.active_branch.rename("main")

    return repo


def _create_feature_branch(repo, branch_name="feature"):
    """Create and checkout a feature branch from main."""
    repo.create_head(branch_name, repo.heads.main.commit)
    repo.heads[branch_name].checkout()
    return repo


class TestExtractPrChangedTypes:
    """Tests for extract_pr_changed_types with real git repos."""

    def test_file_added_with_new_class(self, repo_path):
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        new_file = repo_path / "MyProject" / "NewService.cs"
        new_file.write_text(
            "namespace MyProject\n"
            "{\n"
            "    public class NewService { }\n"
            "    public interface INewService { }\n"
            "}\n"
        )
        repo.index.add([str(new_file)])
        repo.index.commit("Add NewService")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")

        assert len(result) == 2
        names = {ct.name for ct in result}
        assert "NewService" in names
        assert "INewService" in names
        assert all(ct.change_kind == "added" for ct in result)
        assert all(ct.owning_project == "MyProject" for ct in result)

        service = next(ct for ct in result if ct.name == "NewService")
        assert service.kind == "class"
        iface = next(ct for ct in result if ct.name == "INewService")
        assert iface.kind == "interface"

    def test_file_modified_class_body_changed(self, repo_path):
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        cs_file = repo_path / "MyProject" / "Initial.cs"
        cs_file.write_text(
            "namespace MyProject\n"
            "{\n"
            "    public class Initial\n"
            "    {\n"
            "        public void DoStuff() { }\n"
            "    }\n"
            "}\n"
        )
        repo.index.add([str(cs_file)])
        repo.index.commit("Modify Initial")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")

        assert len(result) == 1
        assert result[0].name == "Initial"
        assert result[0].change_kind == "modified"
        assert result[0].kind == "class"

    def test_file_deleted(self, repo_path):
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        cs_file = repo_path / "MyProject" / "Initial.cs"
        repo.index.remove([str(cs_file)])
        cs_file.unlink()
        repo.index.commit("Delete Initial.cs")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")

        assert len(result) == 1
        assert result[0].name == "Initial"
        assert result[0].change_kind == "deleted"

    def test_new_type_added_to_existing_file(self, repo_path):
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        cs_file = repo_path / "MyProject" / "Initial.cs"
        cs_file.write_text(
            "namespace MyProject\n"
            "{\n"
            "    public class Initial { }\n"
            "    public enum Status { Active, Inactive }\n"
            "}\n"
        )
        repo.index.add([str(cs_file)])
        repo.index.commit("Add Status enum")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")

        names_and_kinds = {(ct.name, ct.change_kind) for ct in result}
        assert ("Initial", "modified") in names_and_kinds
        assert ("Status", "added") in names_and_kinds

    def test_type_removed_from_existing_file(self, repo_path):
        """When a file has two types on base and one is removed, that type is 'deleted'."""
        repo = _init_repo(repo_path)

        # Add a second type on main first
        cs_file = repo_path / "MyProject" / "Initial.cs"
        cs_file.write_text(
            "namespace MyProject\n"
            "{\n"
            "    public class Initial { }\n"
            "    public class ToBeRemoved { }\n"
            "}\n"
        )
        repo.index.add([str(cs_file)])
        repo.index.commit("Add ToBeRemoved")

        _create_feature_branch(repo)

        # Remove the second type
        cs_file.write_text("namespace MyProject\n{\n    public class Initial { }\n}\n")
        repo.index.add([str(cs_file)])
        repo.index.commit("Remove ToBeRemoved")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")

        names_and_kinds = {(ct.name, ct.change_kind) for ct in result}
        assert ("ToBeRemoved", "deleted") in names_and_kinds
        assert ("Initial", "modified") in names_and_kinds

    def test_file_renamed(self, repo_path):
        """Renamed files should use b_path for project and produce types."""
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        old_path = repo_path / "MyProject" / "Initial.cs"
        new_path = repo_path / "MyProject" / "Renamed.cs"
        content = old_path.read_text()
        new_path.write_text(content)
        repo.index.remove([str(old_path)])
        old_path.unlink()
        repo.index.add([str(new_path)])
        repo.index.commit("Rename Initial.cs to Renamed.cs")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")

        # Git may detect this as rename (R) or as delete+add (D+A).
        # Either way we should get the Initial type with correct owning project.
        assert len(result) >= 1
        assert all(ct.owning_project == "MyProject" for ct in result)
        # The Initial class must appear regardless of how git classifies the change
        initial_types = [ct for ct in result if ct.name == "Initial"]
        assert len(initial_types) >= 1
        # change_kind should be "modified" (R), "deleted" (D side), or "added" (A side)
        assert initial_types[0].change_kind in ("modified", "deleted", "added")

    def test_branch_not_found_raises_value_error(self, repo_path):
        _init_repo(repo_path)

        with pytest.raises(ValueError, match="Cannot resolve"):
            extract_pr_changed_types(str(repo_path), "nonexistent-branch", "main")

    def test_tag_accepted_as_feature_ref(self, repo_path):
        """Tags should be accepted as valid refs."""
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)
        cs_file = repo_path / "MyProject" / "Tagged.cs"
        cs_file.write_text("public class Tagged { }\n")
        repo.index.add([str(cs_file)])
        repo.index.commit("add tagged class")
        repo.create_tag("v1.0.0")
        repo.heads.main.checkout()

        result = extract_pr_changed_types(str(repo_path), "v1.0.0", "main")
        assert any(ct.name == "Tagged" for ct in result)

    def test_sha_accepted_as_feature_ref(self, repo_path):
        """Full SHA should be accepted as a valid ref."""
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)
        cs_file = repo_path / "MyProject" / "BySha.cs"
        cs_file.write_text("public class BySha { }\n")
        repo.index.add([str(cs_file)])
        commit = repo.index.commit("add sha class")
        sha = commit.hexsha
        repo.heads.main.checkout()

        result = extract_pr_changed_types(str(repo_path), sha, "main")
        assert any(ct.name == "BySha" for ct in result)

    def test_no_merge_base_raises_value_error(self, repo_path):
        """Two branches with no common ancestor should raise ValueError."""
        repo = _init_repo(repo_path)

        # Create an orphan branch (no common ancestor with main)
        repo.git.checkout("--orphan", "orphan-branch")
        orphan_file = repo_path / "MyProject" / "Orphan.cs"
        orphan_file.write_text("public class Foo {\n}\n")
        repo.index.add([str(orphan_file)])
        repo.index.commit("Orphan commit")

        with pytest.raises(ValueError, match="No common ancestor"):
            extract_pr_changed_types(str(repo_path), "orphan-branch", "main")

    def test_no_cs_changes_returns_empty(self, repo_path):
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        txt_file = repo_path / "README.md"
        txt_file.write_text("Hello")
        repo.index.add([str(txt_file)])
        repo.index.commit("Add readme")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")
        assert result == []

    def test_cs_file_without_csproj_skipped(self, repo_path):
        """A .cs file with no .csproj up the tree should be skipped."""
        repo = _init_repo(repo_path)
        _create_feature_branch(repo)

        loose_dir = repo_path / "scripts"
        loose_dir.mkdir()
        loose_cs = loose_dir / "Helper.cs"
        loose_cs.write_text("public class Helper {\n}\n")
        repo.index.add([str(loose_cs)])
        repo.index.commit("Add loose cs file")

        result = extract_pr_changed_types(str(repo_path), "feature", "main")
        assert all(ct.owning_project == "MyProject" for ct in result) or result == []


class TestDiffTypeSets:
    """Standalone tests for _diff_type_sets."""

    def test_empty_both(self):
        assert _diff_type_sets([], []) == []

    def test_empty_base_all_added(self):
        result = _diff_type_sets([], [("Foo", "class"), ("Bar", "interface")])
        assert len(result) == 2
        assert all(r[2] == "added" for r in result)

    def test_empty_feature_all_deleted(self):
        result = _diff_type_sets([("Foo", "class")], [])
        assert len(result) == 1
        assert result[0] == ("Foo", "class", "deleted")

    def test_same_types_all_modified(self):
        base = [("Foo", "class"), ("Bar", "interface")]
        feat = [("Foo", "class"), ("Bar", "interface")]
        result = _diff_type_sets(base, feat)
        assert len(result) == 2
        assert all(r[2] == "modified" for r in result)

    def test_mixed_changes(self):
        base = [("Foo", "class"), ("Old", "enum")]
        feat = [("Foo", "class"), ("New", "struct")]
        result = _diff_type_sets(base, feat)
        by_name = {r[0]: r[2] for r in result}
        assert by_name["Foo"] == "modified"
        assert by_name["Old"] == "deleted"
        assert by_name["New"] == "added"

    def test_type_kind_change(self):
        """If a type changes kind (class → record), feature kind is used."""
        base = [("Foo", "class")]
        feat = [("Foo", "record")]
        result = _diff_type_sets(base, feat)
        assert len(result) == 1
        assert result[0] == ("Foo", "record", "modified")
