from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest

from orbit_guard.demo import (
    DEFAULT_SCENARIO_PATH,
    assess_scenario,
    build_committee_brief,
    build_record,
    validate_demo,
)
from orbit_guard.scenario_io import load_scenario, scenario_sha256


def _record() -> dict[str, object]:
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    return build_record(
        scenario,
        assess_scenario(scenario),
        scenario_file_sha256=scenario_sha256(DEFAULT_SCENARIO_PATH),
    )


def test_reproducibility_record_keeps_integrity_guardrails() -> None:
    record = _record()
    validate_demo(record)

    assert record["synthetic"] is True
    assert record["operational_use"] is False
    assert record["human_operator_approval_required"] is True
    assert record["model"] == "local-linear-v0.1"
    assert record["seed"] == 42
    assert record["delay_penalty"] == pytest.approx(8.0)
    assert len(record["scenario_file_sha256"]) == 64
    assert all("probability" not in key.lower() for key in record)
    assert all(
        "probability" not in key.lower()
        for option in record["options"]
        for key in option
    )


def test_committee_brief_is_bounded_and_actionable() -> None:
    brief = build_committee_brief(_record())
    assert "NOT FOR FLIGHT OPERATIONS" in brief
    assert "8.0× the manoeuvre-budget demand" in brief
    assert "six hours divided by 45 minutes equals eight" in brief
    assert "not measured operational performance" in brief
    assert "NSpOC provides warning and" in brief
    assert "authorised operator's validated process and decision authority" in brief
    assert "proposed scrutiny metrics" in brief
    assert "collision-probability calculation" in brief


def test_cli_check_writes_fallback_artifacts(tmp_path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(DEFAULT_SCENARIO_PATH.parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "orbit_guard.demo",
            "--scenario",
            str(DEFAULT_SCENARIO_PATH),
            "--out-dir",
            str(tmp_path),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert "DEMO CHECK: PASS" in completed.stdout
    assert (tmp_path / "demo_result.json").is_file()
    assert (tmp_path / "committee_brief.md").is_file()

    record = json.loads((tmp_path / "demo_result.json").read_text(encoding="utf-8"))
    assert record["recommended_option_id"] == "act_now"
    assert record["delay_penalty"] == pytest.approx(8.0)


def test_scenario_schema_rejects_string_boolean_and_unknown_metadata(tmp_path) -> None:
    fixture = json.loads(DEFAULT_SCENARIO_PATH.read_text(encoding="utf-8"))
    invalid_boolean = deepcopy(fixture)
    invalid_boolean["synthetic"] = "false"
    invalid_path = tmp_path / "invalid_boolean.json"
    invalid_path.write_text(json.dumps(invalid_boolean), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON boolean"):
        load_scenario(invalid_path)

    unknown_metadata = deepcopy(fixture)
    unknown_metadata["assumptions"] = ["silently ignored"]
    invalid_path.write_text(json.dumps(unknown_metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected fields: assumptions"):
        load_scenario(invalid_path)
