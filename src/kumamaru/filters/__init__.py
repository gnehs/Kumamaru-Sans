"""Conservative outline filters."""

from kumamaru.filters.cleanup import cleanup_outline
from kumamaru.filters.corner_rounding import (
    analyze_corner_candidates,
    round_corners,
    round_line_corners,
)
from kumamaru.filters.spur_detection import (
    analyze_spur_candidates,
    auto_apply_candidate_ids,
    detect_spur_candidates,
)
from kumamaru.filters.terminal_rounding import (
    analyze_terminal_candidates,
    apply_terminal_candidates,
    auto_round_cap_candidate_ids,
    round_terminals,
)

__all__ = [
    "analyze_corner_candidates",
    "analyze_spur_candidates",
    "analyze_terminal_candidates",
    "apply_terminal_candidates",
    "auto_round_cap_candidate_ids",
    "auto_apply_candidate_ids",
    "cleanup_outline",
    "detect_spur_candidates",
    "round_corners",
    "round_line_corners",
    "round_terminals",
]
