from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kumamaru.raster_proof import (
    DEFAULT_PPEMS,
    RasterProofError,
    render_raster_proof,
)


def _fake_hb_view(tmp_path: Path, *, fail_ppem: int | None = None) -> Path:
    executable = tmp_path / "hb-view"
    failure = "None" if fail_ppem is None else str(fail_ppem)
    executable.write_text(
        f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if sys.argv[1:] == ["--version"]:
    print("hb-view (HarfBuzz) test-1.0")
    raise SystemExit(0)

log = Path(__file__).with_name("calls.jsonl")
with log.open("a", encoding="utf-8") as output:
    output.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")

ppem_arg = next(argument for argument in sys.argv if argument.startswith("--font-ppem="))
ppem = int(ppem_arg.split("=", 1)[1])
if ppem == {failure}:
    print("synthetic raster failure", file=sys.stderr)
    raise SystemExit(23)

output_arg = next(argument for argument in sys.argv if argument.startswith("--output-file="))
Path(output_arg.split("=", 1)[1]).write_bytes(b"\\x89PNG\\r\\n\\x1a\\nFAKE")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _calls(executable: Path) -> list[list[str]]:
    return [
        json.loads(line)
        for line in executable.with_name("calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_default_ppems_cover_low_text_sizes() -> None:
    assert DEFAULT_PPEMS == (9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 32, 48)


def test_render_raster_proof_uses_native_freetype_hints_and_stable_outputs(
    tmp_path: Path,
) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"not a real font; the injected rasterizer owns validation")
    executable = _fake_hb_view(tmp_path)
    text = "熊丸 with spaces; $(never-a-shell)"

    summary = render_raster_proof(
        font,
        tmp_path / "proof-a",
        text,
        ppems=(9, 12),
        location={"wght": 500, "opsz": 9},
        executable=executable,
    )

    assert summary.ppems == (9, 12)
    assert [path.name for path in summary.images] == ["ppem-009.png", "ppem-012.png"]
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in summary.images)

    calls = _calls(executable)
    assert len(calls) == 2
    for ppem, arguments in zip((9, 12), calls, strict=True):
        assert "--face-loader=ft" in arguments
        assert "--font-funcs=ft" in arguments
        assert "--ft-load-flags=0" in arguments
        assert f"--font-size={ppem}" in arguments
        assert f"--font-ppem={ppem}" in arguments
        assert "--variations=opsz=9,wght=500" in arguments
        assert "--output-format=png" in arguments
        assert arguments[-2:] == [str(font), text]

    manifest_text = summary.manifest.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["font"] == {
        "filename": "Example.ttf",
        "sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
    }
    assert manifest["ppems"] == [9, 12]
    assert manifest["location"] == {"opsz": 9.0, "wght": 500.0}
    assert manifest["rasterizer"] == {
        "executable": "hb-view",
        "version": "hb-view (HarfBuzz) test-1.0",
        "face_loader": "ft",
        "font_funcs": "ft",
        "ft_load_flags": 0,
        "font_size": "<ppem>",
        "font_ppem": "<ppem>",
        "output_format": "png",
        "fixed_arguments": [
            "--face-loader=ft",
            "--font-funcs=ft",
            "--ft-load-flags=0",
            "--output-format=png",
        ],
    }
    assert manifest["images"] == [
        {"path": "images/ppem-009.png", "ppem": 9},
        {"path": "images/ppem-012.png", "ppem": 12},
    ]
    assert str(tmp_path) not in manifest_text

    index_text = summary.index.read_text(encoding="utf-8")
    assert "images/ppem-009.png" in index_text
    assert "images/ppem-012.png" in index_text
    assert "opsz=9,wght=500" in index_text
    assert "$(never-a-shell)" in index_text


def test_manifest_and_index_are_deterministic_across_output_directories(tmp_path: Path) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"font bytes")
    executable = _fake_hb_view(tmp_path)

    first = render_raster_proof(
        font,
        tmp_path / "first",
        "ABC",
        ppems=(9,),
        executable=executable,
    )
    second = render_raster_proof(
        font,
        tmp_path / "second",
        "ABC",
        ppems=(9,),
        executable=executable,
    )

    assert first.manifest.read_bytes() == second.manifest.read_bytes()
    assert first.index.read_bytes() == second.index.read_bytes()


