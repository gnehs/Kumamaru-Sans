"""Topology-preserving corner rounding for Glyphs multi-master sources."""

from __future__ import annotations

import math
import os
import re
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SourceRoundingError(ValueError):
    """Raised when a Glyphs source cannot be transformed safely."""


class SourceRoundingDependencyError(RuntimeError):
    """Raised when the optional source-editing dependency is unavailable."""


def _glyphs_api() -> tuple[Any, Any, str, str, str]:
    """Import glyphsLib only when source editing is requested."""

    try:
        from glyphsLib import CURVE, LINE, OFFCURVE, GSFont, GSNode  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SourceRoundingDependencyError(
            "source rounding requires glyphsLib; install the optional "
            "dependency with `pip install 'kumamaru[source]'`"
        ) from exc
    return GSFont, GSNode, LINE, CURVE, OFFCURVE


@dataclass(frozen=True)
class _Point:
    x: float
    y: float


@dataclass(frozen=True)
class _Candidate:
    path_index: int
    node_index: int
    corner_type: str

    @property
    def candidate_id(self) -> str:
        return f"path-{self.path_index}:node-{self.node_index}"


@dataclass(frozen=True)
class _MasterEdit:
    master_id: str
    master_name: str
    path: Any
    node_index: int
    before: _Point
    control_1: _Point
    control_2: _Point
    after: _Point
    radius: float
    trim_distance: float
    requested_trim_distance: float


@dataclass(frozen=True)
class _TerminalCandidate:
    path_index: int
    start_node_index: int
    end_node_index: int

    @property
    def candidate_id(self) -> str:
        return f"path-{self.path_index}:terminal-{self.start_node_index}-{self.end_node_index}"


@dataclass(frozen=True)
class _TerminalEdit:
    master_id: str
    master_name: str
    path: Any
    start_node_index: int
    end_node_index: int
    start_node: Any
    end_node: Any
    start: _Point
    control_1: _Point
    control_2: _Point
    apex: _Point
    control_3: _Point
    control_4: _Point
    end: _Point
    start_control_index: int | None
    start_control_node: Any | None
    start_control: _Point | None
    end_control_index: int | None
    end_control_node: Any | None
    end_control: _Point | None
    shaft_width: float
    trim_distance: float


_BRACKET_LAYER_NAME = re.compile(r".*[\[\]]\s*\d+\s*\].*")
_ROUND_CAP_HANDLE = 0.5522847498307936
_MAX_TERMINAL_PERPENDICULAR_ERROR_DEGREES = 18.0
_RELAXED_TERMINAL_PERPENDICULAR_ERROR_DEGREES = 20.0
_RELAXED_TERMINAL_PARALLEL_ERROR_DEGREES = 2.0
_RELAXED_TERMINAL_MINIMUM_SIDE_RATIO = 2.5


def _xy(node: Any) -> _Point:
    return _Point(float(node.position.x), float(node.position.y))


def _sub(a: _Point, b: _Point) -> _Point:
    return _Point(a.x - b.x, a.y - b.y)


def _add(a: _Point, b: _Point) -> _Point:
    return _Point(a.x + b.x, a.y + b.y)


def _scale(point: _Point, factor: float) -> _Point:
    return _Point(point.x * factor, point.y * factor)


def _cross(a: _Point, b: _Point) -> float:
    return a.x * b.y - a.y * b.x


def _dot(a: _Point, b: _Point) -> float:
    return a.x * b.x + a.y * b.y


def _length(point: _Point) -> float:
    return math.hypot(point.x, point.y)


def _unit(point: _Point) -> _Point | None:
    length = _length(point)
    if not math.isfinite(length) or length <= 1e-9:
        return None
    return _scale(point, 1.0 / length)


def _oncurve_points(path: Any) -> list[_Point]:
    return [_xy(node) for node in path.nodes if node.type != "offcurve"]


def _signed_area(points: list[_Point]) -> float:
    return (
        sum(
            start.x * end.y - start.y * end.x
            for start, end in zip(points, points[1:] + points[:1], strict=True)
        )
        / 2.0
    )


def _point_in_polygon(point: _Point, vertices: list[_Point]) -> bool:
    inside = False
    for start, end in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        if (start.y > point.y) == (end.y > point.y):
            continue
        crossing_x = start.x + (point.y - start.y) * (end.x - start.x) / (end.y - start.y)
        if crossing_x > point.x:
            inside = not inside
    return inside


def _interior_sample(points: list[_Point]) -> _Point | None:
    area = _signed_area(points)
    if abs(area) <= 1e-9:
        return None
    orientation = 1.0 if area > 0 else -1.0
    extent = max(
        max(point.x for point in points) - min(point.x for point in points),
        max(point.y for point in points) - min(point.y for point in points),
        1.0,
    )
    for start, end in zip(points, points[1:] + points[:1], strict=True):
        unit = _unit(_sub(end, start))
        if unit is None:
            continue
        midpoint = _scale(_add(start, end), 0.5)
        inward = _Point(-unit.y * orientation, unit.x * orientation)
        return _add(midpoint, _scale(inward, extent * 1e-5))
    return None


