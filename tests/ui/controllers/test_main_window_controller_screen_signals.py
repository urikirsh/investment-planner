from __future__ import annotations

"""Screen-level integration tests for `MainWindow` signal wiring."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable

import pytest

from portfolio_core.calc_stock_units import BuyCalculation
from portfolio_core.use_cases import PlanStep
import ui.main_window_wizard as wizard_mod
from ui.main_window import MainWindow

D = Decimal


def _seed_session_usd_ils_cache(window: MainWindow) -> None:
    window.session.cache_usd_ils_quote(
        rate=Decimal("3.75"),
        effective_date=date.fromisoformat("2026-03-10"),
        used_last_published=False,
        cached_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        persist=False,
    )


def test_welcome_screen_load_different_button_signal_enters_main_on_success(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_open_portfolio_from_picker", lambda: True)
    _seed_session_usd_ils_cache(window)
    monkeypatch.setattr(window._welcome_controller, "_schedule_main_screen_transition", window._welcome_controller._complete_startup_transition_to_main)
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
    assert window.screen_wizard.save_continue_btn.isEnabled()
    assert "Units: 2" in window.wiz_result.text()


def test_wizard_price_editing_finished_signal_runs_implicit_calculation_flow(
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

    window.price_edit.editingFinished.emit()

    assert window.wizard_state.last_calc is fake_calc
    assert window.screen_wizard.save_continue_btn.isEnabled()
    assert "Units: 2" in window.wiz_result.text()


def test_wizard_price_editing_finished_does_not_show_modal_error_on_invalid_input(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
    make_buy_calculation: Callable[..., BuyCalculation],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    window.wizard_state.last_calc = make_buy_calculation(
        instrument_id=step.instrument_id,
        price="10",
        planned_money="20",
        units=2,
        spent="20",
        leftover="0",
    )
    window.screen_wizard.save_continue_btn.setEnabled(True)
    window.price_edit.setText("abc")
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(wizard_mod, "show_error", lambda _p, t, m: shown.append((t, m)))

    window.price_edit.editingFinished.emit()

    assert shown == []
    assert window.wizard_state.last_calc is None
    assert not window.screen_wizard.save_continue_btn.isEnabled()
    assert "Calculation not updated:" in window.wiz_result.text()


def test_wizard_price_editing_finished_with_empty_input_clears_calc_and_disables_save(
    window: MainWindow,
    make_plan_step: Callable[..., PlanStep],
    make_buy_calculation: Callable[..., BuyCalculation],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    window.wizard_state.last_calc = make_buy_calculation(
        instrument_id=step.instrument_id,
        price="10",
        planned_money="20",
        units=2,
        spent="20",
        leftover="0",
    )
    window.screen_wizard.save_continue_btn.setEnabled(True)
    window.price_edit.setText("   ")

    window.price_edit.editingFinished.emit()

    assert window.wizard_state.last_calc is None
    assert not window.screen_wizard.save_continue_btn.isEnabled()


def test_wizard_back_to_portfolio_button_signal_runs_back_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(window, "_wizard_back_to_portfolio", lambda: calls.append(True))

    window.screen_wizard.back_to_portfolio_btn.click()

    assert calls == [True]
