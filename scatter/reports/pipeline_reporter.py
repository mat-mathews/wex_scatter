"""Pipeline-only output formatting for analysis results."""
from pathlib import Path
from typing import Dict, List

from scatter.core.models import ImpactReport


def extract_pipeline_names(results: list) -> List[str]:
    """Extract sorted unique pipeline names from ConsumerResult objects."""
    return sorted(set(
        r.pipeline_name for r in results
        if r.pipeline_name
    ))


def extract_impact_pipeline_names(impact_report: ImpactReport) -> List[str]:
    """Extract sorted unique pipeline names from impact report."""
    return sorted(set(
        c.pipeline_name
        for t in impact_report.targets
        for c in t.consumers
        if c.pipeline_name
    ))


def format_pipeline_output(pipeline_names: List[str]) -> str:
    """One pipeline per line, no decoration. Empty string if no pipelines."""
    return '\n'.join(pipeline_names)


def write_pipeline_report(pipeline_names: List[str], output_path: Path) -> None:
    """Write pipeline list to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = (format_pipeline_output(pipeline_names) + '\n') if pipeline_names else ''
    output_path.write_text(content, encoding='utf-8')
