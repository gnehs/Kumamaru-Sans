"""Render deterministic low-PPEM proofs through HarfBuzz's ``hb-view`` CLI.

Unlike :mod:`kumamaru.render`, this module deliberately rasterizes through
FreeType.  The explicit FreeType load flags are important: ``hb-view`` defaults
to ``FT_LOAD_NO_HINTING`` (value 2), while a low-PPEM proof needs the font's
native TrueType hints to run.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path

from kumamaru.report import write_json

DEFAULT_PPEMS = (9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 32, 48)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COMMAND_TIMEOUT_SECONDS = 60
_FIXED_ARGUMENTS = (
    "--face-loader=ft",
    "--font-funcs=ft",
    "--ft-load-flags=0",
    "--output-format=png",
)


class RasterProofError(RuntimeError):
    """Raised when ``hb-view`` cannot produce a trustworthy raster proof."""


@dataclass(frozen=True)
class RasterProofSummary:
    """Paths emitted by :func:`render_raster_proof`."""

    index: Path
    manifest: Path
    images: tuple[Path, ...]
    ppems: tuple[int, ...]


def render_raster_proof(
    font: str | Path,
    output_dir: str | Path,
    text: str,
    *,
    ppems: Sequence[int] = DEFAULT_PPEMS,
    location: Mapping[str, float] | None = None,
    executable: str | Path = "hb-view",
) -> RasterProofSummary:
    """Rasterize ``text`` at each requested PPEM and write an offline index.

    ``executable`` is injectable so callers can select a pinned ``hb-view``
    binary and tests can exercise the subprocess boundary without requiring a
    system installation.  The command is always invoked as an argument list;
    neither the text nor any path is interpreted by a shell.
    """

    font_path = Path(font)
    destination = Path(output_dir)
    normalized_ppems = _validate_ppems(ppems)
    normalized_location = _validate_location(location or {})
    executable_name = str(executable)

    if not text:
        raise ValueError("Raster proof text must not be empty")
    if not font_path.is_file():
        raise FileNotFoundError(f"Raster proof font does not exist or is not a file: {font_path}")
    if font_path.suffix.lower() != ".ttf":
        raise ValueError(f"Raster proof requires a TTF font, got: {font_path}")

    version = _hb_view_version(executable_name)
    font_sha256 = _sha256(font_path)
    variation_argument = _variation_argument(normalized_location)
    image_records: list[dict[str, int | str]] = [
        {"ppem": ppem, "path": f"images/ppem-{ppem:03d}.png"} for ppem in normalized_ppems
    ]

    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".raster-proof-", dir=destination) as temporary:
        stage = Path(temporary)
        stage_images = stage / "images"
        stage_images.mkdir()

        for record in image_records:
            ppem = int(record["ppem"])
            relative_path_string = str(record["path"])
            output_path = stage / relative_path_string
            arguments = [
                executable_name,
                *_FIXED_ARGUMENTS[:3],
                f"--font-size={ppem}",
                f"--font-ppem={ppem}",
            ]
            if variation_argument is not None:
                arguments.append(f"--variations={variation_argument}")
            arguments.extend(
                [
                    _FIXED_ARGUMENTS[3],
                    f"--output-file={output_path}",
                    str(font_path),
                    text,
                ]
            )
            _run(arguments, action=f"rasterize {ppem} ppem")
            _verify_png(output_path, ppem)

        manifest_data = {
            "schema_version": 1,
            "font": {
                "filename": font_path.name,
                "sha256": font_sha256,
            },
            "text": text,
            "ppems": list(normalized_ppems),
            "location": dict(normalized_location),
            "rasterizer": {
                "executable": Path(executable_name).name,
                "version": version,
                "face_loader": "ft",
                "font_funcs": "ft",
                "ft_load_flags": 0,
                "font_size": "<ppem>",
                "font_ppem": "<ppem>",
                "output_format": "png",
                "fixed_arguments": list(_FIXED_ARGUMENTS),
            },
            "images": image_records,
        }
        write_json(stage / "manifest.json", manifest_data)
        (stage / "index.html").write_text(
            _index_html(
                font_name=font_path.name,
                text=text,
                ppems=normalized_ppems,
                location=normalized_location,
                image_records=image_records,
            ),
            encoding="utf-8",
        )

        final_images = destination / "images"
        final_images.mkdir(exist_ok=True)
        expected_image_names = {Path(str(record["path"])).name for record in image_records}
        for stale_image in final_images.glob("ppem-*.png"):
            if stale_image.name not in expected_image_names:
                stale_image.unlink()
        image_paths: list[Path] = []
        for record in image_records:
            relative_image_path = Path(str(record["path"]))
            final_path = destination / relative_image_path
            (stage / relative_image_path).replace(final_path)
            image_paths.append(final_path)
        (stage / "manifest.json").replace(destination / "manifest.json")
        (stage / "index.html").replace(destination / "index.html")

    return RasterProofSummary(
        index=destination / "index.html",
        manifest=destination / "manifest.json",
        images=tuple(image_paths),
        ppems=normalized_ppems,
    )


def _validate_ppems(ppems: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(ppems)
    if not normalized:
        raise ValueError("Raster proof requires at least one PPEM size")
    for ppem in normalized:
        if isinstance(ppem, bool) or not isinstance(ppem, int) or ppem <= 0:
            raise ValueError(f"Raster proof PPEM sizes must be positive integers, got: {ppem!r}")
    if len(set(normalized)) != len(normalized):
        raise ValueError("Raster proof PPEM sizes must not contain duplicates")
    return normalized


def _validate_location(location: Mapping[str, float]) -> tuple[tuple[str, float], ...]:
    normalized: list[tuple[str, float]] = []
    for tag, raw_value in location.items():
        if len(tag) != 4 or not tag.isascii():
            raise ValueError(f"Variation axis tags must be four ASCII characters, got: {tag!r}")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"Variation value for {tag!r} must be numeric, got: {raw_value!r}")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"Variation value for {tag!r} must be finite, got: {raw_value!r}")
        normalized.append((tag, 0.0 if value == 0 else value))
    return tuple(sorted(normalized))


def _variation_argument(location: Sequence[tuple[str, float]]) -> str | None:
    if not location:
        return None
    return ",".join(f"{tag}={value:.15g}" for tag, value in location)


def _hb_view_version(executable: str) -> str:
    result = _run([executable, "--version"], action="read hb-view version")
    version = result.stdout.strip() or result.stderr.strip()
    if not version:
        raise RasterProofError(f"{executable!r} returned an empty version string")
    return version


def _run(arguments: list[str], *, action: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise RasterProofError(
            f"Cannot {action}: hb-view executable was not found: {arguments[0]!r}"
        ) from error
    except OSError as error:
        raise RasterProofError(f"Cannot {action} with {arguments[0]!r}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise RasterProofError(
            f"Cannot {action}: {arguments[0]!r} exceeded {_COMMAND_TIMEOUT_SECONDS} seconds"
        ) from error
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RasterProofError(
            f"Cannot {action}: {arguments[0]!r} exited with status {result.returncode}: {details}"
        )
    return result


def _verify_png(path: Path, ppem: int) -> None:
    if not path.is_file():
        raise RasterProofError(
            f"hb-view reported success for {ppem} ppem but did not create {path.name}"
        )
    with path.open("rb") as image:
        signature = image.read(len(_PNG_SIGNATURE))
    if signature != _PNG_SIGNATURE:
        raise RasterProofError(
            f"hb-view output for {ppem} ppem is not a valid PNG file: {path.name}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _index_html(
    *,
    font_name: str,
    text: str,
    ppems: Sequence[int],
    location: Sequence[tuple[str, float]],
    image_records: Sequence[Mapping[str, int | str]],
) -> str:
    location_label = _variation_argument(location) or "default"
    cards = "\n".join(
        (
            '<figure class="sample">'
            f"<figcaption>{ppem} ppem</figcaption>"
            f'<img src="{escape(str(record["path"]), quote=True)}" '
            f'alt="{ppem} ppem raster" loading="lazy">'
            "</figure>"
        )
        for ppem, record in zip(ppems, image_records, strict=True)
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(font_name)} low-PPEM raster proof</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; padding: 2rem; background: #f4f4f2; color: #171717; }}
    main {{ max-width: 90rem; margin: 0 auto; }}
    h1 {{ margin-bottom: .5rem; }}
    .meta {{ margin: .25rem 0; color: #555; }}
    .matrix {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
      gap: 1rem; margin-top: 2rem; }}
    .sample {{ margin: 0; padding: 1rem; background: white; border: 1px solid #ccc;
      border-radius: .5rem; }}
    figcaption {{ margin-bottom: .75rem; font-weight: 650; }}
    img {{ display: block; max-width: 100%; image-rendering: pixelated; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #171717; color: #eee; }}
      .meta {{ color: #aaa; }}
      .sample {{ background: #242424; border-color: #555; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Low-PPEM raster proof</h1>
    <p class="meta">Font: <code>{escape(font_name)}</code></p>
    <p class="meta">Location: <code>{escape(location_label)}</code></p>
    <p class="meta">Text: <span lang="zh-Hant">{escape(text)}</span></p>
    <section class="matrix" aria-label="PPEM raster matrix">
{cards}
    </section>
  </main>
</body>
</html>
"""
