from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from orbit_guard import daytona_rl
from orbit_guard.daytona_rl import (
    DaytonaRLExecutionError,
    run_daytona_training,
    validate_training_result,
)
from orbit_guard.rl_core import (
    default_hazards,
    hazards_from_payload,
    hazards_to_payload,
    scenario_fingerprint,
    train_policy,
)


SANDBOX_ID = "sandbox-fake-001"
INVOCATION_ID = "fixture-run-001"
BUNDLE_SHA256 = "b" * 64
SEED = 42
GENERATIONS = 2
POPULATION = 6
EPISODES = 1
MAX_STEPS = 26


@pytest.fixture(scope="module")
def validated_result() -> dict:
    return train_policy(
        default_hazards(),
        seed=SEED,
        generations=GENERATIONS,
        population=POPULATION,
        episodes_per_candidate=EPISODES,
        max_steps=MAX_STEPS,
        sandbox_id=SANDBOX_ID,
        invocation_id=INVOCATION_ID,
        runtime_bundle_sha256=BUNDLE_SHA256,
    )


def _validation_kwargs() -> dict:
    hazards = default_hazards()
    return {
        "expected_sandbox_id": SANDBOX_ID,
        "expected_invocation_id": INVOCATION_ID,
        "expected_runtime_bundle_sha256": BUNDLE_SHA256,
        "expected_seed": SEED,
        "expected_scenario_sha256": scenario_fingerprint(hazards, MAX_STEPS),
        "expected_hazards": hazards_to_payload(hazards),
        "expected_generations": GENERATIONS,
        "expected_population": POPULATION,
        "expected_episodes_per_candidate": EPISODES,
        "expected_max_steps": MAX_STEPS,
    }


def test_runtime_status_requires_pinned_sdk_and_nonblank_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        daytona_rl.importlib.metadata,
        "version",
        lambda package: "0.206.0",
    )
    monkeypatch.setenv("DAYTONA_API_KEY", "   ")
    monkeypatch.setenv("DAYTONA_API_URL", "   ")

    status = daytona_rl.runtime_status()

    assert status == {
        "sdk_installed": True,
        "sdk_version": "0.206.0",
        "version_compatible": False,
        "credential_present": False,
        "api_url_overridden": False,
        "ready": False,
    }


def test_worker_result_accepts_only_the_exact_frozen_job_contract(
    validated_result: dict,
) -> None:
    validate_training_result(validated_result, **_validation_kwargs())

    extra = deepcopy(validated_result)
    extra["claim"] = "operationally safe"
    with pytest.raises(DaytonaRLExecutionError, match="schema does not match"):
        validate_training_result(extra, **_validation_kwargs())

    missing = deepcopy(validated_result)
    del missing["reference_frame"]
    with pytest.raises(DaytonaRLExecutionError, match="schema does not match"):
        validate_training_result(missing, **_validation_kwargs())

    wrong_invocation = deepcopy(validated_result)
    wrong_invocation["invocation_id"] = "stale-run"
    with pytest.raises(DaytonaRLExecutionError, match="invocation_id does not match"):
        validate_training_result(wrong_invocation, **_validation_kwargs())

    wrong_hazard = deepcopy(validated_result)
    wrong_hazard["hazards"][0]["x0_km"] += 0.001
    with pytest.raises(DaytonaRLExecutionError, match="hazards do not match"):
        validate_training_result(wrong_hazard, **_validation_kwargs())


