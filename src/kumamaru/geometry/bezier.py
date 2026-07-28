"""Quadratic Bézier evaluation helpers."""

from __future__ import annotations

from kumamaru.geometry.vectors import lerp
from kumamaru.model import Point, QuadraticSegment


def quadratic_point(segment: QuadraticSegment, t: float) -> Point:
    first = lerp(segment.start, segment.control, t)
    second = lerp(segment.control, segment.end, t)
    return lerp(first, second, t)


def quadratic_tangent(segment: QuadraticSegment, t: float) -> Point:
    return Point(
        2.0
        * (
            (1.0 - t) * (segment.control.x - segment.start.x)
            + t * (segment.end.x - segment.control.x)
        ),
        2.0
        * (
            (1.0 - t) * (segment.control.y - segment.start.y)
            + t * (segment.end.y - segment.control.y)
        ),
    )
