from __future__ import annotations

import io
import math
import random
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from fontTools.pens.areaPen import AreaPen  # type: ignore[import-untyped]
from fontTools.pens.boundsPen import BoundsPen  # type: ignore[import-untyped]
from fontTools.pens.recordingPen import (  # type: ignore[import-untyped]
    DecomposingRecordingPen,
)
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from .font_io import (
    HINTING_TABLES,
    PROHIBITED_TABLES,
    REQUIRED_TRUETYPE_TABLES,
    compiled_table_bytes,
    load_font,
    normalized_glyph_bytes,
)
from .geometry.contour import glyph_to_outline
from .geometry.safety import symmetric_boundary_deviation
from .model import GlyphOutline

ALLOWED_CHANGED_TABLES = frozenset(
    {
        "DSIG",
        "OS/2",
        "glyf",
        "head",
        "loca",
        "maxp",
        "name",
        "post",
        *HINTING_TABLES,
    }
)
PRESERVED_LAYOUT_TABLES = ("BASE", "GDEF", "GPOS", "GSUB", "vhea")
DEFAULT_SHAPING_CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "horizontal_traditional_chinese",
        "text": "熊丸體的圓角與收筆測試。個國水心",
        "direction": "ltr",
        "script": "Hant",
        "language": "zh-tw",
        "features": {},
    },
    {
        "name": "latin_and_digits",
        "text": "Kumamaru Sans ABC abc 0123456789",
        "direction": "ltr",
        "script": "Latn",
        "language": "en",
        "features": {},
    },
    {
        "name": "punctuation",
        "text": "，。！？「」（）—…",
        "direction": "ltr",
        "script": "Hant",
        "language": "zh-tw",
        "features": {},
    },
    {
        "name": "vertical",
        "text": "個國固圓圖問間開關體熊丸",
        "direction": "ttb",
        "script": "Hant",
        "language": "zh-tw",
        "features": {"vert": True, "vrt2": True},
    },
)


def _check(
    checks: list[dict[str, Any]],
    category: str,
    name: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append(
        {
            "category": category,
            "name": name,
            "passed": bool(passed),
            "detail": detail,
        }
    )


def _recording_is_closed(recording: list[tuple[str, tuple[Any, ...]]]) -> bool:
    open_contours = 0
    for operation, _arguments in recording:
        if operation == "moveTo":
            open_contours += 1
        elif operation == "closePath":
            open_contours -= 1
        elif operation == "endPath":
            return False
        if open_contours < 0:
            return False
    return open_contours == 0


def _glyph_geometry(font: TTFont, glyph_name: str) -> dict[str, Any]:
    glyph_set = font.getGlyphSet()
    recording_pen = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(recording_pen)
    coordinates: list[tuple[float, float]] = []
    for _operation, arguments in recording_pen.value:
        for argument in arguments:
            if (
                isinstance(argument, tuple)
                and len(argument) == 2
                and all(isinstance(value, (float, int)) for value in argument)
            ):
                coordinates.append((float(argument[0]), float(argument[1])))

    bounds_pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(bounds_pen)
    area_pen = AreaPen(glyph_set)
    glyph_set[glyph_name].draw(area_pen)
    finite = all(math.isfinite(value) for point in coordinates for value in point)
    return {
        "contour_count": sum(
            operation == "moveTo" for operation, _arguments in recording_pen.value
        ),
        "point_count": len(coordinates),
        "bounds": list(bounds_pen.bounds) if bounds_pen.bounds is not None else None,
        "area": float(area_pen.value),
        "finite": finite,
        "closed": _recording_is_closed(recording_pen.value),
    }


def _glyph_outline(font: TTFont, glyph_name: str) -> GlyphOutline:
    glyph_set = font.getGlyphSet()
    return glyph_to_outline(
        glyph_set[glyph_name],
        glyph_name=glyph_name,
        width=font["hmtx"][glyph_name][0],
        glyph_set=glyph_set,
    )


def _shape(path: Path, case: Mapping[str, Any]) -> list[dict[str, int]]:
    import uharfbuzz as hb  # type: ignore[import-untyped]

    blob = hb.Blob.from_file_path(str(path))
    face = hb.Face(blob)
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)
    buffer = hb.Buffer()
    buffer.add_str(str(case["text"]))
    buffer.direction = str(case["direction"])
    buffer.script = str(case["script"])
    buffer.language = str(case["language"])
    hb.shape(font, buffer, dict(case.get("features", {})))
    positions = buffer.glyph_positions or []
    return [
        {
            "glyph_id": info.codepoint,
            "cluster": info.cluster,
            "x_advance": position.x_advance,
            "y_advance": position.y_advance,
            "x_offset": position.x_offset,
            "y_offset": position.y_offset,
        }
        for info, position in zip(buffer.glyph_infos, positions, strict=True)
    ]


