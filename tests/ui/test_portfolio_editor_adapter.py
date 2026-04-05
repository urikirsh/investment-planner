from __future__ import annotations

"""
Unit tests for `ui.portfolio_editor_adapter`.

These tests validate adapter-level mapping behavior independently from
`MainWindow` orchestration:
- model -> widget population
- widget -> payload serialization
- partial/strict mode handling for required cash fields
"""

from decimal import Decimal
from typing import Any

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

from portfolio_core.io_json import load_portfolio
from ui.portfolio_editor_adapter import (
    build_portfolio_data_from_main_editor,
    populate_main_editor_from_portfolio,
)
from ui.screens.main_editor_screen import MainEditorScreen
from ui.shared.ui_types import Col
from ui.shared.ui_utils import (
    NON_INVESTABLE_BUCKET_ID,
    add_instrument_item_to_group,
    get_item_quantity,
    set_group_tree_item,
    set_item_total_value,
)

NON_INVESTABLE_BUCKET_TITLE = "Non-investable holdings (excluded from strategy)"


def _sample_payload() -> dict[str, Any]:
    """Return a representative payload including investable and non-investable rows."""
    return {
        "cash": {"value": "12000", "min_reserve": "2000", "future_tax": "123"},
        "groups": [
            {"id": "g1", "name": "Group 1", "targetPercentage": "60"},
            {"id": "g2", "name": "Group 2", "targetPercentage": "40"},
        ],
        "instruments": [
            {
                "id": "i1",
                "ticker": "1234567",
                "name": "Investable A",
                "quantity": 17,
                "value": "7000",
                "exchange": "TASE",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i2",
                "ticker": "AB12",
                "name": "Investable B",
                "quantity": 0,
                "value": "3000",
                "exchange": "NYSE",
                "investable": True,
                "groupId": "g2",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i3",
                "ticker": "2345678",
                "name": "Legacy Holding",
                "quantity": 9,
                "value": "900",
                "exchange": "TASE",
                "investable": False,
                "targetInGroupPercentage": "0",
            },
        ],
    }


def test_adapter_populate_and_build_round_trip(qapp) -> None:
    """Populate widgets from portfolio and verify serialization returns the same payload."""
    _ = qapp
    payload = _sample_payload()
    portfolio = load_portfolio(payload)
    screen = MainEditorScreen()
    callback_calls = 0

    def on_future_tax_set() -> None:
        nonlocal callback_calls
        callback_calls += 1

    populate_main_editor_from_portfolio(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        portfolio=portfolio,
        non_investable_bucket_id=NON_INVESTABLE_BUCKET_ID,
        non_investable_bucket_title=NON_INVESTABLE_BUCKET_TITLE,
        on_future_tax_value_set=on_future_tax_set,
    )

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=False,
    )

    assert callback_calls == 1
    assert built == payload
    assert screen.tree.topLevelItemCount() == 3


def test_build_data_partial_mode_defaults_empty_cash_fields(qapp) -> None:
    """Verify strict-mode validation and partial-mode defaulting for empty cash inputs."""
    _ = qapp
    screen = MainEditorScreen()
    screen.cash_value_edit.setText("")
    screen.cash_reserve_edit.setText("")
    screen.future_tax_edit.setText("")

    partial = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=True,
    )
    assert partial["cash"] == {"value": "0", "min_reserve": "0", "future_tax": "0"}

    with pytest.raises(ValueError, match="Cash value and reserve must be filled"):
        build_portfolio_data_from_main_editor(
            tree=screen.tree,
            cash_value_edit=screen.cash_value_edit,
            cash_reserve_edit=screen.cash_reserve_edit,
            future_tax_edit=screen.future_tax_edit,
            allow_partial=False,
        )


def test_new_instrument_defaults_to_tase_exchange_in_payload(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    g = QTreeWidgetItem(screen.tree)
    set_group_tree_item(g, "Group 1", "100", "g1")
    add_instrument_item_to_group(g, "0000000", "New Instrument", 0, "100")

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=True,
    )

    assert built["instruments"][0]["exchange"] == "TASE"


