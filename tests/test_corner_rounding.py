from __future__ import annotations

import math

import pytest

from kumamaru.config import CleanupConfig, RoundingConfig
from kumamaru.filters.cleanup import cleanup_outline
from kumamaru.filters.corner_rounding import (
    analyze_corner_candidates,
    round_line_corners,
)
from kumamaru.geometry.contour import OutlinePen, outline_to_glyph, validate_outline
from kumamaru.geometry.vectors import cross, subtract
from kumamaru.model import (
    Contour,
    GlyphOutline,
    LineSegment,
    Point,
    QuadraticSegment,
)


def _outline(points: list[tuple[float, float]], name: str = "shape") -> GlyphOutline:
    vertices = [Point(*point) for point in points]
    segments = [
        LineSegment(vertices[index], vertices[(index + 1) % len(vertices)])
        for index in range(len(vertices))
    ]
    return GlyphOutline(name, [Contour(segments, True, 0)], 500)


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        [(0, 0), (0, 100), (100, 100), (100, 0)],
    ],
)
def test_rounds_clockwise_and_counterclockwise_square(
    points: list[tuple[float, float]],
) -> None:
    original = _outline(points)
    result = round_line_corners(original, RoundingConfig(), upm=1000)

    assert len(result.candidates) == 4
    assert {item.geometry["corner_type"] for item in result.candidates} == {"outer"}
    assert len(result.applied_candidate_ids) == 4
    assert len(result.outline.contours[0].segments) == 8
    assert not validate_outline(result.outline)
    assert len(original.contours[0].segments) == 4

    curves = [
        segment
        for segment in result.outline.contours[0].segments
        if isinstance(segment, QuadraticSegment)
    ]
    assert len(curves) == 4
    for curve in curves:
        # Both derivatives point along an adjacent straight edge because the
        # original corner is the quadratic control.
        tangent_cross = cross(
            subtract(curve.control, curve.start),
            subtract(curve.end, curve.control),
        )
        assert abs(tangent_cross) > 0


def test_concave_notch_uses_inner_radius() -> None:
    outline = _outline(
        [(0, 0), (200, 0), (200, 200), (120, 200), (120, 80), (80, 80), (80, 200), (0, 200)]
    )
    analysis = analyze_corner_candidates(outline, RoundingConfig(), upm=1000)

    inner = [item for item in analysis.candidates if item.geometry["corner_type"] == "inner"]
    outer = [item for item in analysis.candidates if item.geometry["corner_type"] == "outer"]
    assert len(inner) == 2
    assert len(outer) == 6
    assert {item.geometry["radius"] for item in inner} == {8.0}
    assert {item.geometry["radius"] for item in outer} == {24.0}


def test_hole_contour_corners_are_inner_relative_to_fill() -> None:
    outer = _outline([(0, 0), (300, 0), (300, 300), (0, 300)]).contours[0]
    hole = _outline([(100, 100), (100, 200), (200, 200), (200, 100)]).contours[0]
    hole.source_contour_index = 1
    outline = GlyphOutline("hole", [outer, hole], 500)
    result = analyze_corner_candidates(outline, RoundingConfig(), upm=1000)

    by_contour = {
        index: [
            candidate.geometry["corner_type"]
            for candidate in result.candidates
            if candidate.contour_index == index
        ]
        for index in (0, 1)
    }
    assert by_contour[0] == ["outer"] * 4
    assert by_contour[1] == ["inner"] * 4


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (160, 0), (100, 100)],  # acute and obtuse joins
        [(0, 0), (200, 0), (220, 80), (0, 80)],
    ],
)
def test_acute_and_obtuse_results_are_finite(
    points: list[tuple[float, float]],
) -> None:
    result = round_line_corners(_outline(points), RoundingConfig(), upm=1000)
    assert result.candidates
    for segment in result.outline.contours[0].segments:
        points_to_check = (
            (segment.start, segment.end)
            if isinstance(segment, LineSegment)
            else (segment.start, segment.control, segment.end)
        )
        assert all(math.isfinite(point.x) and math.isfinite(point.y) for point in points_to_check)


def test_short_and_zero_length_segments_are_skipped_and_trim_is_capped() -> None:
    config = RoundingConfig(
        outer_radius_em=0.2,
        inner_radius_em=0.1,
        min_segment_length_em=0.008,
    )
    outline = _outline([(0, 0), (5, 0), (5, 0), (100, 0), (100, 100), (0, 100)])
    result = round_line_corners(outline, config, upm=1000)

    assert any("zero-length" in item.reason for item in result.skipped)
    assert all(
        float(candidate.geometry["trim_distance"])
        <= float(candidate.geometry["requested_trim_distance"])
        for candidate in result.candidates
    )
    assert not validate_outline(result.outline)


def test_quadratic_line_joins_are_rounded_without_discontinuity() -> None:
    contour = Contour(
        [
            QuadraticSegment(Point(0, 0), Point(50, -20), Point(100, 0)),
            LineSegment(Point(100, 0), Point(100, 100)),
            LineSegment(Point(100, 100), Point(0, 100)),
            LineSegment(Point(0, 100), Point(0, 0)),
        ],
        True,
        0,
    )
    result = round_line_corners(
        GlyphOutline("quadratic", [contour], 500), RoundingConfig(), upm=1000
    )

    assert result.candidates
    assert result.applied_candidate_ids
    assert not validate_outline(result.outline)
    assert (
        sum(
            isinstance(segment, QuadraticSegment) for segment in result.outline.contours[0].segments
        )
        > 1
    )


def test_outline_pen_expands_implied_quadratic_points_and_serializes() -> None:
    pen = OutlinePen()
    pen.moveTo((0, 0))
    pen.qCurveTo((50, 100), (100, 100), (150, 0))
    pen.lineTo((0, 0))
    pen.closePath()

    contour = pen.contours[0]
    quadratics = [segment for segment in contour.segments if isinstance(segment, QuadraticSegment)]
    assert len(quadratics) == 2
    assert quadratics[0].end == Point(75, 100)
    glyph = outline_to_glyph(GlyphOutline("q", pen.contours, 500))
    assert glyph.numberOfContours == 1


def test_outline_pen_expands_contour_with_only_off_curve_points() -> None:
    pen = OutlinePen()
    pen.qCurveTo((0, 0), (100, 0), None)
    pen.closePath()
    assert len(pen.contours) == 1
    assert len(pen.contours[0].segments) == 2
    assert all(isinstance(segment, QuadraticSegment) for segment in pen.contours[0].segments)
    assert pen.contours[0].segments[0].start == Point(50, 0)


def test_serializer_uses_implicit_closing_line_without_duplicate_point() -> None:
    outline = _outline([(0, 0), (100, 0), (100, 100), (0, 100)])
    glyph = outline_to_glyph(outline)
    assert len(glyph.coordinates) == 4


def test_cleanup_accepts_a_simple_valid_outline() -> None:
    outline = _outline([(0, 0), (100, 0), (100, 100), (0, 100)])
    result = cleanup_outline(outline, CleanupConfig(), upm=1000)
    assert not result.warnings
    assert not validate_outline(result.outline)
