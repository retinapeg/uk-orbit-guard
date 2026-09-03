"""Real-only Daytona execution boundary for UK Orbit Guard RL training.

One call creates a private ephemeral sandbox, uploads a manifest-bound
standard-library worker, executes policy search remotely, validates the
returned evidence against the SDK sandbox identity, and waits for deletion.
This module never substitutes local training.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import ssl
from typing import Any
from uuid import uuid4

from .rl_core import (
    ACTION_NAMES,
    DEFAULT_STEPS,
    DT_SECONDS,
    MODEL_VERSION,
    OBSERVATION_DIM,
    ORBIT_ALTITUDE_KM,
    ORBIT_RADIUS_KM,
    POLICY_PARAMETER_COUNT,
    RESULT_FORMAT,
    RESULT_VERSION,
    SAFETY_RADIUS_KM,
    Hazard,
    hazards_from_payload,
    hazards_to_payload,
    scenario_fingerprint,
    simulate_policy,
    weights_sha256,
    zero_policy,
)

try:
    from daytona import Daytona, CreateSandboxFromSnapshotParams
except ImportError:  # pragma: no cover - readiness path covers missing SDK.
    Daytona = None  # type: ignore[assignment]
    CreateSandboxFromSnapshotParams = None  # type: ignore[assignment]


REMOTE_BASE = "uk-orbit-guard-rl"
WORKER_COMMAND = (
    "python3 daytona_rl_worker.py --job daytona_job.json "
    "--output daytona_result.json"
)
CREATE_TIMEOUT_SECONDS = 120
TRAINING_TIMEOUT_SECONDS = 300
DELETE_TIMEOUT_SECONDS = 120
SANDBOX_TTL_MINUTES = 12
DAYTONA_SDK_VERSION = "0.207.0"
MAX_RESULT_BYTES = 10_000_000
EventCallback = Callable[[Mapping[str, Any]], Any]

RESULT_FIELDS = frozenset(
    {
        "record_type", "record_version", "model_version", "algorithm",
        "policy_class", "sandbox_id", "invocation_id",
        "runtime_bundle_sha256", "training_seed", "started_at_utc",
        "completed_at_utc", "duration_seconds", "scenario_sha256", "hazards",
        "observation_dimension", "action_names", "safety_radius_km",
        "orbit_altitude_km", "dt_seconds", "max_steps", "generations",
        "population", "episodes_per_candidate", "training_episodes",
        "initial_checkpoint_sha256", "trained_checkpoint_sha256",
        "weights_changed", "changed_parameter_elements", "parameter_l2_delta",
        "policy_version_before", "policy_version_after", "trained_weights",
        "training_curve", "policy_evolution", "baseline_evaluation",
        "trained_evaluation", "integrity", "reference_frame",
    }
)


class DaytonaRLConfigurationError(RuntimeError):
    """The project SDK or required credential is unavailable."""


class DaytonaRLExecutionError(RuntimeError):
    """A real sandbox call failed or returned incoherent evidence."""


def runtime_status() -> dict[str, Any]:
    """Return presence-only diagnostics; never expose credential content."""

    try:
        sdk_version = importlib.metadata.version("daytona")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = None
    sdk_installed = bool(
        sdk_version and Daytona is not None and CreateSandboxFromSnapshotParams is not None
    )
    version_compatible = sdk_version == DAYTONA_SDK_VERSION
    credential_present = bool(os.environ.get("DAYTONA_API_KEY", "").strip())
    return {
        "sdk_installed": sdk_installed,
        "sdk_version": sdk_version,
        "version_compatible": version_compatible,
        "credential_present": credential_present,
        "api_url_overridden": bool(os.environ.get("DAYTONA_API_URL", "").strip()),
        "ready": bool(sdk_installed and version_compatible and credential_present),
    }


def run_daytona_training(
    hazards: Sequence[Hazard],
    *,
    seed: int = 42,
    generations: int = 10,
    population: int = 24,
    episodes_per_candidate: int = 3,
    max_steps: int = DEFAULT_STEPS,
    event_callback: EventCallback | None = None,
    invocation_id: str | None = None,
) -> dict[str, Any]:
    """Train once in a real Daytona sandbox and return host-validated evidence."""

    _require_daytona()
    hazard_payload = hazards_to_payload(hazards)
    if not hazard_payload:
        raise ValueError("at least one injected object is required")
    invocation_id = str(uuid4()) if invocation_id is None else _invocation_id(invocation_id)
    scenario_hash = scenario_fingerprint(hazards, max_steps)
    runtime_files, bundle_hash = _capture_runtime_bundle()
    remote_dir = f"{REMOTE_BASE}/{invocation_id}"
    sandbox: Any | None = None
    sandbox_id: str | None = None
    result: dict[str, Any] | None = None
    failure: Exception | None = None
    cleanup_failure: Exception | None = None

    _emit(
        event_callback,
        state="CREATING",
        message="Requesting a private Daytona sandbox",
        sandbox_id=None,
        invocation_id=invocation_id,
    )
    daytona = Daytona()  # type: ignore[misc,operator]
    try:
        params = CreateSandboxFromSnapshotParams(  # type: ignore[misc,operator]
            name=_sandbox_name(invocation_id),
            language="python",
            labels={
                "app": "uk-orbit-guard",
                "purpose": "live-rl-training",
                "run_id": invocation_id,
                "model": MODEL_VERSION,
            },
            public=False,
            ephemeral=True,
            auto_stop_interval=0,
            ttl_minutes=SANDBOX_TTL_MINUTES,
            network_block_all=True,
        )
        sandbox = daytona.create(params, timeout=CREATE_TIMEOUT_SECONDS)
        sandbox_id = _real_sandbox_id(sandbox)
        _emit(
            event_callback,
            state="LIVE",
            message="Daytona sandbox live; uploading frozen worker bundle",
            sandbox_id=sandbox_id,
            invocation_id=invocation_id,
        )
        _upload_runtime(sandbox, remote_dir, runtime_files)
        job = {
            "schema_version": RESULT_VERSION,
            "invocation_id": invocation_id,
            "sandbox_id": sandbox_id,
            "runtime_bundle_sha256": bundle_hash,
            "model_version": MODEL_VERSION,
            "scenario_sha256": scenario_hash,
            "hazards": hazard_payload,
            "seed": seed,
            "generations": generations,
            "population": population,
            "episodes_per_candidate": episodes_per_candidate,
            "max_steps": max_steps,
            "synthetic": True,
            "operational_use": False,
            "human_authority_required": True,
        }
        _upload_json(sandbox, f"{remote_dir}/daytona_job.json", job)
        _emit(
            event_callback,
            state="TRAINING",
            message=(
                f"Generation 0 → {generations} · "
                f"{generations * population * episodes_per_candidate:,} remote episodes"
            ),
            sandbox_id=sandbox_id,
            invocation_id=invocation_id,
        )
        execution = sandbox.process.exec(
            WORKER_COMMAND,
            cwd=remote_dir,
            env={"PYTHONUNBUFFERED": "1"},
            timeout=TRAINING_TIMEOUT_SECONDS,
        )
        if getattr(execution, "exit_code", None) != 0:
            tail = str(getattr(execution, "result", "") or "").strip()[-1_200:]
            raise DaytonaRLExecutionError(
                f"sandbox worker exited with code {getattr(execution, 'exit_code', None)}: {tail}"
            )
        _emit(
            event_callback,
            state="VALIDATING",
            message="Downloading checkpoint and every generation replay",
            sandbox_id=sandbox_id,
            invocation_id=invocation_id,
        )
        result_path = f"{remote_dir}/daytona_result.json"
        result_info = sandbox.fs.get_file_info(result_path, request_timeout=30)
        result_size = getattr(result_info, "size", None)
        if (
            isinstance(result_size, bool)
            or not isinstance(result_size, int)
            or result_size < 1
            or result_size > MAX_RESULT_BYTES
        ):
            raise DaytonaRLExecutionError(
                "sandbox result size is missing or exceeds the 10 MB bound"
            )
        payload = sandbox.fs.download_file(result_path, 60)
        if not isinstance(payload, (bytes, bytearray)):
            raise DaytonaRLExecutionError("sandbox result download was not bytes")
        if len(payload) != result_size or len(payload) > MAX_RESULT_BYTES:
            raise DaytonaRLExecutionError(
                "sandbox result download size changed or exceeds the bound"
            )
        try:
            parsed = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DaytonaRLExecutionError("sandbox result was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise DaytonaRLExecutionError("sandbox result must be an object")
        validate_training_result(
            parsed,
            expected_sandbox_id=sandbox_id,
            expected_invocation_id=invocation_id,
            expected_runtime_bundle_sha256=bundle_hash,
            expected_seed=seed,
            expected_scenario_sha256=scenario_hash,
            expected_hazards=hazard_payload,
            expected_generations=generations,
            expected_population=population,
            expected_episodes_per_candidate=episodes_per_candidate,
            expected_max_steps=max_steps,
        )
        result = parsed
        _emit(
            event_callback,
            state="RESULT_COLLECTED",
            message="Validated checkpoint and generation replays collected",
            sandbox_id=sandbox_id,
            invocation_id=invocation_id,
        )
    except Exception as exc:
        failure = exc
        _emit_safely(
            event_callback,
            state="FAILED",
            message=f"{type(exc).__name__}: {exc}",
            sandbox_id=sandbox_id,
            invocation_id=invocation_id,
        )
    finally:
        if sandbox is not None:
            try:
                sandbox.delete(timeout=DELETE_TIMEOUT_SECONDS, wait=True)
                _emit_safely(
                    event_callback,
                    state="CLEANED",
                    message="Daytona sandbox deletion confirmed",
                    sandbox_id=sandbox_id,
                    invocation_id=invocation_id,
                )
            except Exception as exc:
                cleanup_failure = exc

    if failure is not None:
        message = f"{type(failure).__name__}: {failure}"
        if cleanup_failure is not None:
            message += (
                "; sandbox cleanup also failed: "
                f"{type(cleanup_failure).__name__}: {cleanup_failure}"
            )
        if isinstance(failure, DaytonaRLConfigurationError):
            raise failure
        raise DaytonaRLExecutionError(message) from failure
    if cleanup_failure is not None:
        raise DaytonaRLExecutionError(
            "training evidence was collected but sandbox deletion was not confirmed: "
            f"{type(cleanup_failure).__name__}: {cleanup_failure}"
        ) from cleanup_failure
    if result is None or sandbox_id is None:
        raise DaytonaRLExecutionError("Daytona training produced no validated result")
    return {
        **result,
        "daytona_execution": {
            "sandbox_id": sandbox_id,
            "invocation_id": invocation_id,
            "runtime_bundle_sha256": bundle_hash,
            "result_validated": True,
            "sandbox_deleted": True,
            "local_training_fallback_used": False,
        },
    }


def validate_training_result(
    result: Mapping[str, Any],
    *,
    expected_sandbox_id: str,
    expected_invocation_id: str,
    expected_runtime_bundle_sha256: str,
    expected_seed: int,
    expected_scenario_sha256: str,
    expected_hazards: Sequence[Mapping[str, Any]],
    expected_generations: int,
    expected_population: int,
    expected_episodes_per_candidate: int,
    expected_max_steps: int,
) -> None:
    """Fail closed unless downloaded evidence matches the frozen job."""

    if not isinstance(result, Mapping) or frozenset(result) != RESULT_FIELDS:
        raise DaytonaRLExecutionError("training result schema does not match")
    _validated_identity(expected_sandbox_id, "expected sandbox_id")
    try:
        _invocation_id(expected_invocation_id)
    except ValueError as exc:
        raise DaytonaRLExecutionError(
            "expected invocation_id is invalid"
        ) from exc
    _sha256_digest(
        expected_runtime_bundle_sha256,
        "expected runtime_bundle_sha256",
    )
    _sha256_digest(expected_scenario_sha256, "expected scenario_sha256")
    integer_fields = (
        "record_version",
        "training_seed",
        "observation_dimension",
        "max_steps",
        "generations",
        "population",
        "episodes_per_candidate",
        "training_episodes",
        "policy_version_before",
        "policy_version_after",
    )
    for field in integer_fields:
        _exact_integer(result.get(field), f"training result {field}")
    checks = {
        "record_type": RESULT_FORMAT,
        "record_version": RESULT_VERSION,
        "model_version": MODEL_VERSION,
        "algorithm": "cross-entropy episodic policy search",
        "policy_class": "linear discrete-thrust controller",
        "sandbox_id": expected_sandbox_id,
        "invocation_id": expected_invocation_id,
        "runtime_bundle_sha256": expected_runtime_bundle_sha256,
        "training_seed": expected_seed,
        "scenario_sha256": expected_scenario_sha256,
        "observation_dimension": OBSERVATION_DIM,
        "action_names": list(ACTION_NAMES),
        "safety_radius_km": SAFETY_RADIUS_KM,
        "orbit_altitude_km": ORBIT_ALTITUDE_KM,
        "dt_seconds": DT_SECONDS,
        "max_steps": expected_max_steps,
        "generations": expected_generations,
        "population": expected_population,
        "episodes_per_candidate": expected_episodes_per_candidate,
        "training_episodes": expected_generations * expected_population * expected_episodes_per_candidate,
        "policy_version_before": 0,
        "policy_version_after": 1,
    }
    for field, expected in checks.items():
        if result[field] != expected:
            raise DaytonaRLExecutionError(f"training result {field} does not match job")
    if result["hazards"] != list(expected_hazards):
        raise DaytonaRLExecutionError("training result hazards do not match job")
    hazards = hazards_from_payload(result["hazards"])
    if scenario_fingerprint(hazards, expected_max_steps) != expected_scenario_sha256:
        raise DaytonaRLExecutionError(
            "training scenario digest does not match its hazards and horizon"
        )
    integrity = result["integrity"]
    if (
        not isinstance(integrity, Mapping)
        or set(integrity)
        != {
            "result_is_synthetic",
            "operational_use",
            "human_authority_required",
            "worker_runtime",
        }
        or integrity.get("result_is_synthetic") is not True
        or integrity.get("operational_use") is not False
        or integrity.get("human_authority_required") is not True
        or integrity.get("worker_runtime") != "Python standard library only"
    ):
        raise DaytonaRLExecutionError("training integrity boundary was altered")
    if result["reference_frame"] != {
        "simulation_frame": "planar Hill/LVLH local encounter frame",
        "position_units": "km",
        "velocity_units": "km/s",
        "reference_orbit": "illustrative circular orbit",
        "reference_orbit_radius_km": ORBIT_RADIUS_KM,
        "reference_orbit_altitude_km": ORBIT_ALTITUDE_KM,
        "display_transform": "declared circular reference-orbit embedding",
    }:
        raise DaytonaRLExecutionError("training reference frame was altered")
    started = _timestamp(result["started_at_utc"], "started_at_utc")
    completed = _timestamp(result["completed_at_utc"], "completed_at_utc")
    duration = _finite(result["duration_seconds"], "duration_seconds")
    if completed < started or duration < 0:
        raise DaytonaRLExecutionError("training timing is invalid")
    if not math.isclose(
        duration,
        (completed - started).total_seconds(),
        rel_tol=0.0,
        abs_tol=1.0e-6,
    ):
        raise DaytonaRLExecutionError("training duration does not match timestamps")

    weights = result["trained_weights"]
    if not isinstance(weights, list) or len(weights) != POLICY_PARAMETER_COUNT:
        raise DaytonaRLExecutionError("trained_weights has the wrong shape")
    _finite_sequence(weights, "trained_weights")
    initial_hash = weights_sha256(zero_policy())
    if result["initial_checkpoint_sha256"] != initial_hash:
        raise DaytonaRLExecutionError("initial checkpoint digest is invalid")
    if result["trained_checkpoint_sha256"] != weights_sha256(weights):
        raise DaytonaRLExecutionError("trained checkpoint digest is invalid")
    if result["trained_checkpoint_sha256"] == initial_hash or result["weights_changed"] is not True:
        raise DaytonaRLExecutionError("policy parameters did not change")
    changed = _positive_integer(
        result["changed_parameter_elements"],
        "changed_parameter_elements",
    )
    computed_changed = sum(
        not math.isclose(float(item), 0.0, rel_tol=0.0, abs_tol=1.0e-12)
        for item in weights
    )
    computed_l2 = math.sqrt(math.fsum(float(item) ** 2 for item in weights))
    if changed != computed_changed or changed > POLICY_PARAMETER_COUNT:
        raise DaytonaRLExecutionError("changed policy element count is invalid")
    if (
        not math.isclose(
            _finite(result["parameter_l2_delta"], "parameter_l2_delta"),
            computed_l2,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        )
        or computed_l2 <= 0
    ):
        raise DaytonaRLExecutionError("policy delta is invalid")

    curve = result["training_curve"]
    if not isinstance(curve, list) or len(curve) != expected_generations:
        raise DaytonaRLExecutionError("training curve length does not match generations")
    curve_fields = {
        "generation",
        "mean_return",
        "best_return",
        "validation_return",
        "candidate_success_rate",
        "search_std_mean",
    }
    for generation, point in enumerate(curve, start=1):
        if (
            not isinstance(point, Mapping)
            or set(point) != curve_fields
            or isinstance(point.get("generation"), bool)
            or not isinstance(point.get("generation"), int)
            or point.get("generation") != generation
        ):
            raise DaytonaRLExecutionError("training curve order is invalid")
        for field in ("mean_return", "best_return", "validation_return", "candidate_success_rate", "search_std_mean"):
            _finite(point.get(field), f"training_curve.{field}")
        success_rate = _finite(
            point["candidate_success_rate"],
            "training_curve.candidate_success_rate",
        )
        if not 0.0 <= success_rate <= 1.0:
            raise DaytonaRLExecutionError("training success rate is invalid")
        if _finite(
            point["search_std_mean"],
            "training_curve.search_std_mean",
        ) <= 0:
            raise DaytonaRLExecutionError("training search spread is invalid")

    _validate_evaluation(result["baseline_evaluation"], "baseline_evaluation", hazards, expected_max_steps)
    _validate_evaluation(result["trained_evaluation"], "trained_evaluation", hazards, expected_max_steps)
    if not _semantically_equal(
        result["baseline_evaluation"],
        simulate_policy(
            hazards,
            zero_policy(),
            max_steps=expected_max_steps,
        ),
    ):
        raise DaytonaRLExecutionError("baseline evaluation does not replay from Gen 0")
    if not _semantically_equal(
        result["trained_evaluation"],
        simulate_policy(
            hazards,
            weights,
            max_steps=expected_max_steps,
        ),
    ):
        raise DaytonaRLExecutionError(
            "trained evaluation does not replay from checkpoint"
        )
    evolution = result["policy_evolution"]
    if not isinstance(evolution, list) or len(evolution) != expected_generations + 1:
        raise DaytonaRLExecutionError("policy evolution must include generation 0 and every generation")
    for generation, point in enumerate(evolution):
        if (
            not isinstance(point, Mapping)
            or isinstance(point.get("generation"), bool)
            or not isinstance(point.get("generation"), int)
            or point.get("generation") != generation
        ):
            raise DaytonaRLExecutionError("policy evolution order is invalid")
        _validate_evolution_point(point, hazards, expected_max_steps)
    if evolution[0]["checkpoint_sha256"] != initial_hash:
        raise DaytonaRLExecutionError("generation 0 checkpoint is not the zero policy")
    if evolution[0]["weights"] != zero_policy():
        raise DaytonaRLExecutionError(
            "generation 0 parameters are not the zero policy"
        )
    if evolution[-1]["checkpoint_sha256"] != result["trained_checkpoint_sha256"]:
        raise DaytonaRLExecutionError("final generation checkpoint mismatch")
    if evolution[-1]["weights"] != weights:
        raise DaytonaRLExecutionError(
            "final generation parameters differ from trained checkpoint"
        )
    if evolution[0]["trajectory"] != result["baseline_evaluation"]["trajectory"]:
        raise DaytonaRLExecutionError("generation 0 replay differs from baseline")
    if evolution[-1]["trajectory"] != result["trained_evaluation"]["trajectory"]:
        raise DaytonaRLExecutionError("final replay differs from trained evaluation")
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DaytonaRLExecutionError("training result is not JSON-safe") from exc


def _validate_evaluation(value: Any, name: str, hazards: Sequence[Hazard], max_steps: int) -> None:
    expected_fields = {
        "success", "termination", "steps", "reward", "min_clearance_km",
        "closest_object_id", "fuel_impulse_m_s", "actions", "action_names",
        "rewards", "observations", "trajectory",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise DaytonaRLExecutionError(f"{name} schema is invalid")
    steps = _validate_episode_summary(value, name, hazards, max_steps)
    rewards, observations = value["rewards"], value["observations"]
    if not isinstance(rewards, list) or len(rewards) != steps:
        raise DaytonaRLExecutionError(f"{name}.rewards length is invalid")
    _finite_sequence(rewards, f"{name}.rewards")
    if not math.isclose(_finite(value["reward"], f"{name}.reward"), math.fsum(rewards), rel_tol=1e-12, abs_tol=1e-8):
        raise DaytonaRLExecutionError(f"{name}.reward does not equal reward sum")
    if not isinstance(observations, list) or len(observations) != steps:
        raise DaytonaRLExecutionError(f"{name}.observations length is invalid")
    for observation in observations:
        if not isinstance(observation, list) or len(observation) != OBSERVATION_DIM:
            raise DaytonaRLExecutionError(f"{name} observation shape is invalid")
        _finite_sequence(observation, f"{name}.observation")


def _validate_evolution_point(value: Mapping[str, Any], hazards: Sequence[Hazard], max_steps: int) -> None:
    expected_fields = {
        "generation", "checkpoint_sha256", "weights", "success", "termination", "reward",
        "min_clearance_km", "fuel_impulse_m_s", "steps", "actions",
        "action_names", "trajectory",
    }
    if set(value) != expected_fields:
        raise DaytonaRLExecutionError("policy evolution point schema is invalid")
    checkpoint = value["weights"]
    if not isinstance(checkpoint, list) or len(checkpoint) != POLICY_PARAMETER_COUNT:
        raise DaytonaRLExecutionError(
            "policy evolution checkpoint has the wrong shape"
        )
    _finite_sequence(checkpoint, "policy_evolution.weights")
    digest = value["checkpoint_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise DaytonaRLExecutionError("policy evolution checkpoint digest is invalid")
    if digest != weights_sha256(checkpoint):
        raise DaytonaRLExecutionError(
            "policy evolution checkpoint digest does not match"
        )
    _finite(value["reward"], "policy_evolution.reward")
    _validate_episode_summary(value, "policy_evolution", hazards, max_steps)
    expected = simulate_policy(hazards, checkpoint, max_steps=max_steps)
    for field in (
        "success",
        "termination",
        "reward",
        "min_clearance_km",
        "fuel_impulse_m_s",
        "steps",
        "actions",
        "action_names",
        "trajectory",
    ):
        if not _semantically_equal(value[field], expected[field]):
            raise DaytonaRLExecutionError(
                f"policy evolution {field} does not replay from its checkpoint"
            )


def _validate_episode_summary(value: Mapping[str, Any], name: str, hazards: Sequence[Hazard], max_steps: int) -> int:
    if not isinstance(value.get("success"), bool):
        raise DaytonaRLExecutionError(f"{name}.success must be boolean")
    termination = value.get("termination")
    if termination not in {"horizon_clear", "keep_out_breach"} or value["success"] != (termination == "horizon_clear"):
        raise DaytonaRLExecutionError(f"{name} termination is invalid")
    steps = _positive_integer(value.get("steps"), f"{name}.steps")
    if steps > max_steps or (value["success"] and steps != max_steps):
        raise DaytonaRLExecutionError(f"{name}.steps is inconsistent")
    actions, action_names = value.get("actions"), value.get("action_names")
    if not isinstance(actions, list) or not isinstance(action_names, list) or len(actions) != steps or len(action_names) != steps:
        raise DaytonaRLExecutionError(f"{name} actions are invalid")
    for index, action in enumerate(actions):
        if isinstance(action, bool) or not isinstance(action, int) or not 0 <= action < len(ACTION_NAMES):
            raise DaytonaRLExecutionError(f"{name} action is outside policy space")
        if action_names[index] != ACTION_NAMES[action]:
            raise DaytonaRLExecutionError(f"{name} action name/index disagree")
    trajectory = value.get("trajectory")
    if not isinstance(trajectory, list) or len(trajectory) != steps + 1:
        raise DaytonaRLExecutionError(f"{name}.trajectory length is invalid")
    computed_min = _validate_trajectory(trajectory, actions, hazards, name)
    reported_min = _finite(value.get("min_clearance_km"), f"{name}.min_clearance_km")
    if not math.isclose(reported_min, computed_min, rel_tol=1e-10, abs_tol=1e-9):
        raise DaytonaRLExecutionError(f"{name}.min_clearance_km is inconsistent")
    _finite(value.get("fuel_impulse_m_s"), f"{name}.fuel_impulse_m_s")
    if value["success"] != (reported_min > SAFETY_RADIUS_KM):
        raise DaytonaRLExecutionError(f"{name} clearance/termination disagree")
    return steps


def _validate_trajectory(trajectory: Sequence[Any], actions: Sequence[int], hazards: Sequence[Hazard], name: str) -> float:
    minimum = float("inf")
    for index, point in enumerate(trajectory):
        if not isinstance(point, Mapping):
            raise DaytonaRLExecutionError(f"{name} trajectory point is invalid")
        time_s = _finite(point.get("time_s"), f"{name}.trajectory.time_s")
        if not math.isclose(time_s, index * DT_SECONDS, abs_tol=1e-9):
            raise DaytonaRLExecutionError(f"{name} trajectory time is not monotonic")
        satellite = point.get("satellite")
        if not isinstance(satellite, Mapping) or set(satellite) != {"x_km", "y_km", "vx_km_s", "vy_km_s"}:
            raise DaytonaRLExecutionError(f"{name} satellite state is invalid")
        sx = _finite(satellite["x_km"], f"{name}.satellite.x_km")
        sy = _finite(satellite["y_km"], f"{name}.satellite.y_km")
        _finite(satellite["vx_km_s"], f"{name}.satellite.vx_km_s")
        _finite(satellite["vy_km_s"], f"{name}.satellite.vy_km_s")
        objects = point.get("objects")
        if not isinstance(objects, list) or len(objects) != len(hazards):
            raise DaytonaRLExecutionError(f"{name} object state count is invalid")
        for returned, hazard in zip(objects, hazards):
            if not isinstance(returned, Mapping) or returned.get("object_id") != hazard.object_id or returned.get("kind") != hazard.kind:
                raise DaytonaRLExecutionError(f"{name} object identity changed")
            hx = _finite(returned.get("x_km"), f"{name}.object.x_km")
            hy = _finite(returned.get("y_km"), f"{name}.object.y_km")
            expected_x, expected_y = hazard.position(time_s)
            if not math.isclose(hx, expected_x, abs_tol=1e-9) or not math.isclose(hy, expected_y, abs_tol=1e-9):
                raise DaytonaRLExecutionError(f"{name} object trajectory changed")
            distance = _finite(returned.get("distance_km"), f"{name}.object.distance_km")
            computed = math.hypot(hx - sx, hy - sy)
            if not math.isclose(distance, computed, rel_tol=1e-10, abs_tol=1e-9):
                raise DaytonaRLExecutionError(f"{name} object distance is inconsistent")
            if index > 0:
                minimum = min(minimum, distance)
        expected_action = 0 if index == 0 else actions[index - 1]
        action_index = point.get("action_index")
        if (
            isinstance(action_index, bool)
            or not isinstance(action_index, int)
            or action_index != expected_action
            or point.get("action") != ACTION_NAMES[expected_action]
        ):
            raise DaytonaRLExecutionError(f"{name} trajectory action is inconsistent")
    return minimum


def _capture_runtime_bundle() -> tuple[dict[str, bytes], str]:
    root = Path(__file__).resolve().parents[2]
    paths = {
        "rl_core.py": root / "src" / "orbit_guard" / "rl_core.py",
        "daytona_rl_worker.py": root / "scripts" / "daytona_rl_worker.py",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise DaytonaRLExecutionError("worker bundle is missing: " + ", ".join(missing))
    files = {name: path.read_bytes() for name, path in paths.items()}
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode("utf-8")); digest.update(b"\0")
        digest.update(content); digest.update(b"\0")
    return files, digest.hexdigest()


def _upload_runtime(sandbox: Any, remote_dir: str, files: Mapping[str, bytes]) -> None:
    sandbox.fs.create_folder(REMOTE_BASE, "755", request_timeout=60)
    sandbox.fs.create_folder(remote_dir, "755", request_timeout=60)
    for name, content in files.items():
        sandbox.fs.upload_file(content, f"{remote_dir}/{name}", timeout=60)


def _upload_json(sandbox: Any, path: str, value: Mapping[str, Any]) -> None:
    try:
        payload = json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DaytonaRLExecutionError("Daytona job was not JSON-safe") from exc
    sandbox.fs.upload_file(payload, path, timeout=60)


def _require_daytona() -> None:
    status = runtime_status()
    if not status["sdk_installed"]:
        raise DaytonaRLConfigurationError("Daytona SDK unavailable; install project live extra")
    if not status["version_compatible"]:
        raise DaytonaRLConfigurationError(
            f"Daytona SDK {DAYTONA_SDK_VERSION} required; launch the pinned demo environment"
        )
    if not status["credential_present"]:
        raise DaytonaRLConfigurationError("DAYTONA_API_KEY required; local training fallback disabled")
    _configure_tls_ca_bundle()


def _configure_tls_ca_bundle() -> str | None:
    verify_paths = ssl.get_default_verify_paths()
    if verify_paths.cafile is not None or verify_paths.capath is not None:
        return None
    if verify_paths.openssl_cafile_env in os.environ or verify_paths.openssl_capath_env in os.environ:
        return None
    try:
        import certifi
    except ImportError as exc:  # pragma: no cover
        raise DaytonaRLConfigurationError("Python has no CA bundle and certifi is unavailable") from exc
    bundle = Path(certifi.where())
    if not bundle.is_file():
        raise DaytonaRLConfigurationError("certifi did not provide a CA bundle")
    os.environ.setdefault(verify_paths.openssl_cafile_env, str(bundle))
    return os.environ[verify_paths.openssl_cafile_env]


def _real_sandbox_id(sandbox: Any) -> str:
    sandbox_id = getattr(sandbox, "id", None)
    return _validated_identity(sandbox_id, "Daytona sandbox_id")


def _emit(callback: EventCallback | None, **event: Any) -> None:
    if callback is None:
        return
    returned = callback(event)
    if inspect.isawaitable(returned):
        raise DaytonaRLExecutionError("Daytona event callback must be synchronous")


def _emit_safely(callback: EventCallback | None, **event: Any) -> None:
    try:
        _emit(callback, **event)
    except Exception:
        pass


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DaytonaRLExecutionError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise DaytonaRLExecutionError(f"{name} must be finite")
    return number


def _finite_sequence(value: Any, name: str) -> list[float]:
    if not isinstance(value, list):
        raise DaytonaRLExecutionError(f"{name} must be a list")
    return [_finite(item, name) for item in value]


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DaytonaRLExecutionError(f"{name} must be a positive integer")
    return value


def _exact_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DaytonaRLExecutionError(f"{name} must be an integer")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DaytonaRLExecutionError(f"{name} must be a canonical UTC timestamp ending in Z")
    candidate = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise DaytonaRLExecutionError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DaytonaRLExecutionError(f"{name} must use UTC")
    return parsed


def _validated_identity(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise DaytonaRLExecutionError(f"{name} must be a non-empty printable identifier")
    return value


def _sha256_digest(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DaytonaRLExecutionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _semantically_equal(actual: Any, expected: Any) -> bool:
    """Compare replay structures exactly except for tiny cross-libm float drift."""

    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is bool and type(expected) is bool and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(
            float(actual),
            float(expected),
            rel_tol=1.0e-11,
            abs_tol=1.0e-9,
        )
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        return set(actual) == set(expected) and all(
            _semantically_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _semantically_equal(left, right)
            for left, right in zip(actual, expected)
        )
    return type(actual) is type(expected) and actual == expected


def _invocation_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError("invocation_id must be non-empty text up to 80 characters")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in value):
        raise ValueError("invocation_id contains unsupported characters")
    return value


def _sandbox_name(invocation_id: str) -> str:
    suffix = invocation_id.removeprefix("orbitguard-")[:12]
    if not suffix:
        suffix = hashlib.sha256(invocation_id.encode("utf-8")).hexdigest()[:12]
    return f"uk-orbit-guard-{suffix}"
