"""Transparent local encounter model for the OrbitGuard UK demo.

The model uses constant relative velocity in a two-dimensional local encounter
plane and an instantaneous cross-track impulse. It exists to make the value of
warning lead time legible; it is not an operational orbit propagator.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite, sqrt
from typing import Iterable, Mapping, Sequence

MODEL_VERSION = "local-linear-v0.1"


def _pair(name: str, values: Sequence[float]) -> tuple[float, float]:
    if len(values) != 2:
        raise ValueError(f"{name} must contain exactly two values")
    pair = float(values[0]), float(values[1])
    if not all(isfinite(value) for value in pair):
        raise ValueError(f"{name} values must be finite")
    return pair


@dataclass(frozen=True)
class ManoeuvreOption:
    """One synthetic cross-track manoeuvre option."""

    option_id: str
    label: str
    lead_time_s: float
    cross_track_delta_v_mps: float
    description: str

    def __post_init__(self) -> None:
        if not self.option_id.strip() or not self.label.strip():
            raise ValueError("option_id and label must not be empty")
        if not isfinite(self.lead_time_s) or self.lead_time_s < 0:
            raise ValueError("lead_time_s must not be negative")
        if not isfinite(self.cross_track_delta_v_mps) or self.cross_track_delta_v_mps < 0:
            raise ValueError("cross_track_delta_v_mps must not be negative")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "ManoeuvreOption":
        for field in ("option_id", "label", "lead_time_s", "cross_track_delta_v_mps", "description"):
            if field not in data:
                raise ValueError(f"manoeuvre option is missing required field: {field}")
        return cls(
            option_id=str(data["option_id"]),
            label=str(data["label"]),
            lead_time_s=float(data["lead_time_s"]),
            cross_track_delta_v_mps=float(data["cross_track_delta_v_mps"]),
            description=str(data["description"]),
        )


@dataclass(frozen=True)
class ConjunctionScenario:
    """A wholly synthetic conjunction fixture and illustrative policy target."""

    scenario_id: str
    seed: int
    synthetic: bool
    protected_asset: str
    protected_service: str
    secondary_object: str
    orbit_context: str
    relative_position_m: tuple[float, float]
    relative_velocity_mps: tuple[float, float]
    illustrative_buffer_m: float
    options: tuple[ManoeuvreOption, ...]

    def __post_init__(self) -> None:
        if not self.synthetic:
            raise ValueError("the hackathon model accepts synthetic scenarios only")
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be empty")
        if not isfinite(self.illustrative_buffer_m) or self.illustrative_buffer_m <= 0:
            raise ValueError("illustrative_buffer_m must be greater than zero")
        if not all(isfinite(value) for value in (*self.relative_position_m, *self.relative_velocity_mps)):
            raise ValueError("relative state values must be finite")
        if self.relative_velocity_mps == (0.0, 0.0):
            raise ValueError("relative velocity must not be zero")
        if not self.options:
            raise ValueError("at least one manoeuvre option is required")
        if len({option.option_id for option in self.options}) != len(self.options):
            raise ValueError("manoeuvre option IDs must be unique")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "ConjunctionScenario":
        raw_options = data.get("options")
        if not isinstance(raw_options, list):
            raise ValueError("options must be a list")
        if type(data.get("synthetic")) is not bool:
            raise ValueError("synthetic must be a JSON boolean")
        if type(data.get("seed")) is not int:
            raise ValueError("seed must be a JSON integer")
        if not all(isinstance(item, Mapping) for item in raw_options):
            raise ValueError("every manoeuvre option must be a JSON object")
        return cls(
            scenario_id=str(data["scenario_id"]),
            seed=int(data["seed"]),
            synthetic=data["synthetic"],  # type: ignore[arg-type]
            protected_asset=str(data["protected_asset"]),
            protected_service=str(data["protected_service"]),
            secondary_object=str(data["secondary_object"]),
            orbit_context=str(data["orbit_context"]),
            relative_position_m=_pair(
                "relative_position_m", data["relative_position_m"]  # type: ignore[arg-type]
            ),
            relative_velocity_mps=_pair(
                "relative_velocity_mps", data["relative_velocity_mps"]  # type: ignore[arg-type]
            ),
            illustrative_buffer_m=float(data["illustrative_buffer_m"]),
            options=tuple(ManoeuvreOption.from_mapping(item) for item in raw_options),
        )

    @property
    def time_to_closest_approach_s(self) -> float:
        """Return the nominal TCA for constant relative velocity."""

        rx, ry = self.relative_position_m
        vx, vy = self.relative_velocity_mps
        velocity_squared = vx * vx + vy * vy
        return max(0.0, -((rx * vx + ry * vy) / velocity_squared))

    @property
    def nominal_tca_offset_m(self) -> tuple[float, float]:
        tca = self.time_to_closest_approach_s
        rx, ry = self.relative_position_m
        vx, vy = self.relative_velocity_mps
        return rx + vx * tca, ry + vy * tca

    @property
    def baseline_miss_m(self) -> float:
        x, y = self.nominal_tca_offset_m
        return hypot(x, y)


@dataclass(frozen=True)
class OptionResult:
    """Computed closest-approach result for one option."""

    option: ManoeuvreOption
    projected_tca_offset_m: tuple[float, float]
    projected_miss_m: float
    buffer_met: bool
    displacement_m: float
    warning_fraction_used: float


def assess_option(
    scenario: ConjunctionScenario,
    option: ManoeuvreOption,
) -> OptionResult:
    """Apply an idealised cross-track impulse and assess the illustrative buffer."""

    if option.lead_time_s > scenario.time_to_closest_approach_s + 1e-9:
        raise ValueError("option lead time cannot exceed the scenario warning horizon")

    x_at_tca, y_at_tca = scenario.nominal_tca_offset_m
    direction = 1.0 if y_at_tca >= 0 else -1.0
    displacement_m = option.cross_track_delta_v_mps * option.lead_time_s
    projected_offset = x_at_tca, y_at_tca + direction * displacement_m
    projected_miss_m = hypot(*projected_offset)
    horizon = scenario.time_to_closest_approach_s

    return OptionResult(
        option=option,
        projected_tca_offset_m=projected_offset,
        projected_miss_m=projected_miss_m,
        buffer_met=projected_miss_m >= scenario.illustrative_buffer_m,
        displacement_m=displacement_m,
        warning_fraction_used=option.lead_time_s / horizon if horizon else 0.0,
    )


def required_delta_v(
    scenario: ConjunctionScenario,
    *,
    lead_time_s: float,
    target_separation_m: float | None = None,
) -> float:
    """Return the idealised cross-track delta-v required for a target separation."""

    if lead_time_s <= 0:
        raise ValueError("lead_time_s must be greater than zero")
    if lead_time_s > scenario.time_to_closest_approach_s + 1e-9:
        raise ValueError("lead_time_s cannot exceed the warning horizon")

    target = (
        scenario.illustrative_buffer_m
        if target_separation_m is None
        else target_separation_m
    )
    if target <= 0:
        raise ValueError("target_separation_m must be greater than zero")

    x_at_tca, y_at_tca = scenario.nominal_tca_offset_m
    if abs(x_at_tca) >= target:
        return 0.0
    required_cross_track = sqrt(max(0.0, target * target - x_at_tca * x_at_tca))
    additional_displacement = max(0.0, required_cross_track - abs(y_at_tca))
    return additional_displacement / lead_time_s


def choose_recommendation(results: Iterable[OptionResult]) -> OptionResult:
    """Choose the smallest manoeuvre budget that meets the illustrative buffer."""

    candidates = list(results)
    if not candidates:
        raise ValueError("at least one option result is required")
    passing = [result for result in candidates if result.buffer_met]
    if passing:
        return min(
            passing,
            key=lambda result: (
                result.option.cross_track_delta_v_mps,
                -result.option.lead_time_s,
                -result.projected_miss_m,
            ),
        )
    return max(candidates, key=lambda result: result.projected_miss_m)


def result_by_id(results: Iterable[OptionResult], option_id: str) -> OptionResult:
    for result in results:
        if result.option.option_id == option_id:
            return result
    raise KeyError(f"unknown option_id: {option_id}")
