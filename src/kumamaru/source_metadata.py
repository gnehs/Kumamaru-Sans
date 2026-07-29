"""Add localized OpenType names to fonts compiled from the Glyphs source."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from fontTools.otlLib.builder import buildStatTable  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from kumamaru.config import FontConfig, load_config
from kumamaru.metadata import apply_metadata
from kumamaru.source_normalize import (
    KUMAMARU_LOCALIZED_FAMILY_NAMES,
    KUMAMARU_LOCALIZED_STYLE_NAMES,
)

WINDOWS_LANGUAGES = {
    "ZHT": (3, 1, 0x0404),
    "ZHS": (3, 1, 0x0804),
}
LOCALIZED_WEIGHT_AXIS_NAMES = {
    "ZHT": "字重",
    "ZHS": "字重",
}


class SourceMetadataError(ValueError):
    """Raised when a compiled font cannot be localized safely."""


def localize_compiled_font(
    path: Path,
    *,
    font_config: FontConfig | None = None,
) -> dict[str, Any]:
    """Apply release metadata and localized names to a compiled source font."""

    font = TTFont(path)
    name_table = font["name"]
    english_family = _english_name(font, 16) or _english_name(font, 1)
    if english_family != "Kumamaru Sans":
        raise SourceMetadataError(f"{path} has unexpected family name {english_family!r}")

    english_style = _english_name(font, 17) or _english_name(font, 2) or "Regular"
    if english_style == "Regular" and "fvar" not in font:
        filename_style = path.stem.rpartition("-")[2]
        if filename_style in KUMAMARU_LOCALIZED_STYLE_NAMES:
            english_style = filename_style
    if english_style not in KUMAMARU_LOCALIZED_STYLE_NAMES:
        raise SourceMetadataError(f"{path} has unexpected style name {english_style!r}")

    metadata: dict[str, Any] | None = None
    if font_config is not None:
        metadata = apply_metadata(font, replace(font_config, style_name=english_style))
        name_table = font["name"]

    written: list[dict[str, Any]] = []
    for language, platform in WINDOWS_LANGUAGES.items():
        family = KUMAMARU_LOCALIZED_FAMILY_NAMES[language]
        style = KUMAMARU_LOCALIZED_STYLE_NAMES[english_style][language]
        legacy_family = family
        if _english_name(font, 1) != "Kumamaru Sans":
            legacy_family = f"{family} {style}"
        values = {
            1: legacy_family,
            2: KUMAMARU_LOCALIZED_STYLE_NAMES["Regular"][language],
            4: f"{family} {style}",
            16: family,
            17: style,
        }
        if font_config is not None and font_config.sample_text:
            values[19] = font_config.sample_text
        for name_id, value in values.items():
            name_table.setName(value, name_id, *platform)
            written.append({"language": language, "name_id": name_id, "value": value})

        if "fvar" in font:
            axis = font["fvar"].axes[0]
            name_table.setName(
                LOCALIZED_WEIGHT_AXIS_NAMES[language],
                axis.axisNameID,
                *platform,
            )
            written.append(
                {
                    "language": language,
                    "name_id": axis.axisNameID,
                    "value": LOCALIZED_WEIGHT_AXIS_NAMES[language],
                }
            )
            for instance in font["fvar"].instances:
                instance_style = _english_name(font, instance.subfamilyNameID)
                if instance_style not in KUMAMARU_LOCALIZED_STYLE_NAMES:
                    raise SourceMetadataError(
                        f"{path} has unexpected variable instance name {instance_style!r}"
                    )
                value = KUMAMARU_LOCALIZED_STYLE_NAMES[instance_style][language]
                name_table.setName(value, instance.subfamilyNameID, *platform)
                written.append(
                    {
                        "language": language,
                        "name_id": instance.subfamilyNameID,
                        "value": value,
                    }
                )

    if "fvar" in font:
        _rebuild_variable_stat(font)

    font.save(path)
    return {
        "path": str(path),
        "metadata": metadata,
        "records_written": written,
    }


def _rebuild_variable_stat(font: TTFont) -> None:
    fvar = font["fvar"]
    if len(fvar.axes) != 1 or fvar.axes[0].axisTag != "wght":
        raise SourceMetadataError("variable font must contain exactly one wght axis")

    values: list[dict[str, Any]] = []
    for instance in fvar.instances:
        value = float(instance.coordinates["wght"])
        entry: dict[str, Any] = {
            "value": value,
            "name": instance.subfamilyNameID,
        }
        if value == fvar.axes[0].defaultValue:
            entry["flags"] = 0x2
            if any(other.coordinates["wght"] == 700 for other in fvar.instances):
                entry["linkedValue"] = 700
        values.append(entry)

    buildStatTable(
        font,
        [
            {
                "tag": "wght",
                "name": fvar.axes[0].axisNameID,
                "ordering": 0,
                "values": values,
            }
        ],
    )


def _english_name(font: TTFont, name_id: int) -> str | None:
    record = font["name"].getName(name_id, 3, 1, 0x0409)
    return record.toUnicode() if record is not None else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        help="project TOML whose font metadata is applied before localization",
    )
    parser.add_argument("paths", nargs="+", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    font_config = load_config(args.config).font if args.config is not None else None
    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.ttf")))
        else:
            files.append(path)
    if not files:
        raise SourceMetadataError("no TTF files found")
    for path in files:
        localize_compiled_font(path, font_config=font_config)
        print(f"localized: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
