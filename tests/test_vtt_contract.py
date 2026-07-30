from pathlib import Path

import pytest
from fontTools.ttLib import TTFont, newTable  # type: ignore[import-untyped]
from fontTools.ttLib.tables._f_v_a_r import Axis  # type: ignore[import-untyped]

from kumamaru.vtt_contract import (
    VttContractError,
    prepare_vtt_workspace,
    validate_vtt_artifact,
)
from tests.fixtures.synthetic_font import build_synthetic_font


def _make_variable_font(path: Path) -> Path:
    build_synthetic_font(path, with_hinting=False)
    with TTFont(path) as font:
        fvar = newTable("fvar")
        axis = Axis()
        axis.axisTag = "wght"
        axis.minValue = 100
        axis.defaultValue = 400
        axis.maxValue = 700
        axis.flags = 0
        axis.axisNameID = 256
        fvar.axes = [axis]
        fvar.instances = []
        font["fvar"] = fvar

        gvar = newTable("gvar")
        gvar.version = 1
        gvar.reserved = 0
        gvar.variations = {glyph_name: [] for glyph_name in font.getGlyphOrder()}
        font["gvar"] = gvar
        font.save(path)
    return path


def test_prepare_vtt_workspace_rejects_static_font(tmp_path: Path) -> None:
    font_path = build_synthetic_font(tmp_path / "static.ttf", with_hinting=False)

    with pytest.raises(VttContractError, match="must be a TrueType variable font"):
        prepare_vtt_workspace(font_path, tmp_path / "workspace", pilot_text="A")


def test_prepare_vtt_workspace_copies_variable_font_and_writes_manifest(tmp_path: Path) -> None:
    font_path = _make_variable_font(tmp_path / "variable.ttf")

    report = prepare_vtt_workspace(font_path, tmp_path / "workspace", pilot_text="A")

    assert (tmp_path / "workspace/KumamaruSans-wght-VTT-source.ttf").is_file()
    assert (tmp_path / "workspace/manifest.json").is_file()
    assert (tmp_path / "workspace/PILOT.txt").read_text(encoding="utf-8") == "A\n"
    assert report["axes"] == {"wght": {"min": 100, "default": 400, "max": 700}}


def test_validate_vtt_source_requires_source_tables(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)

    with pytest.raises(VttContractError, match="has no TSI source tables"):
        validate_vtt_artifact(baseline, baseline, stage="source", pilot_text="A")


def test_validate_vtt_artifact_requires_unhinted_baseline(tmp_path: Path) -> None:
    hinted = build_synthetic_font(tmp_path / "hinted.ttf", with_hinting=True)

    with pytest.raises(VttContractError, match="baseline must be unhinted"):
        validate_vtt_artifact(hinted, hinted, stage="compiled", pilot_text="A")


def test_validate_vtt_source_accepts_compatible_tsi_font(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)
    candidate = tmp_path / "candidate.ttf"
    with TTFont(baseline) as font:
        font["TSI0"] = newTable("TSI0")
        tsi1 = newTable("TSI1")
        tsi1.glyphPrograms = {"A": "YAnchor(0,0)"}
        tsi1.extraPrograms = {}
        font["TSI1"] = tsi1
        font.save(candidate)

    report = validate_vtt_artifact(baseline, candidate, stage="source", pilot_text="A")

    assert report["source_tables"] == ["TSI0", "TSI1"]


def test_validate_compiled_requires_pilot_instructions(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)
    compiled = build_synthetic_font(tmp_path / "compiled.ttf", with_hinting=True)
    with TTFont(compiled) as font:
        font["glyf"]["A"].program.fromBytecode([])
        font.save(compiled)

    with pytest.raises(VttContractError, match="no glyph instructions"):
        validate_vtt_artifact(baseline, compiled, stage="compiled", pilot_text="A")


def test_validate_compiled_accepts_static_hinted_font(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)
    compiled = build_synthetic_font(tmp_path / "compiled.ttf", with_hinting=True)

    report = validate_vtt_artifact(baseline, compiled, stage="compiled", pilot_text="A")

    assert report["compiled_hint_tables"] == ["cvt ", "fpgm", "prep"]
    assert report["instructed_glyphs"] == 1
    assert report["cvar"] is False


def test_validate_compiled_rejects_obsolete_vtt_source_tables(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)
    compiled = build_synthetic_font(tmp_path / "compiled.ttf", with_hinting=True)
    with TTFont(compiled) as font:
        table = newTable("TSIB")
        table.data = b"obsolete VTT source"
        font["TSIB"] = table
        font.save(compiled)

    with pytest.raises(VttContractError, match=r"source tables: \['TSIB'\]"):
        validate_vtt_artifact(baseline, compiled, stage="compiled", pilot_text="A")


def test_validate_compiled_rejects_outline_changes(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)
    compiled = build_synthetic_font(tmp_path / "compiled.ttf", with_hinting=True)
    with TTFont(compiled) as font:
        font["glyf"]["A"].coordinates[0] = (1, 0)
        font.save(compiled)

    with pytest.raises(VttContractError, match="outlines or point order changed"):
        validate_vtt_artifact(baseline, compiled, stage="compiled", pilot_text="A")


def test_validate_compiled_rejects_on_curve_flag_changes(tmp_path: Path) -> None:
    baseline = build_synthetic_font(tmp_path / "baseline.ttf", with_hinting=False)
    compiled = build_synthetic_font(tmp_path / "compiled.ttf", with_hinting=True)
    with TTFont(compiled) as font:
        font["glyf"]["A"].flags[0] ^= 0x01
        font.save(compiled)

    with pytest.raises(VttContractError, match="outlines or point order changed"):
        validate_vtt_artifact(baseline, compiled, stage="compiled", pilot_text="A")
