"""Generate an offline HTML + SVG visual proof for a Kumamaru build.

The proof never rasterises glyphs.  FontTools' SVGPathPen preserves quadratic
outlines as SVG paths, so reviewers can zoom indefinitely and inspect the exact
geometry that entered the output font.
"""

# ruff: noqa: E501
# The emitted HTML/SVG intentionally retains a few long, readable markup lines.

from __future__ import annotations

import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from fontTools.pens.boundsPen import BoundsPen  # type: ignore[import-untyped]
from fontTools.pens.recordingPen import DecomposingRecordingPen  # type: ignore[import-untyped]
from fontTools.pens.svgPathPen import SVGPathPen  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

SPECIMENS = (
    "個國固圓圖問間開關體熊丸",
    "小水心事我成也孔兒光永必民",
    "體鬱鑿龜齒齊龍藝響",
    "熊丸體的圓角與收筆測試。ABC abc 0123456789",
)


@dataclass(frozen=True)
class ProofSummary:
    """Locations and aggregate review counts produced by :func:`render_proof`."""

    index: Path
    glyph_count: int
    candidate_count: int
    warning_count: int


@dataclass(frozen=True)
class _GlyphDrawing:
    paths: tuple[str, ...]
    points: tuple[tuple[float, float], ...]
    segments: tuple[tuple[float, float, float, float], ...]
    bbox: tuple[float, float, float, float]


def render_proof(
    before: str | Path,
    after: str | Path,
    glyph_names: Sequence[str],
    output_dir: str | Path,
    analysis: Mapping[str, Any] | None = None,
    build_report: Mapping[str, Any] | None = None,
) -> ProofSummary:
    """Write a self-contained, offline proof directory.

    ``analysis`` intentionally accepts the command's JSON object rather than a
    private model.  This makes proof usable after a build on another machine and
    tolerant of additive analysis-schema changes.  Known candidate fields are
    displayed; unknown fields remain preserved in the source JSON report.
    """

    before_path, after_path = Path(before), Path(after)
    destination = Path(output_dir)
    glyph_dir = destination / "glyphs"
    assets_dir = destination / "assets"
    glyph_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Keep the proof portable when it is copied away from build/.  The copied
    # fonts are review artefacts, not source assets, and are therefore ignored
    # together with build/.
    shutil.copy2(before_path, assets_dir / "before.ttf")
    shutil.copy2(after_path, assets_dir / "after.ttf")

    with (
        TTFont(before_path, lazy=False) as before_font,
        TTFont(after_path, lazy=False) as after_font,
    ):
        before_set, after_set = before_font.getGlyphSet(), after_font.getGlyphSet()
        unicode_by_glyph: dict[str, int] = {}
        for codepoint, mapped_name in sorted((before_font.getBestCmap() or {}).items()):
            unicode_by_glyph.setdefault(mapped_name, codepoint)
        report_by_glyph = _analysis_by_glyph(analysis or {})
        selected = _unique(glyph_names)
        cards: list[str] = []
        candidates = 0
        warnings = 0

        for glyph_name in selected:
            if glyph_name not in before_set or glyph_name not in after_set:
                cards.append(_missing_card(glyph_name))
                warnings += 1
                continue
            before_drawing = _drawing(before_set, glyph_name)
            after_drawing = _drawing(after_set, glyph_name)
            entry = report_by_glyph.get(glyph_name, {})
            glyph_candidates = _candidates(entry)
            glyph_warnings = _warnings(entry, build_report or {}, glyph_name)
            candidates += len(glyph_candidates)
            warnings += len(glyph_warnings)
            filename = _glyph_filename(glyph_name, unicode_by_glyph.get(glyph_name))
            (glyph_dir / filename).write_text(
                _glyph_svg(
                    glyph_name,
                    before_drawing,
                    after_drawing,
                    glyph_candidates,
                    glyph_warnings,
                    _modification_count(entry, build_report or {}, glyph_name),
                ),
                encoding="utf-8",
            )
            cards.append(_glyph_card(glyph_name, filename, glyph_candidates, glyph_warnings))

    index = destination / "index.html"
    index.write_text(
        _index_html(
            cards=cards,
            glyph_count=len(selected),
            candidate_count=candidates,
            warning_count=warnings,
        ),
        encoding="utf-8",
    )
    return ProofSummary(index, len(selected), candidates, warnings)


