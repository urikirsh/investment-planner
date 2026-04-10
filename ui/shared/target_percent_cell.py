from __future__ import annotations

"""Helpers for the tree target-percent column's raw/display split.

The target-percent column behaves differently from plain editable text cells:
- UI display shows a normalized percent string such as ``"25.0%"``.
- Persistence and calculations need the raw numeric text such as ``"25"``.
- In-place editors should open with plain numeric text, not the rendered suffix.

This helper keeps those concerns in one place so callers do not need to know
which Qt item-data role stores the raw value or how to translate between raw
and display forms.
"""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.ui_types import Col

D = Decimal
_ROLE_TARGET_PERCENT_RAW = int(Qt.ItemDataRole.UserRole) + 51


class TargetPercentCell:
    """Encapsulate raw/display access for target-percentage cells.

    Raw metadata is the canonical source of truth for persistence, metrics, and
    editor population. Callers should treat missing raw metadata as an invalid
    or incomplete cell state rather than reparsing the visible text.
    """

    @staticmethod
    def write(item: QTreeWidgetItem, text: str) -> None:
        """Store raw target-percent text and synchronized percentage display text.

        The raw value is stored without a trailing percent sign. The visible
        text is normalized to one decimal place plus ``%`` when the input is a
        valid decimal; invalid non-empty text is preserved as-is so callers can
        still render partial or malformed UI state without crashing.
        """
        raw = TargetPercentCell._strip_suffix(text)
        item.setData(Col.TARGET_PCT.value, _ROLE_TARGET_PERCENT_RAW, raw)
        item.setText(Col.TARGET_PCT.value, TargetPercentCell._format_display_text(raw))

    @staticmethod
    def read_raw_text(item: QTreeWidgetItem) -> str:
        """Return canonical raw target-percent text, or ``""`` when missing."""
        raw_value = item.data(Col.TARGET_PCT.value, _ROLE_TARGET_PERCENT_RAW)
        if isinstance(raw_value, str):
            return raw_value
        return ""

    @staticmethod
    def read_display_text(item: QTreeWidgetItem) -> str:
        """Return rendered target-percent display text."""
        return item.text(Col.TARGET_PCT.value)

    @staticmethod
    def read_raw_text_from_index(index: QModelIndex | QPersistentModelIndex) -> str:
        """Return raw target-percent text for editor population.

        Editors should open with bare numeric text instead of the rendered
        percent suffix so existing validators can continue to operate on plain
        decimal syntax.
        """
        raw_value = index.data(_ROLE_TARGET_PERCENT_RAW)
        if isinstance(raw_value, str):
            return raw_value
        return ""

    @staticmethod
    def parse_decimal(text: str) -> D:
        """Parse raw or display target-percent text as a ``Decimal``.

        This accepts either canonical raw text (for example ``"25"``) or the
        rendered display form (for example ``"25.0%"``). Validation callers use
        this to remain tolerant of programmatic UI writes and revert paths.
        """
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
        """Format raw target-percent text for display.

        Blank input stays blank. Invalid non-empty input is returned unchanged
        so the UI can continue to reflect incomplete or malformed text while a
        separate validation path decides whether to accept or revert it.
        """
        raw = TargetPercentCell._strip_suffix(text)
        if not raw:
            return ""
        try:
            from ui.shared.ui_utils import fmt_pct

            return fmt_pct(D(raw))
        except (InvalidOperation, ValueError):
            return raw
