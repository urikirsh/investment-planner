from __future__ import annotations

"""Row-level API for managed portfolio-tree cell reads and writes."""

from decimal import Decimal

from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.quantity_cell import QuantityCell
from ui.shared.target_percent_cell import TargetPercentCell
from ui.shared.total_value_cell import TotalValueCell
from ui.shared.ui_types import Col
from ui.shared.ui_utils import (
    DRIFT_NEGATIVE_COLOR,
    DRIFT_POSITIVE_COLOR,
    READONLY_TEXT_COLOR,
)

D = Decimal


class PortfolioTreeRow:
    """Wrap one ``QTreeWidgetItem`` and expose managed tree-cell reads, writes, and drift styling."""

    def __init__(self, item: QTreeWidgetItem) -> None:
        self._item = item

    @property
    def item(self) -> QTreeWidgetItem:
        """Return the wrapped Qt item."""
        return self._item

    def set_total_value(self, value: D) -> None:
        """Store and render the row's computed total value."""
        TotalValueCell.write(self._item, D(value))

    def total_value(self) -> D:
        """Return the row's raw total value."""
        return TotalValueCell.read(self._item)

    def set_quantity(self, value: int) -> None:
        """Store and render the row's quantity."""
        QuantityCell.write(self._item, value)

    def quantity(self) -> int:
        """Return the row's raw quantity."""
        return QuantityCell.read(self._item)

    def clear_quantity(self) -> None:
        """Clear quantity display for rows that do not own a quantity input."""
        QuantityCell.clear(self._item)

    def target_pct_text(self) -> str:
        """Return the row's raw target-percentage text without display suffix."""
        return TargetPercentCell.read_raw_text(self._item)

    def target_pct_display_text(self) -> str:
        """Return the row's rendered target-percentage cell text."""
        return TargetPercentCell.read_display_text(self._item)

    def set_target_pct_text(self, text: str) -> None:
        """Set the row's target-percentage cell text using formatted display text."""
        TargetPercentCell.write(self._item, text)

    def portfolio_pct_text(self) -> str:
        """Return the row's portfolio-percentage cell text."""
        return self._item.text(Col.PORTFOLIO_PCT.value)

    def set_portfolio_pct_text(self, text: str) -> None:
        """Set the row's portfolio-percentage cell text."""
        self._item.setText(Col.PORTFOLIO_PCT.value, text)

    def strategy_pct_text(self) -> str:
        """Return the row's strategy-percentage cell text."""
        return self._item.text(Col.STRATEGY_PCT.value)

    def set_strategy_pct_text(self, text: str) -> None:
        """Set the row's strategy-percentage cell text."""
        self._item.setText(Col.STRATEGY_PCT.value, text)

    def drift_text(self) -> str:
        """Return the row's drift cell text."""
        return self._item.text(Col.DRIFT_PP.value)

    def set_drift(self, text: str, drift_pp: Decimal) -> None:
        """Set the row's drift text and matching foreground color together."""
        self._item.setText(Col.DRIFT_PP.value, text)
        if drift_pp < 0:
            self._item.setForeground(Col.DRIFT_PP.value, QBrush(QColor(DRIFT_NEGATIVE_COLOR)))
        elif drift_pp > 0:
            self._item.setForeground(Col.DRIFT_PP.value, QBrush(QColor(DRIFT_POSITIVE_COLOR)))
        else:
            self._item.setForeground(Col.DRIFT_PP.value, QBrush(QColor(READONLY_TEXT_COLOR)))
