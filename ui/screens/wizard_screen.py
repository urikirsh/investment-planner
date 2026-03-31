"""
Wizard screen UI.

This module defines `WizardScreen`, the per-instrument execution view
(screen 4) used after summary review. It provides layout and widget creation
for step information, unit guidance, unit entry, calculation feedback, FX
status/override inputs, and step actions.

Action-row intent:
- `Quit` is kept on the far left as an application-level action.
- Wizard-step actions are grouped on the right:
  `Exit Wizard` and `Skip Step`.
- Primary step commit action (`Save and continue`) is grouped with result data
  in a centered row to keep attention on the decision point.

Focused-row layout:
- Summary row, units row, and result row are centered and width-synced.
- Units input keeps a minimum visual width for at least 11 characters.
- Units input is capped by flow logic to the recommended whole-unit amount.
- `Save and continue` starts disabled and is enabled only after a successful
  calculation/validation by flow logic in `MainWindowWizardMixin`.

All trade execution behavior is intentionally delegated to the coordinator.
"""

from __future__ import annotations

from portfolio_core.domain.models import Exchange
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget


USD_ILS_MANUAL_RATE_LABEL = f"Manual {Exchange.NYSE.currency.value}/ILS rate:"
DEFAULT_UNITS_LABEL = "Units bought:"
DEFAULT_WIZARD_SUMMARY_TEXT = "Planned: - ILS | Price: - ILS/unit | Recommended: - units"
DEFAULT_WIZARD_RESULT_TEXT = "Total spend/proceeds: - ILS | Leftover: - ILS"


