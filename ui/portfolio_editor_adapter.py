"""
Main-editor UI <-> portfolio payload adapter.

This module centralizes conversion rules between:
- main-editor widgets (`QTreeWidget` + cash `QLineEdit`s)
- domain model (`Portfolio`)
- JSON-like payloads used by application use-cases

Why this module exists
----------------------
`MainWindow` coordinates flow and user actions. Mapping logic is kept here so:
- schema details do not leak across UI orchestration code
- conversion behavior is testable in isolation
- UI serialization/deserialization rules have a single source of truth
"""

from __future__ import annotations

from typing import Callable, NotRequired, TypedDict

from PySide6.QtWidgets import QLineEdit, QTreeWidget, QTreeWidgetItem

from portfolio_core.models import Portfolio
from ui.ui_types import Col, RowKind
from ui.ui_utils import (
    add_instrument_item_to_group,
    get_item_currency,
    get_item_id,
    get_item_kind,
    new_id,
    set_group_tree_item,
    set_item_meta,
)


class CashPayload(TypedDict):
    value: str
    min_reserve: str
    future_tax: str


class GroupPayload(TypedDict):
    id: str
    name: str
    targetPercentage: str


class InstrumentPayload(TypedDict):
    id: str
    name: str
    value: str
    currency: str
    quantity: str
    investable: bool
    targetInGroupPercentage: str
    groupId: NotRequired[str]


class PortfolioPayload(TypedDict):
    cash: CashPayload
    groups: list[GroupPayload]
    instruments: list[InstrumentPayload]


class InstrumentUiRow(TypedDict):
    id: str
    name: str
    quantity: str
    value: str
    currency: str
    investable: bool
    groupId: str | None
    targetInGroupPercentage: str


def populate_main_editor_from_portfolio(
    *,
    tree: QTreeWidget,
    cash_value_edit: QLineEdit,
    cash_reserve_edit: QLineEdit,
    future_tax_edit: QLineEdit,
    portfolio: Portfolio,
    non_investable_bucket_id: str,
    non_investable_bucket_title: str,
    on_future_tax_value_set: Callable[[], None],
) -> None:
    """
    Render a `Portfolio` into main-editor widgets.

    Parameters
    ----------
    tree, cash_value_edit, cash_reserve_edit, future_tax_edit:
        Main-editor widgets to populate.
    portfolio:
        Source domain model.
    non_investable_bucket_id, non_investable_bucket_title:
        UI-only bucket metadata values.
    on_future_tax_value_set:
        Callback invoked after setting `future_tax_edit`, typically used to
        refresh visual state (coloring).

    Notes
    -----
    - Tree signals are blocked during population to avoid intermediate
      recalculation/validation side effects.
    - A non-investable bucket row is always present in the tree, even when
      there are no non-investable instruments.
    - Input order from the portfolio model is preserved for deterministic UI.
    """
    tree.blockSignals(True)
    try:
        tree.clear()
        cash_value_edit.setText(str(portfolio.cash.value))
        cash_reserve_edit.setText(str(portfolio.cash.min_reserve))
        future_tax_edit.setText(str(portfolio.cash.future_tax))
        on_future_tax_value_set()

        # group -> instruments (preserve stored order)
        instruments_by_group: dict[str, list[InstrumentUiRow]] = {}
        non_investable_rows: list[InstrumentUiRow] = []

        for ins in portfolio.instruments:
            row: InstrumentUiRow = {
                "id": ins.id,
                "name": ins.name,
                "quantity": ins.quantity,
                "value": str(ins.value),
                "currency": ins.currency.value,
                "investable": ins.investable,
                "groupId": ins.asset_group_id,
                "targetInGroupPercentage": str(ins.target_in_group_pct),
            }
            if ins.investable and ins.asset_group_id:
                instruments_by_group.setdefault(ins.asset_group_id, []).append(row)
            else:
                non_investable_rows.append(row)

        for group in portfolio.asset_groups:
            group_item = QTreeWidgetItem(tree)
            set_group_tree_item(group_item, group.name, group.target_pct, group.id)

            for ins_row in instruments_by_group.get(group.id, []):
                add_instrument_item_to_group(
                    group_item,
                    ins_row["name"],
                    ins_row["quantity"],
                    ins_row["value"],
                    ins_row["targetInGroupPercentage"],
                    ins_row["id"],
                    ins_row["currency"],
                )

        non_investable_bucket = QTreeWidgetItem(tree)
        set_group_tree_item(
            non_investable_bucket,
            non_investable_bucket_title,
            0,
            non_investable_bucket_id,
        )

        for non_investable_row in non_investable_rows:
            add_instrument_item_to_group(
                non_investable_bucket,
                non_investable_row["name"],
                non_investable_row["quantity"],
                non_investable_row["value"],
                "",
                non_investable_row["id"],
                non_investable_row["currency"],
            )

        tree.expandAll()
    finally:
        tree.blockSignals(False)


