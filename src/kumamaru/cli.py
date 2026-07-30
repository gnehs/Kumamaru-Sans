"""The ``kumamaru`` command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kumamaru.config import ConfigError, load_config, load_overrides, parse_glyphset
from kumamaru.pipeline import (
    PipelineError,
    analyze_font,
    build_font,
    inspect_font,
    proof_font,
    validate_fonts,
    write_report,
)
from kumamaru.raster_proof import (
    DEFAULT_PPEMS,
    RasterProofError,
    render_raster_proof,
)
from kumamaru.source_manifest import (
    SourceManifestError,
    inspect_glyphs_source,
    inspect_ibm_plex_sans_tc_source,
)
from kumamaru.source_rounding import (
    SourceRoundingDependencyError,
    SourceRoundingError,
    round_glyphs_source,
)


class ValidationFailed(RuntimeError):
    """Raised after writing a validation report that contains failing checks."""


DEFAULT_RASTER_PROOF_TEXT = (
    "一十口日田中永水心小國圓體鬱龜熊丸　熊丸體的圓角與收筆測試。ABC HOn o 0123456789 @%！？，。"
)


def build_parser() -> argparse.ArgumentParser:
    """Build the strict, discoverable command-line parser."""

    parser = argparse.ArgumentParser(
        prog="kumamaru",
        description="Conservative, auditable TrueType outline transformation tools.",
        allow_abbrev=False,
    )
    subcommands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    inspect_command = subcommands.add_parser("inspect", help="inspect a static TrueType font")
    inspect_command.add_argument("--input", required=True, type=Path, help="source .ttf file")
    inspect_command.add_argument("--output", required=True, type=Path, help="inspection JSON path")
    inspect_command.add_argument("--glyphs", type=Path, help="optional glyph set to check")
    inspect_command.set_defaults(handler=_handle_inspect)

    analyze_command = subcommands.add_parser(
        "analyze", help="analyze selected glyphs without writing a font"
    )
    _add_analysis_arguments(analyze_command)
    analyze_command.set_defaults(handler=_handle_analyze)

    build_command = subcommands.add_parser("build", help="build a targeted, unhinted output font")
    _add_analysis_arguments(build_command, include_output=False)
    build_command.add_argument("--output", required=True, type=Path, help="output .ttf file")
    build_command.add_argument("--overrides", type=Path, help="YAML glyph overrides")
    build_command.add_argument("--report", required=True, type=Path, help="build report JSON path")
    build_command.add_argument(
        "--dry-run", action="store_true", help="analyze and validate without writing output"
    )
    build_command.add_argument(
        "--strict-upstream-sha",
        "--strict-sha",
        dest="strict_upstream_sha",
        action="store_true",
        help="require input SHA-256 to match font.upstream_sha256",
    )
    build_command.add_argument(
        "--strict-overrides",
        action="store_true",
        help="fail if an override references an unknown glyph or candidate",
    )
    build_command.set_defaults(handler=_handle_build)

    proof_command = subcommands.add_parser("proof", help="render an offline HTML + SVG proof")
    proof_command.add_argument("--before", required=True, type=Path, help="original .ttf file")
    proof_command.add_argument("--after", required=True, type=Path, help="modified .ttf file")
    proof_command.add_argument("--glyphs", required=True, type=Path, help="glyph set file")
    proof_command.add_argument("--analysis", type=Path, help="analysis JSON path")
    proof_command.add_argument("--build-report", type=Path, help="build report JSON path")
    proof_command.add_argument("--output", required=True, type=Path, help="proof directory")
    proof_command.set_defaults(handler=_handle_proof)

    raster_proof_command = subcommands.add_parser(
        "raster-proof",
        help="render a FreeType low-PPEM PNG proof with hb-view",
    )
    raster_proof_command.add_argument("--font", required=True, type=Path, help="input .ttf file")
    raster_proof_command.add_argument("--output", required=True, type=Path, help="proof directory")
    raster_text = raster_proof_command.add_mutually_exclusive_group()
    raster_text.add_argument("--text", help="specimen text; defaults to the project hinting sample")
    raster_text.add_argument("--text-file", type=Path, help="UTF-8 specimen text file")
    raster_proof_command.add_argument(
        "--ppem",
        action="append",
        type=int,
        help="PPEM size; repeat to override the default low-PPEM matrix",
    )
    raster_proof_command.add_argument(
        "--variation",
        action="append",
        metavar="TAG=VALUE",
        help="variable-font location; repeat for each four-character axis tag",
    )
    raster_proof_command.add_argument(
        "--hb-view",
        default="hb-view",
        help="hb-view executable name or path (default: hb-view)",
    )
    raster_proof_command.set_defaults(handler=_handle_raster_proof)

    validate_command = subcommands.add_parser(
        "validate", help="validate table and shaping preservation"
    )
    validate_command.add_argument("--before", required=True, type=Path, help="original .ttf file")
    validate_command.add_argument("--after", required=True, type=Path, help="modified .ttf file")
    _add_glyph_selection_arguments(validate_command)
    validate_command.add_argument("--output", required=True, type=Path, help="validation JSON path")
    validate_command.set_defaults(handler=_handle_validate)

    source_inspect_command = subcommands.add_parser(
        "source-inspect",
        help="inspect Glyphs masters and interpolation compatibility",
    )
    source_inspect_command.add_argument("--input", required=True, type=Path)
    source_inspect_command.add_argument("--output", required=True, type=Path)
    source_inspect_command.add_argument("--glyphs", type=Path, help="optional glyph set to inspect")
    source_inspect_command.add_argument(
        "--expect-ibm-plex-sans-tc",
        action="store_true",
        help="require the pinned IBM Plex Sans TC source identity",
    )
    source_inspect_command.set_defaults(handler=_handle_source_inspect)

    source_round_command = subcommands.add_parser(
        "source-round",
        help="prototype compatible corner rounding across Glyphs masters",
    )
    source_round_command.add_argument("--input", required=True, type=Path)
    source_round_command.add_argument("--output", required=True, type=Path)
    source_round_selection = source_round_command.add_mutually_exclusive_group(required=True)
    source_round_selection.add_argument("--glyphs", type=Path, help="glyph set file")
    source_round_selection.add_argument(
        "--all-glyphs",
        action="store_true",
        help="round every exporting glyph in the Glyphs source",
    )
    source_round_command.add_argument("--report", required=True, type=Path)
    source_round_command.add_argument("--reference-master", default="Regular")
    source_round_command.add_argument(
        "--radius",
        required=True,
        action="append",
        metavar="MASTER=UNITS",
        help="repeat per master, or use '*=UNITS' as a fallback",
    )
    source_round_command.add_argument(
        "--inner-radius",
        action="append",
        metavar="MASTER=UNITS",
        help="optionally repeat per master to round eligible inner corners",
    )
    source_round_command.add_argument(
        "--max-segment-ratio",
        type=float,
        default=0.42,
        help="maximum fraction trimmed from either adjacent segment",
    )
    source_round_command.add_argument(
        "--family-name",
        default="Kumamaru Sans",
        help="non-reserved family name written to the derived source",
    )
    source_round_command.add_argument(
        "--normalize-ibm-plex-sans-tc",
        action="store_true",
        help="repair the published IBM source's weight-axis mappings before saving",
    )
    source_round_command.set_defaults(handler=_handle_source_round)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and return a conventional shell status code."""

    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        arguments.handler(arguments)
    except ValidationFailed as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return 1
    except (
        ConfigError,
        PipelineError,
        RasterProofError,
        SourceManifestError,
        SourceRoundingDependencyError,
        SourceRoundingError,
        OSError,
        ValueError,
    ) as exc:
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 2
    return 0


