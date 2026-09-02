from __future__ import annotations

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from sat_avoid.env import AvoidanceConfig, SatelliteAvoidanceEnv
from sat_avoid.physics import EARTH_RADIUS_M


def test_gym_contract_and_seeded_reset() -> None:
    env = SatelliteAvoidanceEnv(AvoidanceConfig(max_steps=5))
    check_env(env, skip_render_check=True)
    first, _ = env.reset(seed=42)
    second, _ = env.reset(seed=42)
    assert np.array_equal(first, second)
    assert env.observation_space.contains(first)


def test_earth_impact_terminates_with_negative_reward() -> None:
    env = SatelliteAvoidanceEnv(
        AvoidanceConfig(earth_mu=0.0, max_steps=5),
        bodies=[],
    )
    env.reset(seed=1)
    env.state = np.array([EARTH_RADIUS_M - 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    _, reward, terminated, truncated, info = env.step(np.zeros(3))
    assert terminated is True
    assert truncated is False
    assert reward < 0
    assert info["earth_impact"] is True
    assert info["termination_reason"] == "earth_impact"


@pytest.mark.parametrize(
    "action",
    [np.array([0.0]), np.array([0.0, float("nan"), 0.0])],
)
def test_invalid_actions_are_rejected(action) -> None:
    env = SatelliteAvoidanceEnv(AvoidanceConfig(max_steps=5))
    env.reset(seed=1)
    with pytest.raises(ValueError):
        env.step(action)
