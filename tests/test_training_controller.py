from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest

from orbit_guard import training_controller
from orbit_guard.daytona_rl import DaytonaRLExecutionError
from orbit_guard.rl_core import (
    MODEL_VERSION,
    RESULT_VERSION,
    default_hazards,
    hazards_from_payload,
    hazards_to_payload,
    make_hazard,
    scenario_fingerprint,
    train_policy,
)
from orbit_guard.training_controller import (
    RunHandle,
    TrainingControllerError,
    copy_as_last_verified,
    discover_active,
    load_last_verified,
    load_result,
    read_state,
    release_active_lock,
    start_training,
    validate_completed_result,
    validate_request,
    write_live_state,
    write_result_envelope,
)


INVOCATION_ID = "orbitguard-controller-test"
SANDBOX_ID = "sandbox-controller-test"
BUNDLE_SHA256 = "c" * 64
UTC = timezone.utc


def _request() -> dict:
    hazards = default_hazards()
    return {
        "schema_version": RESULT_VERSION,
        "invocation_id": INVOCATION_ID,
        "model_version": MODEL_VERSION,
        "scenario_sha256": scenario_fingerprint(hazards, 26),
        "hazards": hazards_to_payload(hazards),
        "seed": 42,
        "generations": 2,
        "population": 6,
        "episodes_per_candidate": 1,
        "max_steps": 26,
        "synthetic": True,
        "operational_use": False,
        "human_authority_required": True,
    }


def _completed_result() -> dict:
    request = _request()
    worker = train_policy(
        default_hazards(),
        seed=request["seed"],
        generations=request["generations"],
        population=request["population"],
        episodes_per_candidate=request["episodes_per_candidate"],
        max_steps=request["max_steps"],
        sandbox_id=SANDBOX_ID,
        invocation_id=INVOCATION_ID,
        runtime_bundle_sha256=BUNDLE_SHA256,
    )
    return {
        **worker,
        "daytona_execution": {
            "sandbox_id": SANDBOX_ID,
            "invocation_id": INVOCATION_ID,
            "runtime_bundle_sha256": BUNDLE_SHA256,
            "result_validated": True,
            "sandbox_deleted": True,
            "local_training_fallback_used": False,
        },
    }


