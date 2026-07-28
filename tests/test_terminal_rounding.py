from __future__ import annotations

import math

from kumamaru.config import TerminalConfig
from kumamaru.filters.terminal_rounding import (
    analyze_terminal_candidates,
    apply_terminal_candidates,
    auto_round_cap_candidate_ids,
)
from kumamaru.geometry.contour import validate_outline
from kumamaru.model import (
    Candidate,
    Contour,
    GlyphOutline,
    LineSegment,
    Point,
    QuadraticSegment,
)


def _outline(points: list[tuple[float, float]], name: str = "stem") -> GlyphOutline:
    vertices = [Point(*point) for point in points]
    return GlyphOutline(
        name,
        [
            Contour(
                [
                    LineSegment(vertices[index], vertices[(index + 1) % len(vertices)])
                    for index in range(len(vertices))
                ],
                True,
                0,
            )
        ],
        500,
    )


def test_finds_only_two_caps_on_rectangular_stem() -> None:
    outline = _outline([(0, 0), (100, 0), (100, 400), (0, 400)])
    result = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)

    assert len(result.candidates) == 2
    assert {candidate.direction for candidate in result.candidates} == {"up", "down"}
    assert {candidate.geometry["shaft_width"] for candidate in result.candidates} == {100.0}
    assert {candidate.geometry["shaft_width_em"] for candidate in result.candidates} == {0.1}
    assert {candidate.geometry["flare_ratio"] for candidate in result.candidates} == {1.0}


def test_detection_is_rotation_independent() -> None:
    angle = math.radians(37)

    def rotate(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (
            x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
        )

    outline = _outline([rotate(point) for point in [(0, 0), (100, 0), (100, 400), (0, 400)]])
    result = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    assert len(result.candidates) == 2
    assert all(
        float(candidate.geometry["parallel_error_deg"]) < 1e-6 for candidate in result.candidates
    )


def test_explicit_candidate_builds_two_tangent_quadratics_once() -> None:
    outline = _outline([(0, 0), (100, 0), (100, 400), (0, 400)])
    analysis = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    bottom = next(candidate for candidate in analysis.candidates if candidate.direction == "down")
    result = apply_terminal_candidates(outline, analysis.candidates, [bottom.candidate_id])

    assert result.applied_candidate_ids == [bottom.candidate_id]
    assert len(result.outline.contours[0].segments) == 5
    curves = [
        segment
        for segment in result.outline.contours[0].segments
        if isinstance(segment, QuadraticSegment)
    ]
    assert len(curves) == 2
    assert curves[0].end == curves[1].start
    assert curves[0].end.y == 0
    assert not validate_outline(result.outline)
    assert all(isinstance(segment, LineSegment) for segment in outline.contours[0].segments)


def test_mixed_contour_rounds_local_line_cap_and_preserves_existing_curve() -> None:
    contour = Contour(
        [
            LineSegment(Point(0, 0), Point(100, 0)),
            LineSegment(Point(100, 0), Point(100, 400)),
            QuadraticSegment(Point(100, 400), Point(50, 450), Point(0, 400)),
            LineSegment(Point(0, 400), Point(0, 0)),
        ],
        True,
        0,
    )
    outline = GlyphOutline("mixed", [contour], 500)
    analysis = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)

    assert len(analysis.candidates) == 1
    assert analysis.candidates[0].direction == "down"

    result = apply_terminal_candidates(
        outline, analysis.candidates, [analysis.candidates[0].candidate_id]
    )
    curves = [
        segment
        for segment in result.outline.contours[0].segments
        if isinstance(segment, QuadraticSegment)
    ]
    assert len(curves) == 3
    assert any(segment.control == Point(50, 450) for segment in curves)
    assert not validate_outline(result.outline)


def test_quadratic_sided_cap_is_detected_and_rounded() -> None:
    contour = Contour(
        [
            QuadraticSegment(Point(0, 400), Point(0, 180), Point(0, 0)),
            LineSegment(Point(0, 0), Point(100, 0)),
            QuadraticSegment(Point(100, 0), Point(100, 180), Point(100, 400)),
            LineSegment(Point(100, 400), Point(0, 400)),
        ],
        True,
        0,
    )
    outline = GlyphOutline("quadratic-cap", [contour], 500)
    analysis = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    bottom = next(candidate for candidate in analysis.candidates if candidate.direction == "down")

    assert bottom.geometry["side_a_type"] == "quadratic"
    assert bottom.geometry["side_b_type"] == "quadratic"
    assert bottom.candidate_id in auto_round_cap_candidate_ids(
        analysis.candidates, TerminalConfig()
    )

    result = apply_terminal_candidates(outline, analysis.candidates, [bottom.candidate_id])

    assert result.applied_candidate_ids == [bottom.candidate_id]
    assert not validate_outline(result.outline)
    assert len(result.outline.contours[0].segments) == 5
    assert all(
        isinstance(segment, QuadraticSegment) for segment in result.outline.contours[0].segments[:4]
    )


