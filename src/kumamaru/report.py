"""Small, deterministic helpers for machine-readable Kumamaru reports.

The build pipeline deliberately keeps reports as ordinary JSON dictionaries.  This
module provides the boring-but-important boundary around them: JSON only contains
portable values, report files are written atomically, and callers can accumulate
warnings without relying on a logging configuration.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def json_value(value: Any) -> JsonValue:
    """Convert a report value to strict, portable JSON.

    Non-finite floats are rejected instead of silently becoming JavaScript's
    non-standard ``NaN``/``Infinity`` literals.  Paths, enums and dataclasses are
    common in the pipeline, so supporting them here prevents report generation
    from becoming an afterthought in each command.
    """

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"JSON reports cannot contain a non-finite float: {value!r}")
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [json_value(item) for item in value]
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def write_json(path: str | Path, report: Mapping[str, Any]) -> None:
    """Write a UTF-8 JSON report atomically, with stable formatting."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(json_value(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=destination.parent, delete=False
    ) as temporary:
        temporary.write(encoded)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)


def read_json(path: str | Path) -> dict[str, Any]:
    """Read a JSON object report and reject top-level arrays/scalars early."""

    source = Path(path)
    with source.open(encoding="utf-8") as report_file:
        loaded = json.load(report_file)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object in {source}, got {type(loaded).__name__}")
    return loaded


class ReportCollector:
    """Minimal structured report builder shared by commands and filters."""

    def __init__(self, **initial: Any) -> None:
        self.data: MutableMapping[str, Any] = dict(initial)
        self.data.setdefault("warnings", [])
        self.data.setdefault("errors", [])

    def warning(self, message: str, *, glyph_name: str | None = None, **details: Any) -> None:
        item: dict[str, Any] = {"message": message, **details}
        if glyph_name is not None:
            item["glyph_name"] = glyph_name
        self.data["warnings"].append(item)

    def error(self, message: str, *, glyph_name: str | None = None, **details: Any) -> None:
        item: dict[str, Any] = {"message": message, **details}
        if glyph_name is not None:
            item["glyph_name"] = glyph_name
        self.data["errors"].append(item)

    def add(self, key: str, value: Any) -> None:
        self.data[key] = value

    def as_dict(self) -> dict[str, JsonValue]:
        return json_value(dict(self.data))  # type: ignore[return-value]
