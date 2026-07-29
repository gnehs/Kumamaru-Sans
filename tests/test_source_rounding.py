from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import pytest

from kumamaru.source_rounding import (
    SourceRoundingError,
    resolve_glyph_tokens,
    round_glyphs_font,
    round_glyphs_source,
)

pytest.importorskip("glyphsLib")
from glyphsLib import (  # noqa: E402, I001
    CURVE,
    LINE,
    OFFCURVE,
    GSFont,
    GSFontMaster,
    GSGlyph,
    GSLayer,
    GSNode,
    GSPath,
)


MASTER_DATA = (
    ("MASTER-LIGHT", "Light", 0.9),
    ("MASTER-REGULAR", "Regular", 1.0),
    ("MASTER-BOLD", "Bold", 1.2),
)


def _path(points: list[tuple[float, float]]) -> GSPath:
    path = GSPath()
    path.closed = True
    path.nodes = [GSNode(point, type=LINE) for point in points]
    return path


def _rotate(
    point: tuple[float, float],
    angle_degrees: float,
) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    return (
        point[0] * math.cos(angle) - point[1] * math.sin(angle),
        point[0] * math.sin(angle) + point[1] * math.cos(angle),
    )


def _stroke_path(
    scale: float,
    *,
    angle_degrees: float = 0,
    cubic_sides: bool = False,
) -> GSPath:
    raw = [
        ((0, 0), LINE),
        *((((130, 0), OFFCURVE), ((270, 0), OFFCURVE)) if cubic_sides else ()),
        ((400, 0), CURVE if cubic_sides else LINE),
        ((400, 100), LINE),
        *((((270, 100), OFFCURVE), ((130, 100), OFFCURVE)) if cubic_sides else ()),
        ((0, 100), CURVE if cubic_sides else LINE),
    ]
    path = GSPath()
    path.closed = True
    path.nodes = [
        GSNode(
            _rotate((point[0] * scale, point[1] * scale), angle_degrees),
            type=node_type,
        )
        for point, node_type in raw
    ]
    return path


def _font(*, mismatch: bool = False) -> GSFont:
    font = GSFont()
    font.familyName = "Synthetic Source"
    masters: list[GSFontMaster] = []
    for master_id, name, _scale in MASTER_DATA:
        master = GSFontMaster()
        master.id = master_id
        master.name = name
        masters.append(master)
        font.masters.append(master)

    glyph = GSGlyph("A")
    glyph.unicodes = ["0041"]
    for master, (_master_id, _name, scale) in zip(masters, MASTER_DATA, strict=True):
        points = [(0, 0), (100 * scale, 0), (100 * scale, 100 * scale), (0, 100 * scale)]
        if mismatch and master.name == "Bold":
            points.insert(2, (100 * scale, 50 * scale))
        layer = GSLayer()
        layer.layerId = master.id
        layer.associatedMasterId = master.id
        layer.paths.append(_path(points))
        glyph.layers.append(layer)
    font.glyphs.append(glyph)
    return font


def _master_node_types(font: GSFont) -> dict[str, list[str]]:
    glyph = font.glyphs["A"]
    return {
        master.name: [node.type for node in glyph.layers[master.id].paths[0].nodes]
        for master in font.masters
    }


