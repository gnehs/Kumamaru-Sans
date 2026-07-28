"""Explicit, font-library-independent outline and analysis models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypeAlias


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass
class LineSegment:
    start: Point
    end: Point


@dataclass
class QuadraticSegment:
    start: Point
    control: Point
    end: Point


Segment: TypeAlias = LineSegment | QuadraticSegment


@dataclass
class Contour:
    segments: list[Segment]
    closed: bool
    source_contour_index: int


@dataclass
class GlyphOutline:
    glyph_name: str
    contours: list[Contour]
    width: int


CandidateKind: TypeAlias = Literal["corner", "terminal", "spur"]


@dataclass(frozen=True)
class Candidate:
    """Stable analysis record shared by reports, proofs and overrides."""

    candidate_id: str
    kind: CandidateKind
    glyph_name: str
    contour_index: int
    segment_start: int
    segment_end: int
    direction: str
    confidence: float
    reason: str
    point: Point
    geometry: dict[str, float | int | str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkippedItem:
    contour_index: int
    segment_index: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FilterResult:
    """Non-mutating filter result with enough detail for machine reports."""

    outline: GlyphOutline
    candidates: list[Candidate] = field(default_factory=list)
    applied_candidate_ids: list[str] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
