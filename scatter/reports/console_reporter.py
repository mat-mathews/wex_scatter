"""Console output formatting for analysis results."""

import textwrap
from itertools import groupby
from typing import List, Optional

from scatter.core.models import (
    ConsumerResult,
    EnrichedConsumer,
    FilterPipeline,
    ImpactReport,
    PRRiskReport,
    STAGE_DISCOVERY,
    STAGE_INPUT_LABELS,
)
from scatter.core.tree import build_adjacency, CONFIDENCE_LABEL_RANK


def print_filter_pipeline(pipeline: FilterPipeline) -> None:
    """Print filter pipeline summary to console."""
    projects = f"{pipeline.total_projects_scanned:,}"
    files = f"{pipeline.total_files_scanned:,}"
    print(f"Search scope: {pipeline.search_scope} (scanned {projects} projects, {files} files)")

    if pipeline.stages:
        print(f"Filter: {pipeline.format_arrow_chain()}")

        # Diagnostic hint when a stage drops to zero
        for stage in pipeline.stages:
            if stage.output_count == 0 and stage.input_count > 0 and stage.name != STAGE_DISCOVERY:
                prev_label = STAGE_INPUT_LABELS.get(stage.name, "")
                filter_value = pipeline.filter_value_for_stage(stage.name)
                if filter_value:
                    print(
                        f"  Hint: 0 of {stage.input_count} {prev_label} projects contained '{filter_value}' \u2014 verify the {stage.name} name"
                    )
                break


def print_console_report(
    all_results: List["ConsumerResult"],
    pipeline: Optional[FilterPipeline] = None,
    graph_metrics_requested: bool = False,
) -> None:
    """Print formatted analysis results to console."""
    if pipeline is not None:
        print_filter_pipeline(pipeline)

    print(f"\n{'=' * 60}")
    print("  Consumer Analysis")
    print(f"{'=' * 60}")

    if not all_results:
        print("  No consuming relationships found.")
        return

    def group_key(r: "ConsumerResult") -> tuple:
        return (r.target_project_name, r.target_project_path, r.triggering_type)

    all_results = sorted(all_results, key=group_key)
    groups = []
    for key, members in groupby(all_results, key=group_key):
        groups.append((key, list(members)))

    for (target_name, target_path, triggering_type), consumers in groups:
        print(f"  Target: {target_name} ({target_path})")
        print(f"  Consumers: {len(consumers)}")
        if "N/A" not in triggering_type:
            print(f"  Triggering type: {triggering_type}")

        # Sort: by coupling score desc when graph metrics, else alphabetical
        if graph_metrics_requested:
            consumers.sort(key=lambda r: (r.coupling_score is None, -(r.coupling_score or 0)))
        else:
            consumers.sort(key=lambda r: r.consumer_project_name)

        # Dynamic column width for consumer name
        col_w = min(max((len(r.consumer_project_name) for r in consumers), default=40), 60)
        col_w = max(col_w, 40)

        print()
        if graph_metrics_requested:
            print(
                f"  {'Consumer':<{col_w}} {'Score':>7} {'Fan-In':>7} {'Fan-Out':>7} {'Instab.':>7} Solutions"
            )
            print(f"  {'-' * col_w} {'-' * 7} {'-' * 7} {'-' * 7} {'-' * 7} {'-' * 25}")
            for r in consumers:
                solutions = ", ".join(r.consuming_solutions) if r.consuming_solutions else ""
                if r.coupling_score is not None:
                    fi = r.fan_in or 0
                    fo = r.fan_out or 0
                    inst = r.instability or 0.0
                    print(
                        f"  {r.consumer_project_name:<{col_w}} {r.coupling_score:>7.1f} {fi:>7} {fo:>7} {inst:>7.2f} {solutions}"
                    )
                else:
                    print(
                        f"  {r.consumer_project_name:<{col_w}} {'—':>7} {'—':>7} {'—':>7} {'—':>7} {solutions}"
                    )
        else:
            print(f"  {'Consumer':<{col_w}} Solutions")
            print(f"  {'-' * col_w} {'-' * 25}")
            for r in consumers:
                solutions = ", ".join(r.consuming_solutions) if r.consuming_solutions else ""
                print(f"  {r.consumer_project_name:<{col_w}} {solutions}")

        # Batch job status (minimal, beneath table)
        batch_results = [r for r in consumers if r.batch_job_verification]
        if batch_results:
            print()
            for r in batch_results:
                print(f"    [{r.batch_job_verification}] {r.consumer_project_name}")

        # AI summaries (minimal, beneath table)
        summary_results = [r for r in consumers if r.consumer_file_summaries]
        if summary_results:
            print()
            for r in summary_results:
                print(f"    {r.consumer_project_name}")
                for file_rel_path, summary in r.consumer_file_summaries.items():
                    print(f"      {file_rel_path}")
                    wrapped = textwrap.fill(
                        summary, width=76, initial_indent="        ", subsequent_indent="        "
                    )
                    print(wrapped)

        print()

    print(
        f"Analysis complete. {len(all_results)} consumer(s) found across {len(groups)} target(s)."
    )


