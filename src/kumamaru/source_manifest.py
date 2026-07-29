from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

IBM_PLEX_SANS_TC_APP_VERSION = "3259"
IBM_PLEX_SANS_TC_MASTER_COUNT = 3
IBM_PLEX_SANS_TC_GLYPH_COUNT = 19_217

_GLYPHS2_BRACKET_RE = re.compile(r".*[\[\]]\s*\d+\s*\].*")


class SourceManifestError(ValueError):
    """Raised when a Glyphs source cannot be inspected."""


def _load_glyphs_font(path: Path) -> Any:
    try:
        from glyphsLib import GSFont  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SourceManifestError(
            "glyphsLib is required to inspect .glyphs sources; install the "
            "project with its Glyphs source inspection dependency"
        ) from exc

    try:
        return GSFont(path)
    except Exception as exc:
        raise SourceManifestError(f"could not read Glyphs source {path}: {exc}") from exc


def _string(value: object, default: str = "") -> str:
    return default if value is None else str(value)


def _list(value: object) -> list[Any]:
    if value is None:
        return []
    return list(cast(Iterable[Any], value))


def _unicode_values(glyph: object) -> list[str]:
    raw_values = getattr(glyph, "unicodes", None)
    if raw_values is None:
        value = getattr(glyph, "unicode", None)
        raw_values = [] if value is None else [value]
    values: set[str] = set()
    for raw_value in raw_values:
        if isinstance(raw_value, int):
            values.add(f"{raw_value:04X}")
            continue
        value = str(raw_value).removeprefix("U+").removeprefix("u+").upper()
        try:
            values.add(f"{int(value, 16):04X}")
        except ValueError:
            continue
    return sorted(values, key=lambda value: int(value, 16))


def resolve_glyph_tokens(font: object, tokens: Iterable[str]) -> dict[str, str | None]:
    """Resolve characters, U+XXXX values, and glyph names against a GSFont."""

    glyphs = _list(getattr(font, "glyphs", ()))
    names = {_string(getattr(glyph, "name", None)) for glyph in glyphs}
    unicode_map: dict[int, str] = {}
    for glyph in glyphs:
        glyph_name = _string(getattr(glyph, "name", None))
        for value in _unicode_values(glyph):
            unicode_map.setdefault(int(value, 16), glyph_name)

    resolved: dict[str, str | None] = {}
    for raw_token in tokens:
        token = str(raw_token)
        codepoint: int | None = None
        if len(token) == 1:
            codepoint = ord(token)
        elif token.startswith(("U+", "u+")):
            try:
                codepoint = int(token[2:], 16)
            except ValueError:
                codepoint = None
        resolved[token] = unicode_map.get(codepoint) if codepoint is not None else None
        if codepoint is not None and resolved[token] is None:
            canonical_name = f"uni{codepoint:04X}" if codepoint <= 0xFFFF else f"u{codepoint:X}"
            if canonical_name in names:
                resolved[token] = canonical_name
        if codepoint is None and token in names:
            resolved[token] = token
    return resolved


def _is_path(shape: object) -> bool:
    return hasattr(shape, "nodes") and hasattr(shape, "closed")


def _is_component(shape: object) -> bool:
    return hasattr(shape, "name") and not _is_path(shape)


def _shape_signature(shape: object) -> dict[str, Any]:
    if _is_path(shape):
        nodes = cast(Iterable[Any], cast(Any, shape).nodes)
        return {
            "kind": "path",
            "closed": bool(getattr(shape, "closed", True)),
            "nodes": [_string(getattr(node, "type", None)) for node in nodes],
        }
    if _is_component(shape):
        return {
            "kind": "component",
            "name": _string(getattr(shape, "name", None)),
        }
    return {"kind": type(shape).__name__}


def _layer_signature(layer: object) -> list[dict[str, Any]]:
    shapes = getattr(layer, "shapes", None)
    if shapes is None:
        shapes = [*_list(getattr(layer, "paths", ())), *_list(getattr(layer, "components", ()))]
    return [_shape_signature(shape) for shape in shapes]