def test_worker_result_rejects_nonfinite_or_internally_incoherent_evidence(
    validated_result: dict,
) -> None:
    nonfinite = deepcopy(validated_result)
    nonfinite["trained_weights"][0] = float("nan")
    with pytest.raises(DaytonaRLExecutionError, match="must be finite"):
        validate_training_result(nonfinite, **_validation_kwargs())

    wrong_reward = deepcopy(validated_result)
    wrong_reward["baseline_evaluation"]["reward"] += 1.0
    with pytest.raises(DaytonaRLExecutionError, match="does not equal reward sum"):
        validate_training_result(wrong_reward, **_validation_kwargs())

    wrong_action_name = deepcopy(validated_result)
    wrong_action_name["trained_evaluation"]["action_names"][0] = "MAGIC BURN"
    with pytest.raises(DaytonaRLExecutionError, match="action name/index disagree"):
        validate_training_result(wrong_action_name, **_validation_kwargs())

    wrong_distance = deepcopy(validated_result)
    wrong_distance["policy_evolution"][0]["trajectory"][1]["objects"][0][
        "distance_km"
    ] += 0.1
    with pytest.raises(DaytonaRLExecutionError, match="distance is inconsistent"):
        validate_training_result(wrong_distance, **_validation_kwargs())

    wrong_checkpoint = deepcopy(validated_result)
    wrong_checkpoint["policy_evolution"][1]["weights"][0] += 0.01
    with pytest.raises(DaytonaRLExecutionError, match="checkpoint digest"):
        validate_training_result(wrong_checkpoint, **_validation_kwargs())

    wrong_frame = deepcopy(validated_result)
    wrong_frame["reference_frame"]["simulation_frame"] = "Earth-centred telemetry"
    with pytest.raises(DaytonaRLExecutionError, match="reference frame was altered"):
        validate_training_result(wrong_frame, **_validation_kwargs())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.__setitem__(
            "duration_seconds", str(result["duration_seconds"])
        ),
        lambda result: result["training_curve"][0].__setitem__(
            "mean_return", str(result["training_curve"][0]["mean_return"])
        ),
        lambda result: result["baseline_evaluation"]["trajectory"][0][
            "satellite"
        ].__setitem__("x_km", "0.0"),
    ],
    ids=["duration", "curve-return", "trajectory-coordinate"],
)
def test_worker_result_rejects_numeric_strings_even_when_float_convertible(
    validated_result: dict, mutate
) -> None:
    altered = deepcopy(validated_result)
    mutate(altered)

    with pytest.raises(DaytonaRLExecutionError):
        validate_training_result(altered, **_validation_kwargs())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.__setitem__("record_version", True),
        lambda result: result.__setitem__("policy_version_before", False),
        lambda result: result.__setitem__("policy_version_after", True),
        lambda result: result.__setitem__("episodes_per_candidate", True),
        lambda result: result["training_curve"][0].__setitem__("generation", True),
        lambda result: result["policy_evolution"][1].__setitem__("generation", True),
        lambda result: result.__setitem__(
            "integrity",
            {
                "result_is_synthetic": 1,
                "operational_use": 0,
                "human_authority_required": 1,
                "worker_runtime": "Python standard library only",
            },
        ),
        lambda result: result["baseline_evaluation"]["trajectory"][1].__setitem__(
            "action_index", True
        ),
    ],
    ids=[
        "record-version",
        "policy-before",
        "policy-after",
        "episodes",
        "curve-generation",
        "evolution-generation",
        "integrity-boundary",
        "trajectory-action",
    ],
)
def test_worker_result_rejects_boolean_integer_aliases(
    validated_result: dict, mutate
) -> None:
    altered = deepcopy(validated_result)
    mutate(altered)

    with pytest.raises(DaytonaRLExecutionError):
        validate_training_result(altered, **_validation_kwargs())


def test_worker_result_recomputes_the_scenario_digest(
    validated_result: dict,
) -> None:
    altered = deepcopy(validated_result)
    altered["scenario_sha256"] = "0" * 64
    kwargs = {**_validation_kwargs(), "expected_scenario_sha256": "0" * 64}

    with pytest.raises(DaytonaRLExecutionError, match="scenario digest"):
        validate_training_result(altered, **kwargs)


def test_worker_result_rejects_non_utc_offset_timestamps(
    validated_result: dict,
) -> None:
    altered = deepcopy(validated_result)
    london_summer = timezone(timedelta(hours=1))
    for field in ("started_at_utc", "completed_at_utc"):
        parsed = datetime.fromisoformat(altered[field].replace("Z", "+00:00"))
        altered[field] = parsed.astimezone(london_summer).isoformat()

    # These encode the same instants and duration, but the evidence contract
    # requires UTC rather than silently normalising arbitrary offsets.
    with pytest.raises(DaytonaRLExecutionError, match="UTC"):
        validate_training_result(altered, **_validation_kwargs())


class FakeCreateParams:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakeFileSystem:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.created_folders: list[tuple[str, str, int | None]] = []
        self.uploads: list[tuple[str, int]] = []
        self.info_requests: list[tuple[str, int | None]] = []
        self.downloads: list[tuple[str, int]] = []

    def create_folder(
        self, path: str, mode: str, request_timeout: int | None = None
    ) -> None:
        self.created_folders.append((path, mode, request_timeout))

    def upload_file(self, content: bytes, path: str, timeout: int) -> None:
        self.files[path] = bytes(content)
        self.uploads.append((path, timeout))

    def get_file_info(self, path: str, request_timeout: int | None = None):
        self.info_requests.append((path, request_timeout))
        return SimpleNamespace(size=len(self.files[path]))

    def download_file(self, path: str, timeout: int = 1_800) -> bytes:
        self.downloads.append((path, timeout))
        return self.files[path]


