from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from glyphsLib import GSFont, GSFontMaster, GSGlyph, GSLayer, GSNode, GSPath

from kumamaru.source_manifest import (
    IBM_PLEX_SANS_TC_GLYPH_COUNT,
    SourceManifestError,
    build_source_manifest,
    inspect_glyphs_source,
)


@dataclass
class Node:
    type: str


@dataclass
class PathShape:
    nodes: list[Node]
    closed: bool = True


@dataclass
class ComponentShape:
    name: str


@dataclass
class Layer:
    layerId: str
    associatedMasterId: str
    shapes: list[object]
    name: str = ""
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class Glyph:
    name: str
    unicodes: list[str]
    layers: list[Layer]


def _font() -> SimpleNamespace:
    masters = [
        SimpleNamespace(id="M1", name="Regular", axes=[100]),
        SimpleNamespace(id="M2", name="Bold", axes=[700]),
        SimpleNamespace(id="M3", name="Black", axes=[900]),
    ]
    compatible_layers = [
        Layer(
            master.id,
            master.id,
            [PathShape([Node("line"), Node("curve"), Node("offcurve")])],
        )
        for master in masters
    ]
    compatible_layers.append(
        Layer(
            "BRACKET",
            "M2",
            [PathShape([Node("line"), Node("curve"), Node("offcurve")])],
            attributes={"axisRules": [{"min": 600}]},
        )
    )
    incompatible_layers = [
        Layer("M1", "M1", [ComponentShape("stem")]),
        Layer("M2", "M2", [ComponentShape("stem")]),
        Layer("M3", "M3", [ComponentShape("different")]),
    ]
    return SimpleNamespace(
        appVersion="3259",
        format_version=3,
        familyName="Example Sans",
        glyphs=[
            Glyph("A", ["0041"], compatible_layers),
            Glyph("uni500B", ["500B"], incompatible_layers),
        ],
        masters=masters,
        instances=[SimpleNamespace(name="Regular", active=True, type=0, axes=[100])],
        axes=[SimpleNamespace(axisId="weight", name="Weight", axisTag="wght", hidden=False)],
        features=[SimpleNamespace(name="kern", automatic=True, disabled=False)],
    )


def test_manifest_is_json_ready_and_reports_topology_and_brackets() -> None:
    manifest = build_source_manifest(_font(), source="Example.glyphs")

    assert json.loads(json.dumps(manifest, sort_keys=True)) == manifest
    assert manifest["app_version"] == "3259"
    assert manifest["family"] == "Example Sans"
    assert manifest["master_count"] == 3
    assert manifest["instance_count"] == 1
    assert manifest["axis_count"] == 1
    assert manifest["feature_count"] == 1
    assert manifest["compatibility"]["compatible"] is False
    assert manifest["compatibility"]["mismatch_glyphs"] == ["uni500B"]
    assert manifest["bracket_layers"] == {
        "total": 1,
        "glyph_count": 1,
        "by_glyph": {"A": 1},
        "by_master": {"M2": 1},
    }


def test_selection_resolves_character_unicode_and_glyph_name() -> None:
    manifest = build_source_manifest(
        _font(),
        source="Example.glyphs",
        selected_glyphs=["A", "U+500B", "uni500B", "missing"],
    )

    assert manifest["selection"]["limited"] is True
    assert manifest["selection"]["requested"] == [
        {"token": "A", "glyph_name": "A"},
        {"token": "U+500B", "glyph_name": "uni500B"},
        {"token": "uni500B", "glyph_name": "uni500B"},
        {"token": "missing", "glyph_name": None},
    ]
    assert manifest["selection"]["missing"] == ["missing"]
    assert manifest["compatibility"]["checked_glyph_count"] == 2


def test_selection_limits_expensive_glyph_checks() -> None:
    manifest = build_source_manifest(_font(), source="Example.glyphs", selected_glyphs=["A"])

    assert manifest["compatibility"]["compatible"] is True
    assert manifest["compatibility"]["mismatches"] == {}
    assert manifest["bracket_layers"]["by_glyph"] == {"A": 1}
    assert manifest["glyph_count"] == 2


def test_selection_falls_back_to_canonical_name_when_source_unicode_is_wrong() -> None:
    font = _font()
    font.glyphs.append(Glyph("uni975E", ["2FAE"], []))

    manifest = build_source_manifest(font, source="Example.glyphs", selected_glyphs=["非"])

    assert manifest["selection"]["requested"] == [{"token": "非", "glyph_name": "uni975E"}]


def test_gate_reports_all_mismatched_source_identity_fields() -> None:
    manifest = build_source_manifest(
        _font(),
        source="Example.glyphs",
        expected_app_version=3258,
        expected_master_count=2,
        expected_glyph_count=IBM_PLEX_SANS_TC_GLYPH_COUNT,
    )

    assert manifest["source_gate"]["passed"] is False
    failed_fields = [
        check["field"] for check in manifest["source_gate"]["checks"] if not check["passed"]
    ]
    assert failed_fields == [
        "app_version",
        "master_count",
        "glyph_count",
    ]


def test_inspect_rejects_missing_and_non_glyphs_sources(tmp_path: Path) -> None:
    with pytest.raises(SourceManifestError, match="does not exist"):
        inspect_glyphs_source(tmp_path / "missing.glyphs")

    wrong_format = tmp_path / "source.txt"
    wrong_format.write_text("", encoding="utf-8")
    with pytest.raises(SourceManifestError, match=r"expected a \.glyphs"):
        inspect_glyphs_source(wrong_format)


def test_inspect_reads_a_real_glyphs_source(tmp_path: Path) -> None:
    source = tmp_path / "Example.glyphs"
    font = GSFont()
    font.familyName = "Roundtrip Sans"
    font.appVersion = "3259"
    font.format_version = 3
    for name, axis_value in (("Regular", 100), ("Bold", 700), ("Black", 900)):
        master = GSFontMaster()
        master.name = name
        master.axes = [axis_value]
        font.masters.append(master)
    glyph = GSGlyph("A")
    glyph.unicodes = ["0041"]
    font.glyphs.append(glyph)
    for master in font.masters:
        layer = GSLayer()
        layer.layerId = master.id
        layer.associatedMasterId = master.id
        path = GSPath()
        path.nodes = [
            GSNode((0, 0), "line"),
            GSNode((100, 0), "line"),
            GSNode((100, 100), "line"),
        ]
        layer.shapes.append(path)
        glyph.layers.append(layer)
    font.save(source)

    manifest = inspect_glyphs_source(source, selected_glyphs=["U+0041"])

    assert manifest["family"] == "Roundtrip Sans"
    assert manifest["master_count"] == 3
    assert manifest["compatibility"]["compatible"] is True
