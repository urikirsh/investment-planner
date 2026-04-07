from __future__ import annotations

"""Helpers for the tree total-value column's raw/display split.

The total-value column is rendered as formatted text for the UI, but computed
totals are stored separately in item metadata so calculations and persistence
do not need to reparse visible text.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.ui_types import Col

D = Decimal
_ROLE_TOTAL_VALUE = int(Qt.ItemDataRole.UserRole) + 3


class TotalValueCell:
    """Encapsulate raw/display access for the tree total-value column."""

    @staticmethod
    def write(item: QTreeWidgetItem, value: D) -> None:
        """Store raw total value metadata and synchronized display text."""
        from ui.shared.ui_utils import fmt_decimal_grouped

        normalized = D(value)
        item.setData(Col.TOT_VALUE.value, _ROLE_TOTAL_VALUE, str(normalized))
        item.setText(Col.TOT_VALUE.value, fmt_decimal_grouped(normalized))

    @staticmethod
    def read(item: QTreeWidgetItem) -> D:
        """Return raw total value metadata, or ``0`` when missing/corrupt."""
        raw_value = item.data(Col.TOT_VALUE.value, _ROLE_TOTAL_VALUE)
        if isinstance(raw_value, str):
            try:
                return D(raw_value)
            except (InvalidOperation, ValueError):
                pass
        return D("0")