class FakeProcess:
    def __init__(self, filesystem: FakeFileSystem, *, exit_code: int = 0) -> None:
        self.filesystem = filesystem
        self.exit_code = exit_code
        self.calls: list[dict] = []

    def exec(self, command: str, *, cwd: str, env: dict, timeout: int):
        self.calls.append(
            {"command": command, "cwd": cwd, "env": env, "timeout": timeout}
        )
        if self.exit_code:
            return SimpleNamespace(exit_code=self.exit_code, result="synthetic worker failure")
        job = json.loads(self.filesystem.files[f"{cwd}/daytona_job.json"])
        result = train_policy(
            hazards_from_payload(job["hazards"]),
            seed=job["seed"],
            generations=job["generations"],
            population=job["population"],
            episodes_per_candidate=job["episodes_per_candidate"],
            max_steps=job["max_steps"],
            sandbox_id=job["sandbox_id"],
            invocation_id=job["invocation_id"],
            runtime_bundle_sha256=job["runtime_bundle_sha256"],
        )
        self.filesystem.files[f"{cwd}/daytona_result.json"] = json.dumps(
            result, sort_keys=True, allow_nan=False
        ).encode("utf-8")
        return SimpleNamespace(exit_code=0, result="training complete")


class FakeSandbox:
    def __init__(self, *, exit_code: int = 0, delete_error: Exception | None = None) -> None:
        self.id = SANDBOX_ID
        self.fs = FakeFileSystem()
        self.process = FakeProcess(self.fs, exit_code=exit_code)
        self.delete_error = delete_error
        self.delete_calls: list[tuple[int, bool]] = []

    def delete(self, *, timeout: int, wait: bool) -> None:
        self.delete_calls.append((timeout, wait))
        if self.delete_error is not None:
            raise self.delete_error


class FakeDaytonaClient:
    def __init__(self, sandbox: FakeSandbox) -> None:
        self.sandbox = sandbox
        self.create_calls: list[tuple[FakeCreateParams, int]] = []

    def create(self, params: FakeCreateParams, *, timeout: int) -> FakeSandbox:
        self.create_calls.append((params, timeout))
        return self.sandbox


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exit_code: int = 0,
    delete_error: Exception | None = None,
) -> tuple[FakeDaytonaClient, FakeSandbox]:
    sandbox = FakeSandbox(exit_code=exit_code, delete_error=delete_error)
    client = FakeDaytonaClient(sandbox)
    monkeypatch.setattr(daytona_rl, "_require_daytona", lambda: None)
    monkeypatch.setattr(daytona_rl, "Daytona", lambda: client)
    monkeypatch.setattr(daytona_rl, "CreateSandboxFromSnapshotParams", FakeCreateParams)
    monkeypatch.setattr(
        daytona_rl,
        "_capture_runtime_bundle",
        lambda: (
            {"rl_core.py": b"frozen core", "daytona_rl_worker.py": b"frozen worker"},
            BUNDLE_SHA256,
        ),
    )
    return client, sandbox


