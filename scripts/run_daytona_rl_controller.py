"""Background child process for one real UK Orbit Guard Daytona run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from orbit_guard.daytona_rl import run_daytona_training
from orbit_guard.rl_core import hazards_from_payload
from orbit_guard.training_controller import (
    copy_as_last_verified,
    release_active_lock,
    validate_completed_result,
    validate_request,
    write_live_state,
    write_result_envelope,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    request = None
    revision = 1
    last_sandbox_id = None

    def event_callback(event):
        nonlocal last_sandbox_id, revision
        revision += 1
        if isinstance(event.get("sandbox_id"), str) and event["sandbox_id"].strip():
            last_sandbox_id = event["sandbox_id"]
        write_live_state(
            args.state,
            {
                "schema_version": 1,
                "invocation_id": request["invocation_id"],
                "revision": revision,
                "state": event["state"],
                "message": event["message"],
                "sandbox_id": event.get("sandbox_id"),
                "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "pid": os.getpid(),
                "result_path": None,
                "error": None,
            },
        )

    try:
        request = validate_request(json.loads(args.request.read_text(encoding="utf-8")))
        result = run_daytona_training(
            hazards_from_payload(request["hazards"]),
            seed=request["seed"],
            generations=request["generations"],
            population=request["population"],
            episodes_per_candidate=request["episodes_per_candidate"],
            max_steps=request["max_steps"],
            event_callback=event_callback,
            invocation_id=request["invocation_id"],
        )
        validate_completed_result(result, request)
        write_result_envelope(args.result, result)
        copy_as_last_verified(result)
        revision += 1
        write_live_state(
            args.state,
            {
                "schema_version": 1,
                "invocation_id": request["invocation_id"],
                "revision": revision,
                "state": "COMPLETE",
                "message": "Verified Daytona run ready: generation 0 through final replay",
                "sandbox_id": result["daytona_execution"]["sandbox_id"],
                "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "pid": os.getpid(),
                "result_path": str(args.result),
                "error": None,
            },
        )
        return 0
    except Exception as exc:
        invocation_id = request["invocation_id"] if request else args.request.parent.name
        revision += 1
        write_live_state(
            args.state,
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "revision": revision,
                "state": "FAILED",
                "message": "Daytona run failed; no local result was substituted",
                "sandbox_id": last_sandbox_id,
                "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "pid": os.getpid(),
                "result_path": None,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        print(f"DAYTONA CONTROLLER FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        release_active_lock(request["invocation_id"] if request else args.request.parent.name)


if __name__ == "__main__":
    raise SystemExit(main())