def _add_analysis_arguments(
    parser: argparse.ArgumentParser, *, include_output: bool = True
) -> None:
    parser.add_argument("--input", required=True, type=Path, help="source .ttf file")
    _add_glyph_selection_arguments(parser)
    parser.add_argument("--config", required=True, type=Path, help="TOML project configuration")
    if include_output:
        parser.add_argument("--output", required=True, type=Path, help="analysis JSON path")


def _add_glyph_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """Require one explicit, unambiguous source of glyph selections."""

    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--glyphs", type=Path, help="glyph set file")
    selection.add_argument(
        "--all-encoded-glyphs",
        action="store_true",
        help="select each unique glyph name in the font's best Unicode cmap",
    )


def _handle_inspect(arguments: argparse.Namespace) -> None:
    glyphs = parse_glyphset(arguments.glyphs) if arguments.glyphs else []
    write_report(arguments.output, inspect_font(arguments.input, glyph_tokens=glyphs))


def _handle_analyze(arguments: argparse.Namespace) -> None:
    config = load_config(arguments.config)
    report = analyze_font(
        arguments.input,
        parse_glyphset(arguments.glyphs) if arguments.glyphs else [],
        config,
        all_encoded_glyphs=arguments.all_encoded_glyphs,
    )
    write_report(arguments.output, report)


