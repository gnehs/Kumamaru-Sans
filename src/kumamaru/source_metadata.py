"""Add localized OpenType names to fonts compiled from the Glyphs source."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

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


def localize_compiled_font(path: Path) -> dict[str, Any]:
    """Add Traditional and Simplified Chinese name records in place."""

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

    font.save(path)
    return {"path": str(path), "records_written": written}


def _english_name(font: TTFont, name_id: int) -> str | None:
    record = font["name"].getName(name_id, 3, 1, 0x0409)
    return record.toUnicode() if record is not None else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.ttf")))
        else:
            files.append(path)
    if not files:
        raise SourceMetadataError("no TTF files found")
    for path in files:
        localize_compiled_font(path)
        print(f"localized: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