def _master_layer(glyph: object, master_id: str) -> object | None:
    layers = cast(Any, getattr(glyph, "layers", ()))
    try:
        direct = layers[master_id]
    except (KeyError, IndexError, TypeError):
        direct = None
    if direct is not None and _string(getattr(direct, "layerId", None)) == master_id:
        return cast(object, direct)
    for layer in layers:
        layer_id = _string(getattr(layer, "layerId", None))
        associated_id = _string(getattr(layer, "associatedMasterId", None))
        if layer_id == master_id and associated_id in {"", master_id}:
            return cast(object, layer)
    return None


def _glyph_compatibility(glyph: object, masters: Sequence[object]) -> dict[str, Any]:
    signatures: dict[str, list[dict[str, Any]] | None] = {}
    for master in masters:
        master_id = _string(getattr(master, "id", None))
        layer = _master_layer(glyph, master_id)
        signatures[master_id] = None if layer is None else _layer_signature(layer)
    comparable = list(signatures.values())
    compatible = bool(comparable) and all(value is not None for value in comparable)
    if compatible:
        compatible = all(value == comparable[0] for value in comparable[1:])
    return {"compatible": compatible, "master_signatures": signatures}


def _is_bracket_layer(layer: object, format_version: int) -> bool:
    attributes = getattr(layer, "attributes", None)
    if format_version > 2 and isinstance(attributes, Mapping):
        return "axisRules" in attributes
    return bool(_GLYPHS2_BRACKET_RE.fullmatch(_string(getattr(layer, "name", None))))


def _bracket_statistics(glyphs: Sequence[object], format_version: int) -> dict[str, Any]:
    by_glyph: dict[str, int] = {}
    by_master: dict[str, int] = {}
    total = 0
    for glyph in glyphs:
        glyph_count = 0
        for layer in getattr(glyph, "layers", ()):
            if not _is_bracket_layer(layer, format_version):
                continue
            total += 1
            glyph_count += 1
            master_id = _string(getattr(layer, "associatedMasterId", None), "unassociated")
            by_master[master_id] = by_master.get(master_id, 0) + 1
        if glyph_count:
            by_glyph[_string(getattr(glyph, "name", None))] = glyph_count
    return {
        "total": total,
        "glyph_count": len(by_glyph),
        "by_glyph": dict(sorted(by_glyph.items())),
        "by_master": dict(sorted(by_master.items())),
    }


def _axis_manifest(axis: object, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "id": _string(getattr(axis, "axisId", None)) or None,
        "name": _string(getattr(axis, "name", None)),
        "tag": _string(getattr(axis, "axisTag", None)),
        "hidden": bool(getattr(axis, "hidden", False)),
    }


def _master_manifest(master: object) -> dict[str, Any]:
    return {
        "id": _string(getattr(master, "id", None)),
        "name": _string(getattr(master, "name", None)),
        "axes": list(getattr(master, "axes", ()) or ()),
    }


def _instance_manifest(instance: object) -> dict[str, Any]:
    return {
        "name": _string(getattr(instance, "name", None)),
        "active": bool(getattr(instance, "active", getattr(instance, "exports", True))),
        "type": _string(getattr(instance, "type", None)),
        "axes": list(getattr(instance, "axes", ()) or ()),
    }


def _feature_manifest(feature: object) -> dict[str, Any]:
    return {
        "tag": _string(getattr(feature, "name", None)),
        "automatic": bool(getattr(feature, "automatic", False)),
        "disabled": bool(getattr(feature, "disabled", False)),
    }


