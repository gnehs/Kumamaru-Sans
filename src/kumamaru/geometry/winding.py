"""Contour signed-area and orientation helpers."""

from __future__ import annotations

from kumamaru.geometry.bezier import quadratic_point
from kumamaru.geometry.vectors import distance, midpoint, normalize, perpendicular, scale
from kumamaru.model import Contour, GlyphOutline, LineSegment, Point, QuadraticSegment


def _cross_points(a: Point, b: Point) -> float:
    return a.x * b.y - a.y * b.x


def signed_area(contour: Contour) -> float:
    """Return oriented area; quadratics use their exact polynomial integral."""

    area_twice = 0.0
    for segment in contour.segments:
        if isinstance(segment, LineSegment):
            area_twice += _cross_points(segment.start, segment.end)
        elif isinstance(segment, QuadraticSegment):
            # Integral of x dy - y dx for a quadratic Bézier.
            p0, p1, p2 = segment.start, segment.control, segment.end
            area_twice += (
                2.0 * _cross_points(p0, p1) + _cross_points(p0, p2) + 2.0 * _cross_points(p1, p2)
            ) / 3.0
    return area_twice / 2.0


def orientation(contour: Contour, *, epsilon: float = 1e-9) -> int:
    area = signed_area(contour)
    if area > epsilon:
        return 1
    if area < -epsilon:
        return -1
    return 0


def flattened_points(contour: Contour, quadratic_steps: int = 8) -> list[Point]:
    points: list[Point] = []
    for segment in contour.segments:
        if not points:
            points.append(segment.start)
        if isinstance(segment, QuadraticSegment):
            points.extend(
                quadratic_point(segment, step / quadratic_steps)
                for step in range(1, quadratic_steps + 1)
            )
        else:
            points.append(segment.end)
    return points


def point_in_contour(point: Point, contour: Contour) -> bool:
    """Return even-odd containment for a flattened analysis-only contour."""

    return _point_in_vertices(point, flattened_points(contour))


def _point_in_vertices(point: Point, vertices: list[Point]) -> bool:
    inside = False
    for start, end in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        if (start.y > point.y) == (end.y > point.y):
            continue
        crossing_x = start.x + (point.y - start.y) * (end.x - start.x) / (end.y - start.y)
        if crossing_x > point.x:
            inside = not inside
    return inside


def _interior_sample(contour: Contour) -> Point | None:
    contour_orientation = orientation(contour)
    points = flattened_points(contour)
    if contour_orientation == 0 or not points:
        return None
    extent = max(
        max(point.x for point in points) - min(point.x for point in points),
        max(point.y for point in points) - min(point.y for point in points),
        1.0,
    )
    for segment in contour.segments:
        unit = normalize(Point(segment.end.x - segment.start.x, segment.end.y - segment.start.y))
        if unit is None or distance(segment.start, segment.end) <= 1e-9:
            continue
        inward = scale(perpendicular(unit), float(contour_orientation))
        center = midpoint(segment.start, segment.end)
        return Point(
            center.x + inward.x * extent * 1e-5,
            center.y + inward.y * extent * 1e-5,
        )
    return None


def contour_nesting_depths(outline: GlyphOutline) -> dict[int, int]:
    """Count containing contours so hole corners can be classified as inner."""

    prepared: list[tuple[Contour, list[Point], tuple[float, float, float, float] | None]] = []
    for contour in outline.contours:
        vertices = flattened_points(contour)
        bounds = (
            None
            if not vertices
            else (
                min(point.x for point in vertices),
                min(point.y for point in vertices),
                max(point.x for point in vertices),
                max(point.y for point in vertices),
            )
        )
        prepared.append((contour, vertices, bounds))

    depths: dict[int, int] = {}
    for contour, _vertices, _bounds in prepared:
        sample = _interior_sample(contour)
        depths[contour.source_contour_index] = (
            0
            if sample is None
            else sum(
                bounds is not None
                and bounds[0] <= sample.x <= bounds[2]
                and bounds[1] <= sample.y <= bounds[3]
                and _point_in_vertices(sample, vertices)
                for other, vertices, bounds in prepared
                if other is not contour
            )
        )
    return depths