def _validate_basic(font: TTFont, checks: list[dict[str, Any]]) -> None:
    tables = set(font.keys())
    missing = sorted(REQUIRED_TRUETYPE_TABLES - tables)
    _check(
        checks,
        "basic",
        "required_tables",
        not missing,
        "all required tables are present" if not missing else f"missing: {', '.join(missing)}",
    )
    prohibited = sorted(tables & PROHIBITED_TABLES)
    _check(
        checks,
        "basic",
        "static_glyf_font",
        not prohibited,
        "static glyf outlines" if not prohibited else f"prohibited: {', '.join(prohibited)}",
    )
    remaining_hint_tables = sorted(tables & HINTING_TABLES)
    instructed_glyphs: list[str] = []
    if "glyf" in font:
        for glyph_name in font.getGlyphOrder():
            glyph = font["glyf"][glyph_name]
            program = getattr(glyph, "program", None)
            if program is not None and program.getBytecode():
                instructed_glyphs.append(glyph_name)
    unhinted = not remaining_hint_tables and not instructed_glyphs
    _check(
        checks,
        "basic",
        "unhinted",
        unhinted,
        "no global or glyph TrueType instructions remain"
        if unhinted
        else (f"tables={remaining_hint_tables}, instructed_glyphs={instructed_glyphs[:20]}"),
    )

    stream = io.BytesIO()
    try:
        font.save(stream, reorderTables=True)
        stream.seek(0)
        with TTFont(stream, lazy=False, recalcTimestamp=False):
            pass
    except Exception as exc:
        _check(checks, "basic", "roundtrip", False, f"{type(exc).__name__}: {exc}")
    else:
        _check(checks, "basic", "roundtrip", True, "full in-memory save and reload succeeded")

    invalid_glyphs: list[str] = []
    for glyph_name in font.getGlyphOrder():
        try:
            geometry = _glyph_geometry(font, glyph_name)
            bounds = geometry["bounds"]
            bounds_valid = bounds is None or (
                len(bounds) == 4
                and all(math.isfinite(value) for value in bounds)
                and bounds[0] <= bounds[2]
                and bounds[1] <= bounds[3]
            )
            if not geometry["finite"] or not geometry["closed"] or not bounds_valid:
                invalid_glyphs.append(glyph_name)
        except Exception:
            invalid_glyphs.append(glyph_name)
    _check(
        checks,
        "basic",
        "drawable_glyphs",
        not invalid_glyphs,
        "all glyphs draw with finite, closed outlines"
        if not invalid_glyphs
        else f"invalid glyphs: {', '.join(invalid_glyphs[:20])}",
    )


def _validate_preservation(
    before: TTFont,
    after: TTFont,
    checks: list[dict[str, Any]],
) -> None:
    before_order = before.getGlyphOrder()
    after_order = after.getGlyphOrder()
    _check(
        checks,
        "preservation",
        "glyph_count",
        len(before_order) == len(after_order),
        f"before={len(before_order)}, after={len(after_order)}",
    )
    _check(
        checks,
        "preservation",
        "glyph_order",
        before_order == after_order,
        "glyph order is identical" if before_order == after_order else "glyph order changed",
    )
    before_cmap = before.getBestCmap() or {}
    after_cmap = after.getBestCmap() or {}
    _check(
        checks,
        "preservation",
        "best_cmap",
        before_cmap == after_cmap,
        f"before={len(before_cmap)} mappings, after={len(after_cmap)} mappings",
    )
    for tag in ("hmtx", "vmtx"):
        present_before = tag in before
        present_after = tag in after
        same = present_before == present_after and (
            not present_before or before[tag].metrics == after[tag].metrics
        )
        _check(
            checks,
            "preservation",
            tag,
            same,
            "metrics are identical" if same else f"{tag} presence or metrics changed",
        )

    all_tags = (set(before.keys()) | set(after.keys())) - {"GlyphOrder"}
    unexpected_presence_changes: list[str] = []
    changed_disallowed: list[str] = []
    changed_tables: list[str] = []
    for tag in sorted(all_tags):
        if (tag in before) != (tag in after):
            if tag not in ALLOWED_CHANGED_TABLES:
                unexpected_presence_changes.append(tag)
            continue
        if compiled_table_bytes(before, tag) != compiled_table_bytes(after, tag):
            changed_tables.append(tag)
            if tag not in ALLOWED_CHANGED_TABLES:
                changed_disallowed.append(tag)
    _check(
        checks,
        "preservation",
        "table_presence",
        not unexpected_presence_changes,
        "only allowed tables were added/removed"
        if not unexpected_presence_changes
        else f"unexpected presence changes: {', '.join(unexpected_presence_changes)}",
    )
    _check(
        checks,
        "preservation",
        "compiled_table_bytes",
        not changed_disallowed,
        f"changed tables: {', '.join(changed_tables) or '(none)'}"
        if not changed_disallowed
        else f"disallowed changes: {', '.join(changed_disallowed)}",
    )

    for tag in PRESERVED_LAYOUT_TABLES:
        same = (tag in before) == (tag in after) and (
            tag not in before
            or compiled_table_bytes(before, tag) == compiled_table_bytes(after, tag)
        )
        _check(
            checks,
            "preservation",
            f"{tag}_bytes",
            same,
            "presence and bytes are identical" if same else "presence or bytes changed",
        )


