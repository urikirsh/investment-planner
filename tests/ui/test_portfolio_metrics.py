from __future__ import annotations

"""
Unit tests for `ui.portfolio_metrics`.

These tests validate pure recalculation behavior independently from Qt:
- normal group + non-investable rendering semantics
- denominator edge cases (zero totals)
"""

from decimal import Decimal

from ui.portfolio_metrics import (
    MetricGroupRow,
    MetricInstrumentRow,
    MetricsSnapshot,
    compute_portfolio_metrics,
)
from ui.ui_types import RowKind

D = Decimal


def test_compute_portfolio_metrics_group_and_non_investable_rows() -> None:
    """Verify strategy/portfolio/drift output for mixed investable and non-investable rows."""
    snapshot = MetricsSnapshot(
        groups=(
            MetricGroupRow(
                key="g1",
                kind=RowKind.GROUP,
                target_pct_text="60",
                instruments=(
                    MetricInstrumentRow(
                        key="i1",
                        kind=RowKind.INSTRUMENT,
                        value_text="600",
                        target_pct_text="100",
                    ),
                ),
            ),
            MetricGroupRow(
                key="bucket",
                kind=RowKind.NON_INVESTABLE_BUCKET,
                target_pct_text="0",
                instruments=(
                    MetricInstrumentRow(
                        key="i2",
                        kind=RowKind.INSTRUMENT,
                        value_text="400",
                        target_pct_text="",
                    ),
                ),
            ),
        ),
        cash_value_text="0",
        future_tax_text="0",
    )

    result = compute_portfolio_metrics(snapshot)

    assert result.top_total_by_key == {"g1": D("600"), "bucket": D("400")}
    assert result.portfolio_total == D("1000")
    assert result.strategy_total == D("600")
    assert result.portfolio_instruments_total == D("1000")

    assert result.portfolio_pct_text_by_key["g1"] == "60.0%"
    assert result.portfolio_pct_text_by_key["i1"] == "60.0%"
    assert result.portfolio_pct_text_by_key["bucket"] == "40.0%"
    assert result.portfolio_pct_text_by_key["i2"] == "40.0%"

    assert result.strategy_pct_text_by_key["g1"] == "100.0%"
    assert result.drift_text_by_key["g1"] == "+40.0 pp"
    assert result.drift_value_by_key["g1"] == D("40")

    assert result.strategy_pct_text_by_key["i1"] == "100.0%"
    assert result.drift_text_by_key["i1"] == "0.0 pp"
    assert result.drift_value_by_key["i1"] == D("0")

    assert result.target_pct_text_overrides_by_key["bucket"] == ""
    assert result.strategy_pct_text_by_key["bucket"] == ""
    assert result.drift_text_by_key["bucket"] == ""

    assert result.target_pct_text_overrides_by_key["i2"] == ""
    assert result.strategy_pct_text_by_key["i2"] == ""
    assert result.drift_text_by_key["i2"] == ""
    assert result.drift_value_by_key["i2"] == D("0")


def test_compute_portfolio_metrics_handles_zero_denominators() -> None:
    """Ensure empty denominators yield blank percentage/drift text safely."""
    snapshot = MetricsSnapshot(
        groups=(
            MetricGroupRow(
                key="g1",
                kind=RowKind.GROUP,
                target_pct_text="50",
                instruments=(
                    MetricInstrumentRow(
                        key="i1",
                        kind=RowKind.INSTRUMENT,
                        value_text="0",
                        target_pct_text="100",
                    ),
                ),
            ),
        ),
        cash_value_text="0",
        future_tax_text="0",
    )

    result = compute_portfolio_metrics(snapshot)

    assert result.top_total_by_key["g1"] == D("0")
    assert result.portfolio_total == D("0")
    assert result.strategy_total == D("0")
    assert result.portfolio_pct_text_by_key["g1"] == ""
    assert result.portfolio_pct_text_by_key["i1"] == ""
    assert result.strategy_pct_text_by_key["g1"] == ""
    assert result.drift_text_by_key["g1"] == ""
    assert result.strategy_pct_text_by_key["i1"] == ""
    assert result.drift_text_by_key["i1"] == ""
    assert result.drift_value_by_key["i1"] == D("0")
