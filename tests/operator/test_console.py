"""The console app itself, run headless through Streamlit's own `AppTest`.

What is pinned here is what the operator has to be able to read off the
screen -- a stalled run reads as stalled, a finished one reads as finished,
and an explicit theme choice sticks -- not where any of it sits on the page.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import axial.operator.app as app_module

APP_PATH = Path(app_module.__file__)


def _open() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=30).run()


def test_the_sidebar_carries_the_axial_mark(finished_run: Path) -> None:
    """Issue #770: the operator console's sidebar and the analyst UI's own
    inline `<svg>` (`web/src/components/TopBar.tsx`) are the two readers of
    one canonical file (`axial_logo.svg`), not a copy each. `st.html()`
    sanitises `<svg>` out of the DOM entirely (verified against this
    Streamlit version) -- `st.markdown(..., unsafe_allow_html=True)` is the
    one of the two that actually renders it, which is what this pins."""
    at = _open()

    assert not at.exception
    rendered = at.sidebar.markdown[0].value
    assert "<svg" in rendered
    assert "axial-title" in rendered  # the canonical file's own <title id=…>
    assert "currentColor" in rendered  # ink follows the console's own palette


def test_the_sidebar_mark_falls_back_to_text_if_the_asset_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "_LOGO_SVG_PATH", Path("does-not-exist.svg"))

    rendered = app_module._axial_mark_html()

    assert "AXIAL" in rendered
    assert "<svg" not in rendered


def test_a_stalled_run_reads_as_check_this(stalled_run: Path) -> None:
    at = _open()

    assert not at.exception
    (band,) = at.warning
    assert "Stalled: quiet 20m" in band.value
    assert "nothing in flight" in band.value
    assert "Expected one every ~20s" in band.value
    assert "Silence is not health" in band.value


def test_a_finished_run_reads_as_finished_with_its_spend_and_concurrency(
    finished_run: Path,
) -> None:
    at = _open()

    assert not at.exception
    # No quiet band at all: a finished run is not silent, it is over.
    assert not at.warning
    stats = {metric.label: metric.value for metric in at.metric}
    assert stats["spent"] == "$1.25"
    assert stats["effective concurrency / 12"] == "2.0x"


def test_the_theme_starts_on_system_and_an_override_survives_a_rerun(
    finished_run: Path,
) -> None:
    at = _open()

    assert at.session_state["theme_choice"] == "System"
    assert at.session_state["resolved_theme"] == "light"  # no browser preference under AppTest

    at.segmented_control[0].set_value("Dark").run()
    assert at.session_state["resolved_theme"] == "dark"

    # A rerun driven by an unrelated widget must not reset it.
    at.sidebar.radio[0].set_value("Status").run()
    assert at.session_state["theme_choice"] == "Dark"
    assert at.session_state["resolved_theme"] == "dark"


@pytest.mark.parametrize(
    ("choice", "browser", "expected"),
    [
        ("System", "dark", "dark"),
        ("System", None, "light"),
        ("Light", "dark", "light"),
        ("Dark", "light", "dark"),
    ],
)
def test_system_defers_to_the_browser_and_an_explicit_choice_does_not(
    choice: str, browser: str | None, expected: str
) -> None:
    assert app_module.resolve_theme(choice, browser) == expected


def test_the_ingest_button_launches_detached_and_never_blocks_the_console(
    logs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr(
        app_module.cli_bridge,
        "launch_detached",
        lambda args: (launched.append(args), (321, logs_root / "console-launch.log"))[1],
    )

    at = _open()
    at.sidebar.radio[0].set_value("Sources and ingest").run()
    at.button(key="start_ingest").click().run()

    assert launched == [["sources"]]
    assert "pid 321" in at.success[0].value
