"""Shared constants and compiled patterns for Scatter."""
import re
import multiprocessing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

# multiprocessing configuration
DEFAULT_MAX_WORKERS = min(32, (multiprocessing.cpu_count() or 1) + 4)
DEFAULT_CHUNK_SIZE = 75
MULTIPROCESSING_ENABLED = True

# --- regex for type extraction ---
TYPE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"  # Optional access modifier
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+|record\s+|readonly\s+|ref\s+)*"  # Optional keywords (incl. record as modifier for 'record class'/'record struct')
    r"(?:class|struct|interface|enum|record)\s+"  # Type keyword (incl. standalone 'record')
    r"([A-Za-z_][A-Za-z0-9_<>,\s]*?)"  # Capture type name (non-greedy) - handles generics roughly
    r"\s*(?::|{|where|<|\(|;)",  # Look for inheritance colon, opening brace, where clause, generics, positional params, or semicolon
    re.MULTILINE
)

DELEGATE_DECLARATION_PATTERN = re.compile(
    r"^\s*(?:public|internal|private|protected)?\s*"  # Optional access modifier
    r"delegate\s+"                                     # delegate keyword
    r"[A-Za-z_][A-Za-z0-9_<>,\s\[\]\.]*?\s+"          # Return type (e.g., Task, void, int)
    r"([A-Za-z_][A-Za-z0-9_]*)"                        # Capture delegate name
    r"\s*[<(]",                                         # Generic params or parameter list
    re.MULTILINE
)


# --- Impact analysis confidence constants ---
CONFIDENCE_HIGH = 1.0
CONFIDENCE_MEDIUM = 0.6
CONFIDENCE_LOW = 0.3
CONFIDENCE_LABELS = {1.0: "HIGH", 0.6: "MEDIUM", 0.3: "LOW"}
DEFAULT_MAX_DEPTH = 2


def _confidence_label(confidence: float) -> str:
    """Map a confidence float to its label string."""
    if confidence >= CONFIDENCE_HIGH:
        return "HIGH"
    elif confidence >= CONFIDENCE_MEDIUM:
        return "MEDIUM"
    return "LOW"


class RawConsumerDict(TypedDict):
    """Raw consumer dict returned by find_consumers()."""
    consumer_path: Path
    consumer_name: str
    relevant_files: List[Path]


# --- Consumer result data model ---

@dataclass
class ConsumerResult:
    """A consuming relationship between a target project and a consumer project.

    Constructed by v1_bridge._process_consumer_summaries_and_append_results().
    Graph enrichment fields are set by graph_enrichment.enrich_legacy_results().
    """
    target_project_name: str
    target_project_path: str
    triggering_type: str       # class name, method, or "N/A (Project Reference)"
    consumer_project_name: str
    consumer_project_path: str
    consuming_solutions: List[str] = field(default_factory=list)
    pipeline_name: Optional[str] = None
    batch_job_verification: Optional[str] = None
    consumer_file_summaries: Dict[str, str] = field(default_factory=dict)
    # Graph enrichment fields (optional — set when graph context available)
    coupling_score: Optional[float] = None
    fan_in: Optional[int] = None
    fan_out: Optional[int] = None
    instability: Optional[float] = None
    in_cycle: Optional[bool] = None


# --- Impact analysis data models ---

@dataclass
class AnalysisTarget:
    """A single target extracted from a work request (SOW)."""
    target_type: str           # "project" | "sproc" | "class"
    name: str                  # e.g., "GalaxyWorks.Data" or "dbo.sp_InsertPortalConfiguration"
    csproj_path: Optional[Path] = None
    namespace: Optional[str] = None
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    confidence: float = CONFIDENCE_HIGH
    match_evidence: Optional[str] = None  # LLM explanation of why this target was identified


@dataclass
class EnrichedConsumer:
    """A consumer project with AI-enriched metadata."""
    consumer_path: Path
    consumer_name: str
    relevant_files: List[Path] = field(default_factory=list)
    solutions: List[str] = field(default_factory=list)
    pipeline_name: str = ""
    depth: int = 0                          # 0 = direct, 1+ = transitive
    confidence: float = CONFIDENCE_HIGH
    confidence_label: str = "HIGH"
    risk_rating: Optional[str] = None       # "Low" | "Medium" | "High" | "Critical"
    risk_justification: Optional[str] = None
    coupling_narrative: Optional[str] = None
    coupling_vectors: Optional[List[str]] = None
    # consumer_name of the parent in the BFS tree (None = direct consumer).
    # Assumes consumer_name is unique within a single analysis scope.
    propagation_parent: Optional[str] = None
    # Graph-derived metrics (populated when --graph-metrics is used)
    coupling_score: Optional[float] = None
    fan_in: Optional[int] = None
    fan_out: Optional[int] = None
    instability: Optional[float] = None
    in_cycle: Optional[bool] = None


