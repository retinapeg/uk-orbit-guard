"""Helpers for integrating with a Daytona-style training loop."""

from __future__ import annotations

from dataclasses import asdict

from .env import AvoidanceConfig, SatelliteAvoidanceEnv


def make_daytona_task_kwargs(
    *,
    num_bodies: int = 6,
    dt: float = 0.5,
    max_steps: int = 1_000,
    total_timesteps: int = 50_000,
):
    """
    Return a lightweight configuration block you can pass into Daytona job templates.

    Keep this function small and deterministic so Daytona can serialize it cleanly.
    """
    config = AvoidanceConfig(num_bodies=num_bodies, dt=dt, max_steps=max_steps)
    return {
        "env": {"class_path": "sat_avoid.env.SatelliteAvoidanceEnv", "kwargs": asdict(config)},
        "train": {"total_timesteps": total_timesteps},
        "command": "python -m sat_avoid.train",
    }


def build_env_for_daytona(config_dict: dict) -> SatelliteAvoidanceEnv:
    """Deserialize and build an env from a config dict."""
    config = AvoidanceConfig(**config_dict)
    return SatelliteAvoidanceEnv(config=config)

