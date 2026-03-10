from __future__ import annotations

"""
Primary GUI implementation for the investment planner application.

This module defines the main application window and coordinates all
user interaction, including portfolio editing, validation feedback,
navigation through the investment workflow, and triggering planning
and execution logic.

Startup behavior:
- Always opens with a dedicated welcome screen.
- Lets the user open the remembered portfolio, load another file,
  start a new default portfolio, or quit.
- Transitions into the editor flow only after a startup selection.

The main window acts as an orchestrator between the UI components and
the underlying domain logic, while keeping calculation, validation,
and persistence responsibilities in their respective modules.

File-oriented save/open/new action flows are extracted into
`ui.main_window_actions.MainWindowActionsMixin`, and wizard step flow is
extracted into `ui.main_window_wizard.MainWindowWizardMixin`.
This controller keeps screen wiring, refresh orchestration, and summary flow
coordination. Concrete Qt dialog primitives are centralized in `ui.dialogs`
wrappers.
"""

from decimal import Decimal
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QStandardPaths
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStackedWidget,
    QTreeWidgetItem,
)

from portfolio_core.models import Portfolio
from portfolio_core.planning_types import PlanningMode
from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import (
    PlanBuildResult,
    PlanStep,
    build_plan_for_current_document,
    create_new_default_document,
    load_document,
)

from ui.main_window_actions import MainWindowActionsMixin
from ui.main_window_wizard import MainWindowWizardMixin
from ui.constants import APP_NAME, APP_VERSION
from ui.ui_types import RowKind, Col, ROLE_EXCHANGE, ROLE_PREV_TEXT
from ui.ui_utils import (
    BASE_CURRENCY_SUFFIX,
    DEFAULT_EXCHANGE,
    add_instrument_item_to_group,
    get_item_kind,
    parse_exchange_code,
    parse_value_cell,
    set_group_tree_item,
)
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
from ui.screens.welcome_screen import WelcomeScreen
from ui.ui_state import PlanningState, WizardState
from ui.dialogs import show_error, show_warning

D = Decimal

NON_INVESTABLE_BUCKET_TITLE = "Non-investable holdings (excluded from strategy)"
MIN_INVESTABLE_AMOUNT_ILS = D("100")

