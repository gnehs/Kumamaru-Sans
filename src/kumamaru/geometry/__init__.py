"""Geometry primitives and FontTools adapters."""

from kumamaru.geometry.contour import (
    OutlineModelError,
    clone_outline,
    glyph_to_outline,
    outline_to_glyph,
    validate_outline,
)
from kumamaru.geometry.winding import orientation, signed_area

__all__ = [
    "OutlineModelError",
    "clone_outline",
    "glyph_to_outline",
    "orientation",
    "outline_to_glyph",
    "signed_area",
    "validate_outline",
]
