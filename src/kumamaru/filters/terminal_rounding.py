"""Deterministic closed-contour terminal analysis and round-cap rebuilding."""

from __future__ import annotations

import math
from collections.abc import Iterable

from kumamaru.filters.common import setting, stable_candidate_id
from kumamaru.filters.corner_rounding import (
    _incoming_vector,
    _outgoing_vector,
    _parameter_at_distance,
    _quadratic_subsegment,
    _segment_length,
)
from kumamaru.geometry.contour import clone_outline, validate_outline
from kumamaru.geometry.vectors import (
    direction_name,
    distance,
    dot,
    midpoint,
    normalize,
    perpendicular,
    scale,
    subtract,
)
from kumamaru.geometry.winding import contour_nesting_depths, point_in_contour
from kumamaru.model import (
    Candidate,
    Contour,
    FilterResult,
    GlyphOutline,
    LineSegment,
    Point,
    QuadraticSegment,
    SkippedItem,
)


def _cyclic_indices(start_exclusive: int, end_exclusive: int, count: int) -> list[int]:
    indices: list[int] = []
    index = (start_exclusive + 1) % count
    while index != end_exclusive:
        indices.append(index)
        index = (index + 1) % count
        if len(indices) >= count:
            return []
    return indices


def _line_points(segments: list[LineSegment | QuadraticSegment], indices: list[int]) -> list[Point]:
    if not indices:
        return []
    chain = [segments[index] for index in indices]
    if not all(isinstance(segment, LineSegment) for segment in chain):
        return []
    return [chain[0].start, *(segment.end for segment in chain)]


