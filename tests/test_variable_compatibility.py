from __future__ import annotations

import pytest

pytest.importorskip("ufo2ft")
from fontTools.cu2qu.ufo import _get_segments  # noqa: E402
from ufoLib2 import Font  # noqa: E402

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
