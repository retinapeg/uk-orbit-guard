from __future__ import annotations

from copy import deepcopy
import math

import pytest

from orbit_guard.rl_core import (
    ACTION_NAMES,
    DEFAULT_STEPS,
    DT_SECONDS,
    OBSERVATION_DIM,
    POLICY_PARAMETER_COUNT,
    THRUST_KM_S2,
    default_hazards,
    hazards_from_payload,
    hazards_to_payload,
    make_hazard,
    scenario_fingerprint,
    simulate_policy,
    train_policy,
    weights_sha256,
    zero_policy,
)


def test_injected_hazard_templates_round_trip_and_bind_the_scenario_hash() -> None:
    hazards = [
        make_hazard("head_on", 0),
        make_hazard("crossing", 1),
        make_hazard("fast_debris", 2),
    ]
    payload = hazards_to_payload(hazards)

    assert hazards_from_payload(payload) == hazards
    assert scenario_fingerprint(hazards) == scenario_fingerprint(hazards)
    assert scenario_fingerprint(hazards, DEFAULT_STEPS - 1) != scenario_fingerprint(
        hazards, DEFAULT_STEPS
    )
    assert scenario_fingerprint(hazards[:2]) != scenario_fingerprint(hazards)

    tampered = deepcopy(payload)
    tampered[1]["x0_km"] += 0.001
    with pytest.raises(ValueError, match="deterministic injection template"):
        hazards_from_payload(tampered)

    extra_field = deepcopy(payload)
    extra_field[0]["confidence"] = 1.0
    with pytest.raises(ValueError, match="schema mismatch"):
        hazards_from_payload(extra_field)

    with pytest.raises(ValueError, match="unique"):
        hazards_to_payload([make_hazard("head_on", 0), make_hazard("head_on", 0)])


@pytest.mark.parametrize(
    ("kind", "index"),
    [("unknown", 0), ("head_on", -1), ("head_on", True), ("head_on", 6)],
)
def test_injection_factory_rejects_non_allowlisted_or_out_of_range_inputs(
    kind: str, index: int
) -> None:
    with pytest.raises(ValueError):
        make_hazard(kind, index)


def test_gen_zero_replay_is_deterministic_and_internally_coherent() -> None:
    first = simulate_policy(default_hazards(), max_steps=DEFAULT_STEPS)
    second = simulate_policy(default_hazards(), max_steps=DEFAULT_STEPS)

    assert first == second
    assert first["termination"] == "keep_out_breach"
    assert first["success"] is False
    assert first["steps"] == 25
    assert first["min_clearance_km"] == pytest.approx(0.22803508501982736)
    assert first["closest_object_id"] == "H-01"
    assert first["fuel_impulse_m_s"] == 0.0
    assert first["actions"] == [0] * first["steps"]
    assert first["action_names"] == [ACTION_NAMES[0]] * first["steps"]
    assert len(first["observations"]) == first["steps"]
    assert all(len(observation) == OBSERVATION_DIM for observation in first["observations"])
    assert len(first["trajectory"]) == first["steps"] + 1
    assert [point["time_s"] for point in first["trajectory"]] == [
        index * DT_SECONDS for index in range(first["steps"] + 1)
    ]
    computed_minimum = min(
        body["distance_km"]
        for point in first["trajectory"][1:]
        for body in point["objects"]
    )
    assert first["min_clearance_km"] == pytest.approx(computed_minimum)
    assert first["reward"] == pytest.approx(math.fsum(first["rewards"]))


def test_observation_tca_uses_the_requested_episode_horizon() -> None:
    short = simulate_policy(default_hazards(), max_steps=12)
    full = simulate_policy(default_hazards(), max_steps=DEFAULT_STEPS)

    # The head-on template reaches TCA after 520 s. A 12-step (240 s) run must
    # clamp the normalized TCA to its own horizon, not the 72-step default.
    assert short["observations"][0][8] == pytest.approx(1.0)
    assert full["observations"][0][8] == pytest.approx(
        520.0 / (DEFAULT_STEPS * DT_SECONDS)
    )


