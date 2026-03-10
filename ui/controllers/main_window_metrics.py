from __future__ import annotations

"""Derived-value refresh and metrics projection for the main editor."""

from decimal import Decimal

from PySide6.QtWidgets import QTreeWidgetItem

from ui.controllers.protocols import MainWindowMetricsHost
from ui.portfolio_editor_adapter import build_portfolio_data_from_main_editor
from ui.portfolio_metrics import (
    MetricGroupRow,
    MetricInstrumentRow,
    MetricsSnapshot,
    compute_portfolio_metrics,
)
from ui.ui_types import Col
from ui.ui_utils import BASE_CURRENCY_SUFFIX, apply_drift_color, get_item_kind, parse_value_cell

D = Decimal
MIN_INVESTABLE_AMOUNT_ILS = D("100")


class MainWindowMetricsController:
    """Controller containing main-editor recalculation and visual refresh logic."""

    def __init__(self, host: MainWindowMetricsHost) -> None:
        self._host = host

    def refresh_data(self) -> None:
        self.refresh_total_portfolio()
        self.update_investable_balance_visual_state()
        self.update_future_tax_visual_state()
        self.recalc_totals_and_pcts()

    def refresh_total_portfolio(self) -> None:
        host = self._host
        try:
            data = build_portfolio_data_from_main_editor(
                tree=host.tree,
                cash_value_edit=host.cash_value_edit,
                cash_reserve_edit=host.cash_reserve_edit,
                future_tax_edit=host.future_tax_edit,
                allow_partial=True,
            )
            cash_amt = D(str(data["cash"]["value"]))
            future_tax = D(str(data["cash"]["future_tax"]))
            total = cash_amt
            for ins in data.get("instruments", []):
                total += D(str(ins["value"]))
            total -= future_tax
            host.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: {total}")
        except Exception:
            host.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: -")

    def recalc_totals_and_pcts(self) -> None:
        host = self._host
        host._suppress_item_changed = True
        try:
            snapshot, item_by_key = self.build_metrics_snapshot()
            metrics = compute_portfolio_metrics(snapshot)

            for key, total in metrics.top_total_by_key.items():
                item_by_key[key].setText(Col.TOT_VALUE.value, str(total))
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
        finally:
            host._suppress_item_changed = False

    def normalize_future_tax_input(self) -> None:
        if not self._host.future_tax_edit.text().strip():
            self._host.future_tax_edit.setText("0")

    def update_future_tax_visual_state(self) -> None:
        future_tax = parse_value_cell(self._host.future_tax_edit.text())
        if future_tax > 0:
            self._host.future_tax_edit.setStyleSheet("color: #b00020;")
        else:
            self._host.future_tax_edit.setStyleSheet("")

    def update_investable_balance_visual_state(self) -> None:
        host = self._host
        cash_value = parse_value_cell(host.cash_value_edit.text())
        cash_reserve = parse_value_cell(host.cash_reserve_edit.text())
        future_tax = parse_value_cell(host.future_tax_edit.text())
        investable_balance = cash_value - cash_reserve - future_tax
        if investable_balance < 0:
            investable_balance = D("0")

        host.investable_balance_label.setText(f"Investable balance {BASE_CURRENCY_SUFFIX}: {investable_balance}")
        if investable_balance >= MIN_INVESTABLE_AMOUNT_ILS:
            host.investable_balance_label.setStyleSheet("color: #1b5e20;")
        else:
            host.investable_balance_label.setStyleSheet("color: #777777;")

    def build_metrics_snapshot(self) -> tuple[MetricsSnapshot, dict[str, QTreeWidgetItem]]:
        host = self._host
        groups: list[MetricGroupRow] = []
        item_by_key: dict[str, QTreeWidgetItem] = {}

        for i in range(host.tree.topLevelItemCount()):
            top = host.tree.topLevelItem(i)
            if top is None:
                continue

            top_key = f"top:{i}"
            item_by_key[top_key] = top
            top_kind = get_item_kind(top)

            instruments: list[MetricInstrumentRow] = []
            for j in range(top.childCount()):
                child = top.child(j)
                if child is None:
                    continue

                child_key = f"top:{i}:child:{j}"
                item_by_key[child_key] = child
                instruments.append(
                    MetricInstrumentRow(
                        key=child_key,
                        kind=get_item_kind(child),
                        value_text=child.text(Col.TOT_VALUE.value),
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
            cash_value_text=host.cash_value_edit.text(),
            future_tax_text=host.future_tax_edit.text(),
        )
        return snapshot, item_by_key
