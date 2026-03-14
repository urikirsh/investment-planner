from __future__ import annotations

from collections.abc import Iterator
from typing import Callable
from pathlib import Path
import pytest

import portfolio_core.portfolio_session as session_mod
import ui.controllers.main_window_welcome as welcome_mod
from ui.main_window import MainWindow


def _mock_remembered_portfolio_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: Path | None,
    window: MainWindow | None = None,
) -> None:
    """Mock remembered-path lookup either globally or for a specific window."""
    if window is None:
        monkeypatch.setattr(session_mod.PortfolioSession, "get_remembered_portfolio_path", lambda _self: path)
        return
    monkeypatch.setattr(window.session, "get_remembered_portfolio_path", lambda: path)


def _run_welcome_transition_immediately(monkeypatch: pytest.MonkeyPatch, window: MainWindow) -> None:
    monkeypatch.setattr(window._welcome_controller, "_schedule_main_screen_transition", window._welcome_controller._complete_startup_transition_to_main)


@pytest.fixture()
def window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[MainWindow]:
    _ = qapp
    _mock_remembered_portfolio_path(monkeypatch, path=None)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    yield win
    win.close()


def test_welcome_screen_shows_when_no_recent_portfolio(window: MainWindow) -> None:
    assert window.stack.currentWidget() is window.screen_welcome
    assert not window.screen_welcome.open_last_btn.isEnabled()
    assert window.screen_welcome.last_path_label.text() == "No recent portfolio"


def test_build_welcome_last_portfolio_status_for_none_path(window: MainWindow) -> None:
    status = window._build_welcome_last_portfolio_status(None)

    assert status.button_enabled is False
    assert status.path_text == "No recent portfolio"
    assert status.path_tooltip == ""
    assert status.missing_path is False


def test_build_welcome_last_portfolio_status_for_missing_path(window: MainWindow, tmp_path) -> None:
    missing_path = tmp_path / "missing.json"
    status = window._build_welcome_last_portfolio_status(missing_path)

    assert status.button_enabled is False
    assert status.path_tooltip == str(missing_path)
    assert status.missing_path is True
    assert status.path_text.endswith("(Not found)")


def test_build_welcome_last_portfolio_status_for_existing_path(window: MainWindow, tmp_path) -> None:
    existing_path = tmp_path / "existing.json"
    existing_path.write_text("{}", encoding="utf-8")
    status = window._build_welcome_last_portfolio_status(existing_path)

    assert status.button_enabled is True
    assert status.path_tooltip == str(existing_path)
    assert status.missing_path is False
    assert status.path_text.startswith("Last portfolio: ")
    assert "(Not found)" not in status.path_text


