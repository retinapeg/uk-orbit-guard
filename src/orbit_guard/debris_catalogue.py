"""Bounded, cache-first public debris catalogue for the command globe.

The catalogue combines three public CelesTrak debris-event GP/OMM groups.  It
is a visual space-domain-awareness layer only: mean elements are not precision
ephemerides and are never passed into the synthetic RL training job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .public_data import (
    HttpResponse,
    OmmRecord,
    PublicDataError,
    PublicDataFetchError,
    PublicDataValidationError,
    propagate_omm_sgp4,
    urllib_transport,
)


UTC = timezone.utc
SCHEMA_VERSION = 1
RECORD_TYPE = "uk-orbit-guard-public-debris-catalogue"
REFRESH_TTL = timedelta(hours=12)
MAX_GROUP_BYTES = 4_000_000
MAX_RECORDS = 5_000
MAX_SNAPSHOT_BYTES = 4_000_000

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = (
    REPOSITORY_ROOT / "data" / "debris_catalogue_snapshot_2026-09-03.json"
)
DEFAULT_CACHE_PATH = REPOSITORY_ROOT / ".cache" / "debris_catalogue.json"

GROUP_URLS: dict[str, str] = {
    "FENGYUN-1C-DEBRIS": (
        "https://celestrak.org/NORAD/elements/gp.php?"
        "GROUP=FENGYUN-1C-DEBRIS&FORMAT=JSON"
    ),
    "IRIDIUM-33-DEBRIS": (
        "https://celestrak.org/NORAD/elements/gp.php?"
        "GROUP=IRIDIUM-33-DEBRIS&FORMAT=JSON"
    ),
    "COSMOS-2251-DEBRIS": (
        "https://celestrak.org/NORAD/elements/gp.php?"
        "GROUP=COSMOS-2251-DEBRIS&FORMAT=JSON"
    ),
}


def debris_urllib_transport(url: str, *, max_bytes: int) -> HttpResponse:
    """Allow the three larger public debris groups a bounded 15-second fetch."""

    return urllib_transport(
        url,
        max_bytes=max_bytes,
        timeout_seconds=15,
    )


@dataclass(frozen=True)
class DebrisRecord:
    source_group: str
    omm: OmmRecord

    def to_mapping(self) -> dict[str, Any]:
        return {"source_group": self.source_group, "omm": self.omm.to_mapping()}


@dataclass(frozen=True)
class DebrisCatalogue:
    retrieved_at_utc: datetime
    source_urls: tuple[str, ...]
    records: tuple[DebrisRecord, ...]
    content_sha256: str
    schema_version: int = SCHEMA_VERSION
    record_type: str = RECORD_TYPE

    @classmethod
    def build(
        cls,
        records: Sequence[DebrisRecord],
        *,
        retrieved_at_utc: datetime,
        source_urls: Sequence[str],
    ) -> "DebrisCatalogue":
        values = _validate_records(records)
        retrieved = _utc(retrieved_at_utc, "retrieved_at_utc")
        urls = tuple(source_urls)
        if urls != tuple(GROUP_URLS.values()):
            raise PublicDataValidationError("debris source URLs do not match allowlist")
        document = _content_document(values, retrieved, urls)
        digest = _content_sha256(document)
        return cls(retrieved, urls, values, digest)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DebrisCatalogue":
        expected = {
            "schema_version",
            "record_type",
            "retrieved_at_utc",
            "source_urls",
            "records",
            "content_sha256",
        }
        if set(value) != expected:
            raise PublicDataValidationError("debris snapshot schema mismatch")
        if value["schema_version"] != SCHEMA_VERSION or value["record_type"] != RECORD_TYPE:
            raise PublicDataValidationError("unsupported debris snapshot version")
        raw_records = value["records"]
        if not isinstance(raw_records, list):
            raise PublicDataValidationError("debris records must be a list")
        records: list[DebrisRecord] = []
        for index, raw in enumerate(raw_records):
            if not isinstance(raw, Mapping) or set(raw) != {"source_group", "omm"}:
                raise PublicDataValidationError(f"debris record {index} schema mismatch")
            group = raw["source_group"]
            if group not in GROUP_URLS:
                raise PublicDataValidationError(f"debris record {index} group is invalid")
            omm = raw["omm"]
            if not isinstance(omm, Mapping):
                raise PublicDataValidationError(f"debris record {index} OMM is invalid")
            records.append(DebrisRecord(str(group), OmmRecord.from_mapping(omm)))
        retrieved = _parse_utc(value["retrieved_at_utc"], "retrieved_at_utc")
        urls_raw = value["source_urls"]
        if not isinstance(urls_raw, list) or tuple(urls_raw) != tuple(GROUP_URLS.values()):
            raise PublicDataValidationError("debris source URLs do not match allowlist")
        values = _validate_records(records)
        document = _content_document(values, retrieved, tuple(urls_raw))
        digest = value["content_sha256"]
        if not isinstance(digest, str) or digest != _content_sha256(document):
            raise PublicDataValidationError("debris snapshot hash does not match")
        return cls(retrieved, tuple(urls_raw), values, digest)

    @classmethod
    def from_json(cls, payload: bytes | str) -> "DebrisCatalogue":
        raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise PublicDataValidationError("debris snapshot exceeds size bound")
        try:
            decoded = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicDataValidationError("debris snapshot is not valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise PublicDataValidationError("debris snapshot must be an object")
        return cls.from_mapping(decoded)

    @classmethod
    def from_path(cls, path: Path) -> "DebrisCatalogue":
        try:
            return cls.from_json(path.read_bytes())
        except OSError as exc:
            raise PublicDataError(f"could not read debris snapshot: {path}") from exc

    def to_mapping(self) -> dict[str, Any]:
        document = _content_document(self.records, self.retrieved_at_utc, self.source_urls)
        return {**document, "content_sha256": self.content_sha256}

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":")) + "\n"

    def is_fresh(self, now: datetime, ttl: timedelta = REFRESH_TTL) -> bool:
        age = _utc(now, "now") - self.retrieved_at_utc
        return timedelta(0) <= age <= ttl


@dataclass(frozen=True)
class DebrisLoadResult:
    catalogue: DebrisCatalogue
    origin: str
    fresh: bool
    warning: str | None = None


def fetch_catalogue(
    *,
    transport=debris_urllib_transport,
    retrieved_at_utc: datetime | None = None,
) -> DebrisCatalogue:
    records: list[DebrisRecord] = []
    seen: set[int] = set()
    for group, url in GROUP_URLS.items():
        response: HttpResponse = transport(url, max_bytes=MAX_GROUP_BYTES)
        if response.status_code != 200:
            raise PublicDataFetchError(
                f"CelesTrak {group} returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if response.final_url != url:
            raise PublicDataFetchError(f"CelesTrak {group} redirected unexpectedly")
        if len(response.body) > MAX_GROUP_BYTES:
            raise PublicDataValidationError(
                f"CelesTrak {group} response exceeds the byte limit"
            )
        content_type = str(response.headers.get("content-type", "")).lower()
        if content_type and "json" not in content_type:
            raise PublicDataValidationError(
                f"CelesTrak {group} returned a non-JSON content type"
            )
        try:
            decoded = json.loads(
                response.body.decode("utf-8"), parse_constant=_reject_constant
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicDataValidationError(f"CelesTrak {group} returned invalid JSON") from exc
        if not isinstance(decoded, list):
            raise PublicDataValidationError(f"CelesTrak {group} did not return an array")
        for raw in decoded:
            if not isinstance(raw, Mapping):
                raise PublicDataValidationError(f"CelesTrak {group} contains a non-object")
            omm = OmmRecord.from_mapping(raw)
            if omm.norad_catalog_id in seen:
                continue
            seen.add(omm.norad_catalog_id)
            records.append(DebrisRecord(group, omm))
            if len(records) > MAX_RECORDS:
                raise PublicDataValidationError("debris catalogue exceeds record bound")
    return DebrisCatalogue.build(
        records,
        retrieved_at_utc=retrieved_at_utc or datetime.now(UTC),
        source_urls=tuple(GROUP_URLS.values()),
    )


def load_catalogue(
    *,
    allow_network: bool = False,
    now: datetime | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    transport=debris_urllib_transport,
) -> DebrisLoadResult:
    checked_at = _utc(now or datetime.now(UTC), "now")
    cached: DebrisCatalogue | None = None
    fixture: DebrisCatalogue | None = None
    warnings: list[str] = []
    if cache_path.is_file():
        try:
            cached = DebrisCatalogue.from_path(cache_path)
        except PublicDataError as exc:
            warnings.append(f"invalid cache ignored: {exc}")
    if cached is not None and cached.retrieved_at_utc > checked_at:
        warnings.append("future-dated cache ignored: retrieval UTC is ahead of host UTC")
        cached = None
    if cached is not None and cached.is_fresh(checked_at):
        return DebrisLoadResult(cached, "cache", True, _join_warnings(warnings))

    if fixture_path.is_file():
        try:
            fixture = DebrisCatalogue.from_path(fixture_path)
        except PublicDataError as exc:
            warnings.append(f"invalid bundled replay ignored: {exc}")
        if fixture is not None and fixture.retrieved_at_utc > checked_at:
            warnings.append(
                "future-dated bundled replay ignored: retrieval UTC is ahead of host UTC"
            )
            fixture = None

    candidates = [
        ("stale cache", cached),
        ("bundled replay", fixture),
    ]
    available = [(origin, item) for origin, item in candidates if item is not None]
    if available:
        fallback_origin, fallback = max(
            available,
            key=lambda pair: pair[1].retrieved_at_utc,
        )
    else:
        fallback_origin, fallback = "unavailable", None

    if allow_network:
        try:
            live = fetch_catalogue(
                transport=transport,
                retrieved_at_utc=checked_at,
            )
            _atomic_write(cache_path, live.to_json())
            return DebrisLoadResult(live, "network", True, None)
        except (PublicDataError, OSError) as exc:
            if fallback is None:
                raise
            return DebrisLoadResult(
                fallback,
                fallback_origin,
                fallback.is_fresh(checked_at),
                _join_warnings(
                    [
                        *warnings,
                        f"network refresh failed; retained {fallback_origin}: {exc}",
                    ]
                ),
            )
    if fallback is None:
        detail = _join_warnings(warnings)
        raise PublicDataError(
            "no validated debris catalogue is available"
            + (f": {detail}" if detail else "")
        )
    return DebrisLoadResult(
        fallback,
        fallback_origin,
        fallback.is_fresh(checked_at),
        _join_warnings(warnings),
    )


def catalogue_globe_records(
    catalogue: DebrisCatalogue,
    *,
    at: datetime,
) -> list[dict[str, Any]]:
    """Propagate public mean elements to Earth-centred display positions."""

    display_at = _utc(at, "at")
    output: list[dict[str, Any]] = []
    for record in catalogue.records:
        try:
            state = propagate_omm_sgp4(record.omm, display_at)
        except PublicDataError:
            continue
        output.append(
            {
                "object_id": record.omm.norad_catalog_id,
                "name": record.omm.object_name,
                "object_type": (
                    "DEBRIS FRAGMENT"
                    if record.omm.object_name.endswith(" DEB")
                    else "PARENT OBJECT"
                ),
                "position_km": list(state.position_km),
                "element_epoch": record.omm.epoch.isoformat().replace("+00:00", "Z"),
                "source_group": record.source_group,
                "orbit_regime": "PUBLIC GP/OMM",
            }
        )
    return output


def _content_document(
    records: Sequence[DebrisRecord],
    retrieved_at: datetime,
    urls: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "retrieved_at_utc": retrieved_at.isoformat().replace("+00:00", "Z"),
        "source_urls": list(urls),
        "records": [record.to_mapping() for record in records],
    }


def _join_warnings(values: Sequence[str]) -> str | None:
    cleaned = [value for value in values if value]
    return "; ".join(cleaned) if cleaned else None


def _content_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _validate_records(records: Sequence[DebrisRecord]) -> tuple[DebrisRecord, ...]:
    if not 1_000 <= len(records) <= MAX_RECORDS:
        raise PublicDataValidationError(
            f"debris catalogue must contain 1,000 to {MAX_RECORDS:,} records"
        )
    seen: set[int] = set()
    for item in records:
        if not isinstance(item, DebrisRecord) or item.source_group not in GROUP_URLS:
            raise PublicDataValidationError("debris record is invalid")
        if item.omm.norad_catalog_id in seen:
            raise PublicDataValidationError("debris catalogue contains a duplicate NORAD ID")
        seen.add(item.omm.norad_catalog_id)
    return tuple(records)


def _parse_utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise PublicDataValidationError(f"{name} must be text")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PublicDataValidationError(f"{name} is invalid") from exc
    return _utc(parsed, name)


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PublicDataValidationError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _reject_constant(value: str) -> None:
    raise PublicDataValidationError(f"invalid JSON number: {value}")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
