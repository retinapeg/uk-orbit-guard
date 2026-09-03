"""Cache-first public orbit context for the UK Orbit Guard demo.

The data handled here are public GP/OMM mean elements and public SOCRATES
proximity candidates.  They are suitable for provenance-rich visualisation and
education, not operational conjunction assessment or spacecraft commanding.

Nothing in this module performs a network request by default.  A caller must
both opt in with ``allow_network=True`` and provide a transport explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Literal, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import json
import math
import os
import re
import ssl
import tempfile
import warnings


UTC = timezone.utc
SCHEMA_VERSION = 1
REFRESH_TTL = timedelta(hours=2)
PUBLIC_CONTEXT = (
    "Public GP/OMM proximity context only; not operational collision assessment."
)

MAX_OMM_BYTES = 1_000_000
MAX_OMM_RECORDS = 250
MAX_SOCRATES_HTML_BYTES = 1_000_000
MAX_SOCRATES_RECORDS = 100
MAX_SOCRATES_CELL_CHARACTERS = 32_768
MAX_SNAPSHOT_BYTES = 2_000_000

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = (
    REPOSITORY_ROOT / "data" / "public_orbit_snapshot_2026-09-03.json"
)
DEFAULT_CACHE_PATH = REPOSITORY_ROOT / ".cache" / "public_orbit_snapshot.json"


class PublicDataError(RuntimeError):
    """Base error for public-data loading, validation, and refresh."""


class PublicDataValidationError(PublicDataError, ValueError):
    """Raised when untrusted public data fail strict validation."""


class PublicDataFetchError(PublicDataError):
    """A single public feed fetch failed; callers must decide on fallback."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class Sgp4UnavailableError(PublicDataError):
    """The optional ``sgp4`` dependency is not installed."""


class Sgp4PropagationError(PublicDataError):
    """SGP4 reported an error for the supplied public mean elements."""


