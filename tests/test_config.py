from pathlib import Path

import pytest

from kumamaru.config import ConfigError, load_config, load_overrides, parse_glyphset

ROOT = Path(__file__).parents[1]


def test_default_config_loads() -> None:
    config = load_config(ROOT / "config/regular.toml")
    assert config.font.family_name == "Kumamaru Sans"
    assert config.font.vendor_id == "KUMA"
    assert config.font.sample_text.startswith("姐妹們誰懂啊")
    assert config.spur_detection.report_only is True


def test_glyphset_deduplicates_and_preserves_order(tmp_path: Path) -> None:
    glyphs = tmp_path / "glyphs.txt"
    glyphs.write_text("個\nU+500B\nA # comment\nA\n", encoding="utf-8")
    assert parse_glyphset(glyphs) == ["個", "A"]


def test_invalid_unicode_is_rejected(tmp_path: Path) -> None:
    glyphs = tmp_path / "glyphs.txt"
    glyphs.write_text("U+NOPE\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        parse_glyphset(glyphs)


def test_override_schema_loads() -> None:
    overrides = load_overrides(ROOT / "config/overrides.yaml")
    assert overrides["U+5FC3"]["disable_spur_removal"] is True
