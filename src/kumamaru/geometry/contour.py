"""FontTools pen adapters for the explicit Kumamaru outline model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fontTools.misc.roundTools import otRound  # type: ignore[import-untyped]
from fontTools.pens.basePen import BasePen  # type: ignore[import-untyped]
from fontTools.pens.ttGlyphPen import TTGlyphPen  # type: ignore[import-untyped]

from kumamaru.geometry.vectors import distance, is_finite
from kumamaru.model import (
    Contour,
    GlyphOutline,
    LineSegment,
    Point,
    QuadraticSegment,
)


class OutlineModelError(ValueError):
    pass


class OutlinePen(BasePen):  # type: ignore[misc]
    """Collect atomic line/quadratic segments and decompose components."""

    def __init__(self, glyph_set: Any | None = None) -> None:
        super().__init__(glyph_set)
        self.contours: list[Contour] = []
        self._segments: list[LineSegment | QuadraticSegment] = []
        self._start: Point | None = None
        self._current: Point | None = None

    def _moveTo(self, point: tuple[float, float]) -> None:
        if self._start is not None:
            raise OutlineModelError("a contour was not closed before moveTo")
        self._start = self._point(point)
        self._current = self._start

    def _lineTo(self, point: tuple[float, float]) -> None:
        if self._current is None:
            raise OutlineModelError("lineTo before moveTo")
        end = self._point(point)
        self._segments.append(LineSegment(self._current, end))
        self._current = end

    def _qCurveToOne(self, control: tuple[float, float], point: tuple[float, float]) -> None:
        if self._current is None:
            raise OutlineModelError("qCurveTo before moveTo")
        control_point, end = self._point(control), self._point(point)
        self._segments.append(QuadraticSegment(self._current, control_point, end))
        self._current = end

    def _curveToOne(
        self,
        point1: tuple[float, float],
        point2: tuple[float, float],
        point3: tuple[float, float],
    ) -> None:
        raise OutlineModelError(
            f"cubic segment is not valid in a TrueType glyf outline: {point1}, {point2}, {point3}"
        )

    def _closePath(self) -> None:
        if self._start is None or self._current is None:
            raise OutlineModelError("closePath before moveTo")
        if distance(self._current, self._start) > 1e-9:
            self._segments.append(LineSegment(self._current, self._start))
        self._finish(closed=True)

    def _endPath(self) -> None:
        self._finish(closed=False)

    def _finish(self, *, closed: bool) -> None:
        self.contours.append(
            Contour(
                segments=self._segments,
                closed=closed,
                source_contour_index=len(self.contours),
            )
        )
        self._segments = []
        self._start = None
        self._current = None

    @staticmethod
    def _point(raw: tuple[float, float]) -> Point:
        point = Point(float(raw[0]), float(raw[1]))
        if not is_finite(point):
            raise OutlineModelError(f"non-finite coordinate: {raw}")
        return point


def glyph_to_outline(
    glyph: Any,
    *,
    glyph_name: str,
    width: int,
    glyph_set: Any | None = None,
) -> GlyphOutline:
    pen = OutlinePen(glyph_set)
    glyph.draw(pen)
    return GlyphOutline(glyph_name=glyph_name, contours=pen.contours, width=width)


def outline_to_glyph(outline: GlyphOutline) -> Any:
    """Serialize a closed line/quadratic outline using OpenType rounding."""

    pen = TTGlyphPen(None)
    for contour in outline.contours:
        if not contour.closed:
            raise OutlineModelError("TrueType glyf output cannot contain open contours")
        if not contour.segments:
            continue
        # Start immediately after a straight segment when possible. This makes
        # that straight segment the implicit close edge and avoids serializing
        # the start point twice after corner rounding.
        closing_line_index = next(
            (
                index
                for index, segment in enumerate(contour.segments)
                if isinstance(segment, LineSegment)
            ),
            len(contour.segments) - 1,
        )
        segments = (
            contour.segments[closing_line_index + 1 :] + contour.segments[: closing_line_index + 1]
        )
        first = segments[0].start
        pen.moveTo((otRound(first.x), otRound(first.y)))
        current = first
        for index, segment in enumerate(segments):
            if distance(current, segment.start) > 1e-6:
                raise OutlineModelError("discontinuous contour segment chain")
            if isinstance(segment, LineSegment):
                is_implicit_closing_line = (
                    index == len(segments) - 1 and distance(segment.end, first) <= 1e-6
                )
                if not is_implicit_closing_line:
                    pen.lineTo((otRound(segment.end.x), otRound(segment.end.y)))
            else:
                pen.qCurveTo(
                    (otRound(segment.control.x), otRound(segment.control.y)),
                    (otRound(segment.end.x), otRound(segment.end.y)),
                )
            current = segment.end
        if distance(current, first) > 1e-6:
            raise OutlineModelError("closed contour does not end at its starting point")
        pen.closePath()
    return pen.glyph()


def clone_outline(outline: GlyphOutline) -> GlyphOutline:
    return deepcopy(outline)


def validate_outline(outline: GlyphOutline) -> list[str]:
    errors: list[str] = []
    for contour in outline.contours:
        if not contour.closed:
            errors.append(f"contour {contour.source_contour_index} is open")
        if not contour.segments:
            errors.append(f"contour {contour.source_contour_index} is empty")
            continue
        for index, segment in enumerate(contour.segments):
            for point in (
                (segment.start, segment.end)
                if isinstance(segment, LineSegment)
                else (segment.start, segment.control, segment.end)
            ):
                if not is_finite(point):
                    errors.append(
                        f"contour {contour.source_contour_index} segment {index} is non-finite"
                    )
            following = contour.segments[(index + 1) % len(contour.segments)]
            if distance(segment.end, following.start) > 1e-6:
                errors.append(
                    f"contour {contour.source_contour_index} segment {index} is discontinuous"
                )
    return errors
