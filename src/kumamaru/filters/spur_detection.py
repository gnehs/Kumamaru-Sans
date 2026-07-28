"""Report-only flare/spur classification derived from terminal geometry."""

from __future__ import annotations

from collections.abc import Iterable

from kumamaru.filters.common import setting, stable_candidate_id
from kumamaru.geometry.contour import clone_outline
from kumamaru.model import Candidate, FilterResult, GlyphOutline


def detect_spur_candidates(
    outline: GlyphOutline,
    terminal_candidates: Iterable[Candidate],
    config: object,
    *,
    upm: int,
    source_sha256: str = "",
) -> FilterResult:
    if upm <= 0:
        raise ValueError("upm must be positive")
    if not bool(setting(config, "enabled", True)):
        return FilterResult(clone_outline(outline))
    minimum_ratio = float(setting(config, "min_flare_ratio", 1.12))
    maximum_depth = float(setting(config, "max_flare_depth_em", 0.055)) * upm
    candidates: list[Candidate] = []
    for terminal in terminal_candidates:
        if terminal.kind != "terminal":
            continue
        flare_ratio = float(terminal.geometry.get("flare_ratio", 0.0))
        flare_depth = float(terminal.geometry.get("flare_depth", float("inf")))
        chain_count = int(terminal.geometry.get("chain_count", 0))
        # A widened spur requires at least two chain edges.  This prevents a
        # normal rectangular cap (and many directional point/hook tips) from
        # being labelled a removable flare.
        if (
            chain_count < 2
            or flare_ratio < minimum_ratio
            or flare_depth <= 0
            or flare_depth > maximum_depth
        ):
            continue
        excess = min(1.0, (flare_ratio - minimum_ratio) / max(minimum_ratio, 1e-9))
        depth_score = 1.0 - flare_depth / max(maximum_depth, 1e-9)
        confidence = min(
            0.995,
            max(0.0, 0.65 + 0.2 * excess + 0.1 * depth_score + 0.05 * terminal.confidence),
        )
        geometry = dict(terminal.geometry)
        geometry["terminal_candidate_id"] = terminal.candidate_id
        candidate_id = stable_candidate_id(
            source_sha256=source_sha256,
            glyph_name=outline.glyph_name,
            kind="spur",
            contour_index=terminal.contour_index,
            segment_start=terminal.segment_start,
            segment_end=terminal.segment_end,
            geometry=geometry,
        )
        candidates.append(
            Candidate(
                candidate_id=candidate_id,
                kind="spur",
                glyph_name=outline.glyph_name,
                contour_index=terminal.contour_index,
                segment_start=terminal.segment_start,
                segment_end=terminal.segment_end,
                direction=terminal.direction,
                confidence=round(confidence, 6),
                reason=(
                    f"terminal width is {flare_ratio:.3f}× shaft width "
                    f"over {flare_depth:.3f} font units"
                ),
                point=terminal.point,
                geometry=geometry,
            )
        )
    candidates.sort(key=lambda candidate: candidate.candidate_id)
    return FilterResult(clone_outline(outline), candidates=candidates)


analyze_spur_candidates = detect_spur_candidates


def auto_apply_candidate_ids(
    candidates: Iterable[Candidate],
    config: object,
) -> set[str]:
    """Return the IDs permitted by explicit non-report-only configuration."""

    if bool(setting(config, "report_only", True)):
        return set()
    threshold = float(setting(config, "min_confidence_to_auto_apply", 0.98))
    return {
        candidate.candidate_id
        for candidate in candidates
        if candidate.kind == "spur" and candidate.confidence >= threshold
    }