class MainWindow(MainWindowActionsMixin, MainWindowWizardMixin, QMainWindow):
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

        # Screens
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
        """Ensure background FX thread is stopped before window teardown.

        If the fetch thread does not stop within the shutdown wait window,
        close is ignored and the user is asked to retry shortly.
        """
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

    # -------------------------
    # Screen 1 (Welcome)
    # -------------------------

    def _init_welcome_screen(self) -> None:
        """Build startup welcome screen and connect startup actions."""
        self.screen_welcome = WelcomeScreen(app_version=APP_VERSION, parent=self)
        self.screen_welcome.open_last_btn.clicked.connect(self._on_welcome_open_last_clicked)
        self.screen_welcome.load_different_btn.clicked.connect(self._on_welcome_load_different_clicked)
        self.screen_welcome.start_new_btn.clicked.connect(self._on_welcome_start_new_clicked)
        self.screen_welcome.quit_btn.clicked.connect(self._quit_app)

    def _show_welcome_screen_on_startup(self) -> None:
        """Show startup welcome screen and refresh remembered-file state."""
        self.setWindowTitle(self._base_window_title)
        self._refresh_welcome_last_portfolio_ui()
        self.stack.setCurrentWidget(self.screen_welcome)
        if self.screen_welcome.open_last_btn.isEnabled():
            self.screen_welcome.open_last_btn.setFocus()
        else:
            self.screen_welcome.load_different_btn.setFocus()

    def _enter_main_screen(self) -> None:
        """Switch from startup screen to main editor with current file context."""
        self._update_file_context_ui()
        self.stack.setCurrentWidget(self.screen_main)

    @staticmethod
    def _truncate_middle(text: str, *, max_chars: int = 96) -> str:
        """Return middle-truncated text for constrained path labels."""
        if len(text) <= max_chars:
            return text
        part = max((max_chars - 3) // 2, 1)
        return f"{text[:part]}...{text[-part:]}"

    def _refresh_welcome_last_portfolio_ui(self) -> None:
        """Refresh last-portfolio button state and path text on welcome screen."""
        remembered_path = self.session.get_remembered_portfolio_path()

        if remembered_path is None:
            self.screen_welcome.set_last_portfolio_status(
                button_enabled=False,
                path_text="No recent portfolio",
                path_tooltip="",
                missing_path=False,
            )
            return

        full_path = str(remembered_path)
        display_path = self._truncate_middle(full_path)
        path_exists = remembered_path.exists()
        if path_exists:
            path_text = f"Last portfolio: {display_path}"
        else:
            path_text = f"Last portfolio: {display_path} (Not found)"

        self.screen_welcome.set_last_portfolio_status(
            button_enabled=path_exists,
            path_text=path_text,
            path_tooltip=full_path,
            missing_path=not path_exists,
        )

    def _on_welcome_open_last_clicked(self) -> None:
        """Open remembered portfolio when available and enter main screen."""
        remembered_path = self.session.get_remembered_portfolio_path()
        if remembered_path is None or not remembered_path.exists():
            self._refresh_welcome_last_portfolio_ui()
            return
        if not self._open_portfolio_from_path(remembered_path):
            self._refresh_welcome_last_portfolio_ui()
            return
        self._enter_main_screen()

    def _on_welcome_load_different_clicked(self) -> None:
        """Open picker flow from welcome screen and enter main on success."""
        if not self._open_portfolio_from_picker():
            return
        self._enter_main_screen()

    def _on_welcome_start_new_clicked(self) -> None:
        """Initialize default portfolio from welcome and enter main editor."""
        self._load_or_init()
        self._enter_main_screen()

    # -------------------------
    # Screen 2 (Main)
    # -------------------------

    def _init_main_screen(self) -> None:
        """Build screen-2 widget and wire all main-editor signal handlers."""
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

    def _on_item_changed_guard_and_recalc(self, item: QTreeWidgetItem, column: int) -> None:
        if self._suppress_item_changed:
            return

        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TICKER.value:
            # Keep a defensive normalization pass at model-update time.
            # The ticker delegate prevents invalid keystrokes in normal editing,
            # but programmatic edits/pastes/tests can still bypass that path.
            raw_ticker = item.text(column)
            sanitized_ticker = "".join(ch for ch in raw_ticker if ch.isascii() and ch.isalnum())
            normalized_ticker = sanitized_ticker.upper()
            if normalized_ticker != raw_ticker:
                self._suppress_item_changed = True
                try:
                    item.setText(column, normalized_ticker)
                finally:
                    self._suppress_item_changed = False

        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.EXCHANGE.value:
            raw = parse_exchange_code(item.text(column)) or DEFAULT_EXCHANGE.value
            item.setText(column, raw)
            item.setData(0, ROLE_EXCHANGE, raw)

        # Only business-rule validate relevant cells
        if get_item_kind(item) == RowKind.GROUP and column == Col.TARGET_PCT.value:
            if not self._validate_target_pct_cell_or_revert(item):
                self._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            if not self._validate_instrument_target_pct_cell_or_revert(item):
                self._refresh_data()
                return
        if get_item_kind(item) == RowKind.INSTRUMENT and column == Col.QUANTITY.value:
            if not self._validate_instrument_quantity_cell_or_revert(item):
                self._refresh_data()
                return

        self._refresh_data()

    def _add_asset_group(self) -> None:
        # gid = _new_id("grp")
        gitem = QTreeWidgetItem(self.tree)

        set_group_tree_item(gitem, "New Asset Group", 0)

        self.tree.expandAll()
        self._refresh_data()

    def _add_instrument(self) -> None:
        sel = self.tree.currentItem()
        if sel is None:
            show_warning(self, "Add instrument", "Select a group (or an instrument under a group) first.")
            return

        # If instrument selected, use its parent group
        parent = sel.parent() or sel

        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            default_in_group_pct = ""
        else:
            default_in_group_pct = "100" if parent.childCount() == 0 else "0"

        add_instrument_item_to_group(parent, "0000000", "New Instrument", 0, "1", default_in_group_pct)

        self.tree.expandAll()
        self._refresh_data()

    def _delete_selected_row(self) -> None:
        sel = self.tree.currentItem()
        if sel is None:
            return

        if get_item_kind(sel) == RowKind.NON_INVESTABLE_BUCKET:
            show_warning(self, "Not allowed", "The non-investable bucket cannot be deleted.")
            return

        parent = sel.parent()
        if parent is None:
            idx = self.tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)
        self._refresh_data()

    def _load_or_init(self) -> None:
        """Load default portfolio into main editor as a new unsaved document."""
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

    def _on_main_refresh_requested(self, *_args: object) -> None:
        """Single dispatcher for main-screen refresh requests from signals."""
        self._refresh_data()

    def _refresh_data(self) -> None:
        """Refresh all derived main-screen values and visuals from current inputs."""
        self._refresh_total_portfolio()
        self._update_investable_balance_visual_state()
        self._update_future_tax_visual_state()
        self._recalc_totals_and_pcts()

    def _refresh_total_portfolio(self) -> None:
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
            self.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: {total}")
        except Exception:
            self.total_label.setText(f"Total portfolio {BASE_CURRENCY_SUFFIX}: -")

    def _on_invest_clicked(self) -> None:
        self._run_planning(mode=PlanningMode.INVEST)

    def _on_rebalance_clicked(self) -> None:
        self._run_planning(mode=PlanningMode.REBALANCE)

    def _on_main_quit_clicked(self) -> None:
        if not self._confirm_continue_with_unsaved_changes("quitting"):
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _run_planning(self, mode: PlanningMode) -> None:
        """
        Execute planning flow from current UI state and open summary screen.

        ``mode`` selects either invest-only or invest-and-rebalance strategy.
        If prior wizard FX fetch cleanup is still in progress, this flow aborts
        with an explicit "please wait" error to avoid overlapping runs.
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

    # -------------------------
    # Screen 3 (Summary)
    # -------------------------

    def _init_summary_screen(self) -> None:
        """Build screen-3 widget and wire summary navigation actions."""
        self.screen_summary = SummaryScreen(self)
        self.summary_text = self.screen_summary.summary_text
        self.screen_summary.quit_btn.clicked.connect(self._quit_app)
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
        if not self.planning_state.plan_steps:
            # Nothing to do -> go back to main
            self.stack.setCurrentWidget(self.screen_main)
            return
        self._show_current_wizard_step()
        self.stack.setCurrentWidget(self.screen_wizard)
        self._prepare_wizard_fx_rate_cache()

    def _summary_back(self) -> None:
        """Return from summary screen to main editor."""
        self.stack.setCurrentWidget(self.screen_main)

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

        self.investable_balance_label.setText(f"Investable balance {BASE_CURRENCY_SUFFIX}: {investable_balance}")
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

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """
        Start guarded cell editing on double-click for editable cells only.

        Previous text is captured for possible validation-driven revert.
        """
        kind = get_item_kind(item)

        if kind == RowKind.INSTRUMENT and column == Col.TARGET_PCT.value:
            parent = item.parent()
            if parent is not None and get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
                return
        if kind == RowKind.INSTRUMENT and column == Col.EXCHANGE.value:
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

    def _validate_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
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

    def _validate_instrument_target_pct_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
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

    def _validate_instrument_quantity_cell_or_revert(self, item: QTreeWidgetItem) -> bool:
        """
        Validate instrument quantity cell.

        Allowed values are non-negative integers.
        Empty input is normalized immediately to ``0``.
        """
        col = Col.QUANTITY.value
        raw = item.text(col).strip()
        prev = item.data(col, ROLE_PREV_TEXT)

        if raw == "":
            self._suppress_item_changed = True
            try:
                item.setText(col, "0")
            finally:
                self._suppress_item_changed = False
            return True
        if not raw.isdigit():
            self._warn_and_revert(
                item,
                col,
                raw,
                prev,
                "Quantity must be a non-negative integer.",
            )
            return False
        return True

    def _warn_and_revert(self, item: QTreeWidgetItem, col: int, bad: str, prev: str | None, msg: str) -> None:
        """Show validation warning and revert edited cell to previous value."""
        self._suppress_item_changed = True
        try:
            show_warning(self, "Invalid input", f"{msg}\n\nYou entered: {bad}\nReverting to previous value: {prev}")
            item.setText(col, prev if prev is not None else "")
        finally:
            self._suppress_item_changed = False
