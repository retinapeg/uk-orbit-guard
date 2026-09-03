from __future__ import annotations

import json
import math

from plotly.utils import PlotlyJSONEncoder
import pytest

from orbit_guard.rl_core import (
    ACTION_NAMES,
    ORBIT_RADIUS_KM,
    default_hazards,
    simulate_policy,
)
from orbit_guard.rl_visuals import (
    action_mix,
    build_command_globe,
    build_encounter_replay,
    build_training_curve,
    hill_to_earth_display,
)


def _figure_json(figure) -> str:
    return json.dumps(
        figure.to_plotly_json(),
        cls=PlotlyJSONEncoder,
        ensure_ascii=False,
        sort_keys=True,
    )


def test_hill_display_transform_embeds_offsets_on_declared_reference_orbit() -> None:
    origin = hill_to_earth_display(0.0, 0.0, 0.0)
    radial = hill_to_earth_display(1.0, 0.0, 0.0)
    offset = hill_to_earth_display(1.0, 2.0, 800.0)

    assert math.dist(origin, (0.0, 0.0, 0.0)) == pytest.approx(ORBIT_RADIUS_KM)
    assert math.dist(radial, (0.0, 0.0, 0.0)) == pytest.approx(
        ORBIT_RADIUS_KM + 1.0
    )
    assert math.dist(offset, (0.0, 0.0, 0.0)) == pytest.approx(
        math.hypot(ORBIT_RADIUS_KM + 1.0, 2.0)
    )


def test_command_globe_separates_public_context_from_synthetic_asset() -> None:
    records = [
        {
            "object_id": 1,
            "name": "Fengyun fragment",
            "position_km": [7_100.0, 0.0, 20.0],
            "source_group": "FENGYUN-1C-DEBRIS",
        },
        {
            "object_id": 2,
            "name": "Iridium fragment",
            "position_km": [0.0, 7_000.0, 40.0],
            "source_group": "IRIDIUM-33-DEBRIS",
        },
        {
            "object_id": 3,
            "name": "Cosmos fragment",
            "position_km": [-7_050.0, 0.0, 60.0],
            "source_group": "COSMOS-2251-DEBRIS",
        },
    ]
    replay = simulate_policy(default_hazards(), max_steps=26)

    figure = build_command_globe(
        records,
        replay=replay,
        source_label="BUNDLED CELESTRAK GP REPLAY",
        displayed_at="03 Sep 2026 · 12:55 UTC",
    )
    payload = _figure_json(figure)

    trace_names = [trace.name for trace in figure.data]
    assert "FENGYUN 1C DEBRIS · 1" in trace_names
    assert "IRIDIUM 33 DEBRIS · 1" in trace_names
    assert "COSMOS 2251 DEBRIS · 1" in trace_names
    assert "Protected synthetic reference orbit" in trace_names
    assert "Controlled synthetic satellite" in trace_names
    assert figure.data[-1].marker.symbol == "diamond"
    assert "PUBLIC SGP4/TEME FIELD · 3 GROUP-QUERY OBJECTS" in figure.layout.title.text
    assert "BUNDLED CELESTRAK GP REPLAY" in figure.layout.title.text
    assert "CONSTRUCTED SYNTHETIC REFERENCE-ORBIT EMBEDDING" in figure.layout.title.text
    assert "PUBLIC MEAN-ELEMENT CONTEXT · NOT SENSOR TELEMETRY" in payload
    assert "Synthetic controlled satellite" in payload
    assert "Public GP/OMM display position" in payload


def test_empty_command_globe_still_declares_public_data_limitations() -> None:
    figure = build_command_globe(
        [],
        source_label="NO VALIDATED PUBLIC CATALOGUE",
        displayed_at="NOT AVAILABLE",
    )
    payload = _figure_json(figure)

    assert "PUBLIC SGP4/TEME FIELD · 0 GROUP-QUERY OBJECTS" in figure.layout.title.text
    assert "NO VALIDATED PUBLIC CATALOGUE" in figure.layout.title.text
    assert "CONSTRUCTED SYNTHETIC REFERENCE-ORBIT EMBEDDING" in figure.layout.title.text
    assert "PUBLIC MEAN-ELEMENT CONTEXT · NOT SENSOR TELEMETRY" in payload
    assert figure.data[-1].name == "Controlled synthetic satellite"


def test_encounter_replay_is_explicitly_hill_frame_and_animation_is_complete() -> None:
    baseline = simulate_policy(default_hazards(), max_steps=26)
    figure = build_encounter_replay(baseline, generation=1, baseline=baseline)
    payload = _figure_json(figure)

    assert len(figure.frames) == len(baseline["trajectory"])
    assert [trace.name for trace in figure.data[:3]] == [
        "Gen 0 path",
        "Gen 1 controlled path",
        "H-01 incoming path",
    ]
    assert figure.data[-2].marker.symbol == "diamond"
    assert figure.data[-1].marker.symbol == "x"
    assert "SYNTHETIC HILL/LVLH LOCAL OFFSETS" in figure.layout.title.text
    assert figure.layout.xaxis.title.text == "Radial offset x (km)"
    assert figure.layout.yaxis.title.text == "Along-track offset y (km)"
    assert "▶ PLAY" in payload
    assert "❚❚ PAUSE" in payload
    assert len(figure.layout.sliders[0].steps) == len(baseline["trajectory"])


def test_training_curve_includes_gen_zero_and_marks_selected_generation() -> None:
    result = {
        "baseline_evaluation": {"reward": -10.0},
        "training_curve": [
            {"generation": 1, "mean_return": -6.0},
            {"generation": 2, "mean_return": 4.0},
        ],
        "policy_evolution": [
            {"reward": -10.0},
            {"reward": -2.0},
            {"reward": 8.0},
        ],
    }

    figure = build_training_curve(result, selected_generation=1)

    assert list(figure.data[0].x) == [0, 1, 2]
    assert list(figure.data[0].y) == [-10.0, -6.0, 4.0]
    assert list(figure.data[1].y) == [-10.0, -2.0, 8.0]
    assert figure.data[0].name == "Population mean"
    assert figure.data[1].name == "Retained policy replay"
    assert figure.layout.shapes[0].x0 == 1
    assert figure.layout.shapes[0].x1 == 1


def test_action_mix_preserves_full_declared_action_order_and_zero_counts() -> None:
    replay = {"action_names": ["COAST", "PROGRADE", "COAST"]}

    counts = action_mix(replay)

    assert list(counts) == list(ACTION_NAMES)
    assert counts == {
        "COAST": 2,
        "RADIAL OUT": 0,
        "RADIAL IN": 0,
        "PROGRADE": 1,
        "RETROGRADE": 0,
    }


def test_command_figures_are_deterministic_for_identical_inputs() -> None:
    replay = simulate_policy(default_hazards(), max_steps=26)
    kwargs = {
        "replay": replay,
        "source_label": "BUNDLED CELESTRAK GP REPLAY",
        "displayed_at": "03 Sep 2026 · 12:55 UTC",
    }

    assert _figure_json(build_command_globe([], **kwargs)) == _figure_json(
        build_command_globe([], **kwargs)
    )
    assert _figure_json(
        build_encounter_replay(replay, generation=0)
    ) == _figure_json(build_encounter_replay(replay, generation=0))