def test_successful_rerun_removes_stale_managed_images(tmp_path: Path) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"font bytes")
    executable = _fake_hb_view(tmp_path)
    output = tmp_path / "proof"

    render_raster_proof(font, output, "ABC", ppems=(9, 10, 11), executable=executable)
    unrelated = output / "images" / "keep-me.png"
    unrelated.write_bytes(b"user-owned")

    summary = render_raster_proof(font, output, "ABC", ppems=(9,), executable=executable)

    assert [path.name for path in summary.images] == ["ppem-009.png"]
    assert sorted(path.name for path in (output / "images").iterdir()) == [
        "keep-me.png",
        "ppem-009.png",
    ]


def test_rasterizer_failure_is_clear_and_does_not_publish_summary(tmp_path: Path) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"font bytes")
    executable = _fake_hb_view(tmp_path, fail_ppem=10)
    output = tmp_path / "proof"

    with pytest.raises(RasterProofError, match=r"10 ppem.*status 23.*synthetic raster failure"):
        render_raster_proof(
            font,
            output,
            "ABC",
            ppems=(9, 10, 11),
            executable=executable,
        )

    assert not (output / "manifest.json").exists()
    assert not (output / "index.html").exists()
    assert not (output / "images").exists()


def test_failed_rerun_keeps_previous_complete_proof(tmp_path: Path) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"font bytes")
    executable = _fake_hb_view(tmp_path)
    output = tmp_path / "proof"
    original = render_raster_proof(
        font,
        output,
        "original",
        ppems=(9, 10),
        executable=executable,
    )
    original_manifest = original.manifest.read_bytes()
    original_images = {path.name: path.read_bytes() for path in original.images}
    _fake_hb_view(tmp_path, fail_ppem=10)

    with pytest.raises(RasterProofError):
        render_raster_proof(
            font,
            output,
            "replacement",
            ppems=(9, 10),
            executable=executable,
        )

    assert original.manifest.read_bytes() == original_manifest
    assert {path.name: path.read_bytes() for path in original.images} == original_images


def test_missing_rasterizer_has_actionable_error(tmp_path: Path) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"font bytes")

    with pytest.raises(RasterProofError, match="executable was not found"):
        render_raster_proof(
            font,
            tmp_path / "proof",
            "ABC",
            ppems=(9,),
            executable=tmp_path / "missing-hb-view",
        )


def test_hung_rasterizer_times_out_with_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    font = tmp_path / "Example.ttf"
    font.write_bytes(b"font bytes")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 60
        raise subprocess.TimeoutExpired(cmd="hb-view", timeout=60)

    monkeypatch.setattr("kumamaru.raster_proof.subprocess.run", fake_run)

    with pytest.raises(RasterProofError, match=r"exceeded 60 seconds"):
        render_raster_proof(font, tmp_path / "proof", "ABC", ppems=(9,))


@pytest.mark.parametrize(
    ("ppems", "message"),
    [
        ((), "at least one"),
        ((0,), "positive integers"),
        ((9, 9), "duplicates"),
        ((9.0,), "positive integers"),
    ],
)
def test_invalid_ppems_are_rejected(
    tmp_path: Path, ppems: tuple[object, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        render_raster_proof(
            tmp_path / "unused.ttf",
            tmp_path / "proof",
            "ABC",
            ppems=ppems,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "location",
    [
        {"weight": 400},
        {"wght": float("nan")},
        {"wght": True},
    ],
)
def test_invalid_variation_locations_are_rejected(
    tmp_path: Path, location: dict[str, float]
) -> None:
    with pytest.raises(ValueError, match="Variation"):
        render_raster_proof(
            tmp_path / "unused.ttf",
            tmp_path / "proof",
            "ABC",
            ppems=(9,),
            location=location,
        )
