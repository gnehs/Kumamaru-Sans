"""Command orchestration for the Kumamaru Sans MVP.

This module deliberately keeps command concerns (paths, reports, validation of
inputs and error messages) outside the outline algorithms.  Geometry modules
can therefore be exercised in isolation while the CLI has one predictable
place to turn their results into stable JSON artefacts.
"""

from __future__ import annotations

import hashlib
import inspect
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from fontTools.pens.recordingPen import DecomposingRecordingPen  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]

from kumamaru.config import ProjectConfig, RoundingConfig
from kumamaru.report import read_json, write_json


class PipelineError(RuntimeError):
    """A user-facing failure in one of the command workflows."""


REQUIRED_TTF_TABLES = frozenset(
    {"glyf", "loca", "cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2"}
)
HINTING_TABLES = ("cvt ", "fpgm", "prep")


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 digest without loading a font into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_font(
    input_path: str | Path,
    *,
    glyph_tokens: Sequence[str] = (),
) -> dict[str, Any]:
    """Inspect a static TrueType font and return only JSON-compatible data."""

    # Keep inspection details (including exact glyph-program counts) in the
    # font I/O boundary; this wrapper supplies the CLI's consistent errors.
    from kumamaru.font_io import FontFormatError
    from kumamaru.font_io import inspect_font as inspect_source_font

    source = _existing_file(input_path, "input font")
    try:
        return inspect_source_font(source, smoke_glyphs=glyph_tokens)
    except (TTLibError, FontFormatError) as exc:
        raise PipelineError(f"cannot read font '{source}': {exc}") from exc


def analyze_font(
    input_path: str | Path,
    glyph_tokens: Sequence[str],
    config: ProjectConfig,
    *,
    all_encoded_glyphs: bool = False,
) -> dict[str, Any]:
    """Analyze selected outlines without changing the source font.

    The geometry implementation publishes an ``analyze_glyph`` callable.  The
    small fallback below keeps the command useful while a font contains glyphs
    which the conservative analyzer intentionally declines to process.
    """

    source = _existing_file(input_path, "input font")
    inspection = inspect_font(source, glyph_tokens=glyph_tokens)
    entries: list[dict[str, Any]] = []
    try:
        with TTFont(source, lazy=False) as font:
            _require_static_truetype(font, source)
            targets = _resolve_glyph_names(
                font, glyph_tokens, all_encoded_glyphs=all_encoded_glyphs
            )
            for token, glyph_name in targets.items():
                if glyph_name is None:
                    entries.append(_missing_analysis(token))
                    continue
                try:
                    entries.append(
                        _analyze_outline(font, glyph_name, token, config, inspection["sha256"])
                    )
                except Exception as exc:  # geometry failures must be auditable, not silent
                    entries.append(_basic_analysis(font, glyph_name, token, error=str(exc)))
    except TTLibError as exc:
        raise PipelineError(f"cannot read font '{source}': {exc}") from exc
    return {
        "command": "analyze",
        "input": str(source),
        "input_sha256": inspection["sha256"],
        "config": _config_summary(config),
        "glyphs": entries,
        "warnings": [entry for entry in entries if entry.get("status") != "ok"],
        "errors": [],
    }


