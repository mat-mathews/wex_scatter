"""Console output formatting for analysis results."""
import textwrap
from collections import Counter
from typing import Dict, List, Union

from scatter.core.models import ImpactReport


def print_console_report(all_results: List[Dict[str, Union[str, Dict, List[str]]]]) -> None:
    """Print formatted analysis results to console."""
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

        for consumer in ti.consumers:
            depth_info = "direct" if consumer.depth == 0 else f"depth: {consumer.depth}"
            print(f"\n  [{consumer.confidence_label}] {consumer.consumer_name} ({depth_info})")

            if consumer.risk_rating:
                justification = f' — "{consumer.risk_justification}"' if consumer.risk_justification else ""
                print(f"    Risk: {consumer.risk_rating}{justification}")

            if consumer.pipeline_name:
                print(f"    Pipeline: {consumer.pipeline_name}")

            if consumer.solutions:
                print(f"    Solutions: {', '.join(consumer.solutions)}")

            if consumer.coupling_narrative:
                wrapped = textwrap.fill(consumer.coupling_narrative, width=80, initial_indent="    Coupling: ", subsequent_indent="      ")
                print(wrapped)

            if consumer.coupling_vectors:
                print(f"    Coupling vectors: {', '.join(consumer.coupling_vectors)}")

    if report.complexity_justification:
        print(f"\n--- Complexity ---")
        print(f"{report.complexity_rating}: {report.complexity_justification}")

    if report.impact_narrative:
        print(f"\n--- Impact Summary ---")
        print(report.impact_narrative)