def test_fake_daytona_lifecycle_creates_runs_validates_and_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sandbox = _install_fake_sdk(monkeypatch)
    events: list[dict] = []

    returned = run_daytona_training(
        default_hazards(),
        seed=SEED,
        generations=GENERATIONS,
        population=POPULATION,
        episodes_per_candidate=EPISODES,
        max_steps=MAX_STEPS,
        event_callback=events.append,
        invocation_id=INVOCATION_ID,
    )

    assert len(client.create_calls) == 1
    params, create_timeout = client.create_calls[0]
    assert create_timeout == daytona_rl.CREATE_TIMEOUT_SECONDS
    assert params.kwargs["public"] is False
    assert params.kwargs["ephemeral"] is True
    assert params.kwargs["network_block_all"] is True
    assert params.kwargs["name"] == daytona_rl._sandbox_name(INVOCATION_ID)
    assert params.kwargs["name"] == "uk-orbit-guard-fixture-run-"
    assert params.kwargs["labels"]["run_id"] == INVOCATION_ID
    assert sandbox.delete_calls == [(daytona_rl.DELETE_TIMEOUT_SECONDS, True)]
    assert sandbox.process.calls[0]["command"] == daytona_rl.WORKER_COMMAND
    assert sandbox.process.calls[0]["env"] == {"PYTHONUNBUFFERED": "1"}
    remote_dir = f"{daytona_rl.REMOTE_BASE}/{INVOCATION_ID}"
    assert sandbox.fs.created_folders == [
        (daytona_rl.REMOTE_BASE, "755", 60),
        (remote_dir, "755", 60),
    ]
    assert sandbox.fs.downloads == [
        (f"{remote_dir}/daytona_result.json", 60)
    ]
    assert sandbox.fs.info_requests == [
        (f"{remote_dir}/daytona_result.json", 30)
    ]
    uploaded_job = json.loads(sandbox.fs.files[f"{remote_dir}/daytona_job.json"])
    assert uploaded_job["scenario_sha256"] == scenario_fingerprint(
        default_hazards(), MAX_STEPS
    )
    assert uploaded_job["synthetic"] is True
    assert uploaded_job["operational_use"] is False
    assert uploaded_job["human_authority_required"] is True
    assert uploaded_job["sandbox_id"] == SANDBOX_ID
    assert uploaded_job["runtime_bundle_sha256"] == BUNDLE_SHA256
    assert [event["state"] for event in events] == [
        "CREATING",
        "LIVE",
        "TRAINING",
        "VALIDATING",
        "RESULT_COLLECTED",
        "CLEANED",
    ]
    assert returned["scenario_sha256"] == scenario_fingerprint(
        default_hazards(), MAX_STEPS
    )
    assert returned["hazards"] == hazards_to_payload(default_hazards())
    assert returned["daytona_execution"] == {
        "sandbox_id": SANDBOX_ID,
        "invocation_id": INVOCATION_ID,
        "runtime_bundle_sha256": BUNDLE_SHA256,
        "result_validated": True,
        "sandbox_deleted": True,
        "local_training_fallback_used": False,
    }


def test_uploaded_worker_measures_its_own_runtime_bundle(
    tmp_path: Path,
) -> None:
    runtime_files, bundle_sha256 = daytona_rl._capture_runtime_bundle()
    for name, content in runtime_files.items():
        (tmp_path / name).write_bytes(content)
    job = {
        "schema_version": 1,
        "invocation_id": INVOCATION_ID,
        "sandbox_id": SANDBOX_ID,
        "runtime_bundle_sha256": bundle_sha256,
        "model_version": daytona_rl.MODEL_VERSION,
        "scenario_sha256": scenario_fingerprint(default_hazards(), MAX_STEPS),
        "hazards": hazards_to_payload(default_hazards()),
        "seed": SEED,
        "generations": GENERATIONS,
        "population": POPULATION,
        "episodes_per_candidate": EPISODES,
        "max_steps": MAX_STEPS,
        "synthetic": True,
        "operational_use": False,
        "human_authority_required": True,
    }
    job_path = tmp_path / "daytona_job.json"
    output_path = tmp_path / "daytona_result.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    command = [
        sys.executable,
        str(tmp_path / "daytona_rl_worker.py"),
        "--job",
        str(job_path),
        "--output",
        str(output_path),
    ]

    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    returned = json.loads(output_path.read_text(encoding="utf-8"))
    assert returned["runtime_bundle_sha256"] == bundle_sha256
    validate_training_result(
        returned,
        expected_sandbox_id=SANDBOX_ID,
        expected_invocation_id=INVOCATION_ID,
        expected_runtime_bundle_sha256=bundle_sha256,
        expected_seed=SEED,
        expected_scenario_sha256=job["scenario_sha256"],
        expected_hazards=job["hazards"],
        expected_generations=GENERATIONS,
        expected_population=POPULATION,
        expected_episodes_per_candidate=EPISODES,
        expected_max_steps=MAX_STEPS,
    )

    (tmp_path / "rl_core.py").write_bytes(
        runtime_files["rl_core.py"] + b"\n# modified after host digest\n"
    )
    output_path.unlink()
    rejected = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert rejected.returncode == 2
    assert "uploaded runtime bundle does not match" in rejected.stderr
    assert not output_path.exists()


def test_sandbox_name_is_derived_from_unique_invocation_suffix() -> None:
    first = daytona_rl._sandbox_name("orbitguard-aaaaaaaaaaaa-one")
    second = daytona_rl._sandbox_name("orbitguard-bbbbbbbbbbbb-two")

    assert first == "uk-orbit-guard-aaaaaaaaaaaa"
    assert second == "uk-orbit-guard-bbbbbbbbbbbb"
    assert first != second


def test_generated_invocations_produce_distinct_sandbox_names() -> None:
    first = daytona_rl._sandbox_name("orbitguard-11111111-aaaa")
    second = daytona_rl._sandbox_name("orbitguard-22222222-bbbb")

    assert first == "uk-orbit-guard-11111111-aaa"
    assert second == "uk-orbit-guard-22222222-bbb"
    assert first != second


