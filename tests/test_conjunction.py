from __future__ import annotations

from dataclasses import replace
from math import isclose

import pytest

from orbit_guard.conjunction import (
    ManoeuvreOption,
    assess_option,
    choose_recommendation,
    required_delta_v,
    result_by_id,
)
from orbit_guard.demo import DEFAULT_SCENARIO_PATH, assess_scenario
from orbit_guard.scenario_io import load_scenario


@pytest.fixture()
def scenario():
    return load_scenario(DEFAULT_SCENARIO_PATH)


def test_judge_fixture_has_exact_nominal_geometry(scenario) -> None:
    assert scenario.synthetic is True
    assert scenario.time_to_closest_approach_s == pytest.approx(21_600.0)
    assert scenario.nominal_tca_offset_m == pytest.approx((0.0, 120.0))
    assert scenario.baseline_miss_m == pytest.approx(120.0)


def test_four_options_reproduce_headline_numbers(scenario) -> None:
    results = assess_scenario(scenario)

    assert result_by_id(results, "hold").projected_miss_m == pytest.approx(120.0)
    assert result_by_id(results, "act_now").projected_miss_m == pytest.approx(1_200.0)
    assert result_by_id(results, "wait_same_burn").projected_miss_m == pytest.approx(255.0)
    assert result_by_id(results, "wait_recover_margin").projected_miss_m == pytest.approx(1_200.0)

    assert result_by_id(results, "hold").buffer_met is False
    assert result_by_id(results, "wait_same_burn").buffer_met is False
    assert result_by_id(results, "act_now").buffer_met is True
    assert result_by_id(results, "wait_recover_margin").buffer_met is True


def test_early_option_is_lowest_demand_passing_recommendation(scenario) -> None:
    recommendation = choose_recommendation(assess_scenario(scenario))
    assert recommendation.option.option_id == "act_now"
    assert recommendation.buffer_met is True
    assert recommendation.option.cross_track_delta_v_mps == pytest.approx(0.05)


def test_delay_penalty_for_same_margin_is_eightfold(scenario) -> None:
    results = assess_scenario(scenario)
    early = result_by_id(results, "act_now")
    delayed = result_by_id(results, "wait_recover_margin")
    assert delayed.projected_miss_m == pytest.approx(early.projected_miss_m)
    assert (
        delayed.option.cross_track_delta_v_mps
        / early.option.cross_track_delta_v_mps
    ) == pytest.approx(8.0)


def test_required_delta_v_curve_hits_reference_points(scenario) -> None:
    target = result_by_id(assess_scenario(scenario), "act_now").projected_miss_m
    assert required_delta_v(
        scenario, lead_time_s=6 * 3600, target_separation_m=target
    ) == pytest.approx(0.05)
    assert required_delta_v(
        scenario, lead_time_s=45 * 60, target_separation_m=target
    ) == pytest.approx(0.4)


def test_rejects_option_beyond_warning_horizon(scenario) -> None:
    invalid = ManoeuvreOption(
        option_id="too_early",
        label="Outside fixture",
        lead_time_s=scenario.time_to_closest_approach_s + 1,
        cross_track_delta_v_mps=0.01,
        description="Invalid test option",
    )
    with pytest.raises(ValueError, match="warning horizon"):
        assess_option(scenario, invalid)


def test_rejects_non_synthetic_and_non_finite_scenarios(scenario) -> None:
    with pytest.raises(ValueError, match="synthetic"):
        replace(scenario, synthetic=False)
    with pytest.raises(ValueError, match="finite"):
        replace(scenario, relative_position_m=(float("nan"), 0.0))


def test_result_is_deterministic(scenario) -> None:
    first = assess_scenario(scenario)
    second = assess_scenario(scenario)
    assert first == second
    assert isclose(first[1].projected_miss_m, second[1].projected_miss_m)
