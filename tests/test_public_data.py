from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from orbit_guard import public_data
from orbit_guard.public_data import (
    DEFAULT_FIXTURE_PATH,
    PUBLIC_CONTEXT,
    HttpResponse,
    PublicDataValidationError,
    PublicFeedConfig,
    PublicOrbitSnapshot,
    PublicSnapshotStore,
    Sgp4UnavailableError,
    content_sha256,
    load_default_snapshot,
    parse_omm_json,
    parse_socrates_html,
    refresh_public_snapshot,
    snapshot_to_globe_records,
    snapshot_to_screen_candidates,
)


UTC = timezone.utc
OMM_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?CATNR=35683&FORMAT=JSON"
)
SOCRATES_URL = (
    "https://celestrak.org/SOCRATES/table-socrates.php?"
    "NAME=oneweb,&ORDER=TCA&MAX=1"
)


def _fixture() -> PublicOrbitSnapshot:
    return PublicOrbitSnapshot.from_path(DEFAULT_FIXTURE_PATH)


def _one_omm_json() -> bytes:
    return b"""[
      {
        "OBJECT_NAME": "UK-DMC 2",
        "OBJECT_ID": "2009-041C",
        "EPOCH": "2026-09-02T23:28:27.723360",
        "MEAN_MOTION": 14.76127658,
        "ECCENTRICITY": 0.00015124,
        "INCLINATION": 97.8947,
        "RA_OF_ASC_NODE": 19.0927,
        "ARG_OF_PERICENTER": 67.025,
        "MEAN_ANOMALY": 293.1119,
        "EPHEMERIS_TYPE": 0,
        "CLASSIFICATION_TYPE": "U",
        "NORAD_CAT_ID": 35683,
        "ELEMENT_SET_NO": 999,
        "REV_AT_EPOCH": 91804,
        "BSTAR": 0.000037092717,
        "MEAN_MOTION_DOT": 0.00000206,
        "MEAN_MOTION_DDOT": 0
      }
    ]"""


def _one_socrates_html() -> bytes:
    return b"""<!doctype html>
    <html><body>
      <p>Data current as of 2026 Sep 02 06:33:00 UTC</p>
      <p>Computation Interval: Start = 2026 Sep 02 07:00:00 UTC,
         Stop = 2026 Sep 09 07:00:00 UTC</p>
      <table>
        <tr>
          <td>Data</td><td>48237</td><td>ONEWEB-0194 [+]</td><td>0.663</td>
          <td>2026-09-02 07:00:09.568</td><td>4.509</td><td>13.367</td>
        </tr>
        <tr>
          <td>4.509 km</td><td>10842</td><td>DELTA 1 DEB [-]</td><td>0.851</td>
          <td>3.531E-07</td><td>2.119</td>
        </tr>
      </table>
    </body></html>"""


class FakeTransport:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    def __call__(self, url: str, *, max_bytes: int) -> HttpResponse:
        self.calls.append((url, max_bytes))
        return self.responses[url]


def test_bundled_fixture_is_self_verifying_and_offline_compatible() -> None:
    snapshot = load_default_snapshot(cache_path=None)

    assert [record.norad_catalog_id for record in snapshot.objects] == [
        35683,
        25544,
        60470,
        66745,
    ]
    assert snapshot.objects[0].object_name == "UK-DMC 2"
    assert snapshot.objects[0].object_id == "2009-041C"
    assert len(snapshot.events) == 3
    assert snapshot.snapshot_sha256 == (
        "205e1928755de30a36d2f3514e56a04e604b7ae1942b759b23c68e6942038d4d"
    )
    assert snapshot.mode == "public_gp_context"
    assert snapshot.status == "validated_public_snapshot"
    assert snapshot.to_dict()["context"] == PUBLIC_CONTEXT


