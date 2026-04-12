"""
Summary screen UI.

This module defines `SummaryScreen`, the structured plan-review view (screen 3)
shown after planning. The widget builds presentation elements for the plan
overview, planned actions, and workflow footer, while exposing its controls for
coordinator-managed behavior.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.shared.button_styles import (
    REGULAR_BUTTON_STYLE_SIZE,
    apply_primary_action_button_style,
    apply_secondary_action_button_style,
)
from ui.shared.surface_styles import neutral_card_style


class SummaryScreen(QWidget):
    """
    Summary UI (screen 3).

    Exposes controls and simple render helpers so the coordinator can wire
    behavior without owning layout construction details.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._build_header(layout)
        layout.addWidget(self._build_plan_overview_card())
        layout.addWidget(self._build_planned_actions_card(), 1)
        layout.addWidget(self._build_bottom_actions())

    def _build_header(self, layout: QVBoxLayout) -> None:
        title = QLabel("Summary")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel("Review the generated plan before continuing to step-by-step execution.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(subtitle)

    def _build_plan_overview_card(self) -> QWidget:
        card, layout = self._build_card("Plan Overview", spacing=6)

        self.planning_action_label = QLabel("Planning action: -")
        self.planning_action_label.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.planning_action_label)

        self.available_to_allocate_label = QLabel("Available to allocate: -")
        self.available_to_allocate_label.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.available_to_allocate_label)
        return card

    def _build_planned_actions_card(self) -> QWidget:
        card, layout = self._build_card("Planned Actions", spacing=8)

        self.planned_actions_label = QLabel("No actions required.")
        self.planned_actions_label.setWordWrap(True)
        self.planned_actions_label.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.planned_actions_label)
        layout.addStretch(1)
        return card

    def _build_card(self, title: str, *, spacing: int) -> tuple[QWidget, QVBoxLayout]:
        """Build a standard summary card shell and return its widget/layout."""
        card = QWidget(self)
        card.setStyleSheet(neutral_card_style())
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(spacing)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 600; color: #34495e;")
        layout.addWidget(heading)
        return card, layout

    def _build_bottom_actions(self) -> QWidget:
        btns = QWidget(self)
        btns_layout = QHBoxLayout(btns)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.setSpacing(8)

        self.quit_btn = QPushButton("Quit")
        btns_layout.addWidget(self.quit_btn)

        btns_layout.addStretch(1)

        self.back_btn = QPushButton("Back")
        apply_secondary_action_button_style(self.back_btn, size=REGULAR_BUTTON_STYLE_SIZE)
        btns_layout.addWidget(self.back_btn)

        self.start_execution_btn = QPushButton("Start Execution")
        apply_primary_action_button_style(self.start_execution_btn, size=REGULAR_BUTTON_STYLE_SIZE)
        btns_layout.addWidget(self.start_execution_btn)
        return btns

    def set_plan_overview(self, *, planning_action: str, available_to_allocate: str) -> None:
        """Render the summary overview card."""
        self.planning_action_label.setText(f"Planning action: {planning_action}")
        self.available_to_allocate_label.setText(f"Available to allocate: {available_to_allocate}")

    def set_planned_actions(self, *, actions_text: str) -> None:
        """Render the planned-actions card body."""
        self.planned_actions_label.setText(actions_text)
