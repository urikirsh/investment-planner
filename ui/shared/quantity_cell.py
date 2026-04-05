from __future__ import annotations

"""Helpers for the tree quantity column's raw/display split."""

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.ui_types import Col

_ROLE_QUANTITY = int(Qt.ItemDataRole.UserRole) + 4


class QuantityCell:
    """Encapsulate raw/display access for grouped quantity cells."""

    @staticmethod
    def write(item: QTreeWidgetItem, value: int) -> None:
        """Store raw quantity metadata and synchronized grouped display text."""
        from ui.shared.ui_utils import fmt_non_negative_integer_grouped

        normalized = max(0, int(value))
        item.setData(Col.QUANTITY.value, _ROLE_QUANTITY, normalized)
        item.setText(Col.QUANTITY.value, fmt_non_negative_integer_grouped(normalized))

    @staticmethod
    def read(item: QTreeWidgetItem) -> int:
        """Return raw quantity metadata, or ``0`` when missing/corrupt."""
        raw_value = item.data(Col.QUANTITY.value, _ROLE_QUANTITY)
        return raw_value if isinstance(raw_value, int) and raw_value >= 0 else 0

    @staticmethod
    def clear(item: QTreeWidgetItem) -> None:
        """Clear quantity display while keeping raw metadata normalized to zero."""
        item.setData(Col.QUANTITY.value, _ROLE_QUANTITY, 0)
        item.setText(Col.QUANTITY.value, "")

    @staticmethod
    def read_raw_text_from_index(index: QModelIndex | QPersistentModelIndex) -> str:
        """Return plain-digit quantity text for editor population."""
        raw_value = index.data(_ROLE_QUANTITY)
        if isinstance(raw_value, int) and raw_value >= 0:
            return str(raw_value)
        return ""

    @staticmethod
    def write_model_data(
        model: QAbstractItemModel,
        index: QModelIndex | QPersistentModelIndex,
        value: int,
    ) -> None:
        """Store raw quantity metadata and grouped display text through one model index."""
        from ui.shared.ui_utils import fmt_non_negative_integer_grouped

        normalized = max(0, int(value))
        model.setData(index, normalized, _ROLE_QUANTITY)
        model.setData(index, fmt_non_negative_integer_grouped(normalized), Qt.ItemDataRole.EditRole)