def test_auto_rounding_selects_normal_caps_but_not_flares() -> None:
    normal = _outline([(0, 0), (100, 0), (100, 400), (0, 400)])
    candidates = analyze_terminal_candidates(normal, TerminalConfig(), upm=1000).candidates
    assert {
        (
            candidate.geometry["join_a_type"],
            candidate.geometry["join_b_type"],
        )
        for candidate in candidates
    } == {("outer", "outer")}
    assert auto_round_cap_candidate_ids(candidates, TerminalConfig()) == {
        candidate.candidate_id for candidate in candidates
    }

    flare = _outline(
        [
            (0, 400),
            (0, 50),
            (-10, 30),
            (-20, 0),
            (120, 0),
            (110, 30),
            (100, 50),
            (100, 400),
        ]
    )
    flare_candidates = analyze_terminal_candidates(flare, TerminalConfig(), upm=1000).candidates
    selected = auto_round_cap_candidate_ids(flare_candidates, TerminalConfig())
    assert all(
        float(candidate.geometry["flare_ratio"]) < 1.12
        for candidate in flare_candidates
        if candidate.candidate_id in selected
    )


def test_auto_rounding_accepts_slightly_slanted_cap() -> None:
    outline = _outline([(0, 0), (100, 20), (100, 400), (0, 400)])
    candidates = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000).candidates
    slanted = min(candidates, key=lambda candidate: candidate.confidence)

    assert 0.8 <= slanted.confidence < 0.98
    assert slanted.candidate_id in auto_round_cap_candidate_ids(candidates, TerminalConfig())


def test_auto_rounding_accepts_short_narrow_curved_terminal() -> None:
    contour = Contour(
        [
            QuadraticSegment(Point(0, 80), Point(0, 40), Point(0, 0)),
            LineSegment(Point(0, 0), Point(55, 0)),
            QuadraticSegment(Point(55, 0), Point(55, 40), Point(55, 80)),
            LineSegment(Point(55, 80), Point(0, 80)),
        ],
        True,
        0,
    )
    candidates = analyze_terminal_candidates(
        GlyphOutline("short-curved-terminal", [contour], 200),
        TerminalConfig(),
        upm=1000,
    ).candidates
    bottom = next(candidate for candidate in candidates if candidate.direction == "down")

    assert 1.15 <= float(bottom.geometry["shaft_aspect_ratio"]) < 2.0
    assert bottom.candidate_id in auto_round_cap_candidate_ids(candidates, TerminalConfig())


def test_auto_rounding_accepts_short_narrow_line_terminal() -> None:
    outline = _outline([(0, 0), (55, 0), (55, 80), (0, 80)])
    candidates = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000).candidates

    assert candidates
    assert all(
        1.25 <= float(candidate.geometry["shaft_aspect_ratio"]) < 2.0 for candidate in candidates
    )
    assert auto_round_cap_candidate_ids(candidates, TerminalConfig()) == {
        candidate.candidate_id for candidate in candidates
    }


def test_auto_rounding_rejects_box_like_and_nested_counter_candidates() -> None:
    box = _outline([(0, 0), (300, 0), (300, 400), (0, 400)])
    square_candidates = analyze_terminal_candidates(box, TerminalConfig(), upm=1000).candidates
    assert square_candidates
    assert not auto_round_cap_candidate_ids(square_candidates, TerminalConfig())

    outer = _outline([(0, 0), (500, 0), (500, 700), (0, 700)]).contours[0]
    hole = _outline([(80, 80), (80, 620), (420, 620), (420, 80)]).contours[0]
    hole.source_contour_index = 1
    ring = GlyphOutline("ring", [outer, hole], 600)
    ring_candidates = analyze_terminal_candidates(ring, TerminalConfig(), upm=1000).candidates

    assert ring_candidates
    assert not auto_round_cap_candidate_ids(ring_candidates, TerminalConfig())
    assert any(
        bool(candidate.geometry["contains_contour"])
        for candidate in ring_candidates
        if candidate.contour_index == 0
    )
    assert all(
        int(candidate.geometry["nesting_depth"]) == 1
        for candidate in ring_candidates
        if candidate.contour_index == 1
    )

    thick_stem = _outline([(0, 0), (150, 0), (150, 600), (0, 600)])
    thick_candidates = analyze_terminal_candidates(
        thick_stem, TerminalConfig(), upm=1000
    ).candidates
    assert thick_candidates
    assert not auto_round_cap_candidate_ids(thick_candidates, TerminalConfig())


def test_auto_rounding_rejects_inner_join_that_only_looks_like_a_cap() -> None:
    candidate = Candidate(
        candidate_id="terminal-inner-join",
        kind="terminal",
        glyph_name="junction",
        contour_index=0,
        segment_start=1,
        segment_end=1,
        direction="up",
        confidence=1.0,
        reason="test",
        point=Point(50, 50),
        geometry={
            "flare_ratio": 1.0,
            "shaft_aspect_ratio": 4.0,
            "shaft_width_em": 0.05,
            "flare_depth_em": 0.0,
            "nesting_depth": 0,
            "join_a_type": "inner",
            "join_b_type": "inner",
            "side_a_type": "line",
            "side_b_type": "line",
        },
    )

    assert not auto_round_cap_candidate_ids([candidate], TerminalConfig())


def test_unknown_candidate_is_not_silently_ignored() -> None:
    outline = _outline([(0, 0), (100, 0), (100, 400), (0, 400)])
    result = apply_terminal_candidates(outline, [], ["terminal-does-not-exist"])
    assert result.applied_candidate_ids == []
    assert result.warnings == ["unknown terminal candidate: terminal-does-not-exist"]


def test_short_or_non_parallel_shape_is_not_a_terminal() -> None:
    outline = _outline([(0, 0), (30, 0), (45, 25), (5, 35)])
    result = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    assert not result.candidates
