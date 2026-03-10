from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import portfolio_core.portfolio_session as session_mod
from ui.main_window_controller import MainWindow


@pytest.fixture()
def window(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[MainWindow]:
    _ = qapp
    monkeypatch.setattr(session_mod.PortfolioSession, "get_remembered_portfolio_path", lambda _self: None)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    yield win
    win.close()


def test_welcome_screen_shows_when_no_recent_portfolio(window: MainWindow) -> None:
    assert window.stack.currentWidget() is window.screen_welcome
    assert not window.screen_welcome.open_last_btn.isEnabled()
    assert window.screen_welcome.last_path_label.text() == "No recent portfolio"


def test_welcome_screen_marks_missing_recent_portfolio_in_red(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = qapp
    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(session_mod.PortfolioSession, "get_remembered_portfolio_path", lambda _self: missing_path)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    try:
        assert not win.screen_welcome.open_last_btn.isEnabled()
        assert "Not found" in win.screen_welcome.last_path_label.text()
        assert "b00020" in win.screen_welcome.last_path_label.styleSheet()
    finally:
        win.close()


def test_welcome_open_last_transitions_to_main_on_success(window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    remembered_path = tmp_path / "remembered.json"
    remembered_path.write_text("{}", encoding="utf-8")
    seen_paths: list[Path] = []

    def fake_open_portfolio(path: Path) -> bool:
        seen_paths.append(path)
        return True

    monkeypatch.setattr(window.session, "get_remembered_portfolio_path", lambda: remembered_path)
    monkeypatch.setattr(window, "_open_portfolio_from_path", fake_open_portfolio)

    window._on_welcome_open_last_clicked()

    assert seen_paths == [remembered_path]
    assert window.stack.currentWidget() is window.screen_main


def test_welcome_load_different_keeps_welcome_screen_on_cancel(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window, "_open_portfolio_from_picker", lambda: False)

    window._on_welcome_load_different_clicked()

    assert window.stack.currentWidget() is window.screen_welcome


def test_welcome_start_new_loads_default_and_enters_main(window: MainWindow) -> None:
    window._on_welcome_start_new_clicked()

    assert window.stack.currentWidget() is window.screen_main
    assert window.session.current_file_path is None
    assert window.tree.topLevelItemCount() > 0
