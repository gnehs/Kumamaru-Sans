from __future__ import annotations

from pathlib import Path

import pytest

from kumamaru.render import (
    _modification_count,
    _path_elements,
    _proof_placement,
    render_proof,
)
from tests.fixtures.synthetic_font import build_synthetic_font


@pytest.mark.parametrize(
    ("glyph_name", "glyph_entry", "expected"),
    [
        ("A", {"glyph_name": "A", "applied_candidate_ids": ["terminal-1", "corner-2"]}, 2),
        ("uni500B", {"name": "uni500B", "modification_count": 3}, 3),
    ],
)
def test_modification_count_reads_list_shaped_build_report(
    glyph_name: str, glyph_entry: dict[str, object], expected: int
) -> None:
    build_report = {"glyphs": [glyph_entry]}

    assert _modification_count({}, build_report, glyph_name) == expected


def test_modification_count_keeps_mapping_shaped_build_report_support() -> None:
    build_report = {"glyphs": {"A": {"applied_candidate_ids": ["corner-1"]}}}

    assert _modification_count({}, build_report, "A") == 1


def test_proof_displays_applied_candidate_count_from_list_build_report(tmp_path: Path) -> None:
    before = build_synthetic_font(tmp_path / "before.ttf")
    after = build_synthetic_font(tmp_path / "after.ttf")

    render_proof(
        before,
        after,
        ["A"],
        tmp_path / "proof",
        build_report={
            "glyphs": [{"glyph_name": "A", "applied_candidate_ids": ["terminal-1", "corner-2"]}]
        },
    )

    proof = (tmp_path / "proof" / "glyphs" / "U0041.svg").read_text(encoding="utf-8")
    assert "modified: 2" in proof


def test_compound_fill_path_keeps_all_contours_in_one_fill_shape() -> None:
    outer = "M0 0H10V10H0Z"
    inner = "M2 2H8V8H2Z"

    markup = _path_elements((outer, inner), "before-fill")

    assert markup.count("<path ") == 1
    assert f'd="{outer}{inner}"' in markup


def test_proof_placement_centers_y_flipped_glyph_inside_panel() -> None:
    scale, origin_x, baseline = _proof_placement((0.0, -200.0, 1000.0, 800.0))

    left = 35.0 + origin_x
    right = left + 1000.0 * scale
    top = baseline - 800.0 * scale
    bottom = baseline - (-200.0) * scale

    assert (left + right) / 2.0 == pytest.approx(35.0 + 430.0 / 2.0)
    assert (top + bottom) / 2.0 == pytest.approx(82.0 + 478.0 / 2.0)
    assert 82.0 <= top < bottom <= 560.0
