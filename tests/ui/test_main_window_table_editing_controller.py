from __future__ import annotations

"""Focused table-editing behavior tests for the main-window table controller."""

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

import ui.controllers.main_window_table_editing as table_editing
from ui.main_window_controller import MainWindow
from ui.ui_types import Col, ROLE_EXCHANGE, ROLE_PREV_TEXT, RowKind
from ui.ui_utils import set_item_meta


def test_item_changed_exchange_normalizes_invalid_input_to_default_exchange(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: None)
    child = QTreeWidgetItem(window.tree)
    set_item_meta(child, RowKind.INSTRUMENT, "ins-1")
    child.setText(Col.TICKER.value, "1234567")
    child.setText(Col.EXCHANGE.value, "invalid")

    window._on_item_changed_guard_and_recalc(child, Col.EXCHANGE.value)

    assert child.text(Col.EXCHANGE.value) == "TASE"
    assert child.data(0, ROLE_EXCHANGE) == "TASE"


def test_item_changed_quantity_reverts_invalid_value(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: warnings.append(("warn", "warn")))
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
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: None)
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
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: warnings.append(("warn", "warn")))
    child = QTreeWidgetItem(window.tree)
    set_item_meta(child, RowKind.INSTRUMENT, "ins-1")
    child.setText(Col.EXCHANGE.value, "TASE")
    child.setText(Col.TICKER.value, "ab-c_1 ")

    window._on_item_changed_guard_and_recalc(child, Col.TICKER.value)

    assert not warnings
    assert child.text(Col.TICKER.value) == "ABC1"