class WizardScreen(QWidget):
    """
    Wizard UI (screen 4).


    Exposes controls so the coordinator can attach flow behavior.
    The screen itself stays presentation-only: cached-price lookup,
    recommendation math, validation, and persistence all live outside it.
    Input units are intentionally explicit in labels to reduce trade-direction
    mistakes during wizard execution.
    The action row intentionally separates app-level and step-level actions
    to reduce accidental exits during step execution.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        """Compose the full wizard screen layout from section builders."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self._build_header(layout)
        self._build_info_card(layout)
        layout.addStretch(1)
        layout.addWidget(self._build_trade_cluster())
        layout.addStretch(2)
        layout.addWidget(self._build_bottom_actions())
        self.sync_focus_row_widths()

    def _build_header(self, layout: QVBoxLayout) -> None:
        """Add title and subtitle text at the top of the screen."""
        title = QLabel("Execute Plan Step")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel("Review the step details, adjust units if needed, then apply or skip this step.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(subtitle)

    def _build_info_card(self, layout: QVBoxLayout) -> None:
        """Add the step-progress/info card section."""
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

    def _build_trade_cluster(self) -> QWidget:
        """Build and return the center cluster with summary, units, FX, and result rows."""
        trade_cluster = QWidget(self)
        trade_layout = QVBoxLayout(trade_cluster)
        trade_layout.setContentsMargins(0, 0, 0, 0)
        trade_layout.setSpacing(2)

        trade_layout.addWidget(self._build_summary_row())
        trade_layout.addWidget(self._build_units_row())
        trade_layout.addWidget(self._build_fx_panel())
        trade_layout.addWidget(self._build_result_row())
        return trade_cluster

    def _build_summary_row(self) -> QWidget:
        """Build and return the centered summary row above units input."""
        summary_row, self._summary_focus_row, summary_focus_layout = self._build_centered_focus_row(
            outer_spacing=0,
            focus_spacing=0,
        )
        self.wiz_summary = QLabel(DEFAULT_WIZARD_SUMMARY_TEXT)
        self.wiz_summary.setWordWrap(False)
        self.wiz_summary.setStyleSheet("font-size: 15px; font-weight: 600; color: #34495e;")
        summary_focus_layout.addWidget(self.wiz_summary)
        return summary_row

    def _build_units_row(self) -> QWidget:
        """Build and return the centered units-entry row."""
        units_outer_row, self._units_focus_row, units_focus_layout = self._build_centered_focus_row(
            outer_spacing=0,
            focus_spacing=6,
        )
        self.units_label = QLabel(DEFAULT_UNITS_LABEL)
        self.units_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        units_focus_layout.addWidget(self.units_label)

        self.units_edit = QSpinBox()
        self.units_edit.setRange(0, 0)
        self.units_edit.setSingleStep(1)
        self.units_edit.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.units_edit.setStyleSheet(
            "QSpinBox { font-size: 15px; padding: 5px 28px 5px 8px; min-height: 22px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 20px; }"
        )
        units_focus_layout.addWidget(self.units_edit, 1)
        return units_outer_row

    def _build_fx_panel(self) -> QWidget:
        """Build and return the FX status/override panel."""
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

        self.units_error_label = QLabel("")
        self.units_error_label.setWordWrap(True)
        self.units_error_label.setStyleSheet("color: #b00020;")
        self.units_error_label.setVisible(False)
        form_layout.addRow(self.units_error_label)

        self.manual_rate_label = QLabel(USD_ILS_MANUAL_RATE_LABEL)
        self.manual_rate_label.setVisible(False)
        self.manual_rate_edit = QLineEdit()
        self.manual_rate_edit.setPlaceholderText("e.g. 3.65")
        self.manual_rate_edit.setVisible(False)
        form_layout.addRow(self.manual_rate_label, self.manual_rate_edit)
        return form

    def _build_result_row(self) -> QWidget:
        """Build and return the centered result row with the primary commit action."""
        result_row, self._result_focus_row, result_focus_layout = self._build_centered_focus_row(
            outer_spacing=8,
            focus_spacing=8,
        )
        self.wiz_result = QLabel(DEFAULT_WIZARD_RESULT_TEXT)
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
        return result_row

    def _build_centered_focus_row(
        self,
        *,
        outer_spacing: int,
        focus_spacing: int,
    ) -> tuple[QWidget, QWidget, QHBoxLayout]:
        """Build the shared centered-row shell and return outer/focus row plus focus layout."""
        outer_row = QWidget(self)
        outer_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        outer_layout = QHBoxLayout(outer_row)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(outer_spacing)
        outer_layout.addStretch(1)

        focus_row = QWidget(self)
        focus_layout = QHBoxLayout(focus_row)
        focus_layout.setContentsMargins(0, 0, 0, 0)
        focus_layout.setSpacing(focus_spacing)

        outer_layout.addWidget(focus_row)
        outer_layout.addStretch(1)
        return outer_row, focus_row, focus_layout

    def _build_bottom_actions(self) -> QWidget:
        """Build and return the bottom action row (`Quit`, `Exit Wizard`, `Skip Step`)."""
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
        return btns

    def set_step_context(
        self,
        *,
        step_index: int,
        total_steps: int,
        asset_group_name: str,
        ticker: str,
        exchange: Exchange,
        instrument_name: str,
        action: str,
        planned_amount_text: str,
    ) -> None:
        """Render a compact, readable summary block for the active wizard step."""
        self.step_progress.setText(f"Step {step_index}/{total_steps}")
        self.wiz_info.setText(
            f"Instrument: {instrument_name}\n"
            f"Ticker: {ticker}\n"
            f"Exchange: {exchange.value}\n"
            f"Asset group: {asset_group_name}\n"
            f"Action: {action} {planned_amount_text}"
        )

    def sync_focus_row_widths(self) -> None:
        """Keep summary, units, and result rows visually aligned when feasible."""
        spacing = 8
        input_metrics = QFontMetrics(self.units_edit.font())
        min_input_width = input_metrics.horizontalAdvance("0" * 11) + 24
        self.units_edit.setMinimumWidth(min_input_width)

        summary_combo_width = self.wiz_summary.sizeHint().width()
        result_combo_width = self.wiz_result.sizeHint().width() + self.save_continue_btn.sizeHint().width() + spacing
        units_combo_min_width = self.units_label.sizeHint().width() + min_input_width + spacing
        target_width = max(summary_combo_width, result_combo_width, units_combo_min_width)

        margins = self.contentsMargins()
        available_width = max(self.width() - margins.left() - margins.right() - 24, 0)

        self._reset_focus_row_width_constraints()

        if available_width < units_combo_min_width:
            return

        clamped_width = min(target_width, available_width)
        self._summary_focus_row.setFixedWidth(clamped_width)
        self._units_focus_row.setFixedWidth(clamped_width)
        self._result_focus_row.setFixedWidth(clamped_width)

    def _reset_focus_row_width_constraints(self) -> None:
        """Clear fixed-width alignment so rows can fall back to natural sizing."""
        max_qt_width = 16777215
        self._summary_focus_row.setMinimumWidth(0)
        self._summary_focus_row.setMaximumWidth(max_qt_width)
        self._units_focus_row.setMinimumWidth(0)
        self._units_focus_row.setMaximumWidth(max_qt_width)
        self._result_focus_row.setMinimumWidth(0)
        self._result_focus_row.setMaximumWidth(max_qt_width)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Recompute aligned row widths on window resize to keep layout responsive."""
        super().resizeEvent(event)
        self.sync_focus_row_widths()

    def set_trade_mode(self, *, action: str) -> None:
        """Configure units label for the current step action."""
        self.units_label.setText("Units sold:" if action == "SELL" else DEFAULT_UNITS_LABEL)
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
            self.manual_rate_edit.setText(manual_value)
        else:
            self.manual_rate_edit.setText("")

    def set_units_error(self, text: str) -> None:
        """Render inline validation feedback for the units input."""
        normalized = text.strip()
        self.units_error_label.setText(normalized)
        self.units_error_label.setVisible(bool(normalized))

    def set_wizard_summary(self, text: str) -> None:
        """Render the top summary text shown above the units input.

        The summary is kept as one compact line so width syncing can align it
        visually with the units row and the result row.
        """
        self.wiz_summary.setText(text)

    def set_units_limit(self, *, value: int) -> None:
        """Clamp the units spinner to the recommended step limit."""
        self.units_edit.setMaximum(max(value, 0))
