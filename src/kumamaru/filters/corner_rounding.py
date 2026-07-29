"""Conservative line-to-line corner analysis and rounding."""

from __future__ import annotations

import math
from dataclasses import dataclass

from kumamaru.filters.common import setting, stable_candidate_id
from kumamaru.geometry.contour import clone_outline, validate_outline
from kumamaru.geometry.vectors import (
    cross,
    direction_name,
    distance,
    normalize,
    scale,
    subtract,
)
from kumamaru.geometry.winding import contour_nesting_depths, orientation
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


def _quadratic_point(segment: QuadraticSegment, t: float) -> Point:
    inverse = 1.0 - t
    return Point(
        inverse * inverse * segment.start.x
        + 2.0 * inverse * t * segment.control.x
        + t * t * segment.end.x,
        inverse * inverse * segment.start.y
        + 2.0 * inverse * t * segment.control.y
        + t * t * segment.end.y,
    )


def _segment_point(segment: LineSegment | QuadraticSegment, t: float) -> Point:
    if isinstance(segment, LineSegment):
        return Point(
            segment.start.x + (segment.end.x - segment.start.x) * t,
            segment.start.y + (segment.end.y - segment.start.y) * t,
        )
    return _quadratic_point(segment, t)


def _segment_length(segment: LineSegment | QuadraticSegment, *, steps: int = 12) -> float:
    previous = segment.start
    total = 0.0
    for index in range(1, steps + 1):
        point = _segment_point(segment, index / steps)
        total += distance(previous, point)
        previous = point
    return total


def _parameter_at_distance(
    segment: LineSegment | QuadraticSegment,
    target: float,
    *,
    from_end: bool,
) -> float:
    """Find a stable approximate arc-length parameter from one sample table."""

    if isinstance(segment, LineSegment):
        total = distance(segment.start, segment.end)
        if total <= 1e-9:
            return 1.0 if from_end else 0.0
        ratio = max(0.0, min(target / total, 1.0))
        return 1.0 - ratio if from_end else ratio

    steps = 16
    points = [_segment_point(segment, index / steps) for index in range(steps + 1)]
    cumulative = [0.0]
    for previous, point in zip(points, points[1:], strict=False):
        cumulative.append(cumulative[-1] + distance(previous, point))
    total = cumulative[-1]
    if total <= 1e-9:
        return 1.0 if from_end else 0.0
    wanted = max(0.0, min(target, total))
    from_start = total - wanted if from_end else wanted
    for index in range(1, len(cumulative)):
        if cumulative[index] < from_start:
            continue
        span = cumulative[index] - cumulative[index - 1]
        fraction = 0.0 if span <= 1e-9 else (from_start - cumulative[index - 1]) / span
        return ((index - 1) + fraction) / steps
    return 1.0


def _quadratic_subsegment(
    segment: LineSegment | QuadraticSegment,
    start_t: float,
    end_t: float,
) -> LineSegment | QuadraticSegment:
    if isinstance(segment, LineSegment):
        return LineSegment(_segment_point(segment, start_t), _segment_point(segment, end_t))

    def split(quadratic: QuadraticSegment, t: float) -> tuple[QuadraticSegment, QuadraticSegment]:
        first = _segment_point(LineSegment(quadratic.start, quadratic.control), t)
        second = _segment_point(LineSegment(quadratic.control, quadratic.end), t)
        middle = _segment_point(LineSegment(first, second), t)
        return (
            QuadraticSegment(quadratic.start, first, middle),
            QuadraticSegment(middle, second, quadratic.end),
        )

    if start_t <= 0.0 and end_t >= 1.0:
        return QuadraticSegment(segment.start, segment.control, segment.end)
    left, _ = split(segment, end_t)
    if start_t <= 0.0:
        return left
    relative = start_t / end_t if end_t > 1e-9 else 0.0
    _, middle = split(left, relative)
    return middle


def _incoming_vector(segment: LineSegment | QuadraticSegment) -> Point:
    origin = segment.start if isinstance(segment, LineSegment) else segment.control
    vector = subtract(segment.end, origin)
    return vector if normalize(vector) is not None else subtract(segment.end, segment.start)


def _outgoing_vector(segment: LineSegment | QuadraticSegment) -> Point:
    target = segment.end if isinstance(segment, LineSegment) else segment.control
    vector = subtract(target, segment.start)
    return vector if normalize(vector) is not None else subtract(segment.end, segment.start)


