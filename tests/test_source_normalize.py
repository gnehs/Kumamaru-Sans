from __future__ import annotations

from pathlib import Path

from glyphsLib.classes import (
    LINE,
    GSAxis,
    GSFont,
    GSFontMaster,
    GSGlyph,
    GSInstance,
    GSLayer,
    GSNode,
    GSPath,
)

from kumamaru.source_normalize import normalize_ibm_plex_tc_source


def test_normalize_ibm_source_sets_explicit_user_weight_locations(tmp_path: Path) -> None:
    font = GSFont()
    font.familyName = "IBM Plex Sans TC"
    axis = GSAxis()
    axis.name = "Weight"
    axis.axisTag = "wght"
    font.axes.append(axis)
    for name, internal_location in (("Thin", 100), ("Regular", 360), ("Bold", 700)):
        master = GSFontMaster()
        master.name = name
        master.axes = [internal_location]
        font.masters.append(master)
    for name, internal_location in (
        ("Thin", 100),
        ("ExtraLight", 161),
        ("Light", 258),
        ("Regular", 360),
        ("Text", 450),
        ("Medium", 525),
        ("SemiBold", 620),
        ("Bold", 700),
    ):
        instance = GSInstance()
        instance.name = name
        instance.axes = [internal_location]
        instance.weight = "Regular" if name == "Bold" else name
        font.instances.append(instance)

    report = normalize_ibm_plex_tc_source(font)

    assert font.familyName == "Kumamaru Sans"
    assert next(
        prop for prop in font.properties if prop.key == "familyNames"
    )._localized_values == {
        "ENG": "Kumamaru Sans",
        "ZHT": "熊丸體",
        "ZHS": "熊丸体",
    }
    assert next(
        prop for prop in font.instances[3].properties if prop.key == "styleNames"
    )._localized_values == {
        "ENG": "Regular",
        "ZHT": "標準體",
        "ZHS": "常规体",
    }
    assert "1 3 1 0x0404; 熊丸體" in [
        parameter.value
        for parameter in font.customParameters
        if parameter.name == "Name Table Entry"
    ]
    assert "17 3 1 0x0404; 標準體" in [
        parameter.value
        for parameter in font.instances[3].customParameters
        if parameter.name == "Name Table Entry"
    ]
    assert report["original_family"] == "IBM Plex Sans TC"
    assert font.instances[-1].weight == "Bold"
    assert font.masters[1].customParameters["Axis Location"] == [
        {"Axis": "Weight", "Location": 400}
    ]
    assert font.instances[4].customParameters["Axis Location"] == [
        {"Axis": "Weight", "Location": 450}
    ]

    output = tmp_path / "localized.glyphs"
    font.save(output)
    reloaded = GSFont(output)
    assert "1 3 1 0x0404; 熊丸體" in [
        parameter.value
        for parameter in reloaded.customParameters
        if parameter.name == "Name Table Entry"
    ]
    assert "17 3 1 0x0804; 常规体" in [
        parameter.value
        for parameter in reloaded.instances[3].customParameters
        if parameter.name == "Name Table Entry"
    ]


def test_normalize_restores_canonical_unicode_without_removing_compatibility_alias() -> None:
    font = GSFont()
    font.familyName = "IBM Plex Sans TC"
    for name in ("Thin", "Regular", "Bold"):
        master = GSFontMaster()
        master.name = name
        font.masters.append(master)
    for name in ("Thin", "ExtraLight", "Light", "Regular", "Text", "Medium", "SemiBold", "Bold"):
        instance = GSInstance()
        instance.name = name
        font.instances.append(instance)
    glyph = GSGlyph("uni975E")
    glyph.unicodes = ["2FAE"]
    font.glyphs.append(glyph)

    report = normalize_ibm_plex_tc_source(font)

    assert font.glyphs["uni975E"].unicodes == ["2FAE", "975E"]
    assert report["repaired_unicode_glyphs"] == ["uni975E"]


def test_normalize_adds_shape_preserving_points_for_variable_topology() -> None:
    font = GSFont()
    font.familyName = "IBM Plex Sans TC"
    masters: dict[str, GSFontMaster] = {}
    for name in ("Thin", "Regular", "Bold"):
        master = GSFontMaster()
        master.name = name
        font.masters.append(master)
        masters[name] = master
    for name in ("Thin", "ExtraLight", "Light", "Regular", "Text", "Medium", "SemiBold", "Bold"):
        instance = GSInstance()
        instance.name = name
        font.instances.append(instance)

    glyph = GSGlyph("Four-roman")
    thin_points = [
        (698, 0),
        (960, 733),
        (937, 733),
        (684, 25),
        (681, 25),
        (429, 733),
        (405, 733),
        (666, 0),
    ]
    bold_points = [
        (779, 0),
        (981, 733),
        (825, 733),
        (738, 384),
        (699, 170),
        (696, 170),
        (652, 384),
        (566, 733),
        (411, 733),
        (607, 0),
    ]
    for name, points in (
        ("Thin", thin_points),
        ("Regular", thin_points),
        ("Bold", bold_points),
    ):
        layer = GSLayer()
        layer.layerId = masters[name].id
        layer.associatedMasterId = masters[name].id
        path = GSPath()
        path.closed = True
        path.nodes = [GSNode(point, type=LINE) for point in points]
        layer.paths.append(path)
        glyph.layers.append(layer)
    bracket = GSLayer()
    bracket.name = "[275]"
    bracket.layerId = "BRACKET"
    bracket.associatedMasterId = masters["Regular"].id
    bracket_path = GSPath()
    bracket_path.closed = True
    bracket_path.nodes = [GSNode(point, type=LINE) for point in bold_points]
    bracket.paths.append(bracket_path)
    glyph.layers.append(bracket)
    font.glyphs.append(glyph)

    report = normalize_ibm_plex_tc_source(font)

    assert report["repaired_variable_topology_glyphs"] == ["Four-roman"]
    for layer in glyph.layers:
        assert len(layer.paths[0].nodes) == 10
    thin_nodes = glyph.layers[masters["Thin"].id].paths[0].nodes
    for start, inserted, end in (
        (thin_nodes[2], thin_nodes[3], thin_nodes[4]),
        (thin_nodes[5], thin_nodes[6], thin_nodes[7]),
    ):
        cross = (inserted.position.x - start.position.x) * (end.position.y - start.position.y) - (
            inserted.position.y - start.position.y
        ) * (end.position.x - start.position.x)
        assert abs(cross) < 1e-6

    second_report = normalize_ibm_plex_tc_source(font)

    assert second_report["repaired_variable_topology_glyphs"] == []