def test_worker_failure_still_deletes_sandbox_and_never_falls_back_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sandbox = _install_fake_sdk(monkeypatch, exit_code=7)
    events: list[dict] = []

    with pytest.raises(DaytonaRLExecutionError, match="worker exited with code 7"):
        run_daytona_training(
            default_hazards(),
            generations=GENERATIONS,
            population=POPULATION,
            episodes_per_candidate=EPISODES,
            max_steps=MAX_STEPS,
            event_callback=events.append,
            invocation_id="worker-failure",
        )

    assert sandbox.delete_calls == [(daytona_rl.DELETE_TIMEOUT_SECONDS, True)]
    assert [event["state"] for event in events][-2:] == ["FAILED", "CLEANED"]
    assert f"{daytona_rl.REMOTE_BASE}/worker-failure/daytona_result.json" not in sandbox.fs.files


def test_successful_result_fails_closed_when_sandbox_deletion_is_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sandbox = _install_fake_sdk(
        monkeypatch, delete_error=RuntimeError("delete confirmation timeout")
    )

    with pytest.raises(DaytonaRLExecutionError, match="deletion was not confirmed"):
        run_daytona_training(
            default_hazards(),
            generations=GENERATIONS,
            population=POPULATION,
            episodes_per_candidate=EPISODES,
            max_steps=MAX_STEPS,
            invocation_id="cleanup-failure",
        )

    assert sandbox.delete_calls == [(daytona_rl.DELETE_TIMEOUT_SECONDS, True)]


def test_oversized_sandbox_result_is_rejected_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sandbox = _install_fake_sdk(monkeypatch)
    monkeypatch.setattr(
        sandbox.fs,
        "get_file_info",
        lambda path, request_timeout=None: SimpleNamespace(
            size=daytona_rl.MAX_RESULT_BYTES + 1
        ),
    )

    with pytest.raises(DaytonaRLExecutionError, match="10 MB bound"):
        run_daytona_training(
            default_hazards(),
            generations=GENERATIONS,
            population=POPULATION,
            episodes_per_candidate=EPISODES,
            max_steps=MAX_STEPS,
            invocation_id="oversized-result",
        )

    assert sandbox.fs.downloads == []
    assert sandbox.delete_calls == [(daytona_rl.DELETE_TIMEOUT_SECONDS, True)]


def test_invalid_download_is_rejected_and_sandbox_is_still_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sandbox = _install_fake_sdk(monkeypatch)

    def write_invalid_result(command: str, *, cwd: str, env: dict, timeout: int):
        sandbox.fs.files[f"{cwd}/daytona_result.json"] = b"{not-json"
        return SimpleNamespace(exit_code=0, result="claimed success")

    monkeypatch.setattr(sandbox.process, "exec", write_invalid_result)

    with pytest.raises(DaytonaRLExecutionError, match="not valid JSON"):
        run_daytona_training(
            default_hazards(),
            generations=GENERATIONS,
            population=POPULATION,
            episodes_per_candidate=EPISODES,
            max_steps=MAX_STEPS,
            invocation_id="invalid-download",
        )

    assert sandbox.delete_calls == [(daytona_rl.DELETE_TIMEOUT_SECONDS, True)]


def test_callback_failure_after_creation_fails_closed_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sandbox = _install_fake_sdk(monkeypatch)

    def callback(event: dict) -> None:
        if event["state"] == "VALIDATING":
            raise RuntimeError("state sink unavailable")

    with pytest.raises(DaytonaRLExecutionError, match="state sink unavailable"):
        run_daytona_training(
            default_hazards(),
            generations=GENERATIONS,
            population=POPULATION,
            episodes_per_candidate=EPISODES,
            max_steps=MAX_STEPS,
            event_callback=callback,
            invocation_id="callback-failure",
        )

    assert sandbox.delete_calls == [(daytona_rl.DELETE_TIMEOUT_SECONDS, True)]


@pytest.mark.parametrize("invocation_id", ["", "spaces not allowed", "!bad", "x" * 81])
def test_invalid_invocation_id_is_rejected_before_sandbox_creation(
    monkeypatch: pytest.MonkeyPatch, invocation_id: str
) -> None:
    client, _ = _install_fake_sdk(monkeypatch)

    with pytest.raises(ValueError, match="invocation_id"):
        run_daytona_training(default_hazards(), invocation_id=invocation_id)

    assert client.create_calls == []
