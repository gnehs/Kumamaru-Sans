from __future__ import annotations

import json
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from kumamaru.cli import build_parser, main
from tests.fixtures.synthetic_font import build_synthetic_font

ROOT = Path(__file__).parents[1]


def test_parser_exposes_exactly_the_five_public_commands() -> None:
    parser = build_parser()
    action = next(action for action in parser._actions if action.dest == "command")
    assert set(action.choices) == {"inspect", "analyze", "build", "proof", "validate"}
    parsed = parser.parse_args(
        [
            "build",
            "--input",
            "input.ttf",
            "--output",
            "output.ttf",
            "--glyphs",
            "glyphs.txt",
            "--config",
            "regular.toml",
            "--report",
            "report.json",
            "--dry-run",
            "--strict-sha",
            "--strict-overrides",
        ]
    )
    assert parsed.dry_run is True
    assert parsed.strict_upstream_sha is True
    assert parsed.strict_overrides is True


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        (
            "analyze",
            ["--input", "input.ttf", "--config", "regular.toml", "--output", "analysis.json"],
        ),
        (
            "build",
            [
                "--input",
                "input.ttf",
                "--output",
                "output.ttf",
                "--config",
                "regular.toml",
                "--report",
                "report.json",
            ],
        ),
        (
            "validate",
            ["--before", "before.ttf", "--after", "after.ttf", "--output", "validation.json"],
        ),
    ],
)
def test_commands_accept_all_encoded_glyphs_as_the_glyph_selection(
    command: str, arguments: list[str]
) -> None:
    parsed = build_parser().parse_args([command, *arguments, "--all-encoded-glyphs"])

    assert parsed.glyphs is None
    assert parsed.all_encoded_glyphs is True


def test_glyph_selection_options_are_mutually_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "analyze",
                "--input",
                "input.ttf",
                "--glyphs",
                "glyphs.txt",
                "--all-encoded-glyphs",
                "--config",
                "regular.toml",
                "--output",
                "analysis.json",
            ]
        )

    assert "not allowed with argument" in capsys.readouterr().err


def test_analyze_all_encoded_glyphs_deduplicates_best_cmap_glyph_names(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    with TTFont(source) as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[0x42] = "A"
        font.save(source)
    output = tmp_path / "analysis.json"

    assert (
        main(
            [
                "analyze",
                "--input",
                str(source),
                "--all-encoded-glyphs",
                "--config",
                str(ROOT / "config/regular.toml"),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    entries = json.loads(output.read_text(encoding="utf-8"))["glyphs"]
    names = [entry["glyph_name"] for entry in entries]
    assert names == ["space", "zero", "A", "a", "uni500B"]


def test_build_all_encoded_glyphs_uses_each_best_cmap_glyph_once(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    with TTFont(source) as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[0x42] = "A"
        font.save(source)
    report_path = tmp_path / "build.json"

    assert (
        main(
            [
                "build",
                "--input",
                str(source),
                "--output",
                str(tmp_path / "out.ttf"),
                "--all-encoded-glyphs",
                "--config",
                str(ROOT / "config/regular.toml"),
                "--report",
                str(report_path),
                "--dry-run",
            ]
        )
        == 0
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    glyphs = report["glyphs"]
    assert [entry["glyph_name"] for entry in glyphs].count("A") == 1
    assert report["selection"] == {"mode": "all_encoded_glyphs", "glyph_count": 5}
    assert "analysis" not in report
    assert {
        frozenset(
            {
                "glyph_name",
                "token",
                "is_composite",
                "applied_candidate_ids",
                "warnings",
                "safety",
            }
        )
    } == {frozenset(entry) for entry in glyphs}


def test_validate_all_encoded_glyphs_uses_each_best_cmap_glyph_once(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf", with_hinting=False)
    with TTFont(source) as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[0x42] = "A"
        font.save(source)
    report_path = tmp_path / "validation.json"

    assert (
        main(
            [
                "validate",
                "--before",
                str(source),
                "--after",
                str(source),
                "--all-encoded-glyphs",
                "--output",
                str(report_path),
            ]
        )
        == 0
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["modified_glyphs"].count("A") == 1


def test_inspect_command_writes_machine_readable_report(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    glyphs = tmp_path / "glyphs.txt"
    glyphs.write_text("A\n個\n", encoding="utf-8")
    output = tmp_path / "inspection.json"

    assert (
        main(["inspect", "--input", str(source), "--glyphs", str(glyphs), "--output", str(output)])
        == 0
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["glyph_count"] == 7
    assert report["smoke_glyphs"]["U+0041"]["glyph_name"] == "A"
    assert report["smoke_glyphs"]["U+500B"]["present"] is True


def test_missing_input_has_a_clear_cli_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    status = main(
        [
            "inspect",
            "--input",
            str(tmp_path / "missing.ttf"),
            "--output",
            str(tmp_path / "report.json"),
        ]
    )

    assert status == 2
    assert "input font does not exist" in capsys.readouterr().err


def test_build_dry_run_does_not_write_output(tmp_path: Path) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    glyphs = tmp_path / "glyphs.txt"
    glyphs.write_text("A\n", encoding="utf-8")
    output = tmp_path / "out.ttf"
    report = tmp_path / "build.json"

    assert (
        main(
            [
                "build",
                "--input",
                str(source),
                "--output",
                str(output),
                "--glyphs",
                str(glyphs),
                "--config",
                str(ROOT / "config/regular.toml"),
                "--report",
                str(report),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not output.exists()
    build_report = json.loads(report.read_text(encoding="utf-8"))
    assert build_report["dry_run"] is True
    assert "analysis" in build_report
    assert {"corner_candidates", "terminal_candidates", "spur_candidates", "skipped"} <= set(
        build_report["glyphs"][0]
    )


def test_strict_sha_rejects_a_different_upstream_font(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = build_synthetic_font(tmp_path / "source.ttf")
    glyphs = tmp_path / "glyphs.txt"
    glyphs.write_text("A\n", encoding="utf-8")

    status = main(
        [
            "build",
            "--input",
            str(source),
            "--output",
            str(tmp_path / "out.ttf"),
            "--glyphs",
            str(glyphs),
            "--config",
            str(ROOT / "config/regular.toml"),
            "--report",
            str(tmp_path / "build.json"),
            "--strict-sha",
        ]
    )

    assert status == 2
    assert "upstream SHA-256 mismatch" in capsys.readouterr().err


def test_validate_returns_one_after_writing_a_failure_report(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    before = build_synthetic_font(tmp_path / "before.ttf", with_hinting=False)
    after = tmp_path / "after.ttf"
    with TTFont(before) as font:
        width, side_bearing = font["hmtx"]["A"]
        font["hmtx"]["A"] = (width + 10, side_bearing)
        font.save(after)
    glyphs = tmp_path / "glyphs.txt"
    glyphs.write_text("A\n", encoding="utf-8")
    report = tmp_path / "validation.json"

    status = main(
        [
            "validate",
            "--before",
            str(before),
            "--after",
            str(after),
            "--glyphs",
            str(glyphs),
            "--output",
            str(report),
        ]
    )

    assert status == 1
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] is False
    assert "validation failed" in capsys.readouterr().err
