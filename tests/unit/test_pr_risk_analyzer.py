"""Tests for the PR risk analyzer."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import git
import pytest

from scatter.analyzers.pr_risk_analyzer import analyze_pr_risk
from scatter.core.risk_models import RiskLevel


@pytest.fixture
def repo_path(tmp_path):
    """Return resolved tmp_path."""
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

    cs = proj_dir / "Initial.cs"
    cs.write_text("namespace MyProject\n{\n    public class Initial { }\n}\n")

    repo.index.add([str(csproj), str(cs)])
    repo.index.commit("Initial commit")

    if repo.active_branch.name != "main":
        repo.active_branch.rename("main")

    return repo


class TestAnalyzePrRisk:
    """Tests for analyze_pr_risk."""

    def test_empty_diff_returns_green(self, repo_path):
        """Same branch compared to itself → GREEN, no types."""
        repo = _init_repo(repo_path)
        # Create a feature branch at the same commit
        repo.create_head("feature", repo.heads.main.commit)

        report = analyze_pr_risk(repo_path, "feature", "main")

        assert report.risk_level == RiskLevel.GREEN
        assert report.changed_types == []
        assert len(report.profiles) == 0
        assert report.aggregate.composite_score == 0.0

    def test_added_types_low_risk(self, repo_path):
        """Adding new types should produce low change_surface."""
        repo = _init_repo(repo_path)
        repo.create_head("feature", repo.heads.main.commit)
        repo.heads.feature.checkout()

        new_file = repo_path / "MyProject" / "NewService.cs"
        new_file.write_text("namespace MyProject\n{\n    public class NewService { }\n}\n")
        repo.index.add([str(new_file)])
        repo.index.commit("Add NewService")

        report = analyze_pr_risk(repo_path, "feature", "main")

        assert report.risk_level == RiskLevel.GREEN
        assert len(report.changed_types) == 1
        assert report.changed_types[0].change_kind == "added"
        # change_surface for additions only → 0.1
        cs_dim = report.profiles[0].change_surface
        assert cs_dim.score == 0.1
        assert cs_dim.data_available is True

    def test_deleted_types_high_change_surface(self, repo_path):
        """Deleting types should score high on change_surface."""
        repo = _init_repo(repo_path)
        repo.create_head("feature", repo.heads.main.commit)
        repo.heads.feature.checkout()

        cs_file = repo_path / "MyProject" / "Initial.cs"
        repo.index.remove([str(cs_file)])
        cs_file.unlink()
        repo.index.commit("Delete Initial")

        report = analyze_pr_risk(repo_path, "feature", "main")

        assert len(report.changed_types) == 1
        assert report.changed_types[0].change_kind == "deleted"
        cs_dim = report.profiles[0].change_surface
        assert cs_dim.score >= 0.7

    def test_no_graph_partial_scoring_with_warning(self, repo_path):
        """Without graph, should use partial scoring and add warning."""
        repo = _init_repo(repo_path)
        repo.create_head("feature", repo.heads.main.commit)
        repo.heads.feature.checkout()

        new_file = repo_path / "MyProject" / "New.cs"
        new_file.write_text("namespace MyProject\n{\n    public class New { }\n}\n")
        repo.index.add([str(new_file)])
        repo.index.commit("Add")

        report = analyze_pr_risk(repo_path, "feature", "main", graph_ctx=None)

        assert report.graph_available is False
        assert len(report.warnings) > 0
        assert "search-scope" in report.warnings[0].lower() or "graph" in report.warnings[0].lower()

    def test_multiple_projects_aggregate_is_max(self, repo_path):
        """When multiple projects changed, aggregate uses max composite."""
        repo = _init_repo(repo_path)

        # Add second project
        proj2_dir = repo_path / "OtherProject"
        proj2_dir.mkdir()
        csproj2 = proj2_dir / "OtherProject.csproj"
        csproj2.write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        cs2 = proj2_dir / "Other.cs"
        cs2.write_text("namespace OtherProject\n{\n    public class Other { }\n}\n")
        repo.index.add([str(csproj2), str(cs2)])
        repo.index.commit("Add OtherProject")

        repo.create_head("feature", repo.heads.main.commit)
        repo.heads.feature.checkout()

        # Delete from first project (high risk), add to second (low risk)
        cs_file = repo_path / "MyProject" / "Initial.cs"
        repo.index.remove([str(cs_file)])
        cs_file.unlink()

        new_file = proj2_dir / "New.cs"
        new_file.write_text("namespace OtherProject\n{\n    public class New { }\n}\n")
        repo.index.add([str(new_file)])
        repo.index.commit("Delete from MyProject, add to OtherProject")

        report = analyze_pr_risk(repo_path, "feature", "main")

        assert len(report.profiles) == 2
        # Aggregate composite >= the higher of the two
        scores = [p.composite_score for p in report.profiles]
        assert report.aggregate.composite_score >= max(scores) - 0.001

    def test_report_has_duration(self, repo_path):
        repo = _init_repo(repo_path)
        repo.create_head("feature", repo.heads.main.commit)

        report = analyze_pr_risk(repo_path, "feature", "main")
        assert report.duration_ms >= 0

    def test_branch_not_found_raises(self, repo_path):
        _init_repo(repo_path)

        with pytest.raises(ValueError, match="Cannot resolve"):
            analyze_pr_risk(repo_path, "nonexistent", "main")

    def test_graph_path_populates_consumers(self, repo_path):
        """With a mocked GraphContext, consumer counts should flow through to the report."""
        repo = _init_repo(repo_path)
        repo.create_head("feature", repo.heads.main.commit)
        repo.heads.feature.checkout()

        new_file = repo_path / "MyProject" / "NewService.cs"
        new_file.write_text("namespace MyProject\n{\n    public class NewService { }\n}\n")
        repo.index.add([str(new_file)])
        repo.index.commit("Add NewService")

        # Build a mock GraphContext
        mock_graph = MagicMock()
        mock_graph.get_consumer_names.side_effect = lambda name: (
            {"ConsumerA", "ConsumerB"} if name == "MyProject" else set()
        )
        mock_node = MagicMock()
        mock_node.cluster_id = "cluster-1"
        mock_graph.get_node.return_value = mock_node

        mock_graph_ctx = SimpleNamespace(
            graph=mock_graph,
            metrics={
                "MyProject": MagicMock(
                    fan_in=2,
                    fan_out=1,
                    coupling_score=10.0,
                    afferent_coupling=2,
                    efferent_coupling=1,
                    instability=0.33,
                    shared_db_density=0.0,
                )
            },
            cycles=[],
            cycle_members=set(),
        )

        report = analyze_pr_risk(repo_path, "feature", "main", graph_ctx=mock_graph_ctx)

        assert report.graph_available is True
        assert report.total_direct_consumers == 2
        assert len(report.unique_consumers) >= 2
        assert "ConsumerA" in report.unique_consumers
        assert "ConsumerB" in report.unique_consumers
        assert len(report.warnings) == 0
        # Profile should have graph-derived dimensions populated
        profile = report.profiles[0]
        assert profile.structural.data_available is True
        assert profile.change_surface.data_available is True
