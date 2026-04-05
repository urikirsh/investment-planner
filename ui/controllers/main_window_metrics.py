from __future__ import annotations

"""Derived-value refresh and metrics projection for the main editor."""

from collections.abc import Iterator
from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import QTreeWidgetItem

from portfolio_core.domain.models import Exchange
from ui.controllers.protocols import MainWindowMetricsHost, suppress_item_changed
from ui.portfolio_editor_adapter import PortfolioPayload, build_portfolio_data_from_main_editor
from ui.portfolio_metrics import (
    MetricGroupRow,
    MetricInstrumentRow,
    MetricsSnapshot,
    compute_portfolio_metrics,
)
from ui.shared.ui_types import Col
from ui.shared.cached_instrument_pricing import resolve_cached_instrument_price_ils
from ui.shared.ui_utils import (
    BASE_CURRENCY_SUFFIX,
    apply_drift_color,
    fmt_decimal_grouped,
    get_decimal_line_edit_raw_text,
    get_decimal_line_edit_value,
    get_item_exchange,
    get_item_kind,
    get_item_total_value,
    parse_display_non_negative_integer,
    parse_value_cell,
    set_item_total_value,
)

D = Decimal
MIN_INVESTABLE_AMOUNT_ILS = D("100")
_TABLE_VALUE_PRECISION = D("0.01")


