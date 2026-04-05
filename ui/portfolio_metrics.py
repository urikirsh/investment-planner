"""
Pure metrics service for main-editor derived columns.

This module computes totals, percentages, and drift values from a snapshot of
main-editor rows. It contains no Qt dependencies and returns render-ready
strings plus numeric drift values for caller-managed styling.

Design notes
------------
 - Input uses plain dataclasses and typed numeric totals extracted from UI state.
- Output is render-oriented and includes both formatted strings and raw drift
  decimals so callers can style cells consistently without recomputing values.
- Behavior for non-investable rows is encoded here to keep UI orchestration
  focused on widget updates only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ui.shared.ui_types import RowKind
from ui.shared.ui_utils import fmt_pct, fmt_pp, parse_value_cell, safe_pct

D = Decimal


@dataclass(frozen=True)
class MetricInstrumentRow:
    """
    One instrument-row snapshot used for metrics computation.

    `kind` may be `None` for malformed/partial UI snapshots; such rows are
    ignored by computation logic.
    """

    key: str
    kind: RowKind | None
    value: D
    target_pct_text: str


@dataclass(frozen=True)
class MetricGroupRow:
    """
    One top-level row snapshot plus its instrument children.

    `kind` may be `None` for malformed/partial UI snapshots; such rows are
    ignored by computation logic.
    """

    key: str
    kind: RowKind | None
    target_pct_text: str
    instruments: tuple[MetricInstrumentRow, ...]


@dataclass(frozen=True)
class MetricsSnapshot:
    """Immutable input payload for one metrics computation pass."""

    groups: tuple[MetricGroupRow, ...]
    cash_value_text: str
    future_tax_text: str


@dataclass(frozen=True)
class MetricsResult:
    """
    Render-ready metrics output.

    Dictionaries are keyed by the caller-provided row keys so UI code can map
    values back to concrete widgets/items without relying on object identity.
    """

    top_total_by_key: dict[str, D]
    portfolio_pct_text_by_key: dict[str, str]
    strategy_pct_text_by_key: dict[str, str]
    drift_text_by_key: dict[str, str]
    drift_value_by_key: dict[str, D]
    target_pct_text_overrides_by_key: dict[str, str]
    portfolio_total: D
    portfolio_instruments_total: D
    strategy_total: D


def compute_portfolio_metrics(snapshot: MetricsSnapshot) -> MetricsResult:
    """
    Compute all derived main-editor values from immutable input rows.

    Rules implemented
    -----------------
    - Top-level totals are sums of instrument values per group/bucket.
    - Portfolio % uses:
      `portfolio_total = cash + all instruments - future_tax`.
    - Group Strategy % / Drift are computed only for real strategy groups.
    - Instrument Strategy % / Drift are computed within parent group scope.
    - Non-investable bucket rows and their instruments have strategy fields
      blanked and instrument target % blanked for UI display.
    """
    row_values: dict[str, D] = {}
    top_total_by_key: dict[str, D] = {}
    portfolio_pct_text_by_key: dict[str, str] = {}
    strategy_pct_text_by_key: dict[str, str] = {}
    drift_text_by_key: dict[str, str] = {}
    drift_value_by_key: dict[str, D] = {}
    target_pct_text_overrides_by_key: dict[str, str] = {}

    portfolio_instruments_total = D("0")
    strategy_total = D("0")
    group_keys: list[str] = []

    for top in snapshot.groups:
        if top.kind not in (RowKind.GROUP, RowKind.NON_INVESTABLE_BUCKET):
            continue

        total = D("0")
        for child in top.instruments:
            if child.kind != RowKind.INSTRUMENT:
                continue
            child_value = child.value
            total += child_value
            row_values[child.key] = child_value
            portfolio_instruments_total += child_value

        top_total_by_key[top.key] = total
        row_values[top.key] = total
        if top.kind == RowKind.GROUP:
            group_keys.append(top.key)
            strategy_total += total

    cash_value = parse_value_cell(snapshot.cash_value_text)
    future_tax = parse_value_cell(snapshot.future_tax_text)
    portfolio_total = cash_value + portfolio_instruments_total - future_tax

    for key, value in row_values.items():
        pct = safe_pct(value, portfolio_total)
        portfolio_pct_text_by_key[key] = "" if pct is None else fmt_pct(pct)

    for top in snapshot.groups:
        if top.key in group_keys:
            sp = safe_pct(row_values.get(top.key, D("0")), strategy_total)
            if sp is None:
                strategy_pct_text_by_key[top.key] = ""
                drift_text_by_key[top.key] = ""
            else:
                strategy_pct_text_by_key[top.key] = fmt_pct(sp)
                target = parse_value_cell(top.target_pct_text)
                drift = sp - target
                drift_text_by_key[top.key] = fmt_pp(drift)
                drift_value_by_key[top.key] = drift
        elif top.kind == RowKind.NON_INVESTABLE_BUCKET:
            target_pct_text_overrides_by_key[top.key] = ""
            strategy_pct_text_by_key[top.key] = ""
            drift_text_by_key[top.key] = ""

        group_total = row_values.get(top.key, D("0"))
        for child in top.instruments:
            if child.kind != RowKind.INSTRUMENT:
                continue

            if top.kind != RowKind.GROUP:
                target_pct_text_overrides_by_key[child.key] = ""
                strategy_pct_text_by_key[child.key] = ""
                drift_text_by_key[child.key] = ""
                drift_value_by_key[child.key] = D("0")
                continue

            child_sp = safe_pct(row_values.get(child.key, D("0")), group_total)
            if child_sp is None:
                strategy_pct_text_by_key[child.key] = ""
                drift_text_by_key[child.key] = ""
                drift_value_by_key[child.key] = D("0")
                continue

            strategy_pct_text_by_key[child.key] = fmt_pct(child_sp)
            child_target = parse_value_cell(child.target_pct_text)
            child_drift = child_sp - child_target
            drift_text_by_key[child.key] = fmt_pp(child_drift)
            drift_value_by_key[child.key] = child_drift

    return MetricsResult(
        top_total_by_key=top_total_by_key,
        portfolio_pct_text_by_key=portfolio_pct_text_by_key,
        strategy_pct_text_by_key=strategy_pct_text_by_key,
        drift_text_by_key=drift_text_by_key,
        drift_value_by_key=drift_value_by_key,
        target_pct_text_overrides_by_key=target_pct_text_overrides_by_key,
        portfolio_total=portfolio_total,
        portfolio_instruments_total=portfolio_instruments_total,
        strategy_total=strategy_total,
    )
