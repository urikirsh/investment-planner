"""
Wizard screen UI.

This module defines `WizardScreen`, the per-instrument execution view
(screen 3) used after summary review. It provides layout and widget creation
for step information, price entry, FX status/override inputs, calculation
feedback, and step actions.

All trade execution behavior is intentionally delegated to the coordinator.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class WizardScreen(QWidget):
    """
    Wizard UI (screen 3).

    Exposes controls so the coordinator can attach flow behavior.
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
        self.price_label = QLabel("Price (Agorot):")
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

        self.manual_rate_label = QLabel("Manual USD/ILS rate:")
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

    def set_price_mode(self, currency: str) -> None:
        """Configure price-label context for the current instrument currency."""
        if currency == "USD":
            self.price_label.setText("Price (USD):")
            self.price_edit.setPlaceholderText("Enter unit price in USD (e.g. 12.34)")
            return

        self.price_label.setText("Price (Agorot):")
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
            Optional prefilled override value.
        """
        self.fx_info_label.setVisible(visible)
        self.fx_error_label.setVisible(visible)
        self.manual_rate_label.setVisible(visible and manual_visible)
        self.manual_rate_edit.setVisible(visible and manual_visible)

        self.fx_info_label.setText(info_text)
        self.fx_error_label.setText(error_text)

        if manual_visible and manual_value:
            self.manual_rate_edit.setText(manual_value)
        elif not manual_visible:
            self.manual_rate_edit.setText("")
