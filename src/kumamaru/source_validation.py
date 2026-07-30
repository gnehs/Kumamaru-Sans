"""Validate the static and variable fonts compiled from the Glyphs source."""

from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from kumamaru.config import load_config
from kumamaru.font_io import HINTING_TABLES

EXPECTED_WEIGHTS = {
    "Thin": 100,
    "ExtraLight": 200,
    "Light": 300,
    "Regular": 400,
    "Text": 450,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}
REQUIRED_TABLES = {
    "OS/2",
    "cmap",
    "glyf",
    "head",
    "hhea",
    "hmtx",
    "loca",
    "maxp",
    "name",
}
RELEASE_HINTING_TABLES = HINTING_TABLES | {
    "cvar",
}


class SourceValidationError(ValueError):
    """Raised when a compiled source font does not match the release contract."""


def validate_source_build(
    static_dir: Path,
    variable_path: Path,
    *,
    version: str,
    sample_text: str,
) -> dict[str, object]:
    """Validate the complete eight-instance and single-axis variable build."""

    expected_paths = {
        static_dir / f"KumamaruSans-{style}.ttf": (style, weight)
        for style, weight in EXPECTED_WEIGHTS.items()
    }
    actual_paths = set(static_dir.glob("*.ttf"))
    if actual_paths != set(expected_paths):
        missing = sorted(path.name for path in set(expected_paths) - actual_paths)
        extra = sorted(path.name for path in actual_paths - set(expected_paths))
        raise SourceValidationError(f"unexpected static font set; missing={missing}, extra={extra}")
    if not variable_path.is_file() or variable_path.stat().st_size == 0:
        raise SourceValidationError(f"missing variable font: {variable_path}")

    reference_glyph_order: list[str] | None = None
    reference_cmap: set[int] | None = None
    for path, (style, weight) in expected_paths.items():
        with TTFont(path, lazy=False) as font:
            _require_tables(font, path, REQUIRED_TABLES)
            _validate_unhinted(font, path)
            if "fvar" in font or "gvar" in font:
                raise SourceValidationError(f"{path} must be a static TrueType font")
            if font["OS/2"].usWeightClass != weight:
                raise SourceValidationError(
                    f"{path} has weight class {font['OS/2'].usWeightClass}, expected {weight}"
                )
            _validate_names(
                font,
                path,
                style=style,
                version=version,
                sample_text=sample_text,
            )
            reference_glyph_order, reference_cmap = _validate_character_set(
                font,
                path,
                reference_glyph_order,
                reference_cmap,
            )

    with TTFont(variable_path, lazy=False) as font:
        _require_tables(font, variable_path, REQUIRED_TABLES | {"STAT", "fvar", "gvar"})
        _validate_unhinted(font, variable_path)
        _validate_names(
            font,
            variable_path,
            style="Regular",
            version=version,
            sample_text=sample_text,
        )
        reference_glyph_order, reference_cmap = _validate_character_set(
            font,
            variable_path,
            reference_glyph_order,
            reference_cmap,
        )
        _validate_variable_tables(font, variable_path)

    return {
        "static_fonts": len(expected_paths),
        "variable_fonts": 1,
        "glyphs": len(reference_glyph_order or []),
        "encoded_codepoints": len(reference_cmap or set()),
    }


def _require_tables(font: TTFont, path: Path, required: set[str]) -> None:
    missing = sorted(required - set(font.keys()))
    if missing:
        raise SourceValidationError(f"{path} is missing required tables: {missing}")


def _validate_unhinted(font: TTFont, path: Path) -> None:
    """Reject global or per-glyph TrueType hinting in a release artifact."""

    table_tags = set(font.keys())
    global_tables = sorted(
        table_tags & RELEASE_HINTING_TABLES
        | {table_tag for table_tag in table_tags if table_tag.startswith("TSI")}
    )
    instructed_glyphs = [
        glyph_name
        for glyph_name in font.getGlyphOrder()
        if (
            (program := getattr(font["glyf"][glyph_name], "program", None)) is not None
            and program.getBytecode()
        )
    ]
    if not global_tables and not instructed_glyphs:
        return

    details: list[str] = []
    if global_tables:
        details.append(f"hinting global tables present: {global_tables}")
    if instructed_glyphs:
        preview = instructed_glyphs[:20]
        suffix = (
            ""
            if len(instructed_glyphs) <= len(preview)
            else f" (+{len(instructed_glyphs) - len(preview)} more)"
        )
        details.append(f"glyph instructions present: {preview}{suffix}")
    raise SourceValidationError(f"{path} must be unhinted; {'; '.join(details)}")


