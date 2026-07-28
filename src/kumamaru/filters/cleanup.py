"""Bounded skia-pathops cleanup with conservative rollback checks."""

from __future__ import annotations

import math

import pathops  # type: ignore[import-untyped]

from kumamaru.filters.common import setting
from kumamaru.geometry.contour import OutlineModelError, OutlinePen, clone_outline, validate_outline
from kumamaru.geometry.winding import contour_nesting_depths, signed_area
from kumamaru.model import FilterResult, GlyphOutline, LineSegment, QuadraticSegment


def _draw_outline(outline: GlyphOutline, pen: object) -> None:
    for contour in outline.contours:
        if not contour.segments:
            continue
        start = contour.segments[0].start
        pen.moveTo(start.as_tuple())  # type: ignore[attr-defined]
        for segment in contour.segments:
            if isinstance(segment, LineSegment):
                pen.lineTo(segment.end.as_tuple())  # type: ignore[attr-defined]
            else:
                pen.qCurveTo(  # type: ignore[attr-defined]
                    segment.control.as_tuple(), segment.end.as_tuple()
                )
        if contour.closed:
            pen.closePath()  # type: ignore[attr-defined]
        else:
            pen.endPath()  # type: ignore[attr-defined]


def _point_count(outline: GlyphOutline) -> int:
    return sum(
        1 + int(isinstance(segment, QuadraticSegment))
        for contour in outline.contours
        for segment in contour.segments
    )


def _bounds(outline: GlyphOutline) -> tuple[float, float, float, float] | None:
    points = [
        point
        for contour in outline.contours
        for segment in contour.segments
        for point in (
            (segment.start, segment.end)
            if isinstance(segment, LineSegment)
            else (segment.start, segment.control, segment.end)
        )
    ]
    if not points:
        return None
    return (
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def cleanup_outline(
    outline: GlyphOutline,
    config: object,
    *,
    upm: int,
) -> FilterResult:
    """Simplify overlaps, accepting output only inside configured safety limits."""

    if upm <= 0:
        raise ValueError("upm must be positive")
    original = clone_outline(outline)
    if not bool(setting(config, "enabled", True)):
        return FilterResult(original)
    try:
        path = pathops.Path()
        _draw_outline(outline, path.getPen())
        simplified = pathops.Path(path)
        simplified.simplify(
            fix_winding=True,
            keep_starting_points=True,
            clockwise=True,
        )
        collector = OutlinePen()
        simplified.draw(collector)
        cleaned = GlyphOutline(outline.glyph_name, collector.contours, outline.width)
    except (OutlineModelError, PathOpsError, RuntimeError, ValueError) as error:
        return FilterResult(original, warnings=[f"cleanup rolled back: {error}"])

    errors = validate_outline(cleaned)
    if errors:
        return FilterResult(original, warnings=["cleanup rolled back: " + "; ".join(errors)])
    before_topology = sorted(contour_nesting_depths(outline).values())
    after_topology = sorted(contour_nesting_depths(cleaned).values())
    if len(cleaned.contours) != len(outline.contours) or after_topology != before_topology:
        return FilterResult(
            original,
            warnings=[
                "cleanup rolled back: contour nesting topology changed "
                f"{before_topology} -> {after_topology}"
            ],
        )
    original_points, cleaned_points = _point_count(outline), _point_count(cleaned)
    maximum_growth = float(setting(config, "max_point_growth_ratio", 3.0))
    if original_points and cleaned_points > original_points * maximum_growth:
        return FilterResult(
            original,
            warnings=[f"cleanup rolled back: point count {original_points} -> {cleaned_points}"],
        )
    before_bounds, after_bounds = _bounds(outline), _bounds(cleaned)
    maximum_bbox_delta = float(setting(config, "max_bbox_change_em", 0.08)) * upm
    if (
        before_bounds is not None
        and after_bounds is not None
        and any(
            abs(before - after) > maximum_bbox_delta
            for before, after in zip(before_bounds, after_bounds, strict=True)
        )
    ):
        return FilterResult(original, warnings=["cleanup rolled back: bbox change exceeded limit"])
    before_area = sum(abs(signed_area(contour)) for contour in outline.contours)
    cleaned_areas = [abs(signed_area(contour)) for contour in cleaned.contours]
    after_area = sum(cleaned_areas)
    if (
        not math.isfinite(after_area)
        or any(area <= 1e-9 for area in cleaned_areas)
        or (before_area > 1e-9 and not 0.25 <= after_area / before_area <= 2.0)
        or (before_area > 1e-9 and after_area <= 1e-9)
    ):
        return FilterResult(
            original, warnings=["cleanup rolled back: contour area changed abnormally"]
        )
    return FilterResult(cleaned)


# pathops exposes either a dedicated exception type or plain RuntimeError,
# depending on wheel version.  Keeping this alias local makes the rollback
# behavior stable across supported 0.8/0.9 releases.
PathOpsError = getattr(pathops, "PathOpsError", RuntimeError)
