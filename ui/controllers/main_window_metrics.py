from __future__ import annotations

"""Derived-value refresh and metrics projection for the main editor."""

from decimal import Decimal

from PySide6.QtWidgets import QLineEdit, QLabel, QTreeWidget, QTreeWidgetItem

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


class MainWindowMetricsMixin:
    """Mixin containing main-editor recalculation and visual refresh logic."""

    _suppress_item_changed: bool
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    investable_balance_label: QLabel
    total_label: QLabel

    def _refresh_data(self) -> None:
        """Refresh all derived main-screen values and visuals from current inputs."""
        self._refresh_total_portfolio()
        self._update_investable_balance_visual_state()
        self._update_future_tax_visual_state()
        self._recalc_totals_and_pcts()

    def _refresh_total_portfolio(self) -> None:
        """Update total-portfolio label from current editable UI values."""
        try:
            data = build_portfolio_data_from_main_editor(
                tree=self.tree,
                cash_value_edit=self.cash_value_edit,
                cash_reserve_edit=self.cash_reserve_edit,
                future_tax_edit=self.future_tax_edit,
                allow_partial=True,
            )
            cash_amt = D(str(data["cash"]["value"]))
            future_tax = D(str(data["cash"]["future_tax"]))
            total = cash_amt
            for ins in data.get("instruments", []):
                total += D(str(ins["value"]))
            total -= future_tax
            self.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: {total}")
        except Exception:
            self.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: -")

    def _recalc_totals_and_pcts(self) -> None:
        """Recompute all derived table values from editable inputs."""
        self._suppress_item_changed = True
        try:
            snapshot, item_by_key = self._build_metrics_snapshot()
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
            self._suppress_item_changed = False

    def _normalize_future_tax_input(self) -> None:
        """Normalize empty future-tax input to zero on edit completion."""
        if not self.future_tax_edit.text().strip():
            self.future_tax_edit.setText("0")

    def _update_future_tax_visual_state(self) -> None:
        """Highlight future-tax field when value is positive."""
        future_tax = parse_value_cell(self.future_tax_edit.text())
        if future_tax > 0:
            self.future_tax_edit.setStyleSheet("color: #b00020;")
        else:
            self.future_tax_edit.setStyleSheet("")

    def _update_investable_balance_visual_state(self) -> None:
        """Show investable balance and color-code against minimum investable amount."""
        cash_value = parse_value_cell(self.cash_value_edit.text())
        cash_reserve = parse_value_cell(self.cash_reserve_edit.text())
        future_tax = parse_value_cell(self.future_tax_edit.text())
        investable_balance = cash_value - cash_reserve - future_tax
        if investable_balance < 0:
            investable_balance = D("0")

        self.investable_balance_label.setText(f"Investable balance {BASE_CURRENCY_SUFFIX}: {investable_balance}")
        if investable_balance >= MIN_INVESTABLE_AMOUNT_ILS:
            self.investable_balance_label.setStyleSheet("color: #1b5e20;")
        else:
            self.investable_balance_label.setStyleSheet("color: #777777;")

    def _build_metrics_snapshot(self) -> tuple[MetricsSnapshot, dict[str, QTreeWidgetItem]]:
        """Build pure metrics input plus key->item lookup for UI render updates."""
        groups: list[MetricGroupRow] = []
        item_by_key: dict[str, QTreeWidgetItem] = {}

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
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
            cash_value_text=self.cash_value_edit.text(),
            future_tax_text=self.future_tax_edit.text(),
        )
        return snapshot, item_by_key
