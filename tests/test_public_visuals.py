from __future__ import annotations

import json

from plotly.utils import PlotlyJSONEncoder

from orbit_guard.public_visuals import (
    build_public_catalogue_globe,
    build_public_proximity_screen,
)


def _figure_json(figure) -> str:
    return json.dumps(
        figure.to_plotly_json(),
        cls=PlotlyJSONEncoder,
        ensure_ascii=False,
        sort_keys=True,
    )


def test_catalogue_globe_marks_roles_classes_and_selected_trail():
    records = [
        {
            "norad_id": 35683,
            "name": "UK-DMC 2",
            "object_type": "PAYLOAD",
            "position_km": [6_900.0, 0.0, 20.0],
            "orbit_trail_km": [[6_900.0, 0.0, 20.0], [0.0, 6_900.0, 20.0]],
            "element_epoch": "2026-09-03T06:00:00Z",
            "source_group": "DMC",
            "orbit_regime": "LEO",
        },
        {
            "object_id": "debris-1",
            "name": "Public debris record",
            "object_type": "DEBRIS",
            "x_km": 6_800.0,
            "y_km": 350.0,
            "z_km": 40.0,
            "orbit_trail_km": [[6_800.0, 350.0, 40.0], [200.0, 6_780.0, 40.0]],
        },
        {
            "id": "body-1",
            "name": "Public rocket body",
            "object_type": "ROCKET BODY",
            "position_km": [-6_750.0, 0.0, 110.0],
        },
        {"id": "missing-position", "name": "Incomplete row"},
    ]

    figure = build_public_catalogue_globe(
        records,
        selected_id=35683,
        review_candidate_ids=["debris-1"],
        retrieved_at="2026-09-03 08:10 UTC",
    )
    payload = _figure_json(figure)

    assert figure.layout.meta["valid_record_count"] == 3
    assert figure.layout.meta["invalid_record_count"] == 1
    assert figure.layout.meta["review_candidate_count"] == 1
    assert "Selected object · Payload" in payload
    assert "Review candidate · Debris" in payload
    assert "diamond" in payload
    assert '"symbol": "x"' in payload
    assert "Selected object · orbit trail" in payload
    assert "Review candidate · orbit trail" in payload
    assert "PUBLIC-ELEMENT CONTEXT" in payload


def test_catalogue_globe_empty_and_degraded_state_is_explicit():
    figure = build_public_catalogue_globe(
        [{"id": "bad"}],
        selected_id="not-present",
        degraded_message="using the last verified snapshot",
    )
    payload = _figure_json(figure)

    assert "NO VALID PUBLIC ELEMENT POSITIONS" in payload
    assert "SELECTED OBJECT NOT PRESENT" in payload
    assert "CACHED / DEGRADED" in payload
    assert figure.layout.meta["valid_record_count"] == 0


def test_proximity_screen_encodes_range_time_rank_and_object_shape():
    candidates = [
        {
            "norad_id": 100,
            "name": "Payload candidate",
            "object_type": "PAYLOAD",
            "min_range_km": 80.0,
            "tca_hours": 4.5,
            "tca_utc": "2026-09-03T12:40:00Z",
            "element_age": "3.1 h",
            "source_group": "ACTIVE",
        },
        {
            "norad_id": 200,
            "name": "Debris candidate",
            "object_type": "DEBRIS",
            "min_separation_m": 12_500.0,
            "seconds_to_tca": 3_600.0,
            "source_group": "IRIDIUM-33-DEBRIS",
        },
        {
            "norad_id": 300,
            "name": "Rocket-body candidate",
            "object_type": "ROCKET BODY",
            "minimum_range_km": 40.0,
            "hours_to_tca": 2.0,
        },
        {"norad_id": 400, "name": "Outside horizon", "min_range_km": 1.0, "tca_hours": 7.0},
        {"norad_id": 500, "name": "Missing range", "tca_hours": 2.0},
    ]

    figure = build_public_proximity_screen(
        candidates,
        selected_name="Bounded public pair set",
        centre_role="Aggregate screening result",
        horizon_hours=6.0,
    )
    payload = _figure_json(figure)

    assert figure.layout.meta["valid_candidate_count"] == 3
    assert figure.layout.meta["displayed_candidate_count"] == 3
    assert figure.layout.meta["invalid_candidate_count"] == 1
    assert figure.layout.meta["outside_horizon_count"] == 1
    assert "Radius = source-model minimum range" in payload
    assert "angle = source-model TCA" in payload
    assert "SOURCE AS-OF" in payload
    assert '"Now"' not in payload
    assert "Review candidate #1" in payload
    assert "Candidate ID:" in payload
    assert "Catalogue ID:" not in payload
    assert "Display role: Aggregate screening result" in payload
    assert "12.50 km" in payload
    assert "diamond" in payload
    assert '"symbol": "x"' in payload
    assert "square" in payload
    assert "NO COVARIANCE" in payload
    assert "NOT A FLIGHT DECISION" in payload
    assert "OUTSIDE 6 H DECLARED HORIZON" in payload


def test_proximity_screen_empty_degraded_state_and_language_boundary():
    figure = build_public_proximity_screen(
        [],
        selected_name="Public object",
        degraded_message="source unavailable",
    )
    payload = _figure_json(figure)
    lower = payload.lower()

    assert "NO VALID PUBLIC SCREENING CANDIDATES" in payload
    assert "CACHED / DEGRADED" in payload
    assert "threat" not in lower
    assert "safe" not in lower
    assert "collision probability" not in lower


def test_figures_are_deterministic_for_the_same_inputs():
    globe_records = [
        {"id": "one", "name": "One", "object_type": "PAYLOAD", "position_km": [7_000, 1, 2]}
    ]
    screen_records = [
        {"id": "two", "name": "Two", "object_type": "DEBRIS", "min_range_km": 25, "tca_hours": 2}
    ]

    assert _figure_json(build_public_catalogue_globe(globe_records)) == _figure_json(
        build_public_catalogue_globe(globe_records)
    )
    assert _figure_json(build_public_proximity_screen(screen_records)) == _figure_json(
        build_public_proximity_screen(screen_records)
    )
