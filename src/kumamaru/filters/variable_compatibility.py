"""Interpolation-safe repairs after Glyphs open-corner preprocessing."""

from __future__ import annotations

from typing import Any

from ufo2ft.filters import BaseFilter  # type: ignore[import-untyped]


class VariableCompatibilityFilter(BaseFilter):  # type: ignore[misc]
    """Keep two upstream open-corner results compatible across masters.

    glyphsLib's ``eraseOpenCorners`` filter produces one extra line segment in
    ``wa-hira`` Bold and one degenerate line segment in ``asmall-hira`` Regular.
    This filter is intentionally run immediately after that source filter and
    before cu2qu converts the compatible cubics together.
    """

    _pre = True

    def filter(self, glyph: Any) -> bool:
        style_name = str(self.context.font.info.styleName)
        if glyph.name == "wa-hira" and style_name in {"Thin", "Regular"}:
            return _split_first_contour_closing_line(glyph)
        if glyph.name == "asmall-hira" and style_name == "Regular":
            return _remove_first_contour_degenerate_opening_line(glyph)
        return False


def _split_first_contour_closing_line(glyph: Any) -> bool:
    if not len(glyph):
        return False
    contour = glyph[0]
    if len(contour) < 2:
        return False
    start = contour[0]
    end = contour[-1]
    if start.type != "line" or end.type not in {"curve", "qcurve"}:
        return False
    midpoint = (
        (end.x + start.x) / 2.0,
        (end.y + start.y) / 2.0,
    )
    contour.append(
        type(start)(
            midpoint[0],
            midpoint[1],
            type="line",
        ),
    )
    return True


def _remove_first_contour_degenerate_opening_line(glyph: Any) -> bool:
    if not len(glyph):
        return False
    contour = glyph[0]
    if len(contour) < 2:
        return False
    first = contour[0]
    duplicate = contour[1]
    if (
        first.type != "line"
        or duplicate.type != "line"
        or (first.x, first.y) != (duplicate.x, duplicate.y)
    ):
        return False
    del contour[1]
    return True