def _english_name(font: TTFont, name_id: int) -> str | None:
    record = font["name"].getName(name_id, 3, 1, 0x0409)
    return record.toUnicode() if record is not None else None


def _validate_names(
    font: TTFont,
    path: Path,
    *,
    style: str,
    version: str,
    sample_text: str,
) -> None:
    expected = {
        4: f"Kumamaru Sans {style}",
        5: f"Version {version}",
        6: f"KumamaruSans-{style}",
        16: "Kumamaru Sans",
        17: style,
    }
    for name_id, value in expected.items():
        if _english_name(font, name_id) != value:
            raise SourceValidationError(
                f"{path} has unexpected English name ID {name_id}: {_english_name(font, name_id)!r}"
            )
    if font["OS/2"].achVendID != "KUMA":
        raise SourceValidationError(f"{path} has unexpected vendor ID")
    if any(
        "Plex" in record.toUnicode()
        for record in font["name"].names
        if record.nameID in {1, 3, 4, 6, 16}
    ):
        raise SourceValidationError(f"{path} still contains a reserved Plex name")
    for language_id in (0x0404, 0x0804):
        for name_id in (1, 2, 4, 16, 17):
            if font["name"].getName(name_id, 3, 1, language_id) is None:
                raise SourceValidationError(
                    f"{path} is missing localized name ID {name_id} for {language_id:#06x}"
                )
    for language_id in (0x0409, 0x0404, 0x0804):
        record = font["name"].getName(19, 3, 1, language_id)
        if record is None or record.toUnicode() != sample_text:
            raise SourceValidationError(f"{path} has unexpected sample text for {language_id:#06x}")


def _validate_character_set(
    font: TTFont,
    path: Path,
    reference_glyph_order: list[str] | None,
    reference_cmap: set[int] | None,
) -> tuple[list[str], set[int]]:
    glyph_order = font.getGlyphOrder()
    cmap = set((font.getBestCmap() or {}).keys())
    if reference_glyph_order is not None and glyph_order != reference_glyph_order:
        raise SourceValidationError(f"{path} has a different glyph order")
    if reference_cmap is not None and cmap != reference_cmap:
        raise SourceValidationError(f"{path} has a different encoded character set")
    return glyph_order, cmap


def _validate_variable_tables(font: TTFont, path: Path) -> None:
    fvar = font["fvar"]
    axes = fvar.axes
    if len(axes) != 1:
        raise SourceValidationError(f"{path} must contain exactly one variation axis")
    axis = axes[0]
    axis_range = (axis.axisTag, axis.minValue, axis.defaultValue, axis.maxValue)
    if axis_range != ("wght", 100, 400, 700):
        raise SourceValidationError(f"{path} has unexpected variable axis range {axis_range}")
    if _english_name(font, axis.axisNameID) != "Weight":
        raise SourceValidationError(f"{path} has an unexpected English axis name")

    instances = {
        _english_name(font, instance.subfamilyNameID): instance.coordinates["wght"]
        for instance in fvar.instances
    }
    if instances != EXPECTED_WEIGHTS:
        raise SourceValidationError(f"{path} has unexpected named instances: {instances}")

    stat = font["STAT"].table
    if stat.DesignAxisCount != 1 or stat.DesignAxisRecord.Axis[0].AxisTag != "wght":
        raise SourceValidationError(f"{path} has an unexpected STAT axis record")
    axis_values = stat.AxisValueArray.AxisValue if stat.AxisValueArray is not None else []
    values = {float(value.Value): value for value in axis_values if hasattr(value, "Value")}
    if set(values) != set(EXPECTED_WEIGHTS.values()):
        raise SourceValidationError(f"{path} STAT values do not cover every named instance")
    regular = values[400]
    if regular.Flags & 0x2 == 0 or getattr(regular, "LinkedValue", None) != 700:
        raise SourceValidationError(f"{path} STAT Regular value must be elidable and link to Bold")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("static_dir", type=Path)
    parser.add_argument("variable_font", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    font_config = load_config(args.config).font
    result = validate_source_build(
        args.static_dir,
        args.variable_font,
        version=font_config.version,
        sample_text=font_config.sample_text,
    )
    print(
        f"validated {result['static_fonts']} static fonts and "
        f"{result['variable_fonts']} variable font"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