def build_font(
    input_path: str | Path,
    output_path: str | Path,
    glyph_tokens: Sequence[str],
    config: ProjectConfig,
    overrides: Mapping[str, Mapping[str, Any]],
    *,
    dry_run: bool = False,
    strict_upstream_sha: bool = False,
    strict_overrides: bool = False,
    all_encoded_glyphs: bool = False,
) -> dict[str, Any]:
    """Run the targeted build through the font-core implementation.

    ``build_targeted_font`` is intentionally discovered late: installing the
    package and using ``inspect`` must not require optional geometry support.
    The build refuses to write a misleading unmodified font if that core is not
    available.
    """

    source = _existing_file(input_path, "input font")
    digest = sha256_file(source)
    _verify_upstream_sha(config, digest, strict_upstream_sha)
    selected_tokens = glyph_tokens
    analysis: dict[str, Any] | None = None
    if all_encoded_glyphs:
        try:
            with TTFont(source, lazy=False) as font:
                _require_static_truetype(font, source)
                selected_tokens = list(
                    _resolve_glyph_names(font, glyph_tokens, all_encoded_glyphs=True).keys()
                )
        except TTLibError as exc:
            raise PipelineError(f"cannot read font '{source}': {exc}") from exc
    else:
        analysis = analyze_font(source, glyph_tokens, config)
        errors = [entry for entry in analysis["glyphs"] if entry.get("status") == "missing"]
        if errors and (strict_overrides or config.build.fail_on_glyph_error):
            raise PipelineError("one or more requested glyphs are absent from the input font")

    destination = Path(output_path)
    result = _build_outlines(
        source,
        destination,
        selected_tokens,
        config,
        overrides,
        dry_run=dry_run,
        strict_overrides=strict_overrides,
        source_sha256=digest,
        compact_report=all_encoded_glyphs,
    )
    report = dict(result)
    report.update(
        {
            "command": "build",
            "input": str(source),
            "input_sha256": digest,
            "output": str(destination),
            "dry_run": dry_run,
            "strict_upstream_sha": strict_upstream_sha or config.font.strict_upstream_sha,
            "strict_overrides": strict_overrides,
        }
    )
    if analysis is None:
        report["selection"] = {
            "mode": "all_encoded_glyphs",
            "glyph_count": len(selected_tokens),
        }
    else:
        report["analysis"] = analysis
    return report


