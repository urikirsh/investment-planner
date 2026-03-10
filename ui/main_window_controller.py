from __future__ import annotations

"""
Primary GUI implementation for the investment planner application.

This module keeps `MainWindow` as the composition root and orchestrator for
cross-screen flow. Screen-specific behavior is delegated to composed
controllers under `ui.controllers`.
"""

from decimal import Decimal
from pathlib import Path
from typing import Callable, List

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMainWindow, QStackedWidget, QTextEdit, QTreeWidget, QTreeWidgetItem

from portfolio_core.models import Portfolio
from portfolio_core.planning_types import PlanningMode
from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import PlanBuildResult, PlanStep, build_plan_for_current_document, load_document
from ui.constants import APP_NAME
from ui.controllers import (
    MainWindowMainEditorController,
    MainWindowMetricsController,
    MainWindowSummaryController,
    MainWindowTableEditingController,
    MainWindowWelcomeController,
    WelcomeLastPortfolioStatus,
)
from ui.dialogs import show_error
from ui.main_window_actions import MainWindowActionsMixin
from ui.main_window_wizard import MainWindowWizardMixin
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.portfolio_metrics import MetricsSnapshot
from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.welcome_screen import WelcomeScreen
from ui.screens.wizard_screen import WizardScreen
from ui.ui_utils import NON_INVESTABLE_BUCKET_ID
from ui.ui_state import PlanningState, WizardState

D = Decimal

NON_INVESTABLE_BUCKET_TITLE = "Non-investable holdings (excluded from strategy)"


class MainWindow(MainWindowWizardMixin, MainWindowActionsMixin, QMainWindow):
    """
    4-screen flow:
      1) welcome/startup
      2) main editor
      3) summary
      4) per-instrument wizard
    """

    screen_welcome: WelcomeScreen
    screen_main: MainEditorScreen
    screen_summary: SummaryScreen
    screen_wizard: WizardScreen
    summary_text: QTextEdit
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    investable_balance_label: QLabel
    total_label: QLabel

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
        self._suppress_item_changed = False

        self._welcome_controller = MainWindowWelcomeController(self)
        self._main_editor_controller = MainWindowMainEditorController(self)
        self._summary_controller = MainWindowSummaryController(self)
        self._metrics_controller = MainWindowMetricsController(self)
        self._table_editing_controller = MainWindowTableEditingController(self)

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

        self.tree.itemChanged.connect(self._on_item_changed_guard_and_recalc)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

    # -------------------------
    # Main orchestrator behavior
    # -------------------------

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
        """Execute planning flow from current UI state and open summary screen."""
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

    # -------------------------
    # Welcome controller delegates
    # -------------------------

    def _init_welcome_screen(self) -> None:
        self._welcome_controller.init_screen()

    def _show_welcome_screen_on_startup(self) -> None:
        self._welcome_controller.show_on_startup()

    def _enter_main_screen(self) -> None:
        self._welcome_controller.enter_main_screen()

    @staticmethod
    def _truncate_middle(text: str, *, max_chars: int = 96) -> str:
        return MainWindowWelcomeController.truncate_middle(text, max_chars=max_chars)

    def _refresh_welcome_last_portfolio_ui(self) -> None:
        self._welcome_controller.refresh_last_portfolio_ui()

    def _build_welcome_last_portfolio_status(self, remembered_path: Path | None) -> WelcomeLastPortfolioStatus:
        return self._welcome_controller.build_last_portfolio_status(remembered_path)

    def _on_welcome_open_last_clicked(self) -> None:
        self._welcome_controller.on_open_last_clicked()

    def _on_welcome_load_different_clicked(self) -> None:
        self._welcome_controller.on_load_different_clicked()

    def _on_welcome_start_new_clicked(self) -> None:
        self._welcome_controller.on_start_new_clicked()

    def _start_default_document_from_welcome(self) -> bool:
        return self._welcome_controller.start_default_document()

    def _run_welcome_action(
        self,
        *,
        action: Callable[[], bool],
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        self._welcome_controller.run_action(action=action, on_failure=on_failure)

    # -------------------------
    # Main editor controller delegates
    # -------------------------

    def _init_main_screen(self) -> None:
        self._main_editor_controller.init_screen()

    def _add_asset_group(self) -> None:
        self._main_editor_controller.add_asset_group()

    def _add_instrument(self) -> None:
        self._main_editor_controller.add_instrument()

    def _delete_selected_row(self) -> None:
        self._main_editor_controller.delete_selected_row()

    def _load_default_document(self) -> None:
        self._main_editor_controller.load_default_document()

    def _on_main_refresh_requested(self, *_args: object) -> None:
        self._main_editor_controller.on_refresh_requested(*_args)

    def _on_invest_clicked(self) -> None:
        self._main_editor_controller.on_invest_clicked()

    def _on_rebalance_clicked(self) -> None:
        self._main_editor_controller.on_rebalance_clicked()

    def _on_main_quit_clicked(self) -> None:
        self._main_editor_controller.on_quit_clicked()

    # -------------------------
    # Summary controller delegates
    # -------------------------

    def _init_summary_screen(self) -> None:
        self._summary_controller.init_screen()

    def _populate_summary(self, p: Portfolio, steps: List[PlanStep], mode: PlanningMode) -> None:
        self._summary_controller.populate_summary(p, steps, mode)

    def _summary_next(self) -> None:
        self._summary_controller.summary_next()

    def _summary_back(self) -> None:
        self._summary_controller.summary_back()

    # -------------------------
    # Metrics controller delegates
    # -------------------------

    def _refresh_data(self) -> None:
        self._metrics_controller.refresh_data()

    def _refresh_total_portfolio(self) -> None:
        self._metrics_controller.refresh_total_portfolio()

    def _recalc_totals_and_pcts(self) -> None:
        self._metrics_controller.recalc_totals_and_pcts()

    def _normalize_future_tax_input(self) -> None:
        self._metrics_controller.normalize_future_tax_input()

    def _update_future_tax_visual_state(self) -> None:
        self._metrics_controller.update_future_tax_visual_state()

    def _update_investable_balance_visual_state(self) -> None:
        self._metrics_controller.update_investable_balance_visual_state()

    def _build_metrics_snapshot(self) -> tuple[MetricsSnapshot, dict[str, QTreeWidgetItem]]:
        return self._metrics_controller.build_metrics_snapshot()

    # -------------------------
    # Table-editing controller delegates
    # -------------------------

    def _on_item_changed_guard_and_recalc(self, item: QTreeWidgetItem, column: int) -> None:
        self._table_editing_controller.on_item_changed_guard_and_recalc(item, column)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        self._table_editing_controller.on_item_double_clicked(item, column)

    def _validate_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        return self._table_editing_controller.validate_target_pct_cell_or_revert(item)

    def _validate_instrument_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        return self._table_editing_controller.validate_instrument_target_pct_cell_or_revert(item)

    def _validate_instrument_quantity_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        return self._table_editing_controller.validate_instrument_quantity_cell_or_revert(item)

    def _warn_and_revert(self, item: QTreeWidgetItem, col: int, bad: str, prev: str | None, msg: str) -> None:
        self._table_editing_controller.warn_and_revert(item, col, bad, prev, msg)
