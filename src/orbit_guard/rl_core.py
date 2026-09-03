"""Dependency-free reinforcement-learning core for the live Daytona demo.

The simulation is intentionally a small, auditable teaching model.  It uses a
planar Hill-frame approximation around a circular 550 km reference orbit.  The
protected satellite can apply one of five discrete thrust commands while up to
six synthetic objects move through the local encounter frame.

Training uses the cross-entropy method (CEM): a model-free episodic policy-search
algorithm.  It optimises a fixed-size linear policy from complete rollout
returns and needs only the Python standard library, which keeps the code sent to
a Daytona sandbox small and inspectable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import random
from typing import Any, Iterable, Mapping, Sequence


MODEL_VERSION = "hill-cem-v1"
RESULT_FORMAT = "uk-orbit-guard-daytona-rl"
RESULT_VERSION = 1

EARTH_RADIUS_KM = 6_378.137
EARTH_MU_KM3_S2 = 398_600.4418
ORBIT_ALTITUDE_KM = 550.0
ORBIT_RADIUS_KM = EARTH_RADIUS_KM + ORBIT_ALTITUDE_KM
MEAN_MOTION_RAD_S = math.sqrt(EARTH_MU_KM3_S2 / ORBIT_RADIUS_KM**3)

MAX_OBJECTS = 6
DT_SECONDS = 20.0
DEFAULT_STEPS = 72
SAFETY_RADIUS_KM = 0.35
THRUST_KM_S2 = 0.000005  # 0.005 m/s^2; 0.10 m/s impulse per 20 s command.

ACTION_NAMES = (
    "COAST",
    "RADIAL OUT",
    "RADIAL IN",
    "PROGRADE",
    "RETROGRADE",
)
ACTION_ACCELERATIONS = (
    (0.0, 0.0),
    (THRUST_KM_S2, 0.0),
    (-THRUST_KM_S2, 0.0),
    (0.0, THRUST_KM_S2),
    (0.0, -THRUST_KM_S2),
)

# Satellite state (4), nearest-object relative state (4), TCA/miss (2),
# object count (1), episode progress (1).  This never changes when objects are
# added or removed, so one policy can handle all injection-button scenarios.
OBSERVATION_DIM = 12
POLICY_PARAMETER_COUNT = len(ACTION_NAMES) * (OBSERVATION_DIM + 1)

UTC = timezone.utc


@dataclass(frozen=True)
class Hazard:
    """One synthetic uncooperative object in the local encounter frame."""

    object_id: str
    kind: str
    label: str
    x0_km: float
    y0_km: float
    vx_km_s: float
    vy_km_s: float
    colour: str

    def position(self, time_s: float) -> tuple[float, float]:
        return (
            self.x0_km + self.vx_km_s * time_s,
            self.y0_km + self.vy_km_s * time_s,
        )


def make_hazard(kind: str, index: int = 0) -> Hazard:
    """Create one of the three judge-facing synthetic encounter templates."""

    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("index must be a non-negative integer")
    if index >= MAX_OBJECTS:
        raise ValueError(f"at most {MAX_OBJECTS} injected objects are supported")

    # Stagger repeated injections so every object remains visible and produces
    # a distinct time of closest approach inside the 24-minute horizon.
    tca_s = 520.0 + 120.0 * index
    serial = index + 1
    if kind == "head_on":
        miss_x = 0.06 * (-1.0 if index % 2 else 1.0)
        speed = 0.011
        return Hazard(
            object_id=f"H-{serial:02d}",
            kind=kind,
            label=f"Head-on object {serial}",
            x0_km=miss_x,
            y0_km=speed * tca_s,
            vx_km_s=0.0,
            vy_km_s=-speed,
            colour="#ff395d",
        )
    if kind == "crossing":
        miss_y = 0.09 * (-1.0 if index % 2 else 1.0)
        speed = 0.009
        return Hazard(
            object_id=f"X-{serial:02d}",
            kind=kind,
            label=f"Crossing object {serial}",
            x0_km=speed * tca_s,
            y0_km=miss_y,
            vx_km_s=-speed,
            vy_km_s=0.0,
            colour="#fbbf24",
        )
    if kind == "fast_debris":
        vx = 0.0125
        vy = -0.0085
        return Hazard(
            object_id=f"D-{serial:02d}",
            kind=kind,
            label=f"Fast debris {serial}",
            x0_km=-vx * tca_s,
            y0_km=-vy * tca_s,
            vx_km_s=vx,
            vy_km_s=vy,
            colour="#fb7185",
        )
    raise ValueError("kind must be head_on, crossing, or fast_debris")


def default_hazards() -> list[Hazard]:
    """Return the single-object scenario shown on first load."""

    return [make_hazard("head_on", 0)]


def hazards_to_payload(hazards: Sequence[Hazard]) -> list[dict[str, Any]]:
    values = _validate_hazards(hazards)
    _validate_template_sequence(values)
    return [asdict(item) for item in values]


def hazards_from_payload(payload: Any) -> list[Hazard]:
    if not isinstance(payload, list):
        raise ValueError("hazards must be a list")
    hazards: list[Hazard] = []
    expected_fields = set(Hazard.__dataclass_fields__)
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"hazard {index} must be an object")
        if set(item) != expected_fields:
            raise ValueError(f"hazard {index} schema mismatch")
        try:
            hazard = Hazard(
                object_id=_non_empty_string(item.get("object_id"), "object_id"),
                kind=_non_empty_string(item.get("kind"), "kind"),
                label=_non_empty_string(item.get("label"), "label"),
                x0_km=_finite(item.get("x0_km"), "x0_km"),
                y0_km=_finite(item.get("y0_km"), "y0_km"),
                vx_km_s=_finite(item.get("vx_km_s"), "vx_km_s"),
                vy_km_s=_finite(item.get("vy_km_s"), "vy_km_s"),
                colour=_non_empty_string(item.get("colour"), "colour"),
            )
        except ValueError as exc:
            raise ValueError(f"invalid hazard {index}: {exc}") from exc
        hazards.append(hazard)
    values = _validate_hazards(hazards)
    _validate_template_sequence(values)
    return values


def scenario_fingerprint(hazards: Sequence[Hazard], max_steps: int = DEFAULT_STEPS) -> str:
    document = {
        "dt_seconds": DT_SECONDS,
        "hazards": hazards_to_payload(hazards),
        "max_steps": _positive_integer(max_steps, "max_steps"),
        "model_version": MODEL_VERSION,
        "safety_radius_km": SAFETY_RADIUS_KM,
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def encode_weights(weights: Sequence[float]) -> list[float]:
    values = [_finite(item, "policy weight") for item in weights]
    if len(values) != POLICY_PARAMETER_COUNT:
        raise ValueError(
            f"policy requires {POLICY_PARAMETER_COUNT} weights, received {len(values)}"
        )
    return values


def weights_sha256(weights: Sequence[float]) -> str:
    values = encode_weights(weights)
    payload = json.dumps(
        values,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def zero_policy() -> list[float]:
    """A deterministic untrained baseline; tied logits select COAST."""

    return [0.0] * POLICY_PARAMETER_COUNT


def simulate_policy(
    hazards: Sequence[Hazard],
    weights: Sequence[float] | None = None,
    *,
    max_steps: int = DEFAULT_STEPS,
    jitter_seed: int | None = None,
) -> dict[str, Any]:
    """Run one deterministic policy episode and return a JSON-safe trace."""

    validated_hazards = _validate_hazards(hazards)
    max_steps = _positive_integer(max_steps, "max_steps")
    policy = zero_policy() if weights is None else encode_weights(weights)
    episode_hazards = (
        validated_hazards
        if jitter_seed is None
        else _jitter_hazards(validated_hazards, jitter_seed)
    )

    x_km = 0.0
    y_km = 0.0
    vx_km_s = 0.0
    vy_km_s = 0.0
    time_s = 0.0
    min_clearance_km = float("inf")
    closest_object_id: str | None = None
    fuel_impulse_m_s = 0.0
    actions: list[int] = []
    rewards: list[float] = []
    observations: list[list[float]] = []
    trajectory: list[dict[str, Any]] = []
    termination = "horizon_clear"

    trajectory.append(
        _trajectory_point(
            time_s,
            x_km,
            y_km,
            vx_km_s,
            vy_km_s,
            episode_hazards,
            action_index=0,
        )
    )

    for step_index in range(max_steps):
        observation = _observation(
            x_km,
            y_km,
            vx_km_s,
            vy_km_s,
            time_s,
            episode_hazards,
            step_index,
            max_steps,
        )
        action_index = _select_action(policy, observation)
        ux, uy = ACTION_ACCELERATIONS[action_index]

        # Planar Clohessy-Wiltshire / Hill relative motion around the circular
        # reference orbit, integrated semi-implicitly for numerical stability.
        ax = 3.0 * MEAN_MOTION_RAD_S**2 * x_km + 2.0 * MEAN_MOTION_RAD_S * vy_km_s + ux
        ay = -2.0 * MEAN_MOTION_RAD_S * vx_km_s + uy
        vx_km_s += ax * DT_SECONDS
        vy_km_s += ay * DT_SECONDS
        x_km += vx_km_s * DT_SECONDS
        y_km += vy_km_s * DT_SECONDS
        time_s += DT_SECONDS

        distance_km, object_id = _nearest_distance(
            x_km, y_km, time_s, episode_hazards
        )
        if distance_km < min_clearance_km:
            min_clearance_km = distance_km
            closest_object_id = object_id

        used_thrust = action_index != 0
        if used_thrust:
            fuel_impulse_m_s += THRUST_KM_S2 * 1_000.0 * DT_SECONDS

        reward = 0.25
        reward -= 2.2 * math.exp(-distance_km / 0.85)
        reward -= 0.055 if used_thrust else 0.0
        reward -= 0.004 * min((math.hypot(x_km, y_km) / 4.0) ** 2, 20.0)

        collision = distance_km <= SAFETY_RADIUS_KM
        if collision:
            reward -= 120.0
            termination = "keep_out_breach"

        observations.append(observation)
        actions.append(action_index)
        rewards.append(float(reward))
        trajectory.append(
            _trajectory_point(
                time_s,
                x_km,
                y_km,
                vx_km_s,
                vy_km_s,
                episode_hazards,
                action_index=action_index,
            )
        )
        if collision:
            break

    success = termination == "horizon_clear"
    if success:
        rewards[-1] += 40.0

    if not math.isfinite(min_clearance_km):
        min_clearance_km = 999.0

    return {
        "success": success,
        "termination": termination,
        "steps": len(actions),
        "reward": float(math.fsum(rewards)),
        "min_clearance_km": float(min_clearance_km),
        "closest_object_id": closest_object_id,
        "fuel_impulse_m_s": float(fuel_impulse_m_s),
        "actions": actions,
        "action_names": [ACTION_NAMES[item] for item in actions],
        "rewards": rewards,
        "observations": observations,
        "trajectory": trajectory,
    }


def train_policy(
    hazards: Sequence[Hazard],
    *,
    seed: int = 42,
    generations: int = 10,
    population: int = 24,
    episodes_per_candidate: int = 3,
    max_steps: int = DEFAULT_STEPS,
    sandbox_id: str | None = None,
    invocation_id: str | None = None,
    runtime_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    """Train a fixed-size linear policy from episodic returns using CEM."""

    validated_hazards = _validate_hazards(hazards)
    seed = _integer(seed, "seed")
    generations = _bounded_integer(generations, "generations", 2, 80)
    population = _bounded_integer(population, "population", 6, 128)
    episodes_per_candidate = _bounded_integer(
        episodes_per_candidate, "episodes_per_candidate", 1, 12
    )
    max_steps = _bounded_integer(max_steps, "max_steps", 12, 240)
    if sandbox_id is not None:
        sandbox_id = _non_empty_string(sandbox_id, "sandbox_id")
    if invocation_id is not None:
        invocation_id = _non_empty_string(invocation_id, "invocation_id")
    if runtime_bundle_sha256 is not None:
        runtime_bundle_sha256 = _sha256_text(
            runtime_bundle_sha256, "runtime_bundle_sha256"
        )
    if not validated_hazards:
        raise ValueError("training requires at least one injected object")

    started = datetime.now(UTC)
    rng = random.Random(seed)
    initial_weights = zero_policy()
    initial_hash = weights_sha256(initial_weights)
    mean = initial_weights[:]
    std = [0.85] * POLICY_PARAMETER_COUNT
    elite_count = max(2, population // 5)
    best_weights = initial_weights[:]
    baseline_eval = simulate_policy(
        validated_hazards, initial_weights, max_steps=max_steps
    )
    best_validation_reward = float(baseline_eval["reward"])
    best_training_score = float("-inf")
    training_curve: list[dict[str, Any]] = []
    policy_evolution: list[dict[str, Any]] = [
        _evolution_point(0, initial_weights, baseline_eval)
    ]

    for generation in range(1, generations + 1):
        candidates = [mean[:]]
        while len(candidates) < population:
            candidates.append(
                [
                    rng.gauss(parameter_mean, parameter_std)
                    for parameter_mean, parameter_std in zip(mean, std)
                ]
            )

        scored: list[tuple[float, list[float], int]] = []
        success_count = 0
        for candidate_index, candidate in enumerate(candidates):
            episode_returns: list[float] = []
            candidate_successes = 0
            for episode_index in range(episodes_per_candidate):
                jitter_seed = (
                    seed * 1_000_003
                    + generation * 10_007
                    + candidate_index * 101
                    + episode_index
                )
                episode = simulate_policy(
                    validated_hazards,
                    candidate,
                    max_steps=max_steps,
                    jitter_seed=jitter_seed,
                )
                episode_returns.append(float(episode["reward"]))
                candidate_successes += int(bool(episode["success"]))
            score = math.fsum(episode_returns) / len(episode_returns)
            scored.append((score, candidate, candidate_successes))
            success_count += candidate_successes

        scored.sort(key=lambda item: item[0], reverse=True)
        elites = scored[:elite_count]
        elite_weights = [item[1] for item in elites]
        elite_mean = [
            math.fsum(weights[index] for weights in elite_weights) / elite_count
            for index in range(POLICY_PARAMETER_COUNT)
        ]
        elite_std: list[float] = []
        for index, centre in enumerate(elite_mean):
            variance = math.fsum(
                (weights[index] - centre) ** 2 for weights in elite_weights
            ) / elite_count
            elite_std.append(max(0.06, math.sqrt(variance)))

        mean = [0.25 * old + 0.75 * new for old, new in zip(mean, elite_mean)]
        std = [
            max(0.04, 0.35 * old + 0.65 * new)
            for old, new in zip(std, elite_std)
        ]

        generation_candidate = scored[0][1]
        generation_score = float(scored[0][0])
        validation = simulate_policy(
            validated_hazards,
            generation_candidate,
            max_steps=max_steps,
        )
        validation_reward = float(validation["reward"])
        if (
            validation_reward > best_validation_reward + 1.0e-9
            or (
                math.isclose(validation_reward, best_validation_reward)
                and generation_score > best_training_score
            )
        ):
            best_weights = generation_candidate[:]
            best_validation_reward = validation_reward
            best_training_score = generation_score

        training_curve.append(
            {
                "generation": generation,
                "mean_return": float(
                    math.fsum(item[0] for item in scored) / len(scored)
                ),
                "best_return": generation_score,
                "validation_return": validation_reward,
                "candidate_success_rate": success_count
                / (population * episodes_per_candidate),
                "search_std_mean": math.fsum(std) / len(std),
            }
        )
        current_best = simulate_policy(
            validated_hazards, best_weights, max_steps=max_steps
        )
        policy_evolution.append(
            _evolution_point(
                generation,
                best_weights,
                current_best,
            )
        )

    trained_eval = simulate_policy(
        validated_hazards, best_weights, max_steps=max_steps
    )
    trained_hash = weights_sha256(best_weights)
    delta_l2 = math.sqrt(
        math.fsum((after - before) ** 2 for before, after in zip(initial_weights, best_weights))
    )
    changed_elements = sum(
        not math.isclose(before, after, rel_tol=0.0, abs_tol=1.0e-12)
        for before, after in zip(initial_weights, best_weights)
    )
    if changed_elements == 0 or trained_hash == initial_hash:
        raise RuntimeError(
            "policy search completed without a changed validated checkpoint"
        )

    completed = datetime.now(UTC)
    return {
        "record_type": RESULT_FORMAT,
        "record_version": RESULT_VERSION,
        "model_version": MODEL_VERSION,
        "algorithm": "cross-entropy episodic policy search",
        "policy_class": "linear discrete-thrust controller",
        "sandbox_id": sandbox_id,
        "invocation_id": invocation_id,
        "runtime_bundle_sha256": runtime_bundle_sha256,
        "training_seed": seed,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": completed.isoformat().replace("+00:00", "Z"),
        "duration_seconds": (completed - started).total_seconds(),
        "scenario_sha256": scenario_fingerprint(validated_hazards, max_steps),
        "hazards": hazards_to_payload(validated_hazards),
        "observation_dimension": OBSERVATION_DIM,
        "action_names": list(ACTION_NAMES),
        "safety_radius_km": SAFETY_RADIUS_KM,
        "orbit_altitude_km": ORBIT_ALTITUDE_KM,
        "dt_seconds": DT_SECONDS,
        "max_steps": max_steps,
        "generations": generations,
        "population": population,
        "episodes_per_candidate": episodes_per_candidate,
        "training_episodes": generations * population * episodes_per_candidate,
        "initial_checkpoint_sha256": initial_hash,
        "trained_checkpoint_sha256": trained_hash,
        "weights_changed": True,
        "changed_parameter_elements": changed_elements,
        "parameter_l2_delta": delta_l2,
        "policy_version_before": 0,
        "policy_version_after": 1,
        "trained_weights": best_weights,
        "training_curve": training_curve,
        "policy_evolution": policy_evolution,
        "baseline_evaluation": baseline_eval,
        "trained_evaluation": trained_eval,
        "integrity": {
            "result_is_synthetic": True,
            "operational_use": False,
            "human_authority_required": True,
            "worker_runtime": "Python standard library only",
        },
        "reference_frame": {
            "simulation_frame": "planar Hill/LVLH local encounter frame",
            "position_units": "km",
            "velocity_units": "km/s",
            "reference_orbit": "illustrative circular orbit",
            "reference_orbit_radius_km": ORBIT_RADIUS_KM,
            "reference_orbit_altitude_km": ORBIT_ALTITUDE_KM,
            "display_transform": "declared circular reference-orbit embedding",
        },
    }


def _observation(
    x_km: float,
    y_km: float,
    vx_km_s: float,
    vy_km_s: float,
    time_s: float,
    hazards: Sequence[Hazard],
    step_index: int,
    max_steps: int,
) -> list[float]:
    nearest = _nearest_risk(
        x_km,
        y_km,
        vx_km_s,
        vy_km_s,
        time_s,
        hazards,
        horizon_s=max_steps * DT_SECONDS,
    )
    if nearest is None:
        dx = dy = dvx = dvy = 0.0
        tca_s = max_steps * DT_SECONDS
        miss_km = 10.0
    else:
        dx, dy, dvx, dvy, tca_s, miss_km = nearest
    return [
        _clip(x_km / 5.0, -4.0, 4.0),
        _clip(y_km / 5.0, -4.0, 4.0),
        _clip(vx_km_s / 0.012, -4.0, 4.0),
        _clip(vy_km_s / 0.012, -4.0, 4.0),
        _clip(dx / 8.0, -4.0, 4.0),
        _clip(dy / 8.0, -4.0, 4.0),
        _clip(dvx / 0.018, -4.0, 4.0),
        _clip(dvy / 0.018, -4.0, 4.0),
        _clip(tca_s / (max_steps * DT_SECONDS), 0.0, 1.0),
        _clip(miss_km / 4.0, 0.0, 4.0),
        len(hazards) / MAX_OBJECTS,
        step_index / max_steps,
    ]


def _nearest_risk(
    x_km: float,
    y_km: float,
    vx_km_s: float,
    vy_km_s: float,
    time_s: float,
    hazards: Sequence[Hazard],
    *,
    horizon_s: float,
) -> tuple[float, float, float, float, float, float] | None:
    best: tuple[float, tuple[float, float, float, float, float, float]] | None = None
    for hazard in hazards:
        hx, hy = hazard.position(time_s)
        dx = hx - x_km
        dy = hy - y_km
        dvx = hazard.vx_km_s - vx_km_s
        dvy = hazard.vy_km_s - vy_km_s
        velocity_sq = dvx * dvx + dvy * dvy
        tca_s = 0.0 if velocity_sq <= 1.0e-14 else max(0.0, -(dx * dvx + dy * dvy) / velocity_sq)
        tca_s = min(tca_s, max(0.0, horizon_s - time_s))
        miss_x = dx + dvx * tca_s
        miss_y = dy + dvy * tca_s
        miss_km = math.hypot(miss_x, miss_y)
        # Imminent small misses dominate; elapsed encounters naturally fall out.
        risk_score = miss_km + 0.0015 * tca_s
        values = (dx, dy, dvx, dvy, tca_s, miss_km)
        if best is None or risk_score < best[0]:
            best = (risk_score, values)
    return None if best is None else best[1]


def _select_action(weights: Sequence[float], observation: Sequence[float]) -> int:
    features = [*observation, 1.0]
    stride = len(features)
    logits = [
        math.fsum(
            weights[action * stride + index] * feature
            for index, feature in enumerate(features)
        )
        for action in range(len(ACTION_NAMES))
    ]
    return max(range(len(logits)), key=logits.__getitem__)


def _nearest_distance(
    x_km: float,
    y_km: float,
    time_s: float,
    hazards: Sequence[Hazard],
) -> tuple[float, str | None]:
    if not hazards:
        return 999.0, None
    values = [
        (math.hypot(hx - x_km, hy - y_km), hazard.object_id)
        for hazard in hazards
        for hx, hy in [hazard.position(time_s)]
    ]
    return min(values, key=lambda item: item[0])


def _trajectory_point(
    time_s: float,
    x_km: float,
    y_km: float,
    vx_km_s: float,
    vy_km_s: float,
    hazards: Sequence[Hazard],
    *,
    action_index: int,
) -> dict[str, Any]:
    objects = []
    for hazard in hazards:
        hx, hy = hazard.position(time_s)
        objects.append(
            {
                "object_id": hazard.object_id,
                "label": hazard.label,
                "kind": hazard.kind,
                "colour": hazard.colour,
                "x_km": hx,
                "y_km": hy,
                "distance_km": math.hypot(hx - x_km, hy - y_km),
            }
        )
    return {
        "time_s": time_s,
        "satellite": {
            "x_km": x_km,
            "y_km": y_km,
            "vx_km_s": vx_km_s,
            "vy_km_s": vy_km_s,
        },
        "objects": objects,
        "action_index": action_index,
        "action": ACTION_NAMES[action_index],
    }


def _evolution_point(
    generation: int,
    weights: Sequence[float],
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep replay plus the checkpoint required to verify that generation."""

    checkpoint = encode_weights(weights)

    return {
        "generation": generation,
        "checkpoint_sha256": weights_sha256(checkpoint),
        "weights": checkpoint,
        "success": bool(evaluation["success"]),
        "termination": str(evaluation["termination"]),
        "reward": float(evaluation["reward"]),
        "min_clearance_km": float(evaluation["min_clearance_km"]),
        "fuel_impulse_m_s": float(evaluation["fuel_impulse_m_s"]),
        "steps": int(evaluation["steps"]),
        "actions": list(evaluation["actions"]),
        "action_names": list(evaluation["action_names"]),
        "trajectory": list(evaluation["trajectory"]),
    }