def proof_font(
    before: str | Path,
    after: str | Path,
    glyph_tokens: Sequence[str],
    output_dir: str | Path,
    *,
    analysis_path: str | Path | None = None,
    build_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Render offline proof assets after resolving characters to glyph names."""

    from kumamaru.render import render_proof

    before_path = _existing_file(before, "before font")
    after_path = _existing_file(after, "after font")
    try:
        with TTFont(before_path, lazy=False) as font:
            _require_static_truetype(font, before_path)
            names = _resolve_glyph_names(font, glyph_tokens)
    except TTLibError as exc:
        raise PipelineError(f"cannot read before font '{before_path}': {exc}") from exc
    missing = [token for token, name in names.items() if name is None]
    if missing:
        raise PipelineError(f"requested glyphs are absent from before font: {', '.join(missing)}")
    analysis = read_json(analysis_path) if analysis_path is not None else None
    build_report = read_json(build_report_path) if build_report_path is not None else None
    glyph_names = [name for name in names.values() if name is not None]
    summary = render_proof(before_path, after_path, glyph_names, output_dir, analysis, build_report)
    return {
        "command": "proof",
        "before": str(before_path),
        "after": str(after_path),
        "output": str(Path(output_dir)),
        "index": str(summary.index),
        "glyph_count": summary.glyph_count,
        "candidate_count": summary.candidate_count,
        "warning_count": summary.warning_count,
    }


def validate_fonts(
    before: str | Path,
    after: str | Path,
    glyph_tokens: Sequence[str],
    *,
    all_encoded_glyphs: bool = False,
) -> dict[str, Any]:
    """Call the validator, with a useful failure when it is not installed."""

    before_path = _existing_file(before, "before font")
    after_path = _existing_file(after, "after font")
    from kumamaru.validate import validate_fonts as validate

    with TTFont(before_path, lazy=False) as font:
        names = _resolve_glyph_names(font, glyph_tokens, all_encoded_glyphs=all_encoded_glyphs)
    missing = [token for token, glyph_name in names.items() if glyph_name is None]
    if missing:
        raise PipelineError(f"requested glyphs are absent from before font: {', '.join(missing)}")
    modified_glyphs = [name for name in names.values() if name is not None]
    result = validate(
        before_path,
        after_path,
        modified_glyphs=modified_glyphs,
        boundary_subdivisions=4 if all_encoded_glyphs else 8,
        boundary_max_samples=256 if all_encoded_glyphs else None,
    )
    report = dict(result)
    report.setdefault("command", "validate")
    report.setdefault("before", str(before_path))
    report.setdefault("after", str(after_path))
    return report


def write_report(path: str | Path, report: Mapping[str, Any]) -> None:
    """Shared report boundary used by CLI handlers and direct API callers."""

    write_json(path, report)


def _existing_file(path: str | Path, label: str) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise PipelineError(f"{label} does not exist: {resolved}")
    return resolved


def _require_static_truetype(font: TTFont, source: Path) -> None:
    if "glyf" not in font:
        raise PipelineError(f"'{source}' is not a TrueType glyf font (missing 'glyf' table)")
    unsupported = [tag for tag in ("CFF ", "CFF2", "fvar") if tag in font]
    if unsupported:
        raise PipelineError(
            f"'{source}' is not a supported static TTF "
            f"(unsupported tables: {', '.join(unsupported)})"
        )


def _sfnt_flavor(font: TTFont) -> str:
    flavor = font.flavor
    if flavor is None:
        return "TrueType"
    return str(flavor)


def _font_names(font: TTFont) -> dict[str, str]:
    names = font["name"]
    return {
        "family": names.getDebugName(1) or "",
        "subfamily": names.getDebugName(2) or "",
        "full_name": names.getDebugName(4) or "",
        "postscript_name": names.getDebugName(6) or "",
    }


def _resolve_glyph_names(
    font: TTFont,
    tokens: Iterable[str],
    *,
    all_encoded_glyphs: bool = False,
) -> dict[str, str | None]:
    """Resolve explicit tokens or every uniquely encoded best-cmap glyph.

    ``TTFont.getBestCmap()`` maps Unicode code points to glyph names. Several
    code points may intentionally resolve to one glyph, so all-cmap selection
    preserves the cmap's order while deduplicating its glyph-name values.
    """

    requested_tokens = tuple(tokens)
    if all_encoded_glyphs:
        if requested_tokens:
            raise PipelineError("--glyphs and --all-encoded-glyphs cannot be combined")
        glyph_names = dict.fromkeys((font.getBestCmap() or {}).values())
        if not glyph_names:
            raise PipelineError("input font has no encoded glyphs in its best cmap")
        return {glyph_name: glyph_name for glyph_name in glyph_names}

    cmap = font.getBestCmap() or {}
    glyph_set = set(font.getGlyphOrder())
    result: dict[str, str | None] = {}
    for token in requested_tokens:
        if token in glyph_set:
            result[token] = token
        elif len(token) == 1:
            result[token] = cmap.get(ord(token))
        else:
            result[token] = None
    return result


def _basic_analysis(
    font: TTFont, glyph_name: str, token: str, error: str | None = None
) -> dict[str, Any]:
    glyph = font["glyf"][glyph_name]
    recording = DecomposingRecordingPen(font.getGlyphSet())
    font.getGlyphSet()[glyph_name].draw(recording)
    contours = sum(operator == "moveTo" for operator, _ in recording.value)
    line_segments = sum(operator == "lineTo" for operator, _ in recording.value)
    quadratic_segments = sum(operator == "qCurveTo" for operator, _ in recording.value)
    entry: dict[str, Any] = {
        "token": token,
        "glyph_name": glyph_name,
        "status": "ok" if error is None else "warning",
        "is_composite": bool(glyph.isComposite()),
        "contour_count": contours,
        "line_segment_count": line_segments,
        "quadratic_segment_count": quadratic_segments,
        "corner_candidates": [],
        "terminal_candidates": [],
        "spur_candidates": [],
        "skipped": [],
    }
    if error is not None:
        entry["skipped"] = [{"reason": "analyzer_error", "detail": error}]
    return entry


def _decomposed_point_count(font: TTFont, glyph_name: str) -> int:
    recording = DecomposingRecordingPen(font.getGlyphSet())
    font.getGlyphSet()[glyph_name].draw(recording)
    return sum(
        1
        for _operation, arguments in recording.value
        for argument in arguments
        if isinstance(argument, tuple)
        and len(argument) == 2
        and all(isinstance(value, (float, int)) for value in argument)
    )


def _analyze_outline(
    font: TTFont,
    glyph_name: str,
    token: str,
    config: ProjectConfig,
    source_sha256: str,
) -> dict[str, Any]:
    """Convert one glyph into the shared model and collect available filters."""

    from kumamaru.filters.corner_rounding import analyze_corner_candidates
    from kumamaru.geometry.contour import glyph_to_outline

    glyph_set = font.getGlyphSet()
    outline = glyph_to_outline(
        glyph_set[glyph_name],
        glyph_name=glyph_name,
        width=font["hmtx"][glyph_name][0],
        glyph_set=glyph_set,
    )
    corners = analyze_corner_candidates(
        outline,
        config.rounding,
        upm=font["head"].unitsPerEm,
        source_sha256=source_sha256,
    )
    terminal_result = _optional_filter_analysis(
        "kumamaru.filters.terminal_rounding",
        ("analyze_terminal_candidates", "analyze_terminals"),
        outline,
        config.terminal,
        upm=font["head"].unitsPerEm,
        source_sha256=source_sha256,
    )
    from kumamaru.filters.spur_detection import detect_spur_candidates

    spur_result = detect_spur_candidates(
        outline,
        terminal_result.candidates if terminal_result is not None else (),
        config.spur_detection,
        upm=font["head"].unitsPerEm,
        source_sha256=source_sha256,
    )
    return {
        "token": token,
        "glyph_name": glyph_name,
        "status": "ok",
        "is_composite": bool(font["glyf"][glyph_name].isComposite()),
        "contour_count": len(outline.contours),
        "line_segment_count": sum(
            type(segment).__name__ == "LineSegment"
            for contour in outline.contours
            for segment in contour.segments
        ),
        "quadratic_segment_count": sum(
            type(segment).__name__ == "QuadraticSegment"
            for contour in outline.contours
            for segment in contour.segments
        ),
        "corner_candidates": [_candidate_dict(candidate) for candidate in corners.candidates],
        "terminal_candidates": _result_candidates(terminal_result),
        "spur_candidates": _result_candidates(spur_result),
        "skipped": [item.to_dict() for item in corners.skipped]
        + _result_skipped(terminal_result)
        + _result_skipped(spur_result),
        "warnings": list(corners.warnings)
        + _result_warnings(terminal_result)
        + _result_warnings(spur_result),
    }


def _build_outlines(
    source: Path,
    destination: Path,
    glyph_tokens: Sequence[str],
    config: ProjectConfig,
    overrides: Mapping[str, Mapping[str, Any]],
    *,
    dry_run: bool,
    strict_overrides: bool,
    source_sha256: str,
    compact_report: bool = False,
) -> dict[str, Any]:
    """Apply currently-supported transformations, then metadata and dehinting."""

    from kumamaru.filters.cleanup import cleanup_outline
    from kumamaru.filters.corner_rounding import round_line_corners
    from kumamaru.filters.spur_detection import auto_apply_candidate_ids, detect_spur_candidates
    from kumamaru.filters.terminal_rounding import (
        analyze_terminal_candidates,
        apply_terminal_candidates,
        auto_round_cap_candidate_ids,
    )
    from kumamaru.font_io import load_font, remove_dsig, save_font, strip_hinting
    from kumamaru.geometry.contour import glyph_to_outline, outline_to_glyph
    from kumamaru.geometry.safety import symmetric_boundary_deviation, topology_signature
    from kumamaru.metadata import apply_metadata

    transformed: list[dict[str, Any]] = []
    override_warnings: list[dict[str, str]] = []
    instructions_removed_during_rebuild = 0
    with load_font(source, lazy=False) as font:
        _validate_override_glyphs(font, overrides, override_warnings)
        targets = _resolve_glyph_names(font, glyph_tokens)
        glyph_set = font.getGlyphSet()
        unicode_by_glyph = {
            glyph_name: chr(codepoint)
            for codepoint, glyph_name in reversed(sorted((font.getBestCmap() or {}).items()))
        }
        for token, glyph_name in targets.items():
            if glyph_name is None:
                continue
            override = _override_for(
                token,
                glyph_name,
                overrides,
                unicode_token=unicode_by_glyph.get(glyph_name),
            )
            if override is None:
                override = {}
            original_is_composite = bool(font["glyf"][glyph_name].isComposite())
            if bool(override.get("skip", False)):
                if compact_report:
                    transformed.append(
                        {
                            "glyph_name": glyph_name,
                            "token": token,
                            "is_composite": original_is_composite,
                            "applied_candidate_ids": [],
                            "warnings": ["skipped by override"],
                            "safety": None,
                        }
                    )
                else:
                    transformed.append({"glyph_name": glyph_name, "status": "skipped_by_override"})
                continue
            skip_corners, requested_terminal_ids = _override_operations(
                override, glyph_name, strict_overrides, override_warnings
            )
            local_rounding = _rounding_config(config.rounding, override)
            outline = glyph_to_outline(
                glyph_set[glyph_name],
                glyph_name=glyph_name,
                width=font["hmtx"][glyph_name][0],
                glyph_set=glyph_set,
            )
            terminal_analysis = analyze_terminal_candidates(
                outline,
                config.terminal,
                upm=font["head"].unitsPerEm,
                source_sha256=source_sha256,
            )
            spur_analysis = detect_spur_candidates(
                outline,
                terminal_analysis.candidates,
                config.spur_detection,
                upm=font["head"].unitsPerEm,
                source_sha256=source_sha256,
            )
            all_terminal_candidates = terminal_analysis.candidates + spur_analysis.candidates
            automatic_terminal_ids = (
                set()
                if bool(override.get("disable_terminal_rounding", False))
                else auto_round_cap_candidate_ids(
                    terminal_analysis.candidates,
                    config.terminal,
                    maximum_flare_ratio=config.spur_detection.min_flare_ratio,
                )
            )
            automatic_spur_ids = (
                set()
                if bool(override.get("disable_spur_removal", False))
                else auto_apply_candidate_ids(spur_analysis.candidates, config.spur_detection)
            )
            selected_terminal_ids = (
                requested_terminal_ids | automatic_terminal_ids | automatic_spur_ids
            )
            terminal_result = apply_terminal_candidates(
                outline, all_terminal_candidates, selected_terminal_ids
            )
            if terminal_result.warnings:
                for warning in terminal_result.warnings:
                    override_warnings.append({"glyph_name": glyph_name, "message": warning})
            result = round_line_corners(
                terminal_result.outline,
                local_rounding,
                upm=font["head"].unitsPerEm,
                source_sha256=source_sha256,
                skip_corners=skip_corners,
            )
            cleanup_result = cleanup_outline(
                result.outline,
                config.cleanup,
                upm=font["head"].unitsPerEm,
            )
            cleanup_warnings = list(cleanup_result.warnings)
            if result.warnings and config.build.fail_on_glyph_error:
                raise PipelineError(
                    f"cannot safely transform {glyph_name}: {'; '.join(result.warnings)}"
                )
            applied_candidate_ids = list(terminal_result.applied_candidate_ids) + list(
                result.applied_candidate_ids
            )
            final_outline = cleanup_result.outline
            maximum_deviation = config.cleanup.max_bbox_change_em * font["head"].unitsPerEm
            rebuilt_glyph: Any | None = None
            original_point_count: int | None = None
            rebuilt_point_count: int | None = None
            if compact_report:
                applied_candidates = {
                    candidate.candidate_id: candidate
                    for candidate in all_terminal_candidates + result.candidates
                }
                selected_candidates = [
                    applied_candidates[candidate_id]
                    for candidate_id in applied_candidate_ids
                    if candidate_id in applied_candidates
                ]
                boundary_deviation = max(
                    map(_candidate_edit_bound, selected_candidates),
                    default=0.0,
                )
                boundary_measurement = "candidate_bound"
                if (
                    applied_candidate_ids
                    and max(
                        map(_candidate_screening_bound, selected_candidates),
                        default=0.0,
                    )
                    > maximum_deviation
                ):
                    rebuilt_glyph = outline_to_glyph(final_outline)
                    original_glyph = font["glyf"][glyph_name]
                    original_point_count = _decomposed_point_count(font, glyph_name)
                    font["glyf"][glyph_name] = rebuilt_glyph
                    try:
                        rebuilt_glyph.recalcBounds(font["glyf"])
                        rebuilt_point_count = _decomposed_point_count(font, glyph_name)
                        serialized_outline = glyph_to_outline(
                            glyph_set[glyph_name],
                            glyph_name=glyph_name,
                            width=font["hmtx"][glyph_name][0],
                            glyph_set=glyph_set,
                        )
                    finally:
                        font["glyf"][glyph_name] = original_glyph
                    boundary_deviation = symmetric_boundary_deviation(
                        outline,
                        serialized_outline,
                        subdivisions=4,
                        max_samples=256,
                    )
                    boundary_measurement = "serialized_sampled_hausdorff"
            else:
                boundary_deviation = symmetric_boundary_deviation(outline, final_outline)
                boundary_measurement = "sampled_hausdorff"
            before_topology = topology_signature(outline)
            after_topology = topology_signature(final_outline)
            if applied_candidate_ids and (
                not math.isfinite(boundary_deviation)
                or boundary_deviation > maximum_deviation
                or before_topology != after_topology
            ):
                cleanup_warnings.append(
                    "transformation rolled back: source-relative safety check failed "
                    f"(boundary deviation {boundary_deviation:.3f}/{maximum_deviation:g}, "
                    f"topology {before_topology} -> {after_topology})"
                )
                applied_candidate_ids = []
            if applied_candidate_ids:
                if rebuilt_glyph is None:
                    rebuilt_glyph = outline_to_glyph(final_outline)
                original_glyph = font["glyf"][glyph_name]
                if original_point_count is None or rebuilt_point_count is None:
                    original_point_count = _decomposed_point_count(font, glyph_name)
                    font["glyf"][glyph_name] = rebuilt_glyph
                    try:
                        rebuilt_glyph.recalcBounds(font["glyf"])
                        rebuilt_point_count = _decomposed_point_count(font, glyph_name)
                    finally:
                        font["glyf"][glyph_name] = original_glyph
                point_limit = max(
                    1,
                    int(original_point_count * config.cleanup.max_point_growth_ratio),
                )
                if rebuilt_point_count > point_limit:
                    cleanup_warnings.append(
                        "transformation rolled back: source-relative point growth "
                        f"{original_point_count} -> {rebuilt_point_count} exceeds {point_limit}"
                    )
                    applied_candidate_ids = []
                else:
                    original_program = getattr(font["glyf"][glyph_name], "program", None)
                    if original_program is not None and original_program.getBytecode():
                        instructions_removed_during_rebuild += 1
                    font["glyf"][glyph_name] = rebuilt_glyph
                    rebuilt_glyph.recalcBounds(font["glyf"])
            transformed_entry: dict[str, Any] = {
                "glyph_name": glyph_name,
                "token": token,
                "is_composite": original_is_composite,
                "applied_candidate_ids": applied_candidate_ids,
                "warnings": list(terminal_result.warnings)
                + list(result.warnings)
                + cleanup_warnings,
                "safety": {
                    "boundary_deviation": round(boundary_deviation, 6),
                    "boundary_limit": maximum_deviation,
                    "boundary_measurement": boundary_measurement,
                    "topology_before": list(before_topology),
                    "topology_after": list(after_topology),
                },
            }
            if not compact_report:
                transformed_entry.update(
                    {
                        "corner_candidates": [
                            _candidate_dict(candidate) for candidate in result.candidates
                        ],
                        "terminal_candidates": [
                            _candidate_dict(candidate) for candidate in terminal_analysis.candidates
                        ],
                        "spur_candidates": [
                            _candidate_dict(candidate) for candidate in spur_analysis.candidates
                        ],
                        "skipped": [item.to_dict() for item in terminal_result.skipped]
                        + [item.to_dict() for item in result.skipped],
                    }
                )
            transformed.append(transformed_entry)
        if strict_overrides and override_warnings:
            raise PipelineError(override_warnings[0]["message"])
        metadata = apply_metadata(font, config.font)
        hinting: dict[str, Any] = (
            strip_hinting(font) if config.build.strip_hinting else {"unhinted": False}
        )
        if config.build.strip_hinting:
            hinting["glyph_instructions_removed"] += instructions_removed_during_rebuild
        dsig_removed = remove_dsig(font) if config.build.remove_dsig else False
        if not dry_run:
            save_font(font, destination)
    return {
        "output_written": not dry_run,
        "modified_glyphs": [
            item["glyph_name"] for item in transformed if item.get("applied_candidate_ids")
        ],
        "glyphs": transformed,
        "metadata": metadata,
        "hinting": hinting,
        "dsig_removed": dsig_removed,
        "override_warnings": override_warnings,
        "known_limitations": [
            "Terminal/spur rebuilding requires a local all-line cap and shaft chain; unrelated "
            "quadratic segments in the same closed contour are preserved."
        ],
    }


def _override_for(
    token: str,
    glyph_name: str,
    overrides: Mapping[str, Mapping[str, Any]],
    *,
    unicode_token: str | None = None,
) -> Mapping[str, Any] | None:
    character = token if len(token) == 1 else unicode_token
    unicode_key = f"U+{ord(character):04X}" if character is not None else ""
    for key in (token, character, unicode_key, glyph_name):
        if key and key in overrides:
            return overrides[key]
    return None


def _validate_override_glyphs(
    font: TTFont,
    overrides: Mapping[str, Mapping[str, Any]],
    warnings: list[dict[str, str]],
) -> None:
    """Report override keys that cannot possibly select a glyph in this font."""

    cmap = font.getBestCmap() or {}
    glyph_names = set(font.getGlyphOrder())
    for key in overrides:
        glyph_name: str | None
        if key.startswith(("U+", "u+")):
            try:
                glyph_name = cmap.get(int(key[2:], 16))
            except ValueError:
                glyph_name = None
        elif len(key) == 1:
            glyph_name = cmap.get(ord(key))
        else:
            glyph_name = key if key in glyph_names else None
        if glyph_name is None:
            warnings.append(
                {"glyph_name": key, "message": "override glyph does not exist in input font"}
            )


def _override_operations(
    override: Mapping[str, Any],
    glyph_name: str,
    strict: bool,
    warnings: list[dict[str, str]],
) -> tuple[set[tuple[int, int]], set[str]]:
    targets: set[tuple[int, int]] = set()
    terminal_ids: set[str] = set()
    for operation in override.get("operations", []):
        if operation.get("type") == "skip_corner":
            contour, segment = operation.get("contour"), operation.get("segment")
            if isinstance(contour, int) and isinstance(segment, int):
                targets.add((contour, segment))
            else:
                warnings.append(
                    {
                        "glyph_name": glyph_name,
                        "message": "skip_corner override requires integer contour and segment",
                    }
                )
        elif operation.get("type") == "apply_terminal_candidate":
            candidate_id = operation.get("candidate_id")
            if isinstance(candidate_id, str) and candidate_id:
                terminal_ids.add(candidate_id)
            else:
                warnings.append(
                    {
                        "glyph_name": glyph_name,
                        "message": "apply_terminal_candidate override requires candidate_id",
                    }
                )
    return targets, terminal_ids


def _rounding_config(base: RoundingConfig, override: Mapping[str, Any]) -> RoundingConfig:
    """Use a tiny proxy so only documented per-glyph radii are overridden."""

    from dataclasses import replace

    fields = {
        name: override[name] for name in ("outer_radius_em", "inner_radius_em") if name in override
    }
    return replace(base, **fields) if fields else base


def _candidate_dict(candidate: Any) -> dict[str, Any]:
    value = cast(dict[str, Any], candidate.to_dict())
    point = value.get("point")
    if isinstance(point, dict):
        value["point"] = point
    return value


def _candidate_edit_bound(candidate: Any) -> float:
    """Return a conservative source-boundary deviation for compact full builds."""

    geometry = candidate.geometry
    if candidate.kind in {"terminal", "spur"}:
        return max(
            float(geometry.get("shaft_width", 0.0)) / 2.0,
            float(geometry.get("flare_depth", 0.0)),
        )
    trim_distance = float(geometry.get("trim_distance", 0.0))
    interior_angle = float(geometry.get("interior_angle_deg", 0.0))
    if not 0.0 < interior_angle < 180.0:
        return max(float(geometry.get("radius", 0.0)), trim_distance)
    # The replacement quadratic runs from equally trimmed points with the
    # original corner as its control. Its farthest source-boundary deviation
    # is the corner-to-midpoint distance, not the much longer trim distance.
    return trim_distance * math.cos(math.radians(interior_angle) / 2.0) / 2.0


def _candidate_screening_bound(candidate: Any) -> float:
    """Flag edits whose serialized source-relative deviation needs sampling."""

    if candidate.kind in {"terminal", "spur"}:
        return _candidate_edit_bound(candidate)
    geometry = candidate.geometry
    return max(
        float(geometry.get("radius", 0.0)),
        float(geometry.get("trim_distance", 0.0)),
    )


def _optional_filter_analysis(
    module_name: str,
    names: Sequence[str],
    outline: Any,
    config: object,
    *,
    upm: int,
    source_sha256: str,
) -> Any | None:
    for name in names:
        function = _optional_callable(module_name, name)
        if function is not None:
            return _invoke(
                function,
                outline=outline,
                config=config,
                upm=upm,
                source_sha256=source_sha256,
            )
    return None


def _result_candidates(result: Any | None) -> list[dict[str, Any]]:
    return [] if result is None else [_candidate_dict(candidate) for candidate in result.candidates]


def _result_skipped(result: Any | None) -> list[dict[str, Any]]:
    return [] if result is None else [item.to_dict() for item in result.skipped]


def _result_warnings(result: Any | None) -> list[str]:
    return [] if result is None else list(result.warnings)


def _missing_analysis(token: str) -> dict[str, Any]:
    return {
        "token": token,
        "glyph_name": None,
        "status": "missing",
        "contour_count": 0,
        "line_segment_count": 0,
        "quadratic_segment_count": 0,
        "corner_candidates": [],
        "terminal_candidates": [],
        "spur_candidates": [],
        "skipped": [{"reason": "glyph_not_found"}],
    }


def _normalise_analysis(value: Any, token: str, glyph_name: str) -> dict[str, Any]:
    entry = dict(value) if isinstance(value, Mapping) else {"result": value}
    entry.setdefault("token", token)
    entry.setdefault("glyph_name", glyph_name)
    entry.setdefault("status", "ok")
    for key in ("corner_candidates", "terminal_candidates", "spur_candidates", "skipped"):
        entry.setdefault(key, [])
    return entry


def _verify_upstream_sha(config: ProjectConfig, actual: str, strict_flag: bool) -> None:
    required = strict_flag or config.font.strict_upstream_sha
    expected = config.font.upstream_sha256.lower().strip()
    if required and not expected:
        raise PipelineError("strict upstream SHA is enabled but font.upstream_sha256 is empty")
    if required and actual.lower() != expected:
        raise PipelineError(f"upstream SHA-256 mismatch: expected {expected}, got {actual}")


def _config_summary(config: ProjectConfig) -> dict[str, Any]:
    return {
        "outer_radius_em": config.rounding.outer_radius_em,
        "inner_radius_em": config.rounding.inner_radius_em,
        "terminal_enabled": config.terminal.enabled,
        "spur_report_only": config.spur_detection.report_only,
    }


def _optional_callable(module_name: str, name: str) -> Callable[..., Any] | None:
    try:
        module = __import__(module_name, fromlist=[name])
    except ImportError:
        return None
    value = getattr(module, name, None)
    return value if callable(value) else None


def _invoke(function: Callable[..., Any], **kwargs: Any) -> Any:
    """Call a collaborator without passing optional keys it does not declare."""

    parameters = inspect.signature(function).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return function(**kwargs)
    return function(**{key: value for key, value in kwargs.items() if key in parameters})
