"""Tests for prediction logging — Phase 3."""

import json
from pathlib import Path
from types import SimpleNamespace

import git
import pytest

from scatter.core.models import ChangedType
from scatter.core.risk_models import AggregateRisk, RiskDimension, RiskLevel
from scatter.store.prediction_log import (
    _SCHEMA_VERSION,
    append_prediction,
    build_prediction_record,
)


def _make_dimension(name: str, label: str, score: float = 0.0, data_available: bool = True):
    return RiskDimension(
        name=name,
        label=label,
        score=score,
        severity="low",
        factors=[],
        raw_metrics={},
        data_available=data_available,
    )


def _make_report(
    risk_factors=None,
    changed_types=None,
    graph_available=True,
    database_data_available=True,
):
    """Build a minimal PRRiskReport for testing."""
    from scatter.core.models import PRRiskReport

    dims = {
        "structural": _make_dimension("structural", "Structural coupling", 0.3),
        "instability": _make_dimension("instability", "Instability", 0.2),
        "cycle": _make_dimension("cycle", "Cycle entanglement", 0.0),
        "database": _make_dimension(
            "database", "Database coupling", 0.0, data_available=database_data_available
        ),
        "blast_radius": _make_dimension("blast_radius", "Blast radius", 0.5),
        "domain_boundary": _make_dimension("domain_boundary", "Domain boundary", 0.1),
        "change_surface": _make_dimension("change_surface", "Change surface", 0.4),
    }

    agg = AggregateRisk(
        profiles=[],
        **dims,
        composite_score=0.35,
        risk_level=RiskLevel.GREEN,
        risk_factors=risk_factors or ["Factor A", "Factor B"],
    )

    if changed_types is None:
        changed_types = [
            ChangedType(
                name="Widget",
                kind="class",
                change_kind="modified",
                owning_project="MyProject",
                owning_project_path="MyProject/MyProject.csproj",
                file_path="MyProject/Widget.cs",
            )
        ]

    return PRRiskReport(
        branch_name="feat/test",
        base_branch="main",
        changed_types=changed_types,
        aggregate=agg,
        profiles=[],
        total_direct_consumers=3,
        total_transitive_consumers=7,
        graph_available=graph_available,
        duration_ms=123,
    )


class TestBuildPredictionRecord:
    def test_round_trip_serialization(self):
        """Record serializes to JSON and deserializes back identically."""
        report = _make_report()
        record = build_prediction_record(
            report, head_sha="abc123", base_sha="def456", repo_id="test/repo"
        )
        serialized = json.dumps(record)
        deserialized = json.loads(serialized)
        assert deserialized == record

    def test_fields_from_report(self):
        """All fields map correctly from PRRiskReport."""
        report = _make_report()
        record = build_prediction_record(report, head_sha="aaa", base_sha="bbb", repo_id="my/repo")

        assert record["schema_version"] == _SCHEMA_VERSION
        assert record["repo"] == "my/repo"
        assert record["branch"] == "feat/test"
        assert record["base_branch"] == "main"
        assert record["head_sha"] == "aaa"
        assert record["base_sha"] == "bbb"
        assert record["composite_score"] == 0.35
        assert record["risk_level"] == "GREEN"
        assert record["changed_type_count"] == 1
        assert record["direct_consumers"] == 3
        assert record["transitive_consumers"] == 7
        assert record["graph_available"] is True
        assert record["duration_ms"] == 123
        assert record["outcome"] is None
        assert record["outcome_signals"] is None
        assert record["merge_sha"] is None
        assert "timestamp" in record
        assert "scatter_version" in record

    def test_dimension_data_available(self):
        """Reflects per-dimension availability (database=False when graph unavailable)."""
        report = _make_report(database_data_available=False)
        record = build_prediction_record(report, head_sha=None, base_sha=None, repo_id="x")

        assert record["dimension_data_available"]["database"] is False
        assert record["dimension_data_available"]["structural"] is True

    def test_risk_factors_capped_at_three(self):
        """4+ factors in report -> only 3 in record."""
        report = _make_report(risk_factors=["A", "B", "C", "D", "E"])
        record = build_prediction_record(report, head_sha=None, base_sha=None, repo_id="x")

        assert len(record["risk_factors"]) == 3
        assert record["risk_factors"] == ["A", "B", "C"]

    def test_pr_number_from_env(self, monkeypatch):
        """Set SCATTER_PR_NUMBER=42, verify record has pr_number: 42."""
        monkeypatch.setenv("SCATTER_PR_NUMBER", "42")
        report = _make_report()
        record = build_prediction_record(report, head_sha=None, base_sha=None, repo_id="x")

        assert record["pr_number"] == 42

    def test_pr_number_invalid_env_returns_none(self, monkeypatch):
        """Non-numeric SCATTER_PR_NUMBER falls back to None."""
        monkeypatch.setenv("SCATTER_PR_NUMBER", "not_a_number")
        report = _make_report()
        record = build_prediction_record(report, head_sha=None, base_sha=None, repo_id="x")

        assert record["pr_number"] is None

    def test_pr_number_none_without_env(self, monkeypatch):
        """Without SCATTER_PR_NUMBER, pr_number is None."""
        monkeypatch.delenv("SCATTER_PR_NUMBER", raising=False)
        report = _make_report()
        record = build_prediction_record(report, head_sha=None, base_sha=None, repo_id="x")

        assert record["pr_number"] is None


