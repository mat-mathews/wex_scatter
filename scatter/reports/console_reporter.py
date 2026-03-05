"""Console output formatting for analysis results."""
import textwrap
from typing import Dict, List, Union


def print_console_report(all_results: List[Dict[str, Union[str, Dict, List[str]]]]) -> None:
    """Print formatted analysis results to console."""
    print("\n--- Combined Consumer Analysis Report ---")
    if not all_results:
        print("\n--- No Consuming Relationships Found ---")
    else:
        print("\n--- Consuming Relationships Found ---")
        last_target_type = None
        for item in all_results:
            current_target_type = (item['TargetProjectName'], item['TriggeringType'])
            if current_target_type != last_target_type:
                print(f"\nTarget: {item['TargetProjectName']} ({item['TargetProjectPath']})")
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