def _path_depths(paths: list[Any]) -> list[int]:
    polygons = [_oncurve_points(path) for path in paths]
    bounds = [
        (
            min(point.x for point in polygon),
            min(point.y for point in polygon),
            max(point.x for point in polygon),
            max(point.y for point in polygon),
        )
        if polygon
        else None
        for polygon in polygons
    ]
    depths: list[int] = []
    for path_index, polygon in enumerate(polygons):
        sample = _interior_sample(polygon) if len(polygon) >= 3 else None
        path_bounds = bounds[path_index]
        depths.append(
            0
            if sample is None or path_bounds is None
            else sum(
                other_bounds is not None
                and other_bounds[0] <= path_bounds[0]
                and other_bounds[1] <= path_bounds[1]
                and other_bounds[2] >= path_bounds[2]
                and other_bounds[3] >= path_bounds[3]
                and _point_in_polygon(sample, other)
                for other_index, other in enumerate(polygons)
                for other_bounds in [bounds[other_index]]
                if other_index != path_index and len(other) >= 3
            )
        )
    return depths


def _is_locally_convex(path: Any, node_index: int) -> bool:
    nodes = list(path.nodes)
    if not path.closed or len(nodes) < 3:
        return False
    previous = _xy(nodes[(node_index - 1) % len(nodes)])
    corner = _xy(nodes[node_index])
    following = _xy(nodes[(node_index + 1) % len(nodes)])
    incoming = _sub(corner, previous)
    outgoing = _sub(following, corner)
    turn = _cross(incoming, outgoing)
    area = _signed_area(_oncurve_points(path))
    if abs(turn) <= 1e-9 or abs(area) <= 1e-9:
        return False
    return area * turn > 0


def _is_corner_type(
    path: Any,
    node_index: int,
    *,
    nesting_depth: int,
    corner_type: str,
) -> bool:
    locally_convex = _is_locally_convex(path, node_index)
    if corner_type == "outer":
        return locally_convex != (nesting_depth % 2 == 1)
    if corner_type == "inner":
        return nesting_depth % 2 == 1 and locally_convex
    raise AssertionError(f"unsupported corner type: {corner_type}")


def _reference_candidates(
    layer: Any,
    line_type: str,
    *,
    include_inner: bool,
) -> list[_Candidate]:
    paths = list(layer.paths)
    depths = _path_depths(paths)
    candidates: list[_Candidate] = []
    for path_index, path in enumerate(paths):
        nodes = list(path.nodes)
        if not path.closed or len(nodes) < 3:
            continue
        for node_index, node in enumerate(nodes):
            following = nodes[(node_index + 1) % len(nodes)]
            if node.type != line_type or following.type != line_type:
                continue
            if _is_corner_type(
                path,
                node_index,
                nesting_depth=depths[path_index],
                corner_type="outer",
            ):
                candidates.append(_Candidate(path_index, node_index, "outer"))
            elif include_inner and _is_corner_type(
                path,
                node_index,
                nesting_depth=depths[path_index],
                corner_type="inner",
            ):
                candidates.append(_Candidate(path_index, node_index, "inner"))
    return candidates


def _angle_error_degrees(a: _Point, b: _Point) -> float:
    cosine = max(-1.0, min(1.0, _dot(a, b)))
    return math.degrees(math.acos(cosine))


def _incoming_side(
    path: Any,
    end_index: int,
    *,
    line: str,
    curve: str,
    offcurve: str,
) -> tuple[_Point, float, int | None] | None:
    nodes = list(path.nodes)
    end = nodes[end_index]
    if end.type == line:
        previous_index = (end_index - 1) % len(nodes)
        if nodes[previous_index].type == offcurve:
            return None
        vector = _sub(_xy(end), _xy(nodes[previous_index]))
        return vector, _length(vector), None
    if end.type != curve:
        return None
    control_2_index = (end_index - 1) % len(nodes)
    control_1_index = (end_index - 2) % len(nodes)
    start_index = (end_index - 3) % len(nodes)
    if (
        nodes[control_2_index].type != offcurve
        or nodes[control_1_index].type != offcurve
        or nodes[start_index].type == offcurve
    ):
        return None
    points = [
        _xy(nodes[start_index]),
        _xy(nodes[control_1_index]),
        _xy(nodes[control_2_index]),
        _xy(end),
    ]
    length = sum(
        _length(_sub(following, previous))
        for previous, following in zip(points, points[1:], strict=False)
    )
    return _sub(points[-1], points[-2]), length, control_2_index


def _outgoing_side(
    path: Any,
    start_index: int,
    *,
    line: str,
    curve: str,
    offcurve: str,
) -> tuple[_Point, float, int | None] | None:
    nodes = list(path.nodes)
    next_index = (start_index + 1) % len(nodes)
    if nodes[next_index].type == line:
        vector = _sub(_xy(nodes[next_index]), _xy(nodes[start_index]))
        return vector, _length(vector), None
    control_1_index = next_index
    control_2_index = (start_index + 2) % len(nodes)
    end_index = (start_index + 3) % len(nodes)
    if (
        nodes[control_1_index].type != offcurve
        or nodes[control_2_index].type != offcurve
        or nodes[end_index].type != curve
    ):
        return None
    points = [
        _xy(nodes[start_index]),
        _xy(nodes[control_1_index]),
        _xy(nodes[control_2_index]),
        _xy(nodes[end_index]),
    ]
    length = sum(
        _length(_sub(following, previous))
        for previous, following in zip(points, points[1:], strict=False)
    )
    return _sub(points[1], points[0]), length, control_1_index


