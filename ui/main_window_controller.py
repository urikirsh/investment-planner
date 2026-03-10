from __future__ import annotations

"""
Primary GUI implementation for the investment planner application.

This module keeps `MainWindow` as the composition root and orchestrator for
cross-screen flow. Screen-specific behaviors are extracted into controller
mixins under `ui.controllers`.
"""

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from portfolio_core.planning_types import PlanningMode
from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import PlanBuildResult, build_plan_for_current_document, load_document
from ui.constants import APP_NAME
from ui.controllers import (
    MainWindowMainEditorMixin,
    MainWindowMetricsMixin,
    MainWindowSummaryMixin,
    MainWindowTableEditingMixin,
    MainWindowWelcomeMixin,
)
from ui.dialogs import show_error
from ui.main_window_actions import MainWindowActionsMixin
from ui.main_window_wizard import MainWindowWizardMixin
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.ui_utils import NON_INVESTABLE_BUCKET_ID
from ui.ui_state import PlanningState, WizardState

D = Decimal

NON_INVESTABLE_BUCKET_TITLE = "Non-investable holdings (excluded from strategy)"


class MainWindow(
    MainWindowWizardMixin,
    MainWindowWelcomeMixin,
    MainWindowMainEditorMixin,
    MainWindowSummaryMixin,
    MainWindowMetricsMixin,
    MainWindowTableEditingMixin,
    MainWindowActionsMixin,
    QMainWindow,
):
    """
    4-screen flow:
      1) welcome/startup
      2) main editor
      3) summary
      4) per-instrument wizard
    """

    def __init__(self, json_path: str = "portfolio.json"):
        super().__init__()
        self._base_window_title = APP_NAME
        self.setWindowTitle(self._base_window_title)

        app_cfg_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        cfg_dir = Path(app_cfg_dir) if app_cfg_dir else Path.home() / ".investment_planner"
        config_path = cfg_dir / "config.json"
        self.session = PortfolioSession(default_json_path=Path(json_path), config_path=config_path)
        self.planning_state = PlanningState()
        self.wizard_state = WizardState()
        self._non_investable_bucket_id = NON_INVESTABLE_BUCKET_ID
        self._non_investable_bucket_title = NON_INVESTABLE_BUCKET_TITLE

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self._init_welcome_screen()
        self._init_main_screen()
        self._init_summary_screen()
        self._init_wizard_screen()

        self.stack.addWidget(self.screen_welcome)
        self.stack.addWidget(self.screen_main)
        self.stack.addWidget(self.screen_summary)
        self.stack.addWidget(self.screen_wizard)
        self.stack.setCurrentWidget(self.screen_welcome)

        self._update_file_context_ui()
        self._show_welcome_screen_on_startup()

        self._suppress_item_changed = False
        self.tree.itemChanged.connect(self._on_item_changed_guard_and_recalc)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure background FX thread is stopped before window teardown."""
        stopped = self._cancel_wizard_fx_fetch(wait_timeout_ms=12000)
        if not stopped:
            show_error(
                self,
                "Please wait",
                "Still finishing background USD/ILS fetch. Try closing again in a few seconds.",
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _current_file_display_name(self) -> str:
        """Return short file label for UI chrome (filename or ``Untitled``)."""
        if self.session.current_file_path is None:
            return "Untitled"
        return self.session.current_file_path.name

    def _update_file_context_ui(self) -> None:
        """Refresh window title from session state."""
        name = self._current_file_display_name()
        self.setWindowTitle(f"{self._base_window_title} - {name}")

    def _load_portfolio_from_file(self, path: Path) -> None:
        """Load a portfolio from disk into editor state and refresh UI context."""
        p = load_document(self.session, path)
        populate_main_editor_from_portfolio(
            tree=self.tree,
            cash_value_edit=self.cash_value_edit,
            cash_reserve_edit=self.cash_reserve_edit,
            future_tax_edit=self.future_tax_edit,
            portfolio=p,
            non_investable_bucket_id=NON_INVESTABLE_BUCKET_ID,
            non_investable_bucket_title=NON_INVESTABLE_BUCKET_TITLE,
            on_future_tax_value_set=self._update_future_tax_visual_state,
        )
        self._refresh_data()
        self._update_file_context_ui()

    def _run_planning(self, mode: PlanningMode) -> None:
        """
        Execute planning flow from current UI state and open summary screen.

        ``mode`` selects either invest-only or invest-and-rebalance strategy.
        """
        try:
            if not self._save_current_or_save_as(show_success=False):
                return
            plan_result: PlanBuildResult = build_plan_for_current_document(self.session, mode)
            if plan_result.budget <= 0:
                self._show_info("No budget", "No investable cash")
                return
            self.planning_state.plan_steps = plan_result.steps
            self.planning_state.step_index = 0
            self.planning_state.mode = mode
            if not self._reset_wizard_fx_state_for_new_run():
                self._show_error("Please wait", "Still finishing background USD/ILS fetch. Try again in a few seconds.")
                return
            self.wizard_state.last_calc = None

            self._populate_summary(plan_result.portfolio, plan_result.steps, mode)
            self.stack.setCurrentWidget(self.screen_summary)
        except Exception as e:
            self._show_error("Plan failed", str(e))

    def _quit_app(self) -> None:
        """Quit application if a Qt application instance exists."""
        app = QApplication.instance()
        if app is not None:
            app.quit()
