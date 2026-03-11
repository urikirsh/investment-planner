from __future__ import annotations

"""Screen-level integration tests for `MainWindow` signal wiring."""

from decimal import Decimal
from typing import Callable

import pytest

from portfolio_core.calc_stock_units import BuyCalculation
from portfolio_core.use_cases import PlanStep
import ui.main_window_wizard as wizard_mod
from ui.main_window import MainWindow

D = Decimal


def test_welcome_screen_load_different_button_signal_enters_main_on_success(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_open_portfolio_from_picker", lambda: True)
    monkeypatch.setattr(window._welcome_controller, "_schedule_main_screen_transition", lambda callback: callback())
    assert window.stack.currentWidget() is window.screen_welcome

    window.screen_welcome.load_different_btn.click()

    assert window.stack.currentWidget() is window.screen_main


def test_main_editor_add_group_button_signal_adds_top_level_row(window: MainWindow) -> None:
    window.stack.setCurrentWidget(window.screen_main)
    before = window.tree.topLevelItemCount()

    window.screen_main.add_group_btn.click()

    assert window.tree.topLevelItemCount() == before + 1


def test_main_editor_save_button_signal_triggers_save_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_save_current_or_save_as(**kwargs: object) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(window, "_save_current_or_save_as", fake_save_current_or_save_as)

    window.screen_main.save_btn.click()

    assert calls == [{"show_success": True}]


def test_main_editor_save_as_button_signal_triggers_save_as_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_save_current_or_save_as(**kwargs: object) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(window, "_save_current_or_save_as", fake_save_current_or_save_as)

    window.screen_main.save_as_btn.click()

    assert calls == [{"show_success": True, "force_save_as": True}]


def test_main_editor_open_button_signal_triggers_open_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[bool] = []

    def fake_open_from_picker() -> bool:
        opened.append(True)
        return True

    monkeypatch.setattr(window, "_confirm_continue_with_unsaved_changes", lambda _action: True)
    monkeypatch.setattr(window, "_open_portfolio_from_picker", fake_open_from_picker)

    window.screen_main.open_btn.click()

    assert opened == [True]


def test_main_editor_new_button_signal_triggers_new_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded: list[bool] = []
    monkeypatch.setattr(window, "_confirm_continue_with_unsaved_changes", lambda _action: True)
    monkeypatch.setattr(window, "_load_default_document", lambda: loaded.append(True))

    window.screen_main.new_btn.click()

    assert loaded == [True]


def test_summary_next_button_signal_returns_to_main_when_no_steps(window: MainWindow) -> None:
    window.planning_state.plan_steps = []
    window.stack.setCurrentWidget(window.screen_summary)

    window.screen_summary.next_btn.click()

    assert window.stack.currentWidget() is window.screen_main


def test_wizard_calculate_button_signal_runs_calculation_flow(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_buy_calculation: Callable[..., BuyCalculation],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    window.price_edit.setText("10")

    fake_calc = make_buy_calculation(
        instrument_id=step.instrument_id,
        price="10",
        planned_money="20",
        units=2,
        spent="20",
        leftover="0",
    )
    monkeypatch.setattr(wizard_mod, "calculate_buy_units", lambda **_kwargs: fake_calc)

    window.screen_wizard.calculate_btn.click()

    assert window.wizard_state.last_calc is fake_calc
    assert "Units: 2" in window.wiz_result.text()
