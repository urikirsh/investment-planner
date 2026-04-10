from __future__ import annotations

"""Screen-level integration tests for `MainWindow` signal wiring."""

from decimal import Decimal
from typing import Callable

import pytest

from portfolio_core.io_json import load_portfolio
from portfolio_core.workflows import PlanStep
import ui.controllers.main_window_metrics as metrics_mod
import ui.plan_execution_wizard as wizard_mod
import ui.controllers.main_window_welcome as welcome_mod
from ui.main_window import MainWindow


def test_welcome_screen_load_different_button_signal_enters_main_on_success(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    seed_session_usd_ils_cache: Callable[[MainWindow], None],
) -> None:
    staged_portfolio = load_portfolio(
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

    def fake_prepare_portfolio_from_picker() -> bool:
        window._welcome_controller._pending_startup_portfolio = welcome_mod._PendingStartupPortfolio(
            portfolio=staged_portfolio,
            file_path=None,
        )
        return True

    def fake_start_fetch() -> None:
        window._welcome_controller._on_startup_market_data_fetch_finished(None, staged_portfolio, None)

    seed_session_usd_ils_cache(window)
    monkeypatch.setattr(
        metrics_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("100"),
    )
    monkeypatch.setattr(window._welcome_controller, "_schedule_main_screen_transition", window._welcome_controller._complete_startup_transition_to_main)
    monkeypatch.setattr(window._welcome_controller, "_prepare_portfolio_from_picker", fake_prepare_portfolio_from_picker)
    monkeypatch.setattr(window._welcome_controller, "_start_startup_market_data_fetch", fake_start_fetch)
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


def test_main_editor_refresh_market_data_button_signal_triggers_refresh_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(window, "_on_refresh_market_data_clicked", lambda: calls.append(True))

    window.screen_main.refresh_market_data_btn.click()

    assert calls == [True]
    assert "USD/ILS" in window.screen_main.refresh_market_data_btn.toolTip()


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
def test_wizard_units_text_changed_signal_runs_calculation_flow(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("10"),
    )
    window._show_current_plan_execution_step()

    window.units_edit.setValue(1)

    assert window.wizard_state.last_calc is not None
    assert window.wizard_state.last_calc.units == 1
    assert window.screen_wizard.save_continue_btn.isEnabled()
    assert window.wiz_result.text() == "Total spend: 10 ILS | Leftover: 10 ILS"


def test_wizard_units_text_changed_signal_disables_save_on_invalid_input(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("10"),
    )
    window._show_current_plan_execution_step()

    window.units_edit.setValue(1)

    assert window.wizard_state.last_calc is not None
    assert window.wizard_state.last_calc.units == 1
    assert window.screen_wizard.save_continue_btn.isEnabled()


def test_wizard_units_text_changed_signal_disables_save_on_empty_input(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("10"),
    )
    window._show_current_plan_execution_step()

    window.units_edit.setValue(0)

    assert window.wizard_state.last_calc is not None
    assert window.wizard_state.last_calc.units == 0
    assert window.screen_wizard.save_continue_btn.isEnabled()


def test_wizard_units_text_changed_signal_clamps_to_recommended_limit(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    step = make_plan_step(delta="20")
    window.planning_state.plan_steps = [step]
    window.planning_state.step_index = 0
    monkeypatch.setattr(
        wizard_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: Decimal("10"),
    )
    window._show_current_plan_execution_step()

    window.units_edit.setValue(3)

    assert window.units_edit.value() == 2
    assert window.wizard_state.last_calc is not None
    assert window.wizard_state.last_calc.units == 2
    assert window.screen_wizard.save_continue_btn.isEnabled()


def test_exit_plan_execution_button_signal_runs_back_flow(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(window, "_exit_plan_execution_to_portfolio", lambda: calls.append(True))

    window.screen_wizard.back_to_portfolio_btn.click()

    assert calls == [True]
