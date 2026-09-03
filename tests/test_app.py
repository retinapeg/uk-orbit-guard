from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from orbit_guard import training_controller
from orbit_guard.rl_core import (
    DEFAULT_STEPS,
    MODEL_VERSION,
    RESULT_VERSION,
    default_hazards,
    hazards_to_payload,
    scenario_fingerprint,
    train_policy,
)


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _button(app: AppTest, label: str):
    matches = [button for button in app.button if button.label == label]
    assert len(matches) == 1, f"expected one button labelled {label!r}, got {len(matches)}"
    return matches[0]


def _slider(app: AppTest, label: str):
    matches = [slider for slider in app.slider if slider.label == label]
    assert len(matches) == 1, f"expected one slider labelled {label!r}, got {len(matches)}"
    return matches[0]


def _controller_request(invocation_id: str) -> dict[str, object]:
    hazards = default_hazards()
    return {
        "schema_version": RESULT_VERSION,
        "invocation_id": invocation_id,
        "model_version": MODEL_VERSION,
        "scenario_sha256": scenario_fingerprint(hazards, DEFAULT_STEPS),
        "hazards": hazards_to_payload(hazards),
        "seed": 42,
        "generations": 10,
        "population": 24,
        "episodes_per_candidate": 3,
        "max_steps": DEFAULT_STEPS,
        "synthetic": True,
        "operational_use": False,
        "human_authority_required": True,
    }


def _configure_controller_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(training_controller, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(training_controller, "ACTIVE_LOCK", tmp_path / "active.json")
    monkeypatch.setattr(
        training_controller, "LAST_VERIFIED", tmp_path / "last_verified.json"
    )


def _recorded_result(invocation_id: str = "orbitguard-recorded-run") -> dict:
    sandbox_id = "sandbox-recorded-run"
    bundle_sha256 = "a" * 64
    worker = train_policy(
        default_hazards(),
        seed=42,
        generations=10,
        population=24,
        episodes_per_candidate=3,
        max_steps=DEFAULT_STEPS,
        sandbox_id=sandbox_id,
        invocation_id=invocation_id,
        runtime_bundle_sha256=bundle_sha256,
    )
    return {
        **worker,
        "daytona_execution": {
            "sandbox_id": sandbox_id,
            "invocation_id": invocation_id,
            "runtime_bundle_sha256": bundle_sha256,
            "result_validated": True,
            "sandbox_deleted": True,
            "local_training_fallback_used": False,
        },
    }


def test_streamlit_app_renders_all_judge_views_without_exception() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "00  SPACE COMMAND",
        "01  PUBLIC ORBIT PICTURE",
        "02  SYNTHETIC ALERT",
        "03  MANOEUVRE OPTIONS",
        "04  COMMITTEE BRIEF",
    ]
    button_by_label = {button.label: button for button in app.button}
    assert "↻  REFRESH PUBLIC DATA IF DUE" in button_by_label
    assert "▶  RUN DETERMINISTIC SCENARIO" in button_by_label
    assert "↺  RESTORE JUDGE SCENARIO" in button_by_label
    download_labels = {button.label for button in app.get("download_button")}
    assert "↓  DOWNLOAD PUBLIC SNAPSHOT RECORD" in download_labels
    assert "↓  DOWNLOAD COMMITTEE BRIEF" in download_labels
    assert "↓  DOWNLOAD EVIDENCE RECORD" in download_labels
    rendered_markdown = "\n".join(str(item.value) for item in app.markdown)
    assert "PUBLIC SCREEN ENDS HERE" in rendered_markdown
    assert "SYNTHETIC OFFLINE FIXTURE" in rendered_markdown
    assert "SEPARATE FROM ALL PUBLIC OBJECTS" in rendered_markdown
    rendered_captions = "\n".join(str(item.value) for item in app.caption)
    assert "Offline cache-first default" in rendered_captions

    button_by_label["▶  RUN DETERMINISTIC SCENARIO"].click().run()
    assert not app.exception
    assert "integrity verified" in app.success[0].value
    assert "human-approval guards passed" in app.success[0].value
    assert "No network or API call was made" in app.success[0].value


def test_public_proximity_view_names_its_source_time_origin() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()

    app.get("button_group")[0].set_value("Proximity screen").run()

    assert not app.exception
    rendered_captions = "\n".join(str(item.value) for item in app.caption)
    assert "SOCRATES source as-of 02 Sep 2026" in rendered_captions


def test_all_fixed_options_rerender_cleanly() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    for label in ("Hold course", "Act now", "Wait: same burn", "Wait: recover margin"):
        app.radio[0].set_value(label).run()
        assert not app.exception
        assert app.radio[0].value == label


def test_custom_controls_and_judge_reset_restore_known_state() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    app.radio[0].set_value("Wait: recover margin").run()
    _slider(app, "Actionable warning lead time").set_value(180).run()
    _slider(app, "Cross-track manoeuvre demand").set_value(0.25).run()
    assert _slider(app, "Actionable warning lead time").value == 180
    assert _slider(app, "Cross-track manoeuvre demand").value == 0.25

    reset_button = next(
        button for button in app.button if button.label == "↺  RESTORE JUDGE SCENARIO"
    )
    reset_button.click().run()
    assert not app.exception
    assert app.radio[0].value == "Act now"
    assert _slider(app, "Actionable warning lead time").value == 45
    assert _slider(app, "Cross-track manoeuvre demand").value == 0.05


