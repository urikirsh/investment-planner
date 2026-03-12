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

Focused-row layout:
- Price row (`Price + input + Calculate`) and result row
  (`Units/Spent/Leftover + Save and continue`) are centered and width-synced.
- Price input keeps a minimum visual width for at least 11 characters.
- `Save and continue` starts disabled and is enabled only after a successful
  calculation by flow logic in `MainWindowWizardMixin`.

Price-entry semantics:
- ILS steps use agorot input (`Price (Agorot)`), matching
  `portfolio_core.calc_stock_units.calculate_buy_units`.
- USD steps use USD unit-price input (`Price (USD)`), with conversion handled
  by the wizard FX coordinator before calculation.

All trade execution behavior is intentionally delegated to the coordinator.
"""

from __future__ import annotations

from portfolio_core.models import Currency, Exchange
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget

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
        self.step_progress.setStyleSheet("font-size: 15px; font-weight: 600; color: #34495e;")
        info_layout.addWidget(self.step_progress)

        self.wiz_info = QLabel("-")
        self.wiz_info.setWordWrap(True)
        self.wiz_info.setStyleSheet("font-size: 15px;")
        info_layout.addWidget(self.wiz_info)
        layout.addWidget(info_card)
        layout.addStretch(1)

        trade_cluster = QWidget(self)
        trade_layout = QVBoxLayout(trade_cluster)
        trade_layout.setContentsMargins(0, 0, 0, 0)
        trade_layout.setSpacing(2)

        price_outer_row = QWidget(self)
        price_outer_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        price_outer_layout = QHBoxLayout(price_outer_row)
        price_outer_layout.setContentsMargins(0, 0, 0, 0)
        price_outer_layout.setSpacing(0)
        price_outer_layout.addStretch(1)

        self._price_focus_row = QWidget(self)
        price_focus_layout = QHBoxLayout(self._price_focus_row)
        price_focus_layout.setContentsMargins(0, 0, 0, 0)
        price_focus_layout.setSpacing(6)
        self.price_label = QLabel(DEFAULT_PRICE_LABEL)
        self.price_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        price_focus_layout.addWidget(self.price_label)

        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        self.price_edit.setMaxLength(11)
        self.price_edit.setStyleSheet("font-size: 15px; padding: 5px 8px;")
        price_focus_layout.addWidget(self.price_edit, 1)
        self.calculate_btn = QPushButton("Calculate")
        self.calculate_btn.setStyleSheet("font-size: 15px; padding: 5px 10px;")
        price_focus_layout.addWidget(self.calculate_btn)
        price_outer_layout.addWidget(self._price_focus_row)
        price_outer_layout.addStretch(1)
        trade_layout.addWidget(price_outer_row)

        form = QWidget(self)
        form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        form_layout = QFormLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setVerticalSpacing(1)

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
        trade_layout.addWidget(form)
        trade_layout.setSpacing(2)

        result_row = QWidget(self)
        result_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        result_row_layout = QHBoxLayout(result_row)
        result_row_layout.setContentsMargins(0, 0, 0, 0)
        result_row_layout.setSpacing(8)
        result_row_layout.addStretch(1)

        self._result_focus_row = QWidget(self)
        result_focus_layout = QHBoxLayout(self._result_focus_row)
        result_focus_layout.setContentsMargins(0, 0, 0, 0)
        result_focus_layout.setSpacing(8)

        self.wiz_result = QLabel("Units: - | Spent/Proceeds (ILS): - | Leftover vs plan (ILS): -")
        self.wiz_result.setWordWrap(False)
        self.wiz_result.setStyleSheet(
            "background: #f7fbff; border: 1px solid #d5e8ff; border-radius: 6px; "
            "padding: 10px 12px; font-size: 15px; font-weight: 600;"
        )
        result_focus_layout.addWidget(self.wiz_result)

        self.save_continue_btn = QPushButton("Save and continue")
        self.save_continue_btn.setStyleSheet("font-size: 15px; padding: 8px 12px;")
        self.save_continue_btn.setEnabled(False)
        result_focus_layout.addWidget(self.save_continue_btn)
        result_row_layout.addWidget(self._result_focus_row)
        result_row_layout.addStretch(1)
        trade_layout.addWidget(result_row)

        layout.addWidget(trade_cluster)
        layout.addStretch(2)

        btns = QWidget(self)
        btns.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
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
        self.sync_focus_row_widths()

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

    def sync_focus_row_widths(self) -> None:
        """Keep price row and result row visual widths aligned when feasible."""
        spacing = 8
        max_qt_width = 16777215
        input_metrics = QFontMetrics(self.price_edit.font())
        min_input_width = input_metrics.horizontalAdvance("0" * 11) + 24
        self.price_edit.setMinimumWidth(min_input_width)

        result_combo_width = self.wiz_result.sizeHint().width() + self.save_continue_btn.sizeHint().width() + spacing
        price_combo_min_width = (
            self.price_label.sizeHint().width() + min_input_width + self.calculate_btn.sizeHint().width() + spacing * 2
        )
        target_width = max(result_combo_width, price_combo_min_width)

        margins = self.contentsMargins()
        available_width = max(self.width() - margins.left() - margins.right() - 24, 0)

        # Reset any previously fixed width before deciding final sizing mode.
        self._price_focus_row.setMinimumWidth(0)
        self._price_focus_row.setMaximumWidth(max_qt_width)
        self._result_focus_row.setMinimumWidth(0)
        self._result_focus_row.setMaximumWidth(max_qt_width)

        if available_width < price_combo_min_width:
            # Window too narrow: avoid forcing horizontal overflow; let rows size naturally.
            return

        clamped_width = min(target_width, available_width)
        self._price_focus_row.setFixedWidth(clamped_width)
        self._result_focus_row.setFixedWidth(clamped_width)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Recompute aligned row widths on window resize to keep layout responsive."""
        super().resizeEvent(event)
        self.sync_focus_row_widths()

    def set_price_mode(self, exchange: Exchange) -> None:
        """Configure price-label context for the current instrument exchange."""
        if exchange.currency == Currency.USD:
            self.price_label.setText(USD_PRICE_LABEL)
            self.price_edit.setPlaceholderText(f"Enter unit price in {Exchange.NYSE.currency.value} (e.g. 12.34)")
            self.sync_focus_row_widths()
            return

        self.price_label.setText(DEFAULT_PRICE_LABEL)
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        self.sync_focus_row_widths()

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
