from __future__ import annotations

from decimal import Decimal, InvalidOperation
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTreeWidgetItem,
)
from PySide6.QtGui import QColor, QBrush

from portfolio_core.domain.models import Currency, Exchange
from ui.shared.ui_types import ROLE_KIND, ROLE_ID, ROLE_TOTAL_VALUE, RowKind, Col

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
DEFAULT_CURRENCY = Currency.ILS
DEFAULT_EXCHANGE = Exchange.TASE
BASE_CURRENCY_SUFFIX = f"({DEFAULT_CURRENCY.value})"
FIXED_CELL_BG_COLOR = "#fff7e6"


def exchange_choices() -> tuple[str, ...]:
    """Return allowed exchange codes for UI editors and validations."""
    return tuple(exchange.value for exchange in Exchange)


def parse_exchange_code(raw: object) -> str | None:
    """Parse a raw value into a supported exchange code, or ``None``."""
    if isinstance(raw, Exchange):
        return raw.value
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper()
    if not normalized:
        return None
    try:
        return Exchange(normalized).value
    except ValueError:
        return None


def currency_for_exchange(exchange_code: str) -> Currency:
    """Resolve currency for a validated exchange code."""
    return Exchange(exchange_code).currency

def d_from_text(txt: str, field: str) -> D:
    """Parse a required Decimal from text and include field name in errors."""
    try:
        return D(txt.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number, got: {txt!r}")


def validate_non_negative_integer_text(
    text: str,
    *,
    field_label: str,
    required: bool,
) -> tuple[int | None, str]:
    """Validate integer text and return `(value, error_message)`."""
    normalized = text.strip()
    if not normalized:
        if required:
            return None, f"{field_label} is required."
        return None, ""
    if not normalized.isdigit():
        return None, f"{field_label} must be a non-negative integer."
    return int(normalized), ""


def normalize_and_validate_non_negative_integer_text(
    text: str,
    *,
    field_label: str,
    required: bool,
    blank_normalized_text: str | None = None,
) -> tuple[str, int | None, str]:
    """Normalize integer text and return `(normalized_text, value, error_message)`."""
    normalized = text.strip()
    effective_text = blank_normalized_text if not normalized and blank_normalized_text is not None else normalized
    parsed_value, parse_error = validate_non_negative_integer_text(
        effective_text,
        field_label=field_label,
        required=required,
    )
    return effective_text, parsed_value, parse_error

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


def set_item_total_value(item: QTreeWidgetItem, value: D) -> None:
    """Store and render one row's computed total value."""
    normalized = D(value)
    item.setData(Col.TOT_VALUE.value, ROLE_TOTAL_VALUE, str(normalized))
    item.setText(Col.TOT_VALUE.value, fmt_decimal_grouped(normalized))


def get_item_total_value(item: QTreeWidgetItem) -> D:
    """Return a row's raw total value, preferring typed item metadata over display text."""
    raw_value = item.data(Col.TOT_VALUE.value, ROLE_TOTAL_VALUE)
    if isinstance(raw_value, str):
        try:
            return D(raw_value)
        except (InvalidOperation, ValueError):
            pass
    return parse_value_cell(item.text(Col.TOT_VALUE.value))


def get_item_exchange(item: QTreeWidgetItem) -> str:
    """
    Return a valid instrument exchange code from visible text, defaulting to TASE.
    """
    parsed_text = parse_exchange_code(item.text(Col.EXCHANGE.value))
    if parsed_text is not None:
        return parsed_text
    return DEFAULT_EXCHANGE.value

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
        Col.QUANTITY.value,
        Col.TOT_VALUE.value,
        Col.EXCHANGE.value,
        Col.PORTFOLIO_PCT.value,
        Col.STRATEGY_PCT.value,
        Col.DRIFT_PP.value,
    ):
        set_cell_readonly_look(item, c)

def style_instrument_row(item: QTreeWidgetItem) -> None:
    """Apply computed/fixed visual styling for instrument rows."""
    for c in (Col.TOT_VALUE.value, Col.PORTFOLIO_PCT.value, Col.STRATEGY_PCT.value, Col.DRIFT_PP.value):
        set_cell_readonly_look(item, c)
    for c in (Col.TICKER.value, Col.TOT_VALUE.value, Col.EXCHANGE.value):
        if not is_item_cell_editable(item, c):
            set_cell_fixed_look(item, c)

