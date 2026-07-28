from __future__ import annotations

import pytest

from kumamaru.geometry.safety import symmetric_boundary_deviation, topology_signature
from kumamaru.model import Candidate, Contour, GlyphOutline, LineSegment, Point
from kumamaru.pipeline import _candidate_edit_bound, _candidate_screening_bound


def _rectangle(
    x_min: float, y_min: float, x_max: float, y_max: float, *, index: int = 0
) -> Contour:
    points = [
        Point(x_min, y_min),
        Point(x_max, y_min),
        Point(x_max, y_max),
        Point(x_min, y_max),
    ]
    return Contour(
        [
            LineSegment(points[position], points[(position + 1) % len(points)])
            for position in range(len(points))
        ],
        True,
        index,
    )


def test_boundary_deviation_detects_large_internal_reshape() -> None:
    before = GlyphOutline("box", [_rectangle(0, 0, 400, 400)], 500)
    after = GlyphOutline("box", [_rectangle(100, 0, 300, 400)], 500)

    assert symmetric_boundary_deviation(before, after) == pytest.approx(100)
    assert symmetric_boundary_deviation(
        before, after, subdivisions=3, max_samples=8
    ) == pytest.approx(100)


def test_topology_signature_tracks_nested_holes_independent_of_order() -> None:
    outer = _rectangle(0, 0, 400, 400, index=0)
    hole = _rectangle(100, 100, 300, 300, index=1)
    outline = GlyphOutline("ring", [outer, hole], 500)
    reordered = GlyphOutline("ring", [hole, outer], 500)

    assert topology_signature(outline) == (0, 1)
    assert topology_signature(reordered) == (0, 1)


def test_boundary_deviation_is_independent_of_line_segmentation() -> None:
    before = GlyphOutline("box", [_rectangle(0, 0, 400, 400)], 500)
    after = GlyphOutline(
        "box",
        [
            Contour(
                [
                    LineSegment(Point(0, 0), Point(200, 0)),
                    LineSegment(Point(200, 0), Point(400, 0)),
                    LineSegment(Point(400, 0), Point(400, 400)),
                    LineSegment(Point(400, 400), Point(0, 400)),
                    LineSegment(Point(0, 400), Point(0, 0)),
                ],
                True,
                0,
            )
        ],
        500,
    )

    assert symmetric_boundary_deviation(
        before, after, subdivisions=2, max_samples=4
    ) == pytest.approx(0)


def test_compact_corner_bound_measures_curve_deviation_not_trim_length() -> None:
    candidate = Candidate(
        candidate_id="corner-acute",
        kind="corner",
        glyph_name="bopomofo",
        contour_index=0,
        segment_start=0,
        segment_end=1,
        direction="up",
        confidence=1.0,
        reason="test",
        point=Point(0, 0),
        geometry={
            "radius": 70.0,
            "trim_distance": 122.769376,
            "interior_angle_deg": 59.381395,
        },
    )

    assert _candidate_edit_bound(candidate) == pytest.approx(53.326, abs=0.001)
    assert _candidate_edit_bound(candidate) < 80.0
    assert _candidate_screening_bound(candidate) == pytest.approx(122.769376)
    assert _candidate_screening_bound(candidate) > 80.0