def analyze_terminal_candidates(
    outline: GlyphOutline,
    config: object,
    *,
    upm: int,
    source_sha256: str = "",
) -> FilterResult:
    """Find cap chains bracketed by long, anti-parallel line segments."""

    if upm <= 0:
        raise ValueError("upm must be positive")
    result_outline = clone_outline(outline)
    if not bool(setting(config, "enabled", True)):
        return FilterResult(result_outline)
    parallel_tolerance = float(setting(config, "parallel_tolerance_deg", 12.0))
    perpendicular_tolerance = float(setting(config, "perpendicular_tolerance_deg", 18.0))
    minimum_side_length = float(setting(config, "min_side_length_em", 0.045)) * upm
    maximum_chain = int(setting(config, "max_cap_chain_length", 5))
    candidates: list[Candidate] = []
    skipped: list[SkippedItem] = []
    nesting_depths = contour_nesting_depths(outline)

    for contour in outline.contours:
        count = len(contour.segments)
        if not contour.closed or count < 3:
            skipped.append(
                SkippedItem(contour.source_contour_index, 0, "not a closed terminal contour")
            )
            continue
        segments = contour.segments
        side_a_vectors = [_incoming_vector(segment) for segment in segments]
        side_b_vectors = [_outgoing_vector(segment) for segment in segments]
        side_lengths = [_segment_length(segment) for segment in segments]
        for side_a_index, side_a in enumerate(segments):
            side_a_vector = side_a_vectors[side_a_index]
            side_a_length = side_lengths[side_a_index]
            unit_a = normalize(side_a_vector)
            if unit_a is None or side_a_length < minimum_side_length:
                continue
            for chain_count in range(1, min(maximum_chain, count - 2) + 1):
                side_b_index = (side_a_index + chain_count + 1) % count
                side_b = segments[side_b_index]
                side_b_vector = side_b_vectors[side_b_index]
                side_b_length = side_lengths[side_b_index]
                unit_b = normalize(side_b_vector)
                if unit_b is None or side_b_length < minimum_side_length:
                    continue
                anti_parallel_dot = max(-1.0, min(1.0, dot(unit_a, scale(unit_b, -1.0))))
                parallel_error = math.degrees(math.acos(anti_parallel_dot))
                if parallel_error > parallel_tolerance:
                    continue
                chain_indices = _cyclic_indices(side_a_index, side_b_index, count)
                if len(chain_indices) != chain_count:
                    continue
                chain_points = _line_points(segments, chain_indices)
                if not chain_points:
                    continue
                chain_length = sum(
                    distance(segments[index].start, segments[index].end) for index in chain_indices
                )
                if chain_length > min(side_a_length, side_b_length) * 0.85:
                    continue
                base_a, base_b = side_a.end, side_b.start
                chord = subtract(base_b, base_a)
                chord_unit = normalize(chord)
                if chord_unit is None:
                    continue
                shaft_axis = normalize(
                    Point(unit_b.x - unit_a.x, unit_b.y - unit_a.y)
                )  # From terminal back into the shaft, averaged from both sides.
                if shaft_axis is None:
                    continue
                # acos(abs(dot)) is already 0..90; compare its distance to 90.
                chord_axis_angle = math.degrees(
                    math.acos(max(-1.0, min(1.0, abs(dot(chord_unit, shaft_axis)))))
                )
                perpendicular_error = 90.0 - chord_axis_angle
                if perpendicular_error > perpendicular_tolerance:
                    continue
                width_axis = normalize(perpendicular(shaft_axis))
                if width_axis is None:
                    continue
                base_center = midpoint(base_a, base_b)
                outward = scale(shaft_axis, -1.0)
                shaft_width = abs(dot(subtract(base_b, base_a), width_axis))
                if shaft_width <= 1e-9:
                    continue
                width_values = [
                    dot(subtract(point, base_center), width_axis) for point in chain_points
                ]
                terminal_width = max(width_values) - min(width_values)
                depths = [dot(subtract(point, base_center), outward) for point in chain_points]
                flare_depth = max(0.0, max(depths))
                extreme_index = max(range(len(chain_points)), key=lambda index: depths[index])
                extreme = chain_points[extreme_index]
                # A cap chain should not dive materially behind its two shaft anchors.
                direction_consistency = sum(
                    depth >= -max(1.0, shaft_width * 0.1) for depth in depths
                ) / len(depths)
                confidence = max(
                    0.0,
                    min(
                        1.0,
                        0.55
                        + 0.2 * (1.0 - parallel_error / max(parallel_tolerance, 1e-9))
                        + 0.15 * (1.0 - perpendicular_error / max(perpendicular_tolerance, 1e-9))
                        + 0.1 * direction_consistency,
                    ),
                )
                geometry: dict[str, float | int | str] = {
                    "side_a_index": side_a_index,
                    "side_b_index": side_b_index,
                    "chain_count": chain_count,
                    "chain_length": round(chain_length, 6),
                    "shaft_width": round(shaft_width, 6),
                    "shaft_width_em": round(shaft_width / upm, 9),
                    "side_a_length": round(side_a_length, 6),
                    "side_b_length": round(side_b_length, 6),
                    "side_a_type": "line" if isinstance(side_a, LineSegment) else "quadratic",
                    "side_b_type": "line" if isinstance(side_b, LineSegment) else "quadratic",
                    "shaft_aspect_ratio": round(min(side_a_length, side_b_length) / shaft_width, 6),
                    "terminal_width": round(terminal_width, 6),
                    "flare_ratio": round(terminal_width / shaft_width, 6),
                    "flare_depth": round(flare_depth, 6),
                    "flare_depth_em": round(flare_depth / upm, 9),
                    "parallel_error_deg": round(parallel_error, 6),
                    "perpendicular_error_deg": round(perpendicular_error, 6),
                    "axis_x": round(shaft_axis.x, 9),
                    "axis_y": round(shaft_axis.y, 9),
                    "base_a_x": round(base_a.x, 6),
                    "base_a_y": round(base_a.y, 6),
                    "base_b_x": round(base_b.x, 6),
                    "base_b_y": round(base_b.y, 6),
                    "nesting_depth": nesting_depths.get(contour.source_contour_index, 0),
                    "contains_contour": int(
                        any(
                            other.segments and point_in_contour(other.segments[0].start, contour)
                            for other in outline.contours
                            if other is not contour
                        )
                    ),
                }
                candidate_id = stable_candidate_id(
                    source_sha256=source_sha256,
                    glyph_name=outline.glyph_name,
                    kind="terminal",
                    contour_index=contour.source_contour_index,
                    segment_start=chain_indices[0],
                    segment_end=chain_indices[-1],
                    geometry=geometry,
                )
                candidates.append(
                    Candidate(
                        candidate_id=candidate_id,
                        kind="terminal",
                        glyph_name=outline.glyph_name,
                        contour_index=contour.source_contour_index,
                        segment_start=chain_indices[0],
                        segment_end=chain_indices[-1],
                        direction=direction_name(outward),
                        confidence=round(confidence, 6),
                        reason="short cap chain between long anti-parallel shaft sides",
                        point=extreme,
                        geometry=geometry,
                    )
                )
    # Each ordered side pair/chain is unique, but sorting makes the report
    # independent of dict/set iteration and therefore golden-test friendly.
    candidates.sort(
        key=lambda item: (
            item.contour_index,
            item.segment_start,
            item.segment_end,
            item.candidate_id,
        )
    )
    return FilterResult(result_outline, candidates=candidates, skipped=skipped)