def _configure_temp_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    run_root = tmp_path / "runs"
    controller_script = tmp_path / "controller.py"
    controller_script.write_text("# fake controller\n", encoding="utf-8")
    monkeypatch.setattr(training_controller, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(training_controller, "RUN_ROOT", run_root)
    monkeypatch.setattr(training_controller, "ACTIVE_LOCK", run_root / "active.json")
    monkeypatch.setattr(
        training_controller, "LAST_VERIFIED", run_root / "last_verified.json"
    )
    monkeypatch.setattr(training_controller, "CONTROLLER_SCRIPT", controller_script)
    monkeypatch.setattr(
        training_controller,
        "runtime_status",
        lambda: {
            "ready": True,
            "sdk_installed": True,
            "sdk_version": "test",
            "credential_present": True,
            "api_url_overridden": False,
        },
    )
    return run_root


class FakeChildProcess:
    pid = os.getpid()

    def poll(self):
        return None

    def terminate(self) -> None:
        raise AssertionError("healthy fake child should not be terminated")

    def wait(self, timeout: int):
        raise AssertionError("healthy fake child should not be waited")

    def kill(self) -> None:
        raise AssertionError("healthy fake child should not be killed")


def test_controller_request_schema_hash_ranges_and_boundary_are_strict() -> None:
    request = _request()
    assert validate_request(request) is request

    mutations = []
    extra = deepcopy(request)
    extra["fallback"] = "local"
    mutations.append((extra, "schema"))
    wrong_hash = deepcopy(request)
    wrong_hash["scenario_sha256"] = "0" * 64
    mutations.append((wrong_hash, "scenario hash"))
    wrong_boundary = deepcopy(request)
    wrong_boundary["operational_use"] = True
    mutations.append((wrong_boundary, "boundary"))
    wrong_identity = deepcopy(request)
    wrong_identity["invocation_id"] = "not-prefixed"
    mutations.append((wrong_identity, "invocation_id"))
    bool_seed = deepcopy(request)
    bool_seed["seed"] = True
    mutations.append((bool_seed, "seed must be an integer"))
    too_small = deepcopy(request)
    too_small["generations"] = 1
    mutations.append((too_small, "generations must be at least 2"))

    for value, message in mutations:
        with pytest.raises(TrainingControllerError, match=message):
            validate_request(value)


def test_start_training_freezes_request_and_uses_one_shell_free_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    monkeypatch.setattr(training_controller, "uuid4", lambda: "controller-test")
    calls: list[dict] = []

    def fake_popen(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return FakeChildProcess()

    monkeypatch.setattr(training_controller.subprocess, "Popen", fake_popen)

    handle = start_training(
        default_hazards(),
        seed=42,
        generations=2,
        population=6,
        episodes_per_candidate=1,
        max_steps=26,
    )

    assert handle.invocation_id == INVOCATION_ID
    assert handle.run_dir == run_root / INVOCATION_ID
    request = json.loads(handle.request_path.read_text(encoding="utf-8"))
    assert validate_request(request) == request
    assert request["hazards"] == hazards_to_payload(default_hazards())
    assert request["scenario_sha256"] == scenario_fingerprint(default_hazards(), 26)
    assert read_state(handle)["state"] == "QUEUED"
    pid_record = json.loads(handle.pid_path.read_text(encoding="utf-8"))
    assert pid_record["invocation_id"] == INVOCATION_ID
    assert pid_record["pid"] == os.getpid()
    assert len(calls) == 1
    assert calls[0]["argv"] == [
        training_controller.sys.executable,
        str(training_controller.CONTROLLER_SCRIPT),
        "--request",
        str(handle.request_path),
        "--state",
        str(handle.state_path),
        "--result",
        str(handle.result_path),
    ]
    assert calls[0]["shell"] is False
    assert calls[0]["start_new_session"] is True
    assert calls[0]["stdin"] is training_controller.subprocess.DEVNULL
    assert calls[0]["stderr"] is training_controller.subprocess.STDOUT
    assert Path(calls[0]["stdout"].name) == handle.log_path

    with pytest.raises(TrainingControllerError, match="already active"):
        start_training(default_hazards())
    assert len(calls) == 1

    release_active_lock("different-run")
    assert training_controller.ACTIVE_LOCK.is_file()
    release_active_lock(INVOCATION_ID)
    assert not training_controller.ACTIVE_LOCK.exists()


def test_launch_failure_releases_host_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    monkeypatch.setattr(training_controller, "uuid4", lambda: "launch-failure")

    def fail_launch(*args, **kwargs):
        raise OSError("cannot spawn")

    monkeypatch.setattr(training_controller.subprocess, "Popen", fail_launch)

    with pytest.raises(OSError, match="cannot spawn"):
        start_training(default_hazards())

    assert not training_controller.ACTIVE_LOCK.exists()


@pytest.mark.parametrize("partial_json", [False, True])
def test_fresh_or_partial_startup_lock_is_never_speculatively_unlinked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, partial_json: bool
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    training_controller.ACTIVE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    if partial_json:
        original = b'{"invocation_id":"orbitguard-concurrent"'
    else:
        original = json.dumps(
            {
                "invocation_id": "orbitguard-concurrent",
                "created_at_utc": datetime.now(UTC).isoformat(),
            }
        ).encode("utf-8")
    training_controller.ACTIVE_LOCK.write_bytes(original)

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("a second controller must not launch")

    monkeypatch.setattr(training_controller.subprocess, "Popen", forbidden_popen)

    with pytest.raises(TrainingControllerError, match="lock|active"):
        start_training(default_hazards())

    assert training_controller.ACTIVE_LOCK.read_bytes() == original


def test_stale_corrupt_lock_without_live_pid_is_reclaimed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    monkeypatch.setattr(training_controller, "uuid4", lambda: "recovered-lock")
    training_controller.ACTIVE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    training_controller.ACTIVE_LOCK.write_text("{partial", encoding="utf-8")
    stale = time.time() - training_controller.STALE_LOCK_RECLAIM_AFTER.total_seconds() - 60
    os.utime(training_controller.ACTIVE_LOCK, (stale, stale))
    monkeypatch.setattr(
        training_controller.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeChildProcess(),
    )

    handle = start_training(default_hazards())

    assert handle.invocation_id == "orbitguard-recovered-lock"
    lock = json.loads(training_controller.ACTIVE_LOCK.read_text(encoding="utf-8"))
    assert lock["invocation_id"] == handle.invocation_id
    release_active_lock(handle.invocation_id)


def test_stale_lock_with_live_controller_pid_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    invocation_id = "orbitguard-still-running"
    run_dir = run_root / invocation_id
    run_dir.mkdir(parents=True)
    (run_dir / "controller_pid.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "pid": os.getpid(),
                "started_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    training_controller.ACTIVE_LOCK.write_text(
        json.dumps(
            {
                "invocation_id": invocation_id,
                "created_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    stale = time.time() - training_controller.STALE_LOCK_RECLAIM_AFTER.total_seconds() - 60
    os.utime(training_controller.ACTIVE_LOCK, (stale, stale))

    with pytest.raises(TrainingControllerError, match="lock|active"):
        start_training(default_hazards())

    assert training_controller.ACTIVE_LOCK.exists()


def test_lock_publication_failure_unlinks_only_new_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    training_controller.RUN_ROOT.mkdir(parents=True, exist_ok=True)

    def fail_dump(*args, **kwargs):
        raise OSError("lock publication failed")

    monkeypatch.setattr(training_controller.json, "dump", fail_dump)
    with pytest.raises(OSError, match="lock publication failed"):
        training_controller._acquire_lock("orbitguard-publication-failure")
    assert not training_controller.ACTIVE_LOCK.exists()


def test_exclusive_lock_race_is_wrapped_as_controller_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    real_open = training_controller.os.open

    def losing_open(path, flags, mode=0o777):
        if Path(path) == training_controller.ACTIVE_LOCK:
            raise FileExistsError("simulated O_EXCL race")
        return real_open(path, flags, mode)

    monkeypatch.setattr(training_controller.os, "open", losing_open)

    with pytest.raises(TrainingControllerError, match="launcher|lock"):
        start_training(default_hazards())


def test_dead_controller_is_persisted_failed_and_releases_matching_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    handle.request_path.parent.mkdir(parents=True, exist_ok=True)
    handle.request_path.write_text(json.dumps(_request()), encoding="utf-8")
    write_live_state(
        handle.state_path,
        {
            "schema_version": 1,
            "invocation_id": INVOCATION_ID,
            "revision": 4,
            "state": "TRAINING",
            "message": "remote training active",
            "sandbox_id": SANDBOX_ID,
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "pid": 999_999_999,
            "result_path": None,
            "error": None,
        },
    )
    handle.pid_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "invocation_id": INVOCATION_ID,
                "pid": 999_999_999,
                "started_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    training_controller.ACTIVE_LOCK.write_text(
        json.dumps(
            {
                "invocation_id": INVOCATION_ID,
                "created_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(training_controller, "_pid_alive", lambda pid: False)

    assert discover_active() is None
    failed = json.loads(handle.state_path.read_text(encoding="utf-8"))
    assert failed["state"] == "FAILED"
    assert failed["revision"] == 5
    assert failed["sandbox_id"] == SANDBOX_ID
    assert failed["result_path"] is None
    assert "exited before a terminal result" in failed["error"]
    assert not training_controller.ACTIVE_LOCK.exists()


def test_startup_grace_allows_pid_publication_then_fails_stale_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    fresh = {
        "schema_version": 1,
        "invocation_id": INVOCATION_ID,
        "revision": 0,
        "state": "QUEUED",
        "message": "controller queued",
        "sandbox_id": None,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "pid": None,
        "result_path": None,
        "error": None,
    }
    write_live_state(handle.state_path, fresh)
    assert read_state(handle)["state"] == "QUEUED"

    stale = {
        **fresh,
        "updated_at_utc": "2000-01-01T00:00:00Z",
    }
    write_live_state(handle.state_path, stale)
    reconciled = read_state(handle)
    assert reconciled["state"] == "FAILED"
    assert reconciled["revision"] == 1
    assert "did not publish a PID" in reconciled["error"]


def test_active_run_reattaches_to_its_strict_frozen_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    hazards = [default_hazards()[0], make_hazard("crossing", 1)]
    request = {
        **_request(),
        "hazards": hazards_to_payload(hazards),
        "scenario_sha256": scenario_fingerprint(hazards, 26),
    }
    handle.request_path.parent.mkdir(parents=True, exist_ok=True)
    handle.request_path.write_text(json.dumps(request), encoding="utf-8")
    write_live_state(
        handle.state_path,
        {
            "schema_version": 1,
            "invocation_id": INVOCATION_ID,
            "revision": 3,
            "state": "LIVE",
            "message": "sandbox created",
            "sandbox_id": SANDBOX_ID,
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "result_path": None,
            "error": None,
        },
    )
    handle.pid_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "invocation_id": INVOCATION_ID,
                "pid": os.getpid(),
                "started_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    training_controller.ACTIVE_LOCK.write_text(
        json.dumps(
            {
                "invocation_id": INVOCATION_ID,
                "created_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(training_controller, "_pid_alive", lambda pid: True)

    active = discover_active()
    assert active == handle
    frozen = training_controller.load_request(active)
    assert hazards_from_payload(frozen["hazards"]) == hazards
    assert frozen["scenario_sha256"] == scenario_fingerprint(hazards, 26)

    outside = RunHandle(INVOCATION_ID, tmp_path / "outside" / INVOCATION_ID)
    with pytest.raises(TrainingControllerError, match="leaves the Daytona run root"):
        training_controller.load_request(outside)


def test_live_state_rejects_stale_identity_extra_fields_and_invalid_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    state = {
        "schema_version": 1,
        "invocation_id": INVOCATION_ID,
        "revision": 3,
        "state": "TRAINING",
        "message": "remote episodes running",
        "sandbox_id": SANDBOX_ID,
        "updated_at_utc": "2026-09-03T13:00:00Z",
        "pid": os.getpid(),
        "result_path": None,
        "error": None,
    }
    write_live_state(handle.state_path, state)
    assert read_state(handle) == state

    stale = deepcopy(state)
    stale["invocation_id"] = "orbitguard-stale"
    write_live_state(handle.state_path, stale)
    with pytest.raises(TrainingControllerError, match="invocation does not match"):
        read_state(handle)

    extra = deepcopy(state)
    extra["progress_percent"] = 50
    write_live_state(handle.state_path, extra)
    with pytest.raises(TrainingControllerError, match="schema is invalid"):
        read_state(handle)

    invalid_revision = deepcopy(state)
    invalid_revision["revision"] = True
    write_live_state(handle.state_path, invalid_revision)
    with pytest.raises(TrainingControllerError, match="revision is invalid"):
        read_state(handle)


@pytest.mark.parametrize(
    ("phase", "changes"),
    [
        ("QUEUED", {"sandbox_id": SANDBOX_ID}),
        ("CREATING", {"result_path": "/tmp/premature.json"}),
        ("LIVE", {"sandbox_id": None}),
        ("TRAINING", {"sandbox_id": SANDBOX_ID, "error": "premature error"}),
        ("COMPLETE", {"sandbox_id": SANDBOX_ID, "result_path": None}),
        (
            "COMPLETE",
            {
                "sandbox_id": SANDBOX_ID,
                "result_path": "RESULT_PATH",
                "error": "success cannot carry an error",
            },
        ),
        ("FAILED", {"error": None}),
        ("FAILED", {"error": "failed", "result_path": "RESULT_PATH"}),
    ],
)
def test_live_state_rejects_incoherent_phase_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    changes: dict,
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    resolved_changes = {
        key: str(handle.result_path) if value == "RESULT_PATH" else value
        for key, value in changes.items()
    }
    state = {
        "schema_version": 1,
        "invocation_id": INVOCATION_ID,
        "revision": 4,
        "state": phase,
        "message": "phase test",
        "sandbox_id": None,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "result_path": None,
        "error": None,
        **resolved_changes,
    }
    write_live_state(handle.state_path, state)

    with pytest.raises(TrainingControllerError):
        read_state(handle)


@pytest.mark.parametrize(
    ("phase", "sandbox", "result", "error", "pid"),
    [
        ("QUEUED", None, None, None, None),
        ("CREATING", None, None, None, os.getpid()),
        ("LIVE", SANDBOX_ID, None, None, os.getpid()),
        ("TRAINING", SANDBOX_ID, None, None, os.getpid()),
        ("VALIDATING", SANDBOX_ID, None, None, os.getpid()),
        ("RESULT_COLLECTED", SANDBOX_ID, None, None, os.getpid()),
        ("CLEANED", SANDBOX_ID, None, None, os.getpid()),
        ("COMPLETE", SANDBOX_ID, "RESULT_PATH", None, os.getpid()),
        ("FAILED", SANDBOX_ID, None, "remote worker failed", os.getpid()),
    ],
)
def test_live_state_accepts_each_coherent_controller_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    sandbox: str | None,
    result: str | None,
    error: str | None,
    pid: int | None,
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    result_path = str(handle.result_path) if result == "RESULT_PATH" else result
    state = {
        "schema_version": 1,
        "invocation_id": INVOCATION_ID,
        "revision": 4,
        "state": phase,
        "message": "phase test",
        "sandbox_id": sandbox,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "pid": pid,
        "result_path": result_path,
        "error": error,
    }
    write_live_state(handle.state_path, state)

    assert read_state(handle) == state


def test_post_spawn_cleanup_releases_lock_even_when_terminate_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    monkeypatch.setattr(training_controller, "uuid4", lambda: "terminate-failure")
    calls = {"terminate": 0, "kill": 0}

    class UncooperativeChild:
        pid = os.getpid()

        def poll(self):
            return None

        def terminate(self) -> None:
            calls["terminate"] += 1
            raise RuntimeError("terminate failed")

        def kill(self) -> None:
            calls["kill"] += 1

        def wait(self, timeout: int):
            return 0

    monkeypatch.setattr(
        training_controller.subprocess,
        "Popen",
        lambda *args, **kwargs: UncooperativeChild(),
    )
    original_atomic_json = training_controller._atomic_json

    def fail_pid_record(path: Path, value: dict) -> None:
        if Path(path).name == "controller_pid.json":
            raise OSError("pid record failed")
        original_atomic_json(path, value)

    monkeypatch.setattr(training_controller, "_atomic_json", fail_pid_record)

    with pytest.raises(Exception) as caught:
        start_training(default_hazards())

    assert "pid record failed" in str(caught.value)
    assert calls["terminate"] == 1
    assert not training_controller.ACTIVE_LOCK.exists()


def test_terminal_active_state_is_released_during_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_root = _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, run_root / INVOCATION_ID)
    write_live_state(
        handle.state_path,
        {
            "schema_version": 1,
            "invocation_id": INVOCATION_ID,
            "revision": 9,
            "state": "COMPLETE",
            "message": "done",
            "sandbox_id": SANDBOX_ID,
            "updated_at_utc": "2026-09-03T13:00:00Z",
            "pid": 123,
            "result_path": str(handle.result_path),
            "error": None,
        },
    )
    training_controller.ACTIVE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    training_controller.ACTIVE_LOCK.write_text(
        json.dumps(
            {
                "invocation_id": INVOCATION_ID,
                "created_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    assert discover_active() is None
    assert not training_controller.ACTIVE_LOCK.exists()


def test_completed_result_envelope_is_hashed_revalidated_and_replayable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    result = _completed_result()
    handle = RunHandle(INVOCATION_ID, training_controller.RUN_ROOT / INVOCATION_ID)

    validate_completed_result(result, _request())
    handle.request_path.parent.mkdir(parents=True, exist_ok=True)
    handle.request_path.write_text(json.dumps(_request()), encoding="utf-8")
    write_live_state(
        handle.state_path,
        {
            "schema_version": 1,
            "invocation_id": INVOCATION_ID,
            "revision": 10,
            "state": "COMPLETE",
            "message": "validated result ready",
            "sandbox_id": SANDBOX_ID,
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "result_path": str(handle.result_path),
            "error": None,
        },
    )
    write_result_envelope(handle.result_path, result)
    assert load_result(handle) == result
    copy_as_last_verified(result)
    assert load_last_verified() == result

    envelope = json.loads(handle.result_path.read_text(encoding="utf-8"))
    envelope["result"]["training_seed"] = 999
    handle.result_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(TrainingControllerError, match="hash does not match"):
        load_result(handle)

    unclean = deepcopy(result)
    unclean["daytona_execution"]["sandbox_deleted"] = False
    write_result_envelope(training_controller.LAST_VERIFIED, unclean)
    assert load_last_verified() is None

    local_only = train_policy(
        default_hazards(),
        seed=42,
        generations=2,
        population=6,
        episodes_per_candidate=1,
        max_steps=26,
        sandbox_id=None,
        invocation_id=None,
        runtime_bundle_sha256=None,
    )
    fabricated = {
        **local_only,
        "daytona_execution": {
            "sandbox_id": None,
            "invocation_id": None,
            "runtime_bundle_sha256": None,
            "result_validated": True,
            "sandbox_deleted": True,
            "local_training_fallback_used": False,
        },
    }
    write_result_envelope(training_controller.LAST_VERIFIED, fabricated)
    assert load_last_verified() is None

    wrong_scenario = deepcopy(result)
    wrong_scenario["scenario_sha256"] = "0" * 64
    write_result_envelope(training_controller.LAST_VERIFIED, wrong_scenario)
    assert load_last_verified() is None


def test_load_result_is_bound_to_handle_request_state_and_result_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_temp_controller(monkeypatch, tmp_path)
    handle = RunHandle(INVOCATION_ID, training_controller.RUN_ROOT / INVOCATION_ID)
    result = _completed_result()
    handle.request_path.parent.mkdir(parents=True, exist_ok=True)
    handle.request_path.write_text(json.dumps(_request()), encoding="utf-8")
    state = {
        "schema_version": 1,
        "invocation_id": INVOCATION_ID,
        "revision": 10,
        "state": "COMPLETE",
        "message": "validated result ready",
        "sandbox_id": SANDBOX_ID,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "result_path": str(handle.result_path),
        "error": None,
    }
    write_live_state(handle.state_path, state)
    write_result_envelope(handle.result_path, result)
    assert load_result(handle) == result

    wrong_sandbox_state = {**state, "sandbox_id": "sandbox-ledger-other"}
    write_live_state(handle.state_path, wrong_sandbox_state)
    with pytest.raises(TrainingControllerError, match="sandbox identity"):
        load_result(handle)

    wrong_path_state = {**state, "result_path": str(tmp_path / "other.json")}
    write_live_state(handle.state_path, wrong_path_state)
    with pytest.raises(TrainingControllerError, match="another result path"):
        load_result(handle)

    write_live_state(handle.state_path, state)
    wrong_invocation = deepcopy(result)
    wrong_invocation["invocation_id"] = "orbitguard-other"
    wrong_invocation["daytona_execution"]["invocation_id"] = "orbitguard-other"
    write_result_envelope(handle.result_path, wrong_invocation)
    with pytest.raises(
        (TrainingControllerError, DaytonaRLExecutionError),
        match="identity|invocation",
    ):
        load_result(handle)

    outside = RunHandle(INVOCATION_ID, tmp_path / "outside" / INVOCATION_ID)
    with pytest.raises(TrainingControllerError, match="leaves the Daytona run root"):
        load_result(outside)


def test_controller_failure_preserves_last_real_sandbox_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_daytona_rl_controller.py"
    spec = importlib.util.spec_from_file_location(
        "test_run_daytona_rl_controller", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    run_dir = tmp_path / INVOCATION_ID
    run_dir.mkdir()
    request_path = run_dir / "request.json"
    state_path = run_dir / "live_state.json"
    result_path = run_dir / "result.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    released: list[str] = []

    def fail_after_sandbox_creation(hazards, **kwargs):
        kwargs["event_callback"](
            {
                "state": "LIVE",
                "message": "sandbox created",
                "sandbox_id": SANDBOX_ID,
                "invocation_id": INVOCATION_ID,
            }
        )
        raise RuntimeError("remote worker stopped")

    monkeypatch.setattr(module, "run_daytona_training", fail_after_sandbox_creation)
    monkeypatch.setattr(module, "release_active_lock", released.append)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "--request",
            str(request_path),
            "--state",
            str(state_path),
            "--result",
            str(result_path),
        ],
    )

    assert module.main() == 1
    failed = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed["state"] == "FAILED"
    assert failed["sandbox_id"] == SANDBOX_ID
    assert failed["result_path"] is None
    assert "RuntimeError: remote worker stopped" in failed["error"]
    assert released == [INVOCATION_ID]


def test_completed_result_rejects_host_worker_identity_or_cleanup_mismatch() -> None:
    result = _completed_result()

    wrong_identity = deepcopy(result)
    wrong_identity["daytona_execution"]["sandbox_id"] = "different-sandbox"
    with pytest.raises(TrainingControllerError, match="identity does not match"):
        validate_completed_result(wrong_identity, _request())

    no_cleanup = deepcopy(result)
    no_cleanup["daytona_execution"]["sandbox_deleted"] = False
    with pytest.raises(TrainingControllerError, match="cleanup/fallback"):
        validate_completed_result(no_cleanup, _request())

    local_fallback = deepcopy(result)
    local_fallback["daytona_execution"]["local_training_fallback_used"] = True
    with pytest.raises(TrainingControllerError, match="cleanup/fallback"):
        validate_completed_result(local_fallback, _request())
