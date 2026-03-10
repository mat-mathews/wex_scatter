"""Shared constants and compiled patterns for Scatter."""
import re
import multiprocessing
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
