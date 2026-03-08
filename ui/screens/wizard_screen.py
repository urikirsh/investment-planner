"""
Wizard screen UI.

This module defines `WizardScreen`, the per-instrument execution view
(screen 3) used after summary review. It provides layout and widget creation
for step information, price entry, FX status/override inputs, calculation
feedback, and step actions.

Price-entry semantics:
- ILS steps use agorot input (`Price (Agorot)`), matching
  `portfolio_core.calc_stock_units.calculate_buy_units`.
- USD steps use USD unit-price input (`Price (USD)`), with conversion handled
  by the wizard FX coordinator before calculation.

All trade execution behavior is intentionally delegated to the coordinator.
"""

from __future__ import annotations

from portfolio_core.models import Currency, Exchange
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.ui_utils import DEFAULT_CURRENCY


DEFAULT_PRICE_LABEL = "Price (Agorot):"
USD_PRICE_LABEL = f"Price ({Exchange.NYSE.currency.value}):"
USD_ILS_MANUAL_RATE_LABEL = f"Manual {Exchange.NYSE.currency.value}/{DEFAULT_CURRENCY.value} rate:"


class WizardScreen(QWidget):
    """
    Wizard UI (screen 3).

    Exposes controls so the coordinator can attach flow behavior.
    Input units are intentionally explicit in labels to reduce cross-unit
    entry mistakes during wizard execution.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Invest per asset group")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.wiz_info = QLabel("-")
        self.wiz_info.setWordWrap(True)
        layout.addWidget(self.wiz_info)

        form = QWidget(self)
        form_layout = QFormLayout(form)
        self.price_label = QLabel(DEFAULT_PRICE_LABEL)
        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        form_layout.addRow(self.price_label, self.price_edit)

        self.fx_info_label = QLabel("")
        self.fx_info_label.setWordWrap(True)
        self.fx_info_label.setVisible(False)
        form_layout.addRow(self.fx_info_label)

        self.fx_error_label = QLabel("")
        self.fx_error_label.setWordWrap(True)
        self.fx_error_label.setStyleSheet("color: #b00020;")
        self.fx_error_label.setVisible(False)
        form_layout.addRow(self.fx_error_label)

        self.manual_rate_label = QLabel(USD_ILS_MANUAL_RATE_LABEL)
        self.manual_rate_label.setVisible(False)
        self.manual_rate_edit = QLineEdit()
        self.manual_rate_edit.setPlaceholderText("e.g. 3.65")
        self.manual_rate_edit.setVisible(False)
        form_layout.addRow(self.manual_rate_label, self.manual_rate_edit)
        layout.addWidget(form)

        calc_row = QWidget(self)
        calc_layout = QHBoxLayout(calc_row)
        self.calculate_btn = QPushButton("Calculate")
        calc_layout.addWidget(self.calculate_btn)

        self.wiz_result = QLabel("Units: - | Spent: - | Leftover vs plan: -")
        self.wiz_result.setWordWrap(True)
        calc_layout.addWidget(self.wiz_result, 1)
        layout.addWidget(calc_row)

        btns = QWidget(self)
        btns_layout = QHBoxLayout(btns)

        self.quit_btn = QPushButton("Quit")
        btns_layout.addWidget(self.quit_btn)

        self.save_continue_btn = QPushButton("Save and continue")
        btns_layout.addWidget(self.save_continue_btn)

        self.continue_without_save_btn = QPushButton("Continue without saving")
        btns_layout.addWidget(self.continue_without_save_btn)

        btns_layout.addStretch(1)
        layout.addWidget(btns)

    def set_price_mode(self, exchange: Exchange) -> None:
        """Configure price-label context for the current instrument exchange."""
        if exchange.currency == Currency.USD:
            self.price_label.setText(USD_PRICE_LABEL)
            self.price_edit.setPlaceholderText(f"Enter unit price in {Exchange.NYSE.currency.value} (e.g. 12.34)")
            return

        self.price_label.setText(DEFAULT_PRICE_LABEL)
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")

    def set_fx_panel(
        self,
        *,
        visible: bool,
        info_text: str,
        error_text: str,
        manual_visible: bool,
        manual_value: str = "",
    ) -> None:
        """
        Render USD FX status and manual-override controls.

        Parameters
        ----------
        visible:
            Controls whether FX panel rows are shown at all.
        info_text:
            Informational FX text (rate/date/source and fallback notes).
        error_text:
            Error message displayed when official FX fetch fails.
        manual_visible:
            Whether manual USD/ILS override controls should be shown.
        manual_value:
            Optional prefilled override value. When controls are visible this
            is always applied, including empty string, to avoid stale values.
        """
        self.fx_info_label.setVisible(visible)
        self.fx_error_label.setVisible(visible)
        self.manual_rate_label.setVisible(visible and manual_visible)
        self.manual_rate_edit.setVisible(visible and manual_visible)

        self.fx_info_label.setText(info_text)
        self.fx_error_label.setText(error_text)

        if manual_visible:
            # Always set explicitly while visible to avoid stale previous-run values.
            self.manual_rate_edit.setText(manual_value)
        else:
            self.manual_rate_edit.setText("")
