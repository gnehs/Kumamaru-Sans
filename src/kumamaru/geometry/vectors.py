"""Numerically defensive two-dimensional vector helpers."""

from __future__ import annotations

import math

from kumamaru.model import Point

EPSILON = 1e-9


def add(a: Point, b: Point) -> Point:
    return Point(a.x + b.x, a.y + b.y)


def subtract(a: Point, b: Point) -> Point:
    return Point(a.x - b.x, a.y - b.y)


def scale(vector: Point, factor: float) -> Point:
    return Point(vector.x * factor, vector.y * factor)


def dot(a: Point, b: Point) -> float:
    return a.x * b.x + a.y * b.y


def cross(a: Point, b: Point) -> float:
    return a.x * b.y - a.y * b.x


def length(vector: Point) -> float:
    return math.hypot(vector.x, vector.y)


def distance(a: Point, b: Point) -> float:
    return length(subtract(a, b))


def normalize(vector: Point, *, epsilon: float = EPSILON) -> Point | None:
    magnitude = length(vector)
    if not math.isfinite(magnitude) or magnitude <= epsilon:
        return None
    return scale(vector, 1.0 / magnitude)


def lerp(a: Point, b: Point, factor: float) -> Point:
    return Point(a.x + (b.x - a.x) * factor, a.y + (b.y - a.y) * factor)


def midpoint(a: Point, b: Point) -> Point:
    return lerp(a, b, 0.5)


def signed_angle_degrees(a: Point, b: Point) -> float | None:
    unit_a, unit_b = normalize(a), normalize(b)
    if unit_a is None or unit_b is None:
        return None
    return math.degrees(math.atan2(cross(unit_a, unit_b), dot(unit_a, unit_b)))


def angle_between_degrees(a: Point, b: Point) -> float | None:
    signed = signed_angle_degrees(a, b)
    return None if signed is None else abs(signed)


def direction_name(vector: Point) -> str:
    unit = normalize(vector)
    if unit is None:
        return "unknown"
    angle = math.degrees(math.atan2(unit.y, unit.x))
    if -22.5 <= angle < 22.5:
        return "right"
    if 22.5 <= angle < 67.5:
        return "up-right"
    if 67.5 <= angle < 112.5:
        return "up"
    if 112.5 <= angle < 157.5:
        return "up-left"
    if angle >= 157.5 or angle < -157.5:
        return "left"
    if -157.5 <= angle < -112.5:
        return "down-left"
    if -112.5 <= angle < -67.5:
        return "down"
    return "down-right"


def project(point: Point, origin: Point, axis: Point) -> float | None:
    unit = normalize(axis)
    return None if unit is None else dot(subtract(point, origin), unit)


def perpendicular(vector: Point) -> Point:
    return Point(-vector.y, vector.x)


def is_finite(point: Point) -> bool:
    return math.isfinite(point.x) and math.isfinite(point.y)
