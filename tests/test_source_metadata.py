from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._f_v_a_r import Axis, NamedInstance

from kumamaru.config import FontConfig
from kumamaru.source_metadata import localize_compiled_font


def _font(path: Path, *, variable: bool = False) -> None:
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef"])
    builder.setupCharacterMap({})
    pen = TTGlyphPen(None)
    builder.setupGlyf({".notdef": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (500, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": "Kumamaru Sans",
            "styleName": "Regular",
            "fullName": "Kumamaru Sans Regular",
            "psName": "KumamaruSans-Regular",
            "uniqueFontIdentifier": "Kumamaru Sans Regular",
        }
    )
    builder.setupOS2()
    builder.setupPost()
    if variable:
        fvar = builder.font["fvar"] = newTable("fvar")
        axis = Axis()
        axis.axisTag = "wght"
        axis.minValue = 100
        axis.defaultValue = 400
        axis.maxValue = 700
        axis.flags = 0
        axis.axisNameID = 256
        builder.font["name"].setName("Weight", 256, 3, 1, 0x0409)
        instance = NamedInstance()
        instance.subfamilyNameID = 2
        instance.coordinates = {"wght": 400}
        instance.postscriptNameID = 0xFFFF
        fvar.axes = [axis]
        fvar.instances = [instance]
    builder.save(path)


def test_localize_compiled_static_font(tmp_path: Path) -> None:
    path = tmp_path / "KumamaruSans-Regular.ttf"
    _font(path)

    localize_compiled_font(path)

    font = TTFont(path)
    names = font["name"]
    assert names.getName(1, 3, 1, 0x0404).toUnicode() == "熊丸體"
    assert names.getName(4, 3, 1, 0x0804).toUnicode() == "熊丸体 常规体"
    assert names.getName(17, 3, 1, 0x0404).toUnicode() == "標準體"
    assert names.getName(6, 3, 1, 0x0404) is None


def test_localize_compiled_variable_axis_and_instance(tmp_path: Path) -> None:
    path = tmp_path / "KumamaruSans[wght].ttf"
    _font(path, variable=True)

    localize_compiled_font(path)

    font = TTFont(path)
    names = font["name"]
    assert names.getName(256, 3, 1, 0x0404).toUnicode() == "字重"
    assert names.getName(2, 3, 1, 0x0404).toUnicode() == "標準體"
    stat = font["STAT"].table
    assert stat.AxisValueCount == 1
    axis_value = stat.AxisValueArray.AxisValue[0]
    assert axis_value.Value == 400
    assert axis_value.Flags == 0x2


def test_apply_project_metadata_to_compiled_source_font(tmp_path: Path) -> None:
    path = tmp_path / "KumamaruSans-Regular.ttf"
    _font(path)
    config = FontConfig(
        family_name="Kumamaru Sans",
        family_name_zh_hant="熊丸體",
        style_name="Regular",
        version="0.1.0",
        vendor_id="KUMA",
        copyright_notice="Copyright Example.",
        sample_text="姐妹們誰懂啊！！",
    )

    localize_compiled_font(path, font_config=config)

    font = TTFont(path)
    names = font["name"]
    assert names.getName(16, 3, 1, 0x0409).toUnicode() == "Kumamaru Sans"
    assert names.getName(17, 3, 1, 0x0409).toUnicode() == "Regular"
    assert names.getName(5, 3, 1, 0x0409).toUnicode() == "Version 0.1.0"
    assert names.getName(19, 3, 1, 0x0804).toUnicode() == "姐妹們誰懂啊！！"
    assert font["OS/2"].achVendID == "KUMA"
    assert font["head"].fontRevision == pytest.approx(0.1, abs=1e-4)
