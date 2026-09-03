from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_streamlit_app_renders_all_judge_views_without_exception() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "00  PUBLIC ORBIT PICTURE",
        "01  SYNTHETIC ALERT",
        "02  MANOEUVRE OPTIONS",
        "03  COMMITTEE BRIEF",
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
    app.slider[0].set_value(180).run()
    app.slider[1].set_value(0.25).run()
    assert app.slider[0].value == 180
    assert app.slider[1].value == 0.25

    reset_button = next(
        button for button in app.button if button.label == "↺  RESTORE JUDGE SCENARIO"
    )
    reset_button.click().run()
    assert not app.exception
    assert app.radio[0].value == "Act now"
    assert app.slider[0].value == 45
    assert app.slider[1].value == 0.05


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