def test_thrust_units_equal_point_one_metre_per_second_per_commanded_step() -> None:
    weights = zero_policy()
    stride = OBSERVATION_DIM + 1
    weights[stride + OBSERVATION_DIM] = 1.0  # RADIAL OUT bias.

    replay = simulate_policy([], weights, max_steps=3)

    assert replay["actions"] == [1, 1, 1]
    expected_per_step_m_s = THRUST_KM_S2 * 1_000.0 * DT_SECONDS
    assert expected_per_step_m_s == pytest.approx(0.1)
    assert replay["fuel_impulse_m_s"] == pytest.approx(0.3)


def test_minimal_cem_run_is_reproducible_and_records_a_changed_checkpoint() -> None:
    kwargs = {
        "seed": 42,
        "generations": 2,
        "population": 6,
        "episodes_per_candidate": 1,
        "max_steps": 26,
        "sandbox_id": "sandbox-test",
        "invocation_id": "invocation-test",
        "runtime_bundle_sha256": "a" * 64,
    }
    first = train_policy(default_hazards(), **kwargs)
    second = train_policy(default_hazards(), **kwargs)

    for field in (
        "trained_weights",
        "trained_checkpoint_sha256",
        "training_curve",
        "policy_evolution",
        "baseline_evaluation",
        "trained_evaluation",
    ):
        assert first[field] == second[field]
    assert len(first["trained_weights"]) == POLICY_PARAMETER_COUNT
    assert first["training_episodes"] == 12
    assert len(first["training_curve"]) == 2
    assert [point["generation"] for point in first["policy_evolution"]] == [0, 1, 2]
    assert all(
        len(point["weights"]) == POLICY_PARAMETER_COUNT
        and point["checkpoint_sha256"] == weights_sha256(point["weights"])
        for point in first["policy_evolution"]
    )
    assert first["policy_evolution"][0]["weights"] == zero_policy()
    assert first["policy_evolution"][-1]["weights"] == first["trained_weights"]
    assert first["weights_changed"] is True
    assert first["changed_parameter_elements"] > 0
    assert first["trained_checkpoint_sha256"] == weights_sha256(first["trained_weights"])
    assert first["trained_checkpoint_sha256"] != first["initial_checkpoint_sha256"]
    assert first["integrity"] == {
        "result_is_synthetic": True,
        "operational_use": False,
        "human_authority_required": True,
        "worker_runtime": "Python standard library only",
    }
    assert first["reference_frame"]["simulation_frame"] == (
        "planar Hill/LVLH local encounter frame"
    )


def test_an_injected_object_changes_both_frozen_hash_and_actual_replay() -> None:
    one = default_hazards()
    two = [*one, make_hazard("crossing", 1)]

    one_replay = simulate_policy(one, max_steps=26)
    two_replay = simulate_policy(two, max_steps=26)

    assert scenario_fingerprint(one, 26) != scenario_fingerprint(two, 26)
    assert len(one_replay["trajectory"][0]["objects"]) == 1
    assert len(two_replay["trajectory"][0]["objects"]) == 2
    assert two_replay["trajectory"][0]["objects"][1]["object_id"] == "X-02"


@pytest.mark.parametrize(
    "overrides",
    [
        {"generations": 1},
        {"population": 5},
        {"episodes_per_candidate": 0},
        {"max_steps": 11},
    ],
)
def test_training_rejects_out_of_contract_search_sizes(overrides: dict[str, int]) -> None:
    kwargs = {
        "generations": 2,
        "population": 6,
        "episodes_per_candidate": 1,
        "max_steps": 26,
        **overrides,
    }
    with pytest.raises(ValueError):
        train_policy(default_hazards(), **kwargs)

    with pytest.raises(ValueError, match="at least one injected object"):
        train_policy([], generations=2, population=6, episodes_per_candidate=1, max_steps=26)