def render_tree(consumers: List[EnrichedConsumer]) -> List[str]:
    """Render consumers as a tree with box-drawing characters.

    Returns a list of output lines (without trailing newlines).
    The caller is responsible for printing a target header above the tree.
    """
    if not consumers:
        return []

    tree = build_adjacency(
        consumers,
        get_name=lambda c: c.consumer_name,
        get_parent=lambda c: c.propagation_parent,
        sort_key=lambda c: CONFIDENCE_LABEL_RANK.get(c.confidence_label, 2),
    )
    lines: List[str] = []

    def _render_children(parent_key: Optional[str], prefix: str) -> None:
        children = tree.get(parent_key, [])
        for i, consumer in enumerate(children):
            is_last = i == len(children) - 1
            connector = "\u2514\u2500\u2500" if is_last else "\u251c\u2500\u2500"
            child_prefix = prefix + ("    " if is_last else "\u2502   ")

            # Derive label from tree position, not the raw field — avoids
            # showing "via <removed>" for orphans re-parented to root.
            if parent_key is None:
                depth_info = "direct"
            else:
                depth_info = f"via {parent_key}"
            lines.append(
                f"{prefix}{connector} {consumer.consumer_name}  [{consumer.confidence_label}]  {depth_info}"
            )

            # Detail lines before children
            if consumer.risk_rating:
                justification = (
                    f' \u2014 "{consumer.risk_justification}"'
                    if consumer.risk_justification
                    else ""
                )
                lines.append(f"{child_prefix}Risk: {consumer.risk_rating}{justification}")
            if consumer.pipeline_name:
                lines.append(f"{child_prefix}Pipeline: {consumer.pipeline_name}")
            if consumer.solutions:
                lines.append(f"{child_prefix}Solutions: {', '.join(consumer.solutions)}")
            if consumer.coupling_narrative:
                initial = f"{child_prefix}Coupling: "
                subsequent = child_prefix + "  "
                wrapped = textwrap.fill(
                    consumer.coupling_narrative,
                    width=80,
                    initial_indent=initial,
                    subsequent_indent=subsequent,
                )
                lines.extend(wrapped.splitlines())
            if consumer.coupling_vectors:
                lines.append(
                    f"{child_prefix}Coupling vectors: {', '.join(consumer.coupling_vectors)}"
                )
            if consumer.coupling_score is not None:
                cycle = "yes" if consumer.in_cycle else "no"
                lines.append(
                    f"{child_prefix}Graph: coupling={consumer.coupling_score}, "
                    f"fan-in={consumer.fan_in}, fan-out={consumer.fan_out}, "
                    f"instability={consumer.instability:.2f}, in-cycle={cycle}"
                )

            # Recurse into children of this consumer
            _render_children(consumer.consumer_name, child_prefix)

    _render_children(None, "")
    return lines