def _require_exact_fields(
    data: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(data)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected fields: {', '.join(unexpected)}")
        raise PublicDataValidationError(f"{label} has {'; '.join(details)}")


def _strict_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise PublicDataValidationError(f"{name} must be a JSON integer")
    if not minimum <= value <= maximum:
        raise PublicDataValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _strict_float(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    maximum_exclusive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicDataValidationError(f"{name} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise PublicDataValidationError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise PublicDataValidationError(f"{name} must be at least {minimum}")
    if maximum is not None:
        outside = result >= maximum if maximum_exclusive else result > maximum
        if outside:
            comparison = "less than" if maximum_exclusive else "at most"
            raise PublicDataValidationError(f"{name} must be {comparison} {maximum}")
    return result


def _parse_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PublicDataValidationError(f"{name} must be a non-empty UTC timestamp")
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise PublicDataValidationError(f"{name} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.utcoffset() != timedelta(0):
        raise PublicDataValidationError(f"{name} must use UTC")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicDataValidationError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_display_utc(value: str, name: str) -> datetime:
    for pattern in (
        "%Y %b %d %H:%M:%S.%f",
        "%Y %b %d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise PublicDataValidationError(f"{name} has an invalid CelesTrak timestamp")


def _clean_text(value: object, name: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise PublicDataValidationError(f"{name} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise PublicDataValidationError(f"{name} must not be empty")
    if len(cleaned) > maximum or any(ord(char) < 32 for char in cleaned):
        raise PublicDataValidationError(f"{name} is invalid or too long")
    return cleaned


OMM_FIELDS = frozenset(
    {
        "OBJECT_NAME",
        "OBJECT_ID",
        "EPOCH",
        "MEAN_MOTION",
        "ECCENTRICITY",
        "INCLINATION",
        "RA_OF_ASC_NODE",
        "ARG_OF_PERICENTER",
        "MEAN_ANOMALY",
        "EPHEMERIS_TYPE",
        "CLASSIFICATION_TYPE",
        "NORAD_CAT_ID",
        "ELEMENT_SET_NO",
        "REV_AT_EPOCH",
        "BSTAR",
        "MEAN_MOTION_DOT",
        "MEAN_MOTION_DDOT",
    }
)

OBJECT_ID_PATTERN = re.compile(r"^\d{4}-\d{3}[A-Z]{1,3}$")


@dataclass(frozen=True)
class OmmRecord:
    """One strictly validated public CelesTrak GP record in OMM-JSON fields."""

    object_name: str
    object_id: str | None
    epoch: datetime
    mean_motion: float
    eccentricity: float
    inclination: float
    right_ascension_of_ascending_node: float
    argument_of_pericenter: float
    mean_anomaly: float
    ephemeris_type: int
    classification_type: str
    norad_catalog_id: int
    element_set_number: int
    revolution_at_epoch: int
    bstar: float
    mean_motion_dot: float
    mean_motion_ddot: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "OmmRecord":
        _require_exact_fields(data, OMM_FIELDS, "OMM record")
        object_id_value = data["OBJECT_ID"]
        if object_id_value is not None:
            object_id = _clean_text(object_id_value, "OBJECT_ID", maximum=16)
            if not OBJECT_ID_PATTERN.fullmatch(object_id):
                raise PublicDataValidationError(
                    "OBJECT_ID must be a full YYYY-NNN piece designator or null"
                )
        else:
            object_id = None

        classification = _clean_text(
            data["CLASSIFICATION_TYPE"], "CLASSIFICATION_TYPE", maximum=1
        )
        if classification != "U":
            raise PublicDataValidationError(
                "public GP fixture accepts unclassified records only"
            )

        return cls(
            object_name=_clean_text(data["OBJECT_NAME"], "OBJECT_NAME", maximum=96),
            object_id=object_id,
            epoch=_parse_utc(data["EPOCH"], "EPOCH"),
            mean_motion=_strict_float(
                data["MEAN_MOTION"], "MEAN_MOTION", minimum=0.0
            ),
            eccentricity=_strict_float(
                data["ECCENTRICITY"],
                "ECCENTRICITY",
                minimum=0.0,
                maximum=1.0,
                maximum_exclusive=True,
            ),
            inclination=_strict_float(
                data["INCLINATION"], "INCLINATION", minimum=0.0, maximum=180.0
            ),
            right_ascension_of_ascending_node=_strict_float(
                data["RA_OF_ASC_NODE"],
                "RA_OF_ASC_NODE",
                minimum=0.0,
                maximum=360.0,
                maximum_exclusive=True,
            ),
            argument_of_pericenter=_strict_float(
                data["ARG_OF_PERICENTER"],
                "ARG_OF_PERICENTER",
                minimum=0.0,
                maximum=360.0,
                maximum_exclusive=True,
            ),
            mean_anomaly=_strict_float(
                data["MEAN_ANOMALY"],
                "MEAN_ANOMALY",
                minimum=0.0,
                maximum=360.0,
                maximum_exclusive=True,
            ),
            ephemeris_type=_strict_int(
                data["EPHEMERIS_TYPE"], "EPHEMERIS_TYPE", minimum=0, maximum=9
            ),
            classification_type=classification,
            norad_catalog_id=_strict_int(
                data["NORAD_CAT_ID"],
                "NORAD_CAT_ID",
                minimum=1,
                maximum=999_999_999,
            ),
            element_set_number=_strict_int(
                data["ELEMENT_SET_NO"],
                "ELEMENT_SET_NO",
                minimum=0,
                maximum=999_999_999,
            ),
            revolution_at_epoch=_strict_int(
                data["REV_AT_EPOCH"],
                "REV_AT_EPOCH",
                minimum=0,
                maximum=999_999_999,
            ),
            bstar=_strict_float(data["BSTAR"], "BSTAR"),
            mean_motion_dot=_strict_float(
                data["MEAN_MOTION_DOT"], "MEAN_MOTION_DOT"
            ),
            mean_motion_ddot=_strict_float(
                data["MEAN_MOTION_DDOT"], "MEAN_MOTION_DDOT"
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "OBJECT_NAME": self.object_name,
            "OBJECT_ID": self.object_id,
            "EPOCH": _format_utc(self.epoch),
            "MEAN_MOTION": self.mean_motion,
            "ECCENTRICITY": self.eccentricity,
            "INCLINATION": self.inclination,
            "RA_OF_ASC_NODE": self.right_ascension_of_ascending_node,
            "ARG_OF_PERICENTER": self.argument_of_pericenter,
            "MEAN_ANOMALY": self.mean_anomaly,
            "EPHEMERIS_TYPE": self.ephemeris_type,
            "CLASSIFICATION_TYPE": self.classification_type,
            "NORAD_CAT_ID": self.norad_catalog_id,
            "ELEMENT_SET_NO": self.element_set_number,
            "REV_AT_EPOCH": self.revolution_at_epoch,
            "BSTAR": self.bstar,
            "MEAN_MOTION_DOT": self.mean_motion_dot,
            "MEAN_MOTION_DDOT": self.mean_motion_ddot,
        }


def _reject_json_constant(value: str) -> None:
    raise PublicDataValidationError(f"invalid JSON numeric constant: {value}")


def _bounded_payload(payload: str | bytes, *, maximum: int, label: str) -> str:
    if isinstance(payload, bytes):
        raw = payload
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PublicDataValidationError(f"{label} must be UTF-8") from exc
    elif isinstance(payload, str):
        text = payload
        raw = payload.encode("utf-8")
    else:
        raise PublicDataValidationError(f"{label} must be text or bytes")
    if len(raw) > maximum:
        raise PublicDataValidationError(f"{label} exceeds {maximum} bytes")
    return text


def parse_omm_records(
    records: Iterable[Mapping[str, object]], *, max_records: int = MAX_OMM_RECORDS
) -> tuple[OmmRecord, ...]:
    if not 1 <= max_records <= MAX_OMM_RECORDS:
        raise ValueError(f"max_records must be between 1 and {MAX_OMM_RECORDS}")
    parsed: list[OmmRecord] = []
    seen: set[int] = set()
    for raw in records:
        if len(parsed) >= max_records:
            raise PublicDataValidationError(
                f"OMM response exceeds the {max_records}-record bound"
            )
        record = OmmRecord.from_mapping(raw)
        if record.norad_catalog_id in seen:
            raise PublicDataValidationError(
                f"duplicate NORAD_CAT_ID: {record.norad_catalog_id}"
            )
        seen.add(record.norad_catalog_id)
        parsed.append(record)
    if not parsed:
        raise PublicDataValidationError("OMM response contains no records")
    return tuple(parsed)


def parse_omm_json(
    payload: str | bytes, *, max_records: int = MAX_OMM_RECORDS
) -> tuple[OmmRecord, ...]:
    """Parse a bounded CelesTrak JSON response and reject schema drift."""

    text = _bounded_payload(payload, maximum=MAX_OMM_BYTES, label="OMM JSON")
    try:
        decoded = json.loads(text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise PublicDataValidationError("OMM response is not valid JSON") from exc
    if not isinstance(decoded, list) or not all(
        isinstance(item, Mapping) for item in decoded
    ):
        raise PublicDataValidationError("OMM response must be a JSON array of objects")
    return parse_omm_records(decoded, max_records=max_records)


SOCRATES_FIELDS = frozenset(
    {
        "first_norad_catalog_id",
        "first_object_name",
        "first_operational_status",
        "first_days_since_epoch",
        "second_norad_catalog_id",
        "second_object_name",
        "second_operational_status",
        "second_days_since_epoch",
        "tca_utc",
        "minimum_range_km",
        "relative_speed_km_s",
        "public_maximum_probability",
        "dilution_threshold_km",
        "context",
        "operational_collision_assessment",
    }
)

STATUS_PATTERN = re.compile(r"^(?P<name>.+?)\s+\[(?P<status>[+PBSXD?\-])\]$")
ALLOWED_STATUSES = frozenset("+PBSXD?-")


@dataclass(frozen=True)
class SocratesRecord:
    """One public-GP SOCRATES proximity candidate, never a flight warning."""

    first_norad_catalog_id: int
    first_object_name: str
    first_operational_status: str
    first_days_since_epoch: float
    second_norad_catalog_id: int
    second_object_name: str
    second_operational_status: str
    second_days_since_epoch: float
    tca_utc: datetime
    minimum_range_km: float
    relative_speed_km_s: float
    public_maximum_probability: float
    dilution_threshold_km: float
    context: str = PUBLIC_CONTEXT
    operational_collision_assessment: bool = False

    def __post_init__(self) -> None:
        if self.context != PUBLIC_CONTEXT:
            raise PublicDataValidationError("SOCRATES context label must be preserved")
        if self.operational_collision_assessment is not False:
            raise PublicDataValidationError(
                "public SOCRATES records cannot be marked operational"
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "SocratesRecord":
        _require_exact_fields(data, SOCRATES_FIELDS, "SOCRATES record")
        if data["context"] != PUBLIC_CONTEXT:
            raise PublicDataValidationError("SOCRATES context label must be preserved")
        if data["operational_collision_assessment"] is not False:
            raise PublicDataValidationError(
                "operational_collision_assessment must be false"
            )
        first_status = _clean_text(
            data["first_operational_status"],
            "first_operational_status",
            maximum=1,
        )
        second_status = _clean_text(
            data["second_operational_status"],
            "second_operational_status",
            maximum=1,
        )
        if first_status not in ALLOWED_STATUSES or second_status not in ALLOWED_STATUSES:
            raise PublicDataValidationError("unrecognised CelesTrak operational-status code")
        return cls(
            first_norad_catalog_id=_strict_int(
                data["first_norad_catalog_id"],
                "first_norad_catalog_id",
                minimum=1,
                maximum=999_999_999,
            ),
            first_object_name=_clean_text(
                data["first_object_name"], "first_object_name", maximum=96
            ),
            first_operational_status=first_status,
            first_days_since_epoch=_strict_float(
                data["first_days_since_epoch"],
                "first_days_since_epoch",
                minimum=-3650.0,
                maximum=3650.0,
            ),
            second_norad_catalog_id=_strict_int(
                data["second_norad_catalog_id"],
                "second_norad_catalog_id",
                minimum=1,
                maximum=999_999_999,
            ),
            second_object_name=_clean_text(
                data["second_object_name"], "second_object_name", maximum=96
            ),
            second_operational_status=second_status,
            second_days_since_epoch=_strict_float(
                data["second_days_since_epoch"],
                "second_days_since_epoch",
                minimum=-3650.0,
                maximum=3650.0,
            ),
            tca_utc=_parse_utc(data["tca_utc"], "tca_utc"),
            minimum_range_km=_strict_float(
                data["minimum_range_km"],
                "minimum_range_km",
                minimum=0.0,
                maximum=1000.0,
            ),
            relative_speed_km_s=_strict_float(
                data["relative_speed_km_s"],
                "relative_speed_km_s",
                minimum=0.0,
                maximum=100.0,
            ),
            public_maximum_probability=_strict_float(
                data["public_maximum_probability"],
                "public_maximum_probability",
                minimum=0.0,
                maximum=1.0,
            ),
            dilution_threshold_km=_strict_float(
                data["dilution_threshold_km"],
                "dilution_threshold_km",
                minimum=0.0,
                maximum=1000.0,
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "first_norad_catalog_id": self.first_norad_catalog_id,
            "first_object_name": self.first_object_name,
            "first_operational_status": self.first_operational_status,
            "first_days_since_epoch": self.first_days_since_epoch,
            "second_norad_catalog_id": self.second_norad_catalog_id,
            "second_object_name": self.second_object_name,
            "second_operational_status": self.second_operational_status,
            "second_days_since_epoch": self.second_days_since_epoch,
            "tca_utc": _format_utc(self.tca_utc),
            "minimum_range_km": self.minimum_range_km,
            "relative_speed_km_s": self.relative_speed_km_s,
            "public_maximum_probability": self.public_maximum_probability,
            "dilution_threshold_km": self.dilution_threshold_km,
            "context": self.context,
            "operational_collision_assessment": False,
        }


def parse_socrates_records(
    records: Iterable[Mapping[str, object]],
    *,
    max_records: int = MAX_SOCRATES_RECORDS,
) -> tuple[SocratesRecord, ...]:
    if not 1 <= max_records <= MAX_SOCRATES_RECORDS:
        raise ValueError(f"max_records must be between 1 and {MAX_SOCRATES_RECORDS}")
    parsed: list[SocratesRecord] = []
    seen: set[tuple[int, int, datetime]] = set()
    for raw in records:
        if len(parsed) >= max_records:
            raise PublicDataValidationError(
                f"SOCRATES response exceeds the {max_records}-record bound"
            )
        record = SocratesRecord.from_mapping(raw)
        key = (
            record.first_norad_catalog_id,
            record.second_norad_catalog_id,
            record.tca_utc,
        )
        if key in seen:
            raise PublicDataValidationError("duplicate SOCRATES proximity record")
        seen.add(key)
        parsed.append(record)
    return tuple(parsed)


class _SocratesHtmlParser(HTMLParser):
    """Collect bounded row/cell text without executing or interpreting markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, ...]] = []
        self.document_text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._total_characters = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(tuple(self._row))
                if len(self.rows) > 2 * MAX_SOCRATES_RECORDS + 64:
                    raise PublicDataValidationError("SOCRATES HTML contains too many rows")
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        self._total_characters += len(data)
        if self._total_characters > MAX_SOCRATES_HTML_BYTES:
            raise PublicDataValidationError("SOCRATES HTML text exceeds its bound")
        self.document_text.append(data)
        if self._cell is not None:
            if (
                sum(len(part) for part in self._cell) + len(data)
                > MAX_SOCRATES_CELL_CHARACTERS
            ):
                raise PublicDataValidationError("SOCRATES table cell is too long")
            self._cell.append(data)


@dataclass(frozen=True)
class SocratesReport:
    data_current_at: datetime
    computation_start: datetime
    computation_stop: datetime
    records: tuple[SocratesRecord, ...]
    context: str = PUBLIC_CONTEXT


SOCRATES_CURRENT_PATTERN = re.compile(
    r"Data current as of (\d{4} [A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2}) UTC"
)
SOCRATES_INTERVAL_PATTERN = re.compile(
    r"Computation Interval: Start = "
    r"(\d{4} [A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2}) UTC, Stop = "
    r"(\d{4} [A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2}) UTC"
)


def _parse_status_name(value: str, name: str) -> tuple[str, str]:
    match = STATUS_PATTERN.fullmatch(" ".join(value.split()))
    if match is None:
        raise PublicDataValidationError(f"{name} must end with a status in brackets")
    return (
        _clean_text(match.group("name"), name, maximum=96),
        match.group("status"),
    )


def _html_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise PublicDataValidationError(f"{name} is not numeric") from exc
    return _strict_float(parsed, name)


def _html_int(value: str, name: str) -> int:
    if not re.fullmatch(r"[1-9]\d{0,8}", value.strip()):
        raise PublicDataValidationError(f"{name} is not a valid catalogue number")
    return int(value)


def _record_from_html_rows(
    first: Sequence[str], second: Sequence[str]
) -> SocratesRecord:
    if len(first) != 7 or len(second) != 6:
        raise PublicDataValidationError("SOCRATES conjunction rows have unexpected cells")
    if "Data" not in first[0] or "km" not in second[0]:
        raise PublicDataValidationError("SOCRATES conjunction row markers are missing")
    first_name, first_status = _parse_status_name(first[2], "first_object_name")
    second_name, second_status = _parse_status_name(second[2], "second_object_name")
    return SocratesRecord.from_mapping(
        {
            "first_norad_catalog_id": _html_int(
                first[1], "first_norad_catalog_id"
            ),
            "first_object_name": first_name,
            "first_operational_status": first_status,
            "first_days_since_epoch": _html_float(
                first[3], "first_days_since_epoch"
            ),
            "second_norad_catalog_id": _html_int(
                second[1], "second_norad_catalog_id"
            ),
            "second_object_name": second_name,
            "second_operational_status": second_status,
            "second_days_since_epoch": _html_float(
                second[3], "second_days_since_epoch"
            ),
            "tca_utc": _format_utc(_parse_display_utc(first[4], "tca_utc")),
            "minimum_range_km": _html_float(first[5], "minimum_range_km"),
            "relative_speed_km_s": _html_float(
                first[6], "relative_speed_km_s"
            ),
            "public_maximum_probability": _html_float(
                second[4], "public_maximum_probability"
            ),
            "dilution_threshold_km": _html_float(
                second[5], "dilution_threshold_km"
            ),
            "context": PUBLIC_CONTEXT,
            "operational_collision_assessment": False,
        }
    )


def parse_socrates_html(
    payload: str | bytes, *, max_records: int = MAX_SOCRATES_RECORDS
) -> SocratesReport:
    """Parse a bounded SOCRATES result table into non-operational context."""

    if not 1 <= max_records <= MAX_SOCRATES_RECORDS:
        raise ValueError(f"max_records must be between 1 and {MAX_SOCRATES_RECORDS}")
    text = _bounded_payload(
        payload, maximum=MAX_SOCRATES_HTML_BYTES, label="SOCRATES HTML"
    )
    parser = _SocratesHtmlParser()
    try:
        parser.feed(text)
        parser.close()
    except PublicDataValidationError:
        raise
    except Exception as exc:
        raise PublicDataValidationError("SOCRATES HTML could not be parsed") from exc

    document_text = " ".join(" ".join(parser.document_text).split())
    current_match = SOCRATES_CURRENT_PATTERN.search(document_text)
    interval_match = SOCRATES_INTERVAL_PATTERN.search(document_text)
    if current_match is None or interval_match is None:
        raise PublicDataValidationError("SOCRATES report provenance timestamps are missing")

    records: list[SocratesRecord] = []
    index = 0
    while index < len(parser.rows):
        row = parser.rows[index]
        if (
            len(row) == 7
            and "Data" in row[0]
            and re.fullmatch(r"[1-9]\d{0,8}", row[1].strip())
        ):
            if index + 1 >= len(parser.rows):
                raise PublicDataValidationError("SOCRATES result has an unpaired row")
            records.append(_record_from_html_rows(row, parser.rows[index + 1]))
            if len(records) > max_records:
                raise PublicDataValidationError(
                    f"SOCRATES response exceeds the {max_records}-record bound"
                )
            index += 2
        else:
            index += 1

    parsed_records = parse_socrates_records(
        (record.to_mapping() for record in records), max_records=max_records
    )
    computation_start = _parse_display_utc(
        interval_match.group(1), "computation_start"
    )
    computation_stop = _parse_display_utc(
        interval_match.group(2), "computation_stop"
    )
    if computation_stop <= computation_start:
        raise PublicDataValidationError("SOCRATES computation interval is invalid")
    return SocratesReport(
        data_current_at=_parse_display_utc(
            current_match.group(1), "data_current_at"
        ),
        computation_start=computation_start,
        computation_stop=computation_stop,
        records=parsed_records,
    )


PROVENANCE_FIELDS = frozenset(
    {
        "source_label",
        "source_urls",
        "retrieved_at",
        "earliest_omm_epoch",
        "latest_omm_epoch",
        "socrates_data_as_of",
        "content_sha256",
    }
)


def _https_url(value: object, name: str) -> str:
    url = _clean_text(value, name, maximum=500)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise PublicDataValidationError(f"{name} must be an HTTPS URL")
    return url


@dataclass(frozen=True)
class SourceProvenance:
    source_label: str
    source_urls: tuple[str, ...]
    retrieved_at: datetime
    earliest_omm_epoch: datetime
    latest_omm_epoch: datetime
    socrates_data_as_of: datetime | None
    content_sha256: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "SourceProvenance":
        _require_exact_fields(data, PROVENANCE_FIELDS, "snapshot provenance")
        raw_urls = data["source_urls"]
        if not isinstance(raw_urls, list) or not 1 <= len(raw_urls) <= 16:
            raise PublicDataValidationError("source_urls must contain 1 to 16 URLs")
        urls = tuple(_https_url(item, "source_url") for item in raw_urls)
        digest = _clean_text(data["content_sha256"], "content_sha256", maximum=64)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PublicDataValidationError("content_sha256 must be lowercase SHA-256")
        earliest = _parse_utc(data["earliest_omm_epoch"], "earliest_omm_epoch")
        latest = _parse_utc(data["latest_omm_epoch"], "latest_omm_epoch")
        if earliest > latest:
            raise PublicDataValidationError("OMM epoch provenance is inverted")
        raw_socrates = data["socrates_data_as_of"]
        return cls(
            source_label=_clean_text(
                data["source_label"], "source_label", maximum=160
            ),
            source_urls=urls,
            retrieved_at=_parse_utc(data["retrieved_at"], "retrieved_at"),
            earliest_omm_epoch=earliest,
            latest_omm_epoch=latest,
            socrates_data_as_of=(
                None
                if raw_socrates is None
                else _parse_utc(raw_socrates, "socrates_data_as_of")
            ),
            content_sha256=digest,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "source_label": self.source_label,
            "source_urls": list(self.source_urls),
            "retrieved_at": _format_utc(self.retrieved_at),
            "earliest_omm_epoch": _format_utc(self.earliest_omm_epoch),
            "latest_omm_epoch": _format_utc(self.latest_omm_epoch),
            "socrates_data_as_of": (
                None
                if self.socrates_data_as_of is None
                else _format_utc(self.socrates_data_as_of)
            ),
            "content_sha256": self.content_sha256,
        }


SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "context", "provenance", "omm_records", "socrates_records"}
)


def _canonical_content(
    provenance: SourceProvenance,
    omm_records: Sequence[OmmRecord],
    socrates_records: Sequence[SocratesRecord],
    *,
    schema_version: int,
    context: str,
) -> bytes:
    provenance_without_digest = provenance.to_mapping()
    del provenance_without_digest["content_sha256"]
    payload = {
        "schema_version": schema_version,
        "context": context,
        "provenance": provenance_without_digest,
        "omm_records": [record.to_mapping() for record in omm_records],
        "socrates_records": [record.to_mapping() for record in socrates_records],
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def content_sha256(
    provenance: SourceProvenance,
    omm_records: Sequence[OmmRecord],
    socrates_records: Sequence[SocratesRecord],
    *,
    schema_version: int = SCHEMA_VERSION,
    context: str = PUBLIC_CONTEXT,
) -> str:
    """Hash the complete snapshot record, excluding only the digest itself."""

    return sha256(
        _canonical_content(
            provenance,
            omm_records,
            socrates_records,
            schema_version=schema_version,
            context=context,
        )
    ).hexdigest()


@dataclass(frozen=True)
class PublicOrbitSnapshot:
    """Validated public-data snapshot with self-verifying provenance."""

    provenance: SourceProvenance
    omm_records: tuple[OmmRecord, ...]
    socrates_records: tuple[SocratesRecord, ...]
    schema_version: int = SCHEMA_VERSION
    context: str = PUBLIC_CONTEXT

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise PublicDataValidationError("unsupported public snapshot schema")
        if self.context != PUBLIC_CONTEXT:
            raise PublicDataValidationError("public snapshot context label was changed")
        if not self.omm_records:
            raise PublicDataValidationError("public snapshot needs at least one OMM record")
        epochs = [record.epoch for record in self.omm_records]
        if self.provenance.earliest_omm_epoch != min(epochs):
            raise PublicDataValidationError("earliest OMM epoch provenance does not match")
        if self.provenance.latest_omm_epoch != max(epochs):
            raise PublicDataValidationError("latest OMM epoch provenance does not match")
        expected_hash = content_sha256(
            self.provenance,
            self.omm_records,
            self.socrates_records,
            schema_version=self.schema_version,
            context=self.context,
        )
        if self.provenance.content_sha256 != expected_hash:
            raise PublicDataValidationError("public snapshot content hash does not match")

    @classmethod
    def build(
        cls,
        *,
        omm_records: Sequence[OmmRecord],
        socrates_records: Sequence[SocratesRecord],
        source_label: str,
        source_urls: Sequence[str],
        retrieved_at: datetime,
        socrates_data_as_of: datetime | None,
    ) -> "PublicOrbitSnapshot":
        object_tuple = tuple(omm_records)
        candidate_tuple = tuple(socrates_records)
        if not object_tuple:
            raise PublicDataValidationError("cannot build an empty public snapshot")
        epochs = [record.epoch for record in object_tuple]
        validated_urls = tuple(_https_url(url, "source_url") for url in source_urls)
        if not 1 <= len(validated_urls) <= 16:
            raise PublicDataValidationError("source_urls must contain 1 to 16 URLs")
        validated_retrieved_at = _parse_utc(
            _format_utc(retrieved_at), "retrieved_at"
        )
        validated_socrates_data_as_of = (
            None
            if socrates_data_as_of is None
            else _parse_utc(
                _format_utc(socrates_data_as_of), "socrates_data_as_of"
            )
        )
        provenance_without_digest = SourceProvenance(
            source_label=_clean_text(source_label, "source_label", maximum=160),
            source_urls=validated_urls,
            retrieved_at=validated_retrieved_at,
            earliest_omm_epoch=min(epochs),
            latest_omm_epoch=max(epochs),
            socrates_data_as_of=validated_socrates_data_as_of,
            content_sha256="0" * 64,
        )
        provenance = replace(
            provenance_without_digest,
            content_sha256=content_sha256(
                provenance_without_digest,
                object_tuple,
                candidate_tuple,
                schema_version=SCHEMA_VERSION,
                context=PUBLIC_CONTEXT,
            ),
        )
        return cls(
            provenance=provenance,
            omm_records=object_tuple,
            socrates_records=candidate_tuple,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "PublicOrbitSnapshot":
        _require_exact_fields(data, SNAPSHOT_FIELDS, "public snapshot")
        if data["schema_version"] != SCHEMA_VERSION:
            raise PublicDataValidationError("unsupported public snapshot schema")
        if data["context"] != PUBLIC_CONTEXT:
            raise PublicDataValidationError("public snapshot context label was changed")
        raw_omm = data["omm_records"]
        raw_socrates = data["socrates_records"]
        raw_provenance = data["provenance"]
        if not isinstance(raw_omm, list) or not all(
            isinstance(item, Mapping) for item in raw_omm
        ):
            raise PublicDataValidationError("omm_records must be an array of objects")
        if not isinstance(raw_socrates, list) or not all(
            isinstance(item, Mapping) for item in raw_socrates
        ):
            raise PublicDataValidationError(
                "socrates_records must be an array of objects"
            )
        if not isinstance(raw_provenance, Mapping):
            raise PublicDataValidationError("provenance must be an object")
        return cls(
            provenance=SourceProvenance.from_mapping(raw_provenance),
            omm_records=parse_omm_records(raw_omm),
            socrates_records=parse_socrates_records(raw_socrates),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "PublicOrbitSnapshot":
        text = _bounded_payload(
            payload, maximum=MAX_SNAPSHOT_BYTES, label="public snapshot"
        )
        try:
            decoded = json.loads(text, parse_constant=_reject_json_constant)
        except json.JSONDecodeError as exc:
            raise PublicDataValidationError("public snapshot is not valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise PublicDataValidationError("public snapshot must be a JSON object")
        return cls.from_mapping(decoded)

    @classmethod
    def from_path(cls, path: Path) -> "PublicOrbitSnapshot":
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise PublicDataError(f"could not read public snapshot: {path}") from exc
        return cls.from_json(payload)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "context": self.context,
            "provenance": self.provenance.to_mapping(),
            "omm_records": [record.to_mapping() for record in self.omm_records],
            "socrates_records": [
                record.to_mapping() for record in self.socrates_records
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), indent=2, sort_keys=True) + "\n"

    def to_dict(self) -> dict[str, object]:
        """Return the validated on-disk record as a JSON-serialisable mapping."""

        return self.to_mapping()

    @property
    def retrieved_at_utc(self) -> datetime:
        return self.provenance.retrieved_at

    @property
    def source_updated_at_utc(self) -> datetime:
        if self.provenance.socrates_data_as_of is not None:
            return max(
                self.provenance.latest_omm_epoch,
                self.provenance.socrates_data_as_of,
            )
        return self.provenance.latest_omm_epoch

    @property
    def objects(self) -> tuple[OmmRecord, ...]:
        return self.omm_records

    @property
    def events(self) -> tuple[SocratesRecord, ...]:
        return self.socrates_records

    @property
    def snapshot_sha256(self) -> str:
        return self.provenance.content_sha256

    @property
    def mode(self) -> str:
        return "public_gp_context"

    @property
    def status(self) -> str:
        return "validated_public_snapshot"

    def is_fresh(
        self, now: datetime, *, ttl: timedelta = REFRESH_TTL
    ) -> bool:
        checked_at = _parse_utc(_format_utc(now), "now")
        age = checked_at - self.provenance.retrieved_at
        return timedelta(0) <= age <= ttl


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    final_url: str


class Transport(Protocol):
    def __call__(self, url: str, *, max_bytes: int) -> HttpResponse:
        """Fetch exactly once and return a bounded response."""


def urllib_transport(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float = 10,
) -> HttpResponse:
    """Explicit opt-in stdlib transport; performs one request and no retries."""

    request = Request(
        url,
        headers={
            "Accept": "application/json,text/html;q=0.9",
            "User-Agent": "UK-Orbit-Guard-Hackathon/0.1 public-data demo",
        },
    )
    try:
        try:
            import certifi
        except ImportError:
            tls_context = ssl.create_default_context()
        else:
            tls_context = ssl.create_default_context(cafile=certifi.where())
        class _NoRedirectHandler(HTTPRedirectHandler):
            def redirect_request(self, request: object, *args: object) -> None:
                del request, args
                return None

        opener = build_opener(
            _NoRedirectHandler(), HTTPSHandler(context=tls_context)
        )
        response = opener.open(  # noqa: S310 - allowlisted
            request,
            timeout=timeout_seconds,
        )
    except HTTPError as exc:
        body = exc.read(max_bytes + 1)
        return HttpResponse(
            status_code=exc.code,
            body=body,
            headers={key.lower(): value for key, value in exc.headers.items()},
            final_url=exc.geturl(),
        )
    except URLError as exc:
        raise PublicDataFetchError(f"public feed request failed: {exc.reason}") from exc

    with response:
        body = response.read(max_bytes + 1)
        headers = {key.lower(): value for key, value in response.headers.items()}
        return HttpResponse(
            status_code=response.status,
            body=body,
            headers=headers,
            final_url=response.geturl(),
        )


def _validate_celestrak_url(url: str, *, endpoint: Literal["omm", "socrates"]) -> str:
    validated = _https_url(url, f"{endpoint}_url")
    parsed = urlparse(validated)
    if parsed.hostname not in {"celestrak.org", "www.celestrak.org"}:
        raise PublicDataValidationError(f"{endpoint}_url must use celestrak.org")
    expected_path = (
        "/NORAD/elements/gp.php"
        if endpoint == "omm"
        else "/SOCRATES/table-socrates.php"
    )
    if parsed.path.lower() != expected_path.lower():
        raise PublicDataValidationError(
            f"{endpoint}_url must use the documented {expected_path} endpoint"
        )
    return validated


@dataclass(frozen=True)
class PublicFeedConfig:
    """A deliberately small allowlisted collection of public feed queries."""

    omm_urls: tuple[str, ...]
    socrates_url: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.omm_urls) <= 8:
            raise PublicDataValidationError("configure between 1 and 8 OMM URLs")
        if len(set(self.omm_urls)) != len(self.omm_urls):
            raise PublicDataValidationError("OMM URLs must be unique")
        for url in self.omm_urls:
            _validate_celestrak_url(url, endpoint="omm")
        if self.socrates_url is not None:
            _validate_celestrak_url(self.socrates_url, endpoint="socrates")


DEFAULT_FEED_CONFIG = PublicFeedConfig(
    omm_urls=(
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=35683&FORMAT=JSON",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=JSON",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=60470&FORMAT=JSON",
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=66745&FORMAT=JSON",
    ),
    socrates_url=(
        "https://celestrak.org/SOCRATES/table-socrates.php?"
        "NAME=oneweb,&ORDER=TCA&MAX=5"
    ),
)


def _fetch_once(
    transport: Transport, url: str, *, max_bytes: int
) -> HttpResponse:
    response = transport(url, max_bytes=max_bytes)
    if len(response.body) > max_bytes:
        raise PublicDataFetchError(f"public feed exceeded {max_bytes} bytes")
    if response.status_code in {403, 404}:
        raise PublicDataFetchError(
            f"public feed returned HTTP {response.status_code}; request was not retried",
            status_code=response.status_code,
        )
    if not 200 <= response.status_code < 300:
        raise PublicDataFetchError(
            f"public feed returned HTTP {response.status_code}; request was not retried",
            status_code=response.status_code,
        )
    return response


LoadOrigin = Literal["cache", "network", "fixture"]


@dataclass(frozen=True)
class SnapshotLoadResult:
    snapshot: PublicOrbitSnapshot
    origin: LoadOrigin
    fresh: bool
    warning: str | None = None


class PublicSnapshotStore:
    """Load fresh cache first, optionally refresh once, then fall back safely."""

    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        fixture_path: Path = DEFAULT_FIXTURE_PATH,
        feed_config: PublicFeedConfig = DEFAULT_FEED_CONFIG,
        transport: Transport | None = None,
        ttl: timedelta = REFRESH_TTL,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self.cache_path = cache_path
        self.fixture_path = fixture_path
        self.feed_config = feed_config
        self.transport = transport
        self.ttl = ttl

    def load(
        self,
        *,
        allow_network: bool = False,
        now: datetime | None = None,
    ) -> SnapshotLoadResult:
        """Return public context without networking unless explicitly enabled."""

        checked_at = now or datetime.now(UTC)
        checked_at = _parse_utc(_format_utc(checked_at), "now")
        stale_cache: PublicOrbitSnapshot | None = None
        cache_warning: str | None = None

        if self.cache_path is not None and self.cache_path.is_file():
            try:
                cached = PublicOrbitSnapshot.from_path(self.cache_path)
            except PublicDataError as exc:
                cache_warning = f"ignored invalid cache: {exc}"
            else:
                if cached.is_fresh(checked_at, ttl=self.ttl):
                    return SnapshotLoadResult(cached, "cache", True)
                stale_cache = cached

        refresh_warning: str | None = None
        if allow_network:
            if self.transport is None:
                refresh_warning = (
                    "network refresh requested without an explicit transport; no request made"
                )
            else:
                try:
                    refreshed = self._refresh(checked_at)
                except PublicDataError as exc:
                    refresh_warning = f"network refresh failed: {exc}"
                else:
                    if self.cache_path is not None:
                        try:
                            _write_snapshot_atomic(self.cache_path, refreshed)
                        except OSError as exc:
                            return SnapshotLoadResult(
                                refreshed,
                                "network",
                                True,
                                (
                                    "public refresh validated but cache write failed; "
                                    f"using refreshed in-memory snapshot only: {exc}"
                                ),
                            )
                    return SnapshotLoadResult(refreshed, "network", True)

        if stale_cache is not None:
            warning = refresh_warning or (
                "using last-known-good stale cache; network refresh was not enabled"
            )
            return SnapshotLoadResult(stale_cache, "cache", False, warning)

        fixture = PublicOrbitSnapshot.from_path(self.fixture_path)
        warnings = [item for item in (cache_warning, refresh_warning) if item]
        if not warnings:
            warnings.append("using bundled offline public-data fixture")
        return SnapshotLoadResult(
            fixture,
            "fixture",
            fixture.is_fresh(checked_at, ttl=self.ttl),
            "; ".join(warnings),
        )

    def _refresh(self, retrieved_at: datetime) -> PublicOrbitSnapshot:
        if self.transport is None:  # pragma: no cover - guarded by load
            raise PublicDataFetchError("explicit transport is required")
        omm_records: list[OmmRecord] = []
        seen: set[int] = set()
        for url in self.feed_config.omm_urls:
            response = _fetch_once(
                self.transport, url, max_bytes=MAX_OMM_BYTES
            )
            for record in parse_omm_json(response.body):
                if record.norad_catalog_id in seen:
                    raise PublicDataValidationError(
                        f"duplicate NORAD_CAT_ID across feeds: {record.norad_catalog_id}"
                    )
                seen.add(record.norad_catalog_id)
                omm_records.append(record)
                if len(omm_records) > MAX_OMM_RECORDS:
                    raise PublicDataValidationError("combined OMM feeds exceed their bound")

        socrates_records: tuple[SocratesRecord, ...] = ()
        socrates_data_as_of: datetime | None = None
        if self.feed_config.socrates_url is not None:
            response = _fetch_once(
                self.transport,
                self.feed_config.socrates_url,
                max_bytes=MAX_SOCRATES_HTML_BYTES,
            )
            report = parse_socrates_html(response.body)
            socrates_records = report.records
            socrates_data_as_of = report.data_current_at

        source_urls = list(self.feed_config.omm_urls)
        if self.feed_config.socrates_url is not None:
            source_urls.append(self.feed_config.socrates_url)
        return PublicOrbitSnapshot.build(
            omm_records=omm_records,
            socrates_records=socrates_records,
            source_label="CelesTrak public GP/OMM and SOCRATES Plus",
            source_urls=source_urls,
            retrieved_at=retrieved_at,
            socrates_data_as_of=socrates_data_as_of,
        )


def _write_snapshot_atomic(path: Path, snapshot: PublicOrbitSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(snapshot.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def sgp4_available() -> bool:
    """Return whether the optional propagation dependency can be imported."""

    try:
        import sgp4.api  # noqa: F401
        import sgp4.omm  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class PropagatedState:
    """TEME state propagated from public GP/OMM context, not live telemetry."""

    norad_catalog_id: int
    at_utc: datetime
    position_km: tuple[float, float, float]
    velocity_km_s: tuple[float, float, float]
    reference_frame: str = "TEME"
    model: str = "SGP4"
    context: str = PUBLIC_CONTEXT
    operational_collision_assessment: bool = False


def propagate_omm_sgp4(record: OmmRecord, at: datetime) -> PropagatedState:
    """Propagate one public OMM record when ``sgp4`` is installed.

    This helper deliberately returns only a propagated state.  It does not
    calculate miss distance, covariance, probability, or an avoidance command.
    """

    try:
        from sgp4 import omm
        from sgp4.api import SGP4_ERRORS, Satrec, jday
    except ImportError as exc:
        raise Sgp4UnavailableError(
            "optional dependency 'sgp4' is not installed; no propagation performed"
        ) from exc

    at_utc = _parse_utc(_format_utc(at), "at")
    fields = record.to_mapping()
    omm_fields = {
        key: (
            record.epoch.strftime("%Y-%m-%dT%H:%M:%S.%f")
            if key == "EPOCH"
            else str(value)
        )
        for key, value in fields.items()
        if value is not None
    }
    satellite = Satrec()
    try:
        omm.initialize(satellite, omm_fields)
    except Exception as exc:
        raise Sgp4PropagationError("SGP4 could not initialise from the OMM record") from exc

    julian_day, fraction = jday(
        at_utc.year,
        at_utc.month,
        at_utc.day,
        at_utc.hour,
        at_utc.minute,
        at_utc.second + at_utc.microsecond / 1_000_000,
    )
    error_code, position, velocity = satellite.sgp4(julian_day, fraction)
    if error_code != 0:
        detail = SGP4_ERRORS.get(error_code, "unknown SGP4 error")
        raise Sgp4PropagationError(f"SGP4 error {error_code}: {detail}")
    return PropagatedState(
        norad_catalog_id=record.norad_catalog_id,
        at_utc=at_utc,
        position_km=tuple(float(value) for value in position),  # type: ignore[arg-type]
        velocity_km_s=tuple(float(value) for value in velocity),  # type: ignore[arg-type]
    )


# Compatibility surface consumed by the demo application.  The richer
# ``SnapshotLoadResult`` remains available to callers that need cache origin or
# warning details.
PublicSnapshot = PublicOrbitSnapshot


def _source_updated_at(snapshot: PublicOrbitSnapshot) -> datetime:
    if snapshot.provenance.socrates_data_as_of is not None:
        return max(
            snapshot.provenance.latest_omm_epoch,
            snapshot.provenance.socrates_data_as_of,
        )
    return snapshot.provenance.latest_omm_epoch


def load_default_snapshot(
    cache_path: Path | str | None = DEFAULT_CACHE_PATH,
    fixture_path: Path | str = DEFAULT_FIXTURE_PATH,
    *,
    now: datetime | None = None,
) -> PublicSnapshot:
    """Load a fresh cache or bundled fixture, making zero network requests."""

    store = PublicSnapshotStore(
        cache_path=None if cache_path is None else Path(cache_path),
        fixture_path=Path(fixture_path),
    )
    return store.load(allow_network=False, now=now).snapshot


def refresh_public_snapshot(
    cache_path: Path | str | None = DEFAULT_CACHE_PATH,
    *,
    now: datetime | None = None,
    transport: Transport | None = None,
    force: bool = False,
) -> PublicSnapshot:
    """Refresh only when the caller supplies a transport explicitly.

    With ``transport=None`` this remains offline and returns cache/fixture data.
    A forced refresh makes one request per configured URL; any failure falls
    back without retrying, including HTTP 403 and 404.
    """

    checked_at = now or datetime.now(UTC)
    store = PublicSnapshotStore(
        cache_path=None if cache_path is None else Path(cache_path),
        fixture_path=DEFAULT_FIXTURE_PATH,
        transport=transport,
    )
    if transport is None:
        return store.load(allow_network=False, now=checked_at).snapshot
    if not force:
        return store.load(allow_network=True, now=checked_at).snapshot
    try:
        refreshed = store._refresh(  # noqa: SLF001 - module-level explicit API
            _parse_utc(_format_utc(checked_at), "now")
        )
    except PublicDataError:
        return store.load(allow_network=False, now=checked_at).snapshot
    if store.cache_path is not None:
        try:
            _write_snapshot_atomic(store.cache_path, refreshed)
        except OSError as exc:
            warnings.warn(
                (
                    "public refresh validated but cache write failed; using "
                    f"refreshed in-memory snapshot only: {exc}"
                ),
                RuntimeWarning,
                stacklevel=2,
            )
    return refreshed


EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 = 398_600.4418


def _eccentric_anomaly(mean_anomaly: float, eccentricity: float) -> float:
    estimate = mean_anomaly
    for _ in range(12):
        residual = estimate - eccentricity * math.sin(estimate) - mean_anomaly
        derivative = 1.0 - eccentricity * math.cos(estimate)
        next_estimate = estimate - residual / derivative
        if abs(next_estimate - estimate) < 1e-13:
            return next_estimate
        estimate = next_estimate
    return estimate


def _mean_element_position_km(
    record: OmmRecord, *, mean_anomaly_degrees: float | None = None
) -> tuple[float, float, float]:
    """Return a two-body display position at the element epoch.

    This intentionally modest fallback keeps the demo visible when optional
    SGP4 is absent.  It is labelled as an element-epoch display position and is
    never used to derive the SOCRATES proximity candidates.
    """

    radians_per_second = record.mean_motion * 2.0 * math.pi / 86_400.0
    semi_major_axis = (
        EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 / radians_per_second**2
    ) ** (1.0 / 3.0)
    mean_anomaly = math.radians(
        record.mean_anomaly
        if mean_anomaly_degrees is None
        else mean_anomaly_degrees
    )
    eccentric_anomaly = _eccentric_anomaly(mean_anomaly, record.eccentricity)
    x_perifocal = semi_major_axis * (
        math.cos(eccentric_anomaly) - record.eccentricity
    )
    y_perifocal = (
        semi_major_axis
        * math.sqrt(1.0 - record.eccentricity**2)
        * math.sin(eccentric_anomaly)
    )

    ascending_node = math.radians(record.right_ascension_of_ascending_node)
    argument = math.radians(record.argument_of_pericenter)
    inclination = math.radians(record.inclination)
    cos_node, sin_node = math.cos(ascending_node), math.sin(ascending_node)
    cos_arg, sin_arg = math.cos(argument), math.sin(argument)
    cos_inc, sin_inc = math.cos(inclination), math.sin(inclination)
    x = (
        (cos_node * cos_arg - sin_node * sin_arg * cos_inc) * x_perifocal
        + (-cos_node * sin_arg - sin_node * cos_arg * cos_inc) * y_perifocal
    )
    y = (
        (sin_node * cos_arg + cos_node * sin_arg * cos_inc) * x_perifocal
        + (-sin_node * sin_arg + cos_node * cos_arg * cos_inc) * y_perifocal
    )
    z = sin_arg * sin_inc * x_perifocal + cos_arg * sin_inc * y_perifocal
    return (x, y, z)


def _display_object_type(name: str) -> str:
    upper = name.upper()
    if " DEB" in upper or upper.endswith("DEB"):
        return "DEBRIS"
    if " R/B" in upper or upper.endswith(" R/B"):
        return "ROCKET BODY"
    return "PAYLOAD"


def snapshot_to_globe_records(
    snapshot: PublicSnapshot, selected_id: object | None = None
) -> list[dict[str, object]]:
    """Adapt public OMM records to the feed-agnostic globe renderer.

    If the optional SGP4 package is available, positions are replayed at the
    snapshot retrieval timestamp, never at wall-clock ``now``.  A per-record
    two-body element-epoch fallback keeps the offline fixture demonstrable.
    """

    selected_text = None if selected_id is None else str(selected_id)
    records: list[dict[str, object]] = []
    for item in snapshot.omm_records:
        catalogue_id = str(item.norad_catalog_id)
        selected = selected_text in {
            catalogue_id,
            item.object_id,
            item.object_name,
        }
        replay_at = snapshot.retrieved_at_utc
        try:
            position = propagate_omm_sgp4(item, replay_at).position_km
            period = timedelta(days=1.0 / item.mean_motion)
            trail = [
                propagate_omm_sgp4(
                    item, replay_at + period * (step / 72.0)
                ).position_km
                for step in range(73)
            ]
        except (Sgp4UnavailableError, Sgp4PropagationError):
            position = _mean_element_position_km(item)
            trail = [
                _mean_element_position_km(item, mean_anomaly_degrees=degrees)
                for degrees in range(0, 361, 5)
            ]
            position_model = "two-body display position at element epoch"
            position_at_utc = item.epoch
            position_frame = "mean-element display"
        else:
            position_model = "SGP4/TEME at snapshot retrieval time"
            position_at_utc = replay_at
            position_frame = "TEME"
        records.append(
            {
                "id": catalogue_id,
                "norad_id": item.norad_catalog_id,
                "object_id": catalogue_id,
                "international_designator": item.object_id,
                "name": item.object_name,
                "object_name": item.object_name,
                "object_type": _display_object_type(item.object_name),
                "position_km": position,
                "orbit_trail_km": trail,
                "epoch_utc": _format_utc(item.epoch),
                "element_epoch": _format_utc(item.epoch),
                "position_at_utc": _format_utc(position_at_utc),
                "position_frame": position_frame,
                "source_group": "CelesTrak public GP/OMM",
                "orbit_regime": "Public mean-element display",
                "selected": selected,
                "position_model": position_model,
                "context": PUBLIC_CONTEXT,
                "operational_collision_assessment": False,
            }
        )
    return records


def snapshot_to_screen_candidates(
    snapshot: PublicSnapshot, now: datetime | None = None
) -> list[dict[str, object]]:
    """Adapt SOCRATES rows without presenting them as operational warnings."""

    reference = now or snapshot.provenance.socrates_data_as_of or _source_updated_at(
        snapshot
    )
    reference = _parse_utc(_format_utc(reference), "now")
    candidates: list[dict[str, object]] = []
    for item in snapshot.socrates_records:
        seconds_to_tca = (item.tca_utc - reference).total_seconds()
        event_id = (
            f"{item.first_norad_catalog_id}-{item.second_norad_catalog_id}-"
            f"{item.tca_utc.strftime('%Y%m%dT%H%M%S')}"
        )
        candidates.append(
            {
                "id": event_id,
                "object_id": event_id,
                "name": f"{item.first_object_name} ↔ {item.second_object_name}",
                "object_name": f"{item.first_object_name} ↔ {item.second_object_name}",
                "object_type": _display_object_type(item.second_object_name),
                "first_norad_catalog_id": item.first_norad_catalog_id,
                "first_object_name": item.first_object_name,
                "second_norad_catalog_id": item.second_norad_catalog_id,
                "second_object_name": item.second_object_name,
                "minimum_range_km": item.minimum_range_km,
                "min_range_km": item.minimum_range_km,
                "relative_speed_km_s": item.relative_speed_km_s,
                "public_maximum_probability": item.public_maximum_probability,
                "dilution_threshold_km": item.dilution_threshold_km,
                "tca_utc": _format_utc(item.tca_utc),
                "seconds_to_tca": seconds_to_tca,
                "tca_hours": seconds_to_tca / 3_600.0,
                "temporal_status": (
                    "upcoming" if seconds_to_tca >= 0.0 else "elapsed"
                ),
                "element_age": (
                    f"{item.first_days_since_epoch:.3f} d / "
                    f"{item.second_days_since_epoch:.3f} d"
                ),
                "source_group": "CelesTrak public SOCRATES Plus",
                "context": PUBLIC_CONTEXT,
                "operational_collision_assessment": False,
            }
        )
    return sorted(candidates, key=lambda candidate: candidate["tca_utc"])
