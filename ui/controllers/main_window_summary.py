from __future__ import annotations

"""Summary-screen setup and summary-to-wizard navigation behavior."""

from decimal import Decimal
from typing import List, cast

from PySide6.QtWidgets import QStackedWidget, QTextEdit, QWidget

from portfolio_core.models import Portfolio
from portfolio_core.planning_types import PlanningMode
from portfolio_core.use_cases import PlanStep
from ui.controllers.protocols import MainWindowSummaryDependencies
from ui.screens.summary_screen import SummaryScreen
from ui.screens.wizard_screen import WizardScreen
from ui.ui_state import PlanningState

D = Decimal


class MainWindowSummaryMixin:
    """Mixin containing summary-screen wiring and render behavior."""

    stack: QStackedWidget
    planning_state: PlanningState
    screen_main: QWidget
    screen_wizard: WizardScreen
    summary_text: QTextEdit

    def _init_summary_screen(self) -> None:
        """Build screen-3 widget and wire summary navigation actions."""
        deps = cast(MainWindowSummaryDependencies, self)
        self.screen_summary = SummaryScreen(cast(QWidget, self))
        self.summary_text = self.screen_summary.summary_text
        self.screen_summary.quit_btn.clicked.connect(deps._quit_app)
        self.screen_summary.back_btn.clicked.connect(self._summary_back)
        self.screen_summary.next_btn.clicked.connect(self._summary_next)

    def _populate_summary(self, p: Portfolio, steps: List[PlanStep], mode: PlanningMode) -> None:
        budget = p.cash.value - p.cash.min_reserve - p.cash.future_tax
        if budget < 0:
            budget = D("0")
        lines = [
            f"Mode: {mode.value}",
            f"Future tax (non-investable): {p.cash.future_tax}",
            f"Invest budget (cash - minimal reserve - future tax): {budget}",
            "",
        ]
        if not steps:
            lines.append("No actions required.")
        else:
            lines.append("Planned actions (split per instrument by in-group target percentages):")
            for s in steps:
                action = "BUY" if s.planned_delta_money > 0 else "SELL"
                lines.append(
                    f"- {action} {abs(s.planned_delta_money)} in [{s.asset_group_name}] via [{s.instrument_name}]"
                )

        if mode == PlanningMode.REBALANCE:
            lines.append("")
            lines.append("Note: SELL steps follow per-instrument in-group targets.")

        self.summary_text.setText("\n".join(lines))

    def _summary_next(self) -> None:
        """Advance from summary to wizard, or return to main if no steps exist."""
        deps = cast(MainWindowSummaryDependencies, self)
        if not self.planning_state.plan_steps:
            self.stack.setCurrentWidget(self.screen_main)
            return
        deps._show_current_wizard_step()
        self.stack.setCurrentWidget(self.screen_wizard)
        deps._prepare_wizard_fx_rate_cache()

    def _summary_back(self) -> None:
        """Return from summary screen to main editor."""
        self.stack.setCurrentWidget(self.screen_main)
