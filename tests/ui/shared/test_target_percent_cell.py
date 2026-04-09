from __future__ import annotations

from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ui.shared.target_percent_cell import TargetPercentCell
from ui.shared.ui_types import Col


def test_target_percent_cell_updates_raw_value_and_display_text() -> None:
    item = QTreeWidgetItem()

    TargetPercentCell.write(item, "12.5")

    assert TargetPercentCell.read_raw_text(item) == "12.5"
    assert TargetPercentCell.read_display_text(item) == "12.5%"


def test_target_percent_cell_formats_existing_percent_suffix() -> None:
    item = QTreeWidgetItem()

    TargetPercentCell.write(item, "12.5%")

    assert TargetPercentCell.read_raw_text(item) == "12.5"
    assert TargetPercentCell.read_display_text(item) == "12.5%"


def test_target_percent_cell_read_raw_text_from_index_uses_stored_metadata(qapp: object) -> None:
    _ = qapp
    tree = QTreeWidget()
    tree.setColumnCount(len(Col))
    item = QTreeWidgetItem(tree)
    TargetPercentCell.write(item, "25")

    index = tree.model().index(0, Col.TARGET_PCT.value)

    assert TargetPercentCell.read_raw_text_from_index(index) == "25"


@pytest.mark.parametrize("text, expected", [("12.5", Decimal("12.5")), ("12.5%", Decimal("12.5"))])
def test_target_percent_cell_parse_decimal_accepts_raw_and_display_text(text: str, expected: Decimal) -> None:
    assert TargetPercentCell.parse_decimal(text) == expected
