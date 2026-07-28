from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

from kumamaru.font_io import (
    inspect_font,
    load_font,
    remove_dsig,
    save_font,
    sha256_file,
    strip_hinting,
)
from kumamaru.validate import validate_fonts
from tests.fixtures.synthetic_font import GLYPH_ORDER, build_synthetic_font


def test_inspect_reports_required_font_facts(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")

    report = inspect_font(source, smoke_glyphs=["個", "U+0041", "missing"])

    assert report["sha256"] == sha256_file(source)
    assert report["sfnt_flavor"] == "TrueType"
    assert report["units_per_em"] == 1000
    assert report["glyph_count"] == len(GLYPH_ORDER)
    assert report["outline_counts"]["composite"] == 1
    assert report["hinting"]["present"] is True
    assert report["smoke_glyphs"]["U+500B"] == {
        "present": True,
        "glyph_name": "uni500B",
    }
    assert report["smoke_glyphs"]["missing"]["present"] is False


def test_strip_hinting_and_dsig_survive_roundtrip(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    output = tmp_path / "out.ttf"
    with load_font(source) as font:
        strip_report = strip_hinting(font)
        assert remove_dsig(font) is True
        save_font(font, output)

    with TTFont(output, lazy=False) as rebuilt:
        assert not {"cvt ", "fpgm", "prep", "DSIG"} & set(rebuilt.keys())
        assert all(
            not getattr(rebuilt["glyf"][name], "program", None)
            or not rebuilt["glyf"][name].program.getBytecode()
            for name in rebuilt.getGlyphOrder()
        )
        assert rebuilt["maxp"].maxZones == 1
        assert rebuilt["maxp"].maxSizeOfInstructions == 0
    assert strip_report["unhinted"] is True
    assert strip_report["glyph_instructions_removed"] == 1


def test_validation_accepts_metadata_and_hint_removal(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    output = tmp_path / "out.ttf"
    with load_font(source) as font:
        strip_hinting(font)
        remove_dsig(font)
        save_font(font, output)

    report = validate_fonts(
        source,
        output,
        modified_glyphs=(),
        shaping_cases=(
            {
                "name": "fixture",
                "text": "Aa0個",
                "direction": "ltr",
                "script": "Latn",
                "language": "en",
                "features": {},
            },
        ),
    )

    assert report["passed"], [check for check in report["checks"] if not check["passed"]]
