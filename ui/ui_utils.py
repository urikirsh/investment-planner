from __future__ import annotations

from decimal import Decimal, InvalidOperation
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTreeWidgetItem,
)
from PySide6.QtGui import QColor, QBrush

from ui.ui_types import ROLE_CURRENCY, ROLE_KIND, ROLE_ID, RowKind, Col

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
    """Parse a required Decimal from text and include field name in errors."""
    try:
        return D(txt.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number, got: {txt!r}")

def set_item_meta(item: QTreeWidgetItem, kind: RowKind, _id: str) -> None:
    """
    Attach semantic row metadata (kind/id) to a tree item.

    `kind` is stored directly as `RowKind` (a `StrEnum`) rather than as an
    untyped token, which keeps downstream reads type-safe.
    """
    item.setData(0, ROLE_KIND, kind)
    item.setData(0, ROLE_ID, _id)

def get_item_kind(item: QTreeWidgetItem) -> RowKind | None:
    """
    Return stored row kind as typed enum.

    Returns `None` if metadata is missing/corrupt so call sites can fail-soft
    in UI paths instead of throwing during enum conversion.
    """
    return RowKind.from_raw(item.data(0, ROLE_KIND))

def get_item_id(item: QTreeWidgetItem) -> str:
    """Return stored internal id string, or empty string if missing."""
    return item.data(0, ROLE_ID) or ""


def get_item_currency(item: QTreeWidgetItem) -> str:
    """Return stored instrument currency, defaulting to ILS."""
    text_value = (item.text(Col.CURRENCY.value) or "").strip()
    if text_value in ("ILS", "USD"):
        return text_value
    raw = item.data(0, ROLE_CURRENCY)
    if isinstance(raw, str) and raw in ("ILS", "USD"):
        return raw
    return "ILS"

def new_id(prefix: str) -> str:
    """Generate a short, pseudo-random id with a stable prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

def style_group_row(item: QTreeWidgetItem) -> None:
    """Apply visual styling for top-level group/bucket rows."""
    if get_item_kind(item) == RowKind.NON_INVESTABLE_BUCKET:
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
        Col.CURRENCY.value,
        Col.PORTFOLIO_PCT.value,
        Col.STRATEGY_PCT.value,
        Col.DRIFT_PP.value,
    ):
        set_cell_readonly_look(item, c)

def style_instrument_row(item: QTreeWidgetItem) -> None:
    """Apply read-only visual styling for derived instrument columns."""
    for c in (Col.PORTFOLIO_PCT.value, Col.STRATEGY_PCT.value, Col.DRIFT_PP.value):
        set_cell_readonly_look(item, c)

def apply_row_alignment(item: QTreeWidgetItem) -> None:
    """Apply per-column alignment conventions for group/instrument rows."""

    # Numbers are right-aligned for instruments, centered for groups
    for col in [Col.TOT_VALUE, Col.DRIFT_PP, Col.STRATEGY_PCT, Col.PORTFOLIO_PCT, Col.TARGET_PCT]:
        col_idx = col.value
        if get_item_kind(item) != RowKind.INSTRUMENT:
            item.setTextAlignment(
                col_idx,
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            )
        else:
            item.setTextAlignment(
                col_idx,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )

    item.setTextAlignment(
        Col.CURRENCY.value,
        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
    )

    # Text left-aligned
    item.setTextAlignment(
        Col.NAME.value,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )


def set_group_tree_item(gitem: QTreeWidgetItem,
                         name: str,
                         target_pct: Decimal | int | str,
                         id_str: str = "") -> None:
    """
    Initialize a top-level group/bucket row with metadata, style and defaults.

    The row is marked as non-editable by default; editing is temporarily enabled
    by higher-level UI handlers when needed.
    """
    gitem.setFlags(
        gitem.flags()
        | Qt.ItemFlag.ItemIsEditable
        | Qt.ItemFlag.ItemIsDragEnabled
        | Qt.ItemFlag.ItemIsDropEnabled
    )
    gitem.setText(Col.NAME.value, name)
    gitem.setText(Col.TOT_VALUE.value, "0")  # will be recalculated anyway
    gitem.setText(Col.CURRENCY.value, "")
    gitem.setText(Col.TARGET_PCT.value, str(target_pct))

    gid = id_str.strip() or new_id("grp")

    row_kind = RowKind.NON_INVESTABLE_BUCKET if id_str == NON_INVESTABLE_BUCKET_ID else RowKind.GROUP

    set_item_meta(gitem, row_kind, gid)
    disable_edits_to_row(gitem)

    apply_row_alignment(gitem)
    style_group_row(gitem)


def add_instrument_item_to_group(
        gitem: QTreeWidgetItem,
        name: str,
        value: str,
        in_group_pct: str,
        id_str: str = "",
        currency: str = "ILS",
) \
        -> None:
    """Create and initialize an instrument child row under the given parent group."""
    item = QTreeWidgetItem(gitem)
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
    item.setText(Col.NAME.value, name)
    item.setText(Col.TOT_VALUE.value, value)
    currency_value = currency if currency in ("ILS", "USD") else "ILS"
    item.setText(Col.CURRENCY.value, currency_value)
    item.setText(Col.TARGET_PCT.value, in_group_pct)

    iid = id_str.strip() or new_id("ins")
    set_item_meta(item, RowKind.INSTRUMENT, iid)
    item.setData(0, ROLE_CURRENCY, currency_value)

    apply_row_alignment(item)

    flags = item.flags()
    flags &= ~Qt.ItemFlag.ItemIsDropEnabled
    item.setFlags(flags)
    disable_edits_to_row(item)

    style_instrument_row(item)


def disable_edits_to_row(row: QTreeWidgetItem) -> None:
    """Disable in-place editing for all columns in a row."""
    flags = row.flags()
    flags &= ~Qt.ItemFlag.ItemIsEditable
    row.setFlags(flags)


def parse_value_cell(txt: str) -> D:
    """
    Parse numeric cell text defensively.

    Returns ``0`` for empty/invalid input so live UI calculations can proceed;
    strict validation happens separately before save/planning.
    """
    txt = (txt or "").strip()
    if not txt:
        return D("0")
    try:
        return D(txt)
    except (InvalidOperation, ValueError):
        # If user typed garbage, treat as 0 for sums, validation will catch later
        return D("0")

def fmt_pct(value: D) -> str:
    """Format a percentage value with one decimal place."""
    return f"{value:.1f}%"

def fmt_pp(value: D) -> str:
    """Format a drift value in percentage points with sign for positives."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f} pp"

def safe_pct(numer: D, denom: D) -> D | None:
    """Return ``numer/denom * 100`` or ``None`` for zero denominator."""
    if denom == 0:
        return None
    return (numer * D("100")) / denom

def apply_drift_color(item: QTreeWidgetItem, col_index: int, drift_pp: Decimal) -> None:
    """
    Color-code drift (percentage points):
    - Negative (under target): red
    - Positive (over target): green
    - Zero: default color
    """
    if drift_pp < 0:
        # Underweight -> red
        item.setForeground(col_index, QBrush(QColor("#b00020")))
    elif drift_pp > 0:
        # Overweight -> green
        item.setForeground(col_index, QBrush(QColor("#1b5e20")))
    else:
        # Neutral -> default
        set_cell_readonly_look(item, col_index)

def set_cell_readonly_look(item: QTreeWidgetItem, col: int) -> None:
    """Apply neutral read-only foreground color to a single cell."""
    item.setForeground(col, QBrush(QColor("#777777")))

def _is_cell_editable(kind: RowKind | None, col: int) -> bool:
    """Return whether a cell is user-editable for a given row kind/column."""
    if kind == RowKind.GROUP:
        return col in (Col.NAME.value, Col.TARGET_PCT.value)

    if kind == RowKind.INSTRUMENT:
        return col in (Col.NAME.value, Col.TOT_VALUE.value, Col.CURRENCY.value, Col.TARGET_PCT.value)

    # bucket
    return False
