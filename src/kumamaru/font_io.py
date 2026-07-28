from __future__ import annotations

import hashlib
import io
import os
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]


class FontFormatError(ValueError):
    """Raised when an input is not a supported static TrueType font."""


REQUIRED_TRUETYPE_TABLES = frozenset(
    {"OS/2", "cmap", "glyf", "head", "hhea", "hmtx", "loca", "maxp", "name"}
)
PROHIBITED_TABLES = frozenset({"CFF ", "CFF2", "fvar"})
HINTING_TABLES = frozenset({"LTSH", "VDMX", "cvt ", "fpgm", "hdmx", "prep"})


def sha256_file(path: str | Path) -> str:
    """Return a lowercase SHA-256 digest without loading the whole font in memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_static_truetype(font: TTFont, *, source: str | Path | None = None) -> None:
    """Reject collections, variable fonts, and CFF-flavoured OpenType fonts."""

    label = str(source) if source is not None else "font"
    if font.flavor is not None:
        raise FontFormatError(
            f"{label} is a {font.flavor!r} webfont; an unwrapped static TTF is required"
        )
    tables = set(font.keys())
    if "glyf" not in tables or "loca" not in tables:
        if tables & {"CFF ", "CFF2"}:
            raise FontFormatError(f"{label} uses CFF outlines; only static TTF/glyf is supported")
        raise FontFormatError(f"{label} has no TrueType 'glyf' and 'loca' tables")
    prohibited = sorted(tables & PROHIBITED_TABLES)
    if prohibited:
        formatted = ", ".join(repr(tag) for tag in prohibited)
        raise FontFormatError(f"{label} is not a static TrueType font (found {formatted})")
    missing = sorted(REQUIRED_TRUETYPE_TABLES - tables)
    if missing:
        raise FontFormatError(f"{label} is missing required table(s): {', '.join(missing)}")
    if font.sfntVersion not in {"\x00\x01\x00\x00", "true"}:
        raise FontFormatError(
            f"{label} has unsupported sfnt flavor {font.sfntVersion!r}; expected TrueType"
        )


def load_font(path: str | Path, *, lazy: bool = False, validate: bool = True) -> TTFont:
    """Load one font from a filesystem path and provide user-facing format errors."""

    font_path = Path(path)
    if not font_path.is_file():
        raise FontFormatError(f"font file does not exist: {font_path}")
    try:
        font = TTFont(font_path, lazy=lazy, recalcBBoxes=False, recalcTimestamp=False)
    except (OSError, TTLibError) as exc:
        raise FontFormatError(f"could not read font {font_path}: {exc}") from exc
    if validate:
        try:
            assert_static_truetype(font, source=font_path)
        except Exception:
            font.close()
            raise
    return font


def _debug_name(font: TTFont, name_id: int) -> str | None:
    record = font["name"].getFirstDebugName((name_id,))
    return record if record else None


def _resolve_requested_glyph(
    value: str, cmap: dict[int, str], glyph_order: set[str]
) -> tuple[str, str | None]:
    if value.startswith(("U+", "u+")):
        try:
            codepoint = int(value[2:], 16)
        except ValueError:
            return value, None
        return value, cmap.get(codepoint)
    if len(value) == 1:
        return f"U+{ord(value):04X}", cmap.get(ord(value))
    return value, value if value in glyph_order else None


def inspect_font(
    path: str | Path,
    *,
    smoke_glyphs: Iterable[str] = (),
) -> dict[str, Any]:
    """Inspect a supported input font and return a deterministic JSON-ready mapping."""

    font_path = Path(path)
    if not font_path.is_file():
        raise FontFormatError(f"font file does not exist: {font_path}")
    digest = sha256_file(font_path)
    with load_font(font_path, lazy=False) as font:
        # TTFont implements sequence-style __getitem__, so direct iteration probes "0".
        tables = sorted(tag for tag in font.keys() if tag != "GlyphOrder")  # noqa: SIM118
        glyph_order = font.getGlyphOrder()
        glyph_names = set(glyph_order)
        glyph_order_hash = hashlib.sha256("\0".join(glyph_order).encode()).hexdigest()
        best_cmap = font.getBestCmap() or {}
        glyf = font["glyf"]
        simple_count = 0
        composite_count = 0
        empty_count = 0
        instructed_count = 0
        for glyph_name in glyph_order:
            glyph = glyf[glyph_name]
            if glyph.isComposite():
                composite_count += 1
            elif glyph.numberOfContours > 0:
                simple_count += 1
            else:
                empty_count += 1
            program = getattr(glyph, "program", None)
            if program is not None and program.getBytecode():
                instructed_count += 1

        requested: dict[str, dict[str, Any]] = {}
        for raw_value in smoke_glyphs:
            value = str(raw_value)
            label, glyph_name = _resolve_requested_glyph(value, best_cmap, glyph_names)
            requested[label] = {"present": glyph_name is not None, "glyph_name": glyph_name}

        hinting_tables = sorted(set(tables) & HINTING_TABLES)
        return {
            "input": str(font_path),
            "sha256": digest,
            "sfnt_flavor": "TrueType"
            if font.sfntVersion in {"\x00\x01\x00\x00", "true"}
            else font.sfntVersion,
            "sfnt_version": font.sfntVersion,
            "tables": tables,
            "units_per_em": font["head"].unitsPerEm,
            "glyph_count": len(glyph_order),
            "glyph_order_sha256": glyph_order_hash,
            "unicode_cmap_count": len(best_cmap),
            "outline_counts": {
                "simple": simple_count,
                "composite": composite_count,
                "empty": empty_count,
            },
            "outline_type": "glyf",
            "is_variable": "fvar" in font,
            "has_cff": "CFF " in font,
            "has_cff2": "CFF2" in font,
            "hinting": {
                "present": bool(hinting_tables or instructed_count),
                "tables": hinting_tables,
                "instructed_glyph_count": instructed_count,
            },
            "names": {
                "family": font["name"].getBestFamilyName() or _debug_name(font, 1),
                "subfamily": font["name"].getBestSubFamilyName() or _debug_name(font, 2),
                "full_name": font["name"].getBestFullName() or _debug_name(font, 4),
                "postscript_name": _debug_name(font, 6),
            },
            "fs_type": font["OS/2"].fsType,
            "smoke_glyphs": requested,
        }


def strip_hinting(font: TTFont) -> dict[str, Any]:
    """Remove all glyph programs and global tables that depend on TrueType hints."""

    assert_static_truetype(font)
    glyf = font["glyf"]
    stripped_glyph_count = 0
    for glyph in glyf.glyphs.values():
        if "data" in glyph.__dict__:
            before_data = glyph.data
            glyph.removeHinting()
            stripped_glyph_count += glyph.data != before_data
        else:
            program = getattr(glyph, "program", None)
            if program is not None and program.getBytecode():
                stripped_glyph_count += 1
            glyph.removeHinting()

    removed_tables: list[str] = []
    for tag in sorted(HINTING_TABLES):
        if tag in font:
            del font[tag]
            removed_tables.append(tag)
    maxp = font["maxp"]
    if getattr(maxp, "tableVersion", 0) == 0x00010000:
        maxp.maxZones = 1
        for field in (
            "maxTwilightPoints",
            "maxStorage",
            "maxFunctionDefs",
            "maxInstructionDefs",
            "maxStackElements",
            "maxSizeOfInstructions",
        ):
            setattr(maxp, field, 0)
    return {
        "unhinted": True,
        "glyph_instructions_removed": stripped_glyph_count,
        "removed_hinting_tables": removed_tables,
    }


def remove_dsig(font: TTFont) -> bool:
    """Remove an invalidated digital signature table, returning whether it existed."""

    if "DSIG" not in font:
        return False
    del font["DSIG"]
    return True


def save_font(font: TTFont, path: str | Path) -> Path:
    """Atomically save a font and let FontTools recalculate checksums and bounds."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Point-count changes must be reflected in maxp even when untouched glyph
    # binaries are intentionally kept compact and their bounds are not rebuilt.
    font["maxp"].recalc(font)
    # Modified glyph constructors are responsible for calculating their own bounds.
    # Keeping this false avoids recompiling every untouched glyph.
    font.recalcBBoxes = False
    font.recalcTimestamp = False
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    try:
        font.save(temporary_name, reorderTables=False)
        os.replace(temporary_name, destination)
    except Exception:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise
    return destination


def roundtrip_font(font: TTFont) -> TTFont:
    """Serialize and fully reopen a font in memory for structural validation."""

    stream = io.BytesIO()
    font.save(stream, reorderTables=False)
    stream.seek(0)
    return TTFont(stream, lazy=False, recalcTimestamp=False)


def compiled_table_bytes(font: TTFont, tag: str) -> bytes:
    """Compile one table without serializing an entire sfnt."""

    data: bytes = font.getTableData(tag)
    return data


def normalized_glyph_bytes(font: TTFont, glyph_name: str) -> bytes:
    """Compile one glyph after removing hints, for outline-only comparisons."""

    import copy

    glyph = copy.deepcopy(font["glyf"][glyph_name])
    glyph.removeHinting()
    data: bytes = glyph.compile(font["glyf"], recalcBBoxes=False)
    return data
