"""Repairs needed before compiling the published IBM Plex Sans TC Glyphs source.

The upstream source is authoritative artwork, but its instance weight labels do
not fully describe the intended public ``wght`` coordinates.  In particular,
the Bold instance is labelled Regular and Text shares the Medium class.  Adding
explicit Axis Location parameters makes the mapping deterministic for Glyphs
and glyphsLib/fontmake without changing the internal interpolation coordinates.
"""

from __future__ import annotations

import re
from typing import Any

IBM_PLEX_TC_MASTER_USER_WEIGHTS = {
    "Thin": 100,
    "Regular": 400,
    "Bold": 700,
}

IBM_PLEX_TC_INSTANCE_USER_WEIGHTS = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Text": 450,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}

KUMAMARU_LOCALIZED_FAMILY_NAMES = {
    "ENG": "Kumamaru Sans",
    "ZHT": "熊丸體",
    "ZHS": "熊丸体",
}

KUMAMARU_LOCALIZED_STYLE_NAMES = {
    "Thin": {"ZHT": "極細體", "ZHS": "极细体"},
    "ExtraLight": {"ZHT": "特細體", "ZHS": "特细体"},
    "Light": {"ZHT": "細體", "ZHS": "细体"},
    "Regular": {"ZHT": "標準體", "ZHS": "常规体"},
    "Text": {"ZHT": "內文體", "ZHS": "文本体"},
    "Medium": {"ZHT": "中黑體", "ZHS": "中黑体"},
    "SemiBold": {"ZHT": "中粗體", "ZHS": "中粗体"},
    "Bold": {"ZHT": "粗體", "ZHS": "粗体"},
}

# The published source switches these straight-sided outlines at a bracket
# layer. Thin/Regular therefore omit line points that exist in Bold and the
# bracket layer. Adding on-line points preserves the thin artwork exactly while
# making the masters compatible for OpenType `gvar` interpolation.
_IBM_PLEX_TC_VARIABLE_TOPOLOGY_REPAIRS = {
    "kmSquare": ((0, 7, 7, 8, 9),),
    "Four-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "Six-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "Seven-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "Eight-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "four-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "six-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "seven-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "eight-roman": ((0, 2, 2, 3, 4), (0, 4, 5, 6, 7)),
    "numero": ((0, 2, 2, 3, 4), (0, 8, 9, 10, 11)),
}


class SourceNormalizationError(ValueError):
    """Raised when the expected IBM source structure is not present."""


def normalize_ibm_plex_tc_source(
    font: Any,
    *,
    family_name: str = "Kumamaru Sans",
) -> dict[str, Any]:
    """Apply explicit weight-axis mappings and a non-reserved family name."""

    master_names = {master.name for master in font.masters}
    instance_names = {instance.name for instance in font.instances}
    missing_masters = sorted(IBM_PLEX_TC_MASTER_USER_WEIGHTS.keys() - master_names)
    missing_instances = sorted(IBM_PLEX_TC_INSTANCE_USER_WEIGHTS.keys() - instance_names)
    if missing_masters or missing_instances:
        details: list[str] = []
        if missing_masters:
            details.append(f"masters: {', '.join(missing_masters)}")
        if missing_instances:
            details.append(f"instances: {', '.join(missing_instances)}")
        raise SourceNormalizationError(
            "source does not match IBM Plex Sans TC master structure; missing " + "; ".join(details)
        )

    original_family = str(font.familyName)
    font.familyName = family_name
    localized_family_names = {
        language: value if language != "ENG" else family_name
        for language, value in KUMAMARU_LOCALIZED_FAMILY_NAMES.items()
    }
    _set_localized_property(font, "familyNames", localized_family_names)
    _set_localized_name_entries(
        font,
        {
            language: {1: localized_family_names[language], 16: localized_family_names[language]}
            for language in ("ZHT", "ZHS")
        },
    )
    for master in font.masters:
        location = IBM_PLEX_TC_MASTER_USER_WEIGHTS.get(master.name)
        if location is not None:
            _set_weight_axis_location(master, location)
    for instance in font.instances:
        location = IBM_PLEX_TC_INSTANCE_USER_WEIGHTS.get(instance.name)
        if location is not None:
            _set_weight_axis_location(instance, location)
        if instance.name == "Bold":
            instance.weight = "Bold"
        localized_style_names = {
            "ENG": str(instance.name),
            **KUMAMARU_LOCALIZED_STYLE_NAMES[str(instance.name)],
        }
        _set_localized_property(instance, "styleNames", localized_style_names)
        _set_localized_name_entries(
            instance,
            {
                language: {
                    1: (
                        localized_family_names[language]
                        if instance.name == "Regular"
                        else f"{localized_family_names[language]} {localized_style_names[language]}"
                    ),
                    2: KUMAMARU_LOCALIZED_STYLE_NAMES["Regular"][language],
                    4: f"{localized_family_names[language]} {localized_style_names[language]}",
                    16: localized_family_names[language],
                    17: localized_style_names[language],
                }
                for language in ("ZHT", "ZHS")
            },
        )
    repaired_unicode_glyphs = _restore_canonical_unicode_values(font)
    repaired_variable_topology_glyphs = _repair_variable_topology(font)

    return {
        "original_family": original_family,
        "family": family_name,
        "localized_family_names": localized_family_names,
        "localized_style_names": {
            name: {"ENG": name, **values} for name, values in KUMAMARU_LOCALIZED_STYLE_NAMES.items()
        },
        "master_user_weights": dict(IBM_PLEX_TC_MASTER_USER_WEIGHTS),
        "instance_user_weights": dict(IBM_PLEX_TC_INSTANCE_USER_WEIGHTS),
        "repaired_unicode_glyphs": repaired_unicode_glyphs,
        "repaired_variable_topology_glyphs": repaired_variable_topology_glyphs,
    }


