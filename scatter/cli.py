"""Backward-compatibility shim — public API moved to analysis.py and output.py."""

from scatter.analysis import (  # noqa: F401
    ModeContext,
    ModeResult,
    run_target_analysis,
    run_git_analysis,
    run_sproc_analysis,
    apply_impact_graph_enrichment,
)
from scatter.output import (  # noqa: F401
    dispatch_legacy_output,
)