def _terminal_geometry(
    path: Any,
    candidate: _TerminalCandidate,
    *,
    nesting_depth: int,
    line: str,
    curve: str,
    offcurve: str,
    maximum_width: float,
) -> tuple[dict[str, Any] | None, str | None]:
    nodes = list(path.nodes)
    if not path.closed or len(nodes) < 4:
        return None, "terminal path is not a closed contour with at least four nodes"
    start_index = candidate.start_node_index
    end_index = candidate.end_node_index
    if (start_index + 1) % len(nodes) != end_index or nodes[end_index].type != line:
        return None, "terminal cap is not a single LINE segment"
    if nesting_depth % 2 == 1:
        return None, "terminal belongs to a counter contour"
    if not _is_corner_type(
        path, start_index, nesting_depth=nesting_depth, corner_type="outer"
    ) or not _is_corner_type(path, end_index, nesting_depth=nesting_depth, corner_type="outer"):
        return None, "terminal joins are not both outer"

    incoming = _incoming_side(
        path,
        start_index,
        line=line,
        curve=curve,
        offcurve=offcurve,
    )
    outgoing = _outgoing_side(
        path,
        end_index,
        line=line,
        curve=curve,
        offcurve=offcurve,
    )
    if incoming is None or outgoing is None:
        return None, "terminal shaft side is not LINE or cubic"
    incoming_vector, incoming_length, start_control_index = incoming
    outgoing_vector, outgoing_length, end_control_index = outgoing
    unit_in = _unit(incoming_vector)
    unit_out = _unit(outgoing_vector)
    if unit_in is None or unit_out is None:
        return None, "terminal shaft tangent is degenerate"
    parallel_error = _angle_error_degrees(unit_in, _scale(unit_out, -1.0))
    if parallel_error > 12.0:
        return None, "terminal shaft sides are not anti-parallel within 12 degrees"

    start = _xy(nodes[start_index])
    end = _xy(nodes[end_index])
    chord = _sub(end, start)
    width = _length(chord)
    width_unit = _unit(chord)
    if width_unit is None or width > maximum_width:
        return None, "terminal width is zero or exceeds the safe maximum"
    inward = _unit(_sub(unit_out, unit_in))
    if inward is None:
        return None, "terminal shaft axis is degenerate"
    outward = _scale(inward, -1.0)
    perpendicular_error = 90.0 - _angle_error_degrees(width_unit, inward)
    relaxed_perpendicular_gate = (
        abs(perpendicular_error) <= _RELAXED_TERMINAL_PERPENDICULAR_ERROR_DEGREES
        and parallel_error <= _RELAXED_TERMINAL_PARALLEL_ERROR_DEGREES
        and min(incoming_length, outgoing_length) >= width * _RELAXED_TERMINAL_MINIMUM_SIDE_RATIO
    )
    if (
        abs(perpendicular_error) > _MAX_TERMINAL_PERPENDICULAR_ERROR_DEGREES
        and not relaxed_perpendicular_gate
    ):
        return (
            None,
            "terminal cap exceeds the perpendicular safety gate",
        )
    if min(incoming_length, outgoing_length) < width * 2.0:
        return None, "terminal shaft sides are shorter than twice the width"

    radius = width / 2.0
    new_start = _sub(start, _scale(unit_in, radius))
    new_end = _add(end, _scale(unit_out, radius))
    new_width = _sub(new_end, new_start)
    new_width_unit = _unit(new_width)
    if new_width_unit is None:
        return None, "trimmed terminal width is degenerate"
    center = _scale(_add(new_start, new_end), 0.5)
    apex = _add(center, _scale(outward, radius))
    handle = radius * _ROUND_CAP_HANDLE
    start_delta = _sub(new_start, start)
    end_delta = _sub(new_end, end)
    return (
        {
            "start": new_start,
            "control_1": _add(new_start, _scale(outward, handle)),
            "control_2": _sub(apex, _scale(new_width_unit, handle)),
            "apex": apex,
            "control_3": _add(apex, _scale(new_width_unit, handle)),
            "control_4": _add(new_end, _scale(outward, handle)),
            "end": new_end,
            "start_control_index": start_control_index,
            "start_control": (
                None
                if start_control_index is None
                else _add(_xy(nodes[start_control_index]), start_delta)
            ),
            "end_control_index": end_control_index,
            "end_control": (
                None
                if end_control_index is None
                else _add(_xy(nodes[end_control_index]), end_delta)
            ),
            "shaft_width": width,
            "trim_distance": radius,
        },
        None,
    )


def _terminal_is_exposed(
    paths: list[Any],
    depths: list[int],
    candidate: _TerminalCandidate,
    geometry: Mapping[str, Any],
) -> bool:
    path = paths[candidate.path_index]
    nodes = list(path.nodes)
    cap_midpoint = _scale(
        _add(
            _xy(nodes[candidate.start_node_index]),
            _xy(nodes[candidate.end_node_index]),
        ),
        0.5,
    )
    test_points = (cap_midpoint, geometry["apex"])
    for other_index, other_path in enumerate(paths):
        if other_index == candidate.path_index or depths[other_index] % 2 == 1:
            continue
        polygon = _oncurve_points(other_path)
        if len(polygon) >= 3 and any(_point_in_polygon(point, polygon) for point in test_points):
            return False
    return True


def _reference_terminal_candidates(
    layer: Any,
    *,
    line: str,
    curve: str,
    offcurve: str,
    maximum_width: float,
) -> list[_TerminalCandidate]:
    paths = list(layer.paths)
    depths = _path_depths(paths)
    candidates: list[_TerminalCandidate] = []
    for path_index, path in enumerate(paths):
        nodes = list(path.nodes)
        for end_index, node in enumerate(nodes):
            if node.type != line:
                continue
            start_index = (end_index - 1) % len(nodes)
            if nodes[start_index].type == offcurve:
                continue
            candidate = _TerminalCandidate(path_index, start_index, end_index)
            geometry, _ = _terminal_geometry(
                path,
                candidate,
                nesting_depth=depths[path_index],
                line=line,
                curve=curve,
                offcurve=offcurve,
                maximum_width=maximum_width,
            )
            if geometry is not None and _terminal_is_exposed(
                paths,
                depths,
                candidate,
                geometry,
            ):
                candidates.append(candidate)
    return candidates