def _jitter_hazards(hazards: Sequence[Hazard], seed: int) -> list[Hazard]:
    rng = random.Random(seed)
    output: list[Hazard] = []
    for hazard in hazards:
        output.append(
            Hazard(
                object_id=hazard.object_id,
                kind=hazard.kind,
                label=hazard.label,
                x0_km=hazard.x0_km + rng.uniform(-0.12, 0.12),
                y0_km=hazard.y0_km + rng.uniform(-0.12, 0.12),
                vx_km_s=hazard.vx_km_s * rng.uniform(0.94, 1.06),
                vy_km_s=hazard.vy_km_s * rng.uniform(0.94, 1.06),
                colour=hazard.colour,
            )
        )
    return output


def _validate_hazards(hazards: Sequence[Hazard]) -> list[Hazard]:
    if isinstance(hazards, (str, bytes)) or not isinstance(hazards, Sequence):
        raise ValueError("hazards must be a sequence")
    values = list(hazards)
    if len(values) > MAX_OBJECTS:
        raise ValueError(f"at most {MAX_OBJECTS} injected objects are supported")
    if not all(isinstance(item, Hazard) for item in values):
        raise ValueError("every hazard must be a Hazard")
    object_ids = [item.object_id for item in values]
    if len(object_ids) != len(set(object_ids)):
        raise ValueError("hazard object_id values must be unique")
    for hazard in values:
        for field_name in ("x0_km", "y0_km", "vx_km_s", "vy_km_s"):
            _finite(getattr(hazard, field_name), field_name)
    return values


def _validate_template_sequence(hazards: Sequence[Hazard]) -> None:
    for index, hazard in enumerate(hazards):
        if hazard.kind not in {"head_on", "crossing", "fast_debris"}:
            raise ValueError(f"hazard {index} kind is not allowlisted")
        if hazard != make_hazard(hazard.kind, index):
            raise ValueError(
                f"hazard {index} does not match its deterministic injection template"
            )


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _positive_integer(value: Any, name: str) -> int:
    result = _integer(value, name)
    if result < 1:
        raise ValueError(f"{name} must be at least 1")
    return result


def _bounded_integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    result = _integer(value, name)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256_text(value: Any, name: str) -> str:
    text = _non_empty_string(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)
