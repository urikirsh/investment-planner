from __future__ import annotations

"""Main-editor tree edit normalization and validation behavior."""

from decimal import Decimal
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from ui.dialogs import show_warning
from ui.ui_types import Col, ROLE_EXCHANGE, ROLE_PREV_TEXT, RowKind
from ui.ui_utils import DEFAULT_EXCHANGE, _is_cell_editable, get_item_kind, parse_exchange_code


class MainWindowTableEditingMixin:
    """Mixin containing guarded tree cell editing and validation flows."""

    _suppress_item_changed: bool
    tree: QTreeWidget

    def _refresh_data(self) -> None:
        ...

    def _on_item_changed_guard_and_recalc(self, item: QTreeWidgetItem, column: int) -> None:
        if self._suppress_item_changed:
            return

        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TICKER.value:
            # Defensive normalization for programmatic edits/pastes/tests.
            raw_ticker = item.text(column)
            sanitized_ticker = "".join(ch for ch in raw_ticker if ch.isascii() and ch.isalnum())
            normalized_ticker = sanitized_ticker.upper()
            if normalized_ticker != raw_ticker:
                self._suppress_item_changed = True
                try:
                    item.setText(column, normalized_ticker)
                finally:
                    self._suppress_item_changed = False

        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.EXCHANGE.value:
            raw = parse_exchange_code(item.text(column)) or DEFAULT_EXCHANGE.value
            item.setText(column, raw)
            item.setData(0, ROLE_EXCHANGE, raw)

        if get_item_kind(item) == RowKind.GROUP and column == Col.TARGET_PCT.value:
            if not self._validate_target_pct_cell_or_revert(item):
                self._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            if not self._validate_instrument_target_pct_cell_or_revert(item):
                self._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.QUANTITY.value:
            if not self._validate_instrument_quantity_cell_or_revert(item):
                self._refresh_data()
                return

        self._refresh_data()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """
        Start guarded cell editing on double-click for editable cells only.

        Previous text is captured for possible validation-driven revert.
        """
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
            self.tree.editItem(item, column)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def _validate_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """Validate group target-% cell. Return False when value is reverted."""
        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        try:
            p = Decimal(raw)
        except Exception:
            self._warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False

        if p > 100:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False

        return True

    def _validate_instrument_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """Validate instrument row target-% (in-group target) and revert if invalid."""
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
            self._warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False

        if p < 0:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot be negative.")
            return False
        if p > 100:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False

        return True

    def _validate_instrument_quantity_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """Validate instrument quantity cell (non-negative integer; empty -> 0)."""
        col = Col.QUANTITY.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        if raw == "":
            self._suppress_item_changed = True
            try:
                item.setText(col, "0")
            finally:
                self._suppress_item_changed = False
            return True
        if not raw.isdigit():
            self._warn_and_revert(
                item,
                col,
                raw,
                prev,
                "Quantity must be a non-negative integer.",
            )
            return False
        return True

    def _warn_and_revert(self, item: QTreeWidgetItem, col: int, bad: str, prev: str | None, msg: str) -> None:
        """Show validation warning and revert edited cell to previous value."""
        self._suppress_item_changed = True
        try:
            show_warning(
                cast(QWidget, self),
                "Invalid input",
                f"{msg}\n\nYou entered: {bad}\nReverting to previous value: {prev}",
            )
            item.setText(col, prev if prev is not None else "")
        finally:
            self._suppress_item_changed = False
