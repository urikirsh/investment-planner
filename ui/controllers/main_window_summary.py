from __future__ import annotations

"""Summary-screen setup and summary-to-wizard navigation behavior."""

from decimal import Decimal
from typing import List, cast

from PySide6.QtWidgets import QWidget

from portfolio_core.models import Portfolio
from portfolio_core.planning_types import PlanningMode
from portfolio_core.use_cases import PlanStep
from ui.controllers.protocols import MainWindowSummaryHost
from ui.screens.summary_screen import SummaryScreen

D = Decimal


class MainWindowSummaryController:
    """Controller containing summary-screen wiring and render behavior."""

    def __init__(self, host: MainWindowSummaryHost) -> None:
        self._host = host

    def _host_widget(self) -> QWidget:
        return cast(QWidget, self._host)

    @staticmethod
    def _build_summary_header_lines(p: Portfolio, mode: PlanningMode) -> list[str]:
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
    def _build_summary_action_lines(steps: list[PlanStep]) -> list[str]:
        if not steps:
            return ["No actions required."]

        lines = ["Planned actions (split per instrument by in-group target percentages):"]
        for s in steps:
            action = "BUY" if s.planned_delta_money > 0 else "SELL"
            lines.append(f"- {action} {abs(s.planned_delta_money)} in [{s.asset_group_name}] via [{s.instrument_name}]")
        return lines

    def init_screen(self) -> None:
        host = self._host
        host.screen_summary = SummaryScreen(self._host_widget())
        host.summary_text = host.screen_summary.summary_text
        host.screen_summary.quit_btn.clicked.connect(host._quit_app)
        host.screen_summary.back_btn.clicked.connect(self.summary_back)
        host.screen_summary.next_btn.clicked.connect(self.summary_next)

    def populate_summary(self, p: Portfolio, steps: List[PlanStep], mode: PlanningMode) -> None:
        lines = self._build_summary_header_lines(p, mode)
        lines.extend(self._build_summary_action_lines(list(steps)))
        if mode == PlanningMode.REBALANCE:
            lines.append("")
            lines.append("Note: SELL steps follow per-instrument in-group targets.")

        self._host.summary_text.setText("\n".join(lines))

    def summary_next(self) -> None:
        host = self._host
        if not host.planning_state.plan_steps:
            host.stack.setCurrentWidget(host.screen_main)
            return
        host._show_current_wizard_step()
        host.stack.setCurrentWidget(host.screen_wizard)
        host._prepare_wizard_fx_rate_cache()

    def summary_back(self) -> None:
        self._host.stack.setCurrentWidget(self._host.screen_main)
