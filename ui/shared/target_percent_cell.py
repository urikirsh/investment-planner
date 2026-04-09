from __future__ import annotations

"""Helpers for the tree target-percent column's raw/display split."""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.ui_types import Col

D = Decimal
_ROLE_TARGET_PERCENT_RAW = int(Qt.ItemDataRole.UserRole) + 51


class TargetPercentCell:
    """Encapsulate raw/display access for target-percentage cells."""

    @staticmethod
    def write(item: QTreeWidgetItem, text: str) -> None:
        """Store raw target-percent text and synchronized percentage display text."""
        raw = TargetPercentCell._strip_suffix(text)
        item.setData(Col.TARGET_PCT.value, _ROLE_TARGET_PERCENT_RAW, raw)
        item.setText(Col.TARGET_PCT.value, TargetPercentCell._format_display_text(raw))

    @staticmethod
    def read_raw_text(item: QTreeWidgetItem) -> str:
        """Return raw target-percent text, or parse it from display text when needed."""
        raw_value = item.data(Col.TARGET_PCT.value, _ROLE_TARGET_PERCENT_RAW)
        if isinstance(raw_value, str):
            return raw_value
        return TargetPercentCell._strip_suffix(item.text(Col.TARGET_PCT.value))

    @staticmethod
    def read_display_text(item: QTreeWidgetItem) -> str:
        """Return rendered target-percent display text."""
        return item.text(Col.TARGET_PCT.value)

    @staticmethod
    def read_raw_text_from_index(index: QModelIndex | QPersistentModelIndex) -> str:
        """Return raw target-percent text for editor population."""
        raw_value = index.data(_ROLE_TARGET_PERCENT_RAW)
        if isinstance(raw_value, str):
            return raw_value
        display_value = index.data(Qt.ItemDataRole.DisplayRole)
        if isinstance(display_value, str):
            return TargetPercentCell._strip_suffix(display_value)
        return ""

    @staticmethod
    def parse_decimal(text: str) -> D:
        """Parse raw or display target-percent text as a decimal."""
        return D(TargetPercentCell._strip_suffix(text))

    @staticmethod
    def _strip_suffix(text: str) -> str:
        """Remove one trailing percent sign and surrounding whitespace."""
        stripped = text.strip()
        if stripped.endswith("%"):
            return stripped[:-1].strip()
        return stripped

    @staticmethod
    def _format_display_text(text: str) -> str:
        """Format raw target-percent text for display, preserving blanks and invalid text."""
        raw = TargetPercentCell._strip_suffix(text)
        if not raw:
            return ""
        try:
            from ui.shared.ui_utils import fmt_pct

            return fmt_pct(D(raw))
        except (InvalidOperation, ValueError):
            return raw
