from __future__ import annotations

from PySide6.QtWidgets import QTreeWidgetItem

from ui.ui_types import Col, ROLE_CURRENCY
from ui.ui_utils import get_item_currency


def test_get_item_currency_prefers_valid_visible_text_over_role_data() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.CURRENCY.value, "usd")
    item.setData(0, ROLE_CURRENCY, "ILS")

    assert get_item_currency(item) == "USD"


def test_get_item_currency_falls_back_to_role_data_when_text_is_invalid() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.CURRENCY.value, "not-a-currency")
    item.setData(0, ROLE_CURRENCY, "usd")

    assert get_item_currency(item) == "USD"


def test_get_item_currency_defaults_to_ils_when_both_sources_are_invalid() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.CURRENCY.value, "")
    item.setData(0, ROLE_CURRENCY, object())

    assert get_item_currency(item) == "ILS"