def print_impact_report(report: ImpactReport) -> None:
    """Print formatted impact analysis report to console."""
    print("\n=== Impact Analysis Report ===")
    sow_display = report.sow_text[:200] + "..." if len(report.sow_text) > 200 else report.sow_text
    print(f"Work Request: {sow_display}")

    risk_str = report.overall_risk or "Not assessed"
    complexity_str = report.complexity_rating or "Not assessed"
    effort_str = f" ({report.effort_estimate})" if report.effort_estimate else ""
    print(f"Overall Risk: {risk_str} | Complexity: {complexity_str}{effort_str}")

    if report.ambiguity_level:
        avg_conf = report.avg_target_confidence or 0.0
        print(
            f"Target Quality: {report.ambiguity_level} "
            f"({len(report.targets or [])} targets, avg confidence {avg_conf:.2f})"
        )

    # Detect no-index scenario: no match_evidence on any target
    has_evidence = any(ti.target.match_evidence for ti in (report.targets or []))
    if report.targets and not has_evidence:
        print("Note: Running without codebase index — results may be less accurate.")

    if not report.targets:
        print("\nNo analysis targets were identified.")
        return

    for ti in report.targets:
        print(f"\n--- Target: {ti.target.name} ---")
        if ti.target.match_evidence:
            print(f"Evidence: {ti.target.match_evidence}")
        print(f"Direct Consumers: {ti.total_direct} | Transitive: {ti.total_transitive}")

        if ti.consumers:
            tree_lines = render_tree(ti.consumers)
            for line in tree_lines:
                print(line)

    if report.complexity_justification:
        print("\n--- Complexity ---")
        print(f"{report.complexity_rating}: {report.complexity_justification}")

    if report.impact_narrative:
        print("\n--- Impact Summary ---")
        print(report.impact_narrative)


def print_pr_risk_report(report: PRRiskReport) -> None:
    """Print PR risk analysis report to console."""
    level = report.risk_level
    score = report.aggregate.composite_score
    level_str = level.value

    print(f"\n{'=' * 60}")
    print(f"  PR Risk: {level_str} ({score:.2f})")
    print(f"{'=' * 60}")
    print(f"  Branch: {report.branch_name} (vs {report.base_branch})")

    n_types = len(report.changed_types)
    n_projects = len(report.profiles)
    print(f"  Changed: {n_types} type(s) across {n_projects} project(s)")

    if not report.graph_available:
        print("  Note: Graph not available — partial scoring only.")
        for w in report.warnings:
            print(f"  {w}")

    # Changed types table
    if report.changed_types:
        print(f"\n  {'Type':<30} {'Kind':<12} {'Change':<10} Project")
        print(f"  {'-' * 30} {'-' * 12} {'-' * 10} {'-' * 20}")
        for ct in report.changed_types:
            print(f"  {ct.name:<30} {ct.kind:<12} {ct.change_kind:<10} {ct.owning_project}")

    # Dimension table
    if report.graph_available:
        print(f"\n  {'Dimension':<25} {'Score':>7} {'Severity':<10}")
        print(f"  {'-' * 25} {'-' * 7} {'-' * 10}")
        for dim in report.aggregate.dimensions:
            if not dim.data_available:
                print(f"  {dim.label:<25} {'N/A':>7} {'—':<10}")
            else:
                print(f"  {dim.label:<25} {dim.score:>7.2f} {dim.severity:<10}")
    else:
        cs = report.aggregate.change_surface
        if cs.data_available:
            print(f"\n  Change surface: {cs.score:.2f} ({cs.severity})")

    # Risk factors
    if report.risk_factors:
        print("\n  Risk Factors:")
        for f in report.risk_factors:
            print(f"    • {f}")

    # Consumer summary
    if report.unique_consumers:
        print(
            f"\n  Consumers: {report.total_direct_consumers} direct, "
            f"{report.total_transitive_consumers} transitive "
            f"({len(report.unique_consumers)} unique)"
        )

    print(f"\n  Completed in {report.duration_ms}ms")
    print()