def _handle_build(arguments: argparse.Namespace) -> None:
    config = load_config(arguments.config)
    overrides: dict[str, dict[str, Any]] = (
        load_overrides(arguments.overrides) if arguments.overrides else {}
    )
    report = build_font(
        arguments.input,
        arguments.output,
        parse_glyphset(arguments.glyphs) if arguments.glyphs else [],
        config,
        overrides,
        dry_run=arguments.dry_run,
        strict_upstream_sha=arguments.strict_upstream_sha,
        strict_overrides=arguments.strict_overrides,
        all_encoded_glyphs=arguments.all_encoded_glyphs,
    )
    write_report(arguments.report, report)


def _handle_proof(arguments: argparse.Namespace) -> None:
    report = proof_font(
        arguments.before,
        arguments.after,
        parse_glyphset(arguments.glyphs),
        arguments.output,
        analysis_path=arguments.analysis,
        build_report_path=arguments.build_report,
    )
    # Proof's primary artefact is index.html.  Its short JSON summary is useful
    # on stdout in automation without introducing another required output flag.
    print(report["index"])


def _parse_variation_location(values: Sequence[str] | None) -> dict[str, float]:
    location: dict[str, float] = {}
    for entry in values or ():
        tag, separator, raw_value = entry.partition("=")
        tag = tag.strip()
        if not separator or not tag or not raw_value.strip():
            raise ValueError(f"invalid --variation {entry!r}; expected TAG=VALUE")
        if tag in location:
            raise ValueError(f"duplicate --variation for axis {tag!r}")
        try:
            location[tag] = float(raw_value)
        except ValueError as error:
            raise ValueError(
                f"invalid --variation value for axis {tag!r}: {raw_value!r}"
            ) from error
    return location


def _handle_raster_proof(arguments: argparse.Namespace) -> None:
    if arguments.text_file:
        text = arguments.text_file.read_text(encoding="utf-8")
    elif arguments.text is not None:
        text = arguments.text
    else:
        text = DEFAULT_RASTER_PROOF_TEXT
    summary = render_raster_proof(
        arguments.font,
        arguments.output,
        text,
        ppems=tuple(arguments.ppem) if arguments.ppem else DEFAULT_PPEMS,
        location=_parse_variation_location(arguments.variation),
        executable=arguments.hb_view,
    )
    print(summary.index)


def _handle_validate(arguments: argparse.Namespace) -> None:
    report = validate_fonts(
        arguments.before,
        arguments.after,
        parse_glyphset(arguments.glyphs) if arguments.glyphs else [],
        all_encoded_glyphs=arguments.all_encoded_glyphs,
    )
    write_report(arguments.output, report)
    if not bool(report.get("passed", False)):
        raise ValidationFailed(f"validation failed; see {arguments.output}")


def _handle_source_inspect(arguments: argparse.Namespace) -> None:
    glyphs = parse_glyphset(arguments.glyphs) if arguments.glyphs else []
    inspect = (
        inspect_ibm_plex_sans_tc_source
        if arguments.expect_ibm_plex_sans_tc
        else inspect_glyphs_source
    )
    report = inspect(arguments.input, selected_glyphs=glyphs)
    write_report(arguments.output, report)
    if arguments.expect_ibm_plex_sans_tc and not bool(report["source_gate"]["passed"]):
        raise ValidationFailed(f"source identity validation failed; see {arguments.output}")


def _parse_master_radii(
    values: Sequence[str], *, option_name: str = "--radius"
) -> dict[str, float]:
    radii: dict[str, float] = {}
    for value in values:
        master, separator, raw_radius = value.partition("=")
        master = master.strip()
        if not separator or not master or not raw_radius.strip():
            raise SourceRoundingError(f"invalid {option_name} {value!r}; expected MASTER=UNITS")
        if master in radii:
            raise SourceRoundingError(f"duplicate {option_name} for master {master!r}")
        try:
            radii[master] = float(raw_radius)
        except ValueError as exc:
            raise SourceRoundingError(
                f"invalid radius value for master {master!r}: {raw_radius!r}"
            ) from exc
    return radii


def _handle_source_round(arguments: argparse.Namespace) -> None:
    report = round_glyphs_source(
        arguments.input,
        arguments.output,
        parse_glyphset(arguments.glyphs) if arguments.glyphs else None,
        _parse_master_radii(arguments.radius),
        reference_master=arguments.reference_master,
        max_segment_ratio=arguments.max_segment_ratio,
        family_name=arguments.family_name,
        normalize_ibm_plex_sans_tc=arguments.normalize_ibm_plex_sans_tc,
        all_exporting_glyphs=arguments.all_glyphs,
        inner_radii_by_master=(
            _parse_master_radii(arguments.inner_radius, option_name="--inner-radius")
            if arguments.inner_radius
            else None
        ),
        compact_report=arguments.all_glyphs,
    )
    write_report(arguments.report, report)


if __name__ == "__main__":
    raise SystemExit(main())