def build_portfolio_data_from_main_editor(
    *,
    tree: QTreeWidget,
    cash_value_edit: QLineEdit,
    cash_reserve_edit: QLineEdit,
    future_tax_edit: QLineEdit,
    allow_partial: bool = False,
) -> PortfolioPayload:
    """
    Build JSON-like portfolio payload from current main-editor widgets.

    Parameters
    ----------
    allow_partial:
        If ``True``, empty numeric cash fields are normalized to ``"0"``.
        If ``False``, required cash fields must be non-empty.

    Returns
    -------
    PortfolioPayload
        Payload with `cash`, `groups`, and `instruments` keys that matches
        the shape expected by parsing/saving use-cases.

    Raises
    ------
    ValueError
        If `allow_partial` is ``False`` and required cash fields are empty.

    Behavior notes
    --------------
    - The non-investable top-level bucket is not emitted as a strategy group.
    - Missing instrument ids are generated and written back into row metadata.
    - Non-investable instruments are serialized with `investable=False`,
      `targetInGroupPercentage="0"`, and without `groupId`.
    """
    cash_value = cash_value_edit.text().strip()
    cash_reserve = cash_reserve_edit.text().strip()
    future_tax = future_tax_edit.text().strip()

    if not allow_partial and (not cash_value or not cash_reserve):
        raise ValueError("Cash value and reserve must be filled")

    cash_value = cash_value or "0"
    cash_reserve = cash_reserve or "0"
    future_tax = future_tax or "0"

    groups: list[GroupPayload] = []
    instruments: list[InstrumentPayload] = []

    for i in range(tree.topLevelItemCount()):
        group_item = tree.topLevelItem(i)
        if group_item is None:
            continue

        kind = get_item_kind(group_item)
        if kind == RowKind.INSTRUMENT:
            continue

        group_id = get_item_id(group_item) or new_id("grp")
        group_name = group_item.text(Col.NAME.value).strip()
        target_pct = group_item.text(Col.TARGET_PCT.value).strip() or "0"
        is_non_investable_bucket = kind == RowKind.NON_INVESTABLE_BUCKET

        if not is_non_investable_bucket:
            groups.append({"id": group_id, "name": group_name, "targetPercentage": target_pct})

        for j in range(group_item.childCount()):
            ins = group_item.child(j)
            if ins.parent() is None:
                continue

            instrument_id = get_item_id(ins)
            if not instrument_id:
                instrument_id = new_id("ins")
                set_item_meta(ins, RowKind.INSTRUMENT, instrument_id)

            instrument_name = ins.text(Col.NAME.value).strip()
            quantity = ins.text(Col.QUANTITY.value).strip()
            total_value = ins.text(Col.TOT_VALUE.value).strip() or "0"

            if is_non_investable_bucket:
                instrument: InstrumentPayload = {
                    "id": instrument_id,
                    "name": instrument_name,
                    "quantity": quantity,
                    "value": total_value,
                    "currency": get_item_currency(ins),
                    "investable": False,
                    "targetInGroupPercentage": "0",
                }
            else:
                instrument = {
                    "id": instrument_id,
                    "name": instrument_name,
                    "quantity": quantity,
                    "value": total_value,
                    "currency": get_item_currency(ins),
                    "investable": True,
                    "targetInGroupPercentage": ins.text(Col.TARGET_PCT.value).strip() or "0",
                }
                instrument["groupId"] = group_id

            instruments.append(instrument)

    return {
        "cash": {"value": cash_value, "min_reserve": cash_reserve, "future_tax": future_tax},
        "groups": groups,
        "instruments": instruments,
    }