def _validate_modified_geometry(
    before: TTFont,
    after: TTFont,
    modified_glyphs: Iterable[str],
    checks: list[dict[str, Any]],
    *,
    max_bbox_change_em: float,
    max_point_growth_ratio: float,
    boundary_subdivisions: int,
    boundary_max_samples: int | None,
) -> dict[str, Any]:
    upm = before["head"].unitsPerEm
    maximum_delta = max_bbox_change_em * upm
    results: dict[str, Any] = {}
    valid_names = set(before.getGlyphOrder()) & set(after.getGlyphOrder())
    for glyph_name in dict.fromkeys(modified_glyphs):
        if glyph_name not in valid_names:
            _check(
                checks,
                "geometry",
                f"{glyph_name}:exists",
                False,
                "modified glyph does not exist in both fonts",
            )
            continue
        before_geometry = _glyph_geometry(before, glyph_name)
        after_geometry = _glyph_geometry(after, glyph_name)
        before_bounds = before_geometry["bounds"]
        after_bounds = after_geometry["bounds"]
        if before_bounds is None or after_bounds is None:
            bbox_passed = before_bounds == after_bounds
            deltas: list[float] | None = None
        else:
            deltas = [
                abs(float(after_value) - float(before_value))
                for before_value, after_value in zip(before_bounds, after_bounds, strict=True)
            ]
            bbox_passed = all(delta <= maximum_delta for delta in deltas)
        _check(
            checks,
            "geometry",
            f"{glyph_name}:bbox",
            bbox_passed,
            f"deltas={deltas}, limit={maximum_delta:g}",
        )

        before_points = int(before_geometry["point_count"])
        after_points = int(after_geometry["point_count"])
        growth_limit = max(before_points, 1) * max_point_growth_ratio
        point_passed = after_points <= growth_limit
        _check(
            checks,
            "geometry",
            f"{glyph_name}:point_growth",
            point_passed,
            f"before={before_points}, after={after_points}, limit={growth_limit:g}",
        )

        before_contours = int(before_geometry["contour_count"])
        after_contours = int(after_geometry["contour_count"])
        _check(
            checks,
            "geometry",
            f"{glyph_name}:contour_count",
            before_contours == after_contours,
            f"before={before_contours}, after={after_contours}",
        )

        boundary_deviation = symmetric_boundary_deviation(
            _glyph_outline(before, glyph_name),
            _glyph_outline(after, glyph_name),
            subdivisions=boundary_subdivisions,
            max_samples=boundary_max_samples,
        )
        boundary_passed = math.isfinite(boundary_deviation) and boundary_deviation <= maximum_delta
        _check(
            checks,
            "geometry",
            f"{glyph_name}:boundary_deviation",
            boundary_passed,
            f"deviation={boundary_deviation:g}, limit={maximum_delta:g}",
        )

        before_area = abs(float(before_geometry["area"]))
        after_area = abs(float(after_geometry["area"]))
        if before_area <= 1e-6:
            area_passed = after_area <= 1e-6
            area_ratio = None
        else:
            area_ratio = after_area / before_area
            area_passed = 0.1 <= area_ratio <= 2.0
        _check(
            checks,
            "geometry",
            f"{glyph_name}:area",
            area_passed,
            f"before={before_area:g}, after={after_area:g}, ratio={area_ratio}",
        )
        results[glyph_name] = {
            "before": before_geometry,
            "after": after_geometry,
            "bbox_deltas": deltas,
            "boundary_deviation": boundary_deviation,
            "area_ratio": area_ratio,
        }
    return results


def _validate_unmodified_glyphs(
    before: TTFont,
    after: TTFont,
    modified_glyphs: set[str],
    checks: list[dict[str, Any]],
    *,
    sample_size: int,
) -> dict[str, Any]:
    candidates = [
        name
        for name in before.getGlyphOrder()
        if name not in modified_glyphs and name in after["glyf"]
    ]
    randomizer = random.Random(0)
    sampled = (
        candidates if len(candidates) <= sample_size else randomizer.sample(candidates, sample_size)
    )
    changed = [
        name
        for name in sampled
        if normalized_glyph_bytes(before, name) != normalized_glyph_bytes(after, name)
    ]
    _check(
        checks,
        "preservation",
        "unmodified_glyph_outlines",
        not changed,
        f"sampled={len(sampled)}, changed={', '.join(changed) or '(none)'}",
    )
    return {"sample_size": len(sampled), "sampled_glyphs": sampled, "changed_glyphs": changed}


