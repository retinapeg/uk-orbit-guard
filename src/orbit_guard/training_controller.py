"""Non-blocking host controller for the Streamlit Daytona training button."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .daytona_rl import (
    DaytonaRLExecutionError,
    runtime_status,
    validate_training_result,
)
from .rl_core import (
    DEFAULT_STEPS,
    MODEL_VERSION,
    RESULT_VERSION,
    Hazard,
    hazards_from_payload,
    hazards_to_payload,
    scenario_fingerprint,
)


UTC = timezone.utc
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = REPOSITORY_ROOT / ".cache" / "daytona_rl"
ACTIVE_LOCK = RUN_ROOT / "active.json"
LAST_VERIFIED = RUN_ROOT / "last_verified.json"
CONTROLLER_SCRIPT = REPOSITORY_ROOT / "scripts" / "run_daytona_rl_controller.py"
TERMINAL_STATES = frozenset({"COMPLETE", "FAILED"})
ACTIVE_STATES = frozenset({"QUEUED", "CREATING", "LIVE", "TRAINING", "VALIDATING", "RESULT_COLLECTED", "CLEANED"})
STARTUP_GRACE = timedelta(seconds=10)
STALE_LOCK_RECLAIM_AFTER = timedelta(minutes=20)


class TrainingControllerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunHandle:
    invocation_id: str
    run_dir: Path

    @property
    def request_path(self) -> Path:
        return self.run_dir / "request.json"

    @property
    def state_path(self) -> Path:
        return self.run_dir / "live_state.json"

    @property
    def result_path(self) -> Path:
        return self.run_dir / "result.json"

    @property
    def log_path(self) -> Path:
        return self.run_dir / "controller.log"

    @property
    def pid_path(self) -> Path:
        return self.run_dir / "controller_pid.json"


def start_training(
    hazards: Sequence[Hazard],
    *,
    seed: int = 42,
    generations: int = 10,
    population: int = 24,
    episodes_per_candidate: int = 3,
    max_steps: int = DEFAULT_STEPS,
) -> RunHandle:
    """Freeze one request and launch exactly one shell-free controller process."""

    status = runtime_status()
    if not status["ready"]:
        if not status["sdk_installed"]:
            reason = "Daytona SDK missing"
        elif not status.get("version_compatible"):
            reason = "pinned Daytona SDK version missing"
        else:
            reason = "DAYTONA_API_KEY missing"
        raise TrainingControllerError(f"{reason}; no training process was launched")
    if not CONTROLLER_SCRIPT.is_file():
        raise TrainingControllerError("Daytona controller script is missing")

    payload = hazards_to_payload(hazards)
    if not payload:
        raise TrainingControllerError("inject at least one object before training")
    invocation_id = f"orbitguard-{uuid4()}"
    run_dir = RUN_ROOT / invocation_id
    handle = RunHandle(invocation_id, run_dir)
    request = {
        "schema_version": RESULT_VERSION,
        "invocation_id": invocation_id,
        "model_version": MODEL_VERSION,
        "scenario_sha256": scenario_fingerprint(hazards, max_steps),
        "hazards": payload,
        "seed": seed,
        "generations": generations,
        "population": population,
        "episodes_per_candidate": episodes_per_candidate,
        "max_steps": max_steps,
        "synthetic": True,
        "operational_use": False,
        "human_authority_required": True,
    }

    process: subprocess.Popen[bytes] | None = None
    lock_acquired = False
    try:
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        _acquire_lock(invocation_id)
        lock_acquired = True
        run_dir.mkdir(mode=0o700)
        _atomic_json(handle.request_path, request)
        _atomic_json(
            handle.state_path,
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "revision": 0,
                "state": "QUEUED",
                "message": "Controller queued; no sandbox ID received yet",
                "sandbox_id": None,
                "updated_at_utc": _now(),
                "pid": None,
                "result_path": None,
                "error": None,
            },
        )
        log_handle = handle.log_path.open("ab", buffering=0)
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(CONTROLLER_SCRIPT),
                    "--request",
                    str(handle.request_path),
                    "--state",
                    str(handle.state_path),
                    "--result",
                    str(handle.result_path),
                ],
                cwd=REPOSITORY_ROOT,
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        # Keep PID evidence in a separate file so the parent cannot overwrite a
        # state revision that the fast child may already have advanced.
        _atomic_json(
            handle.pid_path,
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "pid": process.pid,
                "started_at_utc": _now(),
            },
        )
    except BaseException:
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except Exception:
            # The original launch failure is the actionable error. Process
            # cleanup remains best-effort, but the matching lock must never be
            # stranded by a second exception here.
            pass
        finally:
            if lock_acquired:
                _release_lock(invocation_id)
        raise
    return handle


def read_state(handle: RunHandle) -> dict[str, Any]:
    _validate_handle(handle)
    state = _read_json(handle.state_path)
    required = {
        "schema_version", "invocation_id", "revision", "state", "message",
        "sandbox_id", "updated_at_utc", "pid", "result_path", "error",
    }
    if not isinstance(state, dict) or set(state) != required:
        raise TrainingControllerError("live state schema is invalid")
    if state["schema_version"] != 1 or state["invocation_id"] != handle.invocation_id:
        raise TrainingControllerError("live state invocation does not match")
    if state["state"] not in ACTIVE_STATES | TERMINAL_STATES:
        raise TrainingControllerError("live state phase is invalid")
    if isinstance(state["revision"], bool) or not isinstance(state["revision"], int) or state["revision"] < 0:
        raise TrainingControllerError("live state revision is invalid")
    if not isinstance(state["message"], str) or not state["message"].strip():
        raise TrainingControllerError("live state message is invalid")
    if state["sandbox_id"] is not None and not isinstance(state["sandbox_id"], str):
        raise TrainingControllerError("live state sandbox identity is invalid")
    if state["pid"] is not None and (
        isinstance(state["pid"], bool)
        or not isinstance(state["pid"], int)
        or state["pid"] < 1
    ):
        raise TrainingControllerError("live state PID is invalid")
    if state["result_path"] is not None and not isinstance(state["result_path"], str):
        raise TrainingControllerError("live state result path is invalid")
    if state["error"] is not None and not isinstance(state["error"], str):
        raise TrainingControllerError("live state error is invalid")
    phase = state["state"]
    if phase in {"QUEUED", "CREATING"} and state["sandbox_id"] is not None:
        raise TrainingControllerError(
            "pre-creation live state cannot contain a sandbox identity"
        )
    if phase in {
        "LIVE", "TRAINING", "VALIDATING", "RESULT_COLLECTED", "CLEANED", "COMPLETE",
    } and (not isinstance(state["sandbox_id"], str) or not state["sandbox_id"].strip()):
        raise TrainingControllerError(
            "post-creation live state requires a sandbox identity"
        )
    if phase == "COMPLETE":
        if state["result_path"] != str(handle.result_path):
            raise TrainingControllerError(
                "completed live state points at another result path"
            )
        if state["error"] is not None:
            raise TrainingControllerError("completed live state cannot contain an error")
    elif state["result_path"] is not None:
        raise TrainingControllerError(
            "only a completed live state may contain a result path"
        )
    if phase == "FAILED":
        if not isinstance(state["error"], str) or not state["error"].strip():
            raise TrainingControllerError("failed live state requires an error")
    elif state["error"] is not None:
        raise TrainingControllerError("non-failed live state cannot contain an error")
    updated_at = _parse_utc(state["updated_at_utc"], "live state updated_at_utc")
    if state["state"] in ACTIVE_STATES:
        pid = state["pid"] or _controller_pid(handle)
        stale_without_pid = pid is None and datetime.now(UTC) - updated_at > STARTUP_GRACE
        if stale_without_pid or (pid is not None and not _pid_alive(pid)):
            reason = (
                "controller did not publish a PID during startup"
                if stale_without_pid
                else f"controller process {pid} exited before a terminal result"
            )
            state = {
                **state,
                "revision": state["revision"] + 1,
                "state": "FAILED",
                "message": "Daytona controller stopped; no result was accepted",
                "updated_at_utc": _now(),
                "pid": pid,
                "result_path": None,
                "error": reason,
            }
            _atomic_json(handle.state_path, state)
            _release_lock(handle.invocation_id)
    return state


def discover_active() -> RunHandle | None:
    if not ACTIVE_LOCK.is_file():
        return None
    try:
        lock = _read_json(ACTIVE_LOCK)
        if (
            not isinstance(lock, dict)
            or set(lock) not in (
                {"invocation_id", "created_at_utc"},
                {"invocation_id", "created_at_utc", "pid"},
            )
        ):
            return None
        invocation_id = lock["invocation_id"]
        handle = RunHandle(invocation_id, RUN_ROOT / invocation_id)
        state = read_state(handle)
    except (KeyError, OSError, TypeError, TrainingControllerError, json.JSONDecodeError):
        return None
    if state["state"] in TERMINAL_STATES:
        _release_lock(invocation_id)
        return None
    return handle


def load_request(handle: RunHandle) -> dict[str, Any]:
    """Load the exact frozen request for reattachment or result validation."""

    _validate_handle(handle)
    return validate_request(_read_json(handle.request_path))


def load_result(handle: RunHandle) -> dict[str, Any]:
    """Load a terminal artifact only when it is bound to this run handle."""

    request = load_request(handle)
    state = read_state(handle)
    if state["state"] != "COMPLETE":
        raise TrainingControllerError("training result is not in COMPLETE state")
    if state["result_path"] != str(handle.result_path):
        raise TrainingControllerError("completed state points at another result path")
    result = _validate_envelope(_read_json(handle.result_path))
    validate_completed_result(result, request)
    if result.get("invocation_id") != handle.invocation_id:
        raise TrainingControllerError("training result belongs to another invocation")
    if state["sandbox_id"] != result["daytona_execution"]["sandbox_id"]:
        raise TrainingControllerError(
            "completed state sandbox identity does not match result evidence"
        )
    return result


def load_last_verified() -> dict[str, Any] | None:
    if not LAST_VERIFIED.is_file():
        return None
    try:
        return _validate_envelope(_read_json(LAST_VERIFIED))
    except (OSError, TypeError, ValueError, TrainingControllerError, json.JSONDecodeError):
        return None


def write_result_envelope(path: Path, result: Mapping[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    envelope = {
        "schema_version": 1,
        "result_sha256": sha256(payload).hexdigest(),
        "result": dict(result),
    }
    _atomic_json(path, envelope)


def write_live_state(path: Path, state: Mapping[str, Any]) -> None:
    _atomic_json(path, state)


def release_active_lock(invocation_id: str) -> None:
    _release_lock(invocation_id)


def copy_as_last_verified(result: Mapping[str, Any]) -> None:
    write_result_envelope(LAST_VERIFIED, result)


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "invocation_id", "model_version", "scenario_sha256",
        "hazards", "seed", "generations", "population",
        "episodes_per_candidate", "max_steps", "synthetic", "operational_use",
        "human_authority_required",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise TrainingControllerError("controller request schema is invalid")
    if value["schema_version"] != RESULT_VERSION or value["model_version"] != MODEL_VERSION:
        raise TrainingControllerError("controller request version is invalid")
    if (
        value["synthetic"] is not True
        or value["operational_use"] is not False
        or value["human_authority_required"] is not True
    ):
        raise TrainingControllerError("controller request boundary is invalid")
    invocation_id = value["invocation_id"]
    if (
        not isinstance(invocation_id, str)
        or not invocation_id.startswith("orbitguard-")
        or len(invocation_id) > 80
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in invocation_id
        )
    ):
        raise TrainingControllerError("controller invocation_id is invalid")
    scenario_digest = value["scenario_sha256"]
    if (
        not isinstance(scenario_digest, str)
        or len(scenario_digest) != 64
        or any(character not in "0123456789abcdef" for character in scenario_digest)
    ):
        raise TrainingControllerError("controller scenario digest is invalid")
    _request_integer(value["seed"], "seed")
    _request_integer(value["generations"], "generations", 2, 80)
    _request_integer(value["population"], "population", 6, 128)
    _request_integer(
        value["episodes_per_candidate"],
        "episodes_per_candidate",
        1,
        12,
    )
    _request_integer(value["max_steps"], "max_steps", 12, 240)
    hazards = hazards_from_payload(value["hazards"])
    if not hazards:
        raise TrainingControllerError("controller request needs an injected object")
    if scenario_fingerprint(hazards, value["max_steps"]) != value["scenario_sha256"]:
        raise TrainingControllerError("controller request scenario hash is invalid")
    return value


def validate_completed_result(result: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    execution = result.get("daytona_execution")
    execution_fields = {
        "sandbox_id",
        "invocation_id",
        "runtime_bundle_sha256",
        "result_validated",
        "sandbox_deleted",
        "local_training_fallback_used",
    }
    if not isinstance(execution, Mapping) or set(execution) != execution_fields:
        raise TrainingControllerError("host Daytona execution schema is invalid")
    if execution.get("result_validated") is not True:
        raise TrainingControllerError("host Daytona validation evidence is missing")
    if execution.get("sandbox_deleted") is not True or execution.get("local_training_fallback_used") is not False:
        raise TrainingControllerError("Daytona cleanup/fallback evidence is invalid")
    worker_result = {key: value for key, value in result.items() if key != "daytona_execution"}
    if (
        execution.get("invocation_id") != request["invocation_id"]
        or execution.get("sandbox_id") != worker_result.get("sandbox_id")
        or execution.get("runtime_bundle_sha256")
        != worker_result.get("runtime_bundle_sha256")
    ):
        raise TrainingControllerError(
            "host Daytona execution identity does not match worker evidence"
        )
    try:
        validate_training_result(
            worker_result,
            expected_sandbox_id=execution["sandbox_id"],
            expected_invocation_id=request["invocation_id"],
            expected_runtime_bundle_sha256=execution["runtime_bundle_sha256"],
            expected_seed=request["seed"],
            expected_scenario_sha256=request["scenario_sha256"],
            expected_hazards=request["hazards"],
            expected_generations=request["generations"],
            expected_population=request["population"],
            expected_episodes_per_candidate=request["episodes_per_candidate"],
            expected_max_steps=request["max_steps"],
        )
    except DaytonaRLExecutionError as exc:
        raise TrainingControllerError(
            "worker result failed strict host validation"
        ) from exc


def _validate_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "result_sha256", "result"}:
        raise TrainingControllerError("result envelope schema is invalid")
    if value["schema_version"] != 1 or not isinstance(value["result"], dict):
        raise TrainingControllerError("result envelope version is invalid")
    payload = json.dumps(value["result"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if sha256(payload).hexdigest() != value["result_sha256"]:
        raise TrainingControllerError("result envelope hash does not match")
    result = value["result"]
    execution = result.get("daytona_execution")
    execution_fields = {
        "sandbox_id",
        "invocation_id",
        "runtime_bundle_sha256",
        "result_validated",
        "sandbox_deleted",
        "local_training_fallback_used",
    }
    if (
        not isinstance(execution, Mapping)
        or set(execution) != execution_fields
        or execution.get("result_validated") is not True
        or execution.get("sandbox_deleted") is not True
        or execution.get("local_training_fallback_used") is not False
    ):
        raise TrainingControllerError("result is not host-validated Daytona evidence")
    sandbox_id = execution.get("sandbox_id")
    invocation_id = execution.get("invocation_id")
    bundle_digest = execution.get("runtime_bundle_sha256")
    if (
        not isinstance(sandbox_id, str)
        or not sandbox_id.strip()
        or sandbox_id != sandbox_id.strip()
        or len(sandbox_id) > 200
        or any(ord(character) < 33 or ord(character) > 126 for character in sandbox_id)
    ):
        raise TrainingControllerError("Daytona result sandbox identity is invalid")
    if (
        not isinstance(invocation_id, str)
        or not invocation_id.startswith("orbitguard-")
        or len(invocation_id) > 80
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in invocation_id
        )
    ):
        raise TrainingControllerError("Daytona result invocation identity is invalid")
    if (
        not isinstance(bundle_digest, str)
        or len(bundle_digest) != 64
        or any(character not in "0123456789abcdef" for character in bundle_digest)
    ):
        raise TrainingControllerError("Daytona runtime bundle digest is invalid")
    worker_result = {
        key: item for key, item in result.items() if key != "daytona_execution"
    }
    try:
        validate_training_result(
            worker_result,
            expected_sandbox_id=execution["sandbox_id"],
            expected_invocation_id=execution["invocation_id"],
            expected_runtime_bundle_sha256=execution["runtime_bundle_sha256"],
            expected_seed=worker_result["training_seed"],
            expected_scenario_sha256=worker_result["scenario_sha256"],
            expected_hazards=worker_result["hazards"],
            expected_generations=worker_result["generations"],
            expected_population=worker_result["population"],
            expected_episodes_per_candidate=worker_result[
                "episodes_per_candidate"
            ],
            expected_max_steps=worker_result["max_steps"],
        )
    except (KeyError, TypeError, ValueError, DaytonaRLExecutionError) as exc:
        raise TrainingControllerError(
            "result envelope is missing its validation contract"
        ) from exc
    return result


def _acquire_lock(invocation_id: str) -> None:
    try:
        descriptor = os.open(
            ACTIVE_LOCK,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        active = discover_active()
        if active is not None:
            raise TrainingControllerError(f"Daytona training already active: {active.invocation_id}")
        # discover_active removes only a validated terminal lock.  A fresh,
        # partial or corrupt lock is never unlinked speculatively because it
        # may belong to a concurrent launcher in its creation window.
        if ACTIVE_LOCK.exists() and not _reclaim_stale_unowned_lock():
            raise TrainingControllerError(
                "Daytona startup lock exists but cannot yet be reconciled"
            )
        try:
            descriptor = os.open(
                ACTIVE_LOCK,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise TrainingControllerError(
                "another Daytona launcher acquired the active lock"
            ) from exc
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"invocation_id": invocation_id, "created_at_utc": _now()},
                handle,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        _unlink_lock_if_same_file(identity)
        raise


def _reclaim_stale_unowned_lock() -> bool:
    """Reclaim only an old lock with no live controller PID evidence."""

    try:
        identity = ACTIVE_LOCK.stat()
    except OSError:
        return False
    age = datetime.now(UTC) - datetime.fromtimestamp(identity.st_mtime, UTC)
    if age <= STALE_LOCK_RECLAIM_AFTER:
        return False
    try:
        value = _read_json(ACTIVE_LOCK)
    except (OSError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict):
        lock_pid = value.get("pid")
        if (
            not isinstance(lock_pid, bool)
            and isinstance(lock_pid, int)
            and lock_pid > 0
            and _pid_alive(lock_pid)
        ):
            return False
        invocation_id = value.get("invocation_id")
        if isinstance(invocation_id, str):
            candidate = RunHandle(invocation_id, RUN_ROOT / invocation_id)
            try:
                _validate_handle(candidate)
            except TrainingControllerError:
                pass
            else:
                controller_pid = _controller_pid(candidate)
                if controller_pid is not None and _pid_alive(controller_pid):
                    return False
    return _unlink_lock_if_same_file(identity)


def _unlink_lock_if_same_file(identity: os.stat_result) -> bool:
    try:
        current = ACTIVE_LOCK.stat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            return False
        ACTIVE_LOCK.unlink()
        return True
    except OSError:
        return False


def _release_lock(invocation_id: str) -> None:
    if not ACTIVE_LOCK.is_file():
        return
    try:
        value = _read_json(ACTIVE_LOCK)
        if value.get("invocation_id") == invocation_id:
            ACTIVE_LOCK.unlink()
    except (OSError, AttributeError, json.JSONDecodeError):
        return


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_handle(handle: RunHandle) -> None:
    if not isinstance(handle, RunHandle):
        raise TrainingControllerError("run handle type is invalid")
    expected = RUN_ROOT / handle.invocation_id
    if handle.run_dir.resolve() != expected.resolve():
        raise TrainingControllerError("run handle path leaves the Daytona run root")
    if (
        not handle.invocation_id.startswith("orbitguard-")
        or len(handle.invocation_id) > 80
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in handle.invocation_id
        )
    ):
        raise TrainingControllerError("run handle invocation is invalid")


def _controller_pid(handle: RunHandle) -> int | None:
    if not handle.pid_path.is_file():
        return None
    try:
        value = _read_json(handle.pid_path)
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema_version", "invocation_id", "pid", "started_at_utc"}
        or value.get("schema_version") != 1
        or value.get("invocation_id") != handle.invocation_id
    ):
        return None
    pid = value.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return None
    return pid


def _pid_alive(pid: int) -> bool:
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        waited = 0
    except OSError:
        waited = 0
    if waited == pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise TrainingControllerError(f"{name} must be an ISO-8601 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise TrainingControllerError(
            f"{name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise TrainingControllerError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _request_integer(
    value: Any,
    name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrainingControllerError(f"controller {name} must be an integer")
    if minimum is not None and value < minimum:
        raise TrainingControllerError(
            f"controller {name} must be at least {minimum}"
        )
    if maximum is not None and value > maximum:
        raise TrainingControllerError(
            f"controller {name} must be at most {maximum}"
        )
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try: os.unlink(temporary_name)
        except OSError: pass
        raise


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
