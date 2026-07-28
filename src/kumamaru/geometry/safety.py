"""Source-relative outline safety measurements."""

from __future__ import annotations

import math

from kumamaru.geometry.bezier import quadratic_point
from kumamaru.geometry.winding import contour_nesting_depths
from kumamaru.model import GlyphOutline, LineSegment, Point


def boundary_samples(outline: GlyphOutline, *, subdivisions: int = 8) -> list[Point]:
    """Sample every line and quadratic without depending on serialized points."""

    if subdivisions <= 0:
        raise ValueError("subdivisions must be positive")
    samples: list[Point] = []
    for contour in outline.contours:
        for segment in contour.segments:
            for step in range(subdivisions):
                ratio = step / subdivisions
                if isinstance(segment, LineSegment):
                    samples.append(
                        Point(
                            segment.start.x + (segment.end.x - segment.start.x) * ratio,
                            segment.start.y + (segment.end.y - segment.start.y) * ratio,
                        )
                    )
                else:
                    samples.append(quadratic_point(segment, ratio))
    return samples


def symmetric_boundary_deviation(
    before: GlyphOutline,
    after: GlyphOutline,
    *,
    subdivisions: int = 8,
    max_samples: int | None = None,
) -> float:
    """Approximate the symmetric Hausdorff distance between two outline boundaries."""

    before_polylines = _boundary_polylines(before, subdivisions=subdivisions)
    after_polylines = _boundary_polylines(after, subdivisions=subdivisions)
    before_points = [point for polyline in before_polylines for point in polyline[:-1]]
    after_points = [point for polyline in after_polylines for point in polyline[:-1]]
    if max_samples is not None:
        if max_samples <= 0:
            raise ValueError("max_samples must be positive")
        before_points = _uniform_sample(before_points, max_samples)
        after_points = _uniform_sample(after_points, max_samples)
    before_edges = _polyline_edges(before_polylines)
    after_edges = _polyline_edges(after_polylines)
    if not before_points or not after_points or not before_edges or not after_edges:
        return 0.0 if not before_points and not after_points else float("inf")

    def directed(source: list[Point], target: list[tuple[Point, Point]]) -> float:
        return max(
            math.sqrt(min(_point_segment_distance_squared(point, *edge) for edge in target))
            for point in source
        )

    return max(directed(before_points, after_edges), directed(after_points, before_edges))


def _boundary_polylines(outline: GlyphOutline, *, subdivisions: int) -> list[list[Point]]:
    if subdivisions <= 0:
        raise ValueError("subdivisions must be positive")
    polylines: list[list[Point]] = []
    for contour in outline.contours:
        if not contour.segments:
            continue
        points = [contour.segments[0].start]
        for segment in contour.segments:
            if isinstance(segment, LineSegment):
                points.append(segment.end)
            else:
                points.extend(
                    quadratic_point(segment, step / subdivisions)
                    for step in range(1, subdivisions + 1)
                )
        if points[-1] != points[0]:
            points.append(points[0])
        polylines.append(points)
    return polylines


def _polyline_edges(polylines: list[list[Point]]) -> list[tuple[Point, Point]]:
    return [
        (start, end)
        for polyline in polylines
        for start, end in zip(polyline, polyline[1:], strict=False)
    ]


def _point_segment_distance_squared(point: Point, start: Point, end: Point) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return (point.x - start.x) ** 2 + (point.y - start.y) ** 2
    projection = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_squared
    ratio = max(0.0, min(1.0, projection))
    nearest_x, nearest_y = start.x + ratio * dx, start.y + ratio * dy
    return (point.x - nearest_x) ** 2 + (point.y - nearest_y) ** 2


def _uniform_sample(points: list[Point], maximum: int) -> list[Point]:
    if len(points) <= maximum:
        return points
    return [points[index * len(points) // maximum] for index in range(maximum)]


def topology_signature(outline: GlyphOutline) -> tuple[int, ...]:
    """Return an order-independent nesting-depth signature."""

    return tuple(sorted(contour_nesting_depths(outline).values()))
