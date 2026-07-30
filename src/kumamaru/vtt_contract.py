"""Prepare and validate the Windows Visual TrueType hinting pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

COMPILED_HINT_TABLES = {"cvt ", "fpgm", "prep"}
DEFAULT_PILOT_TEXT = "日田國圓"
COMPOSITE_TRANSIENT_FLAGS = 0x0020 | 0x0100  # MORE_COMPONENTS | WE_HAVE_INSTRUCTIONS
SIMPLE_SEMANTIC_FLAGS = 0x01 | 0x40 | 0x80  # ON_CURVE | OVERLAP_SIMPLE | CUBIC
PRESERVED_VARIATION_TABLES = {"avar", "fvar", "gvar", "HVAR", "MVAR", "STAT", "VVAR"}


class VttContractError(ValueError):
    """Raised when a VTT pilot artifact violates the hinting contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _glyph_programs(font: TTFont) -> set[str]:
    glyf = font["glyf"]
    return {
        glyph_name
        for glyph_name in font.getGlyphOrder()
        if (
            (program := getattr(glyf[glyph_name], "program", None)) is not None
            and program.getBytecode()
        )
    }


def _vtt_source_tables(font: TTFont) -> list[str]:
    table_tags = set(font.keys())
    return sorted(table_tag for table_tag in table_tags if table_tag.startswith("TSI"))


def _pilot_glyphs(font: TTFont, pilot_text: str) -> dict[str, str]:
    cmap = font.getBestCmap() or {}
    missing = [character for character in pilot_text if ord(character) not in cmap]
    if missing:
        raise VttContractError(f"font is missing pilot characters: {missing}")
    return {character: cmap[ord(character)] for character in pilot_text}


def _glyph_fingerprint(font: TTFont, glyph_name: str) -> tuple[object, ...]:
    glyf = font["glyf"]
    glyph = glyf[glyph_name]
    if glyph.isComposite():
        components = tuple(
            (
                component.getComponentInfo(),
                getattr(component, "firstPt", None),
                getattr(component, "secondPt", None),
                getattr(component, "flags", 0) & ~COMPOSITE_TRANSIENT_FLAGS,
            )
            for component in glyph.components
        )
        return ("composite", components)
    coordinates, end_points, flags = glyph.getCoordinates(glyf)
    return (
        "simple",
        glyph.numberOfContours,
        tuple(tuple(point) for point in coordinates),
        tuple(end_points),
        tuple(flag & SIMPLE_SEMANTIC_FLAGS for flag in flags),
    )


def _validate_outline_compatibility(baseline: TTFont, candidate: TTFont) -> None:
    baseline_order = baseline.getGlyphOrder()
    if candidate.getGlyphOrder() != baseline_order:
        raise VttContractError("glyph order changed after the unhinted build")
    if (candidate.getBestCmap() or {}) != (baseline.getBestCmap() or {}):
        raise VttContractError("cmap changed after the unhinted build")
    if candidate["head"].unitsPerEm != baseline["head"].unitsPerEm:
        raise VttContractError("unitsPerEm changed after the unhinted build")
    if candidate["hmtx"].metrics != baseline["hmtx"].metrics:
        raise VttContractError("horizontal metrics changed after the unhinted build")
    if ("vmtx" in candidate) != ("vmtx" in baseline):
        raise VttContractError("vertical metrics table presence changed after the unhinted build")
    if "vmtx" in baseline and candidate["vmtx"].metrics != baseline["vmtx"].metrics:
        raise VttContractError("vertical metrics changed after the unhinted build")

    for table_tag in sorted(PRESERVED_VARIATION_TABLES):
        if (table_tag in candidate) != (table_tag in baseline):
            raise VttContractError(f"{table_tag} table presence changed after the unhinted build")
        if table_tag in baseline and candidate.getTableData(table_tag) != baseline.getTableData(
            table_tag
        ):
            raise VttContractError(f"{table_tag} table changed after the unhinted build")

    changed = [
        glyph_name
        for glyph_name in baseline_order
        if _glyph_fingerprint(candidate, glyph_name) != _glyph_fingerprint(baseline, glyph_name)
    ]
    if changed:
        preview = changed[:20]
        suffix = "" if len(changed) <= 20 else f" (+{len(changed) - 20} more)"
        raise VttContractError(f"glyph outlines or point order changed: {preview}{suffix}")


def _validate_unhinted_baseline(font: TTFont) -> None:
    tables = sorted(
        set(font.keys()) & (COMPILED_HINT_TABLES | {"cvar"}) | set(_vtt_source_tables(font))
    )
    instructed = sorted(_glyph_programs(font))
    if tables or instructed:
        raise VttContractError(
            f"VTT baseline must be unhinted; tables={tables}, instructed_glyphs={instructed[:20]}"
        )


