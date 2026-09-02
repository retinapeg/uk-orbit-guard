"""Training entrypoint for PPO on the satellite avoidance environment."""

from __future__ import annotations

import argparse

from .env import AvoidanceConfig, SatelliteAvoidanceEnv


def build_args():
    parser = argparse.ArgumentParser(description="Train satellite avoidance policy.")
    parser.add_argument("--timesteps", type=int, default=50_000, help="Total PPO timesteps.")
    parser.add_argument("--num-bodies", type=int, default=6, help="Number of rotating obstacles.")
    parser.add_argument("--max-steps", type=int, default=1_000, help="Episode horizon.")
    parser.add_argument("--dt", type=float, default=0.5, help="Simulation timestep (s).")
    return parser.parse_args()


def main():
    args = build_args()
    config = AvoidanceConfig(
        num_bodies=args.num_bodies,
        dt=args.dt,
        max_steps=args.max_steps,
    )
    env = SatelliteAvoidanceEnv(config=config)

    try:
        from stable_baselines3 import PPO
    except ImportError as err:  # pragma: no cover
        raise SystemExit(
            "stable-baselines3 is required for this script. Install with: pip install stable-baselines3."
        ) from err

    model = PPO("MlpPolicy", env, verbose=1)
    model.learn(total_timesteps=args.timesteps)
    model.save("artifacts/ppo_satellite_avoidance.zip")


if __name__ == "__main__":
    main()

