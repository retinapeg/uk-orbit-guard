"""Execute one complete UK Orbit Guard RL training job in a Daytona sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from rl_core import (
    MODEL_VERSION,
    RESULT_VERSION,
    hazards_from_payload,
    scenario_fingerprint,
    train_policy,
)


JOB_FIELDS = frozenset(
    {
        "schema_version",
        "invocation_id",
        "sandbox_id",
        "runtime_bundle_sha256",
        "model_version",
        "scenario_sha256",
        "hazards",
        "seed",
        "generations",
        "population",
        "episodes_per_candidate",
        "max_steps",
        "synthetic",
        "operational_use",
        "human_authority_required",
    }
)


def execute_job(
    job: object,
    *,
    measured_runtime_bundle_sha256: str,
) -> dict:
    if not isinstance(job, dict):
        raise ValueError("job must be a JSON object")
    missing = sorted(JOB_FIELDS - frozenset(job))
    unexpected = sorted(frozenset(job) - JOB_FIELDS)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise ValueError("job schema mismatch (" + "; ".join(details) + ")")
    if job["schema_version"] != RESULT_VERSION:
        raise ValueError("unsupported job schema_version")
    if job["model_version"] != MODEL_VERSION:
        raise ValueError("job model_version does not match worker")
    if (
        job["synthetic"] is not True
        or job["operational_use"] is not False
        or job["human_authority_required"] is not True
    ):
        raise ValueError(
            "job must preserve the synthetic/non-operational/human-authority boundary"
        )
    sandbox_id = job.get("sandbox_id")
    if not isinstance(sandbox_id, str) or not sandbox_id.strip():
        raise ValueError("job requires the real Daytona sandbox_id")
    expected_bundle = job.get("runtime_bundle_sha256")
    if (
        not isinstance(expected_bundle, str)
        or len(expected_bundle) != 64
        or any(character not in "0123456789abcdef" for character in expected_bundle)
    ):
        raise ValueError("job runtime_bundle_sha256 is invalid")
    if measured_runtime_bundle_sha256 != expected_bundle:
        raise ValueError("uploaded runtime bundle does not match the frozen host digest")
    hazards = hazards_from_payload(job.get("hazards"))
    if scenario_fingerprint(hazards, job["max_steps"]) != job["scenario_sha256"]:
        raise ValueError("job scenario_sha256 does not match its payload")
    return train_policy(
        hazards,
        seed=job.get("seed", 42),
        generations=job.get("generations", 10),
        population=job.get("population", 24),
        episodes_per_candidate=job.get("episodes_per_candidate", 3),
        max_steps=job.get("max_steps", 72),
        sandbox_id=sandbox_id,
        invocation_id=job["invocation_id"],
        runtime_bundle_sha256=measured_runtime_bundle_sha256,
    )


def measure_runtime_bundle(directory: Path) -> str:
    """Hash the two uploaded runtime files inside the sandbox itself."""

    digest = hashlib.sha256()
    for name in ("daytona_rl_worker.py", "rl_core.py"):
        path = directory / name
        content = path.read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        with Path(args.job).open(encoding="utf-8") as handle:
            job = json.load(handle)
        runtime_directory = Path(args.job).resolve().parent
        result = execute_job(
            job,
            measured_runtime_bundle_sha256=measure_runtime_bundle(
                runtime_directory
            ),
        )
        with Path(args.output).open("w", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"DAYTONA RL WORKER FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
