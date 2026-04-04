from __future__ import annotations

"""
Focused controller-flow tests for `MainWindow`.

These tests validate cross-screen state transitions and prompt/action seams
in the composed-controller architecture, without invoking modal dialogs.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

from portfolio_core.io_json import load_portfolio
from portfolio_core.planning.calc_stock_units import BuyCalculation
from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.workflows import PlanStep
import ui.controllers.main_window_metrics as metrics_mod
import ui.main_window as main_window
from ui.main_window import MainWindow
from ui.ui_state import UnsavedChangesDecision

D = Decimal


def test_refresh_total_portfolio_propagates_unexpected_errors(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_build_portfolio_data_from_main_editor(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(metrics_mod, "build_portfolio_data_from_main_editor", fail_build_portfolio_data_from_main_editor)

    with pytest.raises(RuntimeError, match="boom"):
        window._refresh_total_portfolio()


def test_wizard_state_and_step_index_flow_across_planning_and_wizard_methods(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    # Shared builders are provided by tests/ui/conftest.py.
    make_plan_step: Callable[..., PlanStep],
    make_buy_calculation: Callable[..., BuyCalculation],
) -> None:
    step_1 = make_plan_step(
        delta="120",
        group_id="g_equity",
        group_name="Equity",
        instrument_id="i_world",
        instrument_name="World ETF",
    )
    step_2 = make_plan_step(
        delta="80",
        group_id="g_bonds",
        group_name="Bonds",
        instrument_id="i_bond",
        instrument_name="Bond Fund",
    )
    calc = make_buy_calculation(
        instrument_id="i_world",
        price="10",
        planned_money="120",
        units=12,
        spent="120",
        leftover="0",
    )

    fake_plan_result = SimpleNamespace(
        budget=D("200"),
        steps=[step_1, step_2],
        portfolio=SimpleNamespace(),
    )
    monkeypatch.setattr(window, "_save_current_or_save_as", lambda **_: True)
    monkeypatch.setattr(main_window, "build_plan_for_current_document", lambda *_: fake_plan_result)
    monkeypatch.setattr(window, "_populate_summary", lambda *_: None)

    window.planning_state.step_index = 99
    window.wizard_state.last_calc = calc
    window._run_planning(PlanningMode.REBALANCE)
    assert window.planning_state.plan_steps == [step_1, step_2]
    assert window.planning_state.step_index == 0
    assert window.planning_state.mode == PlanningMode.REBALANCE
    assert window.wizard_state.last_calc is None

    window.wizard_state.last_calc = calc
    window._show_current_wizard_step()
    assert window.planning_state.step_index == 0
    assert window.wizard_state.last_calc is None
    assert window.screen_wizard.step_progress.text() == "Step 1/2"

    window.wizard_state.last_calc = calc
    window._advance_wizard_step()
    assert window.planning_state.step_index == 1
    assert window.wizard_state.last_calc is None
    assert window.screen_wizard.step_progress.text() == "Step 2/2"


def test_run_planning_aborts_when_wizard_fx_reset_cannot_cancel(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    make_plan_step: Callable[..., PlanStep],
) -> None:
    fake_plan_result = SimpleNamespace(
        budget=D("200"),
        steps=[make_plan_step(delta="120")],
        portfolio=SimpleNamespace(),
    )
    errors: list[tuple[str, str]] = []

    monkeypatch.setattr(window, "_save_current_or_save_as", lambda **_: True)
    monkeypatch.setattr(main_window, "build_plan_for_current_document", lambda *_: fake_plan_result)
    monkeypatch.setattr(window, "_reset_wizard_fx_state_for_new_run", lambda: False)
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))

    window._run_planning(PlanningMode.INVEST)

    assert errors and errors[0][0] == "Please wait"


def test_run_planning_shows_error_modal_when_budget_is_zero(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_plan_result = SimpleNamespace(
        budget=D("0"),
        steps=[],
        portfolio=SimpleNamespace(),
    )
    errors: list[tuple[str, str]] = []
    info_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(window, "_save_current_or_save_as", lambda **_: True)
    monkeypatch.setattr(main_window, "build_plan_for_current_document", lambda *_: fake_plan_result)
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))
    monkeypatch.setattr(window, "_show_info", lambda title, message: info_calls.append((title, message)))

    window._run_planning(PlanningMode.INVEST)

    assert errors == [("No budget", "No investable cash")]
    assert info_calls == []


def test_save_flow_uses_resolved_target_and_action_methods_without_dialogs(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    target = tmp_path / "saved.json"
    calls: list[Path] = []
    info_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(window, "_resolve_save_target", lambda **_: target)
    monkeypatch.setattr(window, "_save_from_main_ui", lambda path: calls.append(path))
    monkeypatch.setattr(window, "_show_info", lambda title, message: info_calls.append((title, message)))

    assert window._save_current_or_save_as(show_success=True) is True
    assert calls == [target]
    assert info_calls and info_calls[0][0] == "Saved"


def test_open_from_picker_delegates_prompt_result_to_open_action(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    target = tmp_path / "to_open.json"
    received: list[Path] = []

    def fake_open(path: Path) -> bool:
        received.append(path)
        return True

    monkeypatch.setattr(window, "_prompt_select_open_path", lambda: target)
    monkeypatch.setattr(window, "_open_portfolio_from_path", fake_open)

    assert window._open_portfolio_from_picker() is True
    assert received == [target]


def test_load_portfolio_from_file_renders_refreshed_portfolio(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    target = tmp_path / "to_open.json"
    refreshed = load_portfolio(
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

    monkeypatch.setattr(main_window, "load_document", lambda session, path: refreshed)
    monkeypatch.setattr(
        metrics_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: D("150"),
    )

    window._load_portfolio_from_file(target)

    assert window.total_label.text() == "Total portfolio (ILS): 250.00"


def test_open_clicked_stays_on_current_screen_when_price_refresh_fails(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    target = tmp_path / "to_open.json"
    errors: list[tuple[str, str]] = []
    window.stack.setCurrentWidget(window.screen_main)

    monkeypatch.setattr(window, "_confirm_continue_with_unsaved_changes", lambda _action: True)
    monkeypatch.setattr(window, "_prompt_select_open_path", lambda: target)
    monkeypatch.setattr(window, "_load_portfolio_from_file", lambda path: (_ for _ in ()).throw(ValueError("price fetch failed")))
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))

    window._on_open_clicked()

    assert errors == [("Load failed", "Failed loading JSON:\nprice fetch failed")]
    assert window.stack.currentWidget() is window.screen_main


def test_new_clicked_shows_error_modal_when_default_price_refresh_fails(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[tuple[str, str]] = []
    window.stack.setCurrentWidget(window.screen_main)

    monkeypatch.setattr(window, "_confirm_continue_with_unsaved_changes", lambda _action: True)
    monkeypatch.setattr(
        window,
        "_load_default_document",
        lambda: (_ for _ in ()).throw(ValueError("price fetch failed")),
    )
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))

    window._on_new_clicked()

    assert errors == [("New failed", "price fetch failed")]
    assert window.stack.currentWidget() is window.screen_main


def test_confirm_unsaved_changes_splits_decision_prompt_from_action_resolution(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_has_unsaved_main_changes", lambda: True)
    monkeypatch.setattr(window, "_prompt_unsaved_changes_decision", lambda _: UnsavedChangesDecision.DISCARD)

    assert window._confirm_continue_with_unsaved_changes("opening another portfolio") is True


def test_close_event_cancels_inflight_wizard_fx_fetch(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    seen_timeout: list[int] = []

    def fake_cancel(*, wait_timeout_ms: int = 0) -> bool:
        nonlocal calls
        calls += 1
        seen_timeout.append(wait_timeout_ms)
        return True

    monkeypatch.setattr(window, "_cancel_wizard_fx_fetch", fake_cancel)
    window.close()

    assert calls >= 1
    assert seen_timeout and seen_timeout[0] == 12000


def test_close_event_aborts_when_startup_fx_cleanup_cannot_finish(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    shown_calls = 0
    wizard_cancel_calls = 0

    monkeypatch.setattr(window._welcome_controller, "cancel_pending_startup_transition", lambda **_kwargs: False)

    def fake_cancel_wizard_fx(*, wait_timeout_ms: int = 0) -> bool:
        nonlocal wizard_cancel_calls
        _ = wait_timeout_ms
        wizard_cancel_calls += 1
        return True

    def fake_show_cleanup_in_progress(_parent: object) -> None:
        nonlocal shown_calls
        shown_calls += 1

    monkeypatch.setattr(window, "_cancel_wizard_fx_fetch", fake_cancel_wizard_fx)
    monkeypatch.setattr(main_window, "show_cleanup_in_progress", fake_show_cleanup_in_progress)

    window.close()

    assert shown_calls == 1
    assert wizard_cancel_calls == 0


def test_save_blocks_invalid_ticker_exchange_combination(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    errors: list[tuple[str, str]] = []
    target = tmp_path / "invalid_save.json"

    window.cash_value_edit.setText("1000")
    window.cash_reserve_edit.setText("0")
    window.future_tax_edit.setText("0")

    add_instrument_row(
        tree=window.tree,
        ticker="BRK..B",  # Invalid NYSE symbol shape (double dot)
        exchange="NYSE",
    )

    monkeypatch.setattr(window, "_resolve_save_target", lambda **_: target)
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))

    saved = window._save_current_or_save_as(show_success=False)

    assert saved is False
    assert errors
    assert errors[0][0] == "Validation / Save failed"
    assert "ticker for NYSE must be 1 to 14 uppercase letters/digits, optionally one dot" in errors[0][1]
    assert not target.exists()


def test_save_allows_cash_below_minimum_reserve(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    target = tmp_path / "low-cash-save.json"
    info_calls: list[tuple[str, str]] = []

    window.cash_value_edit.setText("100")
    window.cash_reserve_edit.setText("150")
    window.future_tax_edit.setText("0")
    add_instrument_row(tree=window.tree, ticker="1234567", exchange="TASE")

    monkeypatch.setattr(window, "_resolve_save_target", lambda **_: target)
    monkeypatch.setattr(window, "_show_info", lambda title, message: info_calls.append((title, message)))

    saved = window._save_current_or_save_as(show_success=True)

    assert saved is True
    assert target.exists()
    assert info_calls and info_calls[0][0] == "Saved"