def test_welcome_screen_marks_missing_recent_portfolio_in_red(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = qapp
    missing_path = tmp_path / "missing.json"
    _mock_remembered_portfolio_path(monkeypatch, path=missing_path)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    try:
        assert not win.screen_welcome.open_last_btn.isEnabled()
        assert "Not found" in win.screen_welcome.last_path_label.text()
        assert "b00020" in win.screen_welcome.last_path_label.styleSheet()
    finally:
        win.close()


def test_welcome_open_last_transitions_to_main_on_success(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    remembered_path = tmp_path / "remembered.json"
    remembered_path.write_text("{}", encoding="utf-8")
    seen_paths: list[Path] = []

    def fake_open_portfolio(path: Path) -> bool:
        seen_paths.append(path)
        return True

    _mock_remembered_portfolio_path(monkeypatch, path=remembered_path, window=window)
    monkeypatch.setattr(window, "_open_portfolio_from_path", fake_open_portfolio)
    seed_session_usd_ils_cache(window)
    _run_welcome_transition_immediately(monkeypatch, window)

    window._on_welcome_open_last_clicked()

    assert seen_paths == [remembered_path]
    assert window.stack.currentWidget() is window.screen_main


def test_welcome_open_last_stays_on_welcome_when_open_fails(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    remembered_path = tmp_path / "remembered.json"
    remembered_path.write_text("{}", encoding="utf-8")

    _mock_remembered_portfolio_path(monkeypatch, path=remembered_path, window=window)
    monkeypatch.setattr(window, "_open_portfolio_from_path", lambda _path: False)

    window._on_welcome_open_last_clicked()

    assert window.stack.currentWidget() is window.screen_welcome
    assert window.screen_welcome.open_last_btn.isEnabled()
    assert "Last portfolio:" in window.screen_welcome.last_path_label.text()


def test_welcome_load_different_keeps_welcome_screen_on_cancel(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window, "_open_portfolio_from_picker", lambda: False)

    window._on_welcome_load_different_clicked()

    assert window.stack.currentWidget() is window.screen_welcome


def test_welcome_start_new_loads_default_and_enters_main(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    seed_session_usd_ils_cache(window)
    _run_welcome_transition_immediately(monkeypatch, window)
    window._on_welcome_start_new_clicked()

    assert window.stack.currentWidget() is window.screen_main
    assert window.session.current_file_path is None
    assert window.tree.topLevelItemCount() > 0


def test_welcome_success_action_shows_overlay_before_delayed_main_transition(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    seed_session_usd_ils_cache(window)
    scheduled: list[bool] = []
    monkeypatch.setattr(window._welcome_controller, "_schedule_main_screen_transition", lambda: scheduled.append(True))

    window._on_welcome_start_new_clicked()

    assert scheduled
    assert window.stack.currentWidget() is window.screen_welcome
    assert not window._startup_loading_overlay.isHidden()
    assert not window.stack.isEnabled()

    window._welcome_controller._complete_startup_transition_to_main()

    assert window.stack.currentWidget() is window.screen_main
    assert window._startup_loading_overlay.isHidden()
    assert window.stack.isEnabled()


def test_close_during_startup_transition_hides_overlay_immediately(
    window: MainWindow,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    seed_session_usd_ils_cache(window)
    window._on_welcome_start_new_clicked()

    assert not window._startup_loading_overlay.isHidden()
    assert not window.stack.isEnabled()
    assert window._welcome_controller._startup_transition_timer.isActive()

    window.close()

    assert window._startup_loading_overlay.isHidden()
    assert not window._welcome_controller._startup_transition_timer.isActive()


def test_welcome_fetch_failure_shows_back_dialog_and_keeps_welcome(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[tuple[str, str]] = []

    def fake_start_fetch() -> None:
        window._welcome_controller._startup_transition.fx_fetch_error = "Failed to fetch USD to ILS exchange rate."
        window._welcome_controller._startup_transition.fx_fetch_completed = True
        window._welcome_controller._try_finalize_startup_transition()

    monkeypatch.setattr(window._welcome_controller, "_start_startup_fx_fetch", fake_start_fetch)
    monkeypatch.setattr(
        welcome_mod,
        "show_error_with_back",
        lambda _parent, title, message: shown.append((title, message)),
    )
    _run_welcome_transition_immediately(monkeypatch, window)

    window._on_welcome_start_new_clicked()

    assert shown == [("Exchange rate fetch failed", "Failed to fetch USD to ILS exchange rate.")]
    assert window.stack.currentWidget() is window.screen_welcome
    assert window._startup_loading_overlay.isHidden()


def test_welcome_start_action_aborts_when_previous_startup_fx_cleanup_cannot_finish(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown_calls = 0
    cancel_calls = 0

    def fake_cancel_startup_fx_fetch(**_kwargs: object) -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        return cancel_calls != 1

    def fake_show_cleanup_in_progress(_parent: object, *, action_verb: str = "closing") -> None:
        _ = action_verb
        nonlocal shown_calls
        shown_calls += 1

    monkeypatch.setattr(window._welcome_controller, "_cancel_startup_fx_fetch", fake_cancel_startup_fx_fetch)
    monkeypatch.setattr(
        welcome_mod,
        "show_cleanup_in_progress",
        fake_show_cleanup_in_progress,
    )

    window._on_welcome_start_new_clicked()

    assert shown_calls == 1
    assert window.stack.currentWidget() is window.screen_welcome
    assert window._startup_loading_overlay.isHidden()
    assert not window._welcome_controller._startup_transition_timer.isActive()