def _drawing(glyph_set: Any, glyph_name: str) -> _GlyphDrawing:
    recording = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(recording)
    bounds_pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(bounds_pen)
    points: list[tuple[float, float]] = []
    segments: list[tuple[float, float, float, float]] = []
    previous: tuple[float, float] | None = None
    first: tuple[float, float] | None = None
    for operator, raw_points in recording.value:
        coordinates = [
            first if point is None and first is not None else (float(point[0]), float(point[1]))
            for point in raw_points
        ]
        if operator == "moveTo":
            previous = coordinates[0]
            first = previous
            points.append(previous)
        elif operator in {"lineTo", "curveTo", "qCurveTo"}:
            for point in coordinates:
                points.append(point)
            if previous is not None and coordinates:
                end = coordinates[-1]
                segments.append((previous[0], previous[1], end[0], end[1]))
                previous = end
        elif operator == "closePath" and previous is not None and first is not None:
            segments.append((previous[0], previous[1], first[0], first[1]))
            previous = first
    if not points:
        points = [(0.0, 0.0)]
    xs, ys = zip(*points, strict=True)
    if bounds_pen.bounds is None:
        bbox = (min(xs), min(ys), max(xs), max(ys))
    else:
        bbox = (
            float(bounds_pen.bounds[0]),
            float(bounds_pen.bounds[1]),
            float(bounds_pen.bounds[2]),
            float(bounds_pen.bounds[3]),
        )
    return _GlyphDrawing(
        paths=tuple(_paths_from_recording(glyph_set, recording.value)),
        points=tuple(points),
        segments=tuple(segments),
        bbox=bbox,
    )


def _paths_from_recording(
    glyph_set: Any, commands: Sequence[tuple[str, tuple[Any, ...]]]
) -> list[str]:
    """Replay each closed contour through SVGPathPen, retaining its own style."""

    contours: list[list[tuple[str, tuple[Any, ...]]]] = []
    current: list[tuple[str, tuple[Any, ...]]] = []
    for operator, points in commands:
        if operator == "moveTo" and current:
            contours.append(current)
            current = []
        current.append((operator, points))
        if operator in {"closePath", "endPath"}:
            contours.append(current)
            current = []
    if current:
        contours.append(current)
    paths: list[str] = []
    for contour in contours:
        pen = SVGPathPen(glyph_set)
        for operator, points in contour:
            getattr(pen, operator)(*points)
        paths.append(pen.getCommands())
    return paths


