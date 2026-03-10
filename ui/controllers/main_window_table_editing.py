from __future__ import annotations

"""Main-editor tree edit normalization and validation behavior."""

from decimal import Decimal
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from ui.controllers.protocols import MainWindowTableEditingHost
from ui.dialogs import show_warning
from ui.ui_types import Col, ROLE_EXCHANGE, ROLE_PREV_TEXT, RowKind
from ui.ui_utils import DEFAULT_EXCHANGE, _is_cell_editable, get_item_kind, parse_exchange_code


class MainWindowTableEditingController:
    """Controller containing guarded tree cell editing and validation flows."""

    def __init__(self, host: MainWindowTableEditingHost) -> None:
        self._host = host

    def on_item_changed_guard_and_recalc(self, item: QTreeWidgetItem, column: int) -> None:
        host = self._host
        if host._suppress_item_changed:
            return

        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TICKER.value:
            raw_ticker = item.text(column)
            sanitized_ticker = "".join(ch for ch in raw_ticker if ch.isascii() and ch.isalnum())
            normalized_ticker = sanitized_ticker.upper()
            if normalized_ticker != raw_ticker:
                host._suppress_item_changed = True
                try:
                    item.setText(column, normalized_ticker)
                finally:
                    host._suppress_item_changed = False

        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.EXCHANGE.value:
            raw = parse_exchange_code(item.text(column)) or DEFAULT_EXCHANGE.value
            item.setText(column, raw)
            item.setData(0, ROLE_EXCHANGE, raw)

        if get_item_kind(item) == RowKind.GROUP and column == Col.TARGET_PCT.value:
            if not self.validate_target_pct_cell_or_revert(item):
                host._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            if not self.validate_instrument_target_pct_cell_or_revert(item):
                host._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.QUANTITY.value:
            if not self.validate_instrument_quantity_cell_or_revert(item):
                host._refresh_data()
                return

        host._refresh_data()

    def on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Start guarded cell editing on double-click for editable cells only."""
        host = self._host
        kind = get_item_kind(item)

        if kind == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            parent = item.parent()
            if parent is not None and get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
                return
        if kind == RowKind.INSTRUMENT and column == Col.EXCHANGE.value:
            parent = item.parent()
            if parent is not None and get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
                return

        if _is_cell_editable(kind, column):
            item.setData(column, ROLE_PREV_TEXT, item.text(column))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            host.tree.editItem(item, column)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def validate_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)
        try:
            p = Decimal(raw)
        except Exception:
            self.warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False
        if p > 100:
            self.warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False
        return True

    def validate_instrument_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        parent = item.parent()
        if parent is None:
            return False
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            return False

        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)
        try:
            p = Decimal(raw)
        except Exception:
            self.warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False
        if p < 0:
            self.warn_and_revert(item, col, raw, prev, "Target % cannot be negative.")
            return False
        if p > 100:
            self.warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False
        return True

    def validate_instrument_quantity_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        host = self._host
        col = Col.QUANTITY.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        if raw == "":
            host._suppress_item_changed = True
            try:
                item.setText(col, "0")
            finally:
                host._suppress_item_changed = False
            return True
        if not raw.isdigit():
            self.warn_and_revert(item, col, raw, prev, "Quantity must be a non-negative integer.")
            return False
        return True

    def warn_and_revert(self, item: QTreeWidgetItem, col: int, bad: str, prev: str | None, msg: str) -> None:
        host = self._host
        host._suppress_item_changed = True
        try:
            show_warning(
                cast(QWidget, host),
                "Invalid input",
                f"{msg}\n\nYou entered: {bad}\nReverting to previous value: {prev}",
            )
            item.setText(col, prev if prev is not None else "")
        finally:
            host._suppress_item_changed = False