def test_snapshot_hash_binds_schema_context_sources_timestamps_and_records() -> None:
    raw = json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
    snapshot = _fixture()
    original_digest = snapshot.snapshot_sha256

    assert content_sha256(
        snapshot.provenance,
        snapshot.objects,
        snapshot.events,
        schema_version=snapshot.schema_version + 1,
        context=snapshot.context,
    ) != original_digest
    assert content_sha256(
        snapshot.provenance,
        snapshot.objects,
        snapshot.events,
        schema_version=snapshot.schema_version,
        context=f"{snapshot.context} changed",
    ) != original_digest

    mutations = (
        ("source_label", "Altered public source"),
        ("retrieved_at", "2026-09-03T10:21:39Z"),
        ("socrates_data_as_of", "2026-09-02T06:34:00Z"),
    )
    for field, value in mutations:
        altered = deepcopy(raw)
        altered["provenance"][field] = value
        with pytest.raises(PublicDataValidationError, match="content hash"):
            PublicOrbitSnapshot.from_mapping(altered)

    altered_url = deepcopy(raw)
    altered_url["provenance"]["source_urls"][0] = (
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=99999&FORMAT=JSON"
    )
    with pytest.raises(PublicDataValidationError, match="content hash"):
        PublicOrbitSnapshot.from_mapping(altered_url)

    altered_record = deepcopy(raw)
    altered_record["omm_records"][0]["MEAN_ANOMALY"] = 294.1119
    with pytest.raises(PublicDataValidationError, match="content hash"):
        PublicOrbitSnapshot.from_mapping(altered_record)


def test_strict_omm_and_socrates_parsers_accept_only_bounded_known_schema() -> None:
    omm = parse_omm_json(_one_omm_json(), max_records=1)
    report = parse_socrates_html(_one_socrates_html(), max_records=1)

    assert omm[0].norad_catalog_id == 35683
    assert report.computation_stop - report.computation_start == timedelta(days=7)
    assert report.records[0].minimum_range_km == pytest.approx(4.509)
    assert report.records[0].operational_collision_assessment is False

    altered = _one_omm_json().replace(
        b'"OBJECT_NAME": "UK-DMC 2",',
        b'"OBJECT_NAME": "UK-DMC 2", "UNEXPECTED": true,',
    )
    with pytest.raises(PublicDataValidationError, match="unexpected fields"):
        parse_omm_json(altered, max_records=1)


def test_two_hour_cache_and_no_network_default(tmp_path: Path) -> None:
    fixture = _fixture()
    cache = tmp_path / "cache" / "snapshot.json"
    cache.parent.mkdir()
    cache.write_text(fixture.to_json(), encoding="utf-8")
    transport = FakeTransport({})
    store = PublicSnapshotStore(cache_path=cache, transport=transport)

    exactly_two_hours = fixture.retrieved_at_utc + timedelta(hours=2)
    result = store.load(allow_network=False, now=exactly_two_hours)

    assert result.origin == "cache"
    assert result.fresh is True
    assert transport.calls == []


