from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_streamlit_app_renders_all_judge_views_without_exception() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "01  ALERT",
        "02  MANOEUVRE OPTIONS",
        "03  COMMITTEE BRIEF",
    ]
    assert [button.label for button in app.button] == [
        "▶  RUN DETERMINISTIC SCENARIO",
        "↺  RESTORE JUDGE SCENARIO",
    ]
    assert len(app.get("download_button")) == 2

    app.button[0].click().run()
    assert not app.exception
    assert "integrity verified" in app.success[0].value
    assert "human-approval guards passed" in app.success[0].value
    assert "No network or API call was made" in app.success[0].value


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

    app.button[1].click().run()
    assert not app.exception
    assert app.radio[0].value == "Act now"
    assert app.slider[0].value == 45
    assert app.slider[1].value == 0.05
