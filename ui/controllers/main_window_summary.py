from __future__ import annotations

"""Summary-screen setup and summary-to-wizard navigation behavior."""

from collections.abc import Sequence
from decimal import Decimal
from typing import cast

from PySide6.QtWidgets import QWidget

from portfolio_core.domain.models import Portfolio
from portfolio_core.domain.planning_types import PlanningMode
from portfolio_core.workflows import PlanStep
from ui.controllers.protocols import MainWindowSummaryHost
from ui.screens.summary_screen import SummaryScreen
from ui.shared.ui_utils import fmt_decimal_grouped

D = Decimal


class MainWindowSummaryController:
    """Controller containing summary-screen wiring and render behavior."""

    def __init__(self, host: MainWindowSummaryHost) -> None:
        self._host = host

    def _host_widget(self) -> QWidget:
        """Return host cast to QWidget for screen construction."""
        return cast(QWidget, self._host)

    @staticmethod
    def _planning_action_label(mode: PlanningMode) -> str:
        """Return summary wording aligned with the main-editor planning buttons."""
        if mode == PlanningMode.REBALANCE:
            return "Rebalance Portfolio"
        return "Invest Cash"

    @staticmethod
    def _available_to_allocate_text(p: Portfolio) -> str:
        """Return the formatted summary budget label value."""
        budget = p.cash.value - p.cash.min_reserve - p.cash.future_tax
        if budget < 0:
            budget = D("0")
        return f"{fmt_decimal_grouped(budget)} ILS"

    @staticmethod
    def _build_planned_actions_text(steps: Sequence[PlanStep]) -> str:
        """Build human-readable planned-action lines from computed plan steps."""
        if not steps:
            return "No actions required."

        lines: list[str] = []
        for index, s in enumerate(steps, start=1):
            action = "BUY" if s.planned_delta_money > 0 else "SELL"
            lines.append(
                f"{index}. {action} {fmt_decimal_grouped(abs(s.planned_delta_money), places=2, trim_trailing_zeros=True)} ILS "
                f"in [{s.asset_group_name}] via [{s.instrument_name}]"
            )
        return "\n".join(lines)

    def init_screen(self) -> None:
        """Create summary screen and connect navigation actions."""
        host = self._host
        host.screen_summary = SummaryScreen(self._host_widget())
        host.screen_summary.quit_btn.clicked.connect(host._quit_app)
        host.screen_summary.back_btn.clicked.connect(self.summary_back)
        host.screen_summary.start_execution_btn.clicked.connect(self.summary_next)

    def populate_summary(self, p: Portfolio, steps: Sequence[PlanStep], mode: PlanningMode) -> None:
        """Render the current plan result in the summary screen cards."""
        host = self._host
        host.screen_summary.set_plan_overview(
            planning_action=self._planning_action_label(mode),
            available_to_allocate=self._available_to_allocate_text(p),
        )
        host.screen_summary.set_planned_actions(
            actions_text=self._build_planned_actions_text(steps)
        )

    def summary_next(self) -> None:
        """Advance from summary to wizard (or back to main when no steps)."""
        host = self._host
        if not host.planning_state.plan_steps:
            host.stack.setCurrentWidget(host.screen_main)
            return
        host._show_current_plan_execution_step()
        host.stack.setCurrentWidget(host.screen_wizard)

    def summary_back(self) -> None:
        """Return from summary screen to main editor screen."""
        self._host.stack.setCurrentWidget(self._host.screen_main)