def test_refresh_uses_fake_transport_and_writes_last_known_good_cache(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(
        {
            OMM_URL: HttpResponse(200, _one_omm_json(), {}, OMM_URL),
            SOCRATES_URL: HttpResponse(200, _one_socrates_html(), {}, SOCRATES_URL),
        }
    )
    cache = tmp_path / "snapshot.json"
    store = PublicSnapshotStore(
        cache_path=cache,
        feed_config=PublicFeedConfig((OMM_URL,), SOCRATES_URL),
        transport=transport,
    )
    retrieved_at = datetime(2026, 9, 3, 9, 21, 39, tzinfo=UTC)

    result = store.load(allow_network=True, now=retrieved_at)

    assert result.origin == "network"
    assert result.fresh is True
    assert len(transport.calls) == 2
    assert cache.is_file()
    assert PublicOrbitSnapshot.from_path(cache).snapshot_sha256 == (
        result.snapshot.snapshot_sha256
    )


def test_cache_write_failure_returns_validated_in_memory_refresh_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeTransport(
        {
            OMM_URL: HttpResponse(200, _one_omm_json(), {}, OMM_URL),
            SOCRATES_URL: HttpResponse(200, _one_socrates_html(), {}, SOCRATES_URL),
        }
    )
    store = PublicSnapshotStore(
        cache_path=tmp_path / "unwritable" / "snapshot.json",
        feed_config=PublicFeedConfig((OMM_URL,), SOCRATES_URL),
        transport=transport,
    )

    def fail_cache_write(path: Path, snapshot: PublicOrbitSnapshot) -> None:
        del path, snapshot
        raise OSError("read-only cache")

    monkeypatch.setattr(public_data, "_write_snapshot_atomic", fail_cache_write)
    result = store.load(
        allow_network=True,
        now=datetime(2026, 9, 3, 9, 21, 39, tzinfo=UTC),
    )

    assert result.origin == "network"
    assert result.fresh is True
    assert result.snapshot.objects[0].norad_catalog_id == 35683
    assert result.warning is not None
    assert "cache write failed" in result.warning
    assert "refreshed in-memory snapshot only" in result.warning
    assert len(transport.calls) == 2


def test_forced_refresh_wrapper_warns_but_returns_snapshot_on_cache_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture()

    def fake_refresh(
        store: PublicSnapshotStore, retrieved_at: datetime
    ) -> PublicOrbitSnapshot:
        del store, retrieved_at
        return fixture

    def fail_cache_write(path: Path, snapshot: PublicOrbitSnapshot) -> None:
        del path, snapshot
        raise OSError("read-only cache")

    monkeypatch.setattr(PublicSnapshotStore, "_refresh", fake_refresh)
    monkeypatch.setattr(public_data, "_write_snapshot_atomic", fail_cache_write)

    with pytest.warns(RuntimeWarning, match="cache write failed"):
        returned = refresh_public_snapshot(
            cache_path=tmp_path / "snapshot.json",
            now=datetime(2026, 9, 3, 9, 21, 39, tzinfo=UTC),
            transport=FakeTransport({}),
            force=True,
        )

    assert returned is fixture


@pytest.mark.parametrize("status_code", [403, 404])
def test_http_error_is_not_retried_and_falls_back_to_fixture(
    tmp_path: Path, status_code: int
) -> None:
    transport = FakeTransport(
        {OMM_URL: HttpResponse(status_code, b"Error", {}, OMM_URL)}
    )
    store = PublicSnapshotStore(
        cache_path=tmp_path / "missing-cache.json",
        feed_config=PublicFeedConfig((OMM_URL,), None),
        transport=transport,
    )

    result = store.load(
        allow_network=True,
        now=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
    )

    assert result.origin == "fixture"
    assert len(transport.calls) == 1
    assert result.warning is not None
    assert f"HTTP {status_code}" in result.warning
    assert "not retried" in result.warning


def test_visual_adapters_replay_sgp4_at_snapshot_time_and_label_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _fixture()
    propagation_times: list[datetime] = []

    def fake_propagation(record: object, at: datetime) -> public_data.PropagatedState:
        propagation_times.append(at)
        return public_data.PropagatedState(
            norad_catalog_id=record.norad_catalog_id,  # type: ignore[attr-defined]
            at_utc=at,
            position_km=(7000.0, 1.0, 2.0),
            velocity_km_s=(0.0, 7.5, 0.0),
        )

    monkeypatch.setattr(public_data, "propagate_omm_sgp4", fake_propagation)
    globe = snapshot_to_globe_records(snapshot, selected_id=35683)
    candidates = snapshot_to_screen_candidates(snapshot)

    assert globe[0]["selected"] is True
    assert globe[0]["position_model"] == "SGP4/TEME at snapshot retrieval time"
    assert globe[0]["position_at_utc"] == "2026-09-03T09:21:39Z"
    assert propagation_times
    assert propagation_times[0] == snapshot.retrieved_at_utc
    assert candidates[0]["tca_hours"] == pytest.approx(0.45265778)
    assert all(item["operational_collision_assessment"] is False for item in candidates)

    def no_sgp4(record: object, at: datetime) -> public_data.PropagatedState:
        del record, at
        raise Sgp4UnavailableError("optional dependency is absent")

    monkeypatch.setattr(public_data, "propagate_omm_sgp4", no_sgp4)
    fallback = snapshot_to_globe_records(snapshot)
    assert fallback[0]["position_model"] == (
        "two-body display position at element epoch"
    )
    assert fallback[0]["position_at_utc"] == fallback[0]["epoch_utc"]
