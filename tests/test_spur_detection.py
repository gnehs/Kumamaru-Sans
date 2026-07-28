from __future__ import annotations

from kumamaru.config import SpurConfig, TerminalConfig
from kumamaru.filters.spur_detection import (
    auto_apply_candidate_ids,
    detect_spur_candidates,
)
from kumamaru.filters.terminal_rounding import (
    analyze_terminal_candidates,
    apply_terminal_candidates,
)
from kumamaru.model import Contour, GlyphOutline, LineSegment, Point


def _outline(points: list[tuple[float, float]], name: str = "shape") -> GlyphOutline:
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


def _flare() -> GlyphOutline:
    return _outline(
        [
            (0, 400),
            (0, 50),
            (-10, 30),
            (-20, 0),
            (120, 0),
            (110, 30),
            (100, 50),
            (100, 400),
        ],
        "flare",
    )


def test_normal_square_cap_is_not_a_spur() -> None:
    outline = _outline([(0, 0), (100, 0), (100, 400), (0, 400)])
    terminals = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    spurs = detect_spur_candidates(outline, terminals.candidates, SpurConfig(), upm=1000)
    assert not spurs.candidates


def test_flare_reports_ratio_depth_and_stable_id() -> None:
    outline = _flare()
    terminals = analyze_terminal_candidates(
        outline, TerminalConfig(), upm=1000, source_sha256="abc"
    )
    first = detect_spur_candidates(
        outline,
        terminals.candidates,
        SpurConfig(),
        upm=1000,
        source_sha256="abc",
    )
    second = detect_spur_candidates(
        outline,
        terminals.candidates,
        SpurConfig(),
        upm=1000,
        source_sha256="abc",
    )
    changed_source = detect_spur_candidates(
        outline,
        terminals.candidates,
        SpurConfig(),
        upm=1000,
        source_sha256="def",
    )

    assert len(first.candidates) == 1
    spur = first.candidates[0]
    assert spur.geometry["flare_ratio"] == 1.4
    assert spur.geometry["flare_depth"] == 50.0
    assert spur.candidate_id == second.candidates[0].candidate_id
    assert spur.candidate_id != changed_source.candidates[0].candidate_id
    assert spur.to_dict()["point"] == {"x": -20, "y": 0}


def test_report_only_never_auto_applies() -> None:
    outline = _flare()
    terminals = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    spurs = detect_spur_candidates(outline, terminals.candidates, SpurConfig(), upm=1000)
    assert auto_apply_candidate_ids(spurs.candidates, SpurConfig()) == set()


def test_override_can_apply_spur_candidate_and_preserves_extreme() -> None:
    outline = _flare()
    terminals = analyze_terminal_candidates(outline, TerminalConfig(), upm=1000)
    spurs = detect_spur_candidates(outline, terminals.candidates, SpurConfig(), upm=1000)
    spur = spurs.candidates[0]
    result = apply_terminal_candidates(outline, spurs.candidates, [spur.candidate_id])

    assert result.applied_candidate_ids == [spur.candidate_id]
    minimum_y = min(segment.start.y for segment in result.outline.contours[0].segments)
    assert minimum_y == 0


def test_hook_like_directional_tip_is_not_classified_as_spur() -> None:
    hook = _outline(
        [(0, 400), (0, 0), (80, 0), (130, 45), (95, 70), (70, 45), (70, 400)],
        "hook",
    )
    terminals = analyze_terminal_candidates(hook, TerminalConfig(), upm=1000)
    spurs = detect_spur_candidates(hook, terminals.candidates, SpurConfig(), upm=1000)
    assert not spurs.candidates
