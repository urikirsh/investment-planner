from __future__ import annotations

"""
Unit tests for `ui.portfolio_editor_adapter`.

These tests validate adapter-level mapping behavior independently from
`MainWindow` orchestration:
- model -> widget population
- widget -> payload serialization
- partial/strict mode handling for required cash fields
"""

from typing import Any

import pytest

from investment_planner.io_json import load_portfolio
from ui.portfolio_editor_adapter import (
    build_portfolio_data_from_main_editor,
    populate_main_editor_from_portfolio,
)
from ui.screens.main_editor_screen import MainEditorScreen
from ui.ui_utils import NON_INVESTABLE_BUCKET_ID

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
                "name": "Investable A",
                "value": "7000",
                "investable": True,
                "groupId": "g1",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i2",
                "name": "Investable B",
                "value": "3000",
                "investable": True,
                "groupId": "g2",
                "targetInGroupPercentage": "100",
            },
            {
                "id": "i3",
                "name": "Legacy Holding",
                "value": "900",
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
