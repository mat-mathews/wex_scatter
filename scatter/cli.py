"""Backward-compatibility shim — do not add new code here.

Public API moved to scatter/analysis.py and scatter/output.py during
the modes/ refactor.  This file exists so that code importing
`from scatter.cli import ModeContext` continues to work.  Tested in
tests/unit/test_backward_compat.py.
"""

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
