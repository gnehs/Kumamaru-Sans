"""Shared deterministic filter utilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def setting(config: object, name: str, default: Any) -> Any:
    if isinstance(config, Mapping):
        return config.get(name, default)
    return getattr(config, name, default)


def stable_candidate_id(
    *,
    source_sha256: str,
    glyph_name: str,
    kind: str,
    contour_index: int,
    segment_start: int,
    segment_end: int,
    geometry: Mapping[str, float | int | str],
) -> str:
    payload = {
        "source_sha256": source_sha256.lower(),
        "glyph_name": glyph_name,
        "kind": kind,
        "contour_index": contour_index,
        "segment_start": segment_start,
        "segment_end": segment_end,
        "geometry": geometry,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{kind}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"
