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


class ValidationFailed(RuntimeError):
    """Raised after writing a validation report that contains failing checks."""


def build_parser() -> argparse.ArgumentParser:
    """Build a strict, discoverable parser for the five public commands."""

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

    validate_command = subcommands.add_parser(
        "validate", help="validate table and shaping preservation"
    )
    validate_command.add_argument("--before", required=True, type=Path, help="original .ttf file")
    validate_command.add_argument("--after", required=True, type=Path, help="modified .ttf file")
    _add_glyph_selection_arguments(validate_command)
    validate_command.add_argument("--output", required=True, type=Path, help="validation JSON path")
    validate_command.set_defaults(handler=_handle_validate)
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
    except (ConfigError, PipelineError, OSError, ValueError) as exc:
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


if __name__ == "__main__":
    raise SystemExit(main())
