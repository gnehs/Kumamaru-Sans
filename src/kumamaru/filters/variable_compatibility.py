"""Interpolation-safe repairs after Glyphs open-corner preprocessing."""

from __future__ import annotations

from typing import Any

from ufo2ft.filters import BaseFilter  # type: ignore[import-untyped]


class VariableCompatibilityFilter(BaseFilter):  # type: ignore[misc]
    """Keep upstream open-corner results compatible across masters.

    glyphsLib's ``eraseOpenCorners`` filter produces master-specific line
    segmentation in a small set of IBM Plex Sans TC hiragana outlines. This
    filter is intentionally run immediately after that source filter and before
    cu2qu converts the compatible cubics together.
    """

    _pre = True

    def filter(self, glyph: Any) -> bool:
        style_name = str(self.context.font.info.styleName)
        if style_name == "Bold":
            closing_line_contours = {
                "bu-hira": 1,
                "hu-hira": 1,
                "ka-hira": 1,
                "pu-hira": 3,
            }
            contour_index = closing_line_contours.get(glyph.name)
            if contour_index is not None:
                return _split_closing_line_and_rotate(glyph, contour_index)
            if glyph.name == "wasmall-hira":
                return _split_line_after_point(glyph, 1, 20)
            if glyph.name == "yasmall-hira":
                return _split_line_after_point(glyph, 2, 0)
        if glyph.name == "wa-hira" and style_name in {"Thin", "Regular"}:
            return _split_first_contour_closing_line(glyph)
        if glyph.name == "asmall-hira" and style_name == "Regular":
            return _remove_first_contour_degenerate_opening_line(glyph)
        return False


def _split_closing_line_and_rotate(glyph: Any, contour_index: int) -> bool:
    if len(glyph) <= contour_index:
        return False
    contour = glyph[contour_index]
    if (
        len(contour) < 3
        or contour[0].type != "line"
        or contour[1].type is not None
        or contour[-1].type not in {"curve", "qcurve"}
    ):
        return False
    start = contour[-1]
    end = contour[0]
    contour.append(
        type(end)(
            (start.x + end.x) / 2.0,
            (start.y + end.y) / 2.0,
            type="line",
        ),
    )
    contour[:] = [contour[-1], *contour[:-1]]
    return True


def _split_line_after_point(
    glyph: Any,
    contour_index: int,
    point_index: int,
) -> bool:
    if len(glyph) <= contour_index:
        return False
    contour = glyph[contour_index]
    next_index = point_index + 1
    if len(contour) <= next_index:
        return False
    start = contour[point_index]
    end = contour[next_index]
    if (
        start.type not in {"curve", "qcurve"}
        or end.type != "line"
        or len(contour) <= next_index + 1
        or contour[next_index + 1].type is not None
    ):
        return False
    contour.insert(
        next_index,
        type(end)(
            (start.x + end.x) / 2.0,
            (start.y + end.y) / 2.0,
            type="line",
        ),
    )
    return True


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
