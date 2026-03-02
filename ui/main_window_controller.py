from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QStandardPaths
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QTreeWidgetItem,
    QWidget,
)

from investment_planner.calc_stock_units import calculate_buy_units
from investment_planner.planning_types import PlanningMode
from investment_planner.portfolio_session import PortfolioSession
from investment_planner.use_cases import (
    PlanBuildResult,
    PlanStep,
    apply_wizard_step,
    build_plan_for_current_document,
    create_new_default_document,
    load_document,
    save_document_from_data,
    sync_document_from_data,
)

from ui.ui_types import RowKind, Col, ROLE_PREV_TEXT
from ui.ui_utils import d_from_text, get_item_kind, set_group_tree_item, add_instrument_item_to_group, parse_value_cell
from ui.ui_utils import apply_drift_color, NON_INVESTABLE_BUCKET_ID, _is_cell_editable
from ui.portfolio_editor_adapter import (
    build_portfolio_data_from_main_editor,
    populate_main_editor_from_portfolio,
)
from ui.portfolio_metrics import (
    MetricGroupRow,
    MetricInstrumentRow,
    MetricsSnapshot,
    compute_portfolio_metrics,
)

from ui.screens.main_editor_screen import MainEditorScreen
from ui.screens.summary_screen import SummaryScreen
from ui.screens.wizard_screen import WizardScreen
from ui.ui_state import PlanningState, UnsavedChangesDecision, WizardState

"""
main_window_controller.py

Primary GUI implementation for the investment planner application.

This module defines the main application window and coordinates all
user interaction, including portfolio editing, validation feedback,
navigation through the investment workflow, and triggering planning
and execution logic.

The main window acts as an orchestrator between the UI components and
the underlying domain logic, while keeping calculation, validation,
and persistence responsibilities in their respective modules.

Prompting/UI decision points (message boxes and file pickers) are kept in
dedicated helpers (`_prompt_*`, `_show_*`) and action methods perform the
underlying save/open/plan work. This split keeps behavior testable without
driving interactive dialogs.
"""

D = Decimal

NON_INVESTABLE_BUCKET_TITLE = "Non-investable holdings (excluded from strategy)"
MIN_INVESTABLE_AMOUNT_ILS = D("100")

