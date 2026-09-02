"""Satellite avoidance simulator package."""

from .physics import GRAVITATIONAL_CONSTANT, EARTH_RADIUS_M, EARTH_GM, RotatingBody
from .env import SatelliteAvoidanceEnv, AvoidanceConfig