@dataclass
class TargetImpact:
    """Impact data for a single analysis target."""
    target: AnalysisTarget
    consumers: List[EnrichedConsumer] = field(default_factory=list)
    total_direct: int = 0
    total_transitive: int = 0
    max_depth_reached: int = 0


@dataclass
class ImpactReport:
    """Full impact analysis report."""
    sow_text: str
    targets: List[TargetImpact] = field(default_factory=list)
    impact_narrative: Optional[str] = None       # Manager-friendly summary
    complexity_rating: Optional[str] = None      # "Low" | "Medium" | "High" | "Critical"
    complexity_justification: Optional[str] = None
    effort_estimate: Optional[str] = None        # e.g., "3-5 developer-days"
    overall_risk: Optional[str] = None
    ambiguity_level: Optional[str] = None        # "clear" | "moderate" | "vague"
    avg_target_confidence: Optional[float] = None


# --- Filter pipeline visibility models ---

# Stage name constants — use these instead of raw strings.
STAGE_DISCOVERY = "discovery"
STAGE_PROJECT_REFERENCE = "project_reference"
STAGE_NAMESPACE = "namespace"
STAGE_CLASS = "class"
STAGE_METHOD = "method"

# Human-readable labels for each stage, keyed by stage name constant.
STAGE_LABELS = {
    STAGE_DISCOVERY: None,           # discovery uses input_count as the chain start
    STAGE_PROJECT_REFERENCE: "project refs",
    STAGE_NAMESPACE: "namespace",
    STAGE_CLASS: "class match",
    STAGE_METHOD: "method match",
}

# Label describing the *input* population for each stage (used in diagnostic hints).
STAGE_INPUT_LABELS = {
    STAGE_PROJECT_REFERENCE: "potential",
    STAGE_NAMESPACE: "project-reference-matching",
    STAGE_CLASS: "namespace-matching",
    STAGE_METHOD: "class-matching",
}


@dataclass
class FilterStage:
    """One stage of the consumer detection filter pipeline."""
    name: str           # STAGE_DISCOVERY, STAGE_PROJECT_REFERENCE, etc.
    input_count: int    # projects entering this stage
    output_count: int   # projects passing this stage
    source: str = "filesystem"  # "filesystem" or "graph"

    @property
    def dropped_count(self) -> int:
        """Number of projects filtered out at this stage."""
        return self.input_count - self.output_count


@dataclass
class FilterPipeline:
    """Records the filter funnel from consumer detection."""
    search_scope: str                       # search scope path (for display)
    total_projects_scanned: int             # .csproj files found in scope
    total_files_scanned: int                # .cs files analyzed across all stages
    stages: List[FilterStage] = field(default_factory=list)
    target_project: str = ""                # name of the target being analyzed
    target_namespace: str = ""              # namespace used for filtering
    class_filter: Optional[str] = None      # class filter if applied
    method_filter: Optional[str] = None     # method filter if applied

    def format_arrow_chain(self) -> str:
        """Build the 'N -> M stage -> ...' arrow notation from stages."""
        parts: List[str] = []
        for stage in self.stages:
            if stage.name == STAGE_DISCOVERY:
                parts.append(str(stage.input_count))
            label = STAGE_LABELS.get(stage.name, stage.name)
            if label:
                if stage.source == "graph":
                    label += "[graph]"
                parts.append(f"{stage.output_count} {label}")
        return " \u2192 ".join(parts)

    def filter_value_for_stage(self, stage_name: str) -> Optional[str]:
        """Return the user-supplied filter value relevant to a given stage."""
        return {
            STAGE_PROJECT_REFERENCE: self.target_project,
            STAGE_NAMESPACE: self.target_namespace,
            STAGE_CLASS: self.class_filter,
            STAGE_METHOD: self.method_filter,
        }.get(stage_name)
