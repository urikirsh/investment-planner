from __future__ import annotations

"""Main-editor screen setup and row-level editing actions."""

from typing import cast

from PySide6.QtWidgets import QApplication, QLineEdit, QTreeWidget, QTreeWidgetItem, QWidget

from portfolio_core.planning_types import PlanningMode
from portfolio_core.portfolio_session import PortfolioSession
from portfolio_core.use_cases import create_new_default_document
from ui.controllers.protocols import MainWindowMainEditorDependencies
from ui.dialogs import show_warning
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.screens.main_editor_screen import MainEditorScreen
from ui.ui_types import RowKind
from ui.ui_utils import add_instrument_item_to_group, get_item_kind, set_group_tree_item


class MainWindowMainEditorMixin:
    """Mixin containing main-editor screen wiring and direct row actions."""

    session: PortfolioSession
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str
    screen_main: QWidget

    def _init_main_screen(self) -> None:
        """Build screen-2 widget and wire all main-editor signal handlers."""
        deps = cast(MainWindowMainEditorDependencies, self)
        self.screen_main = MainEditorScreen(cast(QWidget, self))
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
        self.screen_main.save_btn.clicked.connect(deps._on_save_clicked)
        self.screen_main.save_as_btn.clicked.connect(deps._on_save_as_clicked)
        self.screen_main.open_btn.clicked.connect(deps._on_open_clicked)
        self.screen_main.new_btn.clicked.connect(deps._on_new_clicked)

        self.tree.items_reordered.connect(self._on_main_refresh_requested)
        self.cash_value_edit.textChanged.connect(self._on_main_refresh_requested)
        self.cash_reserve_edit.textChanged.connect(self._on_main_refresh_requested)
        self.future_tax_edit.textChanged.connect(self._on_main_refresh_requested)
        self.future_tax_edit.editingFinished.connect(deps._normalize_future_tax_input)

    def _add_asset_group(self) -> None:
        gitem = QTreeWidgetItem(self.tree)
        set_group_tree_item(gitem, "New Asset Group", 0)
        self.tree.expandAll()
        cast(MainWindowMainEditorDependencies, self)._refresh_data()

    def _add_instrument(self) -> None:
        sel = self.tree.currentItem()
        if sel is None:
            show_warning(
                cast(QWidget, self),
                "Add instrument",
                "Select a group (or an instrument under a group) first.",
            )
            return

        parent = sel.parent() or sel
        if get_item_kind(parent) == RowKind.NON_INVESTABLE_BUCKET:
            default_in_group_pct = ""
        else:
            default_in_group_pct = "100" if parent.childCount() == 0 else "0"

        add_instrument_item_to_group(parent, "0000000", "New Instrument", 0, "1", default_in_group_pct)
        self.tree.expandAll()
        cast(MainWindowMainEditorDependencies, self)._refresh_data()

    def _delete_selected_row(self) -> None:
        sel = self.tree.currentItem()
        if sel is None:
            return

        if get_item_kind(sel) == RowKind.NON_INVESTABLE_BUCKET:
            show_warning(cast(QWidget, self), "Not allowed", "The non-investable bucket cannot be deleted.")
            return

        parent = sel.parent()
        if parent is None:
            idx = self.tree.indexOfTopLevelItem(sel)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)
        else:
            parent.removeChild(sel)
        cast(MainWindowMainEditorDependencies, self)._refresh_data()

    def _load_default_document(self) -> None:
        """Load default portfolio into main editor as a new unsaved document."""
        deps = cast(MainWindowMainEditorDependencies, self)
        p = create_new_default_document(self.session)
        populate_main_editor_from_portfolio(
            tree=self.tree,
            cash_value_edit=self.cash_value_edit,
            cash_reserve_edit=self.cash_reserve_edit,
            future_tax_edit=self.future_tax_edit,
            portfolio=p,
            non_investable_bucket_id=self._non_investable_bucket_id,
            non_investable_bucket_title=self._non_investable_bucket_title,
            on_future_tax_value_set=deps._update_future_tax_visual_state,
        )
        deps._refresh_data()
        deps._update_file_context_ui()

    def _on_main_refresh_requested(self, *_args: object) -> None:
        """Single dispatcher for main-screen refresh requests from signals."""
        cast(MainWindowMainEditorDependencies, self)._refresh_data()

    def _on_invest_clicked(self) -> None:
        cast(MainWindowMainEditorDependencies, self)._run_planning(mode=PlanningMode.INVEST)

    def _on_rebalance_clicked(self) -> None:
        cast(MainWindowMainEditorDependencies, self)._run_planning(mode=PlanningMode.REBALANCE)

    def _on_main_quit_clicked(self) -> None:
        deps = cast(MainWindowMainEditorDependencies, self)
        if not deps._confirm_continue_with_unsaved_changes("quitting"):
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()