class MainWindowMetricsController:
    """Controller containing main-editor recalculation and visual refresh logic."""

    def __init__(self, host: MainWindowMetricsHost) -> None:
        self._host = host

    @staticmethod
    def _compute_total_portfolio_amount(data: PortfolioPayload) -> D:
        """Return total portfolio amount after subtracting future tax from assets."""
        cash = data["cash"]
        cash_amt = D(str(cash["value"]))
        future_tax = D(str(cash["future_tax"]))
        total = cash_amt
        instruments = data["instruments"]
        for ins in instruments:
            total += D(str(ins["value"]))
        return total - future_tax

    def refresh_data(self) -> None:
        """Refresh all derived editor values that depend on current table/cash inputs."""
        self._recompute_instrument_row_values()
        self.refresh_total_portfolio()
        self.update_investable_balance_visual_state()
        self.update_future_tax_visual_state()
        self.recalc_totals_and_pcts()

    def _recompute_instrument_row_values(self) -> None:
        """Recompute every instrument row value from cached prices."""
        with suppress_item_changed(self._host):
            for _top_key, _top, instrument_rows in self._iter_top_rows_with_instruments():
                for _child_key, child in instrument_rows:
                    set_item_total_value(child, self._compute_instrument_total_value_ils(child))

    def _compute_instrument_total_value_ils(self, item: QTreeWidgetItem) -> D:
        """Return one instrument row's total value in ILS from cached market data."""
        quantity_text = item.text(Col.QUANTITY.value).strip()
        quantity = parse_display_non_negative_integer(quantity_text)
        if quantity == 0:
            return D("0.00")

        exchange = Exchange(get_item_exchange(item))
        ticker = item.text(Col.TICKER.value).strip()
        instrument_name = item.text(Col.NAME.value).strip() or ticker or "instrument"
        cached_quote = self._host.session.cached_usd_ils_quote
        unit_price_ils = resolve_cached_instrument_price_ils(
            exchange=exchange,
            ticker=ticker,
            instrument_name=instrument_name,
            usd_ils_rate=None if cached_quote is None else cached_quote.rate,
        )
        value_ils = unit_price_ils * D(quantity)
        return value_ils.quantize(_TABLE_VALUE_PRECISION)

    def refresh_total_portfolio(self) -> None:
        """Recompute and render total portfolio label, tolerating partial/invalid input."""
        host = self._host
        try:
            data = build_portfolio_data_from_main_editor(
                tree=host.tree,
                cash_value_edit=host.cash_value_edit,
                cash_reserve_edit=host.cash_reserve_edit,
                future_tax_edit=host.future_tax_edit,
                allow_partial=True,
            )
            total = self._compute_total_portfolio_amount(data)
            host.total_label.setText(
                f"Total portfolio {BASE_CURRENCY_SUFFIX}: {fmt_decimal_grouped(total)}"
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            host.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: -")

    def recalc_totals_and_pcts(self) -> None:
        """Recompute group/instrument metrics and write them back to table cells."""
        with suppress_item_changed(self._host):
            snapshot, item_by_key = self.build_metrics_snapshot()
            metrics = compute_portfolio_metrics(snapshot)

            for key, total in metrics.top_total_by_key.items():
                set_item_total_value(item_by_key[key], total)
            for key, text in metrics.portfolio_pct_text_by_key.items():
                item_by_key[key].setText(Col.PORTFOLIO_PCT.value, text)
            for key, text in metrics.strategy_pct_text_by_key.items():
                item_by_key[key].setText(Col.STRATEGY_PCT.value, text)
            for key, text in metrics.drift_text_by_key.items():
                item_by_key[key].setText(Col.DRIFT_PP.value, text)
            for key, text in metrics.target_pct_text_overrides_by_key.items():
                item_by_key[key].setText(Col.TARGET_PCT.value, text)
            for key, drift in metrics.drift_value_by_key.items():
                apply_drift_color(item_by_key[key], Col.DRIFT_PP.value, drift)

    def normalize_future_tax_input(self) -> None:
        """Normalize blank future-tax input to ``0`` for downstream numeric parsing."""
        if not get_decimal_line_edit_raw_text(self._host.future_tax_edit):
            self._host.future_tax_edit.setText("0")

    def update_future_tax_visual_state(self) -> None:
        """Apply warning color when future tax is positive, clear style otherwise."""
        future_tax = get_decimal_line_edit_value(self._host.future_tax_edit)
        if future_tax > 0:
            self._host.future_tax_edit.setStyleSheet("color: #b00020;")
        else:
            self._host.future_tax_edit.setStyleSheet("")

    def update_investable_balance_visual_state(self) -> None:
        """Recompute investable balance text and color by minimum-investable threshold."""
        host = self._host
        cash_value = get_decimal_line_edit_value(host.cash_value_edit)
        cash_reserve = get_decimal_line_edit_value(host.cash_reserve_edit)
        future_tax = get_decimal_line_edit_value(host.future_tax_edit)
        investable_balance = cash_value - cash_reserve - future_tax
        if investable_balance < 0:
            investable_balance = D("0")

        host.investable_balance_label.setText(
            f"Investable balance {BASE_CURRENCY_SUFFIX}: {fmt_decimal_grouped(investable_balance)}"
        )
        if investable_balance >= MIN_INVESTABLE_AMOUNT_ILS:
            host.investable_balance_label.setStyleSheet("color: #1b5e20;")
        else:
            host.investable_balance_label.setStyleSheet("color: #777777;")

    def _iter_top_rows_with_instruments(
        self,
    ) -> Iterator[tuple[str, QTreeWidgetItem, tuple[tuple[str, QTreeWidgetItem], ...]]]:
        """Yield top-level tree rows with stable keys and child rows in UI order."""
        host = self._host
        for i in range(host.tree.topLevelItemCount()):
            top = host.tree.topLevelItem(i)
            if top is None:
                continue

            top_key = f"top:{i}"
            child_rows: list[tuple[str, QTreeWidgetItem]] = []
            for j in range(top.childCount()):
                child = top.child(j)
                if child is None:
                    continue
                child_rows.append((f"top:{i}:child:{j}", child))

            yield top_key, top, tuple(child_rows)

    def build_metrics_snapshot(self) -> tuple[MetricsSnapshot, dict[str, QTreeWidgetItem]]:
        """Build metrics input snapshot and UI item index for write-back.

        Returns:
            A tuple of:
            - ``MetricsSnapshot`` with immutable group/instrument metric inputs.
            - ``item_by_key`` mapping stable traversal keys to concrete tree items.

        Key format:
            - Top-level group rows: ``top:{i}``
            - Instrument child rows: ``top:{i}:child:{j}``

        The key convention intentionally matches the keys emitted by
        ``compute_portfolio_metrics`` so recalculated texts/colors can be
        applied back to the correct ``QTreeWidgetItem`` without a second tree
        traversal.
        """
        host = self._host
        groups: list[MetricGroupRow] = []
        item_by_key: dict[str, QTreeWidgetItem] = {}

        for top_key, top, instrument_rows in self._iter_top_rows_with_instruments():
            item_by_key[top_key] = top
            top_kind = get_item_kind(top)

            instruments: list[MetricInstrumentRow] = []
            for child_key, child in instrument_rows:
                item_by_key[child_key] = child
                instruments.append(
                    MetricInstrumentRow(
                        key=child_key,
                        kind=get_item_kind(child),
                        value=get_item_total_value(child),
                        target_pct_text=child.text(Col.TARGET_PCT.value),
                    )
                )

            groups.append(
                MetricGroupRow(
                    key=top_key,
                    kind=top_kind,
                    target_pct_text=top.text(Col.TARGET_PCT.value),
                    instruments=tuple(instruments),
                )
            )

        snapshot = MetricsSnapshot(
            groups=tuple(groups),
            cash_value_text=str(get_decimal_line_edit_value(host.cash_value_edit)),
            future_tax_text=str(get_decimal_line_edit_value(host.future_tax_edit)),
        )
        return snapshot, item_by_key
