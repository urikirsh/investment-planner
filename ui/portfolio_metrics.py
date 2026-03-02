"""
Pure metrics service for main-editor derived columns.

This module computes totals, percentages, and drift values from a snapshot of
main-editor rows. It contains no Qt dependencies and returns render-ready
strings plus numeric drift values for caller-managed styling.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ui.ui_types import RowKind
from ui.ui_utils import fmt_pct, fmt_pp, parse_value_cell, safe_pct

D = Decimal


@dataclass(frozen=True)
class MetricInstrumentRow:
    key: str
    kind: str
    value_text: str
    target_pct_text: str


@dataclass(frozen=True)
class MetricGroupRow:
    key: str
    kind: str
    target_pct_text: str
    instruments: tuple[MetricInstrumentRow, ...]


@dataclass(frozen=True)
class MetricsSnapshot:
    groups: tuple[MetricGroupRow, ...]
    cash_value_text: str
    future_tax_text: str


@dataclass(frozen=True)
class MetricsResult:
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
    """Compute all derived main-editor values from immutable input rows."""
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
        if top.kind not in (RowKind.GROUP.name, RowKind.NON_INVESTABLE_BUCKET.name):
            continue

        total = D("0")
        for child in top.instruments:
            if child.kind != RowKind.INSTRUMENT.name:
                continue
            child_value = parse_value_cell(child.value_text)
            total += child_value
            row_values[child.key] = child_value
            portfolio_instruments_total += child_value

        top_total_by_key[top.key] = total
        row_values[top.key] = total
        if top.kind == RowKind.GROUP.name:
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
        elif top.kind == RowKind.NON_INVESTABLE_BUCKET.name:
            target_pct_text_overrides_by_key[top.key] = ""
            strategy_pct_text_by_key[top.key] = ""
            drift_text_by_key[top.key] = ""

        group_total = row_values.get(top.key, D("0"))
        for child in top.instruments:
            if child.kind != RowKind.INSTRUMENT.name:
                continue

            if top.kind != RowKind.GROUP.name:
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

