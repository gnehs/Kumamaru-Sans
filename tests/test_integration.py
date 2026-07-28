from __future__ import annotations

import json
from pathlib import Path

import pytest

from kumamaru.cli import main

ROOT = Path(__file__).parents[1]
UPSTREAM = ROOT / "vendor/IBMPlexSansTC-Regular.ttf"


@pytest.mark.integration
@pytest.mark.skipif(
    not UPSTREAM.exists(), reason="official upstream font is not present in vendor/"
)
def test_official_smoke_workflow(tmp_path: Path) -> None:
    glyphs = ROOT / "config/glyphsets/smoke.txt"
    config = ROOT / "config/regular.toml"
    inspection = tmp_path / "inspection.json"
    analysis = tmp_path / "analysis.json"
    output = tmp_path / "KumamaruSans-Regular.ttf"
    build_report = tmp_path / "build.json"
    proof = tmp_path / "proof"
    validation = tmp_path / "validation.json"

    assert main(["inspect", "--input", str(UPSTREAM), "--output", str(inspection)]) == 0
    assert (
        main(
            [
                "analyze",
                "--input",
                str(UPSTREAM),
                "--glyphs",
                str(glyphs),
                "--config",
                str(config),
                "--output",
                str(analysis),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "build",
                "--input",
                str(UPSTREAM),
                "--output",
                str(output),
                "--glyphs",
                str(glyphs),
                "--config",
                str(config),
                "--report",
                str(build_report),
            ]
        )
        == 0
    )
    build_data = json.loads(build_report.read_text(encoding="utf-8"))
    individual = next(entry for entry in build_data["glyphs"] if entry["glyph_name"] == "uni500B")
    assert [
        candidate_id
        for candidate_id in individual["applied_candidate_ids"]
        if candidate_id.startswith("terminal-")
    ]
    assert all(
        "shaft_aspect_ratio" in candidate["geometry"]
        and "nesting_depth" in candidate["geometry"]
        and "contains_contour" in candidate["geometry"]
        for candidate in individual["terminal_candidates"]
    )
    assert (
        main(
            [
                "proof",
                "--before",
                str(UPSTREAM),
                "--after",
                str(output),
                "--glyphs",
                str(glyphs),
                "--analysis",
                str(analysis),
                "--build-report",
                str(build_report),
                "--output",
                str(proof),
            ]
        )
        == 0
    )
    assert (proof / "index.html").is_file()
    assert (
        main(
            [
                "validate",
                "--before",
                str(UPSTREAM),
                "--after",
                str(output),
                "--glyphs",
                str(glyphs),
                "--output",
                str(validation),
            ]
        )
        == 0
    )
    validation_data = json.loads(validation.read_text(encoding="utf-8"))
    assert validation_data["passed"]
    assert validation_data["geometry"]["uni500B"]["boundary_deviation"] <= 80
