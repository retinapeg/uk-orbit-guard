"""Build the bundled thousand-object debris fixture from downloaded OMM JSON."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from orbit_guard.debris_catalogue import DebrisCatalogue, DebrisRecord, GROUP_URLS
from orbit_guard.public_data import OmmRecord


INPUTS = {
    "FENGYUN-1C-DEBRIS": "orbitguard-fengyun.json",
    "IRIDIUM-33-DEBRIS": "orbitguard-iridium.json",
    "COSMOS-2251-DEBRIS": "orbitguard-cosmos.json",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    args = parser.parse_args()

    try:
        retrieved_at = datetime.fromisoformat(
            args.retrieved_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        parser.error(f"--retrieved-at must be ISO-8601: {exc}")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        parser.error("--retrieved-at must include an explicit UTC offset")
    retrieved_at = retrieved_at.astimezone(timezone.utc)
    if retrieved_at > datetime.now(timezone.utc):
        parser.error("--retrieved-at cannot be in the future")
    records: list[DebrisRecord] = []
    seen: set[int] = set()
    for group, filename in INPUTS.items():
        values = json.loads((args.input_dir / filename).read_text(encoding="utf-8"))
        for raw in values:
            omm = OmmRecord.from_mapping(raw)
            if omm.norad_catalog_id in seen:
                continue
            seen.add(omm.norad_catalog_id)
            records.append(DebrisRecord(group, omm))
    catalogue = DebrisCatalogue.build(
        records,
        retrieved_at_utc=retrieved_at,
        source_urls=tuple(GROUP_URLS.values()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(catalogue.to_json(), encoding="utf-8")
    print(
        json.dumps(
            {
                "records": len(catalogue.records),
                "sha256": catalogue.content_sha256,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