def _cross(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return first[0] * second[1] - first[1] * second[0]


def test_rounds_all_masters_with_identical_new_topology_and_per_master_radii() -> None:
    font = _font()
    report = round_glyphs_font(
        font,
        ["A", "U+0041"],
        {"Light": 8, "Regular": 12, "Bold": 18},
    )

    node_types = _master_node_types(font)
    assert len(set(tuple(types) for types in node_types.values())) == 1
    assert {name: len(types) for name, types in node_types.items()} == {
        "Light": 16,
        "Regular": 16,
        "Bold": 16,
    }
    assert node_types["Regular"].count("line") == 4
    assert node_types["Regular"].count("offcurve") == 8
    assert node_types["Regular"].count("curve") == 4
    for master in font.masters:
        nodes = list(font.glyphs["A"].layers[master.id].paths[0].nodes)
        for curve_index, curve_end in enumerate(nodes):
            if curve_end.type != "curve":
                continue
            start = nodes[(curve_index - 3) % len(nodes)].position
            control_1 = nodes[(curve_index - 2) % len(nodes)].position
            control_2 = nodes[(curve_index - 1) % len(nodes)].position
            previous_end = nodes[(curve_index - 4) % len(nodes)].position
            following_end = nodes[(curve_index + 1) % len(nodes)].position
            incoming_line = (start.x - previous_end.x, start.y - previous_end.y)
            curve_start_tangent = (control_1.x - start.x, control_1.y - start.y)
            curve_end_tangent = (
                curve_end.position.x - control_2.x,
                curve_end.position.y - control_2.y,
            )
            outgoing_line = (
                following_end.x - curve_end.position.x,
                following_end.y - curve_end.position.y,
            )
            assert _cross(incoming_line, curve_start_tangent) == pytest.approx(0)
            assert _cross(curve_end_tangent, outgoing_line) == pytest.approx(0)
    assert report["summary"] == {
        "glyphs_requested": 1,
        "glyphs_skipped": 0,
        "candidates_found": 4,
        "candidates_applied": 4,
        "candidates_skipped": 0,
    }
    applied_radii = {
        master["master_name"]: master["radius"]
        for candidate in report["glyphs"][0]["applied"]
        for master in candidate["masters"]
    }
    assert applied_radii == {"Light": 8.0, "Regular": 12.0, "Bold": 18.0}
    json.dumps(report, sort_keys=True)


def test_topology_mismatch_rolls_back_candidate_in_every_master() -> None:
    font = _font(mismatch=True)
    before = _master_node_types(font)

    report = round_glyphs_font(font, ["A"], {"*": 12})

    assert _master_node_types(font) == before
    assert report["summary"]["candidates_found"] == 4
    assert report["summary"]["candidates_applied"] == 0
    assert report["summary"]["candidates_skipped"] == 4
    assert {skipped["reason"] for skipped in report["glyphs"][0]["skipped"]} == {
        "master 'Bold': node topology differs from reference master"
    }


def test_writes_derived_source_resolves_tokens_and_preserves_input(tmp_path: Path) -> None:
    source = tmp_path / "source.glyphs"
    output = tmp_path / "derived.glyphs"
    font = _font()
    font.save(source)
    original = source.read_bytes()

    loaded = GSFont(source)
    assert resolve_glyph_tokens(loaded, ["A", "U+0041"]) == ["A"]
    report = round_glyphs_source(
        source,
        output,
        ["U+0041"],
        {"Light": 8, "Regular": 12, "Bold": 18},
        family_name="Kumamaru Sans",
    )

    assert source.read_bytes() == original
    assert output.is_file()
    derived = GSFont(output)
    assert derived.familyName == "Kumamaru Sans"
    assert all(
        len(derived.glyphs["A"].layers[master.id].paths[0].nodes) == 16
        for master in derived.masters
    )
    assert report["input"] == str(source)
    assert report["output"] == str(output)
    assert report["family_name"] == "Kumamaru Sans"

    with pytest.raises(SourceRoundingError, match="must differ"):
        round_glyphs_source(source, source, ["A"], {"*": 12})


def test_resolves_character_by_canonical_glyph_name_when_source_unicode_is_wrong() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    glyph.name = "uni975E"
    glyph.unicodes = ["2FAE"]

    assert resolve_glyph_tokens(font, ["非"]) == ["uni975E"]


def test_large_radius_is_clamped_below_half_of_each_segment() -> None:
    report = round_glyphs_font(_font(), ["A"], 10_000, max_segment_ratio=0.4)

    for candidate in report["glyphs"][0]["applied"]:
        for master in candidate["masters"]:
            assert master["clamped"] is True
            expected = {
                "Light": 36.0,
                "Regular": 40.0,
                "Bold": 48.0,
            }[master["master_name"]]
            assert master["trim_distance"] == pytest.approx(expected)


def test_bracket_layer_skips_the_entire_glyph_without_partial_master_edits() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    bracket = GSLayer()
    bracket.layerId = "BRACKET-REGULAR"
    bracket.associatedMasterId = "MASTER-REGULAR"
    bracket.name = "[500]"
    bracket.paths.append(_path([(0, 0), (100, 0), (100, 100), (0, 100)]))
    glyph.layers.append(bracket)
    master_nodes_before = _master_node_types(font)
    bracket_nodes_before = [node.type for node in bracket.paths[0].nodes]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    assert _master_node_types(font) == master_nodes_before
    assert [node.type for node in bracket.paths[0].nodes] == bracket_nodes_before
    glyph_report = report["glyphs"][0]
    assert glyph_report["candidates_found"] == 0
    assert glyph_report["applied"] == []
    assert glyph_report["skipped"][0]["reason"] == "unsupported_bracket_layers"
    assert glyph_report["unsupported_bracket_layers"] == [
        {
            "layer_id": "BRACKET-REGULAR",
            "associated_master_id": "MASTER-REGULAR",
            "name": "[500]",
        }
    ]
    assert report["summary"]["glyphs_skipped"] == 1
    assert report["summary"]["candidates_skipped"] == 0


def test_rounds_white_counter_corners_across_all_masters_with_inner_radii() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        layer = glyph.layers[master.id]
        layer.paths = [
            _path(
                [
                    (0, 0),
                    (100 * scale, 0),
                    (100 * scale, 100 * scale),
                    (0, 100 * scale),
                ]
            ),
            _path(
                [
                    (30 * scale, 30 * scale),
                    (30 * scale, 70 * scale),
                    (70 * scale, 70 * scale),
                    (70 * scale, 30 * scale),
                ]
            ),
        ]

    report = round_glyphs_font(
        font,
        ["A"],
        {"Light": 8, "Regular": 12, "Bold": 18},
        inner_radii_by_master={"Light": 5, "Regular": 7, "Bold": 10},
    )

    assert report["summary"] == {
        "glyphs_requested": 1,
        "glyphs_skipped": 0,
        "candidates_found": 8,
        "candidates_applied": 8,
        "candidates_skipped": 0,
    }
    assert Counter(candidate["corner_type"] for candidate in report["glyphs"][0]["applied"]) == {
        "outer": 4,
        "inner": 4,
    }
    for master in font.masters:
        paths = glyph.layers[master.id].paths
        assert [len(path.nodes) for path in paths] == [16, 16]
        assert [node.type for node in paths[0].nodes] == [node.type for node in paths[1].nodes]
    assert [master["inner_radius"] for master in report["masters"]] == [
        5.0,
        7.0,
        10.0,
    ]


def test_omitting_inner_radii_preserves_counter_corners() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        glyph.layers[master.id].paths.append(
            _path(
                [
                    (30 * scale, 30 * scale),
                    (30 * scale, 70 * scale),
                    (70 * scale, 70 * scale),
                    (70 * scale, 30 * scale),
                ]
            )
        )

    report = round_glyphs_font(font, ["A"], {"*": 10})

    assert report["summary"]["candidates_applied"] == 4
    assert {candidate["corner_type"] for candidate in report["glyphs"][0]["applied"]} == {"outer"}
    for master in font.masters:
        assert len(glyph.layers[master.id].paths[0].nodes) == 16
        assert len(glyph.layers[master.id].paths[1].nodes) == 4


def test_all_exporting_glyphs_uses_compact_report_and_excludes_non_exporting() -> None:
    font = _font()
    non_exporting = GSGlyph("do-not-export")
    non_exporting.export = False
    for master in font.masters:
        layer = GSLayer()
        layer.layerId = master.id
        layer.associatedMasterId = master.id
        layer.paths.append(_path([(0, 0), (50, 0), (50, 50), (0, 50)]))
        non_exporting.layers.append(layer)
    font.glyphs.append(non_exporting)

    report = round_glyphs_font(
        font,
        None,
        {"*": 12},
        all_exporting_glyphs=True,
    )

    assert report["report_mode"] == "compact"
    assert report["glyph_selection"] == "all_exporting"
    assert report["summary"] == {
        "glyphs_requested": 1,
        "glyphs_skipped": 0,
        "candidates_found": 4,
        "candidates_applied": 4,
        "candidates_skipped": 0,
    }
    assert report["glyphs"] == [
        {
            "glyph_name": "A",
            "candidates_found": 4,
            "candidates_applied": 4,
            "candidates_skipped": 0,
            "glyph_skipped": False,
            "corner_types": {
                "outer": {"found": 4, "applied": 4, "skipped": 0},
                "inner": {"found": 0, "applied": 0, "skipped": 0},
            },
            "candidate_kinds": {
                "corner": {"found": 4, "applied": 4, "skipped": 0},
                "terminal": {"found": 0, "applied": 0, "skipped": 0},
            },
            "skip_reasons": {},
        }
    ]
    assert "masters" not in report["glyphs"][0]
    json.dumps(report, sort_keys=True)


def test_compact_report_aggregates_skip_reasons_without_candidate_details() -> None:
    font = _font(mismatch=True)

    report = round_glyphs_font(font, ["A"], {"*": 12}, compact_report=True)

    assert report["report_mode"] == "compact"
    assert report["glyphs"][0] == {
        "glyph_name": "A",
        "candidates_found": 4,
        "candidates_applied": 0,
        "candidates_skipped": 4,
        "glyph_skipped": False,
        "corner_types": {
            "outer": {"found": 4, "applied": 0, "skipped": 4},
            "inner": {"found": 0, "applied": 0, "skipped": 0},
        },
        "candidate_kinds": {
            "corner": {"found": 4, "applied": 0, "skipped": 4},
            "terminal": {"found": 0, "applied": 0, "skipped": 0},
        },
        "skip_reasons": {
            "master 'Bold': node topology differs from reference master": 4,
        },
    }


def test_compact_report_summarizes_glyph_level_bracket_skip() -> None:
    font = _font()
    bracket = GSLayer()
    bracket.layerId = "BRACKET-REGULAR"
    bracket.associatedMasterId = "MASTER-REGULAR"
    bracket.name = "[500]"
    font.glyphs["A"].layers.append(bracket)

    report = round_glyphs_font(font, ["A"], {"*": 12}, compact_report=True)

    assert report["glyphs"][0] == {
        "glyph_name": "A",
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
    assert report["summary"]["glyphs_skipped"] == 1


def test_all_exporting_mode_rejects_explicit_glyph_tokens() -> None:
    with pytest.raises(SourceRoundingError, match="must be empty"):
        round_glyphs_font(
            _font(),
            ["A"],
            {"*": 12},
            all_exporting_glyphs=True,
        )


@pytest.mark.parametrize(
    ("angle_degrees", "cubic_sides", "original_node_count"),
    [(0.0, False, 4), (31.0, False, 4), (0.0, True, 8)],
)
def test_rounds_flat_terminals_into_tangent_cubic_caps_across_masters(
    angle_degrees: float,
    cubic_sides: bool,
    original_node_count: int,
) -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        glyph.layers[master.id].paths = [
            _stroke_path(
                scale,
                angle_degrees=angle_degrees,
                cubic_sides=cubic_sides,
            )
        ]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    terminal_reports = [
        item for item in report["glyphs"][0]["applied"] if item["kind"] == "terminal"
    ]
    assert len(terminal_reports) == 2
    assert report["summary"]["candidates_applied"] == 2
    node_types_by_master: list[list[str]] = []
    for master in font.masters:
        nodes = list(glyph.layers[master.id].paths[0].nodes)
        assert len(nodes) == original_node_count + 10
        node_types_by_master.append([node.type for node in nodes])
        for index, node in enumerate(nodes):
            if node.type != CURVE:
                continue
            previous = nodes[(index - 1) % len(nodes)]
            following = nodes[(index + 1) % len(nodes)]
            if previous.type == OFFCURVE and following.type == OFFCURVE:
                incoming_tangent = (
                    node.position.x - previous.position.x,
                    node.position.y - previous.position.y,
                )
                outgoing_tangent = (
                    following.position.x - node.position.x,
                    following.position.y - node.position.y,
                )
                assert _cross(incoming_tangent, outgoing_tangent) == pytest.approx(
                    0,
                    abs=1e-6,
                )
            control_2 = nodes[(index - 1) % len(nodes)]
            if control_2.type != OFFCURVE:
                continue
            if following.type != LINE:
                continue
            tangent = (
                node.position.x - control_2.position.x,
                node.position.y - control_2.position.y,
            )
            outgoing = (
                following.position.x - node.position.x,
                following.position.y - node.position.y,
            )
            assert _cross(tangent, outgoing) == pytest.approx(0, abs=1e-6)
    assert len({tuple(types) for types in node_types_by_master}) == 1


def test_rounds_overlapping_strokes_as_black_contours_not_counters() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        glyph.layers[master.id].paths = [
            _path(
                [
                    (0, 200 * scale),
                    (600 * scale, 200 * scale),
                    (600 * scale, 300 * scale),
                    (0, 300 * scale),
                ]
            ),
            _path(
                [
                    (260 * scale, 0),
                    (340 * scale, 0),
                    (340 * scale, 500 * scale),
                    (260 * scale, 500 * scale),
                ]
            ),
        ]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    terminal_reports = [
        item for item in report["glyphs"][0]["applied"] if item["kind"] == "terminal"
    ]
    assert len(terminal_reports) == 4
    for master in font.masters:
        assert [len(path.nodes) for path in glyph.layers[master.id].paths] == [14, 14]


def test_preserves_terminal_caps_embedded_in_other_black_strokes() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        glyph.layers[master.id].paths = [
            _path(
                [
                    (260 * scale, 50 * scale),
                    (340 * scale, 50 * scale),
                    (340 * scale, 450 * scale),
                    (260 * scale, 450 * scale),
                ]
            ),
            _path(
                [
                    (0, 0),
                    (600 * scale, 0),
                    (600 * scale, 100 * scale),
                    (0, 100 * scale),
                ]
            ),
            _path(
                [
                    (0, 400 * scale),
                    (600 * scale, 400 * scale),
                    (600 * scale, 500 * scale),
                    (0, 500 * scale),
                ]
            ),
        ]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    terminal_reports = [
        item for item in report["glyphs"][0]["applied"] if item["kind"] == "terminal"
    ]
    assert len(terminal_reports) == 4
    assert {item["path_index"] for item in terminal_reports} == {1, 2}
    for master in font.masters:
        assert [len(path.nodes) for path in glyph.layers[master.id].paths] == [16, 14, 14]


def test_relaxes_perpendicular_gate_only_for_long_parallel_shafts() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    cap_slant = math.tan(math.radians(18.3)) * 100
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        glyph.layers[master.id].paths = [
            _path(
                [
                    (0, 0),
                    (400 * scale, 0),
                    ((400 + cap_slant) * scale, 100 * scale),
                    (0, 100 * scale),
                ]
            )
        ]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    terminal_reports = [
        item for item in report["glyphs"][0]["applied"] if item["kind"] == "terminal"
    ]
    assert len(terminal_reports) == 2


def test_terminal_rounding_can_be_disabled() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        glyph.layers[master.id].paths = [_stroke_path(scale)]

    report = round_glyphs_font(
        font,
        ["A"],
        {"*": 12},
        terminal_rounding=False,
    )

    assert not any(item["kind"] == "terminal" for item in report["glyphs"][0]["applied"])


def test_rejects_wide_rectangle_as_terminal_candidate() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master in font.masters:
        glyph.layers[master.id].paths = [_path([(0, 0), (400, 0), (400, 300), (0, 300)])]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    assert not any(item["kind"] == "terminal" for item in report["glyphs"][0]["applied"])


def test_accepts_terminal_width_just_below_safe_maximum_across_masters() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    widths = {"Light": 126, "Regular": 132, "Bold": 139}
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        width = widths[master.name]
        glyph.layers[master.id].paths = [
            _path(
                [
                    (0, 0),
                    (400 * scale, 0),
                    (400 * scale, width),
                    (0, width),
                ]
            )
        ]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    terminal_applied = [
        item for item in report["glyphs"][0]["applied"] if item["kind"] == "terminal"
    ]
    assert len(terminal_applied) == 2


def test_terminal_candidate_is_skipped_when_one_master_fails_geometry_gate() -> None:
    font = _font()
    glyph = font.glyphs["A"]
    for master, (_master_id, _name, scale) in zip(
        font.masters,
        MASTER_DATA,
        strict=True,
    ):
        width = 160 if master.name == "Bold" else 100 * scale
        glyph.layers[master.id].paths = [
            _path(
                [
                    (0, 0),
                    (400 * scale, 0),
                    (400 * scale, width),
                    (0, width),
                ]
            )
        ]

    report = round_glyphs_font(font, ["A"], {"*": 12})

    terminal_applied = [
        item for item in report["glyphs"][0]["applied"] if item["kind"] == "terminal"
    ]
    terminal_skipped = [
        item for item in report["glyphs"][0]["skipped"] if item["kind"] == "terminal"
    ]
    assert terminal_applied == []
    assert len(terminal_skipped) == 2
    assert all("safe maximum" in item["reason"] for item in terminal_skipped)
