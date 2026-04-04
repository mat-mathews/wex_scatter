"""PR comment markdown formatter for risk reports.

Decision #11: one function, collapsible flag controls <details> wrapping.
"""

from typing import List

from scatter.core.models import PRRiskReport
from scatter.core.risk_models import RiskLevel
from scatter.reports._formatting import md_table as _md_table


_LEVEL_EMOJI = {
    RiskLevel.GREEN: "\u2705",
    RiskLevel.YELLOW: "\u26a0\ufe0f",
    RiskLevel.RED: "\U0001f6a8",
}


def _wrap_collapsible(title: str, content: str) -> str:
    """Wrap content in a <details> block."""
    return f"<details>\n<summary>{title}</summary>\n\n{content}\n</details>"


def build_pr_risk_markdown(report: PRRiskReport, collapsible: bool = False) -> str:
    """Build PR comment markdown from a PRRiskReport.

    Args:
        report: The risk analysis report.
        collapsible: If True, wrap detail sections in <details> tags.
    """
    parts: List[str] = []
    level = report.risk_level
    emoji = _LEVEL_EMOJI.get(level, "")
    score = report.aggregate.composite_score

    # Header
    parts.append(f"## Scatter Risk: {emoji} {level.value} ({score:.2f})\n")

    # One-line summary
    n_types = len(report.changed_types)
    n_projects = len(report.profiles)
    summary = f"{n_types} type(s) changed across {n_projects} project(s)."
    if report.total_direct_consumers > 0:
        summary += f" {report.total_direct_consumers} direct consumer(s) affected."
    if not report.graph_available:
        summary += " (Graph not available — partial scoring.)"
    parts.append(f"{summary}\n")

    # Dimension table
    if report.graph_available:
        dim_headers = ["Dimension", "Score", "Severity"]
        dim_rows = []
        for dim in report.aggregate.dimensions:
            if not dim.data_available:
                dim_rows.append([dim.label, "N/A", "—"])
            else:
                dim_rows.append([dim.label, f"{dim.score:.2f}", dim.severity])
        parts.append("### Risk Dimensions\n")
        parts.append(_md_table(dim_headers, dim_rows))
        parts.append("")
    else:
        # Simplified: show only change_surface
        cs = report.aggregate.change_surface
        parts.append("### Risk Dimensions\n")
        if cs.data_available:
            parts.append(
                _md_table(
                    ["Dimension", "Score", "Severity"],
                    [[cs.label, f"{cs.score:.2f}", cs.severity]],
                )
            )
        parts.append("")
        for w in report.warnings:
            parts.append(f"> {w}\n")

    # Changed types table
    if report.changed_types:
        ct_headers = ["Type", "Kind", "Change", "Project"]
        ct_rows = [
            [ct.name, ct.kind, ct.change_kind, ct.owning_project] for ct in report.changed_types
        ]
        ct_content = "### Changed Types\n\n" + _md_table(ct_headers, ct_rows)
        if collapsible:
            parts.append(_wrap_collapsible(f"Changed Types ({n_types})", ct_content))
        else:
            parts.append(ct_content)
        parts.append("")

    # Risk factors
    if report.risk_factors:
        factors_content = "### Risk Factors\n\n"
        for f in report.risk_factors:
            factors_content += f"- {f}\n"
        if collapsible:
            parts.append(
                _wrap_collapsible(f"Risk Factors ({len(report.risk_factors)})", factors_content)
            )
        else:
            parts.append(factors_content)

    # Consumer impact
    if report.unique_consumers:
        consumer_content = "### Consumer Impact\n\n"
        consumer_content += (
            f"**{report.total_direct_consumers}** direct, "
            f"**{report.total_transitive_consumers}** transitive consumers.\n\n"
        )
        if len(report.unique_consumers) <= 20:
            consumer_content += "Affected: " + ", ".join(report.unique_consumers) + "\n"
        else:
            shown = ", ".join(report.unique_consumers[:20])
            consumer_content += (
                f"Affected (showing 20 of {len(report.unique_consumers)}): {shown}\n"
            )
        if collapsible:
            parts.append(
                _wrap_collapsible(
                    f"Consumer Impact ({len(report.unique_consumers)})", consumer_content
                )
            )
        else:
            parts.append(consumer_content)

    # Footer
    parts.append(f"---\n*Analysis completed in {report.duration_ms}ms*\n")

    return "\n".join(parts)