def apply_row_alignment(item: QTreeWidgetItem) -> None:
    """Apply per-column alignment conventions for group/instrument rows."""

    # Numbers are right-aligned for instruments, centered for groups
    for col in [Col.QUANTITY, Col.TOT_VALUE, Col.DRIFT_PP, Col.STRATEGY_PCT, Col.PORTFOLIO_PCT, Col.TARGET_PCT]:
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
        Col.EXCHANGE.value,
        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
    )

    # Text left-aligned
    item.setTextAlignment(
        Col.TICKER.value,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
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
    gitem.setText(Col.TICKER.value, "")
    gitem.setText(Col.NAME.value, name)
    gitem.setText(Col.QUANTITY.value, "")
    set_item_total_value(gitem, D("0"))  # will be recalculated anyway
    gitem.setText(Col.EXCHANGE.value, "")
    gitem.setText(Col.TARGET_PCT.value, str(target_pct))

    gid = id_str.strip() or new_id("grp")

    row_kind = RowKind.NON_INVESTABLE_BUCKET if id_str == NON_INVESTABLE_BUCKET_ID else RowKind.GROUP

    set_item_meta(gitem, row_kind, gid)
    disable_edits_to_row(gitem)

    apply_row_alignment(gitem)
    style_group_row(gitem)


def add_instrument_item_to_group(
        gitem: QTreeWidgetItem,
        ticker: str,
        name: str,
        quantity: int,
        in_group_pct: str,
        id_str: str = "",
        exchange: str = DEFAULT_EXCHANGE.value,
) \
        -> None:
    """Create an instrument child row with default computed-cell values."""
    item = QTreeWidgetItem(gitem)
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
    ticker_text = ticker.strip()
    quantity_text = str(quantity)
    item.setText(Col.TICKER.value, ticker_text)
    item.setText(Col.NAME.value, name)
    item.setText(Col.QUANTITY.value, quantity_text)
    set_item_total_value(item, D("0"))
    exchange_value = parse_exchange_code(exchange) or DEFAULT_EXCHANGE.value
    item.setText(Col.EXCHANGE.value, exchange_value)
    item.setText(Col.TARGET_PCT.value, in_group_pct)

    iid = id_str.strip() or new_id("ins")
    set_item_meta(item, RowKind.INSTRUMENT, iid)

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
    txt = (txt or "").strip().replace(",", "")
    if not txt:
        return D("0")
    try:
        return D(txt)
    except (InvalidOperation, ValueError):
        # If user typed garbage, treat as 0 for sums, validation will catch later
        return D("0")

def fmt_decimal_grouped(value: D, *, places: int | None = None, trim_trailing_zeros: bool = False) -> str:
    """Format a decimal with comma grouping and optional fixed/trimmed decimals."""
    quantized = value
    if places is not None:
        quantized = value.quantize(D("1").scaleb(-places))
    text = format(quantized, "f")
    if trim_trailing_zeros and "." in text:
        text = text.rstrip("0").rstrip(".")

    integer_part, dot, fractional_part = text.partition(".")
    grouped_integer = f"{int(integer_part):,}"
    if not dot:
        return grouped_integer
    return f"{grouped_integer}.{fractional_part}"

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
        # Underweight -> lighter red for contrast against dark bold text
        item.setForeground(col_index, QBrush(QColor("#d16a7a")))
    elif drift_pp > 0:
        # Overweight -> green
        item.setForeground(col_index, QBrush(QColor("#1b5e20")))
    else:
        # Neutral -> default
        set_cell_readonly_look(item, col_index)

def set_cell_readonly_look(item: QTreeWidgetItem, col: int) -> None:
    """Apply neutral read-only foreground color to a single cell."""
    item.setForeground(col, QBrush(QColor("#777777")))


def set_cell_fixed_look(item: QTreeWidgetItem, col: int) -> None:
    """Apply subtle background tint for user-visible fixed cells."""
    item.setBackground(col, QBrush(QColor(FIXED_CELL_BG_COLOR)))

def is_item_cell_editable(item: QTreeWidgetItem, col: int) -> bool:
    """Return whether an item's cell is editable, including parent-context rules."""
    kind = get_item_kind(item)

    if kind == RowKind.GROUP:
        return col in (Col.NAME.value, Col.TARGET_PCT.value)

    if kind != RowKind.INSTRUMENT:
        return False

    if kind == RowKind.INSTRUMENT and col == Col.TARGET_PCT.value:
        parent = item.parent()
        if parent is not None and get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            return False

    return col in (
        Col.NAME.value,
        Col.QUANTITY.value,
        Col.TARGET_PCT.value,
    )