def _master_lookup(font: Any) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    ambiguous: set[str] = set()
    for master in font.masters:
        lookup[master.id] = master
        if master.name in lookup:
            ambiguous.add(master.name)
        else:
            lookup[master.name] = master
    for name in ambiguous:
        lookup.pop(name, None)
    return lookup


def _resolve_reference_master(font: Any, reference_master: str) -> Any:
    lookup = _master_lookup(font)
    master = lookup.get(reference_master)
    if master is None:
        available = ", ".join(sorted(master.name for master in font.masters))
        raise SourceRoundingError(
            f"reference master {reference_master!r} was not found or is ambiguous; "
            f"available masters: {available}"
        )
    return master


def _resolve_radii(
    font: Any,
    radii_by_master: Mapping[str, float] | float,
) -> dict[str, float]:
    if isinstance(radii_by_master, int | float):
        raw_radii: Mapping[str, float] = {"*": float(radii_by_master)}
    else:
        raw_radii = radii_by_master
    lookup = _master_lookup(font)
    resolved: dict[str, float] = {}
    unknown = sorted(key for key in raw_radii if key != "*" and key not in lookup)
    if unknown:
        raise SourceRoundingError(f"unknown or ambiguous radius master(s): {', '.join(unknown)}")
    for master in font.masters:
        matching = [
            float(value)
            for key, value in raw_radii.items()
            if key != "*" and lookup.get(key) is master
        ]
        if len(set(matching)) > 1:
            raise SourceRoundingError(f"conflicting radii for master {master.name!r}")
        radius = matching[0] if matching else raw_radii.get("*")
        if radius is None:
            raise SourceRoundingError(f"no radius supplied for master {master.name!r}")
        numeric_radius = float(radius)
        if not math.isfinite(numeric_radius) or numeric_radius <= 0:
            raise SourceRoundingError(
                f"radius for master {master.name!r} must be a finite positive number"
            )
        resolved[master.id] = numeric_radius
    return resolved


def resolve_glyph_tokens(font: Any, tokens: Iterable[str]) -> list[str]:
    """Resolve glyph names, single characters, and ``U+XXXX`` tokens."""

    by_name = {glyph.name: glyph for glyph in font.glyphs}
    by_unicode = {
        str(codepoint).upper(): glyph for glyph in font.glyphs for codepoint in glyph.unicodes
    }
    resolved: set[str] = set()
    missing: list[str] = []
    for raw_token in tokens:
        token = str(raw_token)
        glyph = by_name.get(token)
        if glyph is None:
            unicode_value: str | None = None
            if token.startswith(("U+", "u+")):
                try:
                    codepoint = int(token[2:], 16)
                except ValueError:
                    codepoint = -1
                if 0 <= codepoint <= 0x10FFFF:
                    unicode_value = f"{codepoint:04X}"
            elif len(token) == 1:
                unicode_value = f"{ord(token):04X}"
            if unicode_value is not None:
                glyph = by_unicode.get(unicode_value)
                if glyph is None:
                    codepoint = int(unicode_value, 16)
                    canonical_name = (
                        f"uni{codepoint:04X}" if codepoint <= 0xFFFF else f"u{codepoint:X}"
                    )
                    glyph = by_name.get(canonical_name)
        if glyph is None:
            missing.append(token)
        else:
            resolved.add(str(glyph.name))
    if missing:
        raise SourceRoundingError(f"glyph token(s) not found: {', '.join(sorted(missing))}")
    return sorted(resolved)


def _resolve_glyph_selection(
    font: Any,
    glyph_tokens: Iterable[str] | None,
    *,
    all_exporting_glyphs: bool,
) -> list[str]:
    tokens = list(glyph_tokens or ())
    if all_exporting_glyphs:
        if tokens:
            raise SourceRoundingError(
                "glyph_tokens must be empty when all_exporting_glyphs is enabled"
            )
        return sorted(str(glyph.name) for glyph in font.glyphs if bool(glyph.export))
    if glyph_tokens is None:
        raise SourceRoundingError(
            "glyph_tokens are required unless all_exporting_glyphs is enabled"
        )
    return resolve_glyph_tokens(font, tokens)


