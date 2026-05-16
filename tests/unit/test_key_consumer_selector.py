"""Tests for scatter.analyzers.key_consumer_selector."""

from pathlib import Path

from scatter.analyzers.key_consumer_selector import select_key_consumers, MAX_KEY_CONSUMERS
from scatter.core.models import (
    AnalysisTarget,
    EnrichedConsumer,
    TargetImpact,
)


def _make_target(name: str, consumers: list) -> TargetImpact:
    return TargetImpact(
        target=AnalysisTarget(target_type="project", name=name),
        consumers=consumers,
    )


def _make_consumer(name: str, depth: int = 0, risk: str | None = None) -> EnrichedConsumer:
    return EnrichedConsumer(
        consumer_path=Path(f"/fake/{name}/{name}.csproj"),
        consumer_name=name,
        depth=depth,
        risk_rating=risk,
    )


class TestSelectKeyConsumers:
    def test_multi_root_qualifies(self):
        """Consumer under 2+ roots at depth-0 qualifies."""
        targets = [
            _make_target("Root.A", [_make_consumer("Shared.Lib")]),
            _make_target("Root.B", [_make_consumer("Shared.Lib")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 1
        assert result[0].consumer_name == "Shared.Lib"
        assert result[0].appearances == 2
        assert sorted(result[0].root_targets) == ["Root.A", "Root.B"]

    def test_single_root_high_risk_qualifies(self):
        """Consumer under 1 root with High risk qualifies."""
        targets = [
            _make_target("Root.A", [_make_consumer("Critical.Service", risk="High")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 1
        assert result[0].consumer_name == "Critical.Service"
        assert result[0].max_risk == "High"

    def test_single_root_critical_risk_qualifies(self):
        """Consumer under 1 root with Critical risk qualifies."""
        targets = [
            _make_target("Root.A", [_make_consumer("Core.DB", risk="Critical")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 1
        assert result[0].max_risk == "Critical"

    def test_single_root_medium_risk_excluded(self):
        """Consumer under 1 root with Medium risk does NOT qualify."""
        targets = [
            _make_target("Root.A", [_make_consumer("Peripheral.Lib", risk="Medium")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 0

    def test_depth_1_excluded_even_if_multi_root(self):
        """Consumer at depth=1 does not qualify regardless of root count."""
        targets = [
            _make_target("Root.A", [_make_consumer("Transitive.Lib", depth=1)]),
            _make_target("Root.B", [_make_consumer("Transitive.Lib", depth=1)]),
            _make_target("Root.C", [_make_consumer("Transitive.Lib", depth=1)]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 0

    def test_dedup_same_consumer_same_root(self):
        """Same consumer appearing multiple times under same root counts as 1 appearance."""
        consumer_a = _make_consumer("Dup.Lib")
        consumer_b = _make_consumer("Dup.Lib", risk="Medium")
        targets = [
            _make_target("Root.A", [consumer_a, consumer_b]),
            _make_target("Root.B", [_make_consumer("Dup.Lib")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 1
        assert result[0].appearances == 2  # 2 roots, not 3 entries

    def test_both_criteria_met_appears_once(self):
        """Consumer qualifying under both rules appears exactly once."""
        targets = [
            _make_target("Root.A", [_make_consumer("Both.Qualifies", risk="High")]),
            _make_target("Root.B", [_make_consumer("Both.Qualifies", risk="Critical")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 1
        assert result[0].consumer_name == "Both.Qualifies"
        assert result[0].appearances == 2
        assert result[0].max_risk == "Critical"

    def test_risk_rating_none_excluded(self):
        """Consumer with no risk rating under 1 root does not qualify."""
        targets = [
            _make_target("Root.A", [_make_consumer("No.Risk")]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 0

    def test_empty_consumers(self):
        """Target with no consumers returns empty list."""
        targets = [_make_target("Root.A", [])]
        result = select_key_consumers(targets)
        assert result == []

    def test_empty_targets(self):
        """Empty targets list returns empty result."""
        result = select_key_consumers([])
        assert result == []

    def test_truncates_to_max_results(self):
        """Result is capped at max_results."""
        targets = [
            _make_target("Root.A", [_make_consumer(f"Consumer.{i}", risk="High") for i in range(20)]),
        ]
        result = select_key_consumers(targets, max_results=5)
        assert len(result) == 5

    def test_default_max_is_10(self):
        """Default max_results is MAX_KEY_CONSUMERS (10)."""
        targets = [
            _make_target("Root.A", [_make_consumer(f"Consumer.{i}", risk="Critical") for i in range(15)]),
        ]
        result = select_key_consumers(targets)
        assert len(result) == MAX_KEY_CONSUMERS

    def test_sort_by_appearances_desc(self):
        """Higher appearances sorts first."""
        targets = [
            _make_target("Root.A", [_make_consumer("Two.Roots"), _make_consumer("Three.Roots")]),
            _make_target("Root.B", [_make_consumer("Two.Roots"), _make_consumer("Three.Roots")]),
            _make_target("Root.C", [_make_consumer("Three.Roots")]),
        ]
        result = select_key_consumers(targets)
        assert result[0].consumer_name == "Three.Roots"
        assert result[0].appearances == 3
        assert result[1].consumer_name == "Two.Roots"

    def test_sort_by_risk_then_name(self):
        """Equal appearances: higher risk first, then alphabetical name."""
        targets = [
            _make_target("Root.A", [
                _make_consumer("Zebra.Lib", risk="High"),
                _make_consumer("Alpha.Lib", risk="Critical"),
                _make_consumer("Beta.Lib", risk="High"),
            ]),
            _make_target("Root.B", [
                _make_consumer("Zebra.Lib", risk="High"),
                _make_consumer("Alpha.Lib", risk="High"),
                _make_consumer("Beta.Lib", risk="Medium"),
            ]),
        ]
        result = select_key_consumers(targets)
        assert result[0].consumer_name == "Alpha.Lib"  # Critical > High
        assert result[1].consumer_name == "Beta.Lib"   # High, Beta < Zebra
        assert result[2].consumer_name == "Zebra.Lib"  # High, Zebra

    def test_risk_escalation_across_targets(self):
        """max_risk reflects the highest risk across all target appearances."""
        targets = [
            _make_target("Root.A", [_make_consumer("Escalated.Lib", risk="Medium")]),
            _make_target("Root.B", [_make_consumer("Escalated.Lib", risk="Critical")]),
        ]
        result = select_key_consumers(targets)
        assert result[0].max_risk == "Critical"

    def test_fid2728_scenario(self):
        """Mimics the FID-2728 validation: Presenters.Web.Admin under 3 roots at HIGH/High."""
        targets = [
            _make_target(
                "Lighthouse1.AdHoc.SmartviewServices",
                [_make_consumer("Lighthouse1.Presenters.Web.Admin", risk="High")],
            ),
            _make_target(
                "Lighthouse1.AdHoc.Data",
                [_make_consumer("Lighthouse1.Presenters.Web.Admin", risk="High")],
            ),
            _make_target(
                "Lighthouse1.AdHoc.Web.App",
                [_make_consumer("Lighthouse1.Presenters.Web.Admin", risk="High")],
            ),
        ]
        result = select_key_consumers(targets)
        assert len(result) == 1
        assert result[0].consumer_name == "Lighthouse1.Presenters.Web.Admin"
        assert result[0].appearances == 3
        assert result[0].max_risk == "High"