def _shaping_equivalent(
    before: list[dict[str, int]],
    after: list[dict[str, int]],
    *,
    offset_tolerance: float,
) -> bool:
    """Require identical shaping while allowing bounded outline-origin compensation."""

    if len(before) != len(after):
        return False
    exact_fields = ("glyph_id", "cluster", "x_advance", "y_advance")
    for before_item, after_item in zip(before, after, strict=True):
        if any(before_item[field] != after_item[field] for field in exact_fields):
            return False
        if abs(before_item["x_offset"] - after_item["x_offset"]) > offset_tolerance:
            return False
        if abs(before_item["y_offset"] - after_item["y_offset"]) > offset_tolerance:
            return False
    return True


def validate_fonts(
    before_path: str | Path,
    after_path: str | Path,
    *,
    modified_glyphs: Iterable[str] = (),
    max_bbox_change_em: float = 0.08,
    max_point_growth_ratio: float = 3.0,
    boundary_subdivisions: int = 8,
    boundary_max_samples: int | None = None,
    sample_size: int = 100,
    shaping_cases: Iterable[Mapping[str, Any]] = DEFAULT_SHAPING_CASES,
) -> dict[str, Any]:
    """Validate structural, layout, shaping, and targeted-outline invariants."""

    before_file = Path(before_path)
    after_file = Path(after_path)
    checks: list[dict[str, Any]] = []
    requested = tuple(dict.fromkeys(modified_glyphs))
    with load_font(before_file, lazy=False) as before, load_font(after_file, lazy=False) as after:
        before_cmap = before.getBestCmap() or {}
        glyph_order = set(before.getGlyphOrder())
        modified_names: list[str] = []
        unresolved: list[str] = []
        for selector in requested:
            glyph_name: str | None
            if selector in glyph_order:
                glyph_name = selector
            elif len(selector) == 1:
                glyph_name = before_cmap.get(ord(selector))
            elif selector.startswith(("U+", "u+")):
                try:
                    glyph_name = before_cmap.get(int(selector[2:], 16))
                except ValueError:
                    glyph_name = None
            else:
                glyph_name = None
            if glyph_name is None:
                unresolved.append(selector)
            elif glyph_name not in modified_names:
                modified_names.append(glyph_name)
        _check(
            checks,
            "geometry",
            "modified_glyph_selectors",
            not unresolved,
            "all modified glyph selectors resolved"
            if not unresolved
            else f"unresolved: {', '.join(unresolved)}",
        )
        modified = tuple(modified_names)
        _validate_basic(after, checks)
        _validate_preservation(before, after, checks)
        geometry = _validate_modified_geometry(
            before,
            after,
            modified,
            checks,
            max_bbox_change_em=max_bbox_change_em,
            max_point_growth_ratio=max_point_growth_ratio,
            boundary_subdivisions=boundary_subdivisions,
            boundary_max_samples=boundary_max_samples,
        )
        unmodified = _validate_unmodified_glyphs(
            before,
            after,
            set(modified),
            checks,
            sample_size=sample_size,
        )

    shaping: dict[str, Any] = {}
    try:
        for case in shaping_cases:
            name = str(case["name"])
            before_shape = _shape(before_file, case)
            after_shape = _shape(after_file, case)
            same = _shaping_equivalent(
                before_shape,
                after_shape,
                offset_tolerance=max_bbox_change_em * before["head"].unitsPerEm,
            )
            _check(
                checks,
                "shaping",
                name,
                same,
                (
                    "glyph IDs, clusters, and advances are identical; "
                    "offsets stay within geometry limit"
                )
                if same
                else "shaping output changed",
            )
            shaping[name] = {
                "passed": same,
                "before": before_shape,
                "after": after_shape,
            }
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        _check(
            checks,
            "shaping",
            "harfbuzz_available",
            False,
            f"{type(exc).__name__}: {exc}",
        )

    failures = [check for check in checks if not check["passed"]]
    return {
        "passed": not failures,
        "before": str(before_file),
        "after": str(after_file),
        "modified_glyphs": list(modified),
        "requested_glyph_selectors": list(requested),
        "checks": checks,
        "failure_count": len(failures),
        "geometry": geometry,
        "boundary_sampling": {
            "subdivisions": boundary_subdivisions,
            "max_samples": boundary_max_samples,
        },
        "unmodified_glyph_sample": unmodified,
        "shaping": shaping,
    }
