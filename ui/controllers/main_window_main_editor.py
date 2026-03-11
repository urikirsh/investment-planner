from __future__ import annotations

"""Main-editor screen setup and row-level editing actions."""

from typing import cast

from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QWidget

from portfolio_core.planning_types import PlanningMode
from portfolio_core.use_cases import create_new_default_document
from ui.controllers.protocols import MainWindowMainEditorHost
from ui.dialogs import show_warning
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.screens.main_editor_screen import MainEditorScreen
from ui.ui_types import RowKind
from ui.ui_utils import add_instrument_item_to_group, get_item_kind, set_group_tree_item


class MainWindowMainEditorController:
    """Controller for main-editor screen wiring and direct row actions."""

    def __init__(self, host: MainWindowMainEditorHost) -> None:
        self._host = host

    def _host_widget(self) -> QWidget:
        """Return host cast to QWidget for dialog parenting/screen construction."""
        return cast(QWidget, self._host)

    @staticmethod
    def _determine_default_in_group_pct(parent: QTreeWidgetItem) -> str:
        """Return default in-group target for newly added instrument rows."""
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            return ""
        return "100" if parent.childCount() == 0 else "0"

    def init_screen(self) -> None:
        """Build main-editor widget and wire all signal handlers."""
        host = self._host
        host.screen_main = MainEditorScreen(self._host_widget())
        host.tree = host.screen_main.tree
        host.cash_value_edit = host.screen_main.cash_value_edit
        host.cash_reserve_edit = host.screen_main.cash_reserve_edit
        host.future_tax_edit = host.screen_main.future_tax_edit
        host.investable_balance_label = host.screen_main.investable_balance_label
        host.total_label = host.screen_main.total_label

        host.screen_main.add_group_btn.clicked.connect(self.add_asset_group)
        host.screen_main.add_instrument_btn.clicked.connect(self.add_instrument)
        host.screen_main.delete_row_btn.clicked.connect(self.delete_selected_row)
        host.screen_main.quit_btn.clicked.connect(self.on_quit_clicked)
        host.screen_main.invest_btn.clicked.connect(self.on_invest_clicked)
        host.screen_main.rebalance_btn.clicked.connect(self.on_rebalance_clicked)
        host.screen_main.save_btn.clicked.connect(host._on_save_clicked)
        host.screen_main.save_as_btn.clicked.connect(host._on_save_as_clicked)
        host.screen_main.open_btn.clicked.connect(host._on_open_clicked)
        host.screen_main.new_btn.clicked.connect(host._on_new_clicked)

        host.tree.items_reordered.connect(self.on_refresh_requested)
        host.cash_value_edit.textChanged.connect(self.on_refresh_requested)
        host.cash_reserve_edit.textChanged.connect(self.on_refresh_requested)
        host.future_tax_edit.textChanged.connect(self.on_refresh_requested)
        host.future_tax_edit.editingFinished.connect(host._normalize_future_tax_input)

    def add_asset_group(self) -> None:
        """Append a new editable asset-group row and refresh derived values."""
        host = self._host
        new_item = QTreeWidgetItem(host.tree)
        set_group_tree_item(new_item, "New Asset Group", 0)
        host.tree.expandAll()
        host._refresh_data()

    def add_instrument(self) -> None:
        """Add a new instrument under selected group (or selected instrument's parent)."""
        host = self._host
        sel = host.tree.currentItem()
        if sel is None:
            show_warning(
                self._host_widget(),
                "Add instrument",
                "Select a group (or an instrument under a group) first.",
            )
            return

        parent = sel.parent() or sel
        default_in_group_pct = self._determine_default_in_group_pct(parent)
        add_instrument_item_to_group(parent, "0000000", "New Instrument", 0, "1", default_in_group_pct)
        host.tree.expandAll()
        host._refresh_data()

    def delete_selected_row(self) -> None:
        """Delete selected group/instrument row unless it is the protected bucket."""
        host = self._host
        sel = host.tree.currentItem()
        if sel is None:
            return

        if get_item_kind(sel) == RowKind.NON_INVESTABLE_BUCKET:
            show_warning(self._host_widget(), "Not allowed", "The non-investable bucket cannot be deleted.")
            return

        parent = sel.parent()
        if parent is None:
            idx = host.tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                host.tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)
        host._refresh_data()

    def load_default_document(self) -> None:
        """Load default portfolio into main editor as a new unsaved document."""
        host = self._host
        p = create_new_default_document(host.session)
        populate_main_editor_from_portfolio(
            tree=host.tree,
            cash_value_edit=host.cash_value_edit,
            cash_reserve_edit=host.cash_reserve_edit,
            future_tax_edit=host.future_tax_edit,
            portfolio=p,
            non_investable_bucket_id=host._non_investable_bucket_id,
            non_investable_bucket_title=host._non_investable_bucket_title,
            on_future_tax_value_set=host._update_future_tax_visual_state,
        )
        host._refresh_data()
        host._update_file_context_ui()

    def on_refresh_requested(self, *_args: object) -> None:
        """Single dispatcher for main-screen refresh requests from signals."""
        self._host._refresh_data()

    def on_invest_clicked(self) -> None:
        """Start invest planning from current main-editor state."""
        self._host._run_planning(mode=PlanningMode.INVEST)

    def on_rebalance_clicked(self) -> None:
        """Start rebalance planning from current main-editor state."""
        self._host._run_planning(mode=PlanningMode.REBALANCE)

    def on_quit_clicked(self) -> None:
        """Quit app after unsaved-changes confirmation when needed."""
        host = self._host
        if not host._confirm_continue_with_unsaved_changes("quitting"):
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()