def _bracket_layers(font: Any, glyph: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for layer in glyph.layers:
        is_bracket = (
            "axisRules" in layer.attributes
            if font.format_version > 2
            else _BRACKET_LAYER_NAME.match(str(layer.name or "")) is not None
        )
        if is_bracket:
            found.append(
                {
                    "layer_id": str(layer.layerId),
                    "associated_master_id": str(layer.associatedMasterId),
                    "name": str(layer.name or ""),
                }
            )
    return sorted(
        found,
        key=lambda item: (item["associated_master_id"], item["layer_id"], item["name"]),
    )


def _topology_reason(
    reference_paths: list[Any],
    mapped_paths: list[Any],
    candidate: _Candidate,
) -> str | None:
    if len(mapped_paths) != len(reference_paths):
        return "path count differs from reference master"
    reference_path = reference_paths[candidate.path_index]
    mapped_path = mapped_paths[candidate.path_index]
    if bool(mapped_path.closed) != bool(reference_path.closed):
        return "path closure differs from reference master"
    reference_types = [node.type for node in reference_path.nodes]
    mapped_types = [node.type for node in mapped_path.nodes]
    if mapped_types != reference_types:
        return "node topology differs from reference master"
    return None


def _prepare_master_edit(
    master: Any,
    reference_paths: list[Any],
    mapped_paths: list[Any],
    mapped_depths: list[int],
    candidate: _Candidate,
    radius: float,
    max_segment_ratio: float,
) -> tuple[_MasterEdit | None, str | None]:
    reason = _topology_reason(reference_paths, mapped_paths, candidate)
    if reason is not None:
        return None, f"master {master.name!r}: {reason}"
    path = mapped_paths[candidate.path_index]
    if not _is_corner_type(
        path,
        candidate.node_index,
        nesting_depth=mapped_depths[candidate.path_index],
        corner_type=candidate.corner_type,
    ):
        corner_description = (
            "black-outer convex" if candidate.corner_type == "outer" else "white-counter convex"
        )
        return None, f"master {master.name!r}: mapped corner is not {corner_description}"

    nodes = list(path.nodes)
    previous = _xy(nodes[(candidate.node_index - 1) % len(nodes)])
    corner = _xy(nodes[candidate.node_index])
    following = _xy(nodes[(candidate.node_index + 1) % len(nodes)])
    toward_corner = _unit(_sub(corner, previous))
    away_from_corner = _unit(_sub(following, corner))
    incoming_length = _length(_sub(corner, previous))
    outgoing_length = _length(_sub(following, corner))
    if toward_corner is None or away_from_corner is None:
        return None, f"master {master.name!r}: zero-length adjacent segment"

    reverse_incoming = _scale(toward_corner, -1.0)
    cosine = max(-1.0, min(1.0, _dot(reverse_incoming, away_from_corner)))
    interior_angle = math.acos(cosine)
    tangent = math.tan(interior_angle / 2.0)
    if not math.isfinite(tangent) or tangent <= 1e-9:
        return None, f"master {master.name!r}: degenerate corner angle"
    requested_trim = radius / tangent
    trim_limit = min(incoming_length, outgoing_length) * max_segment_ratio
    trim_distance = min(requested_trim, trim_limit)
    if not math.isfinite(trim_distance) or trim_distance <= 1e-9:
        return None, f"master {master.name!r}: trim distance is not usable"

    before = _sub(corner, _scale(toward_corner, trim_distance))
    after = _add(corner, _scale(away_from_corner, trim_distance))
    effective_radius = trim_distance * tangent
    sweep = math.pi - interior_angle
    handle_length = 4.0 / 3.0 * effective_radius * math.tan(sweep / 4.0)
    control_1 = _add(before, _scale(toward_corner, handle_length))
    control_2 = _sub(after, _scale(away_from_corner, handle_length))
    coordinates = (before, control_1, control_2, after)
    if not all(math.isfinite(value) for point in coordinates for value in (point.x, point.y)):
        return None, f"master {master.name!r}: generated coordinates are not finite"
    return (
        _MasterEdit(
            master_id=master.id,
            master_name=master.name,
            path=path,
            node_index=candidate.node_index,
            before=before,
            control_1=control_1,
            control_2=control_2,
            after=after,
            radius=radius,
            trim_distance=trim_distance,
            requested_trim_distance=requested_trim,
        ),
        None,
    )


def _prepare_terminal_edit(
    master: Any,
    reference_paths: list[Any],
    mapped_paths: list[Any],
    mapped_depths: list[int],
    candidate: _TerminalCandidate,
    *,
    line: str,
    curve: str,
    offcurve: str,
    maximum_width: float,
) -> tuple[_TerminalEdit | None, str | None]:
    topology_candidate = _Candidate(
        candidate.path_index,
        candidate.end_node_index,
        "outer",
    )
    reason = _topology_reason(reference_paths, mapped_paths, topology_candidate)
    if reason is not None:
        return None, f"master {master.name!r}: {reason}"
    path = mapped_paths[candidate.path_index]
    geometry, reason = _terminal_geometry(
        path,
        candidate,
        nesting_depth=mapped_depths[candidate.path_index],
        line=line,
        curve=curve,
        offcurve=offcurve,
        maximum_width=maximum_width,
    )
    if reason is not None:
        return None, f"master {master.name!r}: {reason}"
    assert geometry is not None
    nodes = list(path.nodes)
    start_control_index = geometry["start_control_index"]
    end_control_index = geometry["end_control_index"]
    return (
        _TerminalEdit(
            master_id=master.id,
            master_name=master.name,
            path=path,
            start_node_index=candidate.start_node_index,
            end_node_index=candidate.end_node_index,
            start_node=nodes[candidate.start_node_index],
            end_node=nodes[candidate.end_node_index],
            start_control_node=(
                None if start_control_index is None else nodes[start_control_index]
            ),
            end_control_node=(None if end_control_index is None else nodes[end_control_index]),
            **geometry,
        ),
        None,
    )


def _apply_edit(edit: _MasterEdit, node_class: Any, line: str, curve: str, offcurve: str) -> None:
    nodes = list(edit.path.nodes)
    original = nodes[edit.node_index]
    replacement = [
        node_class((edit.before.x, edit.before.y), type=line, name=original.name),
        node_class((edit.control_1.x, edit.control_1.y), type=offcurve),
        node_class((edit.control_2.x, edit.control_2.y), type=offcurve),
        node_class((edit.after.x, edit.after.y), type=curve, smooth=True),
    ]
    edit.path.nodes = nodes[: edit.node_index] + replacement + nodes[edit.node_index + 1 :]


def _apply_terminal_edit(
    edit: _TerminalEdit,
    node_class: Any,
    curve: str,
    offcurve: str,
) -> None:
    nodes = list(edit.path.nodes)
    start_index = next(index for index, node in enumerate(nodes) if node is edit.start_node)
    end_index = next(index for index, node in enumerate(nodes) if node is edit.end_node)
    start = nodes[start_index]
    end = nodes[end_index]
    start.position = (edit.start.x, edit.start.y)
    if edit.start_control_node is not None and edit.start_control is not None:
        edit.start_control_node.position = (
            edit.start_control.x,
            edit.start_control.y,
        )
    if edit.end_control_node is not None and edit.end_control is not None:
        edit.end_control_node.position = (
            edit.end_control.x,
            edit.end_control.y,
        )
    replacement = [
        node_class((edit.control_1.x, edit.control_1.y), type=offcurve),
        node_class((edit.control_2.x, edit.control_2.y), type=offcurve),
        node_class((edit.apex.x, edit.apex.y), type=curve, smooth=True),
        node_class((edit.control_3.x, edit.control_3.y), type=offcurve),
        node_class((edit.control_4.x, edit.control_4.y), type=offcurve),
        node_class((edit.end.x, edit.end.y), type=curve, smooth=True, name=end.name),
    ]
    edit.path.nodes = nodes[:end_index] + replacement + nodes[end_index + 1 :]


def _edit_report(edit: _MasterEdit) -> dict[str, Any]:
    return {
        "master_id": edit.master_id,
        "master_name": edit.master_name,
        "radius": edit.radius,
        "requested_trim_distance": edit.requested_trim_distance,
        "trim_distance": edit.trim_distance,
        "clamped": edit.trim_distance < edit.requested_trim_distance - 1e-9,
        "added_nodes": 3,
    }


def _terminal_edit_report(edit: _TerminalEdit) -> dict[str, Any]:
    return {
        "master_id": edit.master_id,
        "master_name": edit.master_name,
        "shaft_width": edit.shaft_width,
        "radius": edit.shaft_width / 2.0,
        "trim_distance": edit.trim_distance,
        "added_nodes": 5,
    }


def round_glyphs_font(
    font: Any,
    glyph_tokens: Iterable[str] | None,
    radii_by_master: Mapping[str, float] | float,
    *,
    reference_master: str = "Regular",
    max_segment_ratio: float = 0.42,
    inner_radii_by_master: Mapping[str, float] | float | None = None,
    all_exporting_glyphs: bool = False,
    compact_report: bool = False,
    terminal_rounding: bool = True,
) -> dict[str, Any]:
    """Round compatible line corners and flat terminals across every source master.

    ``inner_radii_by_master`` opts white counter corners into rounding.
    ``terminal_rounding`` opts safe single-line caps into tangent cubic rounding.
    ``all_exporting_glyphs`` always uses the bounded compact report; callers may
    also select that mode with ``glyph_tokens=None`` and ``compact_report=True``.
    """

    _, node_class, line, curve, offcurve = _glyphs_api()
    if not math.isfinite(max_segment_ratio) or not 0 < max_segment_ratio < 0.5:
        raise SourceRoundingError("max_segment_ratio must be finite and between 0 and 0.5")
    masters = list(font.masters)
    if not masters:
        raise SourceRoundingError("Glyphs source has no masters")
    reference = _resolve_reference_master(font, reference_master)
    radii = _resolve_radii(font, radii_by_master)
    inner_radii = (
        None if inner_radii_by_master is None else _resolve_radii(font, inner_radii_by_master)
    )
    select_all_exporting = all_exporting_glyphs or (glyph_tokens is None and compact_report)
    glyph_names = _resolve_glyph_selection(
        font,
        glyph_tokens,
        all_exporting_glyphs=select_all_exporting,
    )
    compact_report = compact_report or select_all_exporting

    glyph_reports: list[dict[str, Any]] = []
    total_found = 0
    total_applied = 0
    total_skipped = 0
    total_glyphs_skipped = 0
    for glyph_name in glyph_names:
        glyph = font.glyphs[glyph_name]
        unsupported_bracket_layers = _bracket_layers(font, glyph)
        if unsupported_bracket_layers:
            if compact_report:
                glyph_reports.append(
                    {
                        "glyph_name": glyph_name,
                        "candidates_found": 0,
                        "candidates_applied": 0,
                        "candidates_skipped": 0,
                        "glyph_skipped": True,
                        "corner_types": {
                            "outer": {"found": 0, "applied": 0, "skipped": 0},
                            "inner": {"found": 0, "applied": 0, "skipped": 0},
                        },
                        "candidate_kinds": {
                            "corner": {"found": 0, "applied": 0, "skipped": 0},
                            "terminal": {"found": 0, "applied": 0, "skipped": 0},
                        },
                        "skip_reasons": {"unsupported_bracket_layers": 1},
                    }
                )
            else:
                glyph_reports.append(
                    {
                        "glyph_name": glyph_name,
                        "candidates_found": 0,
                        "applied": [],
                        "skipped": [
                            {
                                "candidate_id": None,
                                "path_index": None,
                                "node_index": None,
                                "corner_type": None,
                                "reason": "unsupported_bracket_layers",
                            }
                        ],
                        "unsupported_bracket_layers": unsupported_bracket_layers,
                    }
                )
            total_glyphs_skipped += 1
            continue
        reference_layer = glyph.layers[reference.id]
        if reference_layer is None:
            layer_skip_reason = f"reference master {reference.name!r} has no layer"
            if compact_report:
                glyph_reports.append(
                    {
                        "glyph_name": glyph_name,
                        "candidates_found": 0,
                        "candidates_applied": 0,
                        "candidates_skipped": 0,
                        "glyph_skipped": True,
                        "corner_types": {
                            "outer": {"found": 0, "applied": 0, "skipped": 0},
                            "inner": {"found": 0, "applied": 0, "skipped": 0},
                        },
                        "candidate_kinds": {
                            "corner": {"found": 0, "applied": 0, "skipped": 0},
                            "terminal": {"found": 0, "applied": 0, "skipped": 0},
                        },
                        "skip_reasons": {layer_skip_reason: 1},
                    }
                )
            else:
                glyph_reports.append(
                    {
                        "glyph_name": glyph_name,
                        "candidates_found": 0,
                        "applied": [],
                        "skipped": [
                            {
                                "candidate_id": None,
                                "path_index": None,
                                "node_index": None,
                                "corner_type": None,
                                "reason": layer_skip_reason,
                            }
                        ],
                        "unsupported_bracket_layers": [],
                    }
                )
            total_glyphs_skipped += 1
            continue

        maximum_terminal_width = float(getattr(font, "upm", 1000) or 1000) * 0.14
        reference_paths = list(reference_layer.paths)
        master_paths = {
            master.id: (
                list(glyph.layers[master.id].paths) if glyph.layers[master.id] is not None else []
            )
            for master in masters
        }
        master_depths = {master.id: _path_depths(master_paths[master.id]) for master in masters}
        terminal_candidates = (
            _reference_terminal_candidates(
                reference_layer,
                line=line,
                curve=curve,
                offcurve=offcurve,
                maximum_width=maximum_terminal_width,
            )
            if terminal_rounding
            else []
        )
        prepared_terminals: list[tuple[_TerminalCandidate, list[_TerminalEdit]]] = []
        skipped: list[dict[str, Any]] = []
        for terminal_candidate in terminal_candidates:
            terminal_edits: list[_TerminalEdit] = []
            terminal_reason: str | None = None
            for master in masters:
                terminal_edit, terminal_reason = _prepare_terminal_edit(
                    master,
                    reference_paths,
                    master_paths[master.id],
                    master_depths[master.id],
                    terminal_candidate,
                    line=line,
                    curve=curve,
                    offcurve=offcurve,
                    maximum_width=maximum_terminal_width,
                )
                if terminal_reason is not None:
                    break
                assert terminal_edit is not None
                terminal_edits.append(terminal_edit)
            if terminal_reason is None:
                prepared_terminals.append((terminal_candidate, terminal_edits))
            else:
                skipped.append(
                    {
                        "candidate_id": terminal_candidate.candidate_id,
                        "kind": "terminal",
                        "path_index": terminal_candidate.path_index,
                        "node_index": terminal_candidate.end_node_index,
                        "start_node_index": terminal_candidate.start_node_index,
                        "end_node_index": terminal_candidate.end_node_index,
                        "corner_type": None,
                        "reason": terminal_reason,
                    }
                )

        applied: list[dict[str, Any]] = []
        applied_by_kind: Counter[str] = Counter()
        for terminal_candidate, terminal_edits in sorted(
            prepared_terminals,
            key=lambda item: (
                item[0].path_index,
                item[0].end_node_index,
            ),
            reverse=True,
        ):
            for terminal_edit in terminal_edits:
                _apply_terminal_edit(
                    terminal_edit,
                    node_class,
                    curve,
                    offcurve,
                )
            applied_by_kind["terminal"] += 1
            if not compact_report:
                applied.append(
                    {
                        "candidate_id": terminal_candidate.candidate_id,
                        "kind": "terminal",
                        "path_index": terminal_candidate.path_index,
                        "node_index": terminal_candidate.end_node_index,
                        "start_node_index": terminal_candidate.start_node_index,
                        "end_node_index": terminal_candidate.end_node_index,
                        "corner_type": None,
                        "masters": [_terminal_edit_report(edit) for edit in terminal_edits],
                    }
                )

        # Terminal edits change node topology. Rebuild these once per master, then
        # reuse the nesting depths for every corner candidate in this glyph.
        reference_paths = list(reference_layer.paths)
        master_paths = {master.id: list(glyph.layers[master.id].paths) for master in masters}
        master_depths = {master.id: _path_depths(master_paths[master.id]) for master in masters}
        corner_candidates = _reference_candidates(
            reference_layer,
            line,
            include_inner=inner_radii is not None,
        )
        prepared: list[tuple[_Candidate, list[_MasterEdit]]] = []
        for candidate in corner_candidates:
            edits: list[_MasterEdit] = []
            reason: str | None = None
            for master in masters:
                if candidate.corner_type == "outer":
                    radius = radii[master.id]
                else:
                    assert inner_radii is not None
                    radius = inner_radii[master.id]
                edit, reason = _prepare_master_edit(
                    master,
                    reference_paths,
                    master_paths[master.id],
                    master_depths[master.id],
                    candidate,
                    radius,
                    max_segment_ratio,
                )
                if reason is not None:
                    break
                assert edit is not None
                edits.append(edit)
            if reason is None:
                prepared.append((candidate, edits))
            else:
                skipped.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "kind": "corner",
                        "path_index": candidate.path_index,
                        "node_index": candidate.node_index,
                        "corner_type": candidate.corner_type,
                        "reason": reason,
                    }
                )

        applied_by_type: Counter[str] = Counter()
        for candidate, edits in sorted(
            prepared,
            key=lambda item: (item[0].path_index, item[0].node_index),
            reverse=True,
        ):
            for edit in edits:
                _apply_edit(edit, node_class, line, curve, offcurve)
            applied_by_kind["corner"] += 1
            applied_by_type[candidate.corner_type] += 1
            if not compact_report:
                applied.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "kind": "corner",
                        "path_index": candidate.path_index,
                        "node_index": candidate.node_index,
                        "corner_type": candidate.corner_type,
                        "masters": [_edit_report(edit) for edit in edits],
                    }
                )
        applied.sort(key=lambda item: (item["path_index"], item["node_index"]))
        skipped.sort(key=lambda item: (item["path_index"], item["node_index"]))
        found_count = len(terminal_candidates) + len(corner_candidates)
        applied_count = sum(applied_by_kind.values())
        total_found += found_count
        total_applied += applied_count
        total_skipped += len(skipped)
        if compact_report:
            found_by_type = Counter(candidate.corner_type for candidate in corner_candidates)
            skipped_by_type = Counter(item["corner_type"] for item in skipped)
            found_by_kind = {
                "corner": len(corner_candidates),
                "terminal": len(terminal_candidates),
            }
            skipped_by_kind = Counter(item["kind"] for item in skipped)
            glyph_reports.append(
                {
                    "glyph_name": glyph_name,
                    "candidates_found": found_count,
                    "candidates_applied": applied_count,
                    "candidates_skipped": len(skipped),
                    "glyph_skipped": False,
                    "corner_types": {
                        corner_type: {
                            "found": found_by_type[corner_type],
                            "applied": applied_by_type[corner_type],
                            "skipped": skipped_by_type[corner_type],
                        }
                        for corner_type in ("outer", "inner")
                    },
                    "candidate_kinds": {
                        kind: {
                            "found": found_by_kind[kind],
                            "applied": applied_by_kind[kind],
                            "skipped": skipped_by_kind[kind],
                        }
                        for kind in ("corner", "terminal")
                    },
                    "skip_reasons": dict(
                        sorted(Counter(item["reason"] for item in skipped).items())
                    ),
                }
            )
        else:
            glyph_reports.append(
                {
                    "glyph_name": glyph_name,
                    "candidates_found": found_count,
                    "applied": applied,
                    "skipped": skipped,
                    "unsupported_bracket_layers": [],
                }
            )

    master_reports = [
        {"id": master.id, "name": master.name, "radius": radii[master.id]} for master in masters
    ]
    if inner_radii is not None:
        for master, master_report in zip(masters, master_reports, strict=True):
            master_report["inner_radius"] = inner_radii[master.id]
    report = {
        "reference_master": {"id": reference.id, "name": reference.name},
        "masters": master_reports,
        "glyphs": glyph_reports,
        "summary": {
            "glyphs_requested": len(glyph_names),
            "glyphs_skipped": total_glyphs_skipped,
            "candidates_found": total_found,
            "candidates_applied": total_applied,
            "candidates_skipped": total_skipped,
        },
    }
    if compact_report:
        report["report_mode"] = "compact"
    if select_all_exporting:
        report["glyph_selection"] = "all_exporting"
    return report


