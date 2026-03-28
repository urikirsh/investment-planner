from __future__ import annotations

from collections.abc import Iterator
from typing import Callable
from pathlib import Path
import pytest

from portfolio_core.domain.models import Portfolio
from portfolio_core.io_json import load_portfolio
import portfolio_core.session.portfolio_session as session_mod
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


def _complete_startup_fetch_successfully(monkeypatch: pytest.MonkeyPatch, window: MainWindow) -> None:
    def fake_start_fetch() -> None:
        window._welcome_controller._startup_transition.fx_fetch_error = None
        window._welcome_controller._startup_transition.fx_fetch_completed = True
        window._welcome_controller._try_finalize_startup_transition()

    monkeypatch.setattr(window._welcome_controller, "_start_startup_fx_fetch", fake_start_fetch)


def _make_staged_portfolio() -> Portfolio:
    return load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "Group", "targetPercentage": "100"}],
            "instruments": [
                {
                    "id": "i1",
                    "ticker": "1234567",
                    "name": "ETF",
                    "quantity": 1,
                    "value": "100",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                }
            ],
        }
    )


@pytest.fixture()
def window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[MainWindow]:
    _ = qapp
    _mock_remembered_portfolio_path(monkeypatch, path=None)
    win = MainWindow(
        json_path=str(tmp_path / "portfolio.json"),
        config_path=tmp_path / "config.json",
    )
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
    win = MainWindow(
        json_path=str(tmp_path / "portfolio.json"),
        config_path=tmp_path / "config.json",
    )
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
    staged_portfolio = _make_staged_portfolio()

    def fake_prepare_portfolio(path: Path) -> bool:
        seen_paths.append(path)
        window._welcome_controller._pending_startup_portfolio = welcome_mod._PendingStartupPortfolio(
            portfolio=staged_portfolio,
            file_path=path,
        )
        return True

    _mock_remembered_portfolio_path(monkeypatch, path=remembered_path, window=window)
    monkeypatch.setattr(window._welcome_controller, "_prepare_portfolio_from_path", fake_prepare_portfolio)
    seed_session_usd_ils_cache(window)
    _run_welcome_transition_immediately(monkeypatch, window)
    monkeypatch.setattr(
        window._welcome_controller,
        "_start_startup_fx_fetch",
        lambda: window._welcome_controller._on_startup_fx_fetch_finished(None, staged_portfolio, None),
    )

    window._on_welcome_open_last_clicked()

    assert seen_paths == [remembered_path]
    assert window.stack.currentWidget() is window.screen_main


