from __future__ import annotations

from array import array
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables.ttProgram import Program

GLYPH_ORDER = [".notdef", "space", "A", "a", "zero", "uni500B", "A.alt"]


def _empty():
    return TTGlyphPen(None).glyph()


def _rectangle(x_min: int, y_min: int, x_max: int, y_max: int):
    pen = TTGlyphPen(None)
    pen.moveTo((x_min, y_min))
    pen.lineTo((x_max, y_min))
    pen.lineTo((x_max, y_max))
    pen.lineTo((x_min, y_max))
    pen.closePath()
    return pen.glyph()


def _triangle():
    pen = TTGlyphPen(None)
    pen.moveTo((80, 0))
    pen.lineTo((300, 700))
    pen.lineTo((520, 0))
    pen.closePath()
    return pen.glyph()


def build_synthetic_font(
    path: Path,
    *,
    with_hinting: bool = True,
    with_dsig: bool = True,
) -> Path:
    """Build a tiny static TTF without using or embedding any upstream font data."""

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(GLYPH_ORDER)
    glyphs = {
        ".notdef": _rectangle(50, 0, 550, 700),
        "space": _empty(),
        "A": _triangle(),
        "a": _rectangle(80, 0, 500, 500),
        "zero": _rectangle(80, 0, 520, 700),
        "uni500B": _rectangle(50, -50, 950, 850),
    }
    composite_pen = TTGlyphPen(glyphs)
    composite_pen.addComponent("A", (1, 0, 0, 1, 20, 0))
    glyphs["A.alt"] = composite_pen.glyph()
    if with_hinting:
        program = Program()
        program.fromAssembly(["SVTCA[0]"])
        glyphs["A"].program = program

    builder.setupCharacterMap(
        {
            0x20: "space",
            0x30: "zero",
            0x41: "A",
            0x61: "a",
            0x500B: "uni500B",
        }
    )
    metrics = {name: (1000 if name == "uni500B" else 600, 0) for name in GLYPH_ORDER}
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=880, descent=-120)
    builder.setupVerticalMetrics({name: (1000, 100) for name in GLYPH_ORDER})
    builder.setupVerticalHeader(ascent=500, descent=-500)
    builder.setupNameTable(
        {
            "familyName": "Upstream Test Plex",
            "styleName": "Regular",
            "uniqueFontIdentifier": "1.0;TEST;UpstreamTestPlex-Regular",
            "fullName": "Upstream Test Plex Regular",
            "psName": "UpstreamTestPlex-Regular",
            "version": "Version 1.0",
            "copyright": "Copyright Example Upstream.",
        }
    )
    builder.setupOS2(
        sTypoAscender=880,
        sTypoDescender=-120,
        usWinAscent=880,
        usWinDescent=120,
        achVendID="TEST",
    )
    builder.setupPost()
    builder.setupMaxp()

    if with_hinting:
        cvt = newTable("cvt ")
        cvt.values = array("h", [20])
        builder.font["cvt "] = cvt
        for tag in ("fpgm", "prep"):
            table = newTable(tag)
            table.program = Program()
            table.program.fromAssembly(["SVTCA[0]"])
            builder.font[tag] = table
    if with_dsig:
        dsig = newTable("DSIG")
        dsig.ulVersion = 1
        dsig.usFlag = 0
        dsig.usNumSigs = 0
        dsig.signatureRecords = []
        builder.font["DSIG"] = dsig

    path.parent.mkdir(parents=True, exist_ok=True)
    builder.save(path)
    return path