def _candidate_indices(candidate: Candidate, count: int) -> tuple[int, int, list[int]]:
    side_a = int(candidate.geometry["side_a_index"])
    side_b = int(candidate.geometry["side_b_index"])
    chain = _cyclic_indices(side_a, side_b, count)
    return side_a, side_b, chain


def apply_terminal_candidates(
    outline: GlyphOutline,
    candidates: Iterable[Candidate],
    candidate_ids: Iterable[str],
) -> FilterResult:
    """Apply explicitly selected terminal/spur IDs as tangent round caps."""

    candidate_list = list(candidates)
    requested = set(candidate_ids)
    available = {candidate.candidate_id: candidate for candidate in candidate_list}
    warnings = [
        f"unknown terminal candidate: {candidate_id}"
        for candidate_id in sorted(requested - available.keys())
    ]
    selected = [
        available[candidate_id]
        for candidate_id in sorted(requested & available.keys())
        if available[candidate_id].kind in {"terminal", "spur"}
    ]
    result_outline = clone_outline(outline)
    by_contour: dict[int, list[Candidate]] = {}
    for candidate in selected:
        by_contour.setdefault(candidate.contour_index, []).append(candidate)

    applied: list[str] = []
    rebuilt_contours: list[Contour] = []
    skipped: list[SkippedItem] = []
    for contour in outline.contours:
        contour_candidates = by_contour.get(contour.source_contour_index, [])
        if not contour_candidates:
            rebuilt_contours.append(clone_outline(GlyphOutline("", [contour], 0)).contours[0])
            continue
        count = len(contour.segments)
        skip_indices: set[int] = set()
        new_start_parameters: dict[int, float] = {}
        new_end_parameters: dict[int, float] = {}
        caps_after: dict[int, tuple[QuadraticSegment, QuadraticSegment]] = {}
        accepted: list[Candidate] = []
        for candidate in contour_candidates:
            side_a, side_b, chain = _candidate_indices(candidate, count)
            if skip_indices.intersection(chain) or side_a in skip_indices or side_b in skip_indices:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        candidate.segment_start,
                        "overlapping selected terminal candidates",
                    )
                )
                continue
            geometry = candidate.geometry
            inward = normalize(Point(float(geometry["axis_x"]), float(geometry["axis_y"])))
            shaft_width = float(geometry["shaft_width"])
            original_depth = float(geometry["flare_depth"])
            if inward is None or shaft_width <= 0:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        candidate.segment_start,
                        "invalid shaft geometry",
                    )
                )
                continue
            radius = shaft_width / 2.0
            shift = radius - original_depth
            trim_distance = max(0.0, shift)
            side_a_segment = contour.segments[side_a]
            side_b_segment = contour.segments[side_b]
            side_a_t = _parameter_at_distance(side_a_segment, trim_distance, from_end=True)
            side_b_t = _parameter_at_distance(side_b_segment, trim_distance, from_end=False)
            trimmed_side_a = _quadratic_subsegment(side_a_segment, 0.0, side_a_t)
            trimmed_side_b = _quadratic_subsegment(side_b_segment, side_b_t, 1.0)
            new_a = trimmed_side_a.end
            new_b = trimmed_side_b.start
            outward = scale(inward, -1.0)
            apex = Point(
                (new_a.x + new_b.x) / 2.0 + outward.x * radius,
                (new_a.y + new_b.y) / 2.0 + outward.y * radius,
            )
            tangent_a = normalize(_incoming_vector(trimmed_side_a))
            tangent_b = normalize(_outgoing_vector(trimmed_side_b))
            if tangent_a is None or tangent_b is None:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        candidate.segment_start,
                        "invalid trimmed shaft tangent",
                    )
                )
                continue
            control_a = Point(
                new_a.x + tangent_a.x * radius,
                new_a.y + tangent_a.y * radius,
            )
            control_b = Point(
                new_b.x - tangent_b.x * radius,
                new_b.y - tangent_b.y * radius,
            )
            new_end_parameters[side_a] = side_a_t
            new_start_parameters[side_b] = side_b_t
            caps_after[side_a] = (
                QuadraticSegment(new_a, control_a, apex),
                QuadraticSegment(apex, control_b, new_b),
            )
            skip_indices.update(chain)
            accepted.append(candidate)
        rebuilt_segments: list[LineSegment | QuadraticSegment] = []
        for index, original in enumerate(contour.segments):
            if index in skip_indices:
                continue
            start_t = new_start_parameters.get(index, 0.0)
            end_t = new_end_parameters.get(index, 1.0)
            trimmed = _quadratic_subsegment(original, start_t, end_t)
            if distance(trimmed.start, trimmed.end) > 1e-9:
                rebuilt_segments.append(trimmed)
            rebuilt_segments.extend(caps_after.get(index, ()))
        rebuilt_contours.append(
            Contour(rebuilt_segments, contour.closed, contour.source_contour_index)
        )
        applied.extend(candidate.candidate_id for candidate in accepted)
    result_outline.contours = rebuilt_contours
    errors = validate_outline(result_outline)
    if errors:
        return FilterResult(
            clone_outline(outline),
            candidates=candidate_list,
            skipped=skipped,
            warnings=warnings + ["terminal transform rolled back: " + "; ".join(errors)],
        )
    return FilterResult(
        result_outline,
        candidates=candidate_list,
        applied_candidate_ids=applied,
        skipped=skipped,
        warnings=warnings,
    )


