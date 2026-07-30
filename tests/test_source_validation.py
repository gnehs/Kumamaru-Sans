from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.ttProgram import Program

from kumamaru.source_validation import SourceValidationError, _validate_unhinted
from tests.fixtures.synthetic_font import build_synthetic_font


def test_source_validation_rejects_hinting_global_tables(tmp_path: Path) -> None:
    path = build_synthetic_font(tmp_path / "hinted.ttf", with_hinting=True)

    with (
        TTFont(path, lazy=False) as font,
        pytest.raises(
            SourceValidationError,
            match=r"must be unhinted; hinting global tables present: \['cvt ', 'fpgm', 'prep'\]",
        ),
    ):
        _validate_unhinted(font, path)


def test_source_validation_rejects_glyph_programs(tmp_path: Path) -> None:
    path = build_synthetic_font(tmp_path / "glyph-program.ttf", with_hinting=False)
    with TTFont(path, lazy=False) as font:
        program = Program()
        program.fromAssembly(["SVTCA[0]"])
        font["glyf"]["A"].program = program

        with pytest.raises(
            SourceValidationError,
            match=r"must be unhinted; glyph instructions present: \['A'\]",
        ):
            _validate_unhinted(font, path)


def test_source_validation_rejects_variable_cvt_and_vtt_source_tables(tmp_path: Path) -> None:
    path = build_synthetic_font(tmp_path / "source-tables.ttf", with_hinting=False)
    with TTFont(path, lazy=False) as font:
        font["cvar"] = newTable("cvar")
        font["TSI1"] = newTable("TSI1")
        font["TSIB"] = newTable("TSIB")

        with pytest.raises(
            SourceValidationError,
            match=r"hinting global tables present: \['TSI1', 'TSIB', 'cvar'\]",
        ):
            _validate_unhinted(font, path)
