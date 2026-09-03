from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import timedelta
import json
import math
from pathlib import Path

import pytest

from orbit_guard.debris_catalogue import (
    DEFAULT_FIXTURE_PATH,
    GROUP_URLS,
    REFRESH_TTL,
    DebrisCatalogue,
    catalogue_globe_records,
    fetch_catalogue,
    load_catalogue,
)
from orbit_guard.public_data import (
    HttpResponse,
    PublicDataFetchError,
    PublicDataValidationError,
)


def _fixture() -> DebrisCatalogue:
    return DebrisCatalogue.from_path(DEFAULT_FIXTURE_PATH)


class FixtureTransport:
    def __init__(self, catalogue: DebrisCatalogue) -> None:
        self.calls: list[tuple[str, int]] = []
        grouped = {
            group: [
                record.omm.to_mapping()
                for record in catalogue.records
                if record.source_group == group
            ]
            for group in GROUP_URLS
        }
        self.responses = {
            url: HttpResponse(
                200,
                json.dumps(grouped[group], allow_nan=False).encode("utf-8"),
                {},
                url,
            )
            for group, url in GROUP_URLS.items()
        }

    def __call__(self, url: str, *, max_bytes: int) -> HttpResponse:
        self.calls.append((url, max_bytes))
        return self.responses[url]


def test_bundled_debris_fixture_is_strict_self_verifying_and_large_enough() -> None:
    catalogue = _fixture()
    round_trip = DebrisCatalogue.from_json(catalogue.to_json())

    assert len(catalogue.records) == 2_661
    assert len({record.omm.norad_catalog_id for record in catalogue.records}) == 2_661
    assert set(record.source_group for record in catalogue.records) == set(GROUP_URLS)
    assert round_trip == catalogue
    assert len(catalogue.content_sha256) == 64


def test_catalogue_hash_and_exact_schema_reject_tampering() -> None:
    raw = _fixture().to_mapping()

    changed_element = deepcopy(raw)
    changed_element["records"][0]["omm"]["MEAN_ANOMALY"] += 0.01
    with pytest.raises(PublicDataValidationError, match="hash"):
        DebrisCatalogue.from_mapping(changed_element)

    unexpected_field = deepcopy(raw)
    unexpected_field["unverified_count"] = 99
    with pytest.raises(PublicDataValidationError, match="schema"):
        DebrisCatalogue.from_mapping(unexpected_field)

    duplicate = deepcopy(raw)
    duplicate["records"][1] = deepcopy(duplicate["records"][0])
    with pytest.raises(PublicDataValidationError, match="duplicate NORAD"):
        DebrisCatalogue.from_mapping(duplicate)

    bad_source = deepcopy(raw)
    bad_source["source_urls"][0] = "https://example.invalid/untrusted"
    with pytest.raises(PublicDataValidationError, match="allowlist"):
        DebrisCatalogue.from_mapping(bad_source)


def test_offline_loader_never_calls_network_and_uses_bundled_replay(
    tmp_path: Path,
) -> None:
    catalogue = _fixture()

    def forbidden_transport(url: str, *, max_bytes: int) -> HttpResponse:
        raise AssertionError(f"unexpected network request: {url} ({max_bytes})")

    result = load_catalogue(
        allow_network=False,
        now=catalogue.retrieved_at_utc + REFRESH_TTL + timedelta(seconds=1),
        cache_path=tmp_path / "missing-cache.json",
        fixture_path=DEFAULT_FIXTURE_PATH,
        transport=forbidden_transport,
    )

    assert result.origin == "bundled replay"
    assert result.fresh is False
    assert result.catalogue.content_sha256 == catalogue.content_sha256
    assert result.warning is None


def test_cache_freshness_boundary_and_invalid_cache_fallback(tmp_path: Path) -> None:
    catalogue = _fixture()
    cache = tmp_path / "debris.json"
    cache.write_text(catalogue.to_json(), encoding="utf-8")

    at_ttl = load_catalogue(
        allow_network=False,
        now=catalogue.retrieved_at_utc + REFRESH_TTL,
        cache_path=cache,
        fixture_path=DEFAULT_FIXTURE_PATH,
    )
    assert at_ttl.origin == "cache"
    assert at_ttl.fresh is True

    cache.write_text("{}\n", encoding="utf-8")
    invalid = load_catalogue(
        allow_network=False,
        now=catalogue.retrieved_at_utc,
        cache_path=cache,
        fixture_path=DEFAULT_FIXTURE_PATH,
    )
    assert invalid.origin == "bundled replay"
    assert invalid.catalogue.content_sha256 == catalogue.content_sha256
    assert invalid.warning is not None
    assert "invalid cache ignored" in invalid.warning


