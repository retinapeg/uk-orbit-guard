"""Gym-compatible satellite avoidance environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from .physics import (
    EARTH_GM,
    EARTH_RADIUS_M,
    RotatingBody,
    make_default_bodies,
    rk4_step,
)


@dataclass
class AvoidanceConfig:
    """Hyper-parameters for dynamics and reward shaping."""

    num_bodies: int = 6
    dt: float = 0.5
    max_steps: int = 1_000
    max_thrust: float = 0.05  # m/s^2
    min_altitude: float = 200e3
    max_altitude: float = 1_500e3
    collision_radius: float = 8e5
    max_radius: float = 1.2e8
    earth_mu: float = EARTH_GM


class SatelliteAvoidanceEnv(gym.Env):
    """Satellite avoids N moving circularly rotating gravitating bodies."""

    def __init__(self, config: AvoidanceConfig | None = None, bodies: list[RotatingBody] | None = None):
        super().__init__()
        self.config = config or AvoidanceConfig()
        self.bodies = bodies if bodies is not None else make_default_bodies(self.config.num_bodies)
        self.config.num_bodies = len(self.bodies)
        self.state = np.zeros(6, dtype=float)
        self.t = 0.0
        self.steps = 0
        self._rng = np.random.default_rng()

        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(6 + 3 * len(self.bodies),),
            dtype=np.float64,
        )
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(3,),
            dtype=np.float64,
        )

    def _sample_initial_state(self) -> np.ndarray:
        altitude = float(self._rng.uniform(self.config.min_altitude, self.config.max_altitude))
        radius = EARTH_RADIUS_M + altitude
        theta = float(self._rng.uniform(0.0, 2.0 * np.pi))
        tangential = np.array([-np.sin(theta), np.cos(theta), 0.0], dtype=float)
        position = radius * np.array([np.cos(theta), np.sin(theta), 0.0], dtype=float)
        speed = np.sqrt(self.config.earth_mu / radius)
        velocity = speed * tangential
        return np.concatenate((position, velocity), axis=0)

    def _relative_body_positions(self, state: np.ndarray, t: float) -> np.ndarray:
        sat_pos = state[:3]
        rel = []
        for body in self.bodies:
            rel.append(sat_pos - body.position(t))
        return np.asarray(rel, dtype=float)

    def _observe(self) -> np.ndarray:
        rel = self._relative_body_positions(self.state, self.t).reshape(-1)
        return np.concatenate((self.state, rel), axis=0).astype(np.float64)

    def _min_distance(self) -> float:
        if len(self.bodies) == 0:
            return self.config.max_radius
        rel = self._relative_body_positions(self.state, self.t)
        return float(np.min(np.linalg.norm(rel, axis=1)))

    def reset(self, seed: int | None = None, options: Dict | None = None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self.state = self._sample_initial_state()
        self.t = 0.0
        self.steps = 0
        return self._observe(), {}

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        action = np.asarray(action, dtype=float)
        action = np.clip(action, self.action_space.low, self.action_space.high)
        control_accel = action * self.config.max_thrust

        next_state = rk4_step(
            self.state,
            self.t,
            self.config.dt,
            control_accel,
            self.bodies,
            earth_mu=self.config.earth_mu,
        )
        self.state = next_state
        self.t += self.config.dt
        self.steps += 1

        min_distance = self._min_distance()
        reward = 0.002 * min_distance - 0.05 * np.dot(action, action) - 0.001 * self.t

        terminated = min_distance <= self.config.collision_radius
        truncated = self.steps >= self.config.max_steps or np.linalg.norm(self.state[:3]) > self.config.max_radius

        if terminated:
            reward -= 100.0
        if truncated:
            reward -= 10.0

        info = {
            "time_s": self.t,
            "step": self.steps,
            "min_distance_m": min_distance,
            "terminated": terminated,
        }
        return self._observe(), float(reward), terminated, truncated, info
