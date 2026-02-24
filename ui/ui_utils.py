from __future__ import annotations

from decimal import Decimal, InvalidOperation
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QComboBox
)
from PySide6.QtGui import QColor, QBrush

from ui.ui_types import ROLE_KIND, ROLE_ID, RowKind, Col

"""
ui_utils.py

Reusable helper functions for the UI layer.

This module contains small, focused utilities used by UI components,
such as styling helpers, formatting functions, and minor UI-related
logic that does not belong in widget classes themselves.

No business logic or persistence logic belongs in this module.
"""

D = Decimal

NON_INVESTABLE_BUCKET_ID = "non_investable_bucket"

def d_from_text(txt: str, field: str) -> D:
    try:
        return D(txt.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number, got: {txt!r}")

def set_item_meta(item: QTreeWidgetItem, kind: str, _id: str) -> None:
    item.setData(0, ROLE_KIND, kind)
    item.setData(0, ROLE_ID, _id)

def get_item_kind(item: QTreeWidgetItem) -> str:
    return item.data(0, ROLE_KIND) or ""

def get_item_id(item: QTreeWidgetItem) -> str:
    return item.data(0, ROLE_ID) or ""

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

def style_group_row(item: QTreeWidgetItem) -> None:
    if get_item_kind(item) == RowKind.NON_INVESTABLE_BUCKET.name:
        background = QBrush(QColor("#e8f0ff")) # subtle blue tint
    else:
        background = QBrush(QColor("#f0f0f0"))

    for col in range(item.columnCount()):
        font = item.font(col)
        font.setBold(True)
        item.setFont(col, font)

        item.setBackground(col, background)

    for c in (
        Col.TOT_VALUE.value,
        Col.PORTFOLIO_PCT.value,
        Col.STRATEGY_PCT.value,
        Col.DRIFT_PP.value,
        Col.IN_GROUP_PCT.value,
    ):
        set_cell_readonly_look(item, c)

def style_instrument_row(item: QTreeWidgetItem) -> None:
    for c in (Col.TARGET_PCT.value, Col.PORTFOLIO_PCT.value, Col.STRATEGY_PCT.value, Col.DRIFT_PP.value):
        set_cell_readonly_look(item, c)

def apply_row_alignment(item: QTreeWidgetItem) -> None:

    # Numbers are right-aligned for instruments, centered for groups
    for col in [Col.TOT_VALUE, Col.DRIFT_PP, Col.STRATEGY_PCT, Col.PORTFOLIO_PCT, Col.TARGET_PCT, Col.IN_GROUP_PCT]:
        col_idx = col.value
        if get_item_kind(item) != RowKind.INSTRUMENT.name:
            item.setTextAlignment(col_idx, Qt.AlignCenter | Qt.AlignVCenter)
        else:
            item.setTextAlignment(col_idx, Qt.AlignRight | Qt.AlignVCenter)

    # Text left-aligned
    item.setTextAlignment(Col.NAME.value, Qt.AlignLeft | Qt.AlignVCenter)
    item.setTextAlignment(Col.PREFERRED_INSTR.value, Qt.AlignLeft | Qt.AlignVCenter)


def set_group_tree_item(tree: QTreeWidget,
                         gitem: QTreeWidgetItem,
                         name: str,
                         target_pct: int,
                         id_str: str = "") -> None:
    gitem.setFlags(gitem.flags() | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
    gitem.setText(Col.NAME.value, name)
    gitem.setText(Col.TOT_VALUE.value, "0")  # will be recalculated anyway
    gitem.setText(Col.TARGET_PCT.value, str(target_pct))
    gitem.setText(Col.IN_GROUP_PCT.value, "")

    combo = QComboBox()
    tree.setItemWidget(gitem, Col.PREFERRED_INSTR.value, combo)

    gid = id_str.strip() or new_id("grp")

    row_kind = RowKind.NON_INVESTABLE_BUCKET.name if id_str == NON_INVESTABLE_BUCKET_ID else RowKind.GROUP.name

    set_item_meta(gitem, row_kind, gid)
    disable_edits_to_row(gitem)

    apply_row_alignment(gitem)
    style_group_row(gitem)


def add_instrument_item_to_group(
        gitem: QTreeWidgetItem, name: str, value: str, in_group_pct: str, id_str: str = ""
) \
        -> None:
    item = QTreeWidgetItem(gitem)
    item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
    item.setText(Col.NAME.value, name)
    item.setText(Col.TOT_VALUE.value, value)
    item.setText(Col.TARGET_PCT.value, "")
    item.setText(Col.IN_GROUP_PCT.value, in_group_pct)
    item.setText(Col.PREFERRED_INSTR.value, "")

    iid = id_str.strip() or new_id("ins")
    set_item_meta(item, RowKind.INSTRUMENT.name, iid)

    apply_row_alignment(item)

    flags = item.flags()
    flags &= ~Qt.ItemIsDropEnabled
    item.setFlags(flags)
    disable_edits_to_row(item)

    style_instrument_row(item)


def disable_edits_to_row(row: QTreeWidgetItem) -> None:
    flags = row.flags()
    flags &= ~Qt.ItemIsEditable
    row.setFlags(flags)


def parse_value_cell(txt: str) -> D:
    txt = (txt or "").strip()
    if not txt:
        return D("0")
    try:
        return D(txt)
    except (InvalidOperation, ValueError):
        # If user typed garbage, treat as 0 for sums, validation will catch later
        return D("0")

def fmt_pct(value: D) -> str:
    # standard rounding to 1 decimal
    return f"{value:.1f}%"

def fmt_pp(value: D) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f} pp"

def safe_pct(numer: D, denom: D) -> D | None:
    if denom == 0:
        return None
    return (numer * D("100")) / denom

def apply_drift_color(item, col_index: int, drift_pp: Decimal) -> None:
    """
    Color-code drift (percentage points):
    - Negative (under target): red
    - Positive (over target): green
    - Zero: default color
    """
    if drift_pp < 0:
        # Underweight → red
        item.setForeground(col_index, QBrush(QColor("#b00020")))
    elif drift_pp > 0:
        # Overweight → green
        item.setForeground(col_index, QBrush(QColor("#1b5e20")))
    else:
        # Neutral → default
        set_cell_readonly_look(item, col_index)

def set_cell_readonly_look(item, col: int) -> None:
    # light gray text
    item.setForeground(col, QBrush(QColor("#777777")))

def _is_cell_editable(kind: str, col: int) -> bool:
    if kind == RowKind.GROUP.name:
        return col in (Col.NAME.value, Col.TARGET_PCT.value)

    if kind == RowKind.INSTRUMENT.name:
        return col in (Col.NAME.value, Col.TOT_VALUE.value, Col.IN_GROUP_PCT.value)

    # bucket
    return False
