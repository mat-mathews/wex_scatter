"""Console output formatting for analysis results."""
import textwrap
from collections import Counter
from typing import Dict, List, Optional, Union

from scatter.core.models import (
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


def print_console_report(all_results: List[Dict[str, Union[str, Dict, List[str]]]],
                         pipeline: Optional[FilterPipeline] = None) -> None:
    """Print formatted analysis results to console."""
    if pipeline is not None:
        print_filter_pipeline(pipeline)

    print("\n--- Combined Consumer Analysis Report ---")
    if not all_results:
        print("\n--- No Consuming Relationships Found ---")
    else:
        print("\n--- Consuming Relationships Found ---")
        group_counts = Counter(
            (item['TargetProjectName'], item['TriggeringType']) for item in all_results
        )
        last_target_type = None
        for item in all_results:
            current_target_type = (item['TargetProjectName'], item['TriggeringType'])
            if current_target_type != last_target_type:
                count = group_counts[current_target_type]
                print(f"\nTarget: {item['TargetProjectName']} ({item['TargetProjectPath']}) ({count} consumer(s))")
                if 'N/A' not in item['TriggeringType']:
                    print(f"    Type/Level: {item['TriggeringType']}")
                last_target_type = current_target_type

            pipeline_info = f" [Pipeline: {item.get('PipelineName', 'N/A')}]" if item.get('PipelineName') else ""
            print(f"         -> Consumed by: {item['ConsumerProjectName']} ({item['ConsumerProjectPath']}){pipeline_info}")

            solutions = item.get('ConsumingSolutions', [])
            if solutions:
                print(f"           Solutions: {', '.join(solutions)}")

            verification = item.get('BatchJobVerification')
            if verification:
                print(f"           Batch Job Status: {verification} in app-config")

            summaries = item.get('ConsumerFileSummaries', {})
            if summaries:
                print("           Summaries:")
                for file_rel_path, summary in summaries.items():
                    indented_summary = textwrap.indent(summary, ' ' * 14)
                    print(f"             File: {file_rel_path}\n{indented_summary}")

        print(f"\n--- Total Consuming Relationships Found: {len(all_results)} ---")


def _render_tree(consumers: List[EnrichedConsumer]) -> List[str]:
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

    if not report.targets:
        print("\nNo analysis targets were identified.")
        return

    for ti in report.targets:
        print(f"\n--- Target: {ti.target.name} ---")
        print(f"Direct Consumers: {ti.total_direct} | Transitive: {ti.total_transitive}")

        if ti.consumers:
            tree_lines = _render_tree(ti.consumers)
            for line in tree_lines:
                print(line)

    if report.complexity_justification:
        print(f"\n--- Complexity ---")
        print(f"{report.complexity_rating}: {report.complexity_justification}")

    if report.impact_narrative:
        print(f"\n--- Impact Summary ---")
        print(report.impact_narrative)
