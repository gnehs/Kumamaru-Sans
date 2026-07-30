from __future__ import annotations

import pytest

pytest.importorskip("ufo2ft")
from fontTools.cu2qu.ufo import _get_segments  # noqa: E402
from ufoLib2 import Font  # noqa: E402
from ufoLib2.objects import Contour, Point  # noqa: E402

from kumamaru.filters.variable_compatibility import (  # noqa: E402
    VariableCompatibilityFilter,
)


def _font(style_name: str) -> Font:
    font = Font()
    font.info.familyName = "Kumamaru Sans"
    font.info.styleName = style_name
    return font


def test_splits_wa_hira_closing_line_without_changing_its_geometry() -> None:
    font = _font("Regular")
    glyph = font.newGlyph("wa-hira")
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    pen.curveTo((20, 0), (80, 100), (100, 100))
    pen.lineTo((0, 0))
    pen.closePath()

    changed = VariableCompatibilityFilter()(font)

    assert changed == {"wa-hira"}
    segments = _get_segments(font["wa-hira"])
    assert [segment[0] for segment in segments] == [
        "move",
        "curve",
        "line",
        "line",
        "close",
    ]
    assert segments[2][1][-1] == (50, 50)


def test_removes_asmall_hira_zero_length_opening_line() -> None:
    font = _font("Regular")
    glyph = font.newGlyph("asmall-hira")
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    pen.lineTo((0, 0))
    pen.curveTo((20, 0), (80, 100), (100, 100))
    pen.lineTo((0, 0))
    pen.closePath()

    changed = VariableCompatibilityFilter()(font)

    assert changed == {"asmall-hira"}
    segments = _get_segments(font["asmall-hira"])
    assert [segment[0] for segment in segments] == [
        "move",
        "curve",
        "line",
        "close",
    ]


@pytest.mark.parametrize(
    ("glyph_name", "contour_index"),
    [
        ("bu-hira", 1),
        ("hu-hira", 1),
        ("ka-hira", 1),
        ("pu-hira", 3),
    ],
)
def test_splits_closing_line_for_bold_hiragana(
    glyph_name: str,
    contour_index: int,
) -> None:
    font = _font("Bold")
    glyph = font.newGlyph(glyph_name)
    for _ in range(contour_index + 1):
        pen = glyph.getPen()
        pen.moveTo((0, 0))
        pen.curveTo((0, 0), (80, 100), (100, 100))
        pen.lineTo((0, 0))
        pen.closePath()

    changed = VariableCompatibilityFilter()(font)

    assert changed == {glyph_name}
    segments = _get_segments(font[glyph_name])
    repaired = segments[contour_index * 4 : (contour_index + 1) * 4 + 1]
    assert [segment[0] for segment in repaired] == [
        "move",
        "line",
        "curve",
        "line",
        "close",
    ]
    split = repaired[0][1][-1]
    original_start = repaired[1][1][-1]
    original_end = repaired[2][1][-1]
    assert split == repaired[-2][1][-1]
    assert split == (
        (original_start[0] + original_end[0]) / 2.0,
        (original_start[1] + original_end[1]) / 2.0,
    )
    assert VariableCompatibilityFilter()(font) == set()


@pytest.mark.parametrize(
    ("glyph_name", "contour_index", "point_count", "split_point_index"),
    [
        ("wasmall-hira", 1, 24, 20),
        ("yasmall-hira", 2, 32, 0),
    ],
)
def test_splits_bold_hiragana_line_without_changing_its_geometry(
    glyph_name: str,
    contour_index: int,
    point_count: int,
    split_point_index: int,
) -> None:
    font = _font("Bold")
    glyph = font.newGlyph(glyph_name)
    for current_contour in range(contour_index + 1):
        if current_contour != contour_index:
            pen = glyph.getPen()
            pen.moveTo((0, 0))
            pen.lineTo((100, 0))
            pen.closePath()
            continue
        points = [Point(float(index), 0.0, type="line") for index in range(point_count)]
        points[split_point_index] = Point(
            float(split_point_index),
            0.0,
            type="curve",
        )
        points[split_point_index + 2] = Point(
            float(split_point_index + 2),
            0.0,
            type=None,
        )
        glyph.appendContour(Contour(points))

    changed = VariableCompatibilityFilter()(font)

    assert changed == {glyph_name}
    contour = font[glyph_name][contour_index]
    inserted = contour[split_point_index + 1]
    start = contour[split_point_index]
    end = contour[split_point_index + 2]
    assert (inserted.x, inserted.y) == (
        (start.x + end.x) / 2.0,
        (start.y + end.y) / 2.0,
    )
    assert VariableCompatibilityFilter()(font) == set()


def test_leaves_other_master_and_glyph_combinations_untouched() -> None:
    font = _font("Bold")
    for name in ("wa-hira", "asmall-hira", "A"):
        glyph = font.newGlyph(name)
        pen = glyph.getPen()
        pen.moveTo((0, 0))
        pen.lineTo((100, 0))
        pen.lineTo((0, 0))
        pen.closePath()

    changed = VariableCompatibilityFilter()(font)

    assert changed == set()
