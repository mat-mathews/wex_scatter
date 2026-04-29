"""Pipeline-only output formatting for analysis results."""

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from scatter.core.models import ImpactReport


PipelineGroup = Dict[str, Any]


def extract_pipeline_names(results: list) -> List[str]:
    """Extract sorted unique pipeline names from ConsumerResult objects."""
    return sorted(set(r.pipeline_name for r in results if r.pipeline_name))


def extract_impact_pipeline_names(impact_report: ImpactReport) -> List[str]:
    """Extract sorted unique pipeline names from impact report."""
    return sorted(
        set(c.pipeline_name for t in impact_report.targets for c in t.consumers if c.pipeline_name)
    )


def group_by_pipeline(
    results: list, name_attr: str = "consumer_project_name"
) -> List[PipelineGroup]:
    """Group consumer names by pipeline. Returns sorted list of pipeline groups.

    Each group: {"pipeline_name": str, "consumer_count": int, "consumers": [str]}.
    Consumers with no pipeline are omitted.
    """
    buckets: Dict[str, List[str]] = defaultdict(list)
    for r in results:
        pipeline = getattr(r, "pipeline_name", None)
        if not pipeline:
            continue
        name = getattr(r, name_attr, "") or ""
        if name and name not in buckets[pipeline]:
            buckets[pipeline].append(name)

    return sorted(
        [
            {
                "pipeline_name": pipeline,
                "consumer_count": len(consumers),
                "consumers": sorted(consumers),
            }
            for pipeline, consumers in buckets.items()
        ],
        key=lambda g: g["pipeline_name"],
    )


def group_impact_by_pipeline(impact_report: ImpactReport) -> List[PipelineGroup]:
    """Group consumers from an impact report by pipeline."""
    buckets: Dict[str, List[str]] = defaultdict(list)
    for target in impact_report.targets:
        for c in target.consumers:
            if c.pipeline_name and c.consumer_name not in buckets[c.pipeline_name]:
                buckets[c.pipeline_name].append(c.consumer_name)

    return sorted(
        [
            {
                "pipeline_name": pipeline,
                "consumer_count": len(consumers),
                "consumers": sorted(consumers),
            }
            for pipeline, consumers in buckets.items()
        ],
        key=lambda g: g["pipeline_name"],
    )


def format_pipeline_output(pipeline_names: List[str]) -> str:
    """One pipeline per line, no decoration. Empty string if no pipelines."""
    return "\n".join(pipeline_names)


def write_pipeline_report(pipeline_names: List[str], output_path: Path) -> None:
    """Write pipeline list to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = (format_pipeline_output(pipeline_names) + "\n") if pipeline_names else ""
    output_path.write_text(content, encoding="utf-8")
