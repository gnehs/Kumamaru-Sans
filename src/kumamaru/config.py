from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when a project configuration is invalid."""


@dataclass(frozen=True)
class FontConfig:
    family_name: str
    family_name_zh_hant: str
    style_name: str
    version: str
    vendor_id: str
    strict_upstream_sha: bool = False
    upstream_sha256: str = ""
    copyright_notice: str = ""
    modification_notice: str = "Modified by the Kumamaru Sans project; not endorsed by IBM."
    license_description: str = (
        "This Font Software is licensed under the SIL Open Font License, Version 1.1."
    )
    license_url: str = "https://openfontlicense.org"
    sample_text: str = ""


@dataclass(frozen=True)
class RoundingConfig:
    enabled: bool = True
    outer_radius_em: float = 0.024
    inner_radius_em: float = 0.008
    min_interior_angle_deg: float = 25.0
    max_interior_angle_deg: float = 165.0
    max_trim_segment_ratio: float = 0.42
    min_segment_length_em: float = 0.008
    collinear_tolerance_deg: float = 4.0


@dataclass(frozen=True)
class TerminalConfig:
    enabled: bool = True
    parallel_tolerance_deg: float = 12.0
    perpendicular_tolerance_deg: float = 18.0
    min_side_length_em: float = 0.045
    max_cap_chain_length: int = 5
    round_cap: bool = True


@dataclass(frozen=True)
class SpurConfig:
    enabled: bool = True
    report_only: bool = True
    min_flare_ratio: float = 1.12
    max_flare_depth_em: float = 0.055
    min_confidence_to_auto_apply: float = 0.98


@dataclass(frozen=True)
class CleanupConfig:
    enabled: bool = True
    max_point_growth_ratio: float = 3.0
    max_bbox_change_em: float = 0.08
    fail_on_self_intersection: bool = True


@dataclass(frozen=True)
class BuildConfig:
    strip_hinting: bool = True
    remove_dsig: bool = True
    fail_on_glyph_error: bool = True


@dataclass(frozen=True)
class ProjectConfig:
    font: FontConfig
    rounding: RoundingConfig = field(default_factory=RoundingConfig)
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    spur_detection: SpurConfig = field(default_factory=SpurConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    build: BuildConfig = field(default_factory=BuildConfig)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    return value


def load_config(path: Path) -> ProjectConfig:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    try:
        font = FontConfig(**_section(data, "font"))
        config = ProjectConfig(
            font=font,
            rounding=RoundingConfig(**_section(data, "rounding")),
            terminal=TerminalConfig(**_section(data, "terminal")),
            spur_detection=SpurConfig(**_section(data, "spur_detection")),
            cleanup=CleanupConfig(**_section(data, "cleanup")),
            build=BuildConfig(**_section(data, "build")),
        )
    except TypeError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
    if len(config.font.vendor_id) != 4:
        raise ConfigError("font.vendor_id must contain exactly four characters")
    if not 0 < config.rounding.max_trim_segment_ratio < 0.5:
        raise ConfigError("rounding.max_trim_segment_ratio must be between 0 and 0.5")
    return config


def load_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise ConfigError(f"override file does not exist: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("glyphs", {}), dict):
        raise ConfigError("overrides must contain a 'glyphs' mapping")
    result: dict[str, dict[str, Any]] = {}
    for glyph_key, value in raw.get("glyphs", {}).items():
        if not isinstance(glyph_key, str) or not isinstance(value, dict):
            raise ConfigError("each glyph override must be a mapping")
        operations = value.get("operations", [])
        if not isinstance(operations, list):
            raise ConfigError(f"{glyph_key}.operations must be a list")
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("type") not in {
                "apply_terminal_candidate",
                "skip_corner",
            }:
                raise ConfigError(f"{glyph_key} contains an unsupported operation")
        result[glyph_key] = value
    return result


def parse_glyphset(path: Path) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.split("#", 1)[0].strip()
        if not value:
            continue
        if value.startswith("U+"):
            try:
                value = chr(int(value[2:], 16))
            except (ValueError, OverflowError) as exc:
                raise ConfigError(f"{path}:{line_number}: invalid Unicode value") from exc
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