class MainWindow(QMainWindow):
    """
    3-screen flow:
      1) main editor
      2) summary
      3) per-instrument wizard
    """

    def __init__(self, json_path: str = "portfolio.json"):
        super().__init__()
        self._base_window_title = "Investment Planner"
        self.setWindowTitle(self._base_window_title)

        app_cfg_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        cfg_dir = Path(app_cfg_dir) if app_cfg_dir else Path.home() / ".investment_planner"
        config_path = cfg_dir / "config.json"
        self.session = PortfolioSession(default_json_path=Path(json_path), config_path=config_path)
        self.planning_state = PlanningState()
        self.wizard_state = WizardState()

        # Screens
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self._init_main_screen()
        self._init_summary_screen()
        self._init_wizard_screen()

        self.stack.addWidget(self.screen_main)
        self.stack.addWidget(self.screen_summary)
        self.stack.addWidget(self.screen_wizard)
        self.stack.setCurrentWidget(self.screen_main)

        self._init_status_bar()
        self._load_or_init()

        self._suppress_item_changed = False
        self.tree.itemChanged.connect(self._on_item_changed_guard_and_recalc)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        self._refresh_data()

    def _current_file_display_name(self) -> str:
        """Return short file label for UI chrome (filename or ``Untitled``)."""
        if self.session.current_file_path is None:
            return "Untitled"
        return self.session.current_file_path.name

    def _current_file_full_path_text(self) -> str:
        """Return full-path tooltip text for the current portfolio file context."""
        if self.session.current_file_path is None:
            return "No file path yet (new unsaved portfolio)."
        return str(self.session.current_file_path)

    def _update_file_context_ui(self) -> None:
        """Refresh window title and status-bar file indicator from session state."""
        name = self._current_file_display_name()
        self.setWindowTitle(f"{self._base_window_title} - {name}")
        self.file_context_label.setText(f"Open: {name}")
        self.file_context_label.setToolTip(self._current_file_full_path_text())

    def _init_status_bar(self) -> None:
        """Create and attach status bar widgets used for active-file visibility."""
        self.file_context_label = QLabel("Open: Untitled")
        self.file_context_label.setToolTip("No file path yet (new unsaved portfolio).")
        bar = QStatusBar(self)
        bar.addPermanentWidget(self.file_context_label, 1)
        self.setStatusBar(bar)

    def _load_portfolio_from_file(self, path: Path):
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

    # -------------------------
    # Screen 1 (Main)
    # -------------------------

    def _init_main_screen(self) -> None:
        """Build screen-1 widget and wire all main-editor signal handlers."""
        self.screen_main = MainEditorScreen(self)
        self.tree = self.screen_main.tree
        self.cash_value_edit = self.screen_main.cash_value_edit
        self.cash_reserve_edit = self.screen_main.cash_reserve_edit
        self.future_tax_edit = self.screen_main.future_tax_edit
        self.investable_balance_label = self.screen_main.investable_balance_label
        self.total_label = self.screen_main.total_label

        self.screen_main.add_group_btn.clicked.connect(self._add_asset_group)
        self.screen_main.add_instrument_btn.clicked.connect(self._add_instrument)
        self.screen_main.delete_row_btn.clicked.connect(self._delete_selected_row)
        self.screen_main.quit_btn.clicked.connect(self._on_main_quit_clicked)
        self.screen_main.invest_btn.clicked.connect(self._on_invest_clicked)
        self.screen_main.rebalance_btn.clicked.connect(self._on_rebalance_clicked)
        self.screen_main.save_btn.clicked.connect(self._on_save_clicked)
        self.screen_main.save_as_btn.clicked.connect(self._on_save_as_clicked)
        self.screen_main.open_btn.clicked.connect(self._on_open_clicked)
        self.screen_main.new_btn.clicked.connect(self._on_new_clicked)

        self.tree.items_reordered.connect(self._on_main_refresh_requested)
        self.cash_value_edit.textChanged.connect(self._on_main_refresh_requested)
        self.cash_reserve_edit.textChanged.connect(self._on_main_refresh_requested)
        self.future_tax_edit.textChanged.connect(self._on_main_refresh_requested)
        self.future_tax_edit.editingFinished.connect(self._normalize_future_tax_input)

    def _on_item_changed_guard_and_recalc(self, item, column: int):
        if self._suppress_item_changed:
            return

        # Only business-rule validate relevant cells
        if get_item_kind(item) == RowKind.GROUP and column == Col.TARGET_PCT.value:
            if not self._validate_target_pct_cell_or_revert(item):
                self._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            if not self._validate_instrument_target_pct_cell_or_revert(item):
                self._refresh_data()
                return

        self._refresh_data()

    def _add_asset_group(self):
        # gid = _new_id("grp")
        gitem = QTreeWidgetItem(self.tree)

        set_group_tree_item(gitem, "New Asset Group", 0)

        self.tree.expandAll()
        self._refresh_data()

    def _add_instrument(self):
        sel = self.tree.currentItem()
        if sel is None:
            QMessageBox.warning(self, "Add instrument", "Select a group (or an instrument under a group) first.")
            return

        # If instrument selected, use its parent group
        parent = sel.parent() or sel

        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            default_in_group_pct = ""
        else:
            default_in_group_pct = "100" if parent.childCount() == 0 else "0"

        add_instrument_item_to_group(parent, "New Instrument", "1", default_in_group_pct)

        self.tree.expandAll()
        self._refresh_data()

    def _delete_selected_row(self):
        sel = self.tree.currentItem()
        if sel is None:
            return

        if get_item_kind(sel) == RowKind.NON_INVESTABLE_BUCKET:
            QMessageBox.warning(self, "Not allowed", "The non-investable bucket cannot be deleted.")
            return

        parent = sel.parent()
        if parent is None:
            idx = self.tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)
        self._refresh_data()

    def _load_or_init(self):
        startup_path = self.session.resolve_startup_path()

        if startup_path is not None:
            try:
                self._load_portfolio_from_file(startup_path)
                return
            except Exception as e:
                QMessageBox.critical(self, "Load failed", f"Failed loading JSON:\n{e}")
                self.session.set_active_file_path(None)

        p = create_new_default_document(self.session)
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

    def _on_main_refresh_requested(self, *_args) -> None:
        """Single dispatcher for main-screen refresh requests from signals."""
        self._refresh_data()

    def _refresh_data(self):
        """Refresh all derived main-screen values and visuals from current inputs."""
        self._refresh_total_portfolio()
        self._update_investable_balance_visual_state()
        self._update_future_tax_visual_state()
        self._recalc_totals_and_pcts()

    def _refresh_total_portfolio(self):
        """
        Update total-portfolio label from current editable UI values.

        Uses partial parsing (invalid/empty values degrade gracefully to placeholder).
        """
        try:
            data = build_portfolio_data_from_main_editor(
                tree=self.tree,
                cash_value_edit=self.cash_value_edit,
                cash_reserve_edit=self.cash_reserve_edit,
                future_tax_edit=self.future_tax_edit,
                allow_partial=True,
            )
            # Total portfolio = cash + all instrument values - future tax
            cash_amt = D(str(data["cash"]["value"]))
            future_tax = D(str(data["cash"]["future_tax"]))
            total = cash_amt
            for ins in data.get("instruments", []):
                total += D(str(ins["value"]))
            total -= future_tax
            self.total_label.setText(f"Total portfolio: {total}")
        except Exception:
            self.total_label.setText("Total portfolio: -")

    def _save_from_main_ui(self, target_path: Path) -> None:
        """
        Build, parse, validate and persist current main-screen portfolio state.

        Parameters
        ----------
        target_path:
            Destination portfolio JSON file path chosen by the current save flow
            (`Save` or `Save As`). The validated portfolio is written to this
            exact path and then marked as the active session file.
        """
        data = build_portfolio_data_from_main_editor(
            tree=self.tree,
            cash_value_edit=self.cash_value_edit,
            cash_reserve_edit=self.cash_reserve_edit,
            future_tax_edit=self.future_tax_edit,
            allow_partial=False,
        )
        save_document_from_data(self.session, data, target_path)
        self._update_file_context_ui()

    def _show_info(self, title: str, message: str) -> None:
        """Show informational feedback via one overridable wrapper."""
        QMessageBox.information(self, title, message)

    def _show_error(self, title: str, message: str) -> None:
        """Show error feedback via one overridable wrapper."""
        QMessageBox.critical(self, title, message)

    def _prompt_select_save_path(self) -> Optional[Path]:
        """Prompt for save location and return normalized target path, or ``None`` if canceled."""
        start_path = self.session.current_file_path or self.session.default_json_path
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Save Portfolio As",
            str(start_path),
            "Portfolio JSON (*.json);;JSON files (*.json);;All files (*)",
        )
        if not selected:
            return None
        chosen = Path(selected).expanduser()
        if chosen.suffix.lower() != ".json":
            chosen = chosen.with_suffix(".json")
        return chosen

    def _prompt_select_open_path(self) -> Optional[Path]:
        """Prompt for portfolio file to open, or return ``None`` if canceled."""
        start_path = self.session.current_file_path or self.session.default_json_path
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Open Portfolio",
            str(start_path.parent),
            "Portfolio JSON (*.json);;JSON files (*.json);;All files (*)",
        )
        if not selected:
            return None
        return Path(selected).expanduser()

    def _resolve_save_target(self, *, force_save_as: bool) -> Optional[Path]:
        """
        Resolve destination path for save flows before executing write action.

        This method decides which path to use (current path vs prompted path)
        but does not mutate portfolio/session data.
        """
        target = None if force_save_as else self.session.current_file_path
        if target is None:
            target = self._prompt_select_save_path()
        return target

    def _execute_save_to_target(self, target: Path, *, show_success: bool) -> bool:
        """Execute save action for a resolved path and emit success/error feedback."""
        try:
            self._save_from_main_ui(target)
            if show_success:
                self._show_info("Saved", f"Portfolio saved to:\n{target}")
            return True
        except Exception as e:
            self._show_error("Validation / Save failed", str(e))
            return False

    def _save_current_or_save_as(self, *, show_success: bool, force_save_as: bool = False) -> bool:
        """
        Save current editor state to active file or a newly selected file.

        Returns ``True`` only when save completed successfully.
        """
        target = self._resolve_save_target(force_save_as=force_save_as)
        if target is None:
            return False
        return self._execute_save_to_target(target, show_success=show_success)

    def _open_portfolio_from_path(self, path: Path) -> bool:
        """Load selected portfolio path and report success."""
        try:
            self._load_portfolio_from_file(path)
            return True
        except Exception as e:
            self._show_error("Load failed", f"Failed loading JSON:\n{e}")
            return False

    def _open_portfolio_from_picker(self) -> bool:
        """Prompt for a portfolio path, then execute open action."""
        path = self._prompt_select_open_path()
        if path is None:
            return False
        return self._open_portfolio_from_path(path)

    def _prompt_unsaved_changes_decision(self, action_text: str) -> UnsavedChangesDecision:
        """
        Prompt unsaved-changes confirmation and return typed decision outcome.

        Returns one of `UnsavedChangesDecision.SAVE`, `.DISCARD`, `.CANCEL`.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText("Your current changes are not saved.")
        box.setInformativeText(f"Do you want to save before {action_text}?")
        save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        dont_save_btn = box.addButton("Don't Save", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == save_btn:
            return UnsavedChangesDecision.SAVE
        if clicked == dont_save_btn:
            return UnsavedChangesDecision.DISCARD
        if clicked == cancel_btn:
            return UnsavedChangesDecision.CANCEL
        return UnsavedChangesDecision.CANCEL

    def _resolve_unsaved_changes_decision(self, decision: UnsavedChangesDecision) -> bool:
        """Apply typed unsaved-changes decision without opening prompt dialogs."""
        if decision == UnsavedChangesDecision.SAVE:
            return self._save_current_or_save_as(show_success=False)
        if decision == UnsavedChangesDecision.DISCARD:
            return True
        return False

    def _confirm_continue_with_unsaved_changes(self, action_text: str) -> bool:
        """Run unsaved-changes prompt + action resolution, returning continuation intent."""
        if not self._has_unsaved_main_changes():
            return True

        decision = self._prompt_unsaved_changes_decision(action_text)
        return self._resolve_unsaved_changes_decision(decision)

    def _on_save_clicked(self):
        """Handle `Save` action from main screen."""
        self._save_current_or_save_as(show_success=True)

    def _on_save_as_clicked(self):
        """Handle `Save As` action from main screen."""
        self._save_current_or_save_as(show_success=True, force_save_as=True)

    def _on_open_clicked(self):
        """Handle `Open` action with unsaved-changes safeguard."""
        if not self._confirm_continue_with_unsaved_changes("opening another portfolio"):
            return
        self._open_portfolio_from_picker()

    def _on_new_clicked(self):
        """Handle `New` action by loading default portfolio after confirmation."""
        if not self._confirm_continue_with_unsaved_changes("creating a new portfolio"):
            return
        p = create_new_default_document(self.session)
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

    def _on_invest_clicked(self):
        self._run_planning(mode=PlanningMode.INVEST)

    def _on_rebalance_clicked(self):
        self._run_planning(mode=PlanningMode.REBALANCE)

    def _on_main_quit_clicked(self):
        if not self._confirm_continue_with_unsaved_changes("quitting"):
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _has_unsaved_main_changes(self) -> bool:
        """
        Compare current UI state against the last loaded/saved snapshot.

        Any parse/load failure is treated as unsaved changes to avoid accidental data loss.
        """
        # If current UI state cannot be parsed, treat it as unsaved changes.
        try:
            current_data = build_portfolio_data_from_main_editor(
                tree=self.tree,
                cash_value_edit=self.cash_value_edit,
                cash_reserve_edit=self.cash_reserve_edit,
                future_tax_edit=self.future_tax_edit,
                allow_partial=True,
            )
            sync_document_from_data(self.session, current_data)
        except Exception:
            return True

        return self.session.document.is_dirty()

    def _run_planning(self, mode: PlanningMode):
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
            self.wizard_state.last_calc = None

            self._populate_summary(plan_result.portfolio, plan_result.steps, mode)
            self.stack.setCurrentWidget(self.screen_summary)
        except Exception as e:
            self._show_error("Plan failed", str(e))

    # -------------------------
    # Screen 2 (Summary)
    # -------------------------

    def _init_summary_screen(self) -> None:
        """Build screen-2 widget and wire summary navigation actions."""
        self.screen_summary = SummaryScreen(self)
        self.summary_text = self.screen_summary.summary_text
        self.screen_summary.quit_btn.clicked.connect(self._quit_app)
        self.screen_summary.back_btn.clicked.connect(self._summary_back)
        self.screen_summary.next_btn.clicked.connect(self._summary_next)

    def _populate_summary(self, p, steps: List[PlanStep], mode: PlanningMode):
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

    def _summary_next(self):
        """Advance from summary to wizard, or return to main if no steps exist."""
        if not self.planning_state.plan_steps:
            # Nothing to do -> go back to main
            self.stack.setCurrentWidget(self.screen_main)
            return
        self._show_current_wizard_step()
        self.stack.setCurrentWidget(self.screen_wizard)

    def _summary_back(self):
        """Return from summary screen to main editor."""
        self.stack.setCurrentWidget(self.screen_main)

    # -------------------------
    # Screen 3 (Wizard)
    # -------------------------

    def _init_wizard_screen(self) -> None:
        """Build screen-3 widget and wire wizard actions."""
        self.screen_wizard = WizardScreen(self)
        self.wiz_info = self.screen_wizard.wiz_info
        self.price_edit = self.screen_wizard.price_edit
        self.wiz_result = self.screen_wizard.wiz_result
        self.screen_wizard.calculate_btn.clicked.connect(self._wizard_calculate)
        self.screen_wizard.quit_btn.clicked.connect(self._quit_app)
        self.screen_wizard.save_continue_btn.clicked.connect(self._wizard_save_continue)
        self.screen_wizard.continue_without_save_btn.clicked.connect(self._wizard_continue_without_saving)

    def _show_current_wizard_step(self):
        """Render current wizard step details and reset last calculation state."""
        s = self.planning_state.plan_steps[self.planning_state.step_index]
        idx = self.planning_state.step_index + 1
        total = len(self.planning_state.plan_steps)

        action = "BUY" if s.planned_delta_money > 0 else "SELL"
        self.wiz_info.setText(
            f"Step {idx}/{total}\n"
            f"Asset group: {s.asset_group_name}\n"
            f"Instrument: {s.instrument_name}\n"
            f"Planned {action} value: {abs(s.planned_delta_money)}"
        )
        self.price_edit.setText("")
        self.wiz_result.setText("Units: - | Spent/Proceeds: - | Leftover vs plan: -")

        # store last calculation
        self.wizard_state.last_calc = None

    def _wizard_calculate(self):
        """Calculate units/spend for the current wizard step from entered price."""
        try:
            s = self.planning_state.plan_steps[self.planning_state.step_index]
            price = d_from_text(self.price_edit.text(), "price")

            planned = abs(s.planned_delta_money)
            calc = calculate_buy_units(
                instrument_id=s.instrument_id,
                planned_money=planned,
                price_ag=price,
            )
            self.wizard_state.last_calc = calc

            label_money = "Spent" if s.planned_delta_money > 0 else "Proceeds"
            self.wiz_result.setText(
                f"Units: {calc.units} | {label_money}: {calc.spent} | Leftover vs plan: {calc.leftover}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Calculation failed", str(e))

    def _wizard_save_continue(self):
        """Apply current step trade (if valid), persist, and move to next step."""
        try:
            if self.session.document.current_portfolio is None:
                raise ValueError("No portfolio loaded")

            s = self.planning_state.plan_steps[self.planning_state.step_index]

            # If user didn't calculate, treat as 0 units (skip saving)
            if self.wizard_state.last_calc is None:
                calc_units = 0
                spent = D("0")
            else:
                calc_units = self.wizard_state.last_calc.units
                spent = self.wizard_state.last_calc.spent

            applied = apply_wizard_step(self.session, s, calc_units, spent)
            if applied:
                self._update_file_context_ui()

            self._advance_wizard_step()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _wizard_continue_without_saving(self):
        """Skip current step without mutating portfolio and move forward."""
        try:
            if self.session.document.current_portfolio is None:
                raise ValueError("No portfolio loaded")
            self._advance_wizard_step()
        except Exception as e:
            QMessageBox.critical(self, "Continue failed", str(e))

    def _advance_wizard_step(self):
        """Move to next wizard step or return to main when flow is complete."""
        # Next step or back to main
        self.planning_state.step_index += 1
        if self.planning_state.step_index >= len(self.planning_state.plan_steps):
            # Return to main with the current in-memory portfolio state.
            current = self.session.document.current_portfolio
            assert current is not None
            populate_main_editor_from_portfolio(
                tree=self.tree,
                cash_value_edit=self.cash_value_edit,
                cash_reserve_edit=self.cash_reserve_edit,
                future_tax_edit=self.future_tax_edit,
                portfolio=current,
                non_investable_bucket_id=NON_INVESTABLE_BUCKET_ID,
                non_investable_bucket_title=NON_INVESTABLE_BUCKET_TITLE,
                on_future_tax_value_set=self._update_future_tax_visual_state,
            )
            self.stack.setCurrentWidget(self.screen_main)
        else:
            self._show_current_wizard_step()

    def _recalc_totals_and_pcts(self) -> None:
        """
        Recompute all derived table values from editable inputs.

        This is the single refresh entrypoint for:
        - aggregated totals (group totals, strategy total, portfolio total)
        - portfolio-level percentages for all rows
        - strategy/diff columns per row scope:
          - group rows: relative to investable strategy universe
          - instrument rows: relative to their parent asset group

        The method intentionally orchestrates small helpers so each step has
        one responsibility and can be reasoned about independently.
        """
        self._suppress_item_changed = True
        try:
            snapshot, item_by_key = self._build_metrics_snapshot()
            metrics = compute_portfolio_metrics(snapshot)

            for key, total in metrics.top_total_by_key.items():
                item_by_key[key].setText(Col.TOT_VALUE.value, str(total))

            for key, text in metrics.portfolio_pct_text_by_key.items():
                item_by_key[key].setText(Col.PORTFOLIO_PCT.value, text)

            for key, text in metrics.strategy_pct_text_by_key.items():
                item_by_key[key].setText(Col.STRATEGY_PCT.value, text)

            for key, text in metrics.drift_text_by_key.items():
                item_by_key[key].setText(Col.DRIFT_PP.value, text)

            for key, text in metrics.target_pct_text_overrides_by_key.items():
                item_by_key[key].setText(Col.TARGET_PCT.value, text)

            for key, drift in metrics.drift_value_by_key.items():
                apply_drift_color(item_by_key[key], Col.DRIFT_PP.value, drift)

        finally:
            self._suppress_item_changed = False

    def _normalize_future_tax_input(self) -> None:
        """Normalize empty future-tax input to zero on edit completion."""
        if not self.future_tax_edit.text().strip():
            self.future_tax_edit.setText("0")

    def _update_future_tax_visual_state(self) -> None:
        """Highlight future-tax field when value is positive."""
        future_tax = parse_value_cell(self.future_tax_edit.text())
        if future_tax > 0:
            self.future_tax_edit.setStyleSheet("color: #b00020;")
        else:
            self.future_tax_edit.setStyleSheet("")

    def _update_investable_balance_visual_state(self) -> None:
        """Show investable balance and color-code it against minimum investable amount."""
        cash_value = parse_value_cell(self.cash_value_edit.text())
        cash_reserve = parse_value_cell(self.cash_reserve_edit.text())
        future_tax = parse_value_cell(self.future_tax_edit.text())
        investable_balance = cash_value - cash_reserve - future_tax
        if investable_balance < 0:
            investable_balance = D("0")

        self.investable_balance_label.setText(f"Investable balance: {investable_balance}")
        if investable_balance >= MIN_INVESTABLE_AMOUNT_ILS:
            self.investable_balance_label.setStyleSheet("color: #1b5e20;")
        else:
            self.investable_balance_label.setStyleSheet("color: #777777;")

    def _build_metrics_snapshot(self) -> tuple[MetricsSnapshot, dict[str, QTreeWidgetItem]]:
        """Build pure metrics input plus key->item lookup for UI render updates."""
        groups: list[MetricGroupRow] = []
        item_by_key: dict[str, QTreeWidgetItem] = {}

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is None:
                continue

            top_key = f"top:{i}"
            item_by_key[top_key] = top
            top_kind = get_item_kind(top)

            instruments: list[MetricInstrumentRow] = []
            for j in range(top.childCount()):
                child = top.child(j)
                if child is None:
                    continue

                child_key = f"top:{i}:child:{j}"
                item_by_key[child_key] = child
                instruments.append(
                    MetricInstrumentRow(
                        key=child_key,
                        kind=get_item_kind(child),
                        value_text=child.text(Col.TOT_VALUE.value),
                        target_pct_text=child.text(Col.TARGET_PCT.value),
                    )
                )

            groups.append(
                MetricGroupRow(
                    key=top_key,
                    kind=top_kind,
                    target_pct_text=top.text(Col.TARGET_PCT.value),
                    instruments=tuple(instruments),
                )
            )

        snapshot = MetricsSnapshot(
            groups=tuple(groups),
            cash_value_text=self.cash_value_edit.text(),
            future_tax_text=self.future_tax_edit.text(),
        )
        return snapshot, item_by_key

    def _on_item_double_clicked(self, item, column):
        """
        Start guarded cell editing on double-click for editable cells only.

        Previous text is captured for possible validation-driven revert.
        """
        kind = get_item_kind(item)

        if kind == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            parent = item.parent()
            if parent is not None and get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
                return

        if _is_cell_editable(kind, column):
            # Save previous value for this specific column
            item.setData(column, ROLE_PREV_TEXT, item.text(column))

            # Temporarily enable editing
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.tree.editItem(item, column)
            # Disable immediately after edit starts
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def _quit_app(self) -> None:
        """Quit application if a Qt application instance exists."""
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _validate_target_pct_cell_or_revert(self, item) -> bool:
        """
        Validates the group's Target % cell. Returns True if OK, False if reverted.
        """
        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        try:
            p = Decimal(raw)
        except Exception:
            self._warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False

        if p > 100:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False

        return True

    def _validate_instrument_target_pct_cell_or_revert(self, item) -> bool:
        """
        Validates an instrument row's Target % (in-group target) cell.
        Returns True if accepted, False if reverted/ignored.
        """
        parent = item.parent()
        if parent is None:
            # Defensive: instrument rows should always have a parent.
            return False
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            # In-group % is not applicable for non-investable holdings.
            return False

        col = Col.TARGET_PCT.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        try:
            p = Decimal(raw)
        except Exception:
            self._warn_and_revert(item, col, raw, prev, "Target % must be a number.")
            return False

        if p < 0:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot be negative.")
            return False

        if p > 100:
            self._warn_and_revert(item, col, raw, prev, "Target % cannot exceed 100.")
            return False

        return True

    def _warn_and_revert(self, item, col: int, bad: str, prev: str, msg: str) -> None:
        """Show validation warning and revert edited cell to previous value."""
        self._suppress_item_changed = True
        try:
            QMessageBox.warning(
                self,
                "Invalid input",
                f"{msg}\n\nYou entered: {bad}\nReverting to previous value: {prev}"
            )
            item.setText(col, prev if prev is not None else "")
        finally:
            self._suppress_item_changed = False
