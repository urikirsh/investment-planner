from __future__ import annotations

"""Row-level API for managed numeric cells in the portfolio tree."""

from decimal import Decimal

from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.quantity_cell import QuantityCell
from ui.shared.total_value_cell import TotalValueCell

D = Decimal


class PortfolioTreeRow:
    """Wrap one ``QTreeWidgetItem`` and expose managed numeric cell accessors."""

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