def round_glyphs_source(
    input_path: str | Path,
    output_path: str | Path,
    glyph_tokens: Iterable[str] | None,
    radii_by_master: Mapping[str, float] | float,
    *,
    reference_master: str = "Regular",
    max_segment_ratio: float = 0.42,
    inner_radii_by_master: Mapping[str, float] | float | None = None,
    all_exporting_glyphs: bool = False,
    compact_report: bool = False,
    terminal_rounding: bool = True,
    family_name: str | None = None,
    normalize_ibm_plex_sans_tc: bool = False,
) -> dict[str, Any]:
    """Write a rounded derived ``.glyphs`` source without modifying its input."""

    source = Path(input_path)
    destination = Path(output_path)
    if source.resolve(strict=False) == destination.resolve(strict=False):
        raise SourceRoundingError("output path must differ from input path")
    if not source.is_file():
        raise SourceRoundingError(f"Glyphs source does not exist: {source}")
    if destination.suffix.lower() != ".glyphs":
        raise SourceRoundingError("output path must use the .glyphs suffix")

    font_class, _, _, _, _ = _glyphs_api()
    try:
        font = font_class(source)
    except (OSError, ValueError) as exc:
        raise SourceRoundingError(f"could not read Glyphs source {source}: {exc}") from exc
    if family_name is not None and not family_name.strip():
        raise SourceRoundingError("family_name must not be empty")
    normalization: dict[str, Any] | None = None
    if normalize_ibm_plex_sans_tc:
        from kumamaru.source_normalize import normalize_ibm_plex_tc_source

        normalization = normalize_ibm_plex_tc_source(
            font,
            family_name=family_name or "Kumamaru Sans",
        )
    elif family_name is not None:
        font.familyName = family_name

    report = round_glyphs_font(
        font,
        glyph_tokens,
        radii_by_master,
        reference_master=reference_master,
        max_segment_ratio=max_segment_ratio,
        inner_radii_by_master=inner_radii_by_master,
        all_exporting_glyphs=all_exporting_glyphs,
        compact_report=compact_report,
        terminal_rounding=terminal_rounding,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(file_descriptor)
    try:
        font.save(temporary_name)
        os.replace(temporary_name, destination)
    except Exception:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise
    return {
        "input": str(source),
        "output": str(destination),
        "family_name": font.familyName,
        "normalization": normalization,
        **report,
    }
