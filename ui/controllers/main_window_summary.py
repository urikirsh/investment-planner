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

D = Decimal


class MainWindowSummaryController:
    """Controller containing summary-screen wiring and render behavior."""

    def __init__(self, host: MainWindowSummaryHost) -> None:
        self._host = host

    def _host_widget(self) -> QWidget:
        """Return host cast to QWidget for screen construction."""
        return cast(QWidget, self._host)

    @staticmethod
    def _build_summary_header_lines(p: Portfolio, mode: PlanningMode) -> list[str]:
        """Build fixed summary header lines from portfolio cash and selected mode."""
        budget = p.cash.value - p.cash.min_reserve - p.cash.future_tax
        if budget < 0:
            budget = D("0")
        return [
            f"Mode: {mode.value}",
            f"Future tax (non-investable): {p.cash.future_tax}",
            f"Invest budget (cash - minimal reserve - future tax): {budget}",
            "",
        ]

    @staticmethod
    def _build_summary_action_lines(steps: Sequence[PlanStep]) -> list[str]:
        """Build human-readable action lines from computed plan steps."""
        if not steps:
            return ["No actions required."]

        lines = ["Planned actions (split per instrument by in-group target percentages):"]
        for s in steps:
            action = "BUY" if s.planned_delta_money > 0 else "SELL"
            lines.append(f"- {action} {abs(s.planned_delta_money)} in [{s.asset_group_name}] via [{s.instrument_name}]")
        return lines

    def init_screen(self) -> None:
        """Create summary screen and connect navigation actions."""
        host = self._host
        host.screen_summary = SummaryScreen(self._host_widget())
        host.summary_text = host.screen_summary.summary_text
        host.screen_summary.quit_btn.clicked.connect(host._quit_app)
        host.screen_summary.back_btn.clicked.connect(self.summary_back)
        host.screen_summary.next_btn.clicked.connect(self.summary_next)

    def populate_summary(self, p: Portfolio, steps: Sequence[PlanStep], mode: PlanningMode) -> None:
        """Render summary text block for the current plan result."""
        lines = self._build_summary_header_lines(p, mode)
        lines.extend(self._build_summary_action_lines(steps))
        if mode == PlanningMode.REBALANCE:
            lines.append("")
            lines.append("Note: SELL steps follow per-instrument in-group targets.")

        self._host.summary_text.setText("\n".join(lines))

    def summary_next(self) -> None:
        """Advance from summary to wizard (or back to main when no steps)."""
        host = self._host
        if not host.planning_state.plan_steps:
            host.stack.setCurrentWidget(host.screen_main)
            return
        host._show_current_wizard_step()
        host.stack.setCurrentWidget(host.screen_wizard)

    def summary_back(self) -> None:
        """Return from summary screen to main editor screen."""
        self._host.stack.setCurrentWidget(self._host.screen_main)
