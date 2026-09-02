"""Load and fingerprint synthetic OrbitGuard scenarios."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .conjunction import MODEL_VERSION, ConjunctionScenario

SCENARIO_FIELDS = {
    "scenario_id",
    "seed",
    "synthetic",
    "model",
    "protected_asset",
    "protected_service",
    "secondary_object",
    "orbit_context",
    "relative_position_m",
    "relative_velocity_mps",
    "illustrative_buffer_m",
    "options",
}


def load_scenario(path: str | Path) -> ConjunctionScenario:
    scenario_path = Path(path)
    with scenario_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("scenario file must contain a JSON object")
    missing = SCENARIO_FIELDS - data.keys()
    unexpected = data.keys() - SCENARIO_FIELDS
    if missing:
        raise ValueError(f"scenario is missing fields: {', '.join(sorted(missing))}")
    if unexpected:
        raise ValueError(f"scenario has unexpected fields: {', '.join(sorted(unexpected))}")
    if data["model"] != MODEL_VERSION:
        raise ValueError(
            f"scenario model must be {MODEL_VERSION!r}, got {data['model']!r}"
        )
    return ConjunctionScenario.from_mapping(data)


def scenario_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