def _join_corner_type(
    contour: Contour,
    next_index: int,
    *,
    nesting_depth: int,
    contour_orientation: int,
) -> str | None:
    """Classify a contour join relative to the filled glyph region."""

    count = len(contour.segments)
    previous = contour.segments[(next_index - 1) % count]
    following = contour.segments[next_index]
    unit_in = normalize(_incoming_vector(previous))
    unit_out = normalize(_outgoing_vector(following))
    if unit_in is None or unit_out is None or contour_orientation == 0:
        return None
    turn = math.degrees(
        math.atan2(
            cross(unit_in, unit_out),
            unit_in.x * unit_out.x + unit_in.y * unit_out.y,
        )
    )
    local_convex = contour_orientation * turn > 0
    is_hole = nesting_depth % 2 == 1
    return "outer" if local_convex != is_hole else "inner"


@dataclass(frozen=True)
class _Corner:
    candidate: Candidate
    previous_index: int
    next_index: int
    before: Point
    after: Point
    previous_t: float
    next_t: float


def _corner_records(
    outline: GlyphOutline,
    config: object,
    *,
    upm: int,
    source_sha256: str,
) -> tuple[list[_Corner], list[SkippedItem]]:
    if upm <= 0:
        raise ValueError("upm must be positive")
    outer_radius = float(setting(config, "outer_radius_em", 0.024)) * upm
    inner_radius = float(setting(config, "inner_radius_em", 0.008)) * upm
    minimum_angle = float(setting(config, "min_interior_angle_deg", 25.0))
    maximum_angle = float(setting(config, "max_interior_angle_deg", 165.0))
    trim_ratio = float(setting(config, "max_trim_segment_ratio", 0.42))
    minimum_length = float(setting(config, "min_segment_length_em", 0.008)) * upm
    collinear = float(setting(config, "collinear_tolerance_deg", 4.0))
    records: list[_Corner] = []
    skipped: list[SkippedItem] = []
    nesting_depths = contour_nesting_depths(outline)

    for contour in outline.contours:
        count = len(contour.segments)
        if not contour.closed or count < 2:
            skipped.append(
                SkippedItem(contour.source_contour_index, 0, "open or underspecified contour")
            )
            continue
        contour_orientation = orientation(contour)
        if contour_orientation == 0:
            skipped.append(SkippedItem(contour.source_contour_index, 0, "zero-area contour"))
            continue
        segment_lengths = [_segment_length(segment) for segment in contour.segments]
        nesting_depth = nesting_depths.get(contour.source_contour_index, 0)
        join_types = [
            _join_corner_type(
                contour,
                index,
                nesting_depth=nesting_depth,
                contour_orientation=contour_orientation,
            )
            for index in range(count)
        ]
        for next_index, following in enumerate(contour.segments):
            previous_index = (next_index - 1) % count
            previous = contour.segments[previous_index]
            corner = following.start
            if distance(previous.end, corner) > 1e-6:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "discontinuous segment join",
                    )
                )
                continue
            incoming = _incoming_vector(previous)
            outgoing = _outgoing_vector(following)
            incoming_length, outgoing_length = (
                segment_lengths[previous_index],
                segment_lengths[next_index],
            )
            unit_in, unit_out = normalize(incoming), normalize(outgoing)
            if (
                unit_in is None
                or unit_out is None
                or incoming_length < minimum_length
                or outgoing_length < minimum_length
            ):
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "zero-length or shorter than minimum adjacent segment",
                    )
                )
                continue
            turn = math.degrees(
                math.atan2(
                    cross(unit_in, unit_out),
                    unit_in.x * unit_out.x + unit_in.y * unit_out.y,
                )
            )
            interior_angle = 180.0 - abs(turn)
            if abs(turn) <= collinear or not minimum_angle <= interior_angle <= maximum_angle:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "angle outside configured range or nearly collinear",
                    )
                )
                continue
            corner_type = join_types[next_index]
            if corner_type is None:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "cannot classify corner relative to fill",
                    )
                )
                continue
            if corner_type == "inner" and nesting_depth % 2 == 0:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "structural inner corner is not a white counter",
                    )
                )
                continue
            radius = outer_radius if corner_type == "outer" else inner_radius
            if radius <= 0:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        f"{corner_type} radius is disabled",
                    )
                )
                continue
            if (
                corner_type == "outer"
                and join_types[(next_index - 1) % count] == "inner"
                and join_types[(next_index + 1) % count] == "inner"
                and incoming_length <= radius
                and outgoing_length <= radius
            ):
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "structural junction shoulder between inner corners",
                    )
                )
                continue
            tangent = math.tan(math.radians(interior_angle / 2.0))
            if not math.isfinite(tangent) or abs(tangent) <= 1e-9:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "unstable trim distance",
                    )
                )
                continue
            requested_trim = radius / tangent
            maximum_trim = min(incoming_length, outgoing_length) * trim_ratio
            trim = min(requested_trim, maximum_trim)
            if trim <= 1e-9:
                skipped.append(
                    SkippedItem(
                        contour.source_contour_index,
                        next_index,
                        "trim distance collapsed to zero",
                    )
                )
                continue
            previous_t = _parameter_at_distance(previous, trim, from_end=True)
            next_t = _parameter_at_distance(following, trim, from_end=False)
            before = _segment_point(previous, previous_t)
            after = _segment_point(following, next_t)
            geometry: dict[str, float | int | str] = {
                "interior_angle_deg": round(interior_angle, 6),
                "signed_turn_deg": round(turn, 6),
                "orientation": contour_orientation,
                "nesting_depth": nesting_depth,
                "corner_type": corner_type,
                "radius": round(radius, 6),
                "trim_distance": round(trim, 6),
                "requested_trim_distance": round(requested_trim, 6),
            }
            candidate_id = stable_candidate_id(
                source_sha256=source_sha256,
                glyph_name=outline.glyph_name,
                kind="corner",
                contour_index=contour.source_contour_index,
                segment_start=previous_index,
                segment_end=next_index,
                geometry=geometry,
            )
            candidate = Candidate(
                candidate_id=candidate_id,
                kind="corner",
                glyph_name=outline.glyph_name,
                contour_index=contour.source_contour_index,
                segment_start=previous_index,
                segment_end=next_index,
                direction=direction_name(scale(unit_in, -1.0)),
                confidence=1.0 if trim == requested_trim else 0.9,
                reason=f"supported line-line {corner_type} corner",
                point=corner,
                geometry=geometry,
            )
            records.append(
                _Corner(
                    candidate,
                    previous_index,
                    next_index,
                    before,
                    after,
                    previous_t,
                    next_t,
                )
            )
    return records, skipped


