from __future__ import annotations

"""
Focused controller-flow tests for `MainWindow`.

These tests validate cross-screen state transitions and prompt/action seams
after extracting action and wizard flows into mixins, without invoking modal
dialogs.
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

from portfolio_core.calc_stock_units import BuyCalculation
from portfolio_core.planning_types import PlanningMode
from portfolio_core.use_cases import PlanStep
import ui.main_window_controller as main_window_controller
from ui.main_window_controller import MainWindow
from ui.ui_types import Col, ROLE_EXCHANGE, ROLE_PREV_TEXT, RowKind
from ui.ui_state import UnsavedChangesDecision
from ui.ui_utils import add_instrument_item_to_group, set_group_tree_item, set_item_meta

D = Decimal


@pytest.fixture()
def window(monkeypatch: pytest.MonkeyPatch, qapp: object, tmp_path) -> Iterator[MainWindow]:
    _ = qapp
    monkeypatch.setattr(MainWindow, "_load_or_init", lambda self: None)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(win, "_cancel_wizard_fx_fetch", lambda **_kwargs: True)
    yield win
    win.close()


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
    monkeypatch.setattr(main_window_controller, "build_plan_for_current_document", lambda *_: fake_plan_result)
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
    assert "Step 1/2" in window.wiz_info.text()

    window.wizard_state.last_calc = calc
    window._advance_wizard_step()
    assert window.planning_state.step_index == 1
    assert window.wizard_state.last_calc is None
    assert "Step 2/2" in window.wiz_info.text()


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
    monkeypatch.setattr(main_window_controller, "build_plan_for_current_document", lambda *_: fake_plan_result)
    monkeypatch.setattr(window, "_reset_wizard_fx_state_for_new_run", lambda: False)
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))

    window._run_planning(PlanningMode.INVEST)

    assert errors and errors[0][0] == "Please wait"


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


def test_item_changed_exchange_normalizes_invalid_input_to_default_exchange(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(main_window_controller, "show_warning", lambda *_args: None)
    child = QTreeWidgetItem(window.tree)
    set_item_meta(child, RowKind.INSTRUMENT, "ins-1")
    child.setText(Col.TICKER.value, "1234567")
    child.setText(Col.EXCHANGE.value, "invalid")

    window._on_item_changed_guard_and_recalc(child, Col.EXCHANGE.value)

    assert child.text(Col.EXCHANGE.value) == "TASE"
    assert child.data(0, ROLE_EXCHANGE) == "TASE"


def test_item_changed_quantity_reverts_invalid_value(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(main_window_controller, "show_warning", lambda *_args: warnings.append(("warn", "warn")))
    child = QTreeWidgetItem(window.tree)
    set_item_meta(child, RowKind.INSTRUMENT, "ins-1")
    child.setText(Col.QUANTITY.value, "5")
    child.setData(Col.QUANTITY.value, ROLE_PREV_TEXT, "5")
    child.setText(Col.QUANTITY.value, "2.5")

    window._on_item_changed_guard_and_recalc(child, Col.QUANTITY.value)

    assert warnings
    assert child.text(Col.QUANTITY.value) == "5"


def test_item_changed_quantity_normalizes_empty_to_zero(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(main_window_controller, "show_warning", lambda *_args: None)
    child = QTreeWidgetItem(window.tree)
    set_item_meta(child, RowKind.INSTRUMENT, "ins-1")
    child.setData(Col.QUANTITY.value, ROLE_PREV_TEXT, "7")
    child.setText(Col.QUANTITY.value, "")

    window._on_item_changed_guard_and_recalc(child, Col.QUANTITY.value)

    assert child.text(Col.QUANTITY.value) == "0"


def test_item_changed_ticker_does_not_revert_invalid_value_before_save(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(main_window_controller, "show_warning", lambda *_args: warnings.append(("warn", "warn")))
    child = QTreeWidgetItem(window.tree)
    set_item_meta(child, RowKind.INSTRUMENT, "ins-1")
    child.setText(Col.EXCHANGE.value, "TASE")
    child.setText(Col.TICKER.value, "ab-c_1 ")

    window._on_item_changed_guard_and_recalc(child, Col.TICKER.value)

    assert not warnings
    assert child.text(Col.TICKER.value) == "ABC1"


def test_save_blocks_invalid_ticker_exchange_combination(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    errors: list[tuple[str, str]] = []
    target = tmp_path / "invalid_save.json"

    window.cash_value_edit.setText("1000")
    window.cash_reserve_edit.setText("0")
    window.future_tax_edit.setText("0")

    group = QTreeWidgetItem(window.tree)
    set_group_tree_item(group, "Group 1", "100", "g1")
    add_instrument_item_to_group(
        group,
        "1234567",  # Invalid for NYSE (valid only for TASE)
        "Instrument 1",
        1,
        "100",
        "100",
        "i1",
        "NYSE",
    )

    monkeypatch.setattr(window, "_resolve_save_target", lambda **_: target)
    monkeypatch.setattr(window, "_show_error", lambda title, message: errors.append((title, message)))

    saved = window._save_current_or_save_as(show_success=False)

    assert saved is False
    assert errors
    assert errors[0][0] == "Validation / Save failed"
    assert "ticker for NYSE must be exactly 4 uppercase letters or digits" in errors[0][1]
    assert not target.exists()