def test_future_cache_is_rejected_and_newer_valid_fixture_is_used(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    future_cache = DebrisCatalogue.build(
        fixture.records,
        retrieved_at_utc=fixture.retrieved_at_utc + timedelta(hours=1),
        source_urls=fixture.source_urls,
    )
    cache_path = tmp_path / "future-cache.json"
    cache_path.write_text(future_cache.to_json(), encoding="utf-8")

    result = load_catalogue(
        allow_network=False,
        now=fixture.retrieved_at_utc,
        cache_path=cache_path,
        fixture_path=DEFAULT_FIXTURE_PATH,
    )

    assert result.origin == "bundled replay"
    assert result.catalogue.content_sha256 == fixture.content_sha256
    assert result.warning is not None
    assert "future-dated cache ignored" in result.warning


def test_newer_fixture_wins_over_older_stale_cache(tmp_path: Path) -> None:
    fixture = _fixture()
    older_cache = DebrisCatalogue.build(
        fixture.records,
        retrieved_at_utc=fixture.retrieved_at_utc - timedelta(days=2),
        source_urls=fixture.source_urls,
    )
    cache_path = tmp_path / "older-cache.json"
    cache_path.write_text(older_cache.to_json(), encoding="utf-8")

    result = load_catalogue(
        allow_network=False,
        now=fixture.retrieved_at_utc + timedelta(days=1),
        cache_path=cache_path,
        fixture_path=DEFAULT_FIXTURE_PATH,
    )

    assert result.origin == "bundled replay"
    assert result.catalogue.content_sha256 == fixture.content_sha256


def test_fake_celestrak_refresh_uses_all_allowlisted_groups_without_network() -> None:
    fixture = _fixture()
    transport = FixtureTransport(fixture)

    fetched = fetch_catalogue(
        transport=transport,
        retrieved_at_utc=fixture.retrieved_at_utc,
    )

    assert [url for url, _ in transport.calls] == list(GROUP_URLS.values())
    assert len(fetched.records) == len(fixture.records)
    assert fetched.content_sha256 == fixture.content_sha256


def test_refresh_failure_keeps_the_validated_offline_fixture(tmp_path: Path) -> None:
    fixture = _fixture()

    def unavailable(url: str, *, max_bytes: int) -> HttpResponse:
        raise PublicDataFetchError("fixture-only test: endpoint unavailable")

    result = load_catalogue(
        allow_network=True,
        now=fixture.retrieved_at_utc + timedelta(days=1),
        cache_path=tmp_path / "cache.json",
        fixture_path=DEFAULT_FIXTURE_PATH,
        transport=unavailable,
    )

    assert result.origin == "bundled replay"
    assert result.catalogue.content_sha256 == fixture.content_sha256
    assert result.warning is not None
    assert "network refresh failed" in result.warning


def test_redirected_celestrak_response_is_rejected_before_parsing() -> None:
    first_url = next(iter(GROUP_URLS.values()))

    def redirected(url: str, *, max_bytes: int) -> HttpResponse:
        return HttpResponse(200, b"[]", {}, "https://example.invalid/redirect")

    with pytest.raises(PublicDataFetchError, match="redirected unexpectedly"):
        fetch_catalogue(transport=redirected)


def test_globe_records_are_finite_earth_centred_display_positions() -> None:
    catalogue = _fixture()
    records = catalogue_globe_records(catalogue, at=catalogue.retrieved_at_utc)

    assert len(records) == len(catalogue.records)
    assert {record["source_group"] for record in records} == set(GROUP_URLS)
    assert Counter(record["object_type"] for record in records) == {
        "DEBRIS FRAGMENT": 2_658,
        "PARENT OBJECT": 3,
    }
    assert all(record["orbit_regime"] == "PUBLIC GP/OMM" for record in records)
    assert all(
        len(record["position_km"]) == 3
        and all(math.isfinite(component) for component in record["position_km"])
        for record in records
    )
