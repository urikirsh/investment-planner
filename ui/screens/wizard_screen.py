"""
Wizard screen UI.

This module defines `WizardScreen`, the per-instrument execution view
(screen 4) used after summary review. It provides layout and widget creation
for step information, price entry, FX status/override inputs, calculation
feedback, and step actions.

Action-row intent:
- `Quit` is kept on the far left as an application-level action.
- Wizard-step actions are grouped on the right:
  `Exit Wizard` and `Skip Step`.
- Primary step commit action (`Save and continue`) is grouped with result data
  in a centered row to keep attention on the decision point.

Price-entry semantics:
- ILS steps use agorot input (`Price (Agorot)`), matching
  `portfolio_core.calc_stock_units.calculate_buy_units`.
- USD steps use USD unit-price input (`Price (USD)`), with conversion handled
  by the wizard FX coordinator before calculation.

All trade execution behavior is intentionally delegated to the coordinator.
"""

from __future__ import annotations

from portfolio_core.models import Currency, Exchange
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui.shared.ui_utils import DEFAULT_CURRENCY


DEFAULT_PRICE_LABEL = "Price (Agorot):"
USD_PRICE_LABEL = f"Price ({Exchange.NYSE.currency.value}):"
USD_ILS_MANUAL_RATE_LABEL = f"Manual {Exchange.NYSE.currency.value}/{DEFAULT_CURRENCY.value} rate:"


class WizardScreen(QWidget):
    """
    Wizard UI (screen 4).

    Exposes controls so the coordinator can attach flow behavior.
    Input units are intentionally explicit in labels to reduce cross-unit
    entry mistakes during wizard execution.
    The action row intentionally separates app-level and step-level actions
    to reduce accidental exits during step execution.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Execute Plan Step")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel("Review the step details, calculate units, then apply or skip this step.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(subtitle)

        info_card = QWidget(self)
        info_card.setStyleSheet("background: #f5f7fa; border: 1px solid #d8dde6; border-radius: 6px;")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(10, 8, 10, 8)
        info_layout.setSpacing(6)

        self.step_progress = QLabel("Step -/-")
        self.step_progress.setStyleSheet("font-size: 12px; font-weight: 600; color: #34495e;")
        info_layout.addWidget(self.step_progress)

        self.wiz_info = QLabel("-")
        self.wiz_info.setWordWrap(True)
        info_layout.addWidget(self.wiz_info)
        layout.addWidget(info_card)

        form = QWidget(self)
        form_layout = QFormLayout(form)
        form_layout.setVerticalSpacing(8)
        self.price_label = QLabel(DEFAULT_PRICE_LABEL)
        price_row = QWidget(self)
        price_row_layout = QHBoxLayout(price_row)
        price_row_layout.setContentsMargins(0, 0, 0, 0)
        price_row_layout.setSpacing(8)
        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        self.price_edit.setMaxLength(11)
        price_row_layout.addWidget(self.price_edit, 1)
        self.calculate_btn = QPushButton("Calculate")
        price_row_layout.addWidget(self.calculate_btn)
        form_layout.addRow(self.price_label, price_row)

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

        result_row = QWidget(self)
        result_row_layout = QHBoxLayout(result_row)
        result_row_layout.setContentsMargins(0, 0, 0, 0)
        result_row_layout.setSpacing(8)
        result_row_layout.addStretch(1)

        self.wiz_result = QLabel("Units: - | Spent/Proceeds (ILS): - | Leftover vs plan (ILS): -")
        self.wiz_result.setWordWrap(False)
        self.wiz_result.setStyleSheet(
            "background: #f7fbff; border: 1px solid #d5e8ff; border-radius: 6px; "
            "padding: 10px 12px; font-size: 15px; font-weight: 600;"
        )
        result_row_layout.addWidget(self.wiz_result)

        self.save_continue_btn = QPushButton("Save and continue")
        self.save_continue_btn.setStyleSheet("font-size: 15px; padding: 8px 12px;")
        result_row_layout.addWidget(self.save_continue_btn)
        result_row_layout.addStretch(1)
        layout.addWidget(result_row)

        btns = QWidget(self)
        btns_layout = QHBoxLayout(btns)
        btns_layout.setContentsMargins(0, 0, 0, 0)

        self.quit_btn = QPushButton("Quit")
        btns_layout.addWidget(self.quit_btn)

        btns_layout.addStretch(1)

        self.back_to_portfolio_btn = QPushButton("Exit Wizard")
        btns_layout.addWidget(self.back_to_portfolio_btn)

        self.continue_without_save_btn = QPushButton("Skip Step")
        btns_layout.addWidget(self.continue_without_save_btn)
        layout.addWidget(btns)

    def set_step_context(
        self,
        *,
        step_index: int,
        total_steps: int,
        asset_group_name: str,
        instrument_name: str,
        action: str,
        planned_amount_text: str,
    ) -> None:
        """Render a compact, readable summary block for the active wizard step."""
        self.step_progress.setText(f"Step {step_index}/{total_steps}")
        self.wiz_info.setText(
            f"Instrument: {instrument_name}\n"
            f"Asset group: {asset_group_name}\n"
            f"Action: {action} {planned_amount_text}"
        )

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