def _source_gate(
    *,
    app_version: str,
    master_count: int,
    glyph_count: int,
    expected_app_version: str | int | None,
    expected_master_count: int | None,
    expected_glyph_count: int | None,
) -> dict[str, Any]:
    expectations = (
        (
            "app_version",
            app_version,
            None if expected_app_version is None else str(expected_app_version),
        ),
        ("master_count", master_count, expected_master_count),
        ("glyph_count", glyph_count, expected_glyph_count),
    )
    checks = [
        {
            "field": field,
            "actual": actual,
            "expected": expected,
            "passed": expected is None or actual == expected,
        }
        for field, actual, expected in expectations
    ]
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def build_source_manifest(
    font: object,
    *,
    source: str | Path,
    selected_glyphs: Iterable[str] = (),
    expected_app_version: str | int | None = None,
    expected_master_count: int | None = None,
    expected_glyph_count: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic, JSON-ready manifest from a loaded GSFont."""

    glyphs = _list(getattr(font, "glyphs", ()))
    masters = _list(getattr(font, "masters", ()))
    instances = _list(getattr(font, "instances", ()))
    axes = _list(getattr(font, "axes", ()))
    features = _list(getattr(font, "features", ()))
    app_version = _string(getattr(font, "appVersion", None))
    format_version = int(getattr(font, "format_version", 2))

    tokens = tuple(str(token) for token in selected_glyphs)
    resolved = resolve_glyph_tokens(font, tokens)
    selected_names = {name for name in resolved.values() if name is not None}
    inspected_glyphs = (
        [glyph for glyph in glyphs if _string(getattr(glyph, "name", None)) in selected_names]
        if tokens
        else glyphs
    )
    inspected_glyphs.sort(key=lambda glyph: _string(getattr(glyph, "name", None)))

    mismatches: dict[str, dict[str, Any]] = {}
    mismatch_glyphs: list[str] = []
    for glyph in inspected_glyphs:
        glyph_name = _string(getattr(glyph, "name", None))
        result = _glyph_compatibility(glyph, masters)
        if not result["compatible"]:
            mismatch_glyphs.append(glyph_name)
            mismatches[glyph_name] = result

    compatibility = {
        "compatible": not mismatch_glyphs,
        "checked_glyph_count": len(inspected_glyphs),
        "mismatch_count": len(mismatch_glyphs),
        "mismatch_glyphs": mismatch_glyphs,
        "mismatches": mismatches,
    }
    bracket_layers = _bracket_statistics(inspected_glyphs, format_version)
    selection = {
        "limited": bool(tokens),
        "requested": [{"token": token, "glyph_name": resolved[token]} for token in tokens],
        "missing": [token for token in tokens if resolved[token] is None],
        "resolved_glyph_count": len(inspected_glyphs),
    }
    gate = _source_gate(
        app_version=app_version,
        master_count=len(masters),
        glyph_count=len(glyphs),
        expected_app_version=expected_app_version,
        expected_master_count=expected_master_count,
        expected_glyph_count=expected_glyph_count,
    )
    return {
        "input": str(Path(source)),
        "app_version": app_version,
        "format_version": format_version,
        "family": _string(getattr(font, "familyName", None)),
        "glyph_count": len(glyphs),
        "master_count": len(masters),
        "instance_count": len(instances),
        "axis_count": len(axes),
        "feature_count": len(features),
        "masters": [_master_manifest(master) for master in masters],
        "instances": [_instance_manifest(instance) for instance in instances],
        "axes": [_axis_manifest(axis, index) for index, axis in enumerate(axes)],
        "features": [_feature_manifest(feature) for feature in features],
        "selection": selection,
        "compatibility": compatibility,
        "bracket_layers": bracket_layers,
        "source_gate": gate,
    }


def inspect_glyphs_source(
    path: str | Path,
    *,
    selected_glyphs: Iterable[str] = (),
    expected_app_version: str | int | None = None,
    expected_master_count: int | None = None,
    expected_glyph_count: int | None = None,
) -> dict[str, Any]:
    """Read a .glyphs file with glyphsLib and return its source manifest."""

    source = Path(path)
    if not source.is_file():
        raise SourceManifestError(f"Glyphs source file does not exist: {source}")
    if source.suffix.casefold() != ".glyphs":
        raise SourceManifestError(f"expected a .glyphs source file, got: {source}")
    font = _load_glyphs_font(source)
    return build_source_manifest(
        font,
        source=source,
        selected_glyphs=selected_glyphs,
        expected_app_version=expected_app_version,
        expected_master_count=expected_master_count,
        expected_glyph_count=expected_glyph_count,
    )


def inspect_ibm_plex_sans_tc_source(
    path: str | Path,
    *,
    selected_glyphs: Iterable[str] = (),
) -> dict[str, Any]:
    """Inspect the official IBM Plex Sans TC Glyphs source and apply its identity gate."""

    return inspect_glyphs_source(
        path,
        selected_glyphs=selected_glyphs,
        expected_app_version=IBM_PLEX_SANS_TC_APP_VERSION,
        expected_master_count=IBM_PLEX_SANS_TC_MASTER_COUNT,
        expected_glyph_count=IBM_PLEX_SANS_TC_GLYPH_COUNT,
    )
