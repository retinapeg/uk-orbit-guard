"""Core gravitation math for the satellite avoidance environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

GRAVITATIONAL_CONSTANT = 6.67430e-11
EARTH_GM = 3.986004418e14  # m^3 / s^2
EARTH_RADIUS_M = 6_378_137.0
EPSILON = 1e-9


@dataclass(frozen=True)
class RotatingBody:
    """Simple rotating point-mass in Earth-centered inertial coordinates."""

    name: str
    mu: float
    orbital_radius: float
    angular_velocity: float
    phase: float = 0.0
    z: float = 0.0

    def position(self, t: float) -> np.ndarray:
        angle = self.angular_velocity * t + self.phase
        return np.array(
            [
                self.orbital_radius * np.cos(angle),
                self.orbital_radius * np.sin(angle),
                self.z,
            ],
            dtype=float,
        )


def make_default_bodies(
    num_bodies: int,
    *,
    mu: float = 4.9e8,
    orbital_radius: float = 4.0e7,
    angular_velocity: float = 1.1e-3,
) -> list[RotatingBody]:
    """Build N equally spaced debris/planet bodies on a circular ring."""
    bodies: list[RotatingBody] = []
    if num_bodies <= 0:
        return bodies

    for idx in range(num_bodies):
        phase = (2.0 * np.pi * idx) / num_bodies
        bodies.append(
            RotatingBody(
                name=f"body_{idx+1}",
                mu=mu,
                orbital_radius=orbital_radius,
                angular_velocity=angular_velocity * (1.0 + 0.02 * idx),
                phase=phase,
            )
        )

    return bodies


def gravitational_acceleration(
    satellite_position: np.ndarray,
    t: float,
    bodies: Sequence[RotatingBody],
    earth_mu: float = EARTH_GM,
) -> np.ndarray:
    """Compute gravitational acceleration on satellite from Earth and rotating bodies."""
    position = np.asarray(satellite_position, dtype=float)
    distance_to_earth = np.linalg.norm(position)
    accel = -earth_mu * position / ((distance_to_earth + EPSILON) ** 3)

    for body in bodies:
        relative = position - body.position(t)
        distance_to_body = np.linalg.norm(relative)
        accel -= body.mu * relative / ((distance_to_body + EPSILON) ** 3)

    return accel


def satellite_derivative(
    state: np.ndarray,
    t: float,
    control_accel: np.ndarray,
    bodies: Sequence[RotatingBody],
    earth_mu: float,
) -> np.ndarray:
    """State derivative for [x, y, z, vx, vy, vz]."""
    state = np.asarray(state, dtype=float)
    position = state[:3]
    velocity = state[3:]
    gravity = gravitational_acceleration(position, t, bodies, earth_mu=earth_mu)
    d_position = velocity
    d_velocity = gravity + np.asarray(control_accel, dtype=float)
    return np.concatenate((d_position, d_velocity), axis=0)


def rk4_step(
    state: np.ndarray,
    t: float,
    dt: float,
    control_accel: np.ndarray,
    bodies: Sequence[RotatingBody],
    *,
    earth_mu: float = EARTH_GM,
) -> np.ndarray:
    """Fourth-order Runge-Kutta update for one control step."""
    state = np.asarray(state, dtype=float)
    control_accel = np.asarray(control_accel, dtype=float)

    k1 = satellite_derivative(state, t, control_accel, bodies, earth_mu)
    k2 = satellite_derivative(state + 0.5 * dt * k1, t + 0.5 * dt, control_accel, bodies, earth_mu)
    k3 = satellite_derivative(state + 0.5 * dt * k2, t + 0.5 * dt, control_accel, bodies, earth_mu)
    k4 = satellite_derivative(state + dt * k3, t + dt, control_accel, bodies, earth_mu)

    return state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

