from __future__ import annotations

"""Main-editor tree edit normalization and validation behavior."""

from decimal import Decimal
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from ui.controllers.protocols import MainWindowTableEditingHost
from ui.dialogs import show_warning
from ui.shared.ui_types import Col, ROLE_PREV_TEXT, RowKind
from ui.shared.ui_utils import get_item_kind, is_item_cell_editable


class MainWindowTableEditingController:
    """Controller containing guarded tree cell editing and validation flows."""

    def __init__(self, host: MainWindowTableEditingHost) -> None:
        self._host = host

    def _host_widget(self) -> QWidget:
        """Return host cast to QWidget for warning-dialog parenting."""
        return cast(QWidget, self._host)

    def _validate_edited_cell(self, item: QTreeWidgetItem, *, kind: RowKind | None, column: int) -> bool:
        """Dispatch edited-cell validation by row kind and edited column."""
        if kind == RowKind.GROUP and column == Col.TARGET_PCT.value:
            return self.validate_target_pct_cell_or_revert(item)
        if kind == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            return self.validate_instrument_target_pct_cell_or_revert(item)
        if kind == RowKind.INSTRUMENT and column == Col.QUANTITY.value:
            return self.validate_instrument_quantity_cell_or_revert(item)
        return True

    def on_item_changed_guard_and_recalc(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle itemChanged with guard, normalization, validation, and refresh."""
        host = self._host
        if host._suppress_item_changed:
            return

        kind = get_item_kind(item)
        _ = self._validate_edited_cell(item, kind=kind, column=column)
        host._refresh_data()

    def on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Start guarded cell editing on double-click for editable cells only."""
        host = self._host
        if is_item_cell_editable(item, column):
            item.setData(column, ROLE_PREV_TEXT, item.text(column))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            try:
                host.tree.editItem(item, column)
            finally:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    @staticmethod
    def _read_edit_cell(item: QTreeWidgetItem, col: int) -> tuple[str, str | None]:
        """Return stripped current text and cached previous text for edited cell."""
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)
        return raw, prev

    def _parse_decimal_cell_or_revert(self, item: QTreeWidgetItem, *, col: int, label: str) -> Decimal | None:
        """Parse numeric cell value, warning/reverting when parsing fails."""
        raw, prev = self._read_edit_cell(item, col)
        try:
            return Decimal(raw)
        except Exception:
            self.warn_and_revert(item, col, raw, prev, f"{label} must be a number.")
            return None

    def validate_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """Validate group target percentage and revert invalid edits."""
        col = Col.TARGET_PCT.value
        p = self._parse_decimal_cell_or_revert(item, col=col, label="Target %")
        if p is None:
            return False
        if p > 100:
            raw, prev = self._read_edit_cell(item, col)
            self.warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False
        return True

    def validate_instrument_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """Validate instrument target percentage and revert invalid edits."""
        parent = item.parent()
        if parent is None:
            return False
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            return False

        col = Col.TARGET_PCT.value
        p = self._parse_decimal_cell_or_revert(item, col=col, label="Target %")
        if p is None:
            return False
        if p < 0:
            raw, prev = self._read_edit_cell(item, col)
            self.warn_and_revert(item, col, raw, prev, "Target % cannot be negative.")
            return False
        if p > 100:
            raw, prev = self._read_edit_cell(item, col)
            self.warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False
        return True

    def validate_instrument_quantity_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """Validate instrument quantity as non-negative integer; blank becomes zero."""
        host = self._host
        col = Col.QUANTITY.value
        raw, prev = self._read_edit_cell(item, col)

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
        """Show warning and revert edited cell to previous value under change guard."""
        host = self._host
        host._suppress_item_changed = True
        try:
            show_warning(
                self._host_widget(),
                "Invalid input",
                f"{msg}\n\nYou entered: {bad}\nReverting to previous value: {prev}",
            )
            item.setText(col, prev if prev is not None else "")
        finally:
            host._suppress_item_changed = False
