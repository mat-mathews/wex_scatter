"""Console output formatting for analysis results."""
import textwrap
from collections import Counter
from typing import Dict, List, Optional

from scatter.core.models import (
    ConsumerResult,
    EnrichedConsumer,
    FilterPipeline, ImpactReport,
    STAGE_DISCOVERY, STAGE_INPUT_LABELS,
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
                    print(f"  Hint: 0 of {stage.input_count} {prev_label} projects contained '{filter_value}' \u2014 verify the {stage.name} name")
                break


def print_console_report(all_results: List["ConsumerResult"],
                         pipeline: Optional[FilterPipeline] = None,
                         graph_metrics_requested: bool = False) -> None:
    """Print formatted analysis results to console."""
    if pipeline is not None:
        print_filter_pipeline(pipeline)

    print("\n--- Combined Consumer Analysis Report ---")
    if not all_results:
        print("\n--- No Consuming Relationships Found ---")
    else:
        print("\n--- Consuming Relationships Found ---")
        group_counts = Counter(
            (r.target_project_name, r.triggering_type) for r in all_results
        )
        last_target_type = None
        for r in all_results:
            current_target_type = (r.target_project_name, r.triggering_type)
            if current_target_type != last_target_type:
                count = group_counts[current_target_type]
                print(f"\nTarget: {r.target_project_name} ({r.target_project_path}) ({count} consumer(s))")
                if 'N/A' not in r.triggering_type:
                    print(f"    Type/Level: {r.triggering_type}")
                last_target_type = current_target_type

            pipeline_info = f" [Pipeline: {r.pipeline_name}]" if r.pipeline_name else ""
            print(f"         -> Consumed by: {r.consumer_project_name} ({r.consumer_project_path}){pipeline_info}")

            if r.consuming_solutions:
                print(f"           Solutions: {', '.join(r.consuming_solutions)}")

            if r.batch_job_verification:
                print(f"           Batch Job Status: {r.batch_job_verification} in app-config")

            if r.consumer_file_summaries:
                print("           Summaries:")
                for file_rel_path, summary in r.consumer_file_summaries.items():
                    indented_summary = textwrap.indent(summary, ' ' * 14)
                    print(f"             File: {file_rel_path}\n{indented_summary}")

            if graph_metrics_requested:
                if r.coupling_score is not None:
                    fi = r.fan_in or 0
                    fo = r.fan_out or 0
                    inst = r.instability or 0.0
                    cycle = "yes" if r.in_cycle else "no"
                    print(f"           Graph: coupling={r.coupling_score}, fan-in={fi}, fan-out={fo}, instability={inst:.3f}, in-cycle={cycle}")
                else:
                    print("           Graph: (not in graph)")

        print(f"\n--- Total Consuming Relationships Found: {len(all_results)} ---")


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
            is_last = (i == len(children) - 1)
            connector = "\u2514\u2500\u2500" if is_last else "\u251c\u2500\u2500"
            child_prefix = prefix + ("    " if is_last else "\u2502   ")

            # Derive label from tree position, not the raw field — avoids
            # showing "via <removed>" for orphans re-parented to root.
            if parent_key is None:
                depth_info = "direct"
            else:
                depth_info = f"via {parent_key}"
            lines.append(f"{prefix}{connector} {consumer.consumer_name}  [{consumer.confidence_label}]  {depth_info}")

            # Detail lines before children
            if consumer.risk_rating:
                justification = f' \u2014 "{consumer.risk_justification}"' if consumer.risk_justification else ""
                lines.append(f"{child_prefix}Risk: {consumer.risk_rating}{justification}")
            if consumer.pipeline_name:
                lines.append(f"{child_prefix}Pipeline: {consumer.pipeline_name}")
            if consumer.solutions:
                lines.append(f"{child_prefix}Solutions: {', '.join(consumer.solutions)}")
            if consumer.coupling_narrative:
                initial = f"{child_prefix}Coupling: "
                subsequent = child_prefix + "  "
                wrapped = textwrap.fill(consumer.coupling_narrative, width=80,
                                        initial_indent=initial, subsequent_indent=subsequent)
                lines.extend(wrapped.splitlines())
            if consumer.coupling_vectors:
                lines.append(f"{child_prefix}Coupling vectors: {', '.join(consumer.coupling_vectors)}")
            if consumer.coupling_score is not None:
                cycle = "yes" if consumer.in_cycle else "no"
                lines.append(
                    f"{child_prefix}Graph: coupling={consumer.coupling_score}, "
                    f"fan-in={consumer.fan_in}, fan-out={consumer.fan_out}, "
                    f"instability={consumer.instability:.3f}, in-cycle={cycle}"
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
        target_count = sum(len(ti.consumers) for ti in report.targets) if report.targets else 0
        avg_conf = report.avg_target_confidence or 0.0
        print(f"Target Quality: {report.ambiguity_level} "
              f"({len(report.targets or [])} targets, avg confidence {avg_conf:.2f})")

    # Detect no-index scenario: no match_evidence on any target
    has_evidence = any(
        ti.target.match_evidence for ti in (report.targets or [])
    )
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
        print(f"\n--- Complexity ---")
        print(f"{report.complexity_rating}: {report.complexity_justification}")

    if report.impact_narrative:
        print(f"\n--- Impact Summary ---")
        print(report.impact_narrative)
