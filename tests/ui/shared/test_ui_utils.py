from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from ui.shared.ui_types import Col
from ui.shared.ui_utils import (
    FIXED_CELL_BG_COLOR,
    NON_INVESTABLE_BUCKET_ID,
    add_instrument_item_to_group,
    get_item_total_value,
    get_item_exchange,
    is_item_cell_editable,
    normalize_and_validate_non_negative_integer_text,
    set_item_total_value,
    set_group_tree_item,
    validate_non_negative_integer_text,
)


def test_get_item_exchange_prefers_valid_visible_text() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.EXCHANGE.value, "nyse")

    assert get_item_exchange(item) == "NYSE"


def test_get_item_exchange_defaults_to_tase_when_text_is_invalid() -> None:
    item = QTreeWidgetItem()
    item.setText(Col.EXCHANGE.value, "not-an-exchange")

    assert get_item_exchange(item) == "TASE"


def test_add_instrument_item_keeps_empty_ticker_without_implicit_fallback() -> None:
    parent = QTreeWidgetItem()
    add_instrument_item_to_group(parent, "", "Instrument", 0, "100")

    child = parent.child(0)
    assert child is not None
    assert child.text(Col.TICKER.value) == ""


def test_set_item_total_value_updates_raw_value_and_display_text() -> None:
    item = QTreeWidgetItem()

    set_item_total_value(item, Decimal("12345.67"))

    assert get_item_total_value(item) == Decimal("12345.67")
    assert item.text(Col.TOT_VALUE.value) == "12,345.67"


def test_get_item_total_value_prefers_raw_metadata_over_visible_text() -> None:
    item = QTreeWidgetItem()
    set_item_total_value(item, Decimal("12345.67"))
    item.setText(Col.TOT_VALUE.value, "not a number")

    assert get_item_total_value(item) == Decimal("12345.67")


def test_is_item_cell_editable_allows_investable_instrument_target_pct() -> None:
    parent = QTreeWidgetItem()
    set_group_tree_item(parent, "Group", "100")
    add_instrument_item_to_group(parent, "1234567", "Instrument", 0, "100")
    child = parent.child(0)
    assert child is not None

    assert is_item_cell_editable(child, Col.TARGET_PCT.value)


def test_is_item_cell_editable_blocks_non_investable_instrument_target_pct() -> None:
    bucket = QTreeWidgetItem()
    set_group_tree_item(bucket, "Bucket", "0", NON_INVESTABLE_BUCKET_ID)
    add_instrument_item_to_group(bucket, "1234567", "Instrument", 0, "")
    child = bucket.child(0)
    assert child is not None

    assert not is_item_cell_editable(child, Col.TARGET_PCT.value)


def test_fixed_cells_use_tinted_background_on_instrument_rows() -> None:
    parent = QTreeWidgetItem()
    set_group_tree_item(parent, "Group", "100")
    add_instrument_item_to_group(parent, "1234567", "Instrument", 0, "100")
    child = parent.child(0)
    assert child is not None

    assert child.background(Col.TICKER.value).color().name() == FIXED_CELL_BG_COLOR
    assert child.background(Col.EXCHANGE.value).color().name() == FIXED_CELL_BG_COLOR
    assert child.background(Col.NAME.value).style() == Qt.BrushStyle.NoBrush


def test_non_investable_target_pct_does_not_use_fixed_tint() -> None:
    bucket = QTreeWidgetItem()
    set_group_tree_item(bucket, "Bucket", "0", NON_INVESTABLE_BUCKET_ID)
    add_instrument_item_to_group(bucket, "1234567", "Instrument", 0, "")
    child = bucket.child(0)
    assert child is not None

    assert child.background(Col.TARGET_PCT.value).style() == Qt.BrushStyle.NoBrush


def test_validate_non_negative_integer_text_requires_value_when_configured() -> None:
    value, error = validate_non_negative_integer_text(
        "",
        field_label="Units",
        required=True,
    )

    assert value is None
    assert error == "Units is required."


def test_validate_non_negative_integer_text_rejects_non_integer() -> None:
    value, error = validate_non_negative_integer_text(
        "2.5",
        field_label="Quantity",
        required=False,
    )

    assert value is None
    assert error == "Quantity must be a non-negative integer."


def test_validate_non_negative_integer_text_parses_valid_integer() -> None:
    value, error = validate_non_negative_integer_text(
        " 12 ",
        field_label="Quantity",
        required=False,
    )

    assert value == 12
    assert error == ""


def test_normalize_and_validate_non_negative_integer_text_requires_when_blank() -> None:
    normalized, value, error = normalize_and_validate_non_negative_integer_text(
        "",
        field_label="Units",
        required=True,
    )

    assert normalized == ""
    assert value is None
    assert error == "Units is required."


def test_normalize_and_validate_non_negative_integer_text_normalizes_blank_to_zero() -> None:
    normalized, value, error = normalize_and_validate_non_negative_integer_text(
        "   ",
        field_label="Quantity",
        required=False,
        blank_normalized_text="0",
    )

    assert normalized == "0"
    assert value == 0
    assert error == ""