class TestAppendPrediction:
    def test_creates_file_and_appends(self, tmp_path):
        """First call creates, second appends, both valid JSONL."""
        record1 = {"id": 1, "score": 0.5}
        record2 = {"id": 2, "score": 0.8}

        append_prediction(record1, tmp_path)
        append_prediction(record2, tmp_path)

        log_path = tmp_path / ".scatter" / "predictions.jsonl"
        assert log_path.exists()

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == record1
        assert json.loads(lines[1]) == record2

    def test_size_warning(self, tmp_path, caplog):
        """Warns when file exceeds 10MB."""
        log_path = tmp_path / ".scatter" / "predictions.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Write >10MB of data
        log_path.write_bytes(b"x" * (11 * 1024 * 1024))

        import logging

        with caplog.at_level(logging.WARNING):
            append_prediction({"test": True}, tmp_path)

        assert "Consider archiving" in caplog.text

    def test_never_raises_on_error(self):
        """Bad path doesn't raise."""
        # /dev/null/impossible is not a valid directory
        bad_path = Path("/dev/null/impossible/path")
        # Should not raise
        append_prediction({"test": True}, bad_path)


class TestIntegration:
    """Integration test: call run_pr_risk_mode with a real git repo."""

    @pytest.fixture()
    def git_repo(self, tmp_path):
        """Create a minimal git repo with a .cs file change on a branch."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        repo = git.Repo.init(repo_dir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        proj_dir = repo_dir / "MyProject"
        proj_dir.mkdir()

        (proj_dir / "MyProject.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup></PropertyGroup></Project>'
        )
        (proj_dir / "Widget.cs").write_text(
            "namespace MyProject\n{\n    public class Widget { }\n}\n"
        )

        repo.index.add([str(proj_dir / "MyProject.csproj"), str(proj_dir / "Widget.cs")])
        repo.index.commit("Initial commit")
        if repo.active_branch.name != "main":
            repo.active_branch.rename("main")

        # Feature branch with a new type
        repo.create_head("feat/gadget", repo.heads.main.commit)
        repo.heads["feat/gadget"].checkout()
        (proj_dir / "Gadget.cs").write_text(
            "namespace MyProject\n{\n    public class Gadget { }\n}\n"
        )
        repo.index.add([str(proj_dir / "Gadget.cs")])
        repo.index.commit("Add Gadget")

        # Back to main so working tree is clean
        repo.heads.main.checkout()

        return repo_dir

    def test_pr_risk_mode_writes_prediction(self, git_repo):
        """run_pr_risk_mode creates .scatter/predictions.jsonl with valid JSON."""
        from scatter.analysis import ModeContext
        from scatter.config import ScatterConfig
        from scatter.modes.pr_risk import run_pr_risk_mode

        ctx = ModeContext(
            search_scope=git_repo,
            repo_path=git_repo,
            config=ScatterConfig(),
            pipeline_map={},
            solution_file_cache=[],
            batch_job_map={},
            ai_provider=None,
        )

        args = SimpleNamespace(
            branch_name="feat/gadget",
            base_branch="main",
            output_format="console",
            output_file=None,
            collapsible=False,
            no_prediction_log=False,
        )

        import time

        run_pr_risk_mode(args, ctx, start_time=time.time())

        log_path = git_repo / ".scatter" / "predictions.jsonl"
        assert log_path.exists(), "predictions.jsonl should be created"

        line = log_path.read_text().strip().split("\n")[0]
        record = json.loads(line)
        assert record["schema_version"] == _SCHEMA_VERSION
        assert record["branch"] == "feat/gadget"
        assert record["base_branch"] == "main"
        assert record["risk_level"] in ("GREEN", "YELLOW", "RED")

    def test_no_prediction_log_flag_skips_write(self, git_repo):
        """--no-prediction-log prevents predictions.jsonl from being created."""
        from scatter.analysis import ModeContext
        from scatter.config import ScatterConfig
        from scatter.modes.pr_risk import run_pr_risk_mode

        ctx = ModeContext(
            search_scope=git_repo,
            repo_path=git_repo,
            config=ScatterConfig(),
            pipeline_map={},
            solution_file_cache=[],
            batch_job_map={},
            ai_provider=None,
        )

        args = SimpleNamespace(
            branch_name="feat/gadget",
            base_branch="main",
            output_format="console",
            output_file=None,
            collapsible=False,
            no_prediction_log=True,
        )

        import time

        run_pr_risk_mode(args, ctx, start_time=time.time())

        log_path = git_repo / ".scatter" / "predictions.jsonl"
        assert not log_path.exists(), (
            "predictions.jsonl should NOT be created with --no-prediction-log"
        )


class TestResolveBranchSHAs:
    """Tests for resolve_branch_shas helper."""

    def test_resolves_shas_from_real_repo(self, tmp_path):
        """Returns head/base SHAs for known branches."""
        from scatter.analyzers.git_analyzer import resolve_branch_shas

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        (tmp_path / "f.txt").write_text("init")
        repo.index.add(["f.txt"])
        repo.index.commit("init")
        if repo.active_branch.name != "main":
            repo.active_branch.rename("main")
        repo.create_head("feat", repo.heads.main.commit)

        result = resolve_branch_shas(str(tmp_path), "feat", "main")

        assert result.head_sha is not None
        assert result.base_sha is not None
        assert len(result.head_sha) == 40
        # No remote configured, so repo_id should be resolved path
        assert result.repo_id == str(tmp_path.resolve())

    def test_missing_remote_falls_back_to_path(self, tmp_path):
        """Repo without an origin remote uses resolved path as repo_id."""
        from scatter.analyzers.git_analyzer import resolve_branch_shas

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        (tmp_path / "f.txt").write_text("init")
        repo.index.add(["f.txt"])
        repo.index.commit("init")
        if repo.active_branch.name != "main":
            repo.active_branch.rename("main")

        result = resolve_branch_shas(str(tmp_path), "main", "main")

        assert result.repo_id == str(tmp_path.resolve())

    def test_invalid_repo_never_raises(self):
        """Invalid repo path returns defaults without raising."""
        from scatter.analyzers.git_analyzer import resolve_branch_shas

        result = resolve_branch_shas("/nonexistent/path", "feat", "main")

        assert result.head_sha is None
        assert result.base_sha is None
        assert result.repo_id == "/nonexistent/path"

    def test_missing_branch_returns_none_sha(self, tmp_path):
        """Branch that doesn't exist returns None for that SHA."""
        from scatter.analyzers.git_analyzer import resolve_branch_shas

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        (tmp_path / "f.txt").write_text("init")
        repo.index.add(["f.txt"])
        repo.index.commit("init")
        if repo.active_branch.name != "main":
            repo.active_branch.rename("main")

        result = resolve_branch_shas(str(tmp_path), "nonexistent", "main")

        assert result.head_sha is None
        assert result.base_sha is not None