def test_welcome_open_last_stays_on_welcome_when_open_fails(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    remembered_path = tmp_path / "remembered.json"
    remembered_path.write_text("{}", encoding="utf-8")
    shown: list[tuple[str, str]] = []

    _mock_remembered_portfolio_path(monkeypatch, path=remembered_path, window=window)
    monkeypatch.setattr(
        window._welcome_controller,
        "_prepare_portfolio_from_path",
        lambda _path: False,
    )
    monkeypatch.setattr(
        welcome_mod,
        "show_error_with_back",
        lambda _parent, title, message: shown.append((title, message)),
    )

    window._on_welcome_open_last_clicked()

    assert shown == []
    assert window.stack.currentWidget() is window.screen_welcome
    assert window.screen_welcome.open_last_btn.isEnabled()
    assert "Last portfolio:" in window.screen_welcome.last_path_label.text()


def test_welcome_open_last_shows_modal_with_prepare_error_details(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    remembered_path = tmp_path / "remembered.json"
    remembered_path.write_text("{}", encoding="utf-8")
    shown: list[tuple[str, str]] = []

    def fake_prepare_portfolio(_path: Path) -> bool:
        window._welcome_controller._last_prepare_error_message = "Missing or invalid 'cash' object"
        return False

    _mock_remembered_portfolio_path(monkeypatch, path=remembered_path, window=window)
    monkeypatch.setattr(window._welcome_controller, "_prepare_portfolio_from_path", fake_prepare_portfolio)
    monkeypatch.setattr(
        welcome_mod,
        "show_error_with_back",
        lambda _parent, title, message: shown.append((title, message)),
    )

    window._on_welcome_open_last_clicked()

    assert shown == [("Load failed", "Missing or invalid 'cash' object")]
    assert window.stack.currentWidget() is window.screen_welcome


def test_welcome_load_different_keeps_welcome_screen_on_cancel(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window, "_prompt_select_open_path", lambda: None)

    window._on_welcome_load_different_clicked()

    assert window.stack.currentWidget() is window.screen_welcome


def test_welcome_load_different_shows_modal_with_prepare_error_details(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    selected_path = tmp_path / "broken.json"
    selected_path.write_text("{}", encoding="utf-8")
    shown: list[tuple[str, str]] = []

    def fake_prepare_portfolio(_path: Path) -> bool:
        window._welcome_controller._last_prepare_error_message = "Missing or invalid 'cash' object"
        return False

    monkeypatch.setattr(window, "_prompt_select_open_path", lambda: selected_path)
    monkeypatch.setattr(window._welcome_controller, "_prepare_portfolio_from_path", fake_prepare_portfolio)
    monkeypatch.setattr(
        welcome_mod,
        "show_error_with_back",
        lambda _parent, title, message: shown.append((title, message)),
    )

    window._on_welcome_load_different_clicked()

    assert shown == [("Load failed", "Missing or invalid 'cash' object")]
    assert window.stack.currentWidget() is window.screen_welcome


def test_welcome_start_new_loads_default_and_enters_main(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    seed_session_usd_ils_cache(window)
    _run_welcome_transition_immediately(monkeypatch, window)
    monkeypatch.setattr(window._welcome_controller, "_start_startup_fx_fetch", lambda: None)
    window._on_welcome_start_new_clicked()
    pending = window._welcome_controller._pending_startup_portfolio
    assert pending is not None
    window._welcome_controller._on_startup_fx_fetch_finished(None, pending.portfolio, None)

    assert window.stack.currentWidget() is window.screen_main
    assert window.session.current_file_path is None
    assert window.tree.topLevelItemCount() > 0


def test_welcome_open_last_updates_total_label_from_refreshed_portfolio(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    remembered_path = tmp_path / "remembered.json"
    remembered_path.write_text("{}", encoding="utf-8")
    staged_portfolio = _make_staged_portfolio()
    refreshed_portfolio = load_portfolio(
        {
            "cash": {"value": "100", "min_reserve": "0", "future_tax": "0"},
            "groups": [{"id": "g1", "name": "Group", "targetPercentage": "100"}],
            "instruments": [
                {
                    "id": "i1",
                    "ticker": "1234567",
                    "name": "ETF",
                    "quantity": 1,
                    "value": "150",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                }
            ],
        }
    )

    def fake_prepare_portfolio(path: Path) -> bool:
        window._welcome_controller._pending_startup_portfolio = welcome_mod._PendingStartupPortfolio(
            portfolio=staged_portfolio,
            file_path=path,
        )
        return True

    _mock_remembered_portfolio_path(monkeypatch, path=remembered_path, window=window)
    monkeypatch.setattr(window._welcome_controller, "_prepare_portfolio_from_path", fake_prepare_portfolio)
    seed_session_usd_ils_cache(window)
    _run_welcome_transition_immediately(monkeypatch, window)
    monkeypatch.setattr(
        window._welcome_controller,
        "_start_startup_fx_fetch",
        lambda: window._welcome_controller._on_startup_fx_fetch_finished(None, refreshed_portfolio, None),
    )

    window._on_welcome_open_last_clicked()

    assert window.stack.currentWidget() is window.screen_main
    assert window.total_label.text() == "Total portfolio (ILS): 250"


def test_welcome_success_action_shows_overlay_before_delayed_main_transition(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    seed_session_usd_ils_cache(window)
    scheduled: list[bool] = []
    monkeypatch.setattr(window._welcome_controller, "_schedule_main_screen_transition", lambda: scheduled.append(True))
    _complete_startup_fetch_successfully(monkeypatch, window)

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
    monkeypatch: pytest.MonkeyPatch,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    seed_session_usd_ils_cache(window)
    _complete_startup_fetch_successfully(monkeypatch, window)
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

    assert shown == [("Startup data fetch failed", "Failed to fetch USD to ILS exchange rate.")]
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
