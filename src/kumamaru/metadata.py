from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

OFL_DESCRIPTION = "This Font Software is licensed under the SIL Open Font License, Version 1.1."
OFL_URL = "https://openfontlicense.org"
DEFAULT_MODIFICATION_NOTICE = (
    "Modified by the Kumamaru Sans project; this modified font is not endorsed by IBM."
)
MANAGED_NAME_IDS = frozenset({0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17, 19})
WINDOWS_ENGLISH = (3, 1, 0x0409)
WINDOWS_ZH_TW = (3, 1, 0x0404)
UNICODE_RECORD = (0, 4, 0)


class MetadataError(ValueError):
    """Raised when requested metadata cannot form a valid OpenType name table."""


def _config_values(config: object) -> dict[str, Any]:
    if is_dataclass(config):
        values = asdict(config)  # type: ignore[arg-type]
    elif isinstance(config, Mapping):
        values = dict(config)
    else:
        names = (
            "family_name",
            "family_name_zh_hant",
            "style_name",
            "version",
            "vendor_id",
            "copyright_notice",
            "modification_notice",
            "license_description",
            "license_url",
            "sample_text",
        )
        values = {name: getattr(config, name) for name in names if hasattr(config, name)}
    nested = values.get("font")
    if isinstance(nested, Mapping):
        values = dict(nested)
    return values


def _required_string(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MetadataError(f"font metadata field {key!r} must be a non-empty string")
    return value.strip()


def _existing_copyright(font: TTFont) -> str:
    notices: list[str] = []
    for record in font["name"].names:
        if record.nameID != 0:
            continue
        try:
            value = record.toUnicode().strip()
        except UnicodeError:
            continue
        if value and value not in notices:
            notices.append(value)
    return " ".join(notices)


def _set_records(
    font: TTFont,
    name_id: int,
    english: str,
    traditional_chinese: str | None = None,
) -> None:
    name_table = font["name"]
    name_table.setName(english, name_id, *WINDOWS_ENGLISH)
    name_table.setName(traditional_chinese or english, name_id, *WINDOWS_ZH_TW)
    name_table.setName(traditional_chinese or english, name_id, *UNICODE_RECORD)


def read_metadata(font: TTFont) -> dict[str, Any]:
    """Read the primary names and licensing fields used by inspect/build reports."""

    name_table = font["name"]

    def name(name_id: int) -> str | None:
        value: str | None = name_table.getFirstDebugName((name_id,))
        return value

    return {
        "copyright": name(0),
        "family": name_table.getBestFamilyName() or name(1),
        "subfamily": name_table.getBestSubFamilyName() or name(2),
        "unique_id": name(3),
        "full_name": name_table.getBestFullName() or name(4),
        "version": name(5),
        "postscript_name": name(6),
        "license_description": name(13),
        "license_url": name(14),
        "typographic_family": name(16),
        "typographic_subfamily": name(17),
        "vendor_id": font["OS/2"].achVendID,
        "fs_type": font["OS/2"].fsType,
    }


def apply_metadata(font: TTFont, config: object) -> dict[str, Any]:
    """Apply centrally configured Regular metadata in place and return a change report."""

    values = _config_values(config)
    family = _required_string(values, "family_name")
    family_zh = _required_string(values, "family_name_zh_hant")
    style = _required_string(values, "style_name")
    raw_version = _required_string(values, "version")
    vendor_id = _required_string(values, "vendor_id")
    if len(vendor_id) != 4 or not vendor_id.isascii():
        raise MetadataError("vendor_id must be exactly four ASCII characters")

    version = raw_version.removeprefix("Version ").strip()
    version_parts = version.split(".")
    try:
        font_revision = float(".".join(version_parts[:2]))
    except ValueError as exc:
        raise MetadataError("version must begin with numeric major.minor components") from exc
    version_name = f"Version {version}"
    full_name = f"{family} {style}"
    full_name_zh = f"{family_zh} {style}"
    postscript_name = f"{family.replace(' ', '')}-{style.replace(' ', '')}"
    if len(postscript_name) > 63 or re.search(r"[^!-~]|[\[\](){}<>/%]", postscript_name):
        raise MetadataError(
            "family_name and style_name must produce a valid <=63-byte PostScript name"
        )
    unique_id = f"{version};{vendor_id};{postscript_name}"

    upstream_copyright = _existing_copyright(font)
    configured_copyright = str(values.get("copyright_notice", "")).strip()
    modification_notice = str(
        values.get("modification_notice", DEFAULT_MODIFICATION_NOTICE)
    ).strip()
    while modification_notice and upstream_copyright.endswith(modification_notice):
        upstream_copyright = upstream_copyright[: -len(modification_notice)].strip()
    attribution_parts = [upstream_copyright]
    if configured_copyright and configured_copyright not in upstream_copyright:
        attribution_parts.append(configured_copyright)
    copyright_notice = " ".join(part for part in (*attribution_parts, modification_notice) if part)
    license_description = str(values.get("license_description", OFL_DESCRIPTION)).strip()
    license_url = str(values.get("license_url", OFL_URL)).strip()
    sample_text = str(values.get("sample_text", "")).strip()
    if not copyright_notice or not license_description or not license_url:
        raise MetadataError("copyright, modification, and license metadata may not be empty")

    before = read_metadata(font)
    name_table = font["name"]
    name_table.names = [
        record for record in name_table.names if record.nameID not in MANAGED_NAME_IDS
    ]
    _set_records(font, 0, copyright_notice)
    _set_records(font, 1, family, family_zh)
    _set_records(font, 2, style)
    _set_records(font, 3, unique_id)
    _set_records(font, 4, full_name, full_name_zh)
    _set_records(font, 5, version_name)
    _set_records(font, 6, postscript_name)
    _set_records(font, 13, license_description)
    _set_records(font, 14, license_url)
    _set_records(font, 16, family, family_zh)
    _set_records(font, 17, style)
    if sample_text:
        _set_records(font, 19, sample_text, sample_text)

    font["OS/2"].achVendID = vendor_id
    font["OS/2"].fsType = 0
    if style.casefold() == "regular":
        font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0x21) | 0x40
        font["head"].macStyle &= ~0x03
    font["head"].fontRevision = font_revision
    after = read_metadata(font)
    return {
        "before": before,
        "after": after,
        "localized_family": {
            "en": family,
            "zh-TW": family_zh,
        },
        "license": "OFL-1.1",
        "upstream_attribution_preserved": bool(
            upstream_copyright and upstream_copyright in copyright_notice
        ),
    }