def _set_localized_property(owner: Any, key: str, values: dict[str, str]) -> None:
    from glyphsLib.classes import GSFontInfoValue  # type: ignore[import-untyped]

    existing = next((item for item in owner.properties if item.key == key), None)
    prop = existing or GSFontInfoValue(key)
    prop._localized_values = dict(values)
    if existing is None:
        owner.properties.append(prop)


def _set_localized_name_entries(
    owner: Any,
    values_by_language: dict[str, dict[int, str]],
) -> None:
    from glyphsLib.classes import GSCustomParameter

    language_ids = {"ZHT": "0x0404", "ZHS": "0x0804"}
    managed_prefixes = {
        f"{name_id} 3 1 {language_ids[language]};"
        for language, values in values_by_language.items()
        for name_id in values
    }
    retained = [
        parameter
        for parameter in owner.customParameters
        if parameter.name != "Name Table Entry"
        or not any(str(parameter.value).startswith(prefix) for prefix in managed_prefixes)
    ]
    owner.customParameters = retained
    for language, values in values_by_language.items():
        for name_id, value in values.items():
            owner.customParameters.append(
                GSCustomParameter(
                    name="Name Table Entry",
                    value=f"{name_id} 3 1 {language_ids[language]}; {value}",
                )
            )


def _set_weight_axis_location(item: Any, location: int) -> None:
    item.customParameters["Axis Location"] = [
        {
            "Axis": "Weight",
            "Location": location,
        }
    ]


def _restore_canonical_unicode_values(font: Any) -> list[str]:
    repaired: list[str] = []
    for glyph in font.glyphs:
        match = re.fullmatch(r"uni([0-9A-Fa-f]{4})", str(glyph.name)) or re.fullmatch(
            r"u([0-9A-Fa-f]{5,6})",
            str(glyph.name),
        )
        if match is None:
            continue
        canonical = match.group(1).upper()
        unicode_values = [str(value).upper() for value in glyph.unicodes]
        if canonical not in unicode_values:
            glyph.unicodes = [*unicode_values, canonical]
            repaired.append(str(glyph.name))
    return repaired


def _repair_variable_topology(font: Any) -> list[str]:
    masters = {master.name: master for master in font.masters}
    reference_master = masters["Bold"]
    repaired: list[str] = []
    for glyph_name, insertions in _IBM_PLEX_TC_VARIABLE_TOPOLOGY_REPAIRS.items():
        glyph = font.glyphs[glyph_name]
        if glyph is None:
            continue
        reference_layer = glyph.layers[reference_master.id]
        glyph_changed = False
        for master_name in ("Thin", "Regular"):
            layer = glyph.layers[masters[master_name].id]
            insertions_per_path = {
                path_index: sum(1 for insertion in insertions if insertion[0] == path_index)
                for path_index in {insertion[0] for insertion in insertions}
            }
            needs_repair: dict[int, bool] = {}
            for path_index, insertion_count in insertions_per_path.items():
                target_count = len(layer.paths[path_index].nodes)
                reference_count = len(reference_layer.paths[path_index].nodes)
                expected_count = reference_count - insertion_count
                if target_count not in {expected_count, reference_count}:
                    raise SourceNormalizationError(
                        f"{glyph_name} {master_name} path {path_index} has unexpected "
                        f"node count {target_count}; expected {expected_count} or {reference_count}"
                    )
                needs_repair[path_index] = target_count == expected_count
            for (
                path_index,
                target_start_index,
                reference_start_index,
                reference_insert_index,
                reference_end_index,
            ) in sorted(insertions, key=lambda item: item[1], reverse=True):
                target_path = layer.paths[path_index]
                reference_path = reference_layer.paths[path_index]
                if not needs_repair[path_index]:
                    continue
                reference_start = reference_path.nodes[reference_start_index]
                reference_insert = reference_path.nodes[reference_insert_index]
                reference_end = reference_path.nodes[reference_end_index]
                interpolation = _line_projection_fraction(
                    reference_start.position,
                    reference_insert.position,
                    reference_end.position,
                )
                target_start = target_path.nodes[target_start_index]
                target_end = target_path.nodes[(target_start_index + 1) % len(target_path.nodes)]
                if (
                    target_start.type != reference_insert.type
                    or target_end.type != reference_insert.type
                ):
                    raise SourceNormalizationError(
                        f"{glyph_name} {master_name} path {path_index} repair is not line-only"
                    )
                x = (
                    target_start.position.x
                    + (target_end.position.x - target_start.position.x) * interpolation
                )
                y = (
                    target_start.position.y
                    + (target_end.position.y - target_start.position.y) * interpolation
                )
                target_path.nodes.insert(
                    target_start_index + 1,
                    type(reference_insert)((x, y), type=reference_insert.type),
                )
                glyph_changed = True
        if glyph_changed:
            repaired.append(glyph_name)
    return repaired


def _line_projection_fraction(start: Any, point: Any, end: Any) -> float:
    delta_x = end.x - start.x
    delta_y = end.y - start.y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        raise SourceNormalizationError("cannot project onto a zero-length reference segment")
    fraction = ((point.x - start.x) * delta_x + (point.y - start.y) * delta_y) / length_squared
    if not 0 < fraction < 1:
        raise SourceNormalizationError("reference repair point is outside its line segment")
    return float(fraction)
