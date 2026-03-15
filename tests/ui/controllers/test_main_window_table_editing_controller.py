from __future__ import annotations

"""Focused table-editing behavior tests for the main-window table controller."""

from collections.abc import Callable

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

import ui.controllers.main_window_table_editing as table_editing
from ui.main_window import MainWindow
from ui.shared.ui_types import Col, ROLE_EXCHANGE, ROLE_PREV_TEXT


def test_item_changed_exchange_normalizes_invalid_input_to_default_exchange(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: None)
    child = add_instrument_row(tree=window.tree, ticker="1234567")
    child.setText(Col.TICKER.value, "1234567")
    child.setText(Col.EXCHANGE.value, "invalid")

    window._on_item_changed_guard_and_recalc(child, Col.EXCHANGE.value)

    assert child.text(Col.EXCHANGE.value) == "TASE"
    assert child.data(0, ROLE_EXCHANGE) == "TASE"


def test_item_changed_quantity_reverts_invalid_value(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: warnings.append(("warn", "warn")))
    child = add_instrument_row(tree=window.tree, quantity=5, value="100")
    child.setText(Col.QUANTITY.value, "5")
    child.setData(Col.QUANTITY.value, ROLE_PREV_TEXT, "5")
    child.setText(Col.QUANTITY.value, "2.5")

    window._on_item_changed_guard_and_recalc(child, Col.QUANTITY.value)

    assert warnings
    assert child.text(Col.QUANTITY.value) == "5"


def test_item_changed_quantity_normalizes_empty_to_zero(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: None)
    child = add_instrument_row(tree=window.tree, quantity=7)
    child.setData(Col.QUANTITY.value, ROLE_PREV_TEXT, "7")
    child.setText(Col.QUANTITY.value, "")

    window._on_item_changed_guard_and_recalc(child, Col.QUANTITY.value)

    assert child.text(Col.QUANTITY.value) == "0"


def test_item_changed_ticker_does_not_revert_invalid_value_before_save(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: warnings.append(("warn", "warn")))
    child = add_instrument_row(tree=window.tree, exchange="TASE")
    child.setText(Col.EXCHANGE.value, "TASE")
    child.setText(Col.TICKER.value, "ab-c_1 ")

    window._on_item_changed_guard_and_recalc(child, Col.TICKER.value)

    assert not warnings
    assert child.text(Col.TICKER.value) == "ABC1"


@pytest.mark.parametrize("column", [Col.TICKER.value, Col.EXCHANGE.value])
def test_item_double_clicked_does_not_enable_edit_for_locked_identity_columns(
    window: MainWindow,
    add_instrument_row: Callable[..., QTreeWidgetItem],
    column: int,
) -> None:
    child = add_instrument_row(tree=window.tree, ticker="1234567", exchange="TASE")
    previous_role_value = child.data(column, ROLE_PREV_TEXT)

    window._on_item_double_clicked(child, column)

    assert child.data(column, ROLE_PREV_TEXT) == previous_role_value
