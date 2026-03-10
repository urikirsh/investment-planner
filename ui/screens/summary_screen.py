"""
Summary screen UI.

This module defines `SummaryScreen`, the read-only summary view (screen 3)
shown after planning. The widget builds presentation elements and exposes
its controls (`summary_text`, `quit_btn`, `back_btn`, `next_btn`) for
coordinator-managed behavior.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SummaryScreen(QWidget):
    """
    Summary UI (screen 3).

    Exposes controls so the coordinator can wire behavior without owning
    layout construction details.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Summary")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        layout.addWidget(self.summary_text, 1)

        btns = QWidget(self)
        btns_layout = QHBoxLayout(btns)

        self.quit_btn = QPushButton("Quit")
        btns_layout.addWidget(self.quit_btn)

        self.back_btn = QPushButton("Back")
        btns_layout.addWidget(self.back_btn)

        self.next_btn = QPushButton("Next")
        btns_layout.addWidget(self.next_btn)

        btns_layout.addStretch(1)
        layout.addWidget(btns)