def _glyph_svg(
    glyph_name: str,
    before: _GlyphDrawing,
    after: _GlyphDrawing,
    candidates: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
    modifications: int,
) -> str:
    min_x = min(before.bbox[0], after.bbox[0])
    min_y = min(before.bbox[1], after.bbox[1])
    max_x = max(before.bbox[2], after.bbox[2])
    max_y = max(before.bbox[3], after.bbox[3])
    scale, origin_x, baseline = _proof_placement((min_x, min_y, max_x, max_y))
    panels = (
        (35, "原版", before.paths, "before"),
        (535, "修改版", after.paths, "after"),
        (1035, "疊圖", (), "overlay"),
    )
    panel_markup: list[str] = []
    for panel_x, label, paths, kind in panels:
        panel_markup.append(
            f'<rect class="panel" x="{panel_x}" y="82" width="430" height="478" rx="12"/>'
        )
        panel_markup.append(f'<text class="panel-title" x="{panel_x + 18}" y="118">{label}</text>')
        transform = (
            f"translate({panel_x + origin_x:.3f} {baseline:.3f}) scale({scale:.6f} {-scale:.6f})"
        )
        if kind == "overlay":
            panel_markup.append(
                f'<g transform="{transform}">{_path_elements(before.paths, "before-line")}{_path_elements(after.paths, "after-line")}</g>'
            )
            panel_markup.append(_indices_svg(before, panel_x + origin_x, baseline, scale, "before"))
            panel_markup.append(_indices_svg(after, panel_x + origin_x, baseline, scale, "after"))
            panel_markup.append(_candidate_svg(candidates, panel_x + origin_x, baseline, scale))
        else:
            panel_markup.append(
                f'<g transform="{transform}">{_path_elements(paths, f"{kind}-fill")}</g>'
            )
            drawing = before if kind == "before" else after
            panel_markup.append(_indices_svg(drawing, panel_x + origin_x, baseline, scale, kind))
    warning_text = "; ".join(warnings) if warnings else "無"
    stats = (
        f"bbox: {min_x:.0f}, {min_y:.0f}, {max_x:.0f}, {max_y:.0f}"
        f"　points: {len(before.points)} → {len(after.points)}"
        f"　modified: {modifications}　candidates: {len(candidates)}"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1500 680" role="img" aria-labelledby="title description">
  <title id="title">{escape(glyph_name)} 的 Kumamaru Sans 比較 proof</title>
  <desc id="description">原版、修改版與疊圖；可切換輪廓 point 與 segment index，以及候選標記。</desc>
  <style>
    :root {{ color-scheme: light dark; }}
    .bg {{ fill: #f8fafc; }} .panel {{ fill: #fff; stroke: #cbd5e1; stroke-width: 2; }}
    .panel-title, .heading {{ font: 600 21px system-ui, sans-serif; fill: #0f172a; }}
    .detail {{ font: 14px ui-monospace, SFMono-Regular, monospace; fill: #475569; }}
    .button {{ cursor: pointer; fill: #e2e8f0; stroke: #94a3b8; }} .button-text {{ cursor: pointer; font: 600 15px system-ui, sans-serif; fill: #0f172a; }}
    .outline {{ fill-rule: nonzero; stroke-linejoin: round; }} .before-fill {{ fill: #334155; }} .after-fill {{ fill: #0f766e; }}
    .before-line {{ fill: #64748b; fill-opacity: .42; stroke: #334155; stroke-width: 2; }} .after-line {{ fill: #14b8a6; fill-opacity: .42; stroke: #0f766e; stroke-width: 2; }}
    .index {{ display: none; }} .show-indices .index {{ display: block; }} .point {{ fill: #ea580c; }} .segment {{ stroke: #ea580c; stroke-width: 1.5; }} .index-label {{ font: 12px ui-monospace, monospace; fill: #9a3412; }}
    .candidate {{ display: none; }} .show-candidates .candidate {{ display: block; }} .candidate-dot {{ fill: #dc2626; stroke: #fff; stroke-width: 2; }} .candidate-label {{ font: 13px ui-monospace, monospace; fill: #991b1b; paint-order: stroke; stroke: #fff; stroke-width: 4; }}
    @media (prefers-color-scheme: dark) {{ .bg {{ fill:#0f172a; }} .panel {{ fill:#172033; stroke:#475569; }} .panel-title,.heading {{ fill:#f8fafc; }} .detail {{ fill:#cbd5e1; }} .button {{ fill:#334155; stroke:#64748b; }} .button-text {{ fill:#f8fafc; }} }}
  </style>
  <rect class="bg" width="1500" height="680"/>
  <text class="heading" x="35" y="42">{escape(glyph_name)}　Kumamaru Sans 靜態 proof</text>
  <g onclick="document.documentElement.classList.toggle('show-indices')" role="button" tabindex="0" aria-label="切換 point 與 segment index"><rect class="button" x="1010" y="18" width="190" height="36" rx="8"/><text class="button-text" x="1027" y="42">point / segment</text></g>
  <g onclick="document.documentElement.classList.toggle('show-candidates')" role="button" tabindex="0" aria-label="切換 candidate 標記"><rect class="button" x="1215" y="18" width="160" height="36" rx="8"/><text class="button-text" x="1232" y="42">candidates</text></g>
  {"".join(panel_markup)}
  <text class="detail" x="35" y="600">{escape(stats)}</text>
  <text class="detail" x="35" y="630">warnings: {escape(warning_text)}</text>
  <script><![CDATA[
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'i') document.documentElement.classList.toggle('show-indices');
      if (event.key === 'c') document.documentElement.classList.toggle('show-candidates');
    }});
  ]]></script>
</svg>
"""


def _proof_placement(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    """Return scale and panel-relative origin that visually center a glyph."""

    min_x, min_y, max_x, max_y = bbox
    extent = max(max_x - min_x, max_y - min_y, 1.0)
    scale = 405.0 / extent
    panel_center_x = 430.0 / 2.0
    panel_center_y = 82.0 + 478.0 / 2.0
    origin_x = panel_center_x - ((min_x + max_x) / 2.0) * scale
    # Glyph paths use a negative Y scale, so font-space center is added.
    baseline = panel_center_y + ((min_y + max_y) / 2.0) * scale
    return scale, origin_x, baseline


def _path_elements(paths: Sequence[str], class_name: str) -> str:
    """Emit one compound path so TrueType's non-zero fill spans all contours."""

    commands = "".join(path for path in paths if path)
    if not commands:
        return ""
    return f'<path class="outline {class_name}" d="{escape(commands, quote=True)}"/>'


def _indices_svg(
    drawing: _GlyphDrawing, offset_x: float, baseline: float, scale: float, variant: str
) -> str:
    parts = [f'<g class="index {variant}-index" aria-hidden="true">']
    for _number, (x1, y1, x2, y2) in enumerate(drawing.segments):
        parts.append(
            f'<line class="segment" x1="{offset_x + x1 * scale:.2f}" y1="{baseline - y1 * scale:.2f}" x2="{offset_x + x2 * scale:.2f}" y2="{baseline - y2 * scale:.2f}"/>'
        )
    for number, (x, y) in enumerate(drawing.points):
        px, py = offset_x + x * scale, baseline - y * scale
        parts.append(
            f'<circle class="point" cx="{px:.2f}" cy="{py:.2f}" r="3"/><text class="index-label" x="{px + 4:.2f}" y="{py - 4:.2f}">{number}</text>'
        )
    return "".join(parts) + "</g>"


def _candidate_svg(
    candidates: Sequence[Mapping[str, Any]], offset_x: float, baseline: float, scale: float
) -> str:
    parts = ['<g class="candidate" aria-label="分析候選">']
    for candidate in candidates:
        point = _candidate_point(candidate)
        if point is None:
            continue
        x, y = point
        identifier = str(candidate.get("candidate_id") or candidate.get("id") or "candidate")
        px, py = offset_x + x * scale, baseline - y * scale
        parts.append(
            f'<circle class="candidate-dot" cx="{px:.2f}" cy="{py:.2f}" r="6"/><text class="candidate-label" x="{px + 8:.2f}" y="{py - 8:.2f}">{escape(identifier)}</text>'
        )
    return "".join(parts) + "</g>"


def _candidate_point(candidate: Mapping[str, Any]) -> tuple[float, float] | None:
    try:
        for field in ("point", "position", "center", "location"):
            value = candidate.get(field)
            if isinstance(value, Mapping) and "x" in value and "y" in value:
                return float(value["x"]), float(value["y"])
            if isinstance(value, Sequence) and not isinstance(value, str) and len(value) >= 2:
                return float(value[0]), float(value[1])
        if "x" in candidate and "y" in candidate:
            return float(candidate["x"]), float(candidate["y"])
    except (TypeError, ValueError):
        return None
    return None


def _analysis_by_glyph(analysis: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = analysis.get("glyphs", analysis.get("results", {}))
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items() if isinstance(value, Mapping)}
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        return {
            str(item.get("glyph_name") or item.get("name")): item
            for item in raw
            if isinstance(item, Mapping) and (item.get("glyph_name") or item.get("name"))
        }
    return {}


def _candidates(entry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for key in (
        "corners",
        "corner_candidates",
        "terminals",
        "terminal_candidates",
        "spurs",
        "spur_candidates",
        "flare_candidates",
        "candidates",
    ):
        values = entry.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, str):
            result.extend(value for value in values if isinstance(value, Mapping))
    unique: dict[str, Mapping[str, Any]] = {}
    for index, candidate in enumerate(result):
        identifier = str(candidate.get("candidate_id") or candidate.get("id") or index)
        unique.setdefault(identifier, candidate)
    return list(unique.values())


def _warnings(
    entry: Mapping[str, Any], build_report: Mapping[str, Any], glyph_name: str
) -> list[str]:
    messages: list[str] = []
    for source in (entry, build_report):
        for key in ("warnings", "skipped", "errors"):
            values = source.get(key, [])
            if not isinstance(values, Sequence) or isinstance(values, str):
                continue
            for value in values:
                if isinstance(value, str):
                    messages.append(value)
                elif (
                    isinstance(value, Mapping) and value.get("glyph_name", glyph_name) == glyph_name
                ):
                    messages.append(str(value.get("message") or value.get("reason") or value))
    return _unique(messages)


def _modification_count(
    entry: Mapping[str, Any], build_report: Mapping[str, Any], glyph_name: str
) -> int:
    # The build report describes what was actually applied, while analysis is
    # only a prospective view of the glyph.
    for source in (build_report, entry):
        for candidate in (source, _glyph_report_entry(source, glyph_name)):
            if candidate is None:
                continue
            count = candidate.get("modification_count")
            if isinstance(count, int):
                return count
            applied = candidate.get("applied_candidate_ids")
            if isinstance(applied, Sequence) and not isinstance(applied, str):
                return len(applied)
    return 0


def _glyph_report_entry(source: Mapping[str, Any], glyph_name: str) -> Mapping[str, Any] | None:
    """Find a glyph's build result in either supported ``glyphs`` report shape."""

    glyphs = source.get("glyphs")
    if isinstance(glyphs, Mapping):
        entry = glyphs.get(glyph_name)
        return entry if isinstance(entry, Mapping) else None
    if isinstance(glyphs, Sequence) and not isinstance(glyphs, str):
        for entry in glyphs:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("glyph_name") or entry.get("name")
            if name == glyph_name:
                return entry
    return None


def _glyph_filename(glyph_name: str, codepoint: int | None = None) -> str:
    if codepoint is not None:
        return f"U{codepoint:04X}.svg"
    if len(glyph_name) == 1:
        return f"U{ord(glyph_name):04X}.svg"
    safe = "".join(
        character if character.isalnum() or character in "._-" else "_" for character in glyph_name
    )
    return f"{safe or 'glyph'}.svg"


def _glyph_card(
    glyph_name: str, filename: str, candidates: Sequence[Mapping[str, Any]], warnings: Sequence[str]
) -> str:
    marker = f"{len(candidates)} candidates"
    if warnings:
        marker += f" · {len(warnings)} warnings"
    return f'<li><a href="glyphs/{escape(filename, quote=True)}"><span class="glyph">{escape(glyph_name)}</span><span>{escape(marker)}</span></a></li>'


def _missing_card(glyph_name: str) -> str:
    return f'<li class="missing"><span class="glyph">{escape(glyph_name)}</span><span>not found in both fonts</span></li>'


def _index_html(
    *, cards: Iterable[str], glyph_count: int, candidate_count: int, warning_count: int
) -> str:
    specimens = "".join(f'<p class="specimen">{escape(line)}</p>' for line in SPECIMENS)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kumamaru Sans proof</title>
  <style>
    @font-face {{ font-family: ProofBefore; src: url("assets/before.ttf") format("truetype"); }}
    @font-face {{ font-family: ProofAfter; src: url("assets/after.ttf") format("truetype"); }}
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; background:#f8fafc; color:#172033; }}
    body {{ max-width:1100px; margin:0 auto; padding:32px 20px 72px; }} h1 {{ margin-bottom:4px; }} .muted {{ color:#64748b; }}
    .stats, ul {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; padding:0; }} .stat, li {{ list-style:none; border:1px solid #cbd5e1; background:#fff; border-radius:12px; padding:14px; }}
    .stat strong {{ display:block; font-size:26px; }} .specimens {{ margin:32px 0; border-left:4px solid #0f766e; padding:8px 22px; background:#ecfdf5; }} .specimen {{ margin:10px 0; font-size:25px; line-height:1.55; }}
    .comparison {{ display:flex; gap:16px; }} .comparison span {{ flex:1; }} .before {{ font-family:ProofBefore, sans-serif; }} .after {{ font-family:ProofAfter, sans-serif; color:#0f766e; }} a {{ display:flex; justify-content:space-between; align-items:center; gap:10px; color:inherit; text-decoration:none; }} a:hover {{ border-color:#0f766e; }} .glyph {{ font:32px ProofAfter, sans-serif; }} .missing {{ opacity:.65; }}
    @media (prefers-color-scheme:dark) {{ :root {{ background:#0f172a; color:#f8fafc; }} .stat,li {{ background:#172033; border-color:#475569; }} .muted {{ color:#cbd5e1; }} .specimens {{ background:#12352f; }} }}
  </style>
</head>
<body>
  <h1>Kumamaru Sans 靜態 proof</h1>
  <p class="muted">離線可開啟；每個字連結均含原版、修改版、疊圖及可切換的候選／索引圖層。</p>
  <section class="stats" aria-label="proof 統計"><div class="stat"><strong>{glyph_count}</strong>review glyphs</div><div class="stat"><strong>{candidate_count}</strong>candidate markers</div><div class="stat"><strong>{warning_count}</strong>warnings</div></section>
  <section class="specimens"><h2>首頁 specimen</h2><div class="comparison"><span class="before">{specimens}</span><span class="after">{specimens}</span></div></section>
  <h2>逐字檢視</h2><ul>{"".join(cards)}</ul>
</body>
</html>
"""


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