def prepare_vtt_workspace(
    input_font: Path,
    output_dir: Path,
    *,
    pilot_text: str = DEFAULT_PILOT_TEXT,
) -> dict[str, Any]:
    """Copy an unhinted variable font into a traceable VTT editing workspace."""

    if not input_font.is_file():
        raise VttContractError(f"missing input font: {input_font}")
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_font = output_dir / "KumamaruSans-wght-VTT-source.ttf"

    with TTFont(input_font, lazy=False) as font:
        if "glyf" not in font or "fvar" not in font or "gvar" not in font:
            raise VttContractError("VTT pilot input must be a TrueType variable font")
        _validate_unhinted_baseline(font)
        pilot_glyphs = _pilot_glyphs(font, pilot_text)
        axes = {
            axis.axisTag: {
                "min": axis.minValue,
                "default": axis.defaultValue,
                "max": axis.maxValue,
            }
            for axis in font["fvar"].axes
        }

    shutil.copyfile(input_font, workspace_font)
    manifest: dict[str, Any] = {
        "schema": 1,
        "stage": "unhinted-vtt-input",
        "font": workspace_font.name,
        "sha256": _sha256(workspace_font),
        "pilot_text": pilot_text,
        "pilot_glyphs": pilot_glyphs,
        "axes": axes,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "PILOT.txt").write_text(pilot_text + "\n", encoding="utf-8")
    return manifest


def validate_vtt_artifact(
    baseline_path: Path,
    candidate_path: Path,
    *,
    stage: str,
    pilot_text: str = DEFAULT_PILOT_TEXT,
) -> dict[str, Any]:
    """Validate an editable VTT source font or a compiled, source-stripped output."""

    if stage not in {"source", "compiled"}:
        raise VttContractError(f"unsupported VTT stage: {stage}")
    with (
        TTFont(baseline_path, lazy=False) as baseline,
        TTFont(candidate_path, lazy=False) as candidate,
    ):
        _validate_unhinted_baseline(baseline)
        _validate_outline_compatibility(baseline, candidate)
        pilot_glyphs = _pilot_glyphs(candidate, pilot_text)
        tables = set(candidate.keys())
        source_tables = _vtt_source_tables(candidate)
        instructed = _glyph_programs(candidate)

        if stage == "source":
            if not source_tables:
                raise VttContractError("editable VTT source font has no TSI source tables")
        else:
            missing_tables = sorted(COMPILED_HINT_TABLES - tables)
            if missing_tables:
                raise VttContractError(f"compiled VTT font is missing tables: {missing_tables}")
            if source_tables:
                raise VttContractError(
                    f"compiled VTT delivery font still contains source tables: {source_tables}"
                )
            missing_pilot_hints = [
                character
                for character, glyph_name in pilot_glyphs.items()
                if glyph_name not in instructed
            ]
            if missing_pilot_hints:
                raise VttContractError(
                    f"compiled VTT font has no glyph instructions for: {missing_pilot_hints}"
                )
            if "fvar" in candidate and "cvar" not in candidate:
                raise VttContractError("compiled VTT variable font is missing cvar")

        return {
            "schema": 1,
            "stage": stage,
            "baseline_sha256": _sha256(baseline_path),
            "font_sha256": _sha256(candidate_path),
            "pilot_text": pilot_text,
            "pilot_glyphs": pilot_glyphs,
            "source_tables": source_tables,
            "compiled_hint_tables": sorted(tables & COMPILED_HINT_TABLES),
            "cvar": "cvar" in tables,
            "instructed_glyphs": len(instructed),
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    prepare = subcommands.add_parser("prepare", help="prepare an unhinted VTT workspace")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--pilot-text", default=DEFAULT_PILOT_TEXT)

    validate = subcommands.add_parser("validate", help="validate a VTT source or compiled font")
    validate.add_argument("--baseline", type=Path, required=True)
    validate.add_argument("--font", type=Path, required=True)
    validate.add_argument("--stage", choices=("source", "compiled"), required=True)
    validate.add_argument("--pilot-text", default=DEFAULT_PILOT_TEXT)
    validate.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            report = prepare_vtt_workspace(args.input, args.output, pilot_text=args.pilot_text)
        else:
            report = validate_vtt_artifact(
                args.baseline,
                args.font,
                stage=args.stage,
                pilot_text=args.pilot_text,
            )
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except VttContractError as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
