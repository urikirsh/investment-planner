from __future__ import annotations

"""Focused table-editing behavior tests for the main-window table controller."""

from collections.abc import Callable

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from portfolio_core.market_data import TickerLookupFound
from tests.ui.conftest import assert_portfolio_tree_managed_cells_consistent
import ui.controllers.main_window_table_editing as table_editing
import ui.controllers.main_window_metrics as metrics_mod
from ui.main_window import MainWindow
from ui.shared.ui_types import Col, ROLE_PREV_TEXT


def test_item_changed_quantity_reverts_invalid_value(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
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


@pytest.mark.parametrize("column", [Col.TICKER.value, Col.TOT_VALUE.value, Col.EXCHANGE.value])
def test_item_double_clicked_does_not_call_edit_item_for_locked_columns(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
    column: int,
) -> None:
    edit_calls: list[tuple[QTreeWidgetItem, int]] = []

    def _record_edit_item(item: QTreeWidgetItem, edit_column: int) -> None:
        edit_calls.append((item, edit_column))

    monkeypatch.setattr(window.tree, "editItem", _record_edit_item)
    child = add_instrument_row(tree=window.tree, ticker="1234567", exchange="TASE")

    window._on_item_double_clicked(child, column)

    assert not edit_calls


def test_item_changed_quantity_recomputes_total_value_from_cached_price(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
    make_cached_lookup: Callable[..., TickerLookupFound],
) -> None:
    child = add_instrument_row(tree=window.tree, ticker="1234567", exchange="TASE", quantity=7, value="999")
    group = child.parent()
    assert group is not None
    child.setData(Col.QUANTITY.value, ROLE_PREV_TEXT, "7")
    child.setText(Col.QUANTITY.value, "4")

    monkeypatch.setattr(
        metrics_mod,
        "resolve_cached_instrument_price_ils",
        lambda **_kwargs: metrics_mod.D("12.5"),
    )

    window._on_item_changed_guard_and_recalc(child, Col.QUANTITY.value)

    assert child.text(Col.TOT_VALUE.value) == "50.00"
    assert group.text(Col.TOT_VALUE.value) == "50.00"


def test_item_changed_target_pct_formats_with_percent_suffix(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: None)
    child = add_instrument_row(tree=window.tree, target_in_group_pct="25")
    child.setData(Col.TARGET_PCT.value, ROLE_PREV_TEXT, "25.0%")
    child.setText(Col.TARGET_PCT.value, "25")

    window._on_item_changed_guard_and_recalc(child, Col.TARGET_PCT.value)

    assert child.text(Col.TARGET_PCT.value) == "25.0%"


def test_item_changed_quantity_formats_grouped_display(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    monkeypatch.setattr(window, "_refresh_data", lambda: None)
    monkeypatch.setattr(table_editing, "show_warning", lambda *_args: None)
    child = add_instrument_row(tree=window.tree, quantity=7)
    child.setData(Col.QUANTITY.value, ROLE_PREV_TEXT, "7")
    child.setText(Col.QUANTITY.value, "12345")

    window._on_item_changed_guard_and_recalc(child, Col.QUANTITY.value)

    assert child.text(Col.QUANTITY.value) == "12,345"
    assert_portfolio_tree_managed_cells_consistent(window.tree)


def test_item_double_clicked_restores_editable_flag_when_editing_raises(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    add_instrument_row: Callable[..., QTreeWidgetItem],
) -> None:
    child = add_instrument_row(tree=window.tree, ticker="1234567", exchange="TASE")
    original_flags = child.flags()

    def _raise_edit_item(_item: QTreeWidgetItem, _column: int) -> None:
        raise RuntimeError("edit boom")

    monkeypatch.setattr(window.tree, "editItem", _raise_edit_item)

    with pytest.raises(RuntimeError, match="edit boom"):
        window._on_item_double_clicked(child, Col.NAME.value)

    assert not bool(child.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(original_flags & Qt.ItemFlag.ItemIsEditable)
