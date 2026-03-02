"""
Wizard screen UI.

This module defines `WizardScreen`, the per-instrument execution view
(screen 3) used after summary review. It provides layout and widget creation
for step information, price entry, calculation feedback, and step actions.

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
        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Enter unit price (e.g. 123.45)")
        form_layout.addRow("Price (Agorot):", self.price_edit)
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