def test_space_command_keeps_live_training_locked_without_a_credential(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()

    assert not app.exception
    training = _button(app, "▶ TRAIN GEN 0 → 10 ON DAYTONA")
    assert training.disabled is True
    assert any("no local training result is presented as Daytona" in item.value for item in app.warning)
    captions = "\n".join(str(item.value) for item in app.caption)
    assert "Synthetic local encounter geometry" in captions
    assert "not an Earth-centred ephemeris" in captions


def test_space_command_injection_changes_the_visible_frozen_scenario() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    before = "\n".join(str(item.value) for item in app.markdown)

    _button(app, "＋ CROSSING OBJECT").click().run()

    assert not app.exception
    after = "\n".join(str(item.value) for item in app.markdown)
    assert "X-02 · CROSSING" in after
    assert after != before


def test_failed_public_refresh_cooldown_disables_repeat_attempt() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    app.session_state.public_refresh_blocked_until = datetime.now(
        timezone.utc
    ) + timedelta(hours=1)

    app.run()

    refresh_button = next(
        button
        for button in app.button
        if button.label == "↻  REFRESH PUBLIC DATA IF DUE"
    )
    assert refresh_button.disabled is True
    assert any("refresh is paused" in info.value for info in app.info)


def test_corrupt_active_request_withholds_all_synthetic_policy_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_controller_paths(monkeypatch, tmp_path)
    invocation_id = "orbitguard-corrupt-request"
    run_dir = tmp_path / invocation_id
    run_dir.mkdir()
    (run_dir / "request.json").write_text("{not-json", encoding="utf-8")
    (run_dir / "live_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "revision": 4,
                "state": "TRAINING",
                "message": "remote episodes running",
                "sandbox_id": "sandbox-corrupt-request",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "result_path": None,
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=20)
    app.session_state.rl_run_handle = {
        "invocation_id": invocation_id,
        "run_dir": str(run_dir),
    }
    app.session_state.rl_reattach_error = None
    app.run()

    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "INCOHERENT ACTIVE RUN" in rendered
    assert "Synthetic evidence withheld" in rendered
    assert "SCENARIO DISPLAY WITHHELD" in rendered
    assert not any(metric.label == "MIN SIMULATED CLEARANCE" for metric in app.metric)
    assert not any(slider.label.startswith("POLICY GENERATION") for slider in app.slider)


def test_failed_daytona_run_takes_priority_over_ready_state(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_controller_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("DAYTONA_API_KEY", "ui-state-test-only")
    invocation_id = "orbitguard-failed-run"
    run_dir = tmp_path / invocation_id
    run_dir.mkdir()
    (run_dir / "request.json").write_text(
        json.dumps(_controller_request(invocation_id)), encoding="utf-8"
    )
    (run_dir / "live_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "revision": 8,
                "state": "FAILED",
                "message": "Daytona run failed; no local result was substituted",
                "sandbox_id": "sandbox-failed-run",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "result_path": None,
                "error": "remote worker exited before returning evidence",
            }
        ),
        encoding="utf-8",
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=20)
    app.session_state.rl_run_handle = {
        "invocation_id": invocation_id,
        "run_dir": str(run_dir),
    }
    app.session_state.rl_reattach_error = None
    app.run()

    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "DAYTONA FAILED" in rendered
    assert "NO RESULT ACCEPTED · NO LOCAL TRAINING SUBSTITUTED" in rendered
    assert "DAYTONA READY" not in rendered


def test_loading_recorded_replay_detaches_terminal_failed_run(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_controller_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("DAYTONA_API_KEY", "ui-state-test-only")
    invocation_id = "orbitguard-failed-before-replay"
    run_dir = tmp_path / invocation_id
    run_dir.mkdir()
    (run_dir / "request.json").write_text(
        json.dumps(_controller_request(invocation_id)), encoding="utf-8"
    )
    (run_dir / "live_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "invocation_id": invocation_id,
                "revision": 8,
                "state": "FAILED",
                "message": "Daytona run failed; no local result was substituted",
                "sandbox_id": "sandbox-failed-before-replay",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "result_path": None,
                "error": "remote worker returned no acceptable evidence",
            }
        ),
        encoding="utf-8",
    )
    training_controller.write_result_envelope(
        training_controller.LAST_VERIFIED, _recorded_result()
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=20)
    app.session_state.rl_run_handle = {
        "invocation_id": invocation_id,
        "run_dir": str(run_dir),
    }
    app.session_state.rl_reattach_error = None
    app.run()

    _button(app, "↻ LOAD LAST VERIFIED REPLAY").click().run()

    assert not app.exception
    rendered = "\n".join(str(item.value) for item in app.markdown)
    assert "RECORDED DAYTONA REPLAY" in rendered
    assert "VALIDATED PRIOR RUN · NOT CURRENT LIVE COMPUTE" in rendered
    assert "DAYTONA FAILED" not in rendered
    assert app.session_state.rl_run_handle is None
    assert app.session_state.rl_hazards == default_hazards()