def analyze_corner_candidates(
    outline: GlyphOutline,
    config: object,
    *,
    upm: int,
    source_sha256: str = "",
) -> FilterResult:
    records, skipped = _corner_records(outline, config, upm=upm, source_sha256=source_sha256)
    return FilterResult(
        outline=clone_outline(outline),
        candidates=[record.candidate for record in records],
        skipped=skipped,
    )


def round_line_corners(
    outline: GlyphOutline,
    config: object,
    *,
    upm: int,
    source_sha256: str = "",
    skip_corners: set[tuple[int, int]] | None = None,
) -> FilterResult:
    """Round supported joins without mutating ``outline``.

    ``skip_corners`` contains ``(source_contour_index, next_segment_index)``
    references, matching the segment field used by overrides.
    """

    result_outline = clone_outline(outline)
    if not bool(setting(config, "enabled", True)):
        return FilterResult(result_outline)
    records, skipped = _corner_records(outline, config, upm=upm, source_sha256=source_sha256)
    skipped_keys = skip_corners or set()
    by_contour: dict[int, dict[int, _Corner]] = {}
    candidates: list[Candidate] = []
    applied: list[str] = []
    for record in records:
        candidates.append(record.candidate)
        key = (record.candidate.contour_index, record.next_index)
        if key in skipped_keys:
            skipped.append(
                SkippedItem(
                    record.candidate.contour_index,
                    record.next_index,
                    "override skip_corner",
                )
            )
            continue
        by_contour.setdefault(record.candidate.contour_index, {})[record.next_index] = record
        applied.append(record.candidate.candidate_id)

    rebuilt: list[Contour] = []
    for contour in outline.contours:
        joins = by_contour.get(contour.source_contour_index, {})
        if not joins:
            rebuilt.append(clone_outline(GlyphOutline("", [contour], 0)).contours[0])
            continue
        segments: list[LineSegment | QuadraticSegment] = []
        count = len(contour.segments)
        for index, original in enumerate(contour.segments):
            start_join = joins.get(index)
            end_join = joins.get((index + 1) % count)
            start_t = start_join.next_t if start_join is not None else 0.0
            end_t = end_join.previous_t if end_join is not None else 1.0
            if start_t >= end_t:
                continue
            trimmed = _quadratic_subsegment(original, start_t, end_t)
            if distance(trimmed.start, trimmed.end) > 1e-9:
                segments.append(trimmed)
            if end_join is not None:
                segments.append(
                    QuadraticSegment(
                        end_join.before,
                        end_join.candidate.point,
                        end_join.after,
                    )
                )
        rebuilt.append(Contour(segments, contour.closed, contour.source_contour_index))
    result_outline.contours = rebuilt
    validation_errors = validate_outline(result_outline)
    if validation_errors:
        return FilterResult(
            outline=clone_outline(outline),
            candidates=candidates,
            skipped=skipped,
            warnings=["corner rounding rolled back: " + "; ".join(validation_errors)],
        )
    return FilterResult(
        outline=result_outline,
        candidates=candidates,
        applied_candidate_ids=applied,
        skipped=skipped,
    )


round_corners = round_line_corners
