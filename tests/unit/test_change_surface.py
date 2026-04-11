"""Tests for score_change_surface() dimension scorer."""


from scatter.analyzers.risk_dimensions import score_change_surface
from scatter.core.models import ChangedType


def _make_ct(
    name: str = "Foo",
    kind: str = "class",
    change_kind: str = "modified",
    project: str = "MyProject",
) -> ChangedType:
    return ChangedType(
        name=name,
        kind=kind,
        change_kind=change_kind,
        owning_project=project,
        owning_project_path=f"{project}/{project}.csproj",
        file_path=f"{project}/Foo.cs",
    )


class TestScoreChangeSurface:
    """Unit tests for score_change_surface."""

    def test_no_types_returns_zero(self):
        result = score_change_surface([], "MyProject")
        assert result.score == 0.0
        assert result.data_available is True

    def test_only_additions_returns_low(self):
        types = [_make_ct(change_kind="added")]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.1

    def test_single_deletion_returns_high(self):
        types = [_make_ct(change_kind="deleted")]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.7

    def test_multiple_deletions_scale_toward_one(self):
        types = [
            _make_ct(name="A", change_kind="deleted"),
            _make_ct(name="B", change_kind="deleted"),
            _make_ct(name="C", change_kind="deleted"),
        ]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.9

    def test_deletions_cap_at_one(self):
        types = [_make_ct(name=f"T{i}", change_kind="deleted") for i in range(10)]
        result = score_change_surface(types, "MyProject")
        assert result.score == 1.0

    def test_interface_mod_higher_than_class_mod(self):
        iface = score_change_surface(
            [_make_ct(kind="interface", change_kind="modified")], "MyProject"
        )
        cls = score_change_surface([_make_ct(kind="class", change_kind="modified")], "MyProject")
        assert iface.score > cls.score

    def test_mixed_deletion_wins_over_class_mod(self):
        """When both deletions and class mods exist, deletion score dominates (max)."""
        types = [
            _make_ct(name="A", change_kind="deleted"),
            _make_ct(name="B", kind="class", change_kind="modified"),
        ]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.7  # deletion score

    def test_filters_to_target_project_only(self):
        types = [
            _make_ct(name="A", change_kind="deleted", project="MyProject"),
            _make_ct(name="B", change_kind="deleted", project="OtherProject"),
        ]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.7  # only one deletion (from MyProject)
        assert result.raw_metrics["deletions"] == 1

    def test_monotonicity_more_dangerous_higher_score(self):
        """Adding more dangerous changes should not decrease the score."""
        base = [_make_ct(name="A", change_kind="added")]
        with_mod = base + [_make_ct(name="B", kind="class", change_kind="modified")]
        with_del = with_mod + [_make_ct(name="C", change_kind="deleted")]

        s1 = score_change_surface(base, "MyProject").score
        s2 = score_change_surface(with_mod, "MyProject").score
        s3 = score_change_surface(with_del, "MyProject").score

        assert s1 <= s2 <= s3

    def test_no_matching_project_returns_zero(self):
        types = [_make_ct(project="OtherProject")]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.0

    def test_factors_describe_deletions(self):
        types = [_make_ct(name="Foo", change_kind="deleted")]
        result = score_change_surface(types, "MyProject")
        assert any("deleted" in f for f in result.factors)

    def test_class_mod_score_scales(self):
        types = [_make_ct(name=f"C{i}", kind="class", change_kind="modified") for i in range(6)]
        result = score_change_surface(types, "MyProject")
        # 0.3 + 0.05 * 5 = 0.55, cap 0.6
        assert result.score == 0.55

    def test_class_mod_caps_at_0_6(self):
        types = [_make_ct(name=f"C{i}", kind="class", change_kind="modified") for i in range(20)]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.6

    def test_interface_mod_caps_at_0_8(self):
        types = [
            _make_ct(name=f"I{i}", kind="interface", change_kind="modified") for i in range(10)
        ]
        result = score_change_surface(types, "MyProject")
        assert result.score == 0.8

    def test_raw_metrics_populated(self):
        types = [
            _make_ct(name="A", change_kind="added"),
            _make_ct(name="B", change_kind="deleted"),
            _make_ct(name="C", kind="interface", change_kind="modified"),
            _make_ct(name="D", kind="class", change_kind="modified"),
        ]
        result = score_change_surface(types, "MyProject")
        assert result.raw_metrics["total_changes"] == 4
        assert result.raw_metrics["deletions"] == 1
        assert result.raw_metrics["interface_modifications"] == 1
        assert result.raw_metrics["class_modifications"] == 1
        assert result.raw_metrics["additions"] == 1
