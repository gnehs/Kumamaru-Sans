from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from kumamaru.metadata import apply_metadata
from tests.fixtures.synthetic_font import build_synthetic_font


def test_apply_metadata_renames_and_localizes_without_losing_attribution(
    tmp_path: Path,
) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf", with_hinting=False)
    output = tmp_path / "renamed.ttf"
    with TTFont(source) as font:
        result = apply_metadata(
            font,
            {
                "family_name": "Kumamaru Sans",
                "family_name_zh_hant": "熊丸體",
                "style_name": "Regular",
                "version": "0.1.0",
                "vendor_id": "KUMA",
                "modification_notice": "Modified test font; not endorsed by IBM.",
                "license_description": "SIL Open Font License, Version 1.1.",
                "license_url": "https://openfontlicense.org",
            },
        )
        font.save(output)

    with TTFont(output) as rebuilt:
        name = rebuilt["name"]
        assert name.getName(1, 3, 1, 0x0409).toUnicode() == "Kumamaru Sans"
        assert name.getName(1, 3, 1, 0x0404).toUnicode() == "熊丸體"
        assert name.getName(16, 3, 1, 0x0404).toUnicode() == "熊丸體"
        assert name.getName(6, 3, 1, 0x0409).toUnicode() == "KumamaruSans-Regular"
        assert "Copyright Example Upstream." in name.getName(0, 3, 1, 0x0409).toUnicode()
        assert rebuilt["OS/2"].achVendID == "KUMA"
        assert rebuilt["OS/2"].fsType == 0
        assert rebuilt["OS/2"].fsSelection & 0x40
        assert rebuilt["head"].fontRevision == pytest.approx(0.1, abs=1e-4)
    assert result["upstream_attribution_preserved"] is True


def test_primary_names_do_not_retain_reserved_plex_name(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf", with_hinting=False)
    with TTFont(source) as font:
        apply_metadata(
            font,
            {
                "family_name": "Kumamaru Sans",
                "family_name_zh_hant": "熊丸體",
                "style_name": "Regular",
                "version": "0.1.0",
                "vendor_id": "KUMA",
            },
        )
        managed_primary_ids = {1, 3, 4, 6, 16}
        primary_values = [
            record.toUnicode()
            for record in font["name"].names
            if record.nameID in managed_primary_ids
        ]

    assert primary_values
    assert all("Plex" not in value for value in primary_values)


def test_apply_metadata_is_idempotent(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf", with_hinting=False)
    config = {
        "family_name": "Kumamaru Sans",
        "family_name_zh_hant": "熊丸體",
        "style_name": "Regular",
        "version": "0.1.0",
        "vendor_id": "KUMA",
    }
    with TTFont(source) as font:
        apply_metadata(font, config)
        first = [
            (record.nameID, record.platformID, record.platEncID, record.langID, record.toUnicode())
            for record in font["name"].names
        ]
        apply_metadata(font, config)
        second = [
            (record.nameID, record.platformID, record.platEncID, record.langID, record.toUnicode())
            for record in font["name"].names
        ]

    assert second == first