def auto_round_cap_candidate_ids(
    candidates: Iterable[Candidate],
    config: object,
    *,
    maximum_flare_ratio: float = 1.12,
    minimum_confidence: float = 0.8,
    minimum_shaft_aspect_ratio: float = 2.0,
    maximum_shaft_width_em: float = 0.12,
    maximum_terminal_depth_em: float = 0.02,
) -> set[str]:
    """Select only high-confidence terminals on slender filled stroke contours.

    A short side-chain between two anti-parallel sides also describes the end
    of a box or counter.  Those shapes are valid analysis candidates, but they
    are unsafe to auto-apply unless their shaft is sufficiently slender and
    belongs to a filled (even-depth) contour. Explicit overrides can still
    select rejected candidates after review.
    """

    if not bool(setting(config, "enabled", True)) or not bool(setting(config, "round_cap", True)):
        return set()
    return {
        candidate.candidate_id
        for candidate in candidates
        if candidate.kind == "terminal"
        and candidate.confidence >= minimum_confidence
        and float(candidate.geometry.get("flare_ratio", float("inf"))) < maximum_flare_ratio
        and float(candidate.geometry.get("shaft_aspect_ratio", 0.0)) >= minimum_shaft_aspect_ratio
        and float(candidate.geometry.get("shaft_width_em", float("inf"))) <= maximum_shaft_width_em
        and float(candidate.geometry.get("flare_depth_em", float("inf")))
        <= maximum_terminal_depth_em
        and int(candidate.geometry.get("nesting_depth", 1)) % 2 == 0
    }


round_terminals = apply_terminal_candidates
