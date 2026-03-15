from __future__ import annotations

from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.ui_types import Col, ROLE_EXCHANGE
from ui.shared.ui_utils import (
    NON_INVESTABLE_BUCKET_ID,
    add_instrument_item_to_group,
    get_item_exchange,
    is_item_cell_editable,
    set_group_tree_item,
)


def test_get_item_exchange_prefers_valid_visible_text_over_role_data() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.EXCHANGE.value, "nyse")
    item.setData(0, ROLE_EXCHANGE, "TASE")

    assert get_item_exchange(item) == "NYSE"


def test_get_item_exchange_falls_back_to_role_data_when_text_is_invalid() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.EXCHANGE.value, "not-an-exchange")
    item.setData(0, ROLE_EXCHANGE, "nyse")

    assert get_item_exchange(item) == "NYSE"


def test_get_item_exchange_defaults_to_tase_when_both_sources_are_invalid() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.EXCHANGE.value, "")
    item.setData(0, ROLE_EXCHANGE, object())

    assert get_item_exchange(item) == "TASE"


def test_add_instrument_item_keeps_empty_ticker_without_implicit_fallback() -> None:
    parent = QTreeWidgetItem()
    add_instrument_item_to_group(parent, "", "Instrument", 0, "0", "100")

    child = parent.child(0)
    assert child is not None
    assert child.text(Col.TICKER.value) == ""


def test_is_item_cell_editable_allows_investable_instrument_target_pct() -> None:
    parent = QTreeWidgetItem()
    set_group_tree_item(parent, "Group", "100")
    add_instrument_item_to_group(parent, "1234567", "Instrument", 0, "0", "100")
    child = parent.child(0)
    assert child is not None

    assert is_item_cell_editable(child, Col.TARGET_PCT.value)


def test_is_item_cell_editable_blocks_non_investable_instrument_target_pct() -> None:
    bucket = QTreeWidgetItem()
    set_group_tree_item(bucket, "Bucket", "0", NON_INVESTABLE_BUCKET_ID)
    add_instrument_item_to_group(bucket, "1234567", "Instrument", 0, "0", "")
    child = bucket.child(0)
    assert child is not None

    assert not is_item_cell_editable(child, Col.TARGET_PCT.value)