def test_edited_exchange_persists_through_adapter_save_load_cycle(qapp) -> None:
    _ = qapp
    payload = _sample_payload()
    portfolio = load_portfolio(payload)
    screen = MainEditorScreen()

    populate_main_editor_from_portfolio(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        portfolio=portfolio,
        non_investable_bucket_id=NON_INVESTABLE_BUCKET_ID,
        non_investable_bucket_title=NON_INVESTABLE_BUCKET_TITLE,
        on_future_tax_value_set=lambda: None,
    )

    group1 = screen.tree.topLevelItem(0)
    assert group1 is not None
    investable = group1.child(0)
    investable.setText(Col.EXCHANGE.value, "NYSE")

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=False,
    )
    reloaded = load_portfolio(built)

    assert built["instruments"][0]["exchange"] == "NYSE"
    assert reloaded.instruments[0].exchange.value == "NYSE"


def test_planning_payload_includes_exchange_per_instrument(qapp) -> None:
    _ = qapp
    payload = _sample_payload()
    portfolio = load_portfolio(payload)
    screen = MainEditorScreen()

    populate_main_editor_from_portfolio(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        portfolio=portfolio,
        non_investable_bucket_id=NON_INVESTABLE_BUCKET_ID,
        non_investable_bucket_title=NON_INVESTABLE_BUCKET_TITLE,
        on_future_tax_value_set=lambda: None,
    )

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=False,
    )

    by_id = {i["id"]: i["exchange"] for i in built["instruments"]}
    assert by_id["i1"] == "TASE"
    assert by_id["i2"] == "NYSE"

    by_id_quantity = {i["id"]: i["quantity"] for i in built["instruments"]}
    assert by_id_quantity["i1"] == 17
    assert by_id_quantity["i2"] == 0


def test_build_data_normalizes_grouped_total_value_text(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    group = QTreeWidgetItem(screen.tree)
    set_group_tree_item(group, "Group 1", "100", "g1")
    add_instrument_item_to_group(group, "1234567", "ETF", 1, "100", "i1", "TASE")
    child = group.child(0)
    assert child is not None
    set_item_total_value(child, Decimal("12345.67"))
    child.setText(Col.TOT_VALUE.value, "12,345.67")

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=True,
    )

    assert built["instruments"][0]["value"] == "12345.67"


def test_build_data_uses_raw_cash_state_instead_of_grouped_display_text(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()
    screen.show()

    screen.cash_value_edit.setText("12345.67")
    screen.cash_reserve_edit.setText("500")
    screen.future_tax_edit.setText("25")
    screen.cash_value_edit.editingFinished.emit()
    screen.cash_reserve_edit.editingFinished.emit()
    screen.future_tax_edit.editingFinished.emit()

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=False,
    )

    assert screen.cash_value_edit.text() == "12,345.67"
    assert built["cash"] == {"value": "12345.67", "min_reserve": "500", "future_tax": "25"}


def test_build_data_uses_raw_quantity_state_instead_of_grouped_display_text(qapp) -> None:
    _ = qapp
    screen = MainEditorScreen()

    group = QTreeWidgetItem(screen.tree)
    set_group_tree_item(group, "Group 1", "100", "g1")
    add_instrument_item_to_group(group, "1234567", "ETF", 12345, "100", "i1", "TASE")
    child = group.child(0)
    assert child is not None
    assert get_item_quantity(child) == 12345
    child.setText(Col.QUANTITY.value, "not a number")

    built = build_portfolio_data_from_main_editor(
        tree=screen.tree,
        cash_value_edit=screen.cash_value_edit,
        cash_reserve_edit=screen.cash_reserve_edit,
        future_tax_edit=screen.future_tax_edit,
        allow_partial=True,
    )

    assert built["instruments"][0]["quantity"] == 12345
